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

FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "")
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# 排除的 industry_category 關鍵字
_EXCLUDE_KEYWORDS = ["ETF", "指數", "基金", "存託"]

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
    """把 industry_category 直接當 sector_id（中文 slug）"""
    return category.strip()


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
    sectors: dict[str, str] = {}  # sector_id -> sector_name
    mappings: list[tuple] = []    # (stock_id, sector_id, effective_date)

    for row in rows:
        if not _is_valid_stock(row):
            continue
        sid = str(row["stock_id"]).strip()
        category = str(row["industry_category"]).strip()
        sector_id = _make_sector_id(category)
        sectors[sector_id] = category
        mappings.append((sid, sector_id, today))

    log.info(f"[universe] 有效股票 {len(mappings)} 筆，產業 {len(sectors)} 個")

    with db() as conn:
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
