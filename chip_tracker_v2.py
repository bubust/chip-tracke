"""
chip_tracker_v2.py — 台股籌碼追蹤核心引擎
- 非同步抓取 TWSE 4 個 bulk endpoints
- SQLite cache（同日期不重複打）
- 估算千張大戶買賣方向
"""

import asyncio
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

# ── 目錄設定 ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "chip_data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "cache.db"

# ── TWSE API endpoints ────────────────────────────────────────────────────────
TWSE_BASE = "https://www.twse.com.tw/rwd/zh"

ENDPOINTS = {
    "t86":       f"{TWSE_BASE}/fund/T86",
    "margin":    f"{TWSE_BASE}/marginTrading/MI_MARGN",
    "sbl":       f"{TWSE_BASE}/SBL/TWT93U",
    "day_trade": f"{TWSE_BASE}/trading/TWTB4U",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.twse.com.tw/",
}

# ── 估算權重 ──────────────────────────────────────────────────────────────────
WEIGHTS = {
    "foreign":        1.00,
    "foreign_dealer": 0.85,
    "trust":          0.95,
    "dealer_self":    0.70,
    "dealer_hedge":   0.10,
    "sbl":           -0.80,
    "day_trade":     -0.50,
}


# ════════════════════════════════════════════════════════════════════════════
# SQLite helpers
# ════════════════════════════════════════════════════════════════════════════

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS market_raw (
            date    TEXT NOT NULL,
            dataset TEXT NOT NULL,
            payload TEXT NOT NULL,
            fetched TEXT NOT NULL,
            PRIMARY KEY (date, dataset)
        );

        CREATE TABLE IF NOT EXISTS calibration (
            stock_id     TEXT NOT NULL,
            period_end   TEXT NOT NULL,
            period_days  INTEGER,
            est_change   REAL,
            actual_change REAL,
            error_pct    REAL,
            PRIMARY KEY (stock_id, period_end)
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            stock_id TEXT PRIMARY KEY,
            name     TEXT,
            added_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS push_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id     TEXT,
            signal_emoji TEXT,
            signal_title TEXT,
            pushed_at    TEXT,
            ok           INTEGER
        );
    """)
    conn.commit()
    conn.close()


class Cache:
    """SQLite cache for market raw data."""

    def get(self, dt: str, dataset: str) -> Optional[dict]:
        conn = get_conn()
        row = conn.execute(
            "SELECT payload FROM market_raw WHERE date=? AND dataset=?",
            (dt, dataset)
        ).fetchone()
        conn.close()
        if row:
            return json.loads(row["payload"])
        return None

    def put(self, dt: str, dataset: str, payload: dict):
        conn = get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO market_raw (date, dataset, payload, fetched)
               VALUES (?, ?, ?, ?)""",
            (dt, dataset, json.dumps(payload, ensure_ascii=False),
             datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def count(self) -> int:
        conn = get_conn()
        n = conn.execute("SELECT COUNT(*) FROM market_raw").fetchone()[0]
        conn.close()
        return n


cache = Cache()


# ════════════════════════════════════════════════════════════════════════════
# 日期工具
# ════════════════════════════════════════════════════════════════════════════

def is_trading_day(d: date) -> bool:
    """簡易判斷交易日（只擋週末，國定假日待補）"""
    return d.weekday() < 5


def trading_dates(start: date, end: date) -> list[date]:
    """產生指定範圍內的交易日清單"""
    days = []
    cur = start
    while cur <= end:
        if is_trading_day(cur):
            days.append(cur)
        cur += timedelta(days=1)
    return days


def to_twse_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def last_n_trading_dates(n: int, end: date = None) -> list[date]:
    if end is None:
        end = date.today()
    result = []
    cur = end
    while len(result) < n:
        if is_trading_day(cur):
            result.append(cur)
        cur -= timedelta(days=1)
    return list(reversed(result))


# ════════════════════════════════════════════════════════════════════════════
# TWSE 抓取函式
# ════════════════════════════════════════════════════════════════════════════

async def _fetch_json(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    try:
        resp = await client.get(url, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[WARN] fetch failed {url} {params}: {e}")
        return {}


async def fetch_t86(client: httpx.AsyncClient, dt: str) -> dict:
    """三大法人個股買賣超 (T86)"""
    cached = cache.get(dt, "t86")
    if cached is not None:
        return cached
    data = await _fetch_json(client, ENDPOINTS["t86"], {"response": "json", "date": dt, "selectType": "ALL"})
    cache.put(dt, "t86", data)
    return data


async def fetch_margin(client: httpx.AsyncClient, dt: str) -> dict:
    """融資融券餘額 (MI_MARGN)"""
    cached = cache.get(dt, "margin")
    if cached is not None:
        return cached
    data = await _fetch_json(client, ENDPOINTS["margin"], {"response": "json", "date": dt, "selectType": "ALL"})
    cache.put(dt, "margin", data)
    return data


async def fetch_sbl(client: httpx.AsyncClient, dt: str) -> dict:
    """借券賣出餘額 (TWT93U)"""
    cached = cache.get(dt, "sbl")
    if cached is not None:
        return cached
    data = await _fetch_json(client, ENDPOINTS["sbl"], {"response": "json", "date": dt})
    cache.put(dt, "sbl", data)
    return data


async def fetch_day_trade(client: httpx.AsyncClient, dt: str) -> dict:
    """當沖統計 (TWTB4U)"""
    cached = cache.get(dt, "day_trade")
    if cached is not None:
        return cached
    data = await _fetch_json(client, ENDPOINTS["day_trade"], {"response": "json", "date": dt, "selectType": "ALL"})
    cache.put(dt, "day_trade", data)
    return data


# ════════════════════════════════════════════════════════════════════════════
# 欄位解析工具
# ════════════════════════════════════════════════════════════════════════════

def find_field(row: list, fields: list, headers: list) -> Optional[float]:
    """在 headers 中搜尋欄位名稱，回傳對應的數值（去除逗號）"""
    for field in fields:
        for i, h in enumerate(headers):
            if field in h:
                try:
                    val = row[i].replace(",", "").strip()
                    return float(val) if val not in ("", "-", "--") else 0.0
                except (ValueError, IndexError):
                    return 0.0
    return None


def _to_float(val: str) -> float:
    """將帶逗號的數字字串轉 float，失敗回傳 0"""
    try:
        return float(str(val).replace(",", "").strip())
    except Exception:
        return 0.0


def parse_t86(data: dict, stock_id: str) -> dict:
    """
    解析三大法人資料，使用固定欄位索引（TWSE T86 格式穩定）
    Col: 0=代號 1=名稱
         2=外資買  3=外資賣  4=外資淨(foreign)
         5=外資自營買 6=外資自營賣 7=外資自營淨(foreign_dealer)
         8=投信買  9=投信賣  10=投信淨(trust)
         11=自營合計
         12=自營自行買 13=自營自行賣 14=自營自行淨(dealer_self)
         15=自營避險買 16=自營避險賣 17=自營避險淨(dealer_hedge)
    """
    result = {k: 0.0 for k in ["foreign", "foreign_dealer", "trust", "dealer_self", "dealer_hedge"]}
    if not data or data.get("stat") != "OK":
        return result

    for row in data.get("data", []):
        if not row or row[0] != stock_id:
            continue
        if len(row) >= 18:
            result["foreign"]        = _to_float(row[4])
            result["foreign_dealer"] = _to_float(row[7])
            result["trust"]          = _to_float(row[10])
            result["dealer_self"]    = _to_float(row[14])
            result["dealer_hedge"]   = _to_float(row[17])
        break

    return result


def parse_margin(data: dict, stock_id: str) -> dict:
    """
    解析融資融券，回傳融資餘額變化（張）
    MI_MARGN 回傳 tables 陣列，融資表在 tables[1]（tables[0] 是融券）
    Col: 0=代號 1=名稱 2=融資買進 3=融資賣出 4=現金償還
         5=融資餘額(今日) 6=前日融資餘額 → 增減 = row[5] - row[6]
    """
    result = {"margin_chg": 0.0}
    if not data or data.get("stat") != "OK":
        return result

    tables = data.get("tables", [])
    # 優先找 tables[1]（融資表），其次 tables[0]，最後直接 data
    candidates = []
    if len(tables) >= 2:
        candidates = [tables[1], tables[0]]
    elif len(tables) == 1:
        candidates = [tables[0]]

    for tbl in candidates:
        for row in tbl.get("data", []):
            if not row or row[0] != stock_id:
                continue
            if len(row) >= 7:
                today = _to_float(row[5])
                prev  = _to_float(row[6])
                result["margin_chg"] = today - prev
            return result

    # fallback：直接 data
    for row in data.get("data", []):
        if not row or row[0] != stock_id:
            continue
        if len(row) >= 7:
            result["margin_chg"] = _to_float(row[5]) - _to_float(row[6])
        break

    return result


def parse_sbl_day(today_data: dict, prev_data: dict, stock_id: str) -> dict:
    """借券：今日 - 昨日 = 增減（股）"""
    result = {"sbl_chg": 0.0}

    def get_balance(data: dict) -> float:
        if not data or data.get("stat") != "OK":
            return 0.0
        rows = data.get("data", [])
        fields = data.get("fields", [])
        for row in rows:
            if not row or row[0] != stock_id:
                continue
            v = find_field(row, ["借券賣出餘額", "借券賣出數量"], fields)
            return v or 0.0
        return 0.0

    today_bal = get_balance(today_data)
    prev_bal  = get_balance(prev_data)
    result["sbl_chg"] = today_bal - prev_bal
    return result


def parse_day_trade(data: dict, stock_id: str) -> dict:
    """當沖：估算法人當沖量（股）"""
    result = {"day_trade_est": 0.0}
    if not data or data.get("stat") != "OK":
        return result

    fields = data.get("fields", [])
    rows   = data.get("data", [])

    for row in rows:
        if not row or row[0] != stock_id:
            continue
        v = find_field(row, ["當沖買入成交股數", "當沖賣出成交股數", "當沖成交股數"], fields)
        result["day_trade_est"] = v or 0.0
        break

    return result


# ════════════════════════════════════════════════════════════════════════════
# 估算核心
# ════════════════════════════════════════════════════════════════════════════

def estimate(t86: dict, margin: dict, sbl: dict, day_trade: dict) -> dict:
    """
    加權計算大戶/散戶流向
    回傳 dict with: whale_flow_lots, retail_flow_lots, concentration_index
    """
    foreign        = t86.get("foreign",        0.0)
    foreign_dealer = t86.get("foreign_dealer", 0.0)
    trust          = t86.get("trust",          0.0)
    dealer_self    = t86.get("dealer_self",    0.0)
    dealer_hedge   = t86.get("dealer_hedge",   0.0)
    sbl_chg        = sbl.get("sbl_chg",        0.0)
    day_trade_est  = day_trade.get("day_trade_est", 0.0)
    margin_chg     = margin.get("margin_chg",   0.0)

    whale_shares = (
        foreign        * WEIGHTS["foreign"]        +
        foreign_dealer * WEIGHTS["foreign_dealer"] +
        trust          * WEIGHTS["trust"]          +
        dealer_self    * WEIGHTS["dealer_self"]    +
        dealer_hedge   * WEIGHTS["dealer_hedge"]   +
        sbl_chg        * WEIGHTS["sbl"]            +
        day_trade_est  * WEIGHTS["day_trade"]
    )

    whale_flow_lots  = round(whale_shares / 1000)
    retail_flow_lots = margin_chg  # 融資餘額變化（張）

    denom = abs(whale_flow_lots) + abs(retail_flow_lots) + 1
    concentration_index = whale_flow_lots / denom

    return {
        "whale_flow_lots":     whale_flow_lots,
        "retail_flow_lots":    retail_flow_lots,
        "concentration_index": round(concentration_index, 4),
        # 原始分項（供除錯）
        "_foreign":        round(foreign / 1000),
        "_trust":          round(trust / 1000),
        "_dealer_self":    round(dealer_self / 1000),
        "_sbl_chg":        round(sbl_chg / 1000),
        "_day_trade_est":  round(day_trade_est / 1000),
    }


# ════════════════════════════════════════════════════════════════════════════
# 訊號判讀
# ════════════════════════════════════════════════════════════════════════════

def classify_signal(cum7_whale: float, concentration: float, cum7_retail: float) -> dict:
    """
    依 7 日累計大戶流向 + 集中度 判斷訊號
    """
    divergence = cum7_whale < -1500 and cum7_retail > 500  # 大戶賣 + 散戶買

    if divergence:
        return {"emoji": "🔴⚠️", "title": "派發強警訊", "level": -3}
    elif cum7_whale > 1500 and concentration > 0.30:
        return {"emoji": "🟢", "title": "強勢吸籌", "level": 2}
    elif cum7_whale > 500:
        return {"emoji": "🟡", "title": "溫和買超", "level": 1}
    elif cum7_whale < -1500 and concentration < -0.30:
        return {"emoji": "🔴", "title": "主力出貨", "level": -2}
    elif cum7_whale < -500:
        return {"emoji": "🟠", "title": "溫和賣壓", "level": -1}
    else:
        return {"emoji": "⚪", "title": "盤整", "level": 0}


# ════════════════════════════════════════════════════════════════════════════
# 主要公開 API
# ════════════════════════════════════════════════════════════════════════════

async def fetch_one_date(client: httpx.AsyncClient, dt: date, prev_dt: date) -> dict:
    """並行抓取單一日期的所有 endpoints"""
    dt_str   = to_twse_date(dt)
    prev_str = to_twse_date(prev_dt)

    t86_data, margin_data, sbl_today, sbl_prev, day_trade_data = await asyncio.gather(
        fetch_t86(client, dt_str),
        fetch_margin(client, dt_str),
        fetch_sbl(client, dt_str),
        fetch_sbl(client, prev_str),
        fetch_day_trade(client, dt_str),
    )

    return {
        "date":       dt_str,
        "t86":        t86_data,
        "margin":     margin_data,
        "sbl_today":  sbl_today,
        "sbl_prev":   sbl_prev,
        "day_trade":  day_trade_data,
    }


async def update_stocks(
    stock_ids: list[str],
    days: int = 30,
    end_date: date = None,
) -> dict[str, list[dict]]:
    """
    更新指定股票清單，回傳每檔的每日估算紀錄
    同時寫入 chip_data/{stock_id}.csv
    """
    if end_date is None:
        end_date = date.today()

    dates = last_n_trading_dates(days, end_date)
    if not dates:
        return {}

    # 補一個前一天（給 SBL lag 用）
    prev_date = dates[0] - timedelta(days=1)
    while not is_trading_day(prev_date):
        prev_date -= timedelta(days=1)
    all_dates = [prev_date] + dates

    print(f"[INFO] 抓取 {len(dates)} 個交易日，{len(stock_ids)} 支股票")

    async with httpx.AsyncClient() as client:
        # 按日期逐日抓（避免同時大量請求）
        raw_by_date: dict[str, dict] = {}
        for i, dt in enumerate(all_dates):
            prev = all_dates[i - 1] if i > 0 else dt - timedelta(days=1)
            await asyncio.sleep(0.3)  # 避免 429
            raw = await fetch_one_date(client, dt, prev)
            raw_by_date[to_twse_date(dt)] = raw
            print(f"  [{i+1}/{len(all_dates)}] {to_twse_date(dt)} 完成")

    # 計算每檔股票
    results: dict[str, list[dict]] = {}
    for stock_id in stock_ids:
        records = []
        for i, dt in enumerate(dates):
            dt_str = to_twse_date(dt)
            raw = raw_by_date.get(dt_str, {})

            t86_parsed   = parse_t86(raw.get("t86", {}), stock_id)
            margin_parsed = parse_margin(raw.get("margin", {}), stock_id)
            sbl_parsed   = parse_sbl_day(raw.get("sbl_today", {}), raw.get("sbl_prev", {}), stock_id)
            dt_parsed    = parse_day_trade(raw.get("day_trade", {}), stock_id)

            est = estimate(t86_parsed, margin_parsed, sbl_parsed, dt_parsed)
            rec = {"date": dt_str, **est}
            records.append(rec)

        # 計算 7 日累計訊號
        df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
        df["cum7_whale"]  = df["whale_flow_lots"].rolling(7, min_periods=1).sum()
        df["cum7_retail"] = df["retail_flow_lots"].rolling(7, min_periods=1).sum()

        signals = []
        for _, row in df.iterrows():
            sig = classify_signal(row["cum7_whale"], row["concentration_index"], row["cum7_retail"])
            signals.append(sig)
        df["signal_emoji"] = [s["emoji"] for s in signals]
        df["signal_title"] = [s["title"] for s in signals]
        df["signal_level"] = [s["level"] for s in signals]

        # 存 CSV
        csv_path = DATA_DIR / f"{stock_id}.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        results[stock_id] = df.to_dict(orient="records")
        print(f"  [DONE] {stock_id} → {len(records)} 筆，最新訊號: {signals[-1]['emoji']} {signals[-1]['title']}")

    return results


def load_stock_history(stock_id: str) -> list[dict]:
    """從 CSV 讀取個股歷史（無需重新計算）"""
    csv_path = DATA_DIR / f"{stock_id}.csv"
    if not csv_path.exists():
        return []
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    return df.to_dict(orient="records")


def get_market_rankings(dt: str = None, top: int = 30) -> list[dict]:
    """
    從 SQLite cache 撈出指定日期所有股票的估算，回傳大戶排行
    注意：只排已更新的股票
    """
    if dt is None:
        dt = to_twse_date(date.today())

    # 掃描所有 CSV，找該日期的資料
    rankings = []
    for csv_file in DATA_DIR.glob("*.csv"):
        stock_id = csv_file.stem
        df = pd.read_csv(csv_file, encoding="utf-8-sig")
        row = df[df["date"] == dt]
        if row.empty:
            continue
        r = row.iloc[-1].to_dict()
        r["stock_id"] = stock_id
        rankings.append(r)

    rankings.sort(key=lambda x: x.get("cum7_whale", 0), reverse=True)
    return rankings[:top]


# ════════════════════════════════════════════════════════════════════════════
# 初始化
# ════════════════════════════════════════════════════════════════════════════
init_db()


if __name__ == "__main__":
    # 快速測試
    async def _test():
        results = await update_stocks(["2330", "2317"], days=5)
        for sid, records in results.items():
            print(f"\n{'='*40}")
            print(f"股票：{sid}")
            for r in records[-3:]:
                print(r)

    asyncio.run(_test())
