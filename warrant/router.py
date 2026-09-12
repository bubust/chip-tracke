"""
warrant/router.py — 權證選擇器 API routes（整合進 chip-tracker 用）
所有路由定義在 router，由 chip-tracker/server.py include_router(warrant_router, prefix="/warrant")
"""
import logging
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Query
from apscheduler.schedulers.background import BackgroundScheduler

from . import db as _db
from . import calculator as calc
from . import ingester
from . import mis_proxy as mis
from .futures import router as _futures_router

log = logging.getLogger(__name__)

# 載入設定
_CFG_PATH = Path(__file__).parent / "thresholds.yaml"

def _load_cfg():
    with open(_CFG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)

CFG = _load_cfg()
DEFAULTS = CFG["defaults"]
FILTERS  = CFG["filters"]
BS_CFG   = CFG["bs"]
WARNINGS = CFG["warnings"]

router = APIRouter()
router.include_router(_futures_router)

# ── Scheduler ───────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="Asia/Taipei")

def init_warrant():
    """chip-tracker server.py 的 lifespan 裡呼叫"""
    _db.init_db()
    import threading
    with _db.db() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM warrants").fetchone()[0]
    if cnt == 0:
        log.info("[warrant] DB 為空，背景初始化合約檔...")
        def _bg_init():
            try:
                ingester.ingest_contracts()
                log.info("[warrant] 初始合約檔完成")
            except Exception as e:
                log.error(f"[warrant] 初始合約檔失敗: {e}")
        threading.Thread(target=_bg_init, daemon=True).start()

def start_warrant_scheduler():
    scheduler.add_job(lambda: ingester.ingest_contracts(), "cron", hour=8, minute=0, id="w_contracts", replace_existing=True)
    scheduler.add_job(lambda: ingester.backfill_biv_for_underlyings(ingester.get_active_underlying_codes()[:50]), "cron", hour=8, minute=45, id="w_biv", replace_existing=True)
    if not scheduler.running:
        scheduler.start()

def stop_warrant_scheduler():
    if scheduler.running:
        scheduler.shutdown()

# ── 工具函式 ────────────────────────────────────────────────────────────
def _get_iv_stability(warrant_code: str) -> tuple[float, int]:
    with _db.db() as conn:
        rows = conn.execute("""
            SELECT bid_iv FROM iv_daily
            WHERE warrant_code=? AND source='SINOPAC'
            ORDER BY trade_date DESC LIMIT 20
        """, (warrant_code,)).fetchall()
    if len(rows) < 2:
        return 0.0, len(rows)
    vals = [r[0] for r in rows]
    n = len(vals)
    mean = sum(vals) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
    return round(std * 100, 3), n

def _build_warrant_card(w_row, mis_item: dict, underlying_price: float, cfg: dict) -> Optional[dict]:
    fee_discount  = cfg.get("fee_discount",  DEFAULTS["fee_discount"])
    holding_days  = cfg.get("holding_days",  DEFAULTS["holding_days"])
    position_size = cfg.get("position_size", DEFAULTS["position_size"])
    r_free = BS_CFG["risk_free_rate"]
    q      = 0.0

    S = underlying_price
    K = w_row["strike"]
    N = w_row["exercise_ratio"]
    kind = w_row["kind"]

    today = date.today()
    try:
        last_td = date.fromisoformat(w_row["last_trade_date"])
    except Exception:
        return None
    T = (last_td - today).days / 365
    if T <= 0:
        return None

    q_price = mis.parse_price(mis_item)
    bid = q_price["bid"]
    ask = q_price["ask"]
    bid_lots = q_price["bid_lots"]
    ask_lots = q_price["ask_lots"]

    # 盤後用前日收盤代替 bid（已在主流程過濾，這裡做保底）
    if bid is None or bid <= 0:
        prev = q_price.get("prev_close")
        if prev and prev > 0:
            bid = prev
            ask = prev
        else:
            return None

    warrant_price = (bid + ask) / 2 if ask else bid

    bid_iv = calc.implied_vol(bid, S, K, N, T, r_free, q, kind)
    ask_iv = calc.implied_vol(ask, S, K, N, T, r_free, q, kind) if ask else None

    if bid_iv is None:
        return None

    greeks = calc.bs_greeks(S, K, T, r_free, q, bid_iv, kind, N)
    delta       = greeks["delta"]
    vega        = greeks["vega"]
    theta_daily = greeks["theta_daily"]

    if delta is None:
        return None

    iv_stab_pt, iv_stab_n = _get_iv_stability(w_row["code"])

    hurdle = calc.total_hurdle(
        bid=bid, ask=ask or bid * 1.02,
        S=S, delta=delta, vega=vega, theta_daily=theta_daily,
        warrant_price=warrant_price,
        fee_discount=fee_discount, holding_days=holding_days,
        iv_stability_pt=iv_stab_pt,
    )
    if not hurdle:
        return None

    tick = calc.warrant_tick(bid)
    spread_ratio = (ask - bid) / bid if ask else None
    min_spread_ratio = tick / bid
    spread_is_tightest = (ask - bid) <= tick * 1.01 if ask else False

    bid_value = bid * bid_lots * 1000
    moneyness = (S - K) / K if kind == "CALL" else (K - S) / K

    with _db.db() as conn:
        ul = conn.execute("SELECT hv20 FROM underlyings WHERE code=?", (w_row["underlying_code"],)).fetchone()
    hv20 = ul["hv20"] if ul and ul["hv20"] else None
    iv_ratio = (bid_iv / hv20) if hv20 and hv20 > 0 else None

    lights = calc.three_lights(
        entry_h=hurdle["entry_hurdle"], time_h=hurdle["time_hurdle"], iv_h=hurdle["iv_hurdle"],
        stock_entry_h=hurdle["stock_entry_hurdle"], is_cheaper=hurdle["is_cheaper_than_stock"],
        spread_ratio=spread_ratio or 0, bid_value=bid_value, position_size=position_size, bid_lots=bid_lots,
    )

    flags = []
    eff_lev = hurdle.get("effective_leverage", 0)
    if eff_lev > WARNINGS["leverage_high"]:          flags.append("LEVERAGE_HIGH")
    if iv_ratio and iv_ratio > WARNINGS["iv_ratio_high"]: flags.append("IV_EXPENSIVE")
    if hurdle.get("iv_drop_1pt_loss_pct", 0) > WARNINGS["iv_drop_loss_high"]: flags.append("IV_SENSITIVE")
    if iv_stab_n < WARNINGS["iv_stability_min_samples"]: flags.append("IV_STABILITY_LOW")

    return {
        "code": w_row["code"], "name": w_row["name"], "issuer": w_row["issuer"],
        "kind": kind, "style": w_row["style"],
        "bid": bid, "ask": ask, "bid_lots": bid_lots, "ask_lots": ask_lots,
        "bid_value": bid_value,
        "spread_ratio": round(spread_ratio, 6) if spread_ratio else None,
        "min_spread_ratio": round(min_spread_ratio, 6),
        "spread_is_tightest": spread_is_tightest,
        "strike": K, "exercise_ratio": N,
        "moneyness": round(moneyness, 4),
        "days_to_expiry": (last_td - today).days,
        "expiry_date": w_row["last_trade_date"],
        "delta": float(round(delta, 6)),
        "vega": float(round(vega, 6)),
        "theta_daily": float(round(theta_daily, 6)),
        "iv": float(round(bid_iv, 6)),
        "ask_iv": float(round(ask_iv, 6)) if ask_iv else None,
        "iv_ratio": float(round(iv_ratio, 4)) if iv_ratio else None,
        "iv_stability_pt": iv_stab_pt,
        "iv_stability_samples": iv_stab_n,
        "iv_drop_1pt_loss_pct": round(hurdle.get("iv_drop_1pt_loss_pct", 0), 6),
        "outstanding_ratio": None,
        "total_hurdle_pct": float(hurdle["total_hurdle_pct"]) if hurdle.get("total_hurdle_pct") is not None else None,
        "entry_hurdle_pct": float(hurdle["entry_hurdle"]) if hurdle.get("entry_hurdle") is not None else None,
        "time_hurdle_pct": float(hurdle["time_hurdle"]) if hurdle.get("time_hurdle") is not None else None,
        "iv_hurdle_pct": float(hurdle["iv_hurdle"]) if hurdle.get("iv_hurdle") is not None else None,
        "effective_leverage": float(round(hurdle.get("effective_leverage", 0), 4)),
        "is_cheaper_than_stock": bool(hurdle.get("is_cheaper_than_stock")),
        "lights": lights,
        "flags": flags,
        "issuer_score": None,
    }

def _yahoo_close(stock_id: str, market: str) -> Optional[float]:
    """Yahoo Finance 備用報價（MIS 被境外 IP 封鎖時使用）"""
    suffix = ".TW" if market == "TSE" else ".TWO"
    ticker = f"{stock_id}{suffix}"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
    try:
        with httpx.Client(timeout=8, headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = c.get(url)
            data = r.json()
        result = (data.get("chart", {}).get("result") or [])
        if not result:
            return None
        closes = result[0]["indicators"]["quote"][0].get("close", [])
        closes = [x for x in closes if x is not None]
        return round(float(closes[-1]), 2) if closes else None
    except Exception as e:
        log.warning(f"[warrant] Yahoo fallback 失敗 {stock_id}: {e}")
        return None


def apply_hard_filters(w_row, today: date) -> Optional[str]:
    try:
        last_td = date.fromisoformat(w_row["last_trade_date"])
    except Exception:
        return "INVALID_DATE"
    days_left = (last_td - today).days
    if days_left < FILTERS["min_days_to_last_trade"]:
        return "DAYS_TOO_FEW"
    if w_row["style"] != "PLAIN":
        return "NON_PLAIN"
    return None

# ── API Routes ───────────────────────────────────────────────────────────
@router.get("/api/search")
def search(q: str = Query(..., min_length=1)):
    q = q.strip()
    results = []
    with _db.db() as conn:
        wrow = conn.execute("SELECT underlying_code FROM warrants WHERE code=? AND is_active=1", (q,)).fetchone()
        if wrow and wrow["underlying_code"]:
            ul = conn.execute("SELECT code,name,market FROM underlyings WHERE code=?", (wrow["underlying_code"],)).fetchone()
            if ul:
                cnt = conn.execute("SELECT COUNT(*) FROM warrants WHERE underlying_code=? AND is_active=1", (ul["code"],)).fetchone()[0]
                results.append({"code": ul["code"], "name": ul["name"], "market": ul["market"], "warrant_count": cnt, "matched_by": "WARRANT", "highlight_warrant": q})
                return {"results": results}
        rows = conn.execute("""
            SELECT u.code, u.name, u.market, COUNT(w.code) as warrant_count
            FROM underlyings u
            LEFT JOIN warrants w ON w.underlying_code=u.code AND w.is_active=1 AND w.last_trade_date >= date('now')
            WHERE u.code LIKE ? OR u.name LIKE ?
            GROUP BY u.code ORDER BY warrant_count DESC LIMIT 10
        """, (f"{q}%", f"%{q}%")).fetchall()
        for r in rows:
            results.append({"code": r["code"], "name": r["name"], "market": r["market"], "warrant_count": r["warrant_count"], "matched_by": "UNDERLYING"})

    # 若搜尋結果為空，回傳初始化狀態提示
    if not results:
        with _db.db() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM underlyings").fetchone()[0]
        if cnt == 0:
            return {"results": [], "initializing": True, "message": "資料庫初始化中，請稍後 1~2 分鐘再試"}
    return {"results": results}

@router.get("/api/warrants")
def get_warrants(
    underlying: str,
    side: str = "call",
    holding_days: int = Query(7, ge=3, le=10),
    fee_discount: float = Query(0.6, ge=0.1, le=1.0),
    position_size: int = Query(100000, ge=10000),
    max_otm: float = Query(0.10, ge=0.0, le=0.50),
    sort: str = Query("entry"),
):
    kind = "CALL" if side.lower() == "call" else "PUT"
    today = date.today()
    _filters = _load_cfg()["filters"]
    cfg = {"fee_discount": fee_discount, "holding_days": holding_days, "position_size": position_size}

    with _db.db() as conn:
        ul_row = conn.execute("SELECT * FROM underlyings WHERE code=?", (underlying,)).fetchone()
    if not ul_row:
        raise HTTPException(404, f"標的 {underlying} 不存在")

    ul_market_prefix = "tse" if ul_row["market"] == "TSE" else "otc"
    ul_code_key = f"{ul_market_prefix}_{underlying}"
    ul_quotes = mis.get_quotes([ul_code_key])
    ul_item = ul_quotes.get(underlying) or ul_quotes.get(ul_code_key, {})
    ul_price_data = mis.parse_price(ul_item) if ul_item else {}
    S = ul_price_data.get("price")

    if S is None:
        with _db.db() as conn:
            daily = conn.execute("SELECT close_price FROM warrant_daily WHERE warrant_code=? ORDER BY trade_date DESC LIMIT 1", (underlying,)).fetchone()
        S = daily["close_price"] if daily else None

    if not S:
        # MIS 可能被境外 IP 封鎖，改用 Yahoo Finance
        S = _yahoo_close(underlying, ul_row["market"])

    if not S:
        raise HTTPException(503, "無法取得標的現價")

    m_state = mis.market_state(ul_item) if ul_item else "AFTER_HOURS"

    with _db.db() as conn:
        candidates = conn.execute("""
            SELECT * FROM warrants
            WHERE underlying_code=? AND kind=? AND is_active=1
              AND last_trade_date >= date('now', '+60 days') AND style='PLAIN'
            ORDER BY last_trade_date
        """, (underlying, kind)).fetchall()

    if not candidates:
        return {"underlying": {"code": underlying, "name": ul_row["name"], "price": S, "market": ul_row["market"]}, "market_state": m_state, "warrants": [], "excluded_count": 0, "excluded_reasons": [], "warnings": []}

    w_codes = [(f"otc_{r['code']}" if r["market"] == "OTC" else r["code"]) for r in candidates[:50]]
    mis_data = mis.get_quotes(w_codes)

    results = []
    excluded = {}

    for w_row in candidates[:50]:
        code = w_row["code"]
        mis_key = f"otc_{code}" if w_row["market"] == "OTC" else code
        mis_item = mis_data.get(code) or mis_data.get(mis_key, {})

        reason = apply_hard_filters(w_row, today)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue

        if not mis_item:
            excluded["NO_QUOTE"] = excluded.get("NO_QUOTE", 0) + 1
            continue

        price_data = mis.parse_price(mis_item)
        bid = price_data.get("bid")
        ask = price_data.get("ask")
        bid_lots = price_data.get("bid_lots", 0)
        ask_lots = price_data.get("ask_lots", 0)

        # 盤後/週末無 bid → 用前日收盤價代替（仍可計算理論值）
        if (bid is None or bid <= 0) and m_state == "AFTER_HOURS":
            prev = price_data.get("prev_close")
            if prev and prev > 0:
                bid = prev
                ask = prev
            else:
                excluded["NO_BID"] = excluded.get("NO_BID", 0) + 1
                continue
        elif bid is None or bid <= 0:
            excluded["NO_BID"] = excluded.get("NO_BID", 0) + 1
            continue

        if ask is None:
            ask = bid
        if ask < _filters["min_ask_price"]:
            excluded["ASK_TOO_LOW"] = excluded.get("ASK_TOO_LOW", 0) + 1
            continue
        if ask_lots < _filters["min_ask_lots"] and m_state == "OPEN":
            excluded["ASK_LOTS_TOO_FEW"] = excluded.get("ASK_LOTS_TOO_FEW", 0) + 1
            continue

        spread = (ask - bid) / bid if bid > 0 else 1
        tick = calc.warrant_tick(bid)
        is_tightest = (ask - bid) <= tick * 1.01

        if spread > _filters["max_spread_ratio"] and not is_tightest:
            excluded["SPREAD_TOO_WIDE"] = excluded.get("SPREAD_TOO_WIDE", 0) + 1
            continue

        K = w_row["strike"]
        moneyness = (S - K) / K if kind == "CALL" else (K - S) / K
        if moneyness < -max_otm:
            excluded["DEEP_OTM"] = excluded.get("DEEP_OTM", 0) + 1
            continue

        card = _build_warrant_card(dict(w_row), mis_item, S, cfg)
        if card is None:
            excluded["CALC_FAILED"] = excluded.get("CALC_FAILED", 0) + 1
            continue

        results.append(card)

    if sort == "total":
        results.sort(key=lambda x: (round((x["total_hurdle_pct"] or 99) * 10000), -(x["bid_value"] or 0)))
    else:
        results.sort(key=lambda x: (round((x["entry_hurdle_pct"] or 99) * 10000), -(x["bid_value"] or 0)))

    limit_status = None
    if ul_price_data.get("limit_up") and S and S >= ul_price_data["limit_up"] * 0.999:
        limit_status = "LIMIT_UP"
    elif ul_price_data.get("limit_down") and S and S <= ul_price_data["limit_down"] * 1.001:
        limit_status = "LIMIT_DOWN"

    excluded_count = sum(excluded.values())
    excluded_reasons = [f"{k}（{v} 檔）" for k, v in excluded.items()]
    change_pct = None
    prev = ul_price_data.get("prev_close")
    if S and prev and prev > 0:
        change_pct = (S - prev) / prev * 100

    return {
        "underlying": {"code": underlying, "name": ul_row["name"], "price": S, "change_pct": change_pct, "hv20": ul_row["hv20"], "hv60": ul_row["hv60"], "limit_status": limit_status, "market_state": m_state, "data_time": ul_price_data.get("data_time")},
        "quote_time": datetime.now().isoformat(timespec="seconds"),
        "market_state": m_state,
        "warrants": results,
        "excluded_count": excluded_count,
        "excluded_reasons": excluded_reasons,
        "warnings": ["盤後模式：以前日收盤價計算，僅供參考"] if m_state == "AFTER_HOURS" and results else [],
    }

@router.get("/api/excluded")
def get_excluded(underlying: str, side: str = "call", reason: str = ""):
    kind = "CALL" if side.lower() == "call" else "PUT"
    today = date.today()
    with _db.db() as conn:
        rows = conn.execute("SELECT code, name, issuer, kind, style, strike, last_trade_date FROM warrants WHERE underlying_code=? AND kind=? AND is_active=1", (underlying, kind)).fetchall()
    excluded_detail = []
    for r in rows:
        reason_code = apply_hard_filters(r, today)
        if reason_code and (not reason or reason == reason_code):
            excluded_detail.append({"code": r["code"], "name": r["name"], "reason": reason_code, "last_trade_date": r["last_trade_date"]})
    return excluded_detail

@router.get("/api/config")
def get_config():
    with _db.db() as conn:
        rows = conn.execute("SELECT key,value FROM config").fetchall()
    saved = {r["key"]: r["value"] for r in rows}
    return {"fee_discount": float(saved.get("fee_discount", DEFAULTS["fee_discount"])), "holding_days": int(saved.get("holding_days", DEFAULTS["holding_days"])), "position_size": int(saved.get("position_size", DEFAULTS["position_size"]))}

@router.put("/api/config")
def put_config(body: dict):
    with _db.db() as conn:
        for k, v in body.items():
            if k in ("fee_discount", "holding_days", "position_size"):
                conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)", (k, str(v)))
    return {"ok": True}

@router.get("/api/warrant-watchlist")
def get_watchlist():
    with _db.db() as conn:
        rows = conn.execute("SELECT w.underlying_code, u.name, u.market FROM watchlist w JOIN underlyings u ON u.code=w.underlying_code ORDER BY w.sort_order, w.id").fetchall()
    return [{"code": r["underlying_code"], "name": r["name"], "market": r["market"]} for r in rows]

@router.post("/api/warrant-watchlist")
def add_watchlist(body: dict):
    code = body.get("code", "").strip()
    if not code:
        raise HTTPException(400, "code 必填")
    with _db.db() as conn:
        conn.execute("INSERT OR IGNORE INTO watchlist(underlying_code) VALUES(?)", (code,))
    return {"ok": True}

@router.delete("/api/warrant-watchlist/{code}")
def del_watchlist(code: str):
    with _db.db() as conn:
        conn.execute("DELETE FROM watchlist WHERE underlying_code=?", (code,))
    return {"ok": True}

@router.post("/api/ingest/now")
def trigger_ingest():
    n = ingester.ingest_contracts()
    return {"warrants_upserted": n}

@router.get("/api/warrant-status")
def warrant_status():
    with _db.db() as conn:
        warrants = conn.execute("SELECT COUNT(*) FROM warrants WHERE is_active=1").fetchone()[0]
        underlyings = conn.execute("SELECT COUNT(*) FROM underlyings").fetchone()[0]
        iv_records = conn.execute("SELECT COUNT(*) FROM iv_daily").fetchone()[0]
    return {"warrants": warrants, "underlyings": underlyings, "iv_records": iv_records, "time": datetime.now().isoformat()}
