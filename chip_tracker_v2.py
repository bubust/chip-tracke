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
        resp = await client.get(url, params=params, headers=HEADERS, timeout=30,
                                follow_redirects=True)
        if resp.status_code != 200:
            print(f"[WARN] HTTP {resp.status_code} {url}")
            return {}
        return resp.json()
    except Exception as e:
        print(f"[WARN] fetch failed {url} {params}: {type(e).__name__}: {str(e)[:80]}")
        return {}


async def fetch_t86(client: httpx.AsyncClient, dt: str) -> dict:
    """三大法人個股買賣超 (T86)"""
    cached = cache.get(dt, "t86")
    if cached is not None:
        return cached
    data = await _fetch_json(client, ENDPOINTS["t86"], {"response": "json", "date": dt, "selectType": "ALL"})
    # 只 cache stat=OK 且 data 陣列非空的回應（3:30pm 前可能回傳 stat=OK 但 data=[]）
    if data.get("stat") == "OK" and data.get("data"):
        cache.put(dt, "t86", data)
    return data


async def fetch_margin(client: httpx.AsyncClient, dt: str) -> dict:
    """融資融券餘額 (MI_MARGN)"""
    cached = cache.get(dt, "margin")
    if cached is not None:
        return cached
    data = await _fetch_json(client, ENDPOINTS["margin"], {"response": "json", "date": dt, "selectType": "ALL"})
    if data.get("stat") == "OK":
        cache.put(dt, "margin", data)
    return data


async def fetch_sbl(client: httpx.AsyncClient, dt: str) -> dict:
    """借券賣出餘額 (TWT93U)"""
    cached = cache.get(dt, "sbl")
    if cached is not None:
        return cached
    data = await _fetch_json(client, ENDPOINTS["sbl"], {"response": "json", "date": dt})
    if data.get("stat") == "OK":
        cache.put(dt, "sbl", data)
    return data


async def fetch_day_trade(client: httpx.AsyncClient, dt: str) -> dict:
    """當沖統計 (TWTB4U)"""
    cached = cache.get(dt, "day_trade")
    if cached is not None:
        return cached
    data = await _fetch_json(client, ENDPOINTS["day_trade"], {"response": "json", "date": dt, "selectType": "ALL"})
    if data.get("stat") == "OK":
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
    加權計算法人/散戶流向（v2）
    重要改動：移除自營避險（dealer_hedge）
    — 自營避險是發行認購權證的對沖買盤，與主動看多無關，納入計算會高估買進訊號
    """
    foreign        = t86.get("foreign",        0.0)
    foreign_dealer = t86.get("foreign_dealer", 0.0)
    trust          = t86.get("trust",          0.0)
    dealer_self    = t86.get("dealer_self",    0.0)
    # dealer_hedge 刻意不納入計算
    sbl_chg        = sbl.get("sbl_chg",        0.0)
    day_trade_est  = day_trade.get("day_trade_est", 0.0)
    margin_chg     = margin.get("margin_chg",   0.0)

    whale_shares = (
        foreign        * WEIGHTS["foreign"]        +
        foreign_dealer * WEIGHTS["foreign_dealer"] +
        trust          * WEIGHTS["trust"]          +
        dealer_self    * WEIGHTS["dealer_self"]
        # dealer_hedge 排除
        + sbl_chg      * WEIGHTS["sbl"]
        + day_trade_est * WEIGHTS["day_trade"]
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
    # ── 層二：背離（最高優先）──────────────────
    # 法人賣超 + 融資增加 → 法人出貨、散戶接盤（最危險）
    if cum7_whale < -1000 and cum7_retail > 300:
        return {"emoji": "🔴⚠️", "title": "散戶接盤警示", "level": -3}

    # ── 層一+三：外資投信同步 + 連續性 ───────────
    # 外資+投信同步買 + 連續4天以上 → 最強建倉訊號
    if cum7_foreign > 500 and cum7_trust > 100 and consecutive_buy >= 4:
        return {"emoji": "🟢🟢", "title": "外資投信同步建倉", "level": 3}

    # ── 層一+二：法人買 + 散戶退場 ───────────────
    # 法人進、融資減 → 散戶放棄、法人悄悄買（最佳進場信號）
    if cum7_whale > 500 and cum7_retail < -200:
        return {"emoji": "🟢", "title": "法人建倉散戶退", "level": 2}

    # 外資+投信同向買（無連續性門檻）
    if cum7_foreign > 300 and cum7_trust > 50:
        return {"emoji": "🟢", "title": "外資投信同步買", "level": 2}

    # 法人買 + 散戶也跟（注意後段出貨風險）
    if cum7_whale > 500 and cum7_retail > 200:
        return {"emoji": "🟡", "title": "法人買散戶跟進", "level": 1}

    # 法人溫和買進
    if cum7_whale > 300:
        return {"emoji": "🟡", "title": "法人溫和買進", "level": 1}

    # ── 賣出訊號 ─────────────────────────────
    if cum7_whale < -1000:
        return {"emoji": "🔴", "title": "法人出貨", "level": -2}

    if cum7_whale < -300:
        return {"emoji": "🟠", "title": "法人溫和賣出", "level": -1}

    return {"emoji": "⚪", "title": "盤整觀望", "level": 0}


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

            # T86 是主要資料來源；stat != OK 表示 API 封鎖或無資料，跳過此日不寫零
            if raw.get("t86", {}).get("stat") != "OK":
                continue

            t86_parsed   = parse_t86(raw.get("t86", {}), stock_id)
            margin_parsed = parse_margin(raw.get("margin", {}), stock_id)
            sbl_parsed   = parse_sbl_day(raw.get("sbl_today", {}), raw.get("sbl_prev", {}), stock_id)
            dt_parsed    = parse_day_trade(raw.get("day_trade", {}), stock_id)

            est = estimate(t86_parsed, margin_parsed, sbl_parsed, dt_parsed)
            rec = {"date": dt_str, **est}
            records.append(rec)

        # 沒有任何有效日期（全部 API 封鎖）→ 保留現有 CSV，不覆蓋
        csv_path = DATA_DIR / f"{stock_id}.csv"
        if not records:
            print(f"  [SKIP] {stock_id} — 無有效 T86 資料（API 封鎖或非交易日），保留現有資料")
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
    掃描全市場上市股票，從 T86 bulk 一次取得所有股票並計算大戶流向。
    自動往前找最近有資料的交易日（T86 資料約在收盤後 3:30pm 發布）。
    回傳 (results, actual_date_str)
    """
    if dt is None:
        dt = date.today()

    # 往前找最多 5 個交易日，找到有資料的日期
    async with httpx.AsyncClient() as client:
        for _ in range(5):
            if not is_trading_day(dt):
                dt -= timedelta(days=1)
                continue
            dt_str = to_twse_date(dt)
            print(f"[SCAN] 嘗試 {dt_str}")
            t86_data = await fetch_t86(client, dt_str)
            # stat=OK 且 data 有內容才算找到
            if t86_data and t86_data.get("stat") == "OK" and t86_data.get("data"):
                break
            dt -= timedelta(days=1)
        else:
            print("[SCAN] 找不到有資料的日期")
            return [], ""

        prev_dt = dt - timedelta(days=1)
        while not is_trading_day(prev_dt):
            prev_dt -= timedelta(days=1)

        margin_data, sbl_today, sbl_prev, day_trade_data = await asyncio.gather(
            fetch_margin(client, dt_str),
            fetch_sbl(client, dt_str),
            fetch_sbl(client, to_twse_date(prev_dt)),
            fetch_day_trade(client, dt_str),
        )

    if not t86_data or t86_data.get("stat") != "OK":
        print(f"[SCAN] T86 stat={t86_data.get('stat') if t86_data else 'empty'} — 無資料")
        return [], ""

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
