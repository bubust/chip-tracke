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
    "sbl":       f"{TWSE_BASE}/SBL/TWT93U",           # 備用（目前 TWSE 有時重導向）
    "day_trade": f"{TWSE_BASE}/dayTrading/TWTB4U",    # 2026 新路徑
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.twse.com.tw/",
}

# ── 估算權重（預設值）────────────────────────────────────────────────────────
DEFAULT_WEIGHTS = {
    "foreign":        1.00,
    "foreign_dealer": 0.85,
    "trust":          0.95,
    "dealer_self":    0.70,
    "dealer_hedge":   0.10,
    "sbl":           -0.80,
    "day_trade":     -0.50,
}

# ── 訊號門檻（預設值）────────────────────────────────────────────────────────
DEFAULT_THRESHOLDS = {
    "alert_whale":   -1000,  # 散戶接盤警示：大戶7日累計
    "alert_retail":    300,  # 散戶接盤警示：散戶7日累計
    "lvl3_foreign":    500,  # 外資投信同步建倉：外資7日累計
    "lvl3_trust":      100,  # 外資投信同步建倉：投信7日累計
    "lvl3_consec":       4,  # 外資投信同步建倉：連續買超天數
    "lvl2a_whale":     500,  # 法人建倉散戶退：大戶7日累計
    "lvl2a_retail":   -200,  # 法人建倉散戶退：散戶7日累計（負=散戶減）
    "lvl2b_foreign":   300,  # 外資投信同步買：外資7日累計
    "lvl2b_trust":      50,  # 外資投信同步買：投信7日累計
    "lvl1a_whale":     500,  # 法人買散戶跟進：大戶7日累計
    "lvl1a_retail":    200,  # 法人買散戶跟進：散戶7日累計（正=散戶增）
    "lvl1b_whale":     300,  # 法人溫和買進：大戶7日累計
    "sell_strong":   -1000,  # 法人出貨：大戶7日累計
    "sell_mild":      -300,  # 法人溫和賣出：大戶7日累計
}

# 向後相容的舊名稱（供 estimate() 直接參考用）
WEIGHTS = DEFAULT_WEIGHTS


def get_weights() -> dict:
    """從 settings 讀取可覆寫的權重，無設定則用預設值"""
    try:
        conn = get_conn()
        rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'w_%'").fetchall()
        conn.close()
        result = dict(DEFAULT_WEIGHTS)
        for row in rows:
            k = row["key"][2:]  # 去掉 "w_" 前綴
            if k in result:
                result[k] = float(row["value"])
        return result
    except Exception:
        return dict(DEFAULT_WEIGHTS)


def get_thresholds() -> dict:
    """從 settings 讀取可覆寫的訊號門檻，無設定則用預設值"""
    try:
        conn = get_conn()
        rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE 't_%'").fetchall()
        conn.close()
        result = dict(DEFAULT_THRESHOLDS)
        for row in rows:
            k = row["key"][2:]  # 去掉 "t_" 前綴
            if k in result:
                result[k] = float(row["value"])
        return result
    except Exception:
        return dict(DEFAULT_THRESHOLDS)


def save_params(weights: dict, thresholds: dict):
    """儲存自訂參數到 settings 表"""
    conn = get_conn()
    for k, v in weights.items():
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                     (f"w_{k}", str(v)))
    for k, v in thresholds.items():
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                     (f"t_{k}", str(v)))
    conn.commit()
    conn.close()


def lookup_stock_name(stock_id: str) -> str:
    """從 TWSE OpenAPI 查股票名稱（免 IP 限制），找不到回傳空字串"""
    try:
        import httpx as _httpx
        resp = _httpx.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_AVG_ALL",
            timeout=10
        )
        for row in resp.json():
            if row.get("Code") == stock_id:
                return row.get("Name", "").strip()
    except Exception:
        pass
    return ""


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
# Finmind API 抓取函式（取代 TWSE，支援海外 IP）
# ════════════════════════════════════════════════════════════════════════════

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

async def _fetch_finmind(client: httpx.AsyncClient, dataset: str, stock_id: str,
                          start_date: str, end_date: str = None) -> list:
    """抓取 Finmind 單一 dataset，回傳 data 陣列"""
    params = {"dataset": dataset, "data_id": stock_id, "start_date": start_date}
    if end_date:
        params["end_date"] = end_date
    try:
        resp = await client.get(FINMIND_BASE, params=params, timeout=30)
        d = resp.json()
        if d.get("status") == 200:
            return d.get("data", [])
        print(f"[WARN] Finmind {dataset} {stock_id}: {d.get('msg','unknown error')}")
        return []
    except Exception as e:
        print(f"[WARN] Finmind fetch failed {dataset} {stock_id}: {type(e).__name__}: {str(e)[:80]}")
        return []


def _parse_institutional(rows: list) -> dict[str, dict]:
    """
    解析 Finmind TaiwanStockInstitutionalInvestorsBuySell
    → {date_str: {foreign, foreign_dealer, trust, dealer_self, dealer_hedge}}
    """
    NAME_MAP = {
        "Foreign_Investor":    "foreign",
        "Foreign_Dealer_Self": "foreign_dealer",
        "Investment_Trust":    "trust",
        "Dealer_Self":         "dealer_self",
        "Dealer_Hedging":      "dealer_hedge",
    }
    result: dict[str, dict] = {}
    for row in rows:
        dt = row.get("date", "")[:10].replace("-", "")  # YYYYMMDD
        key = NAME_MAP.get(row.get("name", ""))
        if not dt or not key:
            continue
        if dt not in result:
            result[dt] = {k: 0.0 for k in ["foreign", "foreign_dealer", "trust", "dealer_self", "dealer_hedge"]}
        result[dt][key] = float(row.get("buy", 0)) - float(row.get("sell", 0))
    return result


def _parse_margin_finmind(rows: list) -> dict[str, dict]:
    """
    解析 Finmind TaiwanStockMarginPurchaseShortSale
    → {date_str: {margin_chg}}
    """
    result: dict[str, dict] = {}
    for row in rows:
        dt = row.get("date", "")[:10].replace("-", "")
        if not dt:
            continue
        today  = float(row.get("MarginPurchaseTodayBalance",     0) or 0)
        prev   = float(row.get("MarginPurchaseYesterdayBalance", 0) or 0)
        result[dt] = {"margin_chg": today - prev}
    return result


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
    加權計算法人/散戶流向（v2）
    重要改動：移除自營避險（dealer_hedge）
    — 自營避險是發行認購權證的對沖買盤，與主動看多無關，納入計算會高估買進訊號
    """
    W = get_weights()  # 動態讀取（支援使用者調整）
    foreign        = t86.get("foreign",        0.0)
    foreign_dealer = t86.get("foreign_dealer", 0.0)
    trust          = t86.get("trust",          0.0)
    dealer_self    = t86.get("dealer_self",    0.0)
    # dealer_hedge 刻意不納入計算
    sbl_chg        = sbl.get("sbl_chg",        0.0)
    day_trade_est  = day_trade.get("day_trade_est", 0.0)
    margin_chg     = margin.get("margin_chg",   0.0)

    whale_shares = (
        foreign        * W["foreign"]        +
        foreign_dealer * W["foreign_dealer"] +
        trust          * W["trust"]          +
        dealer_self    * W["dealer_self"]
        # dealer_hedge 排除
        + sbl_chg      * W["sbl"]
        + day_trade_est * W["day_trade"]
    )

    whale_flow_lots  = round(whale_shares / 1000)
    retail_flow_lots = round(margin_chg)   # 融資餘額變化（張）

    # 各法人分拆（股 → 張）
    foreign_lots     = round(foreign / 1000)
    trust_lots       = round(trust / 1000)
    dealer_self_lots = round(dealer_self / 1000)

    denom = abs(whale_flow_lots) + abs(retail_flow_lots) + 1
    concentration_index = whale_flow_lots / denom

    return {
        "whale_flow_lots":     whale_flow_lots,
        "retail_flow_lots":    retail_flow_lots,
        "concentration_index": round(concentration_index, 4),
        "foreign_lots":        foreign_lots,
        "trust_lots":          trust_lots,
        "dealer_self_lots":    dealer_self_lots,
    }


# ════════════════════════════════════════════════════════════════════════════
# 訊號判讀
# ════════════════════════════════════════════════════════════════════════════

def classify_signal(
    cum7_whale:   float,
    concentration: float,
    cum7_retail:  float,
    cum7_foreign: float = 0.0,
    cum7_trust:   float = 0.0,
    consecutive_buy: int = 0,
) -> dict:
    """
    三層訊號判讀（v2）

    層一：外資+投信方向 — 同向為強訊號
    層二：法人 vs 散戶背離 — 最高優先
    層三：連續性 — consecutive_buy 天數

    訊號矩陣：
    -3  🔴⚠️  散戶接盤警示（法人賣 + 融資增）
    -2  🔴    法人出貨
    -1  🟠    法人溫和賣出
     0  ⚪    盤整觀望
     1  🟡    法人溫和買進 / 法人買散戶跟進
     2  🟢    法人建倉散戶退 / 外資投信同步買
     3  🟢🟢  外資投信同步建倉（連續4日+）
    """
    T = get_thresholds()  # 動態讀取門檻

    # ── 層二：背離（最高優先）──────────────────
    if cum7_whale < T["alert_whale"] and cum7_retail > T["alert_retail"]:
        return {"emoji": "🔴⚠️", "title": "散戶接盤警示", "level": -3}

    # ── 層一+三：外資投信同步 + 連續性 ───────────
    if cum7_foreign > T["lvl3_foreign"] and cum7_trust > T["lvl3_trust"] and consecutive_buy >= T["lvl3_consec"]:
        return {"emoji": "🟢🟢", "title": "外資投信同步建倉", "level": 3}

    # ── 層一+二：法人買 + 散戶退場 ───────────────
    if cum7_whale > T["lvl2a_whale"] and cum7_retail < T["lvl2a_retail"]:
        return {"emoji": "🟢", "title": "法人建倉散戶退", "level": 2}

    # 外資+投信同向買（無連續性門檻）
    if cum7_foreign > T["lvl2b_foreign"] and cum7_trust > T["lvl2b_trust"]:
        return {"emoji": "🟢", "title": "外資投信同步買", "level": 2}

    # 法人買 + 散戶也跟
    if cum7_whale > T["lvl1a_whale"] and cum7_retail > T["lvl1a_retail"]:
        return {"emoji": "🟡", "title": "法人買散戶跟進", "level": 1}

    # 法人溫和買進
    if cum7_whale > T["lvl1b_whale"]:
        return {"emoji": "🟡", "title": "法人溫和買進", "level": 1}

    # ── 賣出訊號 ─────────────────────────────
    if cum7_whale < T["sell_strong"]:
        return {"emoji": "🔴", "title": "法人出貨", "level": -2}

    if cum7_whale < T["sell_mild"]:
        return {"emoji": "🟠", "title": "法人溫和賣出", "level": -1}

    return {"emoji": "⚪", "title": "盤整觀望", "level": 0}


# ════════════════════════════════════════════════════════════════════════════
# 主要公開 API
# ════════════════════════════════════════════════════════════════════════════

async def update_stocks(
    stock_ids: list[str],
    days: int = 30,
    end_date: date = None,
) -> dict[str, list[dict]]:
    """
    更新指定股票清單（透過 Finmind API，支援海外 IP）
    回傳每檔的每日估算紀錄，同時寫入 chip_data/{stock_id}.csv
    """
    if end_date is None:
        end_date = date.today()

    dates = last_n_trading_dates(days, end_date)
    if not dates:
        return {}

    start_str = dates[0].strftime("%Y-%m-%d")
    end_str   = end_date.strftime("%Y-%m-%d")
    print(f"[INFO] Finmind 抓取 {start_str}~{end_str}，{len(stock_ids)} 支股票")

    results: dict[str, list[dict]] = {}

    async with httpx.AsyncClient() as client:
        for stock_id in stock_ids:
            await asyncio.sleep(0.5)  # 避免 429
            inst_rows, margin_rows = await asyncio.gather(
                _fetch_finmind(client, "TaiwanStockInstitutionalInvestorsBuySell",
                               stock_id, start_str, end_str),
                _fetch_finmind(client, "TaiwanStockMarginPurchaseShortSale",
                               stock_id, start_str, end_str),
            )
            inst_by_date   = _parse_institutional(inst_rows)
            margin_by_date = _parse_margin_finmind(margin_rows)

            records = []
            for dt in dates:
                dt_str = to_twse_date(dt)
                if dt_str not in inst_by_date:
                    continue  # 非交易日或無資料，跳過

                t86_parsed    = inst_by_date[dt_str]
                margin_parsed = margin_by_date.get(dt_str, {"margin_chg": 0.0})
                sbl_parsed    = {"sbl_chg": 0.0}        # Finmind 借券格式不相容，暫設 0
                dt_parsed     = {"day_trade_est": 0.0}   # 當沖資料暫不納入

                est = estimate(t86_parsed, margin_parsed, sbl_parsed, dt_parsed)
                rec = {"date": dt_str, **est}
                records.append(rec)

            # 沒有任何有效日期 → 保留現有 CSV，不覆蓋
            csv_path = DATA_DIR / f"{stock_id}.csv"
            if not records:
                print(f"  [SKIP] {stock_id} — Finmind 無資料，保留現有資料")
                results[stock_id] = load_stock_history(stock_id)
                continue

            # 新資料的日期集合
            df_new = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
            new_dates = set(df_new["date"].astype(str))

            # 與現有 CSV 合併：保留舊有日期、用新資料覆蓋重疊日期
            if csv_path.exists():
                try:
                    existing_df = pd.read_csv(csv_path, encoding="utf-8-sig")
                    keep_cols = [c for c in df_new.columns if c in existing_df.columns]
                    old_rows = existing_df[~existing_df["date"].astype(str).isin(new_dates)][keep_cols]
                    df = pd.concat([old_rows, df_new[keep_cols]], ignore_index=True).sort_values("date").reset_index(drop=True)
                except Exception:
                    df = df_new
            else:
                df = df_new

            # 計算 7 日累計 + 連續買超天數（在合併後的完整序列上計算）
            df["cum7_whale"]   = df["whale_flow_lots"].rolling(7, min_periods=1).sum()
            df["cum7_retail"]  = df["retail_flow_lots"].rolling(7, min_periods=1).sum()
            df["cum7_foreign"] = df["foreign_lots"].rolling(7, min_periods=1).sum()
            df["cum7_trust"]   = df["trust_lots"].rolling(7, min_periods=1).sum()

            # 連續買超天數（whale_flow_lots > 0 即算，碰到負值歸零）
            consec = []
            cnt = 0
            for v in df["whale_flow_lots"]:
                cnt = cnt + 1 if v > 0 else 0
                consec.append(cnt)
            df["consecutive_buy"] = consec

            signals = []
            for _, row in df.iterrows():
                sig = classify_signal(
                    row["cum7_whale"],
                    row["concentration_index"],
                    row["cum7_retail"],
                    row["cum7_foreign"],
                    row["cum7_trust"],
                    int(row["consecutive_buy"]),
                )
                signals.append(sig)
            df["signal_emoji"] = [s["emoji"] for s in signals]
            df["signal_title"] = [s["title"] for s in signals]
            df["signal_level"] = [s["level"] for s in signals]

            # 存 CSV
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")

            results[stock_id] = df.to_dict(orient="records")
            print(f"  [DONE] {stock_id} → {len(df)} 筆（新增 {len(records)} 筆），最新訊號: {signals[-1]['emoji']} {signals[-1]['title']}")

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
# 全市場批量解析
# ════════════════════════════════════════════════════════════════════════════

def parse_t86_all(data: dict) -> dict[str, dict]:
    """批量解析 T86，回傳 {stock_id: {foreign, trust, ...}}"""
    result = {}
    if not data or data.get("stat") != "OK":
        return result
    for row in data.get("data", []):
        if not row or len(row) < 18:
            continue
        sid = str(row[0]).strip()
        if not sid:
            continue
        result[sid] = {
            "foreign":        _to_float(row[4]),
            "foreign_dealer": _to_float(row[7]),
            "trust":          _to_float(row[10]),
            "dealer_self":    _to_float(row[14]),
            "dealer_hedge":   _to_float(row[17]),
        }
    return result


def parse_margin_all(data: dict) -> dict[str, dict]:
    """批量解析融資餘額，回傳 {stock_id: {margin_chg}}"""
    result = {}
    if not data or data.get("stat") != "OK":
        return result
    tables = data.get("tables", [])
    candidates = ([tables[1], tables[0]] if len(tables) >= 2
                  else [tables[0]] if tables else [data])
    seen: set[str] = set()
    for tbl in candidates:
        for row in tbl.get("data", []):
            if not row or len(row) < 7:
                continue
            sid = str(row[0]).strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            result[sid] = {"margin_chg": _to_float(row[5]) - _to_float(row[6])}
    return result


def parse_sbl_all(today_data: dict, prev_data: dict) -> dict[str, dict]:
    """批量解析借券賣出，回傳 {stock_id: {sbl_chg}}"""
    def _build_map(data: dict) -> dict[str, float]:
        m: dict[str, float] = {}
        if not data or data.get("stat") != "OK":
            return m
        fields = data.get("fields", [])
        col = next((i for i, f in enumerate(fields)
                    if "借券賣出餘額" in f or "借券賣出數量" in f), None)
        if col is None:
            return m
        for row in data.get("data", []):
            if not row or len(row) <= col:
                continue
            m[str(row[0]).strip()] = _to_float(row[col])
        return m

    t_map = _build_map(today_data)
    p_map = _build_map(prev_data)
    sids  = set(t_map) | set(p_map)
    return {sid: {"sbl_chg": t_map.get(sid, 0.0) - p_map.get(sid, 0.0)} for sid in sids}


def parse_day_trade_all(data: dict) -> dict[str, dict]:
    """批量解析當沖，回傳 {stock_id: {day_trade_est}}"""
    result = {}
    if not data or data.get("stat") != "OK":
        return result
    fields = data.get("fields", [])
    col = next((i for i, f in enumerate(fields)
                if "當沖買入成交股數" in f or "當沖成交股數" in f), None)
    if col is None:
        return result
    for row in data.get("data", []):
        if not row or len(row) <= col:
            continue
        result[str(row[0]).strip()] = {"day_trade_est": _to_float(row[col])}
    return result


async def scan_market_today(dt: date = None) -> tuple[list[dict], str]:
    """
    掃描全市場上市股票。
    優先透過 TWSE rwd endpoint，若被封鎖（海外 IP）則回傳空結果。
    """
    if dt is None:
        dt = date.today()

    TWSE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.twse.com.tw/",
    }

    t86_data = {}
    margin_data = {}
    sbl_today = {}
    sbl_prev = {}
    day_trade_data = {}
    dt_str = ""

    async with httpx.AsyncClient() as client:
        for _ in range(5):
            if not is_trading_day(dt):
                dt -= timedelta(days=1)
                continue
            dt_str = to_twse_date(dt)
            print(f"[SCAN] 嘗試 {dt_str}")
            try:
                resp = await client.get(
                    "https://www.twse.com.tw/rwd/zh/fund/T86",
                    params={"response": "json", "date": dt_str, "selectType": "ALL"},
                    headers=TWSE_HEADERS,
                    timeout=20,
                )
                if resp.status_code == 200:
                    t86_data = resp.json()
                    if t86_data.get("stat") == "OK" and t86_data.get("data"):
                        break
            except Exception as e:
                print(f"[SCAN] TWSE 連線失敗（可能為海外 IP 封鎖）: {e}")
                return [], ""
            dt -= timedelta(days=1)
        else:
            print("[SCAN] 找不到有資料的日期")
            return [], ""

        if not t86_data or t86_data.get("stat") != "OK":
            return [], ""

        prev_dt = dt - timedelta(days=1)
        while not is_trading_day(prev_dt):
            prev_dt -= timedelta(days=1)
        prev_str = to_twse_date(prev_dt)

        async def _get(url, params):
            try:
                r = await client.get(url, params=params, headers=TWSE_HEADERS, timeout=20)
                return r.json() if r.status_code == 200 else {}
            except Exception:
                return {}

        margin_data, sbl_today, sbl_prev, day_trade_data = await asyncio.gather(
            _get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN",
                 {"response": "json", "date": dt_str, "selectType": "ALL"}),
            _get("https://www.twse.com.tw/rwd/zh/SBL/TWT93U", {"response": "json", "date": dt_str}),
            _get("https://www.twse.com.tw/rwd/zh/SBL/TWT93U", {"response": "json", "date": prev_str}),
            _get("https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U",
                 {"response": "json", "date": dt_str, "selectType": "ALL"}),
        )

    t86_map  = parse_t86_all(t86_data)
    marg_map = parse_margin_all(margin_data)
    sbl_map  = parse_sbl_all(sbl_today, sbl_prev)
    dt_map   = parse_day_trade_all(day_trade_data)

    print(f"[SCAN] T86 股票數={len(t86_map)}")
    results = []
    for sid, t86 in t86_map.items():
        margin  = marg_map.get(sid, {"margin_chg": 0.0})
        sbl     = sbl_map.get(sid,  {"sbl_chg": 0.0})
        dt_item = dt_map.get(sid,   {"day_trade_est": 0.0})
        est = estimate(t86, margin, sbl, dt_item)
        # 全市場掃描為單日資料，用日線值代替 7 日累計（近似）
        sig = classify_signal(
            est["whale_flow_lots"],
            est["concentration_index"],
            est["retail_flow_lots"],
            est["foreign_lots"],
            est["trust_lots"],
            0,   # 無歷史資料，不計算連續性
        )
        results.append({
            "stock_id":            sid,
            "date":                dt_str,
            "whale_flow_lots":     est["whale_flow_lots"],
            "retail_flow_lots":    est["retail_flow_lots"],
            "concentration_index": est["concentration_index"],
            "foreign_lots":        est["foreign_lots"],
            "trust_lots":          est["trust_lots"],
            "dealer_self_lots":    est["dealer_self_lots"],
            "signal_emoji":        sig["emoji"],
            "signal_title":        sig["title"],
            "signal_level":        sig["level"],
        })

    results.sort(key=lambda x: x["whale_flow_lots"], reverse=True)
    print(f"[SCAN] 完成，共 {len(results)} 支，日期={dt_str}")
    return results, dt_str


def clear_bad_cache() -> int:
    """刪除 stat != OK 或 data=[] 的快取資料，回傳刪除筆數"""
    conn = get_conn()
    rows = conn.execute("SELECT date, dataset, payload FROM market_raw").fetchall()
    deleted = 0
    for row in rows:
        try:
            d = json.loads(row["payload"])
            # 清除 stat!=OK，或 stat=OK 但 data 陣列為空（收盤前被 cache 的空回應）
            bad = d.get("stat") != "OK" or (
                "data" in d and not d.get("data")
            )
            if bad:
                conn.execute("DELETE FROM market_raw WHERE date=? AND dataset=?",
                             (row["date"], row["dataset"]))
                deleted += 1
        except Exception:
            conn.execute("DELETE FROM market_raw WHERE date=? AND dataset=?",
                         (row["date"], row["dataset"]))
            deleted += 1
    conn.commit()
    conn.close()
    return deleted


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
