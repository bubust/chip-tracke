"""
margin_maint.py — 個股融資維持率（估計）＋「融資維持率偏低」清單（S_MAINT_LOW，2026-11-01 新增）

交易所只公布整體市場的融資維持率，個股沒有 → 用每天的融資買進／餘額＋股價估「平均融資成本」：
  - 每天融資買進（扣掉資券互抵＝當日沖銷）× 當天均價（(高＋低＋收)÷3）加進成本
  - 減少的張數（賣出＋現償，一樣扣掉資券互抵）照當時的平均成本扣掉（前日餘額＋買進－賣出－現償＝今日餘額，官方資料逐檔成立）
  - 平均融資成本＝成本 ÷ 餘額；估計維持率＝現在股價 ÷（平均成本 × 融資成數）
    融資成數：上市 6 成（買進當下 166.7%）、上櫃 5 成（200%）；跌破 130% 券商追繳，補不出來就斷頭
  - 回補第一天的餘額不知道成本 → 用那天的均價；「可信度」＝現在的餘額裡、回補期間買進的比例
  - 收盤一天變動超過 14%（漲跌幅 10%）＝減資／分割／大額除權 → 成本跟著股價等比例調整（維持率不因此跳動）
資料：TWSE rwd MI_MARGN（selectType=ALL）＋櫃買 margin/balance → chip_data/course.db margin_flow（chip_course.refresh
每天順便存、backfill 回補半年）；股價：price_daily（官方日行情，不還原）
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Optional

MAINT_DAYS = 130          # 用幾個交易日估（約半年）
KEEP_DAYS = 400           # margin_flow 留多久（日曆天）
LEV = {"twse": 0.6, "tpex": 0.5}
MKT_NAME = {"twse": "上市", "tpex": "上櫃"}
CALL = 130.0              # 追繳線（%）
JUMP = 0.14               # 收盤一天變動超過這個＝減資／分割／除權
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
        got = {(d, m) for d, m in c.execute("SELECT date, market FROM fetch_log WHERE kind='mflow'")}
        todo = [d for d in days if (d.isoformat(), "twse") not in got or (d.isoformat(), "tpex") not in got]
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
                            c.execute("INSERT OR REPLACE INTO fetch_log VALUES ('mflow',?,?,0)", (ds, mk))
                            stat["closed"] += 1
                        else:
                            stat["failed"] += 1
                    c.commit()
                    time.sleep(pause)
        c.execute("DELETE FROM margin_flow WHERE date<?", ((today - timedelta(days=KEEP_DAYS)).isoformat(),))
        c.commit()
        stat["days"] = c.execute("SELECT COUNT(DISTINCT date) FROM margin_flow").fetchone()[0]
    return stat


def need_backfill(min_days: int = 100) -> bool:
    import chip_course as CC
    try:
        with closing(CC.get_conn()) as c:
            return c.execute("SELECT COUNT(DISTINCT date) FROM margin_flow").fetchone()[0] < min_days
    except Exception:       # noqa: BLE001
        return False


# ── 估計 ─────────────────────────────────────────────────────────────────────

def estimate(rows: list, px: dict) -> Optional[dict]:
    """rows：[(YYYY-MM-DD, 買進, 賣出, 現償, 前日餘額, 今日餘額, 資券互抵)]（張，舊→新）；px：{YYYY-MM-DD: (高, 低, 收)}
    → {bal, avg（平均融資成本，每股）, close（最後一天有價的收盤）, conf（可信度 0～1）, chg5, adj（調整次數）, days, date}"""
    cost = bal = init = last_c = None
    adj, hist, last_d = 0, [], None
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
            continue
        jumped = cl is not None and last_c and abs(cl / last_c - 1) > JUMP
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
            last_c, last_d = cl, d
        hist.append(bl)
    if cost is None or not bal or bal <= 0 or not last_c or cost <= 0:
        return None
    return {"bal": bal, "avg": cost / bal, "close": last_c, "conf": max(0.0, 1 - init / bal),
            "chg5": bal - hist[-6] if len(hist) >= 6 else None, "adj": adj, "days": len(hist), "date": rows[-1][0],
            "px_date": last_d}


def maint_of(close: float, avg: float, mkt: str) -> float:
    return close / (avg * LEV.get(mkt, 0.6)) * 100


def _price_rows(pc, sid: str, lo8: str) -> dict:
    out = {}
    for d, h, l_, c_ in pc.execute("SELECT date, high, low, close FROM price_daily WHERE stock_id=? AND date>=? ORDER BY date",
                                   (sid, lo8)):
        d = str(d).replace("-", "")
        if len(d) == 8:
            out[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = (h, l_, c_)
    return out


def compute(min_lots: float = 0, n_days: int = MAINT_DAYS) -> tuple:
    """→ (最新融資資料日, {sid: estimate(...) ＋ name、mkt})；只算最新餘額 ≥ min_lots 的（股價一檔一檔查，記憶體小）"""
    import chip_course as CC
    import price_cache as PC
    with closing(CC.get_conn()) as c:
        dates = [r[0] for r in c.execute("SELECT DISTINCT date FROM margin_flow ORDER BY date DESC LIMIT ?", (n_days,))]
        if not dates:
            return None, {}
        lo, asof = dates[-1], dates[0]
        keep = {r[0] for r in c.execute("SELECT sid FROM margin_flow WHERE date=? AND bal>=?", (asof, min_lots))}
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
    return asof, out


# ── 清單 ─────────────────────────────────────────────────────────────────────

def screen(get_df, names: Optional[dict], p: dict) -> list:
    """S_MAINT_LOW：估計維持率 ≤ max_maint（預設 140%）、融資餘額 ≥ min_lots、可信度 ≥ min_conf；維持率由低到高"""
    import chip_course as CC
    mx, lots = float(p.get("max_maint", 140)), float(p.get("min_lots", 300))
    conf, mp = float(p.get("min_conf", 50)) / 100, float(p.get("min_price", 10))
    asof, est = compute(min_lots=lots)
    out = []
    for sid, e in est.items():
        if e["conf"] < conf or maint_of(e["close"], e["avg"], e["mkt"]) > mx * 1.15:   # 先粗篩（股價還要用最新的）
            continue
        df = get_df(sid)
        close = float(df.iloc[-1]["close"]) if df is not None and len(df) else e["close"]
        m = maint_of(close, e["avg"], e["mkt"])
        if m > mx or close < mp:
            continue
        call = CALL / 100 * e["avg"] * LEV[e["mkt"]]
        nm = {sid: e["name"], **(names or {})}
        row = CC._row(sid, df, nm, "S_MAINT_LOW") if df is not None and len(df) else {
            "stock_id": sid, "name": nm.get(sid, ""), "close": round(close, 2), "change_pct": None, "volume": None, "bb_score": None,
            "strategy": "S_MAINT_LOW", "last_date": e["px_date"]}
        row.update(maint=round(m, 1), margin_lots=round(e["bal"]), margin_cost=round(e["avg"], 2), call_price=round(call, 2),
                   to_call_pct=round((call / close - 1) * 100, 1), margin_chg5=None if e["chg5"] is None else round(e["chg5"]),
                   conf=round(e["conf"] * 100), market=MKT_NAME[e["mkt"]], margin_date=asof,
                   note=(f"估計維持率 {m:.0f}%：融資平均成本約 {e['avg']:.2f} 元（{MKT_NAME[e['mkt']]}融資 {LEV[e['mkt']] * 10:.0f} 成），"
                         f"{'已跌破' if close <= call else f'跌到 {call:.2f} 元（再跌 {(1 - call / close) * 100:.1f}%）跌破'} 130% 追繳線。"
                         "融資多、維持率低＝再跌會有追繳／斷頭賣壓；等融資大減（斷頭出清）、止跌後再看"
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
