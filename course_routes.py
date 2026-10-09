"""
course_routes.py — 📋 講義訊號 API（PLAN-COURSE）
- GET  /api/course/today：出貨日、主流族群大跌、當沖名單、漲停打開候選／盤中已打開、大盤出貨日＋研究結論
- GET  /api/course/dist：最近 3 個交易日有出貨日的股票（網頁「⚠出貨日」徽章用）
- GET  /api/course/dist/{sid}：這檔最近一年的出貨日
- GET  /api/course/research：研究結論（research/course/results/course_site.json）
- POST /api/course/refresh：重算（背景，不推播）
"""
from __future__ import annotations

import json
import os
import re
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

import course_live as L

router = APIRouter()
HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "research", "course", "results", "course_site.json")


def _clean(o):
    from server import _sanitize_for_json
    return _sanitize_for_json(o)


def research() -> dict:
    try:
        with open(SITE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


@router.get("/api/course/today")
def api_course_today():
    out = {k: L.latest(k) for k in ("dist", "sector", "daytrade", "limit", "market")}
    if out["dist"]:
        out["dist"]["items"] = out["dist"]["items"][:200]
    out["live"] = L.live_status()
    out["research"] = research()
    return JSONResponse(content=_clean(out))


@router.get("/api/course/dist")
def api_course_dist():
    d = L.latest("dist") or {}
    return JSONResponse(content=_clean({"date": d.get("date"), "items": [
        {"stock_id": x["stock_id"], "date": x["date"], "type": x["type"], "type_name": x["type_name"]} for x in d.get("items", [])]}))


@router.get("/api/course/dist/{sid}")
def api_course_dist_sid(sid: str):
    if not re.fullmatch(r"[0-9]{4}", sid or ""):
        raise HTTPException(400, "股票代號要 4 碼數字")
    return JSONResponse(content=_clean({"stock_id": sid, "items": L.dist_of(sid)}))


@router.get("/api/course/research")
def api_course_research():
    return JSONResponse(content=_clean(research()))


@router.post("/api/course/refresh")
def api_course_refresh():
    threading.Thread(target=L.nightly, kwargs={"push": False}, daemon=True).start()
    return {"started": True}
