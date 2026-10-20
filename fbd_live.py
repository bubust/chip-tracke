"""盤中假跌破（B72，PLAN-B72 D）：全市場「🪤 假跌破買進」S_FBD 用即時價算，09:10～13:10 每 5 分鐘。
- 每天第一次跑：price_cache 每檔最近 130 根（到昨天）→ 候選＝昨天收盤 < 昨天 MA10、前 20 日均量 ≥ min_vol_lots、收盤 > min_price
- 每次：鉅亨即時報價補今天那根 → scanner.screen_sfbd（同一份函式、使用者 ⚙️ 參數）
  盤中今天的量還沒滿 → 傳進去的今天量＝max(目前累計量, 前 20 日均量（不含今天）)，「今天量 ≥ min_vol_lots」和
  「跌破那天量 ≤ 20 日均量×倍數」才不會被半天的量拉低
- 新出現的合併一則 Telegram（同一檔一天一次，push_log key fbdlive:{日}:{代號}；推失敗下次再推）
- 13:10（13:10～13:25 第一次跑到）：發「收盤前還成立」清單，標早上已通知／新出現，早上出現過、現在不成立的另列
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
START, FINAL, FINAL_END = 910, 1310, 1325
HIST_BARS = 130
MAX_LINES = 40
_STATE = {"day": None, "hist": {}, "names": {}, "cands": 0, "checked": None, "sec": None,
          "hits": {}, "seen": {}, "final": False, "error": None}
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
                  hits={}, seen={}, final=False, error=None)
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
    c = df["close"].to_numpy(float)
    ma10 = pd.Series(c).rolling(10).mean().to_numpy()
    broke = None
    for i in range(2, min(6, len(c))):                     # 跟 screen_sfbd 一樣往回找收盤 < MA10 的那天
        if c[-i] < ma10[-i]:
            broke = str(df["date"].iloc[-i])
            break
    prev = c[-2]
    return {"stock_id": sid, "name": name, "price": round(float(c[-1]), 2),
            "chg": round(float(c[-1] / prev - 1), 4) if prev else None,
            "ma10": round(float(ma10[-1]), 2), "broke_date": broke}


def scan_now(day: str, quotes_fn=None, params=None) -> dict:
    """用現在的即時價跑一次 S_FBD → {sid: info}"""
    from scanner import screen_sfbd
    p = dict(params if params is not None else _params())
    ids = list(_STATE["hist"])
    q = _quotes(ids, day, quotes_fn)
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
         push: bool = True) -> dict:
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
        hits = scan_now(day, quotes_fn, params) if _STATE["hist"] else {}
        _STATE.update(checked=now.strftime("%H:%M"), hits=hits)
        new = [x for sid, x in sorted(hits.items()) if sid not in _STATE["seen"] and not _sent(f"fbdlive:{day}:{sid}")]
        res = {"new": new, "final": None, "hits": len(hits)}
        if hm < FINAL:
            if new and push:
                txt = "\n".join([f"🪤 <b>盤中假跌破</b>　{now:%H:%M}（全市場「假跌破買進」，即時價）"] + _lines(new) +
                                ["13:10 會再發收盤前還成立的清單；收盤確認以 18:00 掃描為準。"])
                ok = send(txt)
                _log([f"fbdlive:{day}:{x['stock_id']}" for x in new], ok)
                if ok:
                    for x in new:
                        _STATE["seen"][x["stock_id"]] = x
            elif new:
                for x in new:
                    _STATE["seen"][x["stock_id"]] = x
            return res
        # 13:10：收盤前還成立的清單（新出現的也算在裡面，不另發）
        gone = [x for sid, x in sorted(_STATE["seen"].items()) if sid not in hits]
        items = [x for _, x in sorted(hits.items())]
        res["final"] = {"hits": items, "gone": gone}
        try:                                     # 🎯 尾盤追蹤：13:10 還成立的自動加入（同一天同一檔不重複）
            import tail_track
            tail_track.add_from_fbd(day, items)
        except Exception as e:
            log.warning(f"[fbd-live] 尾盤追蹤加入失敗：{e}")
        if push and (items or gone):
            body = [f"⏰ <b>假跌破：收盤前還成立</b>　{now:%H:%M}（{len(items)} 檔）"]
            body += _lines(items, lambda x: "　（早上已通知）" if x["stock_id"] in _STATE["seen"] else "　🆕") or ["• 沒有"]
            if gone:
                body.append("⚠ 盤中出現過、現在不成立：" + "、".join(
                    f"{x['stock_id']} {html.escape(x['name'] or '')}" for x in gone[:MAX_LINES]))
            body.append("現在買＝尾盤進場；13:10 的價格不是收盤價，收盤確認以 18:00 掃描為準。")
            ok = send("\n".join(body))
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
            "final_sent": _STATE["final"], "error": _STATE["error"],
            "window": "09:10～13:10 每 5 分鐘；13:10 收盤前清單"}
