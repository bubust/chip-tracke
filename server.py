"""
server.py — FastAPI 後端
資料來源：Yahoo Finance（同 tw-macd-scan，不受 TWSE 封鎖）
功能：觀察清單 / 策略篩選（全市場）/ 個股資料 / Telegram 推播
"""

import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from chip_tracker_v2 import (
    DATA_DIR, DB_PATH,
    get_conn, init_db,
    load_stock_history, update_stocks,
    DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS,
    get_weights, get_thresholds, save_params,
)
import supabase_store as sb

BASE_DIR = Path(__file__).parent


# ════════════════════════════════════════════════════════════════════════════
# App 初始化
# ════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="籌碼追蹤系統", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ════════════════════════════════════════════════════════════════════════════
# Pydantic 模型
# ════════════════════════════════════════════════════════════════════════════

class WatchlistItem(BaseModel):
    stock_id: str
    name: Optional[str] = ""

class RefreshBody(BaseModel):
    date: Optional[str] = None
    backfill: Optional[int] = 30
    extra_stocks: Optional[list[str]] = []

class TelegramSettings(BaseModel):
    token: str
    chat_id: str

class CustomMessage(BaseModel):
    text: str

class ParamsBody(BaseModel):
    weights: dict
    thresholds: dict


# ════════════════════════════════════════════════════════════════════════════
# 設定 helpers
# ════════════════════════════════════════════════════════════════════════════

def settings_get(key: str) -> Optional[str]:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None

def settings_set(key: str, value: str):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# Telegram helpers
# ════════════════════════════════════════════════════════════════════════════

async def tg_send(text: str) -> bool:
    token   = settings_get("telegram_token")
    chat_id = settings_get("telegram_chat_id")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            return r.status_code == 200
    except Exception:
        return False

def log_push(stock_id: str, emoji: str, title: str, ok: bool):
    conn = get_conn()
    conn.execute(
        "INSERT INTO push_log (stock_id, signal_emoji, signal_title, pushed_at, ok) VALUES (?,?,?,?,?)",
        (stock_id, emoji, title, datetime.now().isoformat(), 1 if ok else 0)
    )
    conn.commit()
    conn.close()

def format_stock_message(stock_id: str, records: list[dict]) -> str:
    if not records:
        return f"<b>{stock_id}</b>\n無資料"
    latest = records[-1]
    recent = records[-7:] if len(records) >= 7 else records
    cum7 = sum(r.get("whale_flow_lots", 0) for r in recent)
    sig_emoji = latest.get("signal_emoji", "⚪")
    sig_title = latest.get("signal_title", "盤整")
    lines = [
        f"<b>{sig_emoji} {stock_id} — {sig_title}</b>",
        f"日期：{latest.get('date', '?')}",
        f"大戶流向：{latest.get('whale_flow_lots', 0):+,} 張",
        f"散戶流向：{latest.get('retail_flow_lots', 0):+,} 張",
        f"集中度：{latest.get('concentration_index', 0):.3f}",
        f"7日累計：{cum7:+,} 張",
    ]
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# Watchlist API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/watchlist")
def api_get_watchlist():
    rows = sb.wl_list()
    if rows is not None:
        return rows
    conn = get_conn()
    rows = conn.execute("SELECT stock_id, name, added_at FROM watchlist ORDER BY added_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/watchlist")
def api_add_watchlist(item: WatchlistItem):
    sid  = item.stock_id.strip()
    name = (item.name or "").strip()
    now  = datetime.now().isoformat()
    sb.wl_add(sid, name, now)
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO watchlist (stock_id, name, added_at) VALUES (?,?,?)", (sid, name, now))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/watchlist/{stock_id}")
def api_del_watchlist(stock_id: str):
    sb.wl_delete(stock_id)
    sb.cd_delete_stock(stock_id)
    conn = get_conn()
    conn.execute("DELETE FROM watchlist WHERE stock_id=?", (stock_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.put("/api/watchlist/{stock_id}")
def api_update_watchlist(stock_id: str, item: WatchlistItem):
    name = (item.name or "").strip()
    sb.wl_update_name(stock_id, name)
    conn = get_conn()
    conn.execute("UPDATE watchlist SET name=? WHERE stock_id=?", (name, stock_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/watchlist/summary")
async def api_watchlist_summary():
    from yahoo_price import get_stock_list, fetch_prices_for_stocks

    # stocks.csv → 備用股名 + 市場類型
    stocks_df  = get_stock_list()
    csv_names  = dict(zip(stocks_df["stock_id"], stocks_df["stock_name"]))
    mkt_map    = dict(zip(stocks_df["stock_id"], stocks_df["type"]))

    conn = get_conn()
    rows = conn.execute("SELECT stock_id, name FROM watchlist ORDER BY added_at").fetchall()
    conn.close()

    stock_ids = [r["stock_id"] for r in rows]

    # 補空白名稱：DB 有就用 DB，否則從 stocks.csv 補
    names: dict[str, str] = {}
    to_update: list[tuple[str, str]] = []
    for r in rows:
        sid   = r["stock_id"]
        db_n  = (r["name"] or "").strip()
        csv_n = csv_names.get(sid, "")
        resolved = db_n or csv_n
        names[sid] = resolved
        if not db_n and csv_n:
            to_update.append((csv_n, sid))

    # 把補到的名稱同步回 DB
    if to_update:
        conn = get_conn()
        conn.executemany("UPDATE watchlist SET name=? WHERE stock_id=?", to_update)
        conn.commit()
        conn.close()

    # 批次抓最新收盤價
    stock_list   = [(sid, mkt_map.get(sid, "twse")) for sid in stock_ids]
    latest_prices = await fetch_prices_for_stocks(stock_list)

    result = []
    for r in rows:
        sid  = r["stock_id"]
        name = names.get(sid, "")
        records = load_stock_history(sid)
        price_info = latest_prices.get(sid, {})
        item: dict = {
            "stock_id":   sid,
            "name":       name,
            "close":      price_info.get("close"),
            "change_pct": price_info.get("change_pct"),
        }
        if records:
            latest = records[-1]
            last7  = records[-7:]
            cum7   = sum(r2.get("whale_flow_lots", 0) for r2 in last7)
            item.update({
                "has_data":            True,
                "date":                latest.get("date", ""),
                "whale_flow_lots":     latest.get("whale_flow_lots", 0),
                "retail_flow_lots":    latest.get("retail_flow_lots", 0),
                "concentration_index": latest.get("concentration_index", 0),
                "cum7_whale":          cum7,
                "signal_emoji":        latest.get("signal_emoji", "⚪"),
                "signal_title":        latest.get("signal_title", "—"),
                "signal_level":        latest.get("signal_level", 0),
            })
        else:
            item["has_data"] = False
        result.append(item)
    return result


# ════════════════════════════════════════════════════════════════════════════
# Refresh API（觀察清單個股籌碼更新）
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/refresh")
async def api_refresh(body: RefreshBody):
    sb_ids = sb.wl_get_ids()
    if sb_ids is not None:
        stock_ids = sb_ids
    else:
        conn = get_conn()
        rows = conn.execute("SELECT stock_id FROM watchlist").fetchall()
        conn.close()
        stock_ids = [r["stock_id"] for r in rows]
    if body.extra_stocks:
        for s in body.extra_stocks:
            s = s.strip()
            if s and s not in stock_ids:
                stock_ids.append(s)
    if not stock_ids:
        raise HTTPException(status_code=400, detail="觀察清單為空，請先新增股票")
    end_dt = None
    if body.date:
        try:
            end_dt = datetime.strptime(body.date, "%Y%m%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date 格式錯誤，應為 YYYYMMDD")
    days = body.backfill or 30
    results = await update_stocks(stock_ids, days=days, end_date=end_dt)
    settings_set("last_refresh", datetime.now().isoformat())
    return {"ok": True, "updated": list(results.keys()), "days": days}


# ════════════════════════════════════════════════════════════════════════════
# Stock Query API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/stock/{stock_id}")
async def api_stock(stock_id: str, days: int = 30):
    records = load_stock_history(stock_id)
    if not records:
        await update_stocks([stock_id], days=days)
        records = load_stock_history(stock_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"{stock_id} 尚無資料")
    return {"stock_id": stock_id, "data": records[-days:]}

@app.post("/api/stock/{stock_id}/refresh")
async def api_refresh_stock(stock_id: str, days: int = 30):
    await update_stocks([stock_id], days=days)
    records = load_stock_history(stock_id)
    return {"ok": True, "stock_id": stock_id, "records": len(records)}


# ════════════════════════════════════════════════════════════════════════════
# 全市場策略掃描 API（Yahoo Finance）
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/screen/run")
async def api_screen_run(background_tasks: BackgroundTasks):
    from yahoo_price import get_scan_status, run_market_scan
    status = get_scan_status()
    if status["running"]:
        return {"ok": False, "message": "掃描中，請稍候"}
    background_tasks.add_task(run_market_scan)
    return {"ok": True, "message": "全市場掃描已啟動（所有策略）..."}

@app.get("/api/screen/status")
def api_screen_status():
    from yahoo_price import get_scan_status
    return get_scan_status()

@app.get("/api/screen/results")
def api_screen_results():
    from yahoo_price import get_scan_results
    from scanner import STRATEGIES
    raw = get_scan_results()   # {strategy_key: [result_dict, ...]}
    return {
        "finished_at": _scan_status_ts(),
        "strategies":  STRATEGIES,
        "results":     raw,
    }

def _scan_status_ts():
    from yahoo_price import get_scan_status
    return get_scan_status()["finished_at"]


# ════════════════════════════════════════════════════════════════════════════
# 股票搜尋（從 stocks.csv）
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/search")
def api_search_stocks(q: str = ""):
    q = q.strip()
    if not q:
        return []
    try:
        from yahoo_price import get_stock_list
        stocks = get_stock_list()
        mask = (stocks["stock_id"].str.startswith(q) |
                stocks["stock_name"].str.contains(q, na=False))
        return stocks[mask].head(10)[["stock_id","stock_name"]].rename(
            columns={"stock_name": "name"}
        ).to_dict(orient="records")
    except Exception:
        return []


# ════════════════════════════════════════════════════════════════════════════
# Settings / Params API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/params")
def api_get_params():
    return {
        "weights":    get_weights(),
        "thresholds": get_thresholds(),
        "defaults": {
            "weights":    DEFAULT_WEIGHTS,
            "thresholds": DEFAULT_THRESHOLDS,
        }
    }

@app.post("/api/params")
def api_save_params(body: ParamsBody):
    w = {k: float(v) for k, v in body.weights.items()    if k in DEFAULT_WEIGHTS}
    t = {k: float(v) for k, v in body.thresholds.items() if k in DEFAULT_THRESHOLDS}
    save_params(w, t)
    return {"ok": True, "saved_weights": len(w), "saved_thresholds": len(t)}

@app.post("/api/params/reset")
def api_reset_params():
    conn = get_conn()
    conn.execute("DELETE FROM settings WHERE key LIKE 'w_%' OR key LIKE 't_%'")
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/settings")
def api_get_settings():
    token   = settings_get("telegram_token") or ""
    chat_id = settings_get("telegram_chat_id") or ""
    masked  = (token[:10] + "...") if len(token) > 10 else token
    return {
        "telegram_token_masked": masked,
        "telegram_chat_id": chat_id,
        "has_token": bool(token),
    }

@app.post("/api/settings/telegram")
def api_save_telegram(body: TelegramSettings):
    settings_set("telegram_token",   body.token.strip())
    settings_set("telegram_chat_id", body.chat_id.strip())
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# Telegram Push API
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/telegram/test")
async def api_tg_test():
    ok = await tg_send("✅ 籌碼追蹤系統測試訊息\n連線正常！")
    if not ok:
        raise HTTPException(status_code=400, detail="推播失敗，請確認 token 與 chat_id")
    return {"ok": True}

@app.post("/api/telegram/push/{stock_id}")
async def api_tg_push_stock(stock_id: str):
    records = load_stock_history(stock_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"{stock_id} 尚無資料")
    msg = format_stock_message(stock_id, records)
    ok  = await tg_send(msg)
    latest = records[-1]
    log_push(stock_id, latest.get("signal_emoji","⚪"), latest.get("signal_title","?"), ok)
    if not ok:
        raise HTTPException(status_code=400, detail="Telegram 推播失敗")
    return {"ok": True}

@app.post("/api/telegram/push-custom")
async def api_tg_push_custom(body: CustomMessage):
    ok = await tg_send(body.text)
    if not ok:
        raise HTTPException(status_code=400, detail="Telegram 推播失敗")
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# Status / Push Log
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/status")
def api_status():
    conn = get_conn()
    cache_count    = conn.execute("SELECT COUNT(*) FROM market_raw").fetchone()[0]
    watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    conn.close()
    last_refresh = settings_get("last_refresh")
    return {
        "cache_count":      cache_count,
        "watchlist_count":  watchlist_count,
        "last_refresh":     last_refresh,
        "db_path":          str(DB_PATH),
    }

@app.get("/api/push-log")
def api_push_log(limit: int = 20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM push_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/api/cache")
def api_clear_cache():
    from chip_tracker_v2 import clear_bad_cache
    deleted = clear_bad_cache()
    return {"ok": True, "deleted": deleted}


# ════════════════════════════════════════════════════════════════════════════
# 首頁
# ════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    html_path = BASE_DIR / "dashboard.html"
    if html_path.exists():
        return FileResponse(html_path)
    return JSONResponse({"error": "dashboard.html not found"}, status_code=404)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
