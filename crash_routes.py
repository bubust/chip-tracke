"""
crash_routes.py — 📉 大跌買點（PLAN-BEST2 第 6 節：大跌時買大盤 0050／權值股）

今天的數值（第 t 天收盤後）：
  加權 vs 60 日最高收盤（跌幅）、加權 vs 60 日線（乖離）、股票池裡「負乖離抄底」（季線乖離 ≤ −20%）家數（最近一次掃描 S_BIAS）
深跌門檻（研究裡 5 年只出現 4～5 次、每次之後 60～120 天買 0050／台積電大多賺；事件太少 → 只當參考、不做顯著性宣稱）：
  T1 加權 ≤ 60 日最高 × 0.85、T2 加權 ≤ 60 日線 × 0.90、T3 負乖離家數 ≥ 100
任一條「今天第一次成立」→ Telegram（同一天只推一次）
"""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
HERE = os.path.dirname(os.path.abspath(__file__))
SUMMARY = os.path.join(HERE, "research", "best2", "results", "crash_site.json")
_TW = timezone(timedelta(hours=8))
DEEP = {"T1_dd15": "加權比 60 日最高跌 ≥ 15%", "T2_ma60_10": "加權低於 60 日線 ≥ 10%", "T3_bias100": "負乖離抄底 ≥ 100 檔"}


def _bias_count():
    try:
        from yahoo_price import get_scan_results
        return len(get_scan_results().get("S_BIAS") or [])
    except Exception:
        return None


def today_state() -> dict:
    import best_strategy as bs
    tx = bs.taiex_series()
    if tx is None or len(tx) < 61:
        return {"error": "加權指數資料不夠"}
    s = tx.sort_index()
    last, d = float(s.iloc[-1]), str(s.index[-1])
    prev = s.iloc[:-1]
    hi60, ma60 = float(s.iloc[-60:].max()), float(s.iloc[-60:].mean())
    hi60p, ma60p = float(prev.iloc[-60:].max()), float(prev.iloc[-60:].mean())
    dd, bias = last / hi60 - 1, last / ma60 - 1
    dd_p, bias_p = float(prev.iloc[-1]) / hi60p - 1, float(prev.iloc[-1]) / ma60p - 1
    nb = _bias_count()
    trig = {"T1_dd15": dd <= -0.15, "T2_ma60_10": bias <= -0.10, "T3_bias100": (nb or 0) >= 100}
    was = {"T1_dd15": dd_p <= -0.15, "T2_ma60_10": bias_p <= -0.10}
    first = [k for k, v in trig.items() if v and not was.get(k, False)]
    # 中度（研究裡跟隨機差不多）只顯示
    mild = {"T1_dd8": dd <= -0.08, "T1_dd10": dd <= -0.10, "T2_ma60_5": bias <= -0.05, "T2_ma60_8": bias <= -0.08, "T3_bias50": (nb or 0) >= 50}
    return {"date": d, "taiex": round(last, 2), "hi60": round(hi60, 2), "ma60": round(ma60, 2), "dd": round(dd, 4), "bias": round(bias, 4),
            "bias_count": nb, "deep": trig, "deep_first_today": first, "mild": mild, "labels": DEEP}


def _history():
    try:
        with open(SUMMARY, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


@router.get("/api/crash/today")
def api_crash_today():
    return JSONResponse(content={"today": today_state(), "history": _history()})


def push_crash(dry: bool = False) -> dict:
    st = today_state()
    if st.get("error") or not st.get("deep_first_today"):
        return {"sent": False, "state": st}
    from best_routes import _sent, _log, _get_conn
    key = f"crash:{st['date']}"
    if _sent(key):
        return {"sent": False, "dup": True}
    c = _get_conn()                                   # 同一波大跌只推一次：14 天內推過就不再推
    since = (datetime.now() - timedelta(days=14)).isoformat()
    recent = c.execute("SELECT 1 FROM push_log WHERE stock_id='S_BEST' AND signal_title LIKE 'crash:%' AND ok=1 AND pushed_at >= ? LIMIT 1", (since,)).fetchone()
    c.close()
    if recent:
        return {"sent": False, "dup": True, "note": "14 天內推過"}
    hist = _history() or {}
    lines = [f"📉 <b>大跌買點觸發</b>　{st['date'][4:6]}/{st['date'][6:]}",
             f"加權 {st['taiex']}（比 60 日最高 {st['dd'] * 100:+.1f}%、比 60 日線 {st['bias'] * 100:+.1f}%）；負乖離抄底 {st['bias_count'] or '—'} 檔",
             "成立：" + "、".join(DEEP[k] for k in st["deep_first_today"])]
    if hist.get("text"):
        lines.append(html.escape(hist["text"]))
    lines.append("— 牆泥袋溥的戰術中心")
    text = "\n".join(lines)
    if dry:
        return {"sent": False, "text": text}
    import asyncio
    from server import tg_send
    ok = asyncio.run(tg_send(text))
    _log(key, ok)
    return {"sent": ok}


STRAT = os.path.join(HERE, "research", "best2", "results", "strategy_site.json")


@router.get("/api/best2/strategies")
def api_best2_strategies():
    """策略篩選每個策略的「5 年回測：原本 vs 改良」（research/best2/report2.py 產生）"""
    try:
        with open(STRAT, encoding="utf-8") as fh:
            return JSONResponse(content=json.load(fh))
    except Exception:
        return JSONResponse(content={})
