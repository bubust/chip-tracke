"""
link_routes.py — 🔗 連動／處置股 API（PLAN-LINK）
- GET  /api/link/stock/{sid}：這檔的連動股（相關係數、同產業、股價比值、偏差率、誰領先、今天漲跌）
- GET  /api/link/movers：今天各產業「先發動」＋跟進候選（10 分鐘快取）
- GET  /api/disposal/today：處置中／今天出關／快被處置＋雙刀候選（30 分鐘快取）
- GET  /api/link/research：研究結論（research/link/results/*_summary.json 的重點）
- POST /api/link/refresh：重算連動股（每天 18:00 掃描後排程也會跑）
研究（research/link）結論：跟進第二名、處置雙刀都沒有通過有效標準 → 依計畫不推 Telegram，只在網頁上顯示並標「回測沒有優勢」。
"""
from __future__ import annotations

import json
import os
import threading
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

import disposal
import linkage

router = APIRouter()
HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "research", "link", "results")
_MOVERS = {"t": 0.0, "data": None}
_LOCK = threading.Lock()                  # 重算連動股同時只跑一個（排程＋手動＋查不到時背景補算）


def _clean(o):
    from server import _sanitize_for_json   # server 啟動後才會呼叫
    return _sanitize_for_json(o)


def refresh_all():
    if not _LOCK.acquire(blocking=False):
        return {"busy": True}
    try:
        r = linkage.compute_all()
        _MOVERS["t"] = 0.0
        try:
            disposal.today(force=True)
        except Exception:
            pass
        return r
    finally:
        _LOCK.release()


@router.get("/api/link/stock/{sid}")
def api_link_stock(sid: str):
    if not (sid.isdigit() and len(sid) == 4):
        raise HTTPException(400, "股票代號要 4 碼數字")
    p = linkage.peers_of(sid)
    if p is None:
        if not _LOCK.locked():
            threading.Thread(target=refresh_all, daemon=True).start()
        return {"stock_id": sid, "peers": [], "note": "連動資料計算中或這檔不在股票池（20 日均量 ≥ 500 張、股價 ≥ 10 元），稍後再試"}
    return JSONResponse(content=_clean({"stock_id": sid, **p}))


@router.get("/api/link/movers")
def api_link_movers():
    if _MOVERS["data"] is None or time.time() - _MOVERS["t"] > 600:
        _MOVERS.update(data=linkage.movers(), t=time.time())
    return JSONResponse(content=_clean({"movers": _MOVERS["data"], "research": _research().get("follow")}))


@router.get("/api/disposal/today")
def api_disposal_today(force: int = 0):
    d = disposal.today(force=bool(force))
    return JSONResponse(content=_clean({**d, "research": _research().get("disposal")}))


def _load(name):
    try:
        with open(os.path.join(RES, name), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _research() -> dict:
    """網站用的研究結論（research/link/results/link_conclusions.json；report_link.py 產生）"""
    return _load("link_conclusions.json") or {}


@router.get("/api/link/research")
def api_link_research():
    return JSONResponse(content=_clean(_research()))


@router.post("/api/link/refresh")
def api_link_refresh():
    threading.Thread(target=refresh_all, daemon=True).start()
    return {"started": True}
