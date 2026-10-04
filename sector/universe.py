"""
sector/universe.py — 從 FinMind 建立產業對照表
"""
import os
import logging
import re
from datetime import date

import httpx

from .db import db

log = logging.getLogger(__name__)

_FALLBACK_FM_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9"
    ".eyJ1c2VyX2lkIjoiYnVidXN0IiwiZW1haWwiOiJidWJ1c3RAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0"
    ".LcLL157_bH6YbABE7JOlg0cAEwwzOV6GfJA6uK2cvIA"
)
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "") or _FALLBACK_FM_TOKEN
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# 排除的 industry_category 關鍵字（ETF、指數、權證「所有證券」、ETN 都不是一般股票）
_EXCLUDE_KEYWORDS = ["ETF", "指數", "基金", "存託", "Index", "大盤", "所有證券", "ETN"]

# FinMind 上市／上櫃同一個產業用不同名字 → 合併成一個（舊版分開算，例：上櫃「金融業」只剩券商 8 支）
_CATEGORY_ALIAS = {
    "金融業": "金融保險",
    "數位雲端類": "數位雲端",
    "綠能環保類": "綠能環保",
    "居家生活類": "居家生活",
    "運動休閒類": "運動休閒",
    "其他電子類": "其他電子業",
    "農業科技業": "農業科技",
    "觀光事業": "觀光餐旅",
    "創新版股票": "創新板股票",
}
# 上市的「大類」：同一支股票通常還有細分產業（2330＝半導體業＋電子工業）→ 有細分就用細分
_UMBRELLA = {"電子工業", "化學生技醫療"}

# 只保留純數字 stock_id（4~6碼）；含字母者通常是憑證/債券
_VALID_STOCK_RE = re.compile(r"^\d{4,6}$")


def _is_valid_stock(row: dict) -> bool:
    """過濾只保留一般股票（排除 ETF、憑證等）"""
    sid = str(row.get("stock_id", "")).strip()
    if not _VALID_STOCK_RE.match(sid):
        return False
    category = str(row.get("industry_category", "")).strip()
    if not category:
        return False
    for kw in _EXCLUDE_KEYWORDS:
        if kw in category:
            return False
    return True


def _make_sector_id(category: str) -> str:
    """industry_category → sector_id（中文；上市／上櫃不同名的合併成一個）"""
    c = category.strip()
    return _CATEGORY_ALIAS.get(c, c)


def build_mapping(rows: list) -> dict:
    """FinMind TaiwanStockInfo 列 → {stock_id: sector_id}。
    同一支股票會出現好幾列：舊分類也留著（例 6195：2023 貿易百貨、2026 居家生活類）→ 用 date 最新的那列；
    同一天有大類＋細分（2330：電子工業＋半導體業）→ 用細分。興櫃（type=emerging）沒有每日行情，不納入。"""
    cands: dict = {}
    for row in rows:
        if not _is_valid_stock(row) or str(row.get("type", "")).strip() == "emerging":
            continue
        sid = str(row["stock_id"]).strip()
        sec = _make_sector_id(str(row["industry_category"]))
        d = str(row.get("date") or "")
        d = d if d[:4].isdigit() else ""                    # 'None' 當最舊
        cands.setdefault(sid, []).append((d, sec not in _UMBRELLA, sec))
    return {sid: max(lst)[2] for sid, lst in cands.items()}


def fetch_and_build_mapping() -> dict:
    """
    從 FinMind TaiwanStockInfo 建立 sector_master + stock_sector_map。
    回傳 {sector_id: count} 統計。
    """
    token = FINMIND_TOKEN
    if not token:
        log.warning("[universe] 未設定 FINMIND_TOKEN，無法抓取產業資料")
        return {}

    log.info("[universe] 開始從 FinMind 抓 TaiwanStockInfo...")
    try:
        resp = httpx.get(
            FINMIND_URL,
            params={"dataset": "TaiwanStockInfo", "token": token},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error(f"[universe] FinMind 請求失敗: {e}")
        return {}

    rows = data.get("data", [])
    if not rows:
        log.warning("[universe] FinMind 回傳空資料")
        return {}

    log.info(f"[universe] 收到 {len(rows)} 筆股票資料")

    today = date.today().isoformat()
    m = build_mapping(rows)
    sectors: dict[str, str] = {sec: sec for sec in m.values()}           # sector_id -> sector_name
    mappings: list[tuple] = [(sid, sec, today) for sid, sec in m.items()]  # (stock_id, sector_id, effective_date)

    log.info(f"[universe] 有效股票 {len(mappings)} 支，產業 {len(sectors)} 個")

    with db() as conn:
        # 整個重建：舊對照表的主鍵含日期，不清掉的話同一支股票會同時屬於新舊兩個產業；
        # 已經不存在的產業（例：舊的「金融業」）在每日結果／事件裡的舊資料也一起清掉
        conn.execute("DELETE FROM stock_sector_map")
        conn.execute("DELETE FROM sector_master")
        keep = list(sectors)
        ph = ",".join("?" * len(keep))
        conn.execute(f"DELETE FROM sector_daily WHERE sector_id NOT IN ({ph})", keep)
        conn.execute(f"DELETE FROM sector_events WHERE sector_id NOT IN ({ph})", keep)
        # 寫入 sector_master
        for sector_id, sector_name in sectors.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO sector_master
                    (sector_id, sector_name, exchange, created_at)
                VALUES (?, ?, 'ALL', ?)
                """,
                (sector_id, sector_name, today),
            )

        # 寫入 stock_sector_map
        conn.executemany(
            """
            INSERT OR REPLACE INTO stock_sector_map
                (stock_id, sector_id, effective_date)
            VALUES (?, ?, ?)
            """,
            mappings,
        )

        # 記錄最後初始化時間
        conn.execute(
            "INSERT OR REPLACE INTO sector_meta (key, value) VALUES ('last_init', ?)",
            (today,),
        )

    log.info("[universe] sector_master + stock_sector_map 寫入完成")

    # 統計每個產業的股票數
    counts: dict[str, int] = {}
    for _, sector_id, _ in mappings:
        counts[sector_id] = counts.get(sector_id, 0) + 1
    return counts


def get_all_sectors() -> dict:
    """回傳 {sector_id: sector_name} dict"""
    with db() as conn:
        rows = conn.execute(
            "SELECT sector_id, sector_name FROM sector_master ORDER BY sector_id"
        ).fetchall()
    return {r["sector_id"]: r["sector_name"] for r in rows}


def get_sector_stocks(sector_id: str) -> list:
    """回傳 [stock_id] list（取最新一筆 effective_date）"""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT stock_id FROM stock_sector_map
            WHERE sector_id = ?
            ORDER BY effective_date DESC, stock_id
            """,
            (sector_id,),
        ).fetchall()
    # 去重（同一 stock_id 可能有多筆不同 effective_date）
    seen = set()
    result = []
    for r in rows:
        sid = r["stock_id"]
        if sid not in seen:
            seen.add(sid)
            result.append(sid)
    return result


def get_stock_sector(stock_id: str) -> str | None:
    """回傳該股票的 sector_id（取最新一筆）"""
    with db() as conn:
        row = conn.execute(
            """
            SELECT sector_id FROM stock_sector_map
            WHERE stock_id = ?
            ORDER BY effective_date DESC
            LIMIT 1
            """,
            (stock_id,),
        ).fetchone()
    return row["sector_id"] if row else None


def is_initialized() -> bool:
    """判斷 sector_master 是否已有資料"""
    try:
        with db() as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM sector_master"
            ).fetchone()[0]
        return cnt > 0
    except Exception:
        return False
