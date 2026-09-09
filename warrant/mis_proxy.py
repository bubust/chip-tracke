"""
MIS 代理層 — 批次查詢 + 3 秒快取 + rate limit 保護
"""
import time
import logging
from typing import Optional
from datetime import datetime, date
from threading import Lock

import httpx

log = logging.getLogger(__name__)

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
MIS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://mis.twse.com.tw/stock/index.jsp",
    "Accept":     "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

_cache: dict = {}       # ex_ch_key → (timestamp, data)
_last_request = 0.0
_lock = Lock()
MIN_INTERVAL = 0.5      # 秒，保守値（實測 0.2s 不觸發，留緩衝）


def _build_ex_ch(codes: list[str]) -> str:
    """codes 格式: '2330' (TSE), 'otc_700019' (OTC), '064692' (TSE warrant)"""
    parts = []
    for c in codes:
        if c.startswith("otc_"):
            parts.append(f"otc_{c[4:]}.tw")
        elif c.startswith("tse_"):
            parts.append(f"tse_{c[4:]}.tw")
        else:
            parts.append(f"tse_{c}.tw")   # 預設 TSE
    return "|".join(parts)


def _fetch_mis(ex_ch: str) -> list[dict]:
    global _last_request

    with _lock:
        now = time.time()
        wait = MIN_INTERVAL - (now - _last_request)
        if wait > 0:
            time.sleep(wait)

        params = {
            "ex_ch": ex_ch,
            "json":  "1",
            "delay": "0",
            "_":     str(int(time.time() * 1000)),
        }
        try:
            r = httpx.get(MIS_URL, params=params, headers=MIS_HEADERS, timeout=10)
            _last_request = time.time()
            data = r.json()
            return data.get("msgArray", [])
        except Exception as e:
            _last_request = time.time()
            log.warning(f"[MIS] 請求失敗: {e}")
            return []


def get_quotes(codes: list[str], cache_ttl: float = 3.0) -> dict[str, dict]:
    """
    批次取報價，3 秒 cache。
    回傳 {code: mis_item_dict}
    """
    now = time.time()
    result = {}
    miss = []

    for c in codes:
        cached = _cache.get(c)
        if cached and (now - cached[0]) < cache_ttl:
            result[c] = cached[1]
        else:
            miss.append(c)

    if not miss:
        return result

    # 分批（每批 50）
    BATCH = 50
    for i in range(0, len(miss), BATCH):
        batch = miss[i:i + BATCH]
        ex_ch = _build_ex_ch(batch)
        items = _fetch_mis(ex_ch)

        for item in items:
            raw_code = item.get("c", "")
            # strip market prefix
            code = raw_code
            _cache[code] = (now, item)
            result[code] = item

    return result


def parse_price(item: dict) -> dict:
    """從 MIS item 解析常用欄位"""
    def safe_float(s):
        try:
            return float(s) if s and s != "-" else None
        except Exception:
            return None

    def parse_tiers(s: str) -> list[Optional[float]]:
        if not s:
            return []
        return [safe_float(x) for x in s.split("_") if x != ""]

    bid_tiers = parse_tiers(item.get("b", ""))
    ask_tiers = parse_tiers(item.get("a", ""))
    bid_vol   = parse_tiers(item.get("g", ""))
    ask_vol   = parse_tiers(item.get("f", ""))

    bid = bid_tiers[0] if bid_tiers else None
    ask = ask_tiers[0] if ask_tiers else None
    bid_lots = int(bid_vol[0]) if bid_vol and bid_vol[0] is not None else 0
    ask_lots = int(ask_vol[0]) if ask_vol and ask_vol[0] is not None else 0

    z = safe_float(item.get("z"))
    y = safe_float(item.get("y"))
    price = z if z is not None else y

    tlong = item.get("tlong", "0")
    try:
        data_ts = datetime.fromtimestamp(int(tlong) / 1000)
    except Exception:
        data_ts = None

    return {
        "price":      price,
        "bid":        bid,
        "ask":        ask,
        "bid_lots":   bid_lots,
        "ask_lots":   ask_lots,
        "prev_close": y,
        "limit_up":   safe_float(item.get("u")),
        "limit_down": safe_float(item.get("w")),
        "open":       safe_float(item.get("o")),
        "high":       safe_float(item.get("h")),
        "low":        safe_float(item.get("l")),
        "data_time":  data_ts.isoformat() if data_ts else None,
        "name":       item.get("n", ""),
        "ex":         item.get("ex", "tse"),
    }


def market_state(item: dict) -> str:
    """判斷市場狀態"""
    now = datetime.now()
    wd = now.weekday()
    if wd >= 5:
        return "AFTER_HOURS"

    h = now.hour
    m = now.minute
    t = h * 60 + m

    if t < 9 * 60:
        return "PRE_OPEN"
    if t >= 13 * 60 + 25:
        return "AFTER_HOURS"
    if t >= 13 * 60 + 20:
        return "CLOSING_AUCTION"

    # 有 bid 代表盤中
    bid = item.get("b", "")
    if bid and bid != "-":
        return "OPEN"
    return "AFTER_HOURS"
