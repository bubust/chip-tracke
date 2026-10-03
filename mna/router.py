"""
收購併購 API

GET    /api/mna/list            清單（狀態、現價、溢價、剩餘天數、年化報酬）
GET    /api/mna/status          資料狀態＋更新進度
POST   /api/mna/refresh         背景從 MOPS 重大訊息更新（days=回溯交易日數）
POST   /api/mna/deal            手動新增；PUT /api/mna/deal/{id} 修改；DELETE 刪除
POST   /api/mna/import          匯入 CSV（第一列表頭：標的代號、收購方、類型、公告日、收購價、最低數量、最高數量、比例、範圍、期間起、期間迄、對價、備註）
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from . import db
from .fetcher import fetch_range
from treasury.parser import roc_to_iso, to_num

router = APIRouter()
_TW = timezone(timedelta(hours=8))
_refresh = {"running": False, "progress": 0, "total": 0}
_lock = threading.Lock()


def tw_today() -> date:
    return datetime.now(_TW).date()


def run_refresh(days: int = 14) -> dict:
    with _lock:
        if _refresh["running"]:
            return {"ok": False, "message": "已在更新中"}
        _refresh.update(running=True, progress=0, total=0)
    try:
        def prog(d, t):
            with _lock:
                _refresh.update(progress=d, total=t)
        res = fetch_range(days, progress=prog)
        st = db.upsert_auto(res["records"])
        now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M")
        msg = f"找到 {len(res['records'])} 則收購併購訊息（新增 {st['inserted']}、補資料 {st['updated']}）"
        if res["errors"]:
            msg += f"；{len(res['errors'])} 天失敗"
        db.set_status(last_refresh=now, last_message=msg, last_errors="\n".join(res["errors"][:6]) or None,
                      last_snippet=res["snippet"] or None)
        return {"ok": True, "message": msg}
    except Exception as e:
        db.set_status(last_refresh=datetime.now(_TW).strftime("%Y-%m-%d %H:%M"), last_message=f"更新失敗：{e}")
        return {"ok": False, "message": str(e)}
    finally:
        with _lock:
            _refresh["running"] = False


@router.post("/api/mna/refresh")
def refresh(days: int = Query(14, ge=1, le=120)):
    with _lock:
        if _refresh["running"]:
            return {"ok": False, "message": "已在更新中"}
    threading.Thread(target=run_refresh, args=(days,), daemon=True, name="mna-refresh").start()
    return {"ok": True, "message": f"開始從公開資訊觀測站重大訊息更新近 {days} 個交易日"}


@router.get("/api/mna/status")
def status():
    s = db.get_status()
    with _lock:
        s["refresh"] = dict(_refresh)
    return s


def _latest_prices(ids) -> dict:
    out = {}
    try:
        from chip_tracker_v2 import DB_PATH
        c = sqlite3.connect(str(DB_PATH), timeout=5.0)
        for sid in ids:
            r = c.execute("SELECT close, date FROM price_daily WHERE stock_id=? AND close>0 ORDER BY date DESC LIMIT 1",
                          (sid,)).fetchone()
            if r:
                out[sid] = (r[0], r[1])
        c.close()
    except Exception:
        pass
    return out


def classify_status(r: dict, today: date) -> str:
    if r.get("status_override"):
        return r["status_override"]
    ps, pe = r.get("period_start"), r.get("period_end")
    t = today.isoformat()
    if ps and t < ps:
        return "未開始"
    if pe:
        return "進行中" if t <= pe else "已結束"
    if r.get("deal_type") == "公開收購":
        return "待補期間"
    return "已公告"


def enrich(rows: list, today: date = None) -> list:
    today = today or tw_today()
    prices = _latest_prices({r["target_id"] for r in rows})
    out = []
    for r in rows:
        r = dict(r)
        r["status"] = classify_status(r, today)
        px, pdate = prices.get(r["target_id"], (None, None))
        r["price"], r["price_date"] = px, pdate
        op = r.get("offer_price")
        r["premium_pct"] = round((op / px - 1) * 100, 2) if op and px else None
        pe = r.get("period_end")
        r["days_left"] = (date.fromisoformat(pe) - today).days if pe and r["status"] in ("進行中", "未開始") else None
        r["annualized_pct"] = (round(r["premium_pct"] * 365 / max(r["days_left"], 1), 1)
                               if r["premium_pct"] is not None and r["premium_pct"] > 0 and r["days_left"] else None)
        r["min_lots"] = round(r["min_shares"] / 1000) if r.get("min_shares") else None
        r["max_lots"] = round(r["max_shares"] / 1000) if r.get("max_shares") else None
        r["amount_yi"] = round(op * r["max_shares"] / 1e8, 2) if op and r.get("max_shares") else None
        out.append(r)
    return out


@router.get("/api/mna/list")
def list_deals(days: int = Query(365, ge=7, le=3650)):
    since = (tw_today() - timedelta(days=days)).isoformat()
    rows = enrich(db.all_rows(since))
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"rows": rows, "counts": counts, "status": status()}


class Deal(BaseModel):
    target_id: str
    target_name: Optional[str] = ""
    acquirer: Optional[str] = ""
    deal_type: Optional[str] = "公開收購"
    announce_date: Optional[str] = None
    offer_price: Optional[float] = None
    min_shares: Optional[float] = None
    max_shares: Optional[float] = None
    offer_pct: Optional[float] = None
    scope: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    consideration: Optional[str] = None
    status_override: Optional[str] = None
    notes: Optional[str] = ""


def _clean(d: Deal) -> dict:
    if not re.fullmatch(r"[0-9A-Za-z]{2,10}", (d.target_id or "").strip()):
        raise HTTPException(400, "標的代號格式不正確")
    data = d.model_dump()
    data["target_id"] = data["target_id"].strip()
    for k in ("announce_date", "period_start", "period_end"):
        data[k] = roc_to_iso(data[k]) if data.get(k) else None
    for k in ("target_name", "acquirer", "deal_type", "scope", "consideration", "status_override", "notes"):
        v = "".join(ch for ch in str(data.get(k) or "") if ch >= " ").strip()
        data[k] = v[:300] or None
    return data


@router.post("/api/mna/deal")
def create_deal(d: Deal):
    return {"ok": True, "id": db.save_manual(_clean(d))}


@router.put("/api/mna/deal/{deal_id}")
def update_deal(deal_id: int, d: Deal):
    db.save_manual(_clean(d), deal_id)
    return {"ok": True, "id": deal_id}


@router.delete("/api/mna/deal/{deal_id}")
def delete_deal(deal_id: int):
    db.delete(deal_id)
    return {"ok": True}


_CSV_MAP = {"標的代號": "target_id", "代號": "target_id", "標的名稱": "target_name", "名稱": "target_name",
            "收購方": "acquirer", "類型": "deal_type", "公告日": "announce_date", "收購價": "offer_price",
            "最低數量": "min_shares", "最高數量": "max_shares", "比例": "offer_pct", "範圍": "scope",
            "期間起": "period_start", "期間迄": "period_end", "對價": "consideration", "備註": "notes"}


@router.post("/api/mna/import")
async def import_csv(request: Request):
    raw = await request.body()
    if not raw or len(raw) > 4 * 1024 * 1024:
        raise HTTPException(400, "檔案是空的或太大（上限 4MB）")
    text = None
    for enc in ("utf-8-sig", "cp950"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    rows = list(csv.reader(io.StringIO(text or "")))
    if len(rows) < 2:
        raise HTTPException(400, "CSV 至少要有表頭和一列資料")
    hdr = [_CSV_MAP.get(h.strip()) for h in rows[0]]
    if "target_id" not in hdr:
        raise HTTPException(400, "表頭要有「標的代號」")
    n = 0
    for r in rows[1:]:
        rec = {k: (r[i].strip() if i < len(r) else "") for i, k in enumerate(hdr) if k}
        if not rec.get("target_id"):
            continue
        for k in ("offer_price", "min_shares", "max_shares", "offer_pct"):
            rec[k] = to_num(rec.get(k))
        rec = {k: v for k, v in rec.items() if v not in ("", None)}
        try:
            data = _clean(Deal(**rec))
        except Exception:
            continue
        data["source"] = "匯入"
        db.save_manual(data)
        n += 1
    return {"ok": True, "imported": n}
