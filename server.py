"""
server.py — FastAPI 後端
- REST API (watchlist / refresh / stock / market / telegram / settings)
- 靜態伺服 dashboard.html
"""

import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chip_tracker_v2 import (
    DATA_DIR, DB_PATH,
    get_conn, init_db,
    get_market_rankings, load_stock_history,
    to_twse_date, update_stocks,
    scan_market_today, clear_bad_cache,
    DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS,
    get_weights, get_thresholds, save_params,
    lookup_stock_name,
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
    allow_origins=["https://bubust.github.io", "http://localhost:8000", "http://127.0.0.1:8000"],
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

class MarketRankingBody(BaseModel):
    date: Optional[str] = None
    top: Optional[int] = 30

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
    """更新股票名稱"""
    name = (item.name or "").strip()
    sb.wl_update_name(stock_id, name)
    conn = get_conn()
    conn.execute("UPDATE watchlist SET name=? WHERE stock_id=?", (name, stock_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/watchlist/summary")
def api_watchlist_summary():
    """取得觀察清單所有股票的最新資料摘要（最新一天 + 7日累計）"""
    conn = get_conn()
    rows = conn.execute("SELECT stock_id, name FROM watchlist ORDER BY added_at").fetchall()
    conn.close()

    result = []
    for row in rows:
        sid  = row["stock_id"]
        name = row["name"] or ""
        records = load_stock_history(sid)
        item: dict = {"stock_id": sid, "name": name}
        if records:
            latest  = records[-1]
            last7   = records[-7:]
            cum7    = sum(r.get("whale_flow_lots", 0) for r in last7)
            item.update({
                "has_data":           True,
                "date":               latest.get("date", ""),
                "whale_flow_lots":    latest.get("whale_flow_lots", 0),
                "retail_flow_lots":   latest.get("retail_flow_lots", 0),
                "concentration_index": latest.get("concentration_index", 0),
                "cum7_whale":         cum7,
                "signal_emoji":       latest.get("signal_emoji", "⚪"),
                "signal_title":       latest.get("signal_title", "—"),
                "signal_level":       latest.get("signal_level", 0),
            })
        else:
            item["has_data"] = False
        result.append(item)
    return result


# ════════════════════════════════════════════════════════════════════════════
# Refresh API
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/refresh")
async def api_refresh(body: RefreshBody):
    # 取觀察清單（優先 Supabase）
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
        # 第一次查詢自動抓取
        await update_stocks([stock_id], days=days)
        records = load_stock_history(stock_id)
    if not records:
        raise HTTPException(status_code=404, detail=f"{stock_id} 尚無資料，可能非上市股票或當日無交易")
    records = records[-days:]
    return {"stock_id": stock_id, "data": records}


@app.post("/api/stock/{stock_id}/refresh")
async def api_refresh_stock(stock_id: str, days: int = 30):
    """強制重新抓取個股資料（bypass cache 壞資料）"""
    await update_stocks([stock_id], days=days)
    records = load_stock_history(stock_id)
    return {"ok": True, "stock_id": stock_id, "records": len(records)}


# ════════════════════════════════════════════════════════════════════════════
# Debug API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/debug/twse")
async def api_debug_twse(date: str = "20260521"):
    """測試 Render 能否存取 TWSE API"""
    import httpx
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {"response": "json", "date": date, "selectType": "ALL"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.twse.com.tw/",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, params=params, headers=headers)
            d = r.json()
            return {
                "status_code": r.status_code,
                "stat": d.get("stat"),
                "rows": len(d.get("data", [])),
                "sample": d.get("data", [[]])[0][:3] if d.get("data") else None,
            }
    except Exception as e:
        return {"error": str(e)}


# ════════════════════════════════════════════════════════════════════════════
# Market Rankings API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/market/rankings")
def api_market_rankings(date: str = None, top: int = 30):
    if date is None:
        date = to_twse_date(datetime.today().date())
    rankings = get_market_rankings(dt=date, top=top)
    return {"date": date, "data": rankings}


@app.get("/api/market/scan")
async def api_market_scan(top: int = 50):
    """掃描全市場上市股票大戶排行（自動找最近有資料的交易日）"""
    data, actual_dt = await scan_market_today()
    return {
        "date":        actual_dt or to_twse_date(datetime.today().date()),
        "total":       len(data),
        "top_buyers":  data[:top],
        "top_sellers": list(reversed(data[-top:])) if len(data) >= top else list(reversed(data)),
    }


@app.delete("/api/cache")
def api_clear_cache():
    """清除 stat != OK 的快取資料（修復全部 +0 問題）"""
    deleted = clear_bad_cache()
    return {"ok": True, "deleted": deleted}


# ════════════════════════════════════════════════════════════════════════════
# Settings API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/lookup/{stock_id}")
def api_lookup_stock(stock_id: str):
    """從快取 T86 查股票名稱"""
    name = lookup_stock_name(stock_id.upper().strip())
    return {"stock_id": stock_id, "name": name}


# ─── 股票清單快取（用於名稱搜尋）────────────────────────────────────────
_stock_list: list[dict] = []
_stock_list_fetched: Optional[str] = None

def _get_stock_list() -> list[dict]:
    """從 TWSE OpenAPI 取上市股票清單（每日快取一次）"""
    global _stock_list, _stock_list_fetched
    today = str(date.today())
    if _stock_list and _stock_list_fetched == today:
        return _stock_list
    try:
        r = httpx.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            _stock_list = [
                {"stock_id": row["Code"], "name": row["Name"].strip()}
                for row in data
                if row.get("Code") and row.get("Name")
            ]
            _stock_list_fetched = today
    except Exception as e:
        print(f"[WARN] fetch stock list failed: {e}")
    return _stock_list

@app.get("/api/search")
def api_search_stocks(q: str = ""):
    """以代號或名稱模糊搜尋上市股票，回傳最多 10 筆"""
    q = q.strip()
    if not q:
        return []
    stocks = _get_stock_list()
    q_lower = q.lower()
    results = []
    for s in stocks:
        sid  = s["stock_id"]
        name = s["name"]
        if sid.startswith(q) or q_lower in name.lower():
            results.append(s)
        if len(results) >= 10:
            break
    return results


@app.get("/api/params")
def api_get_params():
    """取得目前生效的估算權重與訊號門檻"""
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
    """儲存自訂估算權重與訊號門檻"""
    # 只允許已知的 key
    w = {k: float(v) for k, v in body.weights.items()    if k in DEFAULT_WEIGHTS}
    t = {k: float(v) for k, v in body.thresholds.items() if k in DEFAULT_THRESHOLDS}
    save_params(w, t)
    return {"ok": True, "saved_weights": len(w), "saved_thresholds": len(t)}


@app.post("/api/params/reset")
def api_reset_params():
    """重置所有參數為預設值"""
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

@app.post("/api/telegram/push-market")
async def api_tg_push_market(body: MarketRankingBody):
    dt  = body.date or to_twse_date(datetime.today().date())
    top = body.top or 30
    rankings = get_market_rankings(dt=dt, top=top)

    if not rankings:
        raise HTTPException(status_code=404, detail="無排行資料")

    lines = [f"<b>📊 大戶排行 — {dt}</b>", ""]
    for i, r in enumerate(rankings[:20], 1):
        emoji = r.get("signal_emoji", "⚪")
        sid   = r.get("stock_id", "?")
        cum7  = r.get("cum7_whale", 0)
        lines.append(f"{i:2}. {emoji} <b>{sid}</b>  {cum7:+,} 張")

    ok = await tg_send("\n".join(lines))
    if not ok:
        raise HTTPException(status_code=400, detail="Telegram 推播失敗")
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# Push Log API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/push-log")
def api_push_log(limit: int = 20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM push_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════════════════
# Status API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/status")
def api_status():
    conn = get_conn()
    cache_count = conn.execute("SELECT COUNT(*) FROM market_raw").fetchone()[0]
    watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    conn.close()
    csv_count = len(list(DATA_DIR.glob("*.csv")))
    last_refresh = settings_get("last_refresh")
    return {
        "cache_count": cache_count,
        "watchlist_count": watchlist_count,
        "csv_count": csv_count,
        "last_refresh": last_refresh,
        "db_path": str(DB_PATH),
        "data_dir": str(DATA_DIR),
    }


# ════════════════════════════════════════════════════════════════════════════
# 靜態檔 / 首頁
# ════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    html_path = BASE_DIR / "dashboard.html"
    if html_path.exists():
        return FileResponse(html_path)
    return JSONResponse({"error": "dashboard.html not found"}, status_code=404)


# ════════════════════════════════════════════════════════════════════════════
# 啟動
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
