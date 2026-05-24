"""
supabase_store.py — 持久化存儲層
watchlist 和 chip_data 存 Supabase，Render 重啟後資料不遺失。
若環境變數未設定則回退到本機 SQLite/CSV。
"""

import os
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

def _enabled():
    return bool(SUPABASE_URL and SUPABASE_KEY)

def _h():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

def _get(path, params=None):
    try:
        r = httpx.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_h(), params=params, timeout=15)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        print(f"[SB] GET {path} failed: {e}")
        return []

def _post(path, data, prefer="resolution=ignore-duplicates,return=minimal"):
    try:
        r = httpx.post(f"{SUPABASE_URL}/rest/v1/{path}", headers={**_h(), "Prefer": prefer},
                       json=data, timeout=30)
        return r.status_code in (200, 201, 204)
    except Exception as e:
        print(f"[SB] POST {path} failed: {e}")
        return False

def _patch(path, data):
    try:
        r = httpx.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers={**_h(), "Prefer": "return=minimal"},
                        json=data, timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"[SB] PATCH {path} failed: {e}")
        return False

def _delete(path):
    try:
        r = httpx.delete(f"{SUPABASE_URL}/rest/v1/{path}", headers={**_h(), "Prefer": "return=minimal"}, timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"[SB] DELETE {path} failed: {e}")
        return False


# ── Watchlist ──────────────────────────────────────────────────────────────

def wl_list():
    """回傳 [{stock_id, name, added_at}, ...]"""
    if not _enabled():
        return None  # 呼叫端自行處理 fallback
    return _get("chip_watchlist", {"order": "added_at"})

def wl_add(stock_id: str, name: str = "", added_at: str = ""):
    if not _enabled():
        return False
    return _post("chip_watchlist", {"stock_id": stock_id, "name": name, "added_at": added_at})

def wl_delete(stock_id: str):
    if not _enabled():
        return False
    return _delete(f"chip_watchlist?stock_id=eq.{stock_id}")

def wl_update_name(stock_id: str, name: str):
    if not _enabled():
        return False
    return _patch(f"chip_watchlist?stock_id=eq.{stock_id}", {"name": name})

def wl_get_ids():
    """僅回傳 stock_id 清單"""
    rows = wl_list()
    if rows is None:
        return None
    return [r["stock_id"] for r in rows]


# ── Chip Data ──────────────────────────────────────────────────────────────

def cd_load(stock_id: str):
    """回傳個股所有歷史記錄（按日期排序）"""
    if not _enabled():
        return None
    rows = _get("chip_data", {"stock_id": f"eq.{stock_id}", "order": "date"})
    return rows if isinstance(rows, list) else []

def cd_upsert(stock_id: str, records: list[dict]):
    """批量寫入 chip_data（merge-duplicates）"""
    if not _enabled() or not records:
        return False
    # 補上 stock_id
    rows = [{**r, "stock_id": stock_id} for r in records]
    # 批次寫（每批 300 筆避免超時）
    ok = True
    for i in range(0, len(rows), 300):
        batch = rows[i:i+300]
        ok = ok and _post("chip_data", batch, prefer="resolution=merge-duplicates,return=minimal")
    return ok

def cd_delete_stock(stock_id: str):
    """刪除某支股票的所有 chip_data（從觀察清單移除時）"""
    if not _enabled():
        return False
    return _delete(f"chip_data?stock_id=eq.{stock_id}")

def cd_all_latest(date_str: str):
    """取得指定日期所有股票的 chip_data（用於大戶排行）"""
    if not _enabled():
        return None
    return _get("chip_data", {"date": f"eq.{date_str}"})
