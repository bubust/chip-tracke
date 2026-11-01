"""
margin_maint.py — 個股融資維持率（估計）＋「融資維持率偏低」清單（S_MAINT_LOW，2026-11-01 新增）

交易所只公布整體市場的融資維持率，個股沒有 → 用每天的融資買進／餘額＋股價估「平均融資成本」：
  - 每天融資買進（扣掉資券互抵＝當日沖銷）× 當天均價（(高＋低＋收)÷3）加進成本
  - 減少的張數（賣出＋現償，一樣扣掉資券互抵）照當時的平均成本扣掉（前日餘額＋買進－賣出－現償＝今日餘額，官方資料逐檔成立）
  - 平均融資成本＝成本 ÷ 餘額；估計維持率＝現在股價 ÷（平均成本 × 融資成數 × 校正）
    融資成數上市、上櫃都是 6 成（買進當下 166.7%；2026-11 用官方「融資買進金額 ÷ 買進張數×股價」實測：上市 0.574、上櫃 0.556，
    少數股票被調降成數才略低於 0.6，上櫃不是網路上常說的 5 成）；跌破 130% 券商追繳，補不出來就斷頭
  - 校正：各檔估出來的融資金額加總，用官方融資金額總數等比例校正（實測估計平均比官方多 12%，10/30 上市 ×0.885、上櫃 ×0.878），
    讓個股加起來＝官方總數（大盤融資維持率），每天重算
  - 回補第一天的餘額不知道成本 → 用那天的均價；「可信度」＝現在的餘額裡、回補期間買進的比例
  - 收盤一天變動超過 14%（漲跌幅 10%）＝減資／分割／大額除權 → 成本跟著股價等比例調整（維持率不因此跳動）
資料：TWSE rwd MI_MARGN（selectType=ALL）＋櫃買 margin/balance → chip_data/course.db margin_flow（chip_course.refresh
每天順便存、backfill 回補半年）；股價：price_daily（官方日行情，不還原）
大盤融資維持率（不是估的）：官方融資金額總數（證交所「信用交易統計」、櫃買 summary「融資金(仟元)」）→ margin_total；
  維持率＝Σ（各檔融資餘額 × 收盤）÷ 官方融資金額
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Optional

MAINT_DAYS = 130          # 用幾個交易日估（約半年）
KEEP_DAYS = 400           # margin_flow 留多久（日曆天）
LEV = {"twse": 0.6, "tpex": 0.6}
CALIB_RANGE = (0.7, 1.2)  # 校正倍數超出這個範圍（資料缺很多）就不校正
MKT_NAME = {"twse": "上市", "tpex": "上櫃"}
CALL = 130.0              # 追繳線（%）
LIMIT = 0.10              # 漲跌幅；隔 n 天的收盤變動超過 (1±10%)^n 再多 3% ＝減資／分割／除權（中間缺價的日子也算進去）
_TW = timezone(timedelta(hours=8))

PARAMS = [
    {"key": "max_maint", "label": "估計維持率上限%（≤）", "type": "number", "default": 140, "min": 100, "max": 200, "step": 5},
    {"key": "min_lots", "label": "融資餘額張數（≥）", "type": "number", "default": 300, "min": 0, "max": 50000, "step": 100},
    {"key": "min_conf", "label": "可信度%（≥，現在的融資裡回補期間買進的比例）", "type": "number", "default": 50, "min": 0, "max": 100,
     "step": 10},
]


# ── 存檔／回補 ───────────────────────────────────────────────────────────────

def save_flows(c, ds: str, flows: dict) -> dict:
    """fetch_margin_day(..., flows) 抓到的一天 → margin_flow；回應的日期跟 ds 對不上（休市時可能回別天）不存。回 {市場: 筆數}"""
    n = {}
    for mk in ("twse", "tpex"):
        rows = flows.get(mk) or {}
        ok = bool(rows) and flows.get(mk + "_date") == ds
        if ok:
            c.executemany("INSERT OR REPLACE INTO margin_flow VALUES (?,?,?,?,?,?,?,?,?,?)",
                          [(ds, sid, mk, *v) for sid, v in rows.items()])
            c.execute("INSERT OR REPLACE INTO fetch_log VALUES ('mflow',?,?,?)", (ds, mk, len(rows)))
        n[mk] = len(rows) if ok else 0
        tot = flows.get(mk + "_total")
        if tot and flows.get(mk + "_date") == ds:
            c.execute("INSERT OR REPLACE INTO margin_total VALUES (?,?,?,?,?,?,?,?)",
                      (ds, mk, tot["bal_lots"], tot["amt_k"], tot.get("buy_lots"), tot.get("buy_amt_k"), tot.get("sell_amt_k"),
                       tot.get("repay_amt_k")))
            c.execute("INSERT OR REPLACE INTO fetch_log VALUES ('mtotal',?,?,1)", (ds, mk))
    return n


def backfill(n_days: int = MAINT_DAYS, budget_s: Optional[float] = None, progress=None, pause: float = 0.6) -> dict:
    """補最近 n_days 個交易日的融資流量（上市＋上櫃，一天 2 個請求，第一次約 5～7 分鐘）；抓過的、休市的日期跳過。
    休市＝有回應但沒有資料（或櫃買回別天）→ 記 0 筆不再抓；連線失敗不記，下次再試。今天不補（晚上 9 點多才公布，refresh 會抓）"""
    import chip_course as CC
    from cb.fetcher import client, fetch_margin_day
    t0 = time.time()
    today = datetime.now(_TW).date()
    days = [d for d in CC._weekdays_back(n_days + 15) if d < today]
    stat = {"fetched": 0, "closed": 0, "failed": 0, "left": 0}
    with closing(CC.get_conn()) as c:
        got = {(k, d, m) for k, d, m in c.execute("SELECT kind, date, market FROM fetch_log WHERE kind IN ('mflow','mtotal')")}
        todo = [d for d in days if any((k, d.isoformat(), m) not in got for k in ("mflow", "mtotal") for m in ("twse", "tpex"))]
        if todo:
            with client() as cl:
                for k, d in enumerate(todo, 1):
                    if budget_s and time.time() - t0 > budget_s:
                        stat["left"] = len(todo) - k + 1
                        break
                    if progress:
                        progress(f"融資維持率回補 {d}", k, len(todo))
                    ds, flows = d.isoformat(), {}
                    fetch_margin_day(cl, d, flows)
                    n = save_flows(c, ds, flows)
                    for mk in ("twse", "tpex"):
                        if n[mk]:
                            stat["fetched"] += 1
                        elif mk + "_date" in flows:            # 有回應、沒資料＝休市
                            c.executemany("INSERT OR REPLACE INTO fetch_log VALUES (?,?,?,0)", [(k, ds, mk) for k in ("mflow", "mtotal")])
                            stat["closed"] += 1
                        else:
                            stat["failed"] += 1
                    c.commit()
                    time.sleep(pause)
        c.execute("DELETE FROM margin_flow WHERE date<?", ((today - timedelta(days=KEEP_DAYS)).isoformat(),))
        c.commit()
        stat["days"] = c.execute("SELECT COUNT(DISTINCT date) FROM margin_flow").fetchone()[0]
    if stat["fetched"]:                                     # 補到舊日子（例：官方總數）→ 同一個資料日的估計／校正要重算
        _ALL.clear()
        _CACHE.clear()
        _MKT_CACHE.clear()
    return stat


def need_backfill(min_days: int = 100) -> bool:
    import chip_course as CC
    try:
        with closing(CC.get_conn()) as c:
            return c.execute("SELECT COUNT(DISTINCT date) FROM margin_flow").fetchone()[0] < min_days
    except Exception:       # noqa: BLE001
        return False


# ── 估計 ─────────────────────────────────────────────────────────────────────

def estimate(rows: list, px: dict, track: bool = False) -> Optional[dict]:
    """rows：[(YYYY-MM-DD, 買進, 賣出, 現償, 前日餘額, 今日餘額, 資券互抵)]（張，舊→新）；px：{YYYY-MM-DD: (高, 低, 收)}
    → {bal, avg（平均融資成本，每股）, close（最後一天有價的收盤）, conf（可信度 0～1）, chg5, adj（調整次數）, days, date}
    track：另外回 series＝[(日期, 平均成本, 收盤, 餘額)]（每天，畫維持率走勢用）"""
    cost = bal = init = last_c = None
    adj, hist, last_d, gap, series = 0, [], None, 0, []
    for d, b, s, r, pv, bl, off in rows:
        p = px.get(d)
        cl = typ = None
        if p and p[2]:
            cl = float(p[2])
            typ = (float(p[0]) + float(p[1]) + cl) / 3 if p[0] and p[1] else cl
        if cost is None:                                    # 第一天：成本不知道 → 用那天的均價
            if typ is None:
                continue
            cost, bal, init, last_c = bl * typ, bl, bl, cl
            hist.append(bl)
            last_d = d
            if track:
                series.append((d, cost / bl if bl > 0 else None, cl, bl))
            continue
        gap += 1                                            # 距離上一個有價的日子幾天（中間缺價的也算）
        jumped = cl is not None and last_c and not ((1 - LIMIT) ** gap * 0.97 <= cl / last_c <= (1 + LIMIT) ** gap * 1.03)
        if jumped:                                          # 減資／分割／除權：成本跟著股價等比例調整
            cost *= cl / last_c
            adj += 1
        if abs(pv - bal) > 0.5:                             # 前日餘額跟昨天的今日餘額對不上（漏抓的日子、減資換股）
            if pv > bal and not jumped and bal > 0:
                cost += (pv - bal) * (typ or cost / bal)
            elif bal > 0:
                cost *= pv / bal
                init *= pv / bal
            else:
                cost, init = pv * (typ or last_c or 0), 0.0
            bal = pv
        buy, red = max(b - off, 0.0), max(s - off, 0.0) + r
        unit = typ if typ is not None else (cost / bal if bal > 0 else 0.0)
        pool = bal + buy
        cost += buy * unit
        if pool > 0:
            keep = max(pool - red, 0.0) / pool
            cost *= keep
            init *= keep
            if pool - red > 0.5 and abs(pool - red - bl) > 0.5:     # 理論上不會（官方等式成立），保險：照比例對齊
                cost *= bl / (pool - red)
                init *= bl / (pool - red)
        bal = bl
        if cl is not None:
            last_c, last_d, gap = cl, d, 0
        hist.append(bl)
        if track:
            series.append((d, cost / bal if bal > 0 else None, cl, bl))
    if cost is None or not bal or bal <= 0 or not last_c or cost <= 0:
        return None
    out = {"bal": bal, "avg": cost / bal, "close": last_c, "conf": max(0.0, 1 - init / bal),
           "chg5": bal - hist[-6] if len(hist) >= 6 else None, "adj": adj, "days": len(hist), "date": rows[-1][0],
           "px_date": last_d}
    if track:
        out["series"] = series
    return out


def maint_of(close: float, avg: float, mkt: str, k: float = 1.0) -> float:
    """k：官方融資金額校正倍數（calib）"""
    return close / (avg * LEV.get(mkt, 0.6) * k) * 100


def _price_rows(pc, sid: str, lo8: str) -> dict:
    out = {}
    for d, h, l_, c_ in pc.execute("SELECT date, high, low, close FROM price_daily WHERE stock_id=? AND date>=? ORDER BY date",
                                   (sid, lo8)):
        d = str(d).replace("-", "")
        if len(d) == 8:
            out[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = (h, l_, c_)
    return out


_ALL: dict = {}            # {"v": (資料日, n, {sid: 估計}, {市場: 校正})}：全部股票（同一個資料日只算一次，約 2 秒；整組一次換，多執行緒安全）


def compute(min_lots: float = 0, n_days: int = MAINT_DAYS) -> tuple:
    """→ (最新融資資料日, {sid: estimate(...) ＋ name、mkt})，只回最新餘額 ≥ min_lots 的；全部股票算一次快取（校正要用全部）"""
    asof, est = _compute_all(n_days)
    return asof, {s: e for s, e in est.items() if e["bal"] >= min_lots}


def calib(asof: Optional[str] = None) -> dict:
    """{市場: 校正倍數}＝官方融資金額 ÷ Σ（估計平均成本 × 成數 × 張）；資料日對不上或算不出來回 {}（＝不校正）"""
    a, _ = _compute_all()
    v = _ALL.get("v")
    return dict(v[3]) if a and v and v[0] == a and (asof is None or a == asof) else {}


def _calib_from(est: dict, asof: str) -> dict:
    """少數沒估到的股票照張數比例放大；估到的張數不到官方的 9 成、或倍數超出 CALIB_RANGE → 1（不校正）"""
    import chip_course as CC
    with closing(CC.get_conn()) as c:
        tot = {m: (bl, amt) for m, bl, amt in c.execute("SELECT mkt, bal_lots, amt_k FROM margin_total WHERE date=?", (asof,))}
    out = {}
    for m in ("twse", "tpex"):
        s_amt = sum(e["avg"] * LEV[m] * e["bal"] for e in est.values() if e["mkt"] == m)     # 元 × 張 ＝ 仟元
        lots = sum(e["bal"] for e in est.values() if e["mkt"] == m)
        bl, amt = tot.get(m, (None, None))
        k = amt / (s_amt * bl / lots) if amt and bl and s_amt and lots / bl >= 0.9 else None
        out[m] = round(k, 4) if k and CALIB_RANGE[0] <= k <= CALIB_RANGE[1] else 1.0
    return out


def _compute_all(n_days: int = MAINT_DAYS) -> tuple:
    import chip_course as CC
    import price_cache as PC
    with closing(CC.get_conn()) as c:
        dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM margin_flow ORDER BY date DESC LIMIT ?", (n_days,))]
        if not dates:
            return None, {}
        lo, asof = dates[-1], dates[0]
        v = _ALL.get("v")
        if v and v[0] == asof and v[1] == n_days:
            return asof, v[2]
        keep = {r[0] for r in c.execute("SELECT sid FROM margin_flow WHERE date=? AND bal>0", (asof,))}
        series: dict = {}
        meta: dict = {}
        for d, sid, mk, nm, b, s, r, pv, bl, off in c.execute(
                "SELECT date, sid, mkt, name, buy, sell, repay, prev, bal, off FROM margin_flow WHERE date>=? ORDER BY sid, date", (lo,)):
            if sid in keep:
                series.setdefault(sid, []).append((d, b, s, r, pv, bl, off))
                meta[sid] = (mk, nm)
    out = {}
    with closing(sqlite3.connect(str(PC.DB_PATH), timeout=10.0)) as pc:
        lo8 = (datetime.strptime(lo, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y%m%d")
        for sid, rows in series.items():
            if rows[-1][0] != asof:
                continue
            e = estimate(rows, _price_rows(pc, sid, lo8))
            if e:
                e["mkt"], e["name"] = meta[sid]
                out[sid] = e
    _ALL["v"] = (asof, n_days, out, _calib_from(out, asof))
    return asof, out


# ── 清單 ─────────────────────────────────────────────────────────────────────

def screen(get_df, names: Optional[dict], p: dict) -> list:
    """S_MAINT_LOW：估計維持率 ≤ max_maint（預設 140%）、融資餘額 ≥ min_lots、可信度 ≥ min_conf；維持率由低到高"""
    import chip_course as CC
    mx, lots = float(p.get("max_maint", 140)), float(p.get("min_lots", 300))
    conf, mp = float(p.get("min_conf", 50)) / 100, float(p.get("min_price", 10))
    asof, est = compute(min_lots=lots)
    ks = calib(asof)
    out = []
    for sid, e in est.items():
        k = ks.get(e["mkt"], 1.0)
        if e["conf"] < conf or maint_of(e["close"], e["avg"], e["mkt"], k) > mx * 1.15:   # 先粗篩（股價還要用最新的）
            continue
        df = get_df(sid)
        close = float(df.iloc[-1]["close"]) if df is not None and len(df) else e["close"]
        m = maint_of(close, e["avg"], e["mkt"], k)
        if m > mx or close < mp:
            continue
        call = CALL / 100 * e["avg"] * LEV[e["mkt"]] * k
        nm = {sid: e["name"], **(names or {})}
        row = CC._row(sid, df, nm, "S_MAINT_LOW") if df is not None and len(df) else {
            "stock_id": sid, "name": nm.get(sid, ""), "close": round(close, 2), "change_pct": None, "volume": None, "bb_score": None,
            "strategy": "S_MAINT_LOW", "last_date": e["px_date"]}
        row.update(maint=round(m, 1), margin_lots=round(e["bal"]), margin_cost=round(e["avg"], 2), call_price=round(call, 2),
                   to_call_pct=round((call / close - 1) * 100, 1), margin_chg5=None if e["chg5"] is None else round(e["chg5"]),
                   conf=round(e["conf"] * 100), market=MKT_NAME[e["mkt"]], margin_date=asof, calib=k,
                   note=(f"估計維持率 {m:.0f}%：融資平均成本約 {e['avg']:.2f} 元（融資 6 成、用官方融資金額校正 ×{k:.3f}），"
                         + ("已跌破 130% 追繳線（這種多半已經有人被追繳／斷頭，剩下的融資成本其實比估的低、實際維持率會高一些）。"
                            if close <= call else f"跌到 {call:.2f} 元（再跌 {(1 - call / close) * 100:.1f}%）跌破 130% 追繳線。")
                         + "融資多、維持率低＝再跌會有追繳／斷頭賣壓；等融資大減（斷頭出清）、止跌後再看"
                         + ("；期間有減資／分割／除權，成本已等比例調整" if e["adj"] else "")))
        out.append(row)
    out.sort(key=lambda r: r["maint"])
    return out


def backfill_and_publish(params: Optional[dict] = None) -> dict:
    """啟動時融資流量不夠 → 回補半年，補完馬上算清單放進策略篩選（不用等 18:00 掃描）"""
    stat = backfill()
    try:
        import chip_course as CC
        import yahoo_price as YP
        from price_cache import get_stock_ohlcv

        def get_df(sid):
            df = get_stock_ohlcv(sid, days=120)
            return df if df is not None and not df.empty else None
        p = {**{x["key"]: x["default"] for x in CC.CHIP_PARAMS["S_MAINT_LOW"]}, **(params or {})}
        rows = screen(get_df, None, p)
        YP.set_strategy_results("S_MAINT_LOW", rows)
        stat["rows"] = len(rows)
    except Exception as e:      # noqa: BLE001
        stat["error"] = f"{type(e).__name__}: {e}"[:200]
    return stat


# ── 單檔／多檔（觀察清單、深度分析、K 線圖）───────────────────────────────────

_CACHE: dict = {}          # (最新融資資料日, sid) → estimate（含 series）


def latest_date() -> Optional[str]:
    import chip_course as CC
    try:
        with closing(CC.get_conn()) as c:
            return c.execute("SELECT MAX(date) FROM margin_flow").fetchone()[0]
    except Exception:       # noqa: BLE001
        return None


def _load(sids: list) -> tuple:
    """→ (最新融資資料日, {sid: estimate(track=True) ＋ mkt、name})；同一個資料日算過的直接用"""
    import chip_course as CC
    import price_cache as PC
    asof = latest_date()
    if not asof:
        return None, {}
    need = [s for s in dict.fromkeys(sids) if (asof, s) not in _CACHE]
    if need:
        with closing(CC.get_conn()) as c:
            dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM margin_flow ORDER BY date DESC LIMIT ?", (MAINT_DAYS,))]
            lo = dates[-1]
            series: dict = {}
            meta: dict = {}
            for k in range(0, len(need), 400):
                part = need[k:k + 400]
                for d, sid, mk, nm, b, s, r, pv, bl, off in c.execute(
                        "SELECT date, sid, mkt, name, buy, sell, repay, prev, bal, off FROM margin_flow "
                        f"WHERE date>=? AND sid IN ({','.join('?' * len(part))}) ORDER BY sid, date", (lo, *part)):
                    series.setdefault(sid, []).append((d, b, s, r, pv, bl, off))
                    meta[sid] = (mk, nm)
        lo8 = (datetime.strptime(lo, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y%m%d")
        with closing(sqlite3.connect(str(PC.DB_PATH), timeout=10.0)) as pc:
            for sid in need:
                rows = series.get(sid)
                e = estimate(rows, _price_rows(pc, sid, lo8), track=True) if rows and rows[-1][0] == asof else None
                if e:
                    e["mkt"], e["name"] = meta[sid]
                _CACHE[(asof, sid)] = e
        if len(_CACHE) > 6000:                              # 換資料日後舊的清掉
            for k in [k for k in _CACHE if k[0] != asof]:
                _CACHE.pop(k, None)
    return asof, {s: _CACHE.get((asof, s)) for s in sids}


def _view(e: dict, close: Optional[float], asof: str, k: float = 1.0) -> dict:
    close = float(close) if close else e["close"]
    lev = LEV.get(e["mkt"], 0.6)
    call = CALL / 100 * e["avg"] * lev * k
    m = maint_of(close, e["avg"], e["mkt"], k)
    level = "call" if m < CALL else "low" if m < 140 else "warn" if m < 150 else "ok"
    return {"maint": round(m, 1), "cost": round(e["avg"], 2), "call_price": round(call, 2), "to_call_pct": round((call / close - 1) * 100, 1),
            "bal": round(e["bal"]), "chg5": None if e["chg5"] is None else round(e["chg5"]), "conf": round(e["conf"] * 100),
            "market": MKT_NAME.get(e["mkt"], ""), "lev": lev, "calib": k, "date": asof, "close": round(close, 2), "level": level,
            "adj": e["adj"]}


def estimate_many(sids: list, closes: Optional[dict] = None) -> dict:
    """觀察清單：{sid: 估計維持率…}（股價用傳進來的現價，沒有就用融資資料日的收盤）；沒融資資料的不回"""
    asof, est = _load(list(sids))
    ks = calib(asof) if any(est.values()) else {}
    return {s: _view(e, (closes or {}).get(s), asof, ks.get(e["mkt"], 1.0)) for s, e in est.items() if e}


def estimate_one(sid: str, close: Optional[float] = None, n_hist: int = 60) -> Optional[dict]:
    """深度分析／K 線圖：估計維持率＋近 n_hist 天每天的維持率、平均成本"""
    asof, est = _load([sid])
    e = est.get(sid)
    if not e:
        return None
    k = calib(asof).get(e["mkt"], 1.0)
    out = _view(e, close, asof, k)
    lev = LEV.get(e["mkt"], 0.6) * k                        # 走勢用今天的校正倍數（每天差不多，實測 0.85～0.89）
    out["series"] = [{"date": d, "maint": round(cl / (avg * lev) * 100, 1), "cost": round(avg, 2), "close": cl, "bal": round(bl)}
                     for d, avg, cl, bl in e.get("series", [])[-n_hist:] if avg and cl]
    return out


# ── 大盤融資維持率（官方融資金額，不是估的）─────────────────────────────────────

_MKT_CACHE: dict = {}


def market_maint(n: int = 60) -> dict:
    """{ok, date, twse, tpex, all（%）, amt_yi（官方融資金額，億）, cover（有收盤的融資張數比例）, series}
    維持率＝Σ（融資餘額 × 收盤）÷ 官方融資金額；少數沒收盤的股票照有收盤的比例放大"""
    import chip_course as CC
    import price_cache as PC
    try:
        with closing(CC.get_conn()) as c:
            dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM margin_total ORDER BY date DESC LIMIT ?", (n,))]
            if not dates:
                return {"ok": False, "note": "官方融資金額還沒抓到（網站重開後會回補）"}
            key = (dates[0], n)
            hit = _MKT_CACHE.get("v")
            if hit and hit[0] == key:
                return hit[1]
            tot = {(d, m): (bl, amt) for d, m, bl, amt in c.execute(
                "SELECT date, mkt, bal_lots, amt_k FROM margin_total WHERE date>=?", (dates[-1],))}
            c.execute("ATTACH DATABASE ? AS px", (str(PC.DB_PATH),))
            mv = {(d, m): (v, lots) for d, m, v, lots in c.execute(
                "SELECT f.date, f.mkt, SUM(f.bal * p.close), SUM(f.bal) FROM margin_flow f "
                "JOIN px.price_daily p ON p.stock_id=f.sid AND p.date=REPLACE(f.date, '-', '') "
                "WHERE f.date>=? AND p.close>0 GROUP BY f.date, f.mkt", (dates[-1],))}
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "note": f"大盤融資維持率計算失敗：{type(e).__name__}"}
    series = []
    for d in sorted(dates):
        row, a_mv, a_amt, cov = {"date": d}, 0.0, 0.0, []
        for m in ("twse", "tpex"):
            t, x = tot.get((d, m)), mv.get((d, m))
            if not t or not x or not t[0] or not t[1] or not x[1]:
                continue
            ratio = x[1] / t[0]                             # 有收盤的融資張數 ÷ 官方融資張數
            if ratio < 0.8:
                continue
            v = x[0] / ratio
            row[m] = round(v / t[1] * 100, 1)               # 張 × 元 ＝ 仟元
            a_mv, a_amt = a_mv + v, a_amt + t[1]
            cov.append(ratio)
        if "twse" in row and "tpex" in row:
            row["all"] = round(a_mv / a_amt * 100, 1)
            row["amt_yi"] = round(a_amt / 1e5, 1)
            row["cover"] = round(min(cov), 3)
            series.append(row)
    if not series:
        return {"ok": False, "note": "融資股票的收盤還不夠"}
    last = series[-1]
    out = {"ok": True, **last, "series": series,
           "chg5": round(last["all"] - series[-6]["all"], 1) if len(series) >= 6 else None,
           "low60": min(r["all"] for r in series)}
    _MKT_CACHE["v"] = (key, out)
    return out
