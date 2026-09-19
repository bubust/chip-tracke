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
    """回傳 [{stock_id, name, added_at}, ...]；出錯時回傳 None 讓呼叫端 fallback 到 SQLite"""
    if not _enabled():
        return None
    try:
        r = httpx.get(
            f"{SUPABASE_URL}/rest/v1/chip_watchlist",
            headers=_h(), params={"order": "added_at"}, timeout=15,
        )
        if r.status_code == 200:
            return r.json()
        print(f"[SB] wl_list HTTP {r.status_code}: {r.text[:200]}")
        return None  # 讓呼叫端 fallback 到 SQLite
    except Exception as e:
        print(f"[SB] wl_list failed: {e}")
        return None  # 讓呼叫端 fallback 到 SQLite

def wl_add(stock_id: str, name: str = "", added_at: str = "", note: str = "", memo: str = ""):
    if not _enabled():
        return False
    return _post("chip_watchlist", {"stock_id": stock_id, "name": name, "added_at": added_at, "note": note, "memo": memo})

def wl_delete(stock_id: str):
    if not _enabled():
        return False
    return _delete(f"chip_watchlist?stock_id=eq.{stock_id}")

def wl_update_name(stock_id: str, name: str):
    if not _enabled():
        return False
    return _patch(f"chip_watchlist?stock_id=eq.{stock_id}", {"name": name})

def wl_update_note(stock_id: str, note: str):
    if not _enabled():
        return False
    return _patch(f"chip_watchlist?stock_id=eq.{stock_id}", {"note": note})

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


# ── Price Daily ──────────────────────────────────────────────────────────────

def pd_upsert(records: list) -> bool:
    """批量寫入 price_daily（merge-duplicates），每批 500 筆"""
    if not _enabled() or not records:
        return False
    ok = True
    for i in range(0, len(records), 500):
        ok = ok and _post("price_daily", records[i:i+500],
                          prefer="resolution=merge-duplicates,return=minimal")
    return ok

def pd_count() -> int:
    """回傳 price_daily 總筆數（透過 Prefer: count=exact header）"""
    if not _enabled():
        return 0
    try:
        r = httpx.get(
            f"{SUPABASE_URL}/rest/v1/price_daily",
            headers={**_h(), "Prefer": "count=exact"},
            params={"select": "date", "limit": "1"},
            timeout=10,
        )
        cr = r.headers.get("content-range", "0/0")
        return int(cr.split("/")[-1]) if "/" in cr else 0
    except Exception:
        return 0

def pd_restore_page(limit: int = 1000, offset: int = 0) -> list:
    """讀取 price_daily 一頁（用於冷啟動恢復）"""
    if not _enabled():
        return []
    return _get(f"price_daily?order=date,stock_id&limit={limit}&offset={offset}") or []


# ── KV Store（用 GitHub Contents API 儲存掃描結果）────────────────────────────

import base64 as _b64
import urllib.request as _urllib_req
import json as _json_kv

_GITHUB_PAT = os.getenv("GITHUB_PAT", "")
_GITHUB_REPO = os.getenv("GITHUB_REPO", "bubust/chip-tracke")
_KV_FILE_MAP = {
    "scan_latest": "scan_data/latest.json",
}

def _gh_headers():
    return {
        "Authorization": f"token {_GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "chip-tracker",
        "Content-Type": "application/json",
    }

def kv_set(key: str, value: str) -> bool:
    """儲存 key-value（用 GitHub Contents API，以 repo 檔案持久化）"""
    if not _GITHUB_PAT:
        return False
    filepath = _KV_FILE_MAP.get(key, f"scan_data/{key}.json")
    api_url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{filepath}"
    # 先取得現有 SHA（更新時必須帶 sha）
    try:
        req = _urllib_req.Request(api_url, headers=_gh_headers())
        with _urllib_req.urlopen(req, timeout=10) as r:
            existing = _json_kv.loads(r.read())
            sha = existing.get("sha", "")
    except Exception:
        sha = ""
    encoded = _b64.b64encode(value.encode()).decode()
    payload = _json_kv.dumps({
        "message": f"scan: update {key}",
        "content": encoded,
        **({"sha": sha} if sha else {}),
    }).encode()
    try:
        req2 = _urllib_req.Request(api_url, data=payload, method="PUT", headers=_gh_headers())
        with _urllib_req.urlopen(req2, timeout=15) as r:
            return r.status in (200, 201)
    except Exception as e:
        print(f"[KV] set {key} failed: {e}")
        return False

def kv_get(key: str) -> str | None:
    """讀取 key-value（走 GitHub Contents API，不受 CDN 快取影響）"""
    import base64 as _b64_get
    filepath = _KV_FILE_MAP.get(key, f"scan_data/{key}.json")
    api_url = f"https://api.github.com/repos/{_GITHUB_REPO}/contents/{filepath}"
    try:
        req = _urllib_req.Request(api_url, headers={**_gh_headers(), "Cache-Control": "no-cache"})
        with _urllib_req.urlopen(req, timeout=10) as r:
            data = _json_kv.loads(r.read())
            return _b64_get.b64decode(data["content"]).decode()
    except Exception as e:
        print(f"[KV] get {key} failed: {e}")
        return None
