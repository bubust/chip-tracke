"""
server.py — FastAPI 後端
資料來源：Yahoo Finance（同 tw-macd-scan，不受 TWSE 封鎖）
功能：觀察清單 / 策略篩選（全市場）/ 個股資料 / Telegram 推播
"""

import asyncio
import json
import os
import sqlite3
from dotenv import load_dotenv
load_dotenv()  # 本機從 .env 載入；Render 用 dashboard 環境變數
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from warrant.router import router as warrant_router, init_warrant, start_warrant_scheduler, stop_warrant_scheduler

from chip_tracker_v2 import (
    DATA_DIR, DB_PATH,
    get_conn, init_db,
    load_stock_history, update_stocks,
    DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS,
    get_weights, get_thresholds, save_params,
)
from scanner import STRATEGY_PARAMS_SCHEMA
import supabase_store as sb

BASE_DIR = Path(__file__).parent

import time as _time

# ── 觀察清單即時現價快取（MIS）───────────────────────────────────────────────
# MIS z 欄位：每次成交後更新，無新成交時回傳 "-"
# _STOCK_PRICE_CACHE：記住每支股票上次查到的真實 z 值，避免 z="-" 時 fallback 到昨收(y)
_PRICE_ALL: dict = {}           # 相容舊呼叫點用（實際未使用）
_PRICE_ALL_TS: float = 0.0
_PRICE_ALL_TTL: float = 20.0
_STOCK_PRICE_CACHE: dict = {}   # {stock_id: {"close": float, "change_pct": float}}

def _sf_price(s) -> "float | None":
    try:
        v = str(s).replace(",", "").strip()
        return float(v) if v and v not in ("-", "--", "N/A", "+", "-", "除", "X", "") else None
    except Exception:
        return None

async def _fetch_mis_prices(stock_ids: list, mkt_map: dict) -> dict:
    """
    TWSE MIS 即時報價（盤中每筆成交更新）。
    先 GET index.jsp 建立 session，再查 getStockInfo.jsp，讓 z 欄位回傳真實成交價。
    TSE → tse_XXXX.tw；OTC → otc_XXXX.tw
    z（成交價）有值 → 顯示真實漲跌；z="-" → 顯示昨收 y + change_pct=None（前端顯示 --）
    """
    if not stock_ids:
        return {}
    parts = []
    for sid in stock_ids:
        prefix = "otc" if mkt_map.get(sid) == "tpex" else "tse"
        parts.append(f"{prefix}_{sid}.tw")

    MIS_BASE = "https://mis.twse.com.tw"
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    # 分批查詢（每批 4 支），降低單次 batch 觸發 z="-" 的機率
    BATCH = 4
    batches = [parts[i:i+BATCH] for i in range(0, len(parts), BATCH)]
    all_items = []

    async with httpx.AsyncClient(
        timeout=15, follow_redirects=True, verify=False,
        headers={"User-Agent": UA},
    ) as client:
        for batch in batches:
            try:
                r = await client.get(
                    f"{MIS_BASE}/stock/api/getStockInfo.jsp",
                    headers={
                        "Accept":           "application/json, text/javascript, */*; q=0.01",
                        "Referer":          f"{MIS_BASE}/",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    params={
                        "ex_ch": "|".join(batch),
                        "json":  "1",
                        "delay": "0",
                        "_":     str(int(_time.time() * 1000)),
                    },
                )
                r.raise_for_status()
                all_items.extend(r.json().get("msgArray", []))
            except Exception as e:
                print(f"[MIS] batch 查詢失敗: {e}")
    items = all_items
    print(f"[MIS] 回傳 {len(items)} 筆")

    result = {}
    z_ok = 0
    for item in items:
        sid = item.get("c", "")
        if not sid:
            continue
        z = _sf_price(item.get("z"))
        y = _sf_price(item.get("y"))
        if z is not None and y and y > 0:
            # 有真實成交價：更新 cache
            pct = round((z - y) / y * 100, 2)
            entry = {"close": round(z, 2), "change_pct": pct}
            _STOCK_PRICE_CACHE[sid] = entry
            result[sid] = entry
            z_ok += 1
        elif sid in _STOCK_PRICE_CACHE:
            # z="-"（本次無新成交）：用上次查到的真實價，不 fallback 到昨收
            result[sid] = _STOCK_PRICE_CACHE[sid]
        elif y is not None:
            # 從未查過且 z="-"：只好顯示昨收，但不 cache（避免永遠卡住昨收）
            result[sid] = {"close": round(y, 2), "change_pct": None}
    print(f"[MIS] parsed={len(result)} 支，即時z={z_ok} 支，cache命中={len(result)-z_ok} 支")
    return result


async def _fetch_all_prices() -> dict:
    """為相容其他呼叫點保留，實際上回傳空 dict（watchlist 端點改用 _fetch_mis_prices）"""
    return _PRICE_ALL


# ════════════════════════════════════════════════════════════════════════════
# App 初始化
# ════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_warrant()
    start_warrant_scheduler()
    yield
    stop_warrant_scheduler()

app = FastAPI(title="籌碼追蹤系統", lifespan=lifespan)

# 掛載 warrant 路由（prefix=/warrant）
app.include_router(warrant_router, prefix="/warrant")

# 掛載 warrant 前端靜態檔
WARRANT_FRONTEND = BASE_DIR / "warrant-frontend"
app.mount("/warrant/static", StaticFiles(directory=str(WARRANT_FRONTEND)), name="warrant_static")

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
    note: Optional[str] = ""   # 來源策略標注，例如 "S10 漲停"

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
    note = (item.note or "").strip()
    now  = datetime.now().isoformat()
    sb.wl_add(sid, name, now, note)
    conn = get_conn()
    existing = conn.execute("SELECT note FROM watchlist WHERE stock_id=?", (sid,)).fetchone()
    if existing is None:
        # 新股票：直接插入
        conn.execute(
            "INSERT INTO watchlist (stock_id, name, added_at, note) VALUES (?,?,?,?)",
            (sid, name, now, note)
        )
    elif note:
        # 已存在 + 帶有策略來源：更新 note（Supabase 也同步）
        conn.execute("UPDATE watchlist SET note=? WHERE stock_id=?", (note, sid))
        sb.wl_update_note(sid, note)
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

@app.post("/api/watchlist/{stock_id}/memo")
async def api_update_memo(stock_id: str, request: Request):
    """更新個人備註（不影響策略 note 欄位）"""
    body = await request.json()
    memo = str(body.get("memo", "")).strip()
    conn = get_conn()
    conn.execute("UPDATE watchlist SET memo=? WHERE stock_id=?", (memo, stock_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/watchlist/{stock_id}/note")
async def api_update_note(stock_id: str, request: Request):
    """更新來源標籤"""
    body = await request.json()
    note = str(body.get("note", "")).strip()
    sb.wl_update_note(stock_id, note)
    conn = get_conn()
    conn.execute("UPDATE watchlist SET note=? WHERE stock_id=?", (note, stock_id))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/watchlist/prices")
async def api_watchlist_prices():
    """輕量端點：MIS 即時現價（先建 session），供自動刷新用。"""
    from yahoo_price import get_stock_list
    conn = get_conn()
    rows = conn.execute("SELECT stock_id FROM watchlist").fetchall()
    conn.close()
    stock_ids = list({r["stock_id"] for r in rows})
    stocks_df = get_stock_list()
    mkt_map = dict(zip(stocks_df["stock_id"], stocks_df["type"]))
    return await _fetch_mis_prices(stock_ids, mkt_map)

@app.get("/api/watchlist/summary")
async def api_watchlist_summary():
    from yahoo_price import get_stock_list

    # Supabase 優先：Render 重啟後 SQLite 是空的，從 Supabase 同步回來
    sb_rows = sb.wl_list()
    if sb_rows is not None and sb_rows:
        conn = get_conn()
        local_ids = {r["stock_id"] for r in conn.execute("SELECT stock_id FROM watchlist").fetchall()}
        for r in sb_rows:
            if r["stock_id"] not in local_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO watchlist (stock_id, name, added_at, note) VALUES (?,?,?,?)",
                    (r["stock_id"], r.get("name", ""), r.get("added_at", ""), r.get("note", ""))
                )
        conn.commit()
        conn.close()

    # stocks.csv → 備用股名 + 市場類型（OTC 補查 MIS 用）
    stocks_df  = get_stock_list()
    csv_names  = dict(zip(stocks_df["stock_id"], stocks_df["stock_name"]))
    mkt_map    = dict(zip(stocks_df["stock_id"], stocks_df["type"]))

    conn = get_conn()
    rows = conn.execute("SELECT stock_id, name, note, memo FROM watchlist ORDER BY added_at").fetchall()
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

    # 現價：MIS 即時報價（先建 session，TSE + OTC 一起查）
    latest_prices = await _fetch_mis_prices(stock_ids, mkt_map)

    result = []
    for r in rows:
        sid  = r["stock_id"]
        name = names.get(sid, "")
        records = load_stock_history(sid)
        price_info = latest_prices.get(sid, {})
        item: dict = {
            "stock_id":   sid,
            "name":       name,
            "note":       (r["note"] or "").strip() if "note" in r.keys() else "",
            "memo":       (r["memo"] or "").strip() if "memo" in r.keys() else "",
            "close":      price_info.get("close"),
            "change_pct": price_info.get("change_pct"),
            "bb_score":   price_info.get("bb_score", 0.0),
            "stage":      price_info.get("stage", {"code": "unknown", "label": "—", "color": "muted", "desc": ""}),
        }
        if records:
            latest = records[-1]
            last7  = records[-7:]
            cum7   = sum(r2.get("whale_flow_lots", 0) for r2 in last7)
            # 連續買超天數（從 CSV/Supabase 讀，若無則從 records 計算）
            consec_buy = int(latest.get("consecutive_buy", 0) or 0)
            # 連續賣超天數（whale < 0 的連續天數，即時計算）
            consec_sell = 0
            for r2 in reversed(records):
                if (r2.get("whale_flow_lots", 0) or 0) < 0:
                    consec_sell += 1
                else:
                    break
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
                "consecutive_buy":     consec_buy,
                "consecutive_sell":    consec_sell,
            })
        else:
            item["has_data"] = False
        result.append(item)

    # 注入 TDCC 千張大戶週資料（從 SQLite 快取讀取，不會發起網路請求）
    from tdcc_chip import get_tdcc_data
    tdcc_map = get_tdcc_data()
    for item in result:
        t = tdcc_map.get(item["stock_id"])
        if t:
            item["kpct"]        = t["current_pct"]
            item["kpct_prev"]   = t["prev_pct"]
            item["kpct_change"] = t["change"]
            item["kpct_date"]   = t["date"]
        else:
            item["kpct"]        = None
            item["kpct_prev"]   = None
            item["kpct_change"] = None
            item["kpct_date"]   = None
    return result


# ════════════════════════════════════════════════════════════════════════════
# Refresh API（觀察清單個股籌碼更新）
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/refresh")
async def api_refresh(body: RefreshBody):
    sb_ids = sb.wl_get_ids()
    if sb_ids:  # 非空才採用 Supabase，空或 None 都 fallback 到 SQLite
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
# 全市場大戶排行 API（TWSE T86 + STOCK_DAY_ALL，單日一次拿全部）
# ════════════════════════════════════════════════════════════════════════════

_UA_TWSE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

@app.get("/api/market/scan")
async def api_market_scan(top: int = 50):
    """全市場今日法人買賣超排行（TWSE 上市，T86 三大法人 + STOCK_DAY_ALL 股價）"""
    from datetime import date, timedelta
    from chip_tracker_v2 import is_trading_day

    timeout_cfg = httpx.Timeout(20.0, connect=8.0)

    # 股價清單（只抓一次）
    price_map: dict = {}
    chip_map: dict = {}
    used_date_str: str = ""

    async with httpx.AsyncClient(
        headers={"User-Agent": _UA_TWSE, "Referer": "https://www.twse.com.tw/"},
        timeout=timeout_cfg,
        verify=False,
        follow_redirects=True,
    ) as client:
        # 先抓股價（與日期無關，單次即可）
        try:
            price_r = await client.get(
                "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
            )
            if price_r.status_code == 200:
                for item in price_r.json():
                    sid = str(item.get("Code", "")).strip()
                    if not sid:
                        continue
                    try:
                        close_s = str(item.get("ClosingPrice", "0")).replace(",", "")
                        price_map[sid] = {
                            "name":  item.get("Name", ""),
                            "close": float(close_s) if close_s not in ("", "--", "-") else None,
                        }
                    except Exception:
                        pass
        except Exception:
            pass

        # T86 嘗試最近 5 個交易日（今日優先，若未公布則往前找）
        attempt_dt = date.today()
        for _ in range(5):
            if not is_trading_day(attempt_dt):
                attempt_dt -= timedelta(days=1)
                continue
            dt_str = attempt_dt.strftime("%Y%m%d")
            try:
                t86_r = await client.get(
                    "https://www.twse.com.tw/rwd/zh/fund/T86",
                    params={"date": dt_str, "selectType": "ALL", "response": "json"},
                )
                if t86_r.status_code == 200:
                    t86 = t86_r.json()
                    if t86.get("stat") == "OK" and t86.get("data"):
                        used_date_str = dt_str
                        for row in t86.get("data", []):
                            try:
                                sid = str(row[0]).strip()

                                def _f(v):
                                    return float(str(v).replace(",", "")) / 1000  # 股 → 張

                                foreign = _f(row[4])
                                trust   = _f(row[10])
                                dealer  = _f(row[14])
                                whale   = foreign * 1.0 + trust * 0.95 + dealer * 0.70
                                chip_map[sid] = {
                                    "foreign_lots":    round(foreign),
                                    "trust_lots":      round(trust),
                                    "whale_flow_lots": round(whale),
                                }
                            except Exception:
                                pass
                        break  # 成功取得資料，停止重試
            except Exception:
                pass
            attempt_dt -= timedelta(days=1)

    if not chip_map:
        raise HTTPException(status_code=503, detail="無法取得 T86 法人資料（TWSE 尚未公布或 IP 封鎖），請稍後再試")

    # 合併結果
    from yahoo_price import get_stock_list
    stocks_df = get_stock_list()
    csv_names = dict(zip(stocks_df["stock_id"], stocks_df["stock_name"]))

    merged = []
    for sid, chip in chip_map.items():
        price_info = price_map.get(sid, {})
        name = price_info.get("name") or csv_names.get(sid, "")
        merged.append({
            "stock_id":        sid,
            "name":            name,
            "close":           price_info.get("close"),
            "foreign_lots":    chip["foreign_lots"],
            "trust_lots":      chip["trust_lots"],
            "whale_flow_lots": chip["whale_flow_lots"],
            "retail_flow_lots": 0,
            "signal_emoji":    "⚪",
            "signal_title":    "—",
            "signal_level":    0,
        })

    merged.sort(key=lambda x: x["whale_flow_lots"], reverse=True)
    return {
        "date":        used_date_str,
        "total":       len(merged),
        "top_buyers":  merged[:top],
        "top_sellers": list(reversed(merged))[:top],
    }


# ════════════════════════════════════════════════════════════════════════════
# Stock Query API
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/stock/{stock_id}/ohlcv")
def api_stock_ohlcv(stock_id: str):
    """回傳個股 OHLCV 日線資料（供 K 線圖使用）"""
    from yahoo_price import fetch_yahoo, get_stock_list
    stocks = get_stock_list()
    row = stocks[stocks["stock_id"] == stock_id]
    market = str(row.iloc[0]["type"]) if not row.empty else "twse"
    df = fetch_yahoo(stock_id, market)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"{stock_id} 無法取得資料")
    return df.tail(300).fillna(0).to_dict(orient="records")

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
# ════════════════════════════════════════════════════════════════════════════
# TDCC 千張大戶週資料
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/tdcc/refresh")
async def api_tdcc_refresh(background_tasks: BackgroundTasks):
    """觸發 TDCC 官方 OpenAPI 更新（全市場，無 IP 限制）"""
    from tdcc_chip import refresh_for_stocks
    background_tasks.add_task(refresh_for_stocks)
    return {"ok": True, "message": "已開始從 TDCC 官方 OpenAPI 下載全市場資料（~9.7MB）"}

@app.post("/api/chip/import")
async def api_chip_import(request: Request):
    """
    接收本機上傳的 TDCC 千張大戶週資料。
    Body: {"date": "20260904", "data": {"2330": 78.5, "2317": 45.2, ...}}
    """
    from tdcc_chip import _save
    body = await request.json()
    date_str = str(body.get("date", "")).strip()
    data     = body.get("data", {})
    if not date_str or not data:
        raise HTTPException(status_code=400, detail="缺少 date 或 data")
    if len(date_str) != 8 or not date_str.isdigit():
        raise HTTPException(status_code=400, detail="date 格式應為 YYYYMMDD")
    clean = {str(k): float(v) for k, v in data.items() if v is not None}
    _save(date_str, clean)
    return {"ok": True, "date": date_str, "count": len(clean)}

@app.get("/api/stock/{stock_id}/tdcc")
def api_stock_tdcc(stock_id: str):
    """回傳單支股票的千張大戶歷史（最近 12 週）"""
    from tdcc_chip import get_stock_tdcc_history
    history = get_stock_tdcc_history(stock_id, weeks=12)
    return {"stock_id": stock_id, "history": history}

@app.post("/api/chip/refresh-watchlist")
async def api_chip_refresh_watchlist(background_tasks: BackgroundTasks):
    """用 FinMind 更新觀察清單股票的千張大戶資料（Plan C 手動觸發）"""
    from tdcc_chip import refresh_for_stocks
    sb_ids = sb.wl_get_ids()
    if sb_ids:  # 非空才採用 Supabase，空或 None 都 fallback 到 SQLite
        stock_ids = sb_ids
    else:
        conn = get_conn()
        rows = conn.execute("SELECT stock_id FROM watchlist").fetchall()
        conn.close()
        stock_ids = [r["stock_id"] for r in rows]
    if not stock_ids:
        return {"ok": False, "message": "觀察清單為空"}
    background_tasks.add_task(refresh_for_stocks, stock_ids)
    return {"ok": True, "count": len(stock_ids), "message": f"已開始更新 {len(stock_ids)} 支股票"}

@app.get("/api/tdcc/status")
def api_tdcc_status():
    """回傳 TDCC 快取狀態"""
    from tdcc_chip import get_tdcc_data, DB_PATH
    import sqlite3
    data = get_tdcc_data()
    # 取各日期的快取筆數
    date_counts = {}
    try:
        c = sqlite3.connect(DB_PATH)
        rows = c.execute("SELECT date, COUNT(*) FROM tdcc_holding GROUP BY date ORDER BY date DESC LIMIT 5").fetchall()
        date_counts = {r[0]: r[1] for r in rows}
        c.close()
    except Exception:
        pass
    if not data:
        return {"loaded": False, "count": 0, "date": None, "cache_by_date": date_counts}
    sample = next(iter(data.values()))
    return {"loaded": True, "count": len(data), "date": sample.get("date"), "cache_by_date": date_counts}

@app.get("/api/tdcc/test/{stock_id}")
async def api_tdcc_test(stock_id: str):
    """測試 TDCC 官方 OpenAPI（debug 用，無 IP 限制）"""
    from tdcc_chip import TDCC_OPENAPI, _parse_openapi_rows
    try:
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(TDCC_OPENAPI)
            r.raise_for_status()
            rows = r.json()
        date_str, data = _parse_openapi_rows(rows)
        kpct = data.get(stock_id, 0.0)
        available_dates = []
        try:
            import sqlite3
            from tdcc_chip import DB_PATH
            c = sqlite3.connect(DB_PATH)
            available_dates = [r[0] for r in c.execute(
                "SELECT DISTINCT date FROM tdcc_holding ORDER BY date DESC LIMIT 3"
            ).fetchall()]
            c.close()
        except Exception:
            pass
        return {"ok": True, "stock_id": stock_id, "date": date_str, "kpct": kpct, "available_dates": available_dates}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# 全市場策略掃描 API（Yahoo Finance）
# ════════════════════════════════════════════════════════════════════════════

def _load_strategy_params() -> dict:
    """從 DB 讀取所有策略參數設定，回傳 {strategy_key: {param_key: value}}"""
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'sp_%'").fetchall()
    conn.close()
    result = {}
    for r in rows:
        sk = r['key'][3:]   # 去掉 'sp_' prefix
        try:
            result[sk] = json.loads(r['value'])
        except Exception:
            pass
    return result

@app.post("/api/screen/run")
async def api_screen_run(background_tasks: BackgroundTasks):
    from yahoo_price import get_scan_status, run_market_scan
    status = get_scan_status()
    if status["running"]:
        return {"ok": False, "message": "掃描中，請稍候"}
    strategy_params = _load_strategy_params()
    background_tasks.add_task(run_market_scan, strategy_params=strategy_params)
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

@app.get("/api/stock-market/{stock_id}")
def api_stock_market(stock_id: str):
    """回傳單支股票的市場類型 twse/tpex"""
    try:
        from yahoo_price import get_stock_list
        stocks = get_stock_list()
        row = stocks[stocks["stock_id"] == stock_id]
        if row.empty:
            return {"market": "twse"}   # 預設上市
        return {"market": str(row.iloc[0]["type"])}
    except Exception:
        return {"market": "twse"}

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
        return stocks[mask].head(10)[["stock_id","stock_name","type"]].rename(
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

@app.get("/api/params/strategies")
def get_strategy_params():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'sp_%'").fetchall()
    conn.close()
    saved = {}
    for r in rows:
        sk = r['key'][3:]   # 去掉 'sp_' prefix
        try:
            saved[sk] = json.loads(r['value'])
        except Exception:
            pass
    result = {}
    for skey, schema in STRATEGY_PARAMS_SCHEMA.items():
        saved_vals = saved.get(skey, {})
        params = {}
        for field in schema:
            params[field['key']] = saved_vals.get(field['key'], field['default'])
        result[skey] = {"schema": schema, "values": params}
    return result

@app.put("/api/params/strategies/{strategy_key}")
async def put_strategy_params(strategy_key: str, request: Request):
    body = await request.json()
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (f"sp_{strategy_key}", json.dumps(body))
    )
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

@app.get("/api/debug/yahoo/{stock_id}")
async def debug_yahoo(stock_id: str):
    """Debug: 查看 Yahoo 原始 meta + 解析後 DataFrame 的最後幾行，確認補丁是否正確觸發"""
    import asyncio, time as _time
    from yahoo_price import get_stock_list
    import httpx, datetime as _dt

    stocks = get_stock_list()
    row = stocks[stocks["stock_id"] == stock_id]
    market = "twse" if row.empty else str(row.iloc[0]["type"])
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]

    now = int(_time.time())
    p1  = now - 730 * 86400  # 2y
    params = {"interval": "1d", "period1": p1, "period2": now}

    async with httpx.AsyncClient(verify=False, timeout=15,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as client:
        for suffix in suffixes:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
            try:
                r = await client.get(url, params=params)
                raw = r.json()
                result = (raw.get("chart", {}).get("result") or [{}])[0]
                meta   = result.get("meta", {})
                from yahoo_price import _parse_yahoo_json
                df = _parse_yahoo_json(raw)
                if df.empty:
                    continue

                rmt = meta.get("regularMarketTime", 0)
                rmp = meta.get("regularMarketPrice")
                rmo = meta.get("regularMarketOpen")
                rmh = meta.get("regularMarketDayHigh")
                rml = meta.get("regularMarketDayLow")
                rmv = meta.get("regularMarketVolume")
                # regularMarketTime 轉台灣時間
                rmt_tw = (_dt.datetime.utcfromtimestamp(int(rmt)) + _dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if rmt else None

                last5 = df.tail(5)[["date","open","high","low","close","volume"]].to_dict("records")
                return {
                    "stock_id":   stock_id,
                    "suffix":     suffix,
                    "total_rows": len(df),
                    "last_date":  df.iloc[-1]["date"],
                    "meta": {
                        "regularMarketTime_tw": rmt_tw,
                        "regularMarketOpen":    rmo,
                        "regularMarketDayHigh": rmh,
                        "regularMarketDayLow":  rml,
                        "regularMarketPrice":   rmp,
                        "regularMarketVolume":  rmv,
                    },
                    "last5_rows": last5,
                    "last_is_red_k": bool(float(df.iloc[-1]["close"]) > float(df.iloc[-1]["open"])) if df.iloc[-1]["open"] else None,
                }
            except Exception as e:
                return {"error": str(e), "suffix": suffix}
    return {"error": "no data"}


@app.get("/api/debug/bb/{stock_id}")
async def debug_bb(stock_id: str):
    """Debug: 查看 Yahoo 抓到的原始資料及 BB 計算過程"""
    import asyncio, time
    from yahoo_price import _fetch_yahoo_async, get_stock_list
    from scanner import calc_bb_score
    import httpx

    stocks = get_stock_list()
    row = stocks[stocks["stock_id"] == stock_id]
    market = "twse" if row.empty else str(row.iloc[0]["type"])
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]

    sem = asyncio.Semaphore(5)
    now = int(time.time())
    p1 = now - 365 * 86400
    params = {"interval": "1d", "period1": p1, "period2": now}
    async with httpx.AsyncClient(verify=False, timeout=15) as client:
        for suffix in suffixes:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
            try:
                r = await client.get(url, params=params)
                from yahoo_price import _parse_yahoo_json
                df = _parse_yahoo_json(r.json())
                if df.empty: continue
                closes = df["close"]
                ma20 = float(closes.rolling(20).mean().iloc[-1])
                std20 = float(closes.rolling(20).std(ddof=0).iloc[-1])
                last_close = float(df.iloc[-1]["close"])
                last_date = df.iloc[-1]["date"]
                raw_score = (last_close - ma20) / (2 * std20) * 10 if std20 > 0 else 0
                return {
                    "stock_id": stock_id, "suffix": suffix,
                    "total_rows": len(df),
                    "last_date": last_date,
                    "last_close": round(last_close, 2),
                    "ma20": round(ma20, 2),
                    "std20": round(std20, 4),
                    "upper_band": round(ma20 + 2*std20, 2),
                    "lower_band": round(ma20 - 2*std20, 2),
                    "raw_score": round(raw_score, 2),
                    "bb_score": calc_bb_score(df),
                    "last_10_closes": [round(float(x), 2) for x in closes.tail(10).tolist()],
                }
            except Exception as e:
                return {"error": str(e)}
    return {"error": "no data"}

@app.get("/api/debug/prices")
async def debug_prices():
    """Debug: 直接呼叫各現價來源，回傳原始結構與解析結果，方便確認 Render 上可連到哪些 API"""
    out = {}
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.twse.com.tw/",
    }
    async with httpx.AsyncClient(headers=hdrs, timeout=20, follow_redirects=True, verify=False) as client:
        def _inspect(label, r_status, jdata):
            """解析回傳的 JSON，找出所有可能藏資料的位置"""
            info = {"status": r_status, "top_keys": list(jdata.keys()),
                    "stat": jdata.get("stat"), "date": jdata.get("date")}
            # 檢查 tables 陣列
            tables = jdata.get("tables") or []
            info["tables_count"] = len(tables)
            info["tables_summary"] = []
            all_rows = []
            for i, tbl in enumerate(tables):
                if not isinstance(tbl, dict):
                    info["tables_summary"].append({"i": i, "type": str(type(tbl))})
                    continue
                tbl_data = tbl.get("data") or tbl.get("rows") or []
                info["tables_summary"].append({
                    "i": i,
                    "title": tbl.get("title", ""),
                    "keys": list(tbl.keys()),
                    "data_rows": len(tbl_data),
                    "fields": tbl.get("fields", [])[:5],
                    "sample": tbl_data[0] if tbl_data else None,
                })
                all_rows.extend(tbl_data)
            # 也檢查根層的 data/data8/aaData
            for k in ["data", "data8", "data9", "aaData"]:
                v = jdata.get(k) or []
                if v:
                    info[f"root_{k}_count"] = len(v)
                    info[f"root_{k}_sample"] = v[0] if v else None
            info["total_rows_found"] = len(all_rows)
            return info

        # MI_INDEX
        try:
            r = await client.get(
                "https://www.twse.com.tw/exchangeReport/MI_INDEX",
                params={"response": "json", "type": "ALLBUT0999"},
            )
            jdata = r.json() if r.status_code == 200 else {}
            out["mi_index"] = _inspect("mi_index", r.status_code, jdata)
        except Exception as e:
            out["mi_index"] = {"error": str(e)}

        # MIS — 嘗試多個 session 入口，看哪個能取得 cookie
        MIS_BASE = "https://mis.twse.com.tw"
        UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        mis_entries = [
            f"{MIS_BASE}/",
            f"{MIS_BASE}/stock/",
            f"{MIS_BASE}/stock/fibest.jsp",
            f"{MIS_BASE}/stock/fibest.jsp?lang=zh_TW",
        ]
        out["mis_session"] = {}
        for entry_url in mis_entries:
            try:
                async with httpx.AsyncClient(timeout=12, follow_redirects=True, verify=False,
                                             headers={"User-Agent": UA}) as mis_client:
                    sess_r = await mis_client.get(entry_url,
                        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
                    cookies_got = dict(mis_client.cookies)
                    price_r = await mis_client.get(
                        f"{MIS_BASE}/stock/api/getStockInfo.jsp",
                        headers={"Accept": "application/json, text/javascript, */*; q=0.01",
                                 "Referer": entry_url,
                                 "X-Requested-With": "XMLHttpRequest"},
                        params={"ex_ch": "tse_2303.tw|tse_3481.tw|otc_5314.tw", "json": "1", "delay": "0",
                                "_": str(int(_time.time() * 1000))},
                    )
                    items = price_r.json().get("msgArray", []) if price_r.status_code == 200 else []
                    out["mis_session"][entry_url] = {
                        "session_status": sess_r.status_code,
                        "cookies": list(cookies_got.keys()),
                        "price_status": price_r.status_code,
                        "z_values": {i.get("c"): i.get("z") for i in items},
                    }
            except Exception as e:
                out["mis_session"][entry_url] = {"error": str(e)}

        # FinMind — 測試今日收盤 + 分鐘資料
        import datetime as _dt
        today_str = _dt.date.today().strftime("%Y-%m-%d")
        FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiYnVidXN0IiwiZW1haWwiOiJidWJ1c3RAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.LcLL157_bH6YbABE7JOlg0cAEwwzOV6GfJA6uK2cvIA"
        for fm_dataset in ["TaiwanStockPrice", "TaiwanStockPriceMinute"]:
            try:
                fm_r = await client.get(
                    "https://api.finmindtrade.com/api/v4/data",
                    params={"dataset": fm_dataset, "stock_id": "2303",
                            "start_date": today_str, "token": FINMIND_TOKEN},
                )
                fm_data = fm_r.json() if fm_r.status_code == 200 else {}
                fm_rows = fm_data.get("data", [])
                out[f"finmind_{fm_dataset}"] = {
                    "status": fm_r.status_code,
                    "rows": len(fm_rows),
                    "latest": fm_rows[-1] if fm_rows else None,
                    "msg": fm_data.get("msg", ""),
                }
            except Exception as e:
                out[f"finmind_{fm_dataset}"] = {"error": str(e)}

        # Fugle — 台灣券商即時 API（demo key 有限制但免費）
        for fugle_url in [
            "https://api.fugle.tw/realtime/v0.3/intraday/quote?symbolId=2303&apiToken=demo",
            "https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/2303",
        ]:
            try:
                fg_r = await client.get(fugle_url, headers={"X-API-KEY": "demo"})
                fg_data = fg_r.json() if fg_r.status_code == 200 else {}
                out[f"fugle_{fugle_url.split('/')[-1].split('?')[0]}"] = {
                    "status": fg_r.status_code,
                    "keys": list(fg_data.keys())[:10],
                    "sample": str(fg_data)[:300],
                }
            except Exception as e:
                out[f"fugle_{fugle_url.split('/')[-1].split('?')[0]}"] = {"error": str(e)}

    # 也順帶重置快取，強制下次重新抓
    global _PRICE_ALL_TS
    _PRICE_ALL_TS = 0.0
    out["cache_reset"] = True
    return out


@app.get("/")
def root():
    html_path = BASE_DIR / "dashboard.html"
    if html_path.exists():
        return FileResponse(html_path)
    return JSONResponse({"error": "dashboard.html not found"}, status_code=404)

@app.get("/warrant/")
def warrant_index():
    return FileResponse(str(WARRANT_FRONTEND / "index.html"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
