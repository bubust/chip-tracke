"""盤中假跌破（B72，PLAN-B72 D；B91 改 13:15＋日線多頭結構＋大盤盤面）：全市場「🪤 假跌破買進」S_FBD 用即時價算，09:10～13:15 每 5 分鐘。
- 每天第一次跑：price_cache 每檔最近 130 根（到昨天）→ 候選＝昨天收盤 < 昨天 MA10、前 20 日均量 ≥ min_vol_lots、收盤 > min_price
- 每次：鉅亨即時報價補今天那根 → scanner.screen_sfbd（同一份函式、使用者 ⚙️ 參數）
  盤中今天的量還沒滿 → 傳進去的今天量＝max(目前累計量, 前 20 日均量（不含今天）)，「今天量 ≥ min_vol_lots」和
  「跌破那天量 ≤ 20 日均量×倍數」才不會被半天的量拉低
- 每檔成立的另外算日線結構（tail_market.struct_check：低不破低、高過高；今天那根＝到現在的即時開高低收）
- 新出現、而且結構合格的合併一則 Telegram（同一檔一天一次，push_log key fbdlive:{日}:{代號}；推失敗下次再推）；結構不合格的不推
- 13:15（13:15～13:25 第一次跑到；B91 用戶從 13:10 改）：抓加權 13:15 盤面（MIS → 鉅亨）→ tail_market 特徵＋研究判斷，
  發「13:15 還成立」清單＝計入（結構合格）＋一行不計入（結構不合格）＋早上出現過、現在不成立的；
  全部（含不合格、帶 struct_ok）加進 🎯 尾盤追蹤，13:15 算的結構／大盤存進去就固定
- B92（用戶：「這個時間，假跌破跟雙 MACD 多跟 W 底再攻擊一併通知，有重疊多策略的特別標注」）：13:15 那一次改抓全市場即時價，
  另外跑 📈 雙MACD多（S1）、📈 W底再攻擊（S2）（scanner 同一份函式、使用者 ⚙️ 參數；歷史跟 18:00 掃描一樣每檔最近 520 根，
  分批讀、算完就丟，避免 512MB 機器記憶體不夠），合併成同一則；同一檔中兩招以上＝⭐ 多策略重疊，放最上面、清單裡也標 ⭐
收盤確認以 18:00 全市場掃描為準。"""
import html
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
TW = timezone(timedelta(hours=8))
START, FINAL, FINAL_END = 910, 1315, 1325
HIST_BARS = 130
MAX_LINES = 40
MAX_NG = 30               # 不計入那一行最多列幾檔
EXTRA = (("S1", "📈", "雙MACD多"), ("S2", "📈", "W底再攻擊"))   # B92 13:15 一併通知的策略（scanner.PRICE_STRATEGY_FNS）
EXTRA_BARS = 520          # 跟 18:00 掃描一樣（get_stock_ohlcv days=520）：大 MACD(108,216,18) 才算得準
EXTRA_CHUNK = 50          # 一次讀幾檔的歷史（512MB 機器：分批讀、算完就丟；全市場 1,900 檔×520 根實測 7 秒、多吃約 30MB）
TG_MAX = 3800             # Telegram 一則最多 4096 字，留一點空間
_STATE = {"day": None, "hist": {}, "names": {}, "cands": 0, "checked": None, "sec": None,
          "hits": {}, "seen": {}, "final": False, "error": None, "mkt": None, "extra": None}
_LOCK = threading.Lock()


# ── 推播紀錄（tracker DB 的 push_log，跟其他盤中推播同一張表）──────────────────────
def _conn():
    from chip_tracker_v2 import DB_PATH
    c = sqlite3.connect(str(DB_PATH), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _sent(key: str) -> bool:
    c = _conn()
    try:
        r = c.execute("SELECT 1 FROM push_log WHERE stock_id='FBDLIVE' AND signal_title=? AND ok=1 LIMIT 1", (key,)).fetchone()
    finally:
        c.close()
    return r is not None


def _log(keys: list, ok: bool) -> None:
    c = _conn()
    try:
        now = datetime.now(TW).isoformat()
        c.executemany("INSERT INTO push_log (stock_id, signal_emoji, signal_title, pushed_at, ok) VALUES (?,?,?,?,?)",
                      [("FBDLIVE", "🪤", k, now, 1 if ok else 0) for k in keys])
        c.commit()
    finally:
        c.close()


def _send(text: str) -> bool:
    import asyncio
    try:
        from server import tg_send
        return bool(asyncio.run(tg_send(text)))
    except Exception as e:                       # 推播失敗不影響排程；記 ok=0，下次再推
        log.warning(f"[fbd-live] Telegram: {e}")
        return False


# ── 資料 ────────────────────────────────────────────────────────────────────
def _params() -> dict:
    try:
        from server import _load_strategy_params
        return _load_strategy_params().get("S_FBD", {}) or {}
    except Exception:
        return {}


def _params_all() -> dict:
    try:
        from server import _load_strategy_params
        return _load_strategy_params() or {}
    except Exception:
        return {}


def _send_long(send, text: str) -> bool:
    """超過 Telegram 長度就照行切成幾則（每則都要成功才算成功）"""
    if len(text) <= TG_MAX:
        return bool(send(text))
    parts, cur = [], ""
    for ln in text.split("\n"):
        if cur and len(cur) + len(ln) + 1 > TG_MAX:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n{ln}" if cur else ln[:TG_MAX]
    if cur:
        parts.append(cur)
    ok = True
    for part in parts:
        ok = bool(send(part)) and ok
    return ok


def _load_hist(day: str) -> tuple:
    """price_cache 全部股票最近 HIST_BARS 根（日期 < day）＋股名：一個 SQL"""
    from price_cache import DB_PATH
    from yahoo_price import get_stock_list
    st = get_stock_list()
    names = dict(zip(st["stock_id"].astype(str), st["stock_name"]))
    since = (datetime.strptime(day, "%Y%m%d") - timedelta(days=HIST_BARS * 2)).strftime("%Y%m%d")
    c = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        df = pd.read_sql_query("SELECT stock_id, date, open, high, low, close, volume FROM price_daily "
                               "WHERE date >= ? AND date < ? ORDER BY stock_id, date", c, params=(since, day))
    finally:
        c.close()
    df["stock_id"] = df["stock_id"].astype(str)
    df = df[df["stock_id"].isin(names)]
    for k in ("open", "high", "low", "close", "volume"):
        df[k] = pd.to_numeric(df[k], errors="coerce")
    hist = {sid: g.tail(HIST_BARS).drop(columns="stock_id").reset_index(drop=True) for sid, g in df.groupby("stock_id")}
    return hist, names


def candidates(hist: dict, params: dict) -> dict:
    """昨天收盤 < 昨天 MA10、前 20 日均量 ≥ min_vol_lots、收盤 > min_price、至少 65 根 → {sid: (df, 前20日均量)}"""
    min_price = float(params.get("min_price", 10))
    min_vol = float(params.get("min_vol_lots", 300))
    out = {}
    for sid, df in hist.items():
        if len(df) < 65:
            continue
        c = df["close"].to_numpy(float)
        v = df["volume"].to_numpy(float)
        if np.isnan(c[-10:]).any() or np.isnan(v[-20:]).any():
            continue
        avg20 = float(v[-20:].mean())
        if c[-1] <= min_price or avg20 < min_vol or not c[-1] < c[-10:].mean():
            continue
        out[sid] = (df, avg20)
    return out


def _prepare(day: str, load_hist_fn=None, params=None) -> None:
    hist, names = (load_hist_fn or _load_hist)(day)
    cands = candidates(hist, params if params is not None else _params())
    _STATE.update(day=day, hist=cands, names=names, cands=len(cands), checked=None, sec=None,
                  hits={}, seen={}, final=False, error=None, mkt=None, extra=None)
    log.info(f"[fbd-live] {day} 候選 {len(cands)} 檔（全部 {len(hist)} 檔）")


def _quotes(ids: list, day: str, quotes_fn=None) -> dict:
    """鉅亨即時報價（只收日期＝今天）；整體或大部分失敗 → 缺的那些重試一次"""
    if quotes_fn is None:
        from yahoo_price import _prefetch_rt_for_scan as quotes_fn
    try:
        q = dict(quotes_fn(ids, day) or {})
    except Exception as e:
        log.warning(f"[fbd-live] 報價失敗：{e}")
        q = {}
    miss = [s for s in ids if s not in q]
    if miss and len(miss) > len(ids) * 0.4:
        time.sleep(2)
        try:
            q.update(quotes_fn(miss, day) or {})
        except Exception as e:
            log.warning(f"[fbd-live] 報價重試失敗：{e}")
    return q


def _hit_info(sid: str, df: pd.DataFrame, name: str) -> dict:
    import tail_market as TM
    c = df["close"].to_numpy(float)
    ma10 = pd.Series(c).rolling(10).mean().to_numpy()
    broke = None
    for i in range(2, min(6, len(c))):                     # 跟 screen_sfbd 一樣往回找收盤 < MA10 的那天
        if c[-i] < ma10[-i]:
            broke = str(df["date"].iloc[-i])
            break
    prev = c[-2]
    try:
        st = TM.struct_check(df["high"].to_numpy(float), df["low"].to_numpy(float))
    except Exception as e:                                  # noqa: BLE001  算不出來＝不合格
        st = {"ok": False, "reason": f"結構算不出來：{type(e).__name__}"}
    return {"stock_id": sid, "name": name, "price": round(float(c[-1]), 2),
            "chg": round(float(c[-1] / prev - 1), 4) if prev else None,
            "ma10": round(float(ma10[-1]), 2), "broke_date": broke, "struct_ok": bool(st.get("ok")), "struct": st}


def scan_now(day: str, quotes_fn=None, params=None, quotes: dict | None = None) -> dict:
    """用現在的即時價跑一次 S_FBD → {sid: info}（quotes：13:15 已經抓好的全市場報價）"""
    from scanner import screen_sfbd
    p = dict(params if params is not None else _params())
    ids = list(_STATE["hist"])
    q = quotes if quotes is not None else _quotes(ids, day, quotes_fn)
    if not q:
        return {}
    hits = {}
    for sid in ids:
        b = q.get(sid)
        if not b:
            continue
        hist, avg20 = _STATE["hist"][sid]
        row = {"date": day, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
               "volume": max(float(b.get("volume") or 0), avg20)}
        df = pd.concat([hist, pd.DataFrame([row])], ignore_index=True)
        name = _STATE["names"].get(sid, "")
        try:
            if screen_sfbd({sid: df}, {sid: name}, params=p):
                hits[sid] = _hit_info(sid, df, name)
        except Exception as e:
            log.warning(f"[fbd-live] {sid}: {e}")
    return hits


# ── 13:15 一併通知：雙MACD多、W底再攻擊（B92）──────────────────────────────────
def _iter_hist(day: str, sids: list, bars: int = EXTRA_BARS, chunk: int = EXTRA_CHUNK):
    """price_cache 每檔最近 bars 根（日期 < day）；一次讀 chunk 檔、一檔一檔交出去（不一次全部放記憶體）"""
    from price_cache import DB_PATH
    since = (datetime.strptime(day, "%Y%m%d") - timedelta(days=int(bars * 1.55))).strftime("%Y%m%d")
    c = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        for i in range(0, len(sids), chunk):
            part = list(sids[i:i + chunk])
            df = pd.read_sql_query("SELECT stock_id, date, open, high, low, close, volume FROM price_daily "
                                   f"WHERE stock_id IN ({','.join('?' * len(part))}) AND date >= ? AND date < ? "
                                   "ORDER BY stock_id, date", c, params=(*part, since, day))
            df["stock_id"] = df["stock_id"].astype(str)
            for k in ("open", "high", "low", "close", "volume"):
                df[k] = pd.to_numeric(df[k], errors="coerce")
            for sid, g in df.groupby("stock_id"):
                yield sid, g.tail(bars).drop(columns="stock_id").reset_index(drop=True)
            del df
    finally:
        c.close()


def scan_extra(day: str, quotes: dict, names: dict, params_all: dict | None = None, hist_iter=None) -> dict:
    """13:15 即時價跑 EXTRA 的策略 → {"S1": {sid: info}, "S2": {...}}；歷史 + 今天那根（量＝到 13:15 的累計量）"""
    from scanner import PRICE_STRATEGY_FNS
    pa = params_all if params_all is not None else _params_all()
    out = {k: {} for k, _, _ in EXTRA}
    ids = sorted(sid for sid in quotes if sid in names)
    for sid, hist in (hist_iter or _iter_hist)(day, ids):
        b = quotes.get(sid)
        if not b or hist is None or len(hist) < 61:
            continue
        row = {"date": day, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
               "volume": float(b.get("volume") or 0)}
        df = pd.concat([hist, pd.DataFrame([row])], ignore_index=True)
        prev = float(hist["close"].iloc[-1])
        for key, _, _ in EXTRA:
            try:
                r = PRICE_STRATEGY_FNS[key]({sid: df}, {sid: names.get(sid, "")}, params=pa.get(key) or {})
            except Exception as e:                       # noqa: BLE001  單檔算不出來不影響別檔
                log.warning(f"[fbd-live] {key} {sid}: {e}")
                continue
            if r:
                x = r[0]
                out[key][sid] = {"stock_id": sid, "name": names.get(sid, ""), "price": round(float(b["close"]), 2),
                                 "chg": round(float(b["close"]) / prev - 1, 4) if prev and prev == prev else None,
                                 "stop": x.get("stop"), "wave_high": x.get("wave_high"), "base_days": x.get("base_days")}
    return out


def overlaps(fbd_all: list, extra: dict) -> list:
    """同一檔中兩招以上（假跌破含日線結構不合格的）→ [{stock_id, name, price, chg, tags}]，招數多的先"""
    m = {}
    for x in fbd_all:
        m.setdefault(x["stock_id"], {**x, "tags": []})["tags"].append("🪤 假跌破" + ("" if x.get("struct_ok") else "（日線結構不合格）"))
    for key, emo, nm in EXTRA:
        for sid, x in sorted((extra or {}).get(key, {}).items()):
            m.setdefault(sid, {**x, "tags": []})["tags"].append(f"{emo} {nm}")
    return sorted((v for v in m.values() if len(v["tags"]) >= 2), key=lambda v: (-len(v["tags"]), v["stock_id"]))


def _xline(x: dict, key: str, star: bool) -> str:
    chg = f"（{x['chg'] * 100:+.1f}%）" if x.get("chg") is not None else ""
    tail = f"，停損 {x['stop']}（盤整低點）" if key == "S2" and x.get("stop") is not None else ""
    return f"• {x['stock_id']} {html.escape(x['name'] or '')} {x['price']}{chg}{tail}" + ("　⭐" if star else "")


# ── 13:15 大盤盤面（B91）────────────────────────────────────────────────────
def market_snapshot(now: datetime) -> dict:
    """加權 13:15：MIS（失敗重試 1 次）→ 鉅亨；日 K、費半從 wave.db → tail_market 特徵＋研究判斷。
    回 {snap, feats, verdict, src, checked_at, error}；抓不到 snap／feats＝None（尾盤追蹤之後補算）"""
    import tail_market as TM
    out = {"snap": None, "feats": None, "verdict": TM.verdict(None), "src": "live", "checked_at": now.strftime("%H:%M"), "error": None}
    today = now.strftime("%Y-%m-%d")
    snap = None
    try:
        from wave import data as WD
        for k in range(2):
            q = WD.live_taiex()
            if q and q.get("date") == today and q.get("c"):
                snap = {"o": q["o"], "h": q["h"], "l": q["l"], "x": q["c"], "y": q.get("y"), "src": "MIS", "time": q.get("time")}
                break
            if k == 0:
                time.sleep(2)
    except Exception as e:                                  # noqa: BLE001
        out["error"] = f"MIS {type(e).__name__}"
    if snap is None:
        try:
            from wave import futdata as FD
            q = FD.fetch_cnyes_quote("TWII")
            ts = q.get("ts") if q else None
            if q and q.get("price") and (not ts or datetime.fromtimestamp(ts, TW).strftime("%Y-%m-%d") == today):
                snap = {"o": q.get("open") or q["price"], "h": q.get("high") or q["price"], "l": q.get("low") or q["price"],
                        "x": q["price"], "y": q.get("ref"), "src": "鉅亨"}
        except Exception as e:                              # noqa: BLE001
            out["error"] = ((out["error"] or "") + f" 鉅亨 {type(e).__name__}").strip()
    if snap is None:
        log.warning(f"[fbd-live] 13:15 大盤抓不到：{out['error']}")
        return out
    out["snap"] = snap
    try:
        from wave import data as WD
        tw = WD.load_idx("TWII")
        tw = tw[tw["date"] < today]
        sox = WD.load_idx("SOX")
        feats = TM.market_features(tw["h"].to_numpy(float), tw["l"].to_numpy(float), tw["c"].to_numpy(float), snap,
                                   TM.sox_change(sox["date"].tolist(), sox["c"].tolist(), today))
        out["feats"] = feats
        out["verdict"] = TM.verdict(feats)
    except Exception as e:                                  # noqa: BLE001
        out["error"] = f"大盤特徵 {type(e).__name__}: {e}"[:200]
        log.warning(f"[fbd-live] {out['error']}")
    return out


def _pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def market_lines(mkt: dict) -> list:
    """Telegram 13:15 清單的大盤：盤面一行＋研究判斷一行"""
    import tail_market as TM
    f = (mkt or {}).get("feats")
    if not f:
        return ["🌐 大盤 13:15 抓不到（之後補算）"]
    lines = ["🌐 " + html.escape(TM.describe(f))]
    v = (mkt or {}).get("verdict") or {}
    res = TM.load_research()
    rules = [r for r in res.get("rules") or [] if r.get("pass")]
    if v.get("label") in ("good", "bad") and v.get("rules"):
        r = v["rules"][0]
        o = r.get("oos") or {}
        word = "比較好 ✅" if v["label"] == "good" else "比較差 ⚠"
        lines.append(f"研究：這種盤勢過去{word}（{html.escape(str(r.get('family_name', '')))}＝{html.escape(str(r.get('bucket', '')))}："
                     f"樣本外勝率 {_pct(o.get('win'))}、每筆平均 {(o.get('mean') or 0) * 100:+.1f}%）")
    elif rules:
        lines.append("研究：今天的盤勢沒有落在比較好或比較差的格子")
    elif res:
        lines.append("研究：5 年回測沒找到明顯比較好或比較差的盤勢（大盤只當參考）")
    yr = year_line(f, res)
    if yr:
        lines.append(yr)
    return lines


def year_line(f: dict, res: dict) -> str:
    """參考（沒通過檢定）：大盤日線是這種狀態時，這招各年平均是賺還是賠（tail_research.json families.M4 的逐年，筆數 ≥ 20 的年）"""
    b = (f or {}).get("M4")
    x = ((((res or {}).get("families") or {}).get("M4") or {}).get("buckets") or {}).get(b) if b else None
    ys = [v for v in ((x or {}).get("years") or {}).values() if (v or {}).get("n", 0) >= 20]
    if len(ys) < 3:
        return ""
    neg = sum(1 for v in ys if v.get("mean", 0) < 0)
    word = f"{neg} 年平均是賠的" if neg * 2 > len(ys) else f"{len(ys) - neg} 年平均是賺的"
    return f"參考（事後統計、沒通過檢定）：大盤日線{b}時，這招過去 {len(ys)} 年有 {word}"


def _md(d):
    return f"{d[4:6]}/{d[6:8]}" if d else "—"


def _line(x: dict, tag: str = "") -> str:
    chg = f"（{x['chg'] * 100:+.1f}%）" if x.get("chg") is not None else ""
    return (f"• {x['stock_id']} {html.escape(x['name'] or '')} {x['price']}{chg} 站回 MA10 {x['ma10']}"
            f"，{_md(x.get('broke_date'))} 跌破{tag}")


def _lines(items: list, tag_fn=lambda x: "") -> list:
    out = [_line(x, tag_fn(x)) for x in items[:MAX_LINES]]
    if len(items) > MAX_LINES:
        out.append(f"…還有 {len(items) - MAX_LINES} 檔（看網站策略篩選）")
    return out


def tick(now: datetime | None = None, quotes_fn=None, load_hist_fn=None, params=None, send_fn=None,
         push: bool = True, market_fn=None, extra_hist_fn=None, params_all=None) -> dict:
    """排程每 5 分鐘呼叫；回傳這次的 {new, final, hits}"""
    now = now or datetime.now(TW)
    hm = now.hour * 100 + now.minute
    if now.weekday() >= 5 or not (START <= hm <= FINAL_END):
        return {"new": [], "final": None, "hits": 0}
    day = now.strftime("%Y%m%d")
    if not _LOCK.acquire(blocking=False):
        log.warning("[fbd-live] 上一次還沒跑完，這次跳過")
        return {"new": [], "final": None, "hits": 0}
    send = send_fn or _send
    t0 = time.time()
    try:
        if _STATE["day"] != day:
            _prepare(day, load_hist_fn, params)
        if hm >= FINAL and (_STATE["final"] or _sent(f"fbdlive:{day}:final")):
            return {"new": [], "final": None, "hits": len(_STATE["hits"])}
        q_all = None
        if hm >= FINAL:                          # B92 13:15：全市場報價一次抓（假跌破＋雙MACD多＋W底再攻擊共用）
            q_all = _quotes(sorted(_STATE["names"]), day, quotes_fn)
        hits = scan_now(day, quotes_fn, params, quotes=q_all) if _STATE["hist"] else {}
        _STATE.update(checked=now.strftime("%H:%M"), hits=hits)
        new = [x for sid, x in sorted(hits.items())
               if x.get("struct_ok") and sid not in _STATE["seen"] and not _sent(f"fbdlive:{day}:{sid}")]
        res = {"new": new, "final": None, "hits": len(hits)}
        if hm < FINAL:
            if new and push:
                txt = "\n".join([f"🪤 <b>盤中假跌破</b>　{now:%H:%M}（全市場「假跌破買進」＋日線低不破低、高過高，即時價）"] + _lines(new) +
                                ["13:15 會再發還成立的清單（含大盤盤面）；收盤確認以 18:00 掃描為準。"])
                ok = send(txt)
                _log([f"fbdlive:{day}:{x['stock_id']}" for x in new], ok)
                if ok:
                    for x in new:
                        _STATE["seen"][x["stock_id"]] = x
            elif new:
                for x in new:
                    _STATE["seen"][x["stock_id"]] = x
            return res
        # 13:15：還成立的清單（新出現的也算在裡面，不另發）；計入＝日線結構合格，不合格的一行帶過
        gone = [x for sid, x in sorted(_STATE["seen"].items()) if sid not in hits]
        allx = [x for _, x in sorted(hits.items())]
        items = [x for x in allx if x.get("struct_ok")]
        ng = [x for x in allx if not x.get("struct_ok")]
        try:
            mkt = (market_fn or market_snapshot)(now)
        except Exception as e:                   # noqa: BLE001  大盤抓不到也照發清單
            log.warning(f"[fbd-live] 大盤：{e}")
            mkt = {"snap": None, "feats": None, "verdict": {"label": "nodata", "rules": []}, "src": "live",
                   "checked_at": now.strftime("%H:%M"), "error": str(e)[:200]}
        _STATE["mkt"] = mkt
        res["final"] = {"hits": items, "ng": ng, "gone": gone, "mkt": mkt}
        try:                                     # 🎯 尾盤追蹤：13:15 成立的全部加入（含結構不合格、帶 struct_ok；同一天同一檔不重複）
            import tail_track
            tail_track.add_from_fbd(day, allx, mkt=mkt)
        except Exception as e:
            log.warning(f"[fbd-live] 尾盤追蹤加入失敗：{e}")
        extra = {k: {} for k, _, _ in EXTRA}
        try:                                     # B92 雙MACD多、W底再攻擊（失敗也照發假跌破清單）
            if q_all:
                extra = scan_extra(day, q_all, _STATE["names"], params_all, extra_hist_fn)
        except Exception as e:                   # noqa: BLE001
            log.warning(f"[fbd-live] 13:15 雙MACD多／W底：{e}")
            extra["error"] = f"{type(e).__name__}: {e}"[:200]
        ov = overlaps(allx, extra)
        star = {x["stock_id"] for x in ov}
        _STATE["extra"] = {"checked": now.strftime("%H:%M"), "overlap": ov, "error": extra.get("error"),
                           **{k: [x for _, x in sorted(extra.get(k, {}).items())] for k, _, _ in EXTRA}}
        res["final"]["extra"] = _STATE["extra"]
        n_extra = sum(len(extra.get(k, {})) for k, _, _ in EXTRA)
        if push and (allx or gone or n_extra):
            names3 = "＋".join(["假跌破"] + [nm for _, _, nm in EXTRA])
            body = [f"⏰ <b>13:15 尾盤：{names3}</b>　{now:%H:%M}"] + market_lines(mkt)
            if ov:
                body.append(f"⭐ <b>多策略重疊</b>（{len(ov)} 檔）")
                body += [f"• {x['stock_id']} {html.escape(x['name'] or '')} {x['price']}"
                         + (f"（{x['chg'] * 100:+.1f}%）" if x.get("chg") is not None else "") + "：" + "＋".join(x["tags"])
                         for x in ov[:MAX_LINES]]
            body.append(f"🪤 <b>假跌破＋日線多頭：13:15 還成立</b>（計入 {len(items)} 檔）")
            body += _lines(items, lambda x: ("　（早上已通知）" if x["stock_id"] in _STATE["seen"] else "　🆕")
                           + ("　⭐" if x["stock_id"] in star else "")) or ["• 沒有（結構合格的）"]
            if ng:
                more = f"…等 {len(ng)} 檔" if len(ng) > MAX_NG else ""
                body.append("🚫 不計入（日線不是低不破低、高過高）：" + "、".join(
                    f"{x['stock_id']} {html.escape(x['name'] or '')}" + ("⭐" if x["stock_id"] in star else "") for x in ng[:MAX_NG]) + more)
            if gone:
                body.append("⚠ 盤中出現過、現在不成立：" + "、".join(
                    f"{x['stock_id']} {html.escape(x['name'] or '')}" for x in gone[:MAX_LINES]))
            for key, emo, nm in EXTRA:
                xs = [x for _, x in sorted(extra.get(key, {}).items())]
                body.append(f"{emo} <b>{nm}</b>（{len(xs)} 檔）")
                if extra.get("error") and not xs:
                    body.append("• 這次算不出來（之後看 18:00 掃描）")
                    continue
                body += [_xline(x, key, x["stock_id"] in star) for x in xs[:MAX_LINES]] or ["• 沒有"]
                if len(xs) > MAX_LINES:
                    body.append(f"…還有 {len(xs) - MAX_LINES} 檔（看網站策略篩選）")
            body.append("現在買＝尾盤進場；13:15 的價格不是收盤價、量也還沒滿，收盤確認以 18:00 掃描為準。")
            ok = _send_long(send, "\n".join(body))
            _log([f"fbdlive:{day}:final"] + [f"fbdlive:{day}:{x['stock_id']}" for x in items if x["stock_id"] not in _STATE["seen"]], ok)
            if ok:
                _STATE["final"] = True
                for x in items:
                    _STATE["seen"].setdefault(x["stock_id"], x)
        else:
            _STATE["final"] = True
        return res
    except Exception as e:
        _STATE["error"] = f"{type(e).__name__}: {e}"
        log.warning(f"[fbd-live] {e}")
        return {"new": [], "final": None, "hits": 0}
    finally:
        _STATE["sec"] = round(time.time() - t0, 1)
        log.info(f"[fbd-live] {now:%H:%M} 候選 {_STATE['cands']}、成立 {len(_STATE['hits'])}、{_STATE['sec']} 秒")
        _LOCK.release()


def live_status() -> dict:
    return {"day": _STATE["day"], "checked": _STATE["checked"], "sec": _STATE["sec"], "candidates": _STATE["cands"],
            "hits": [x for _, x in sorted(_STATE["hits"].items())],
            "seen": [x for _, x in sorted(_STATE["seen"].items())],
            "final_sent": _STATE["final"], "error": _STATE["error"], "mkt": _STATE.get("mkt"), "extra": _STATE.get("extra"),
            "window": "09:10～13:15 每 5 分鐘；13:15 還成立的清單（日線結構合格才計入）＋雙MACD多、W底再攻擊（重疊標 ⭐）"}
