"""
個股期貨小幫手 — /api/futures/{stock_id}

資料來源（TAIFEX OpenAPI, 前一交易日）：
  /v1/SSFLists                   → StockCode → Contract code 映射
  /v1/DailyMarketReportFut       → 日行情（Last, Settlement, BestBid/Ask）
  /v1/SingleStockFuturesMargining → 保證金率（InitialMarginRate, MaintenanceMarginRate）
現貨報價：TWSE MIS（mis_proxy）
"""
import json
import logging
from calendar import monthrange
from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Query

log = logging.getLogger(__name__)
router = APIRouter()

_BASE  = "https://openapi.taifex.com.tw/v1"
_HDRS  = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}

_STANDARD_SIZE = 2000   # 每口股數（標準個股期）
_MINI_SIZE     = 200    # mini 個股期

# 簡易快取（同一天不重複打 API）
_cache: dict = {}


def _fetch(path: str) -> list:
    import time
    key = f"{date.today()}:{path}"
    if key in _cache:
        return _cache[key]
    with httpx.Client(timeout=12, headers=_HDRS) as c:
        r = c.get(_BASE + path)
        r.raise_for_status()
        data = json.loads(r.content.decode("utf-8", errors="replace"))
    _cache[key] = data if isinstance(data, list) else []
    return _cache[key]


def _pct(s: str) -> float:
    """'20.25%' → 0.2025"""
    try:
        return float(str(s).replace("%", "").strip()) / 100
    except Exception:
        return 0.0


def _sf(v) -> float | None:
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f >= 0 else None
    except Exception:
        return None


def _settlement_day(year: int, month: int) -> date:
    """台灣期貨結算日：當月第三個星期三"""
    count = 0
    for day in range(1, monthrange(year, month)[1] + 1):
        d = date(year, month, day)
        if d.weekday() == 2:
            count += 1
            if count == 3:
                return d
    return date(year, month, monthrange(year, month)[1])


def _days_left(month_str: str) -> int:
    try:
        y, m = int(month_str[:4]), int(month_str[4:6])
        return max(0, (_settlement_day(y, m) - date.today()).days)
    except Exception:
        return 0


# ── 標的清單端點 ────────────────────────────────────────────────────────

@router.get("/api/futures/list")
def get_futures_list():
    """回傳所有個股期標的清單（從 TAIFEX SSFLists）"""
    from warrant import db as _db

    try:
        ssf_list = _fetch("/SSFLists")
    except Exception as e:
        log.warning(f"[SSFLists] 失敗: {e}")
        return []

    # 從 DB 取股票名稱
    with _db.db() as conn:
        ul_rows = conn.execute("SELECT code, name FROM underlyings").fetchall()
    name_map = {r["code"]: r["name"] for r in ul_rows}

    # 按 StockCode 分組
    stocks: dict = {}
    for item in ssf_list:
        code = str(item.get("StockCode", "")).strip()
        if not code:
            continue
        contract = str(item.get("Contract", "")).strip()
        # 判斷 mini：Type 欄位含「小型」或 Contract 代號以 Q/X 開頭
        type_str = str(item.get("Type", "")).strip()
        is_mini = "小型" in type_str or contract.startswith("Q") or contract.startswith("X")
        if code not in stocks:
            stocks[code] = {
                "stock_code": code,
                "stock_name": name_map.get(code, ""),
                "contracts": []
            }
        stocks[code]["contracts"].append({
            "code": contract,
            "is_mini": is_mini,
            "type_label": "小型" if is_mini else "標準"
        })

    result = sorted(stocks.values(), key=lambda x: x["stock_code"])
    return result


# ── 主端點 ──────────────────────────────────────────────────────────────

@router.get("/api/futures/{stock_id}")
def get_futures(
    stock_id: str,
    capital: int = Query(0, ge=0, description="本金（元），用於試算可買口數"),
):
    from warrant import db as _db
    from warrant import mis_proxy as mis

    # ── 1. 股票基本資料 ─────────────────────────────────────────────────
    with _db.db() as conn:
        ul_row = conn.execute(
            "SELECT code, name, market FROM underlyings WHERE code=?", (stock_id,)
        ).fetchone()

    if not ul_row:
        # 嘗試從 stocks.csv 補建 underlyings 記錄
        import os, pandas as pd
        _csv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stocks.csv")
        try:
            _df = pd.read_csv(_csv, dtype=str, encoding="utf-8")
            _row = _df[_df["stock_id"] == stock_id]
            if _row.empty:
                raise HTTPException(404, f"找不到股票 {stock_id}")
            _name   = str(_row.iloc[0]["stock_name"])
            _market = "TSE" if str(_row.iloc[0]["type"]) == "twse" else "OTC"
            with _db.db() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO underlyings(code, name, market, updated_at)
                    VALUES(?, ?, ?, datetime('now'))
                """, (stock_id, _name, _market))
            with _db.db() as conn:
                ul_row = conn.execute(
                    "SELECT code, name, market FROM underlyings WHERE code=?", (stock_id,)
                ).fetchone()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(404, f"股票 {stock_id} 不在資料庫") from e

    if not ul_row:
        raise HTTPException(404, f"找不到股票 {stock_id}")

    stock_name = ul_row["name"]
    market     = ul_row["market"]

    # ── 2. 現貨即時報價 ─────────────────────────────────────────────────
    prefix  = "tse" if market != "OTC" else "otc"
    ul_key  = f"{prefix}_{stock_id}"
    ul_q    = mis.get_quotes([ul_key])
    ul_item = ul_q.get(stock_id) or ul_q.get(ul_key, {})
    spot_raw   = mis.parse_price(ul_item) if ul_item else {}
    spot_price = spot_raw.get("price") or spot_raw.get("prev_close")

    # ── 3. TAIFEX SSFLists → 取得該股的 Contract code(s) ──────────────
    try:
        ssf_list = _fetch("/SSFLists")
    except Exception as e:
        log.warning(f"[SSFLists] 失敗: {e}")
        ssf_list = []

    # StockCode 精確比對
    matched_contracts = {
        item["Contract"]: item
        for item in ssf_list
        if str(item.get("StockCode", "")).strip() == stock_id
    }

    if not matched_contracts:
        return {
            "stock":         {"id": stock_id, "name": stock_name, "spot_price": spot_price, "market": market},
            "capital":       capital,
            "standard_near": None,
            "standard_far":  None,
            "mini_near":     None,
            "mini_far":      None,
            "_debug": {"contract_codes": [], "daily_matched": 0, "msg": "SSFLists 中找不到此股票"},
        }

    contract_codes = list(matched_contracts.keys())   # e.g. ['CDF', 'QFF']

    # ── 4. TAIFEX 日行情 ────────────────────────────────────────────────
    try:
        daily_all = _fetch("/DailyMarketReportFut")
    except Exception as e:
        log.warning(f"[DailyMarketReportFut] 失敗: {e}")
        daily_all = []

    # 日行情：Contract 欄位格式為 "DQF"（無月份後綴）
    # ContractMonth(Week) 為 "202609"（月契約）或 "202609W1"（週契約，排除）
    daily_matched = [
        item for item in daily_all
        if item.get("Contract", "").strip() in contract_codes
        and len(str(item.get("ContractMonth(Week)", "")).strip()) == 6   # 只取月契約
    ]

    # ── 5. 保證金率 ──────────────────────────────────────────────────────
    try:
        margin_all = _fetch("/SingleStockFuturesMargining")
    except Exception as e:
        log.warning(f"[SingleStockFuturesMargining] 失敗: {e}")
        margin_all = []

    # 保證金：UnderlyingSecurityCode 精確比對（一個股票代號對應一個保證金率）
    margin_info = {}
    for m in margin_all:
        if str(m.get("UnderlyingSecurityCode", "")).strip() == stock_id:
            margin_info = m
            break
    init_rate  = _pct(margin_info.get("InitialMarginRate", "0%"))
    maint_rate = _pct(margin_info.get("MaintenanceMarginRate", "0%"))

    # ── 6. 組合合約卡 ────────────────────────────────────────────────────
    contracts = []
    for item in daily_matched:
        contract    = item["Contract"].strip()
        month_str   = str(item.get("ContractMonth(Week)", "")).strip()
        last_price  = _sf(item.get("Last"))
        settle      = _sf(item.get("SettlementPrice"))
        best_bid    = _sf(item.get("BestBid"))
        best_ask    = _sf(item.get("BestAsk"))
        volume      = int(_sf(item.get("Volume")) or 0)
        oi          = int(_sf(item.get("OpenInterest")) or 0)
        change      = _sf(item.get("Change"))
        change_pct  = item.get("%", "")

        # 報價：優先 last > settle
        price = last_price or settle

        # mini 判斷（通常 mini 的 Contract code 以 Q 或 X 開頭，可調整）
        ssf_type = matched_contracts[contract].get("Type", "")
        is_mini  = "小型" in ssf_type or contract.startswith("Q") or contract.startswith("X")
        size     = _MINI_SIZE if is_mini else _STANDARD_SIZE

        # 保證金計算（率 × 每口市值）
        contract_value  = round((price or 0) * size)
        orig_margin     = round(contract_value * init_rate)  if (contract_value and init_rate)  else 0
        maint_margin    = round(contract_value * maint_rate) if (contract_value and maint_rate) else 0

        # 基差
        basis     = round(price - spot_price, 2) if (price and spot_price) else None
        basis_pct = round(basis / spot_price * 100, 2) if (basis is not None and spot_price) else None

        # 槓桿
        leverage = round(contract_value / orig_margin, 1) if (contract_value and orig_margin) else None

        # 每口 1% 損益
        pnl_1pct = round(price * 0.01 * size) if price else None

        # 天數
        days = _days_left(month_str)
        expiry_label = f"{month_str[:4]}/{month_str[4:6]}"

        # 本金試算
        lots       = int(capital / orig_margin) if (capital and orig_margin) else 0
        margin_used= lots * orig_margin
        cap_left   = capital - margin_used

        contracts.append({
            "product_code":       contract,
            "expiry_month":       month_str,
            "expiry_label":       expiry_label,
            "days_to_expiry":     days,
            "price":              price,
            "best_bid":           best_bid,
            "best_ask":           best_ask,
            "change":             change,
            "change_pct":         change_pct,
            "volume":             volume,
            "open_interest":      oi,
            "contract_size":      size,
            "contract_value":     contract_value,
            "basis":              basis,
            "basis_pct":          basis_pct,
            "init_margin_rate":   round(init_rate * 100, 2),
            "original_margin":    orig_margin,
            "maintenance_margin": maint_margin,
            "leverage":           leverage,
            "is_mini":            is_mini,
            "lots_affordable":    lots,
            "margin_used":        margin_used,
            "capital_left":       cap_left,
            "pnl_per_lot_1pct":   pnl_1pct,
        })

    # 按到期月份排序
    contracts.sort(key=lambda x: x["expiry_month"])

    standard = [c for c in contracts if not c["is_mini"]]
    mini     = [c for c in contracts if c["is_mini"]]

    return {
        "stock": {
            "id":          stock_id,
            "name":        stock_name,
            "spot_price":  spot_price,
            "market":      market,
        },
        "capital":        capital,
        "standard_near":  standard[0] if len(standard) > 0 else None,
        "standard_far":   standard[1] if len(standard) > 1 else None,
        "mini_near":      mini[0] if len(mini) > 0 else None,
        "mini_far":       mini[1] if len(mini) > 1 else None,
        "_debug": {
            "contract_codes": contract_codes,
            "daily_matched": len(daily_matched),
            "margin_rate":   f"原始{round(init_rate*100,2)}% 維持{round(maint_rate*100,2)}%",
        },
    }
