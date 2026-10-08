"""
best_routes.py — 🔬 研究選出的方法（PLAN-BEST）的 API、觀察清單出場狀態、Telegram 推播

- GET /api/best/summary：規則、研究統計（research/best/results/summary.json）給說明頁
- GET /api/best/watch：觀察清單裡從這個方法加入（來源含 🔬 研究候選／🏆）或填了成本、而且有這個方法訊號的股票 → 交易計畫與出場狀態
- push_best_signals()：18:00 掃描後推播今天的訊號（同一天只推一次）
- push_best_exits()：持有中（有成本）出場條件成立 → 推播「明天開盤賣」（同股同天只推一次）
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

import best_strategy as bs

router = APIRouter()
log = logging.getLogger(__name__)
_TW = timezone(timedelta(hours=8))
SEARCH_BACK = 10          # 加入／填成本那天往回找最多 10 根內的訊號


def _get_conn():
    from chip_tracker_v2 import get_conn
    return get_conn()


def _ymd(s) -> str:
    d = str(s or "")[:10].replace("-", "").replace("/", "")
    return d if len(d) == 8 and d.isdigit() else ""


def from_best(note: str) -> bool:
    return bool(note) and any(t in note for t in bs.NOTE_TAGS)


def watch_plan(sid: str, note: str, added_at, cost, cost_at, df=None) -> dict | None:
    """單一觀察清單股票的交易計畫；沒有這個方法的訊號（也不是從這個方法加入）回 None"""
    if not bs.CONFIG["signal"]:
        return None
    has_cost = cost is not None and float(cost) > 0
    if not from_best(note) and not has_cost:          # 只看從這個方法加入、或填了成本的
        return None
    if df is None:
        from price_cache import get_stock_ohlcv
        df = get_stock_ohlcv(sid, days=bs.WINDOW)
    if df is None or len(df) < bs.MIN_BARS:
        return None
    A = bs._arrays(df)
    d0 = _ymd(cost_at if has_cost else added_at) or A["date"][-1]
    base = max((i for i, d in enumerate(A["date"]) if d <= d0), default=None)
    if base is None:
        return None
    # 沒成本：加入那天（晚上加入＝當天收盤）的訊號，往回找最近一次，隔天開盤進場；
    # 有成本：填成本那天＝買進日，訊號是買進日「之前」最近一次（同一串連續訊號裡持有中再出現的不算新的一筆）
    sig = None
    cache = {}
    top = base - 1 if has_cost and A["date"][base] == d0 else base
    for i in range(top, max(-1, top - SEARCH_BACK), -1):
        if bs.signal_at(A, i, cache=cache) and bs.regime_ok(A["date"][i]) is not False:
            sig = i
            break
    if sig is None:
        if not from_best(note):
            return None
        return {"stock_id": sid, "status": "no_signal", "text": "加入前 10 天內找不到這個方法的訊號"}
    if has_cost:
        entry = base if A["date"][base] == d0 else min(base + 1, A["n"] - 1)
        entry = max(entry, sig + 1) if sig + 1 < A["n"] else None
    else:
        entry = sig + 1 if sig + 1 < A["n"] else None
    p = bs.plan_for(A, sig, entry, entry_price=float(cost) if has_cost else None)
    p = {k: v for k, v in p.items() if k != "roll"}
    p["stock_id"] = sid
    p["holding"] = has_cost
    p["text"] = status_text(p)
    return p


def status_text(p: dict) -> str:
    st = p.get("status")
    ld = p.get("last_day") or ""
    md = f"{ld[4:6]}/{ld[6:]}" if ld else ""
    risk = "｜".join(x for x in (f"損 {p['stop']}" if p.get("stop") is not None else "",
                                  f"利 {p['target']}" if p.get("target") is not None else "") if x)
    if st == "signal":
        return f"🔬 明天開盤買｜{risk}｜最晚 {md}".replace("｜｜", "｜")
    if st == "holding":
        return f"🔬 抱第 {p['held_days']}/{p['max_days']} 天｜{risk}｜最晚 {md} 開盤賣".replace("｜｜", "｜")
    if st == "exit_today":
        return f"🔔 明天開盤賣（{p.get('exit_reason')}）"
    if st == "exited":
        ed = p.get("exit_date") or ""
        return f"✔ 已出場：{ed[4:6]}/{ed[6:]} {p.get('exit_reason')}（隔天開盤賣）"
    return p.get("text") or ""


def watch_plans() -> dict:
    conn = _get_conn()
    rows = conn.execute("SELECT stock_id, name, note, added_at, cost, cost_at FROM watchlist").fetchall()
    conn.close()
    out = {}
    for r in rows:
        try:
            p = watch_plan(r["stock_id"], r["note"] or "", r["added_at"], r["cost"], r["cost_at"])
        except Exception as e:
            log.warning(f"[best] watch {r['stock_id']}: {e}")
            continue
        if p:
            p["name"] = r["name"] or ""
            out[r["stock_id"]] = p
    return out


@router.get("/api/best/summary")
def api_best_summary():
    return {"key": bs.KEY, "label": bs.LABEL, "config": bs.CONFIG, "passed": bs.PASSED, "summary": bs.summary()}


@router.get("/api/best/watch")
def api_best_watch():
    from fastapi.responses import JSONResponse
    from server import _sanitize_for_json  # noqa: WPS433（server 啟動後才會呼叫）
    return JSONResponse(content=_sanitize_for_json(watch_plans()))


# ── Telegram ────────────────────────────────────────────────────────────────
def _sent(key: str) -> bool:
    conn = _get_conn()
    hit = conn.execute("SELECT 1 FROM push_log WHERE stock_id=? AND signal_title=? AND ok=1 LIMIT 1", ("S_BEST", key)).fetchone()
    conn.close()
    return hit is not None


def _log(key: str, ok: bool):
    conn = _get_conn()
    conn.execute("INSERT INTO push_log (stock_id, signal_emoji, signal_title, pushed_at, ok) VALUES (?,?,?,?,?)",
                 ("S_BEST", "🔬", key, datetime.now().isoformat(), 1 if ok else 0))
    conn.commit()
    conn.close()


def signals_message(results: list, day: str) -> str:
    sm = bs.summary()
    d = sm.get("main") or sm.get("alt") or {}
    desc = d.get("desc") or {}
    lines = [f"🔬 <b>{html.escape(bs.LABEL)}</b>　{day[4:6]}/{day[6:]} 收盤訊號 {len(results)} 檔"]
    if not bs.PASSED:
        lines.append("⚠️ 未通過全部回測關卡（帳戶回撤超標），小部位參考")
    for r in results[:25]:
        lines.append(f"• <b>{html.escape(r['stock_id'])} {html.escape(r.get('name') or '')}</b> 收 {r.get('close')}｜{html.escape(r.get('plan') or '')}")
    if len(results) > 25:
        lines.append(f"…還有 {len(results) - 25} 檔（網站策略篩選看全部）")
    if desc:
        lines.append(f"出場：{html.escape(desc.get('exit') or '')}")
    lines.append("— 牆泥袋溥的戰術中心")
    return "\n".join(lines)


def push_best_signals(dry: bool = False) -> dict:
    """18:00 掃描完成後：今天的訊號推一則（沒有訊號不推）；同一天只推一次"""
    from yahoo_price import get_scan_results
    res = [r for r in (get_scan_results().get(bs.KEY) or [])]
    day = datetime.now(_TW).strftime("%Y%m%d")
    res = [r for r in res if str(r.get("last_date") or day) == day]
    key = f"best:sig:{day}"
    if not res or _sent(key):
        return {"sent": False, "n": len(res)}
    text = signals_message(res, day)
    if dry:
        return {"sent": False, "n": len(res), "text": text}
    import asyncio
    from server import tg_send
    ok = asyncio.run(tg_send(text))
    _log(key, ok)
    return {"sent": ok, "n": len(res)}


def push_best_exits(dry: bool = False) -> list:
    """持有中（觀察清單有成本、這個方法的部位）今天收盤出場條件成立 → 推「明天開盤賣」"""
    day = datetime.now(_TW).strftime("%Y%m%d")
    out = []
    for sid, p in watch_plans().items():
        if not p.get("holding") or p.get("status") != "exit_today":
            continue
        key = f"best:exit:{sid}:{day}"
        if _sent(key):
            continue
        text = (f"🔔 <b>{html.escape(sid)} {html.escape(p.get('name') or '')}</b>　🔬 研究候選出場\n"
                f"{html.escape(p.get('exit_reason') or '')} → 明天開盤賣\n"
                f"買進 {p.get('entry_price')}，抱了 {p.get('held_days')} 天\n— 牆泥袋溥的戰術中心")
        item = {"stock_id": sid, "key": key, "text": text, "sent": False}
        if not dry:
            import asyncio
            from server import tg_send
            ok = asyncio.run(tg_send(text))
            _log(key, ok)
            item["sent"] = ok
        out.append(item)
    return out


@router.get("/api/best/push-check")
def api_best_push_check():
    """只試算、不發送：現在推播會發什麼（驗證用）"""
    return {"signals": push_best_signals(dry=True), "exits": push_best_exits(dry=True)}
