"""
庫藏股 API

GET  /api/treasury/list          買回清單（含狀態、現價、決議後漲跌、與買回價格區間的位置）
GET  /api/treasury/stock/{sid}   單一公司歷次買回
GET  /api/treasury/active        進行中的公司（給觀察清單 / 策略篩選標記用）
GET  /api/treasury/status        資料狀態 + 更新進度
POST /api/treasury/refresh       背景從 MOPS 更新（days=回溯天數）
POST /api/treasury/import        匯入 MOPS 另存的 CSV / HTML（request body 直接放檔案內容）
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from . import db
from .fetcher import fetch_range
from .parser import parse_any

log = logging.getLogger(__name__)
router = APIRouter()
_TW = timezone(timedelta(hours=8))

_refresh = {"running": False, "progress": 0, "total": 0, "message": ""}
_refresh_lock = threading.Lock()


def tw_today() -> date:
    return datetime.now(_TW).date()


# ── 更新 ──────────────────────────────────────────────────────────────────────

def run_refresh(days: int = 180) -> dict:
    """同步執行：抓近 days 天（依董事會決議日）的買回資料並寫入。排程 / 背景 thread 呼叫。"""
    with _refresh_lock:
        if _refresh["running"]:
            return {"ok": False, "message": "已在更新中"}
        _refresh.update(running=True, progress=0, total=0, message="")
    try:
        end = tw_today()
        start = end - timedelta(days=days)

        def _prog(d, t):
            with _refresh_lock:
                _refresh.update(progress=d, total=t)

        res = fetch_range(start, end, progress=_prog)
        stat = db.upsert(res["records"])
        now = datetime.now(_TW).strftime("%Y-%m-%d %H:%M")
        msg = f"抓到 {len(res['records'])} 筆（新增 {stat['inserted']}、更新 {stat['updated']}）"
        if res["errors"]:
            msg += f"；{len(res['errors'])} 段失敗"
        db.set_status(last_refresh=now, last_message=msg,
                      last_errors="\n".join(res["errors"][:8]) or None,
                      last_snippet=res["snippet"] or None,
                      **({"last_success": now} if res["records"] or not res["errors"] else {}))
        log.info(f"[treasury] {msg}")
        return {"ok": not res["errors"] or bool(res["records"]), "message": msg, "errors": res["errors"]}
    except Exception as e:
        log.error(f"[treasury] refresh 失敗: {e}")
        db.set_status(last_refresh=datetime.now(_TW).strftime("%Y-%m-%d %H:%M"),
                      last_message=f"更新失敗：{type(e).__name__}: {e}")
        return {"ok": False, "message": str(e)}
    finally:
        with _refresh_lock:
            _refresh["running"] = False


@router.post("/api/treasury/refresh")
def refresh(days: int = Query(180, ge=7, le=1500)):
    with _refresh_lock:
        if _refresh["running"]:
            return {"ok": False, "message": "已在更新中"}
    threading.Thread(target=run_refresh, args=(days,), daemon=True, name="treasury-refresh").start()
    return {"ok": True, "message": f"開始從公開資訊觀測站更新近 {days} 天的庫藏股資料"}


@router.post("/api/treasury/import")
async def import_file(request: Request):
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "沒有收到檔案內容")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, "檔案太大（上限 8MB）")
    recs = parse_any(raw)
    if not recs:
        raise HTTPException(400, "檔案裡找不到庫藏股表格（需要有「公司代號」「董事會決議日期」等欄位）")
    stat = db.upsert(recs)
    db.set_status(last_import=datetime.now(_TW).strftime("%Y-%m-%d %H:%M"),
                  last_import_message=f"匯入 {len(recs)} 筆（新增 {stat['inserted']}、更新 {stat['updated']}）")
    return {"ok": True, "parsed": len(recs), **stat}


@router.get("/api/treasury/status")
def get_status():
    s = db.get_status()
    with _refresh_lock:
        s["refresh"] = dict(_refresh)
    return s


# ── 查詢 ──────────────────────────────────────────────────────────────────────

def _stock_meta() -> dict:
    try:
        from yahoo_price import get_stock_list
        df = get_stock_list()
        return {r.stock_id: (r.stock_name, r.type) for r in df.itertuples(index=False)}
    except Exception:
        return {}


def _price_lookup(rows: list) -> tuple:
    """回傳 (latest: {sid: (close, date)}, at_board: {(sid, board_date): close})，資料來自 price_daily 快取"""
    latest, at_board = {}, {}
    try:
        from chip_tracker_v2 import DB_PATH as PRICE_DB
        conn = sqlite3.connect(str(PRICE_DB), timeout=5.0)
        sids = sorted({r["stock_id"] for r in rows})
        for i in range(0, len(sids), 500):
            chunk = sids[i:i + 500]
            q = ("SELECT p.stock_id, p.close, p.date FROM price_daily p JOIN "
                 "(SELECT stock_id, MAX(date) d FROM price_daily WHERE stock_id IN "
                 f"({','.join('?' * len(chunk))}) GROUP BY stock_id) m "
                 "ON p.stock_id=m.stock_id AND p.date=m.d")
            for sid, close, d in conn.execute(q, chunk):
                latest[sid] = (close, d)
        for r in rows:
            bd = (r.get("board_date") or "").replace("-", "")
            row = conn.execute("SELECT close FROM price_daily WHERE stock_id=? AND date>=? "
                               "ORDER BY date LIMIT 1", (r["stock_id"], bd)).fetchone()
            if row and row[0]:
                at_board[(r["stock_id"], r["board_date"])] = row[0]
        conn.close()
    except Exception as e:
        log.warning(f"[treasury] 讀股價快取失敗: {e}")
    return latest, at_board


def classify(r: dict, today: date) -> str:
    ps, pe = r.get("period_start"), r.get("period_end")
    t = today.isoformat()
    reported = r.get("done") == 1 or r.get("bought_shares") not in (None, 0)
    if ps and t < ps:
        return "未開始"
    if pe and t <= pe:
        return "已結束" if (r.get("done") == 1 and r.get("bought_shares")) else "進行中"
    if not pe:
        return "已結束" if reported else "進行中"
    return "已結束" if reported else "期滿待申報"


def enrich(rows: list, today: date = None, with_prices: bool = True) -> list:
    today = today or tw_today()
    meta = _stock_meta()
    latest, at_board = _price_lookup(rows) if with_prices else ({}, {})
    out = []
    for r in rows:
        r = dict(r)
        m = meta.get(r["stock_id"])
        if m:
            r["name"] = r.get("name") or m[0]
            r["market"] = r.get("market") or m[1]
        r["market"] = {"sii": "twse", "otc": "tpex"}.get(r.get("market"), r.get("market"))
        r["status"] = classify(r, today)
        plan, bought = r.get("plan_shares"), r.get("bought_shares")
        r["plan_lots"] = round(plan / 1000) if plan else None
        r["bought_lots"] = round(bought / 1000) if bought is not None else None
        if r.get("exec_ratio") is None and plan and bought is not None:
            r["exec_ratio"] = round(bought / plan * 100, 2)
        pe, ps = r.get("period_end"), r.get("period_start")
        r["days_left"] = (date.fromisoformat(pe) - today).days if pe and r["status"] == "進行中" else None
        r["days_since_board"] = (today - date.fromisoformat(r["board_date"])).days
        price, pdate = latest.get(r["stock_id"], (None, None))
        r["price"], r["price_date"] = price, pdate
        lo, hi = r.get("price_low"), r.get("price_high")
        if price and hi:
            r["to_high_pct"] = round((hi / price - 1) * 100, 2)   # 現價離可買上限還有多少 %
            r["range_pos"] = ("低於下限" if lo and price < lo else
                              "高於上限" if price > hi else "區間內")
        else:
            r["to_high_pct"] = r["range_pos"] = None
        b = at_board.get((r["stock_id"], r["board_date"]))
        r["price_at_board"] = b
        r["chg_since_board"] = round((price / b - 1) * 100, 2) if price and b else None
        if price and r.get("avg_price"):
            r["vs_avg_price"] = round((price / r["avg_price"] - 1) * 100, 2)
        else:
            r["vs_avg_price"] = None
        out.append(r)
    return out


@router.get("/api/treasury/list")
def list_buybacks(status: str = Query("all"), days: int = Query(365, ge=7, le=3650),
                  market: str = Query("")):
    since = (tw_today() - timedelta(days=days)).isoformat()
    rows = enrich(db.all_rows(since=since))
    if status != "all":
        wanted = set(status.split(","))
        rows = [r for r in rows if r["status"] in wanted]
    if market:
        rows = [r for r in rows if (r.get("market") or "") == market]
    counts = {}
    for r in enrich(db.all_rows(since=since), with_prices=False):
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"rows": rows, "counts": counts, "since": since, "status": get_status()}


@router.get("/api/treasury/stock/{stock_id}")
def stock_history(stock_id: str):
    conn = db.get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM treasury_buyback WHERE stock_id=? ORDER BY board_date DESC", (stock_id,))]
    conn.close()
    rows = enrich(rows)
    done = [r for r in rows if r["status"] == "已結束" and r.get("exec_ratio") is not None]
    return {
        "stock_id": stock_id,
        "name": rows[0]["name"] if rows else "",
        "count": len(rows),
        "avg_exec_ratio": round(sum(r["exec_ratio"] for r in done) / len(done), 1) if done else None,
        "total_bought_amount": sum(r.get("bought_amount") or 0 for r in rows) or None,
        "rows": rows,
    }


@router.get("/api/treasury/active")
def active():
    """進行中 / 未開始的買回：{stock_id: {...}}（觀察清單、策略篩選打標記用，不查股價）"""
    since = (tw_today() - timedelta(days=200)).isoformat()
    out = {}
    for r in enrich(db.all_rows(since=since), with_prices=False):
        if r["status"] in ("進行中", "未開始") and r["stock_id"] not in out:
            out[r["stock_id"]] = {k: r.get(k) for k in
                                  ("status", "board_date", "period_start", "period_end", "plan_lots",
                                   "price_low", "price_high", "purpose", "days_left")}
    return out
