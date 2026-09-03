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
    conn.execute(
        "INSERT OR IGNORE INTO watchlist (stock_id, name, added_at, note) VALUES (?,?,?,?)",
        (sid, name, now, note)
    )
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

    # stocks.csv → 備用股名 + 市場類型
    stocks_df  = get_stock_list()
    csv_names  = dict(zip(stocks_df["stock_id"], stocks_df["stock_name"]))
    mkt_map    = dict(zip(stocks_df["stock_id"], stocks_df["type"]))

    conn = get_conn()
    rows = conn.execute("SELECT stock_id, name, note FROM watchlist ORDER BY added_at").fetchall()
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
            "note":       (r["note"] or "").strip() if "note" in r.keys() else "",
            "close":      price_info.get("close"),
            "change_pct": price_info.get("change_pct"),
            "bb_score":   price_info.get("bb_score", 0.0),
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
