"""
warrant/flow.py — 權證金流日報
每天 14:10 從 TWSE / TPEx 抓今日全市場權證成交量，依標的股彙整計算
認購 / 認售淨流量，存入 warrant_flow 表。
"""

import logging
import requests
from datetime import date, datetime
from typing import Optional

from . import db as _db

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
}


# ── 資料抓取 ──────────────────────────────────────────────────────────────────

def _twse_date(d: str) -> str:
    """'2026-09-21' → '20260921'"""
    return d.replace("-", "")


def fetch_twse_daily(date_str: str) -> list[dict]:
    """
    TWSE 上市權證每日成交行情（TWTB4U）。
    回傳 [{warrant_code, volume, turnover, close_price}, ...]
    """
    url = "https://www.twse.com.tw/rwd/zh/warrant/TWTB4U"
    params = {"date": _twse_date(date_str), "response": "json", "selectType": "ALL"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        fields = data.get("fields", [])
        rows = data.get("data", [])
        if not fields or not rows:
            log.warning(f"[flow] TWSE TWTB4U 無資料 {date_str}")
            return []
        result = []
        for row in rows:
            d = dict(zip(fields, row))
            code   = d.get("證券代號", "").strip()
            vol_s  = d.get("成交股數", "0").replace(",", "")
            turn_s = d.get("成交金額", "0").replace(",", "")
            close_s = d.get("收盤價", "0").replace(",", "")
            if not code:
                continue
            try:
                vol    = int(vol_s) // 1000  # 股 → 張（1張=1000股 for warrants）
                turn   = float(turn_s)
                close  = float(close_s) if close_s not in ("", "--", "-") else 0.0
                if vol > 0:
                    result.append({"code": code, "volume": vol,
                                   "turnover": turn, "close": close, "market": "TSE"})
            except Exception:
                continue
        log.info(f"[flow] TWSE 取得 {len(result)} 檔有成交權證")
        return result
    except Exception as e:
        log.error(f"[flow] TWSE fetch 失敗: {e}")
        return []


def fetch_tpex_daily(date_str: str) -> list[dict]:
    """
    TPEx 上櫃權證每日成交行情。
    date_str: 'YYYY-MM-DD'
    """
    # 民國年
    y, m, d_day = date_str.split("-")
    roc_year = int(y) - 1911
    roc_date = f"{roc_year}/{m}/{d_day}"

    url = "https://www.tpex.org.tw/web/bond/warrant/warrantOtcTrade/warrantOtcTrade_result.php"
    params = {"l": "zh-tw", "se": "EW", "d": roc_date, "o": "json"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        aaData = data.get("aaData", [])
        if not aaData:
            log.warning(f"[flow] TPEx 無資料 {date_str}")
            return []
        result = []
        for row in aaData:
            # 典型欄位順序: 代號, 名稱, 成交張數, 成交金額(千元), 開盤, 最高, 最低, 收盤, ...
            if len(row) < 4:
                continue
            code = str(row[0]).strip()
            try:
                vol  = int(str(row[2]).replace(",", ""))
                turn = float(str(row[3]).replace(",", "")) * 1000  # 千元→元
                close_raw = str(row[7]).replace(",", "") if len(row) > 7 else "0"
                close = float(close_raw) if close_raw not in ("", "--", "-") else 0.0
                if vol > 0:
                    result.append({"code": code, "volume": vol,
                                   "turnover": turn, "close": close, "market": "OTC"})
            except Exception:
                continue
        log.info(f"[flow] TPEx 取得 {len(result)} 檔有成交權證")
        return result
    except Exception as e:
        log.error(f"[flow] TPEx fetch 失敗: {e}")
        return []


# ── 計算 & 儲存 ───────────────────────────────────────────────────────────────

def calc_and_save(date_str: Optional[str] = None) -> int:
    """
    抓取 TWSE + TPEx 當日成交資料，依標的股彙整後寫入 warrant_flow。
    date_str: 'YYYY-MM-DD'，None = 今天。
    回傳：寫入筆數
    """
    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")

    twse_rows = fetch_twse_daily(date_str)
    tpex_rows = fetch_tpex_daily(date_str)
    all_rows  = twse_rows + tpex_rows

    if not all_rows:
        log.warning(f"[flow] {date_str} 無任何成交資料，跳過")
        return 0

    # 建立 warrant_code → {underlying_code, kind, underlying_name, ...} 對照
    codes = [r["code"] for r in all_rows]
    with _db.db() as conn:
        placeholders = ",".join("?" * len(codes))
        wmap_rows = conn.execute(f"""
            SELECT w.code, w.kind, w.underlying_code,
                   w.name AS warrant_name, w.strike, w.last_trade_date AS expiry_date,
                   u.name AS underlying_name
            FROM warrants w
            LEFT JOIN underlyings u ON w.underlying_code = u.code
            WHERE w.code IN ({placeholders})
        """, codes).fetchall()
    wmap = {r["code"]: dict(r) for r in wmap_rows}

    # 若有 NULL underlying_code，嘗試從 Sinopac map 補回
    null_codes = [c for c in codes if not wmap.get(c) or not (wmap[c].get("underlying_code"))]
    if null_codes:
        try:
            from .ingester import load_sinopac_basic
            sp_map = load_sinopac_basic()
            if sp_map:
                updated = False
                with _db.db() as conn:
                    for code in null_codes:
                        uc = (sp_map.get(code) or {}).get("underlying_code")
                        if uc:
                            conn.execute(
                                "UPDATE warrants SET underlying_code=? WHERE code=? AND underlying_code IS NULL",
                                (uc, code)
                            )
                            updated = True
                if updated:
                    with _db.db() as conn:
                        ph2 = ",".join("?" * len(codes))
                        wmap_rows2 = conn.execute(f"""
                            SELECT w.code, w.kind, w.underlying_code,
                                   w.name AS warrant_name, w.strike,
                                   w.last_trade_date AS expiry_date,
                                   u.name AS underlying_name
                            FROM warrants w
                            LEFT JOIN underlyings u ON w.underlying_code = u.code
                            WHERE w.code IN ({ph2})
                        """, codes).fetchall()
                    wmap = {r["code"]: dict(r) for r in wmap_rows2}
        except Exception as _e:
            log.warning(f"[flow] backfill underlying_code 失敗: {_e}")

    # 彙整
    flow: dict[str, dict] = {}
    for r in all_rows:
        info = wmap.get(r["code"])
        if not info or not info["underlying_code"]:
            continue
        ul = info["underlying_code"]
        if ul not in flow:
            flow[ul] = {
                "underlying_name": info["underlying_name"] or ul,
                "call_volume": 0, "call_turnover": 0.0, "call_count": 0,
                "put_volume":  0, "put_turnover":  0.0, "put_count":  0,
            }
        if info["kind"] == "CALL":
            flow[ul]["call_volume"]   += r["volume"]
            flow[ul]["call_turnover"] += r["turnover"]
            flow[ul]["call_count"]    += 1
        else:
            flow[ul]["put_volume"]    += r["volume"]
            flow[ul]["put_turnover"]  += r["turnover"]
            flow[ul]["put_count"]     += 1

    # 寫入 DB
    now_s = datetime.now().isoformat(timespec="seconds")
    insert_rows = []
    for ul, d in flow.items():
        total = d["call_turnover"] + d["put_turnover"]
        if total <= 0:
            continue
        net  = d["call_turnover"] - d["put_turnover"]
        cp   = round(d["call_turnover"] / d["put_turnover"], 3) if d["put_turnover"] > 0 else None
        insert_rows.append((
            date_str, ul, d["underlying_name"],
            d["call_volume"], round(d["call_turnover"]),
            d["call_count"],
            d["put_volume"],  round(d["put_turnover"]),
            d["put_count"],
            round(net), round(total), cp, now_s
        ))

    # 寫入彙整表
    with _db.db() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO warrant_flow
            (trade_date, underlying_code, underlying_name,
             call_volume, call_turnover, call_count,
             put_volume, put_turnover, put_count,
             net_turnover, total_turnover, cp_ratio, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, insert_rows)

    # 寫入逐檔明細表
    raw_rows = []
    for r in all_rows:
        info = wmap.get(r["code"])
        if not info or not info["underlying_code"]:
            continue
        raw_rows.append((
            date_str, r["code"], info.get("warrant_name"), info["kind"],
            info["underlying_code"], info.get("underlying_name"),
            r["volume"], round(r["turnover"]), r["close"],
            info.get("strike"), info.get("expiry_date"), now_s
        ))
    with _db.db() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO warrant_flow_raw
            (trade_date, warrant_code, warrant_name, kind,
             underlying_code, underlying_name,
             volume, turnover, close_price,
             strike, expiry_date, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, raw_rows)

    log.info(f"[flow] {date_str} 彙整 {len(insert_rows)} 筆，逐檔 {len(raw_rows)} 筆")
    return len(insert_rows)


# ── 查詢 ──────────────────────────────────────────────────────────────────────

def get_ranking(
    date_str: Optional[str] = None,
    min_total: float = 0,
    direction: Optional[str] = None,   # 'CALL' | 'PUT' | None
    sort_by: str = "net",              # 'net' | 'total' | 'call' | 'put' | 'cp'
    limit: int = 200,
) -> list[dict]:
    """讀取指定日期的金流排行"""
    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")

    sort_col = {
        "net":   "ABS(net_turnover)",
        "total": "total_turnover",
        "call":  "call_turnover",
        "put":   "put_turnover",
        "cp":    "cp_ratio",
    }.get(sort_by, "ABS(net_turnover)")

    dir_clause = ""
    dir_params: list = []
    if direction == "CALL":
        dir_clause = "AND net_turnover > 0"
    elif direction == "PUT":
        dir_clause = "AND net_turnover < 0"

    with _db.db() as conn:
        rows = conn.execute(f"""
            SELECT trade_date, underlying_code, underlying_name,
                   call_volume, call_turnover, call_count,
                   put_volume,  put_turnover,  put_count,
                   net_turnover, total_turnover, cp_ratio
            FROM warrant_flow
            WHERE trade_date = ?
              AND total_turnover >= ?
              {dir_clause}
            ORDER BY {sort_col} DESC
            LIMIT ?
        """, [date_str, min_total] + dir_params + [limit]).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["direction"] = "CALL" if d["net_turnover"] > 0 else "PUT" if d["net_turnover"] < 0 else "FLAT"
        # 轉成萬元方便顯示
        for key in ("call_turnover", "put_turnover", "net_turnover", "total_turnover"):
            d[key] = round(d[key] / 10000, 1)  # 元 → 萬元
        result.append(d)
    return result


def get_warrant_ranking(
    date_str: Optional[str] = None,
    kind: Optional[str] = None,       # 'CALL' | 'PUT' | None
    sort_by: str = "turnover",        # 'turnover' | 'volume'
    limit: int = 30,
) -> list[dict]:
    """個別權證成交量/金額排行"""
    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")
    sort_col = "volume" if sort_by == "volume" else "turnover"
    kind_clause = ""
    kind_params: list = []
    if kind in ("CALL", "PUT"):
        kind_clause = "AND kind = ?"
        kind_params = [kind]
    with _db.db() as conn:
        rows = conn.execute(f"""
            SELECT trade_date, warrant_code, warrant_name, kind,
                   underlying_code, underlying_name,
                   volume, turnover, close_price, strike, expiry_date
            FROM warrant_flow_raw
            WHERE trade_date = ? AND volume > 0
              {kind_clause}
            ORDER BY {sort_col} DESC
            LIMIT ?
        """, [date_str] + kind_params + [limit]).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["turnover_wan"] = round(d["turnover"] / 10000, 1)
        result.append(d)
    return result


def get_stock_history(underlying_code: str, days: int = 20) -> list[dict]:
    """單支股票近 N 筆金流歷史"""
    with _db.db() as conn:
        rows = conn.execute("""
            SELECT trade_date, call_volume, call_turnover, call_count,
                   put_volume, put_turnover, put_count,
                   net_turnover, total_turnover, cp_ratio
            FROM warrant_flow
            WHERE underlying_code = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, (underlying_code, days)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for key in ("call_turnover", "put_turnover", "net_turnover", "total_turnover"):
            d[key] = round(d[key] / 10000, 1)
        result.append(d)
    return result


def get_available_dates(limit: int = 30) -> list[str]:
    """回傳有金流資料的日期清單"""
    with _db.db() as conn:
        rows = conn.execute("""
            SELECT DISTINCT trade_date FROM warrant_flow
            ORDER BY trade_date DESC LIMIT ?
        """, (limit,)).fetchall()
    return [r["trade_date"] for r in rows]
