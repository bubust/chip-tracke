"""
Positioning Engine V1 — Data Fetchers
Fetches from TAIFEX and TWSE for all positioning inputs.
"""

import asyncio
import csv
import io
import json
import logging
from datetime import date, datetime, timedelta

import httpx

from .db import get_conn, DB_PATH

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
}

# ── helpers ───────────────────────────────────────────────────────────────────

def _int(s: str) -> int | None:
    try:
        return int(s.replace(",", "").strip())
    except Exception:
        return None


def _float(s: str) -> float | None:
    try:
        return float(s.replace(",", "").strip())
    except Exception:
        return None


def _last_trading_day_str() -> str:
    d = date.today()
    for _ in range(7):
        if d.weekday() < 5:
            return d.strftime("%Y/%m/%d")
        d -= timedelta(days=1)
    return date.today().strftime("%Y/%m/%d")


def _to_trading_day(d: date) -> date:
    """If d is a weekend, return the previous weekday."""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _fmt(d: date) -> str:
    return d.strftime("%Y/%m/%d")


# ── TAIFEX: institutional futures (TX / MTX / TMF) ───────────────────────────

async def fetch_taifex_inst_futures(target_date: date | None = None) -> dict:
    """
    Download 三大法人期貨未平倉 from futContractsDateDown.
    Returns raw rows keyed by (identity, contract).
    """
    dt_str = _fmt(_to_trading_day(target_date)) if target_date else _last_trading_day_str()
    url = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
    payload = {"queryStartDate": dt_str, "queryEndDate": dt_str}

    rows_out = {}
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        r = await client.post(url, data=payload)
        text = r.content.decode("ms950", errors="replace")

    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 13:
            continue
        identity = row[0].strip()
        contract = row[1].strip()
        if not identity or not contract:
            continue
        # Only care about TX, MTX (小型臺指), TMF (臺灣永續)
        key = None
        if "臺股期貨" in contract or contract == "TX":
            key = (identity, "TX")
        elif "小型臺指" in contract or "MXF" in contract:
            key = (identity, "MTX")
        elif "永續" in contract or "TMF" in contract:
            key = (identity, "TMF")
        else:
            continue
        rows_out[key] = {
            "trade_long": _int(row[2]) if len(row) > 2 else None,
            "trade_short": _int(row[4]) if len(row) > 4 else None,
            "trade_net": _int(row[6]) if len(row) > 6 else None,
            "oi_long": _int(row[8]) if len(row) > 8 else None,
            "oi_short": _int(row[10]) if len(row) > 10 else None,
            "oi_net": _int(row[12]) if len(row) > 12 else None,
        }
    return rows_out, dt_str


# ── TAIFEX: large trader futures ──────────────────────────────────────────────

async def fetch_taifex_large_trader(target_date: date | None = None) -> dict:
    """
    Download 期貨大額交易人未平倉 from largeTraderFutDown.
    Returns top5/top10 long/short and market total for TX-equivalent contracts.
    """
    dt_str = _fmt(_to_trading_day(target_date)) if target_date else _last_trading_day_str()
    url = "https://www.taifex.com.tw/cht/3/largeTraderFutDown"
    payload = {"queryStartDate": dt_str, "queryEndDate": dt_str}

    result = {}
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        r = await client.post(url, data=payload)
        text = r.content.decode("ms950", errors="replace")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    # TAIFEX large trader CSV:
    # row[0]=日期, row[1]=契約, row[2]=到期月份,
    # row[3]=前五大多方口數, row[4]=前五大空方口數,
    # row[5]=前十大多方口數, row[6]=前十大空方口數,
    # row[7]=全市場多方口數, row[8]=全市場空方口數
    for row in rows:
        if len(row) < 9:
            continue
        contract_raw = row[1].strip()
        month = row[2].strip()

        # Only use "所有序列" / combined row (month=="所有序列" or "全部" or blank)
        is_all = month in ("", "所有序列", "全部", "全月份")
        if not is_all:
            continue

        key = None
        if "臺股期貨" in contract_raw or contract_raw in ("TX", "臺指"):
            key = "TX"
        elif "小型臺指" in contract_raw or contract_raw == "MTX":
            key = "MTX"
        elif "永續" in contract_raw or contract_raw == "TMF":
            key = "TMF"
        else:
            continue

        result[key] = {
            "top5_long": _int(row[3]),
            "top5_short": _int(row[4]),
            "top10_long": _int(row[5]),
            "top10_short": _int(row[6]),
            "market_long": _int(row[7]),
            "market_short": _int(row[8]),
        }

    return result, dt_str


# ── TAIFEX: options (PCR + institutional) ────────────────────────────────────

async def fetch_taifex_inst_options(target_date: date | None = None) -> dict:
    """
    Download 三大法人選擇權未平倉 from optContractsDateDown.
    Also compute PCR-OI from total call/put across all series.
    """
    dt_str = _fmt(_to_trading_day(target_date)) if target_date else _last_trading_day_str()
    url = "https://www.taifex.com.tw/cht/3/optContractsDateDown"
    payload = {"queryStartDate": dt_str, "queryEndDate": dt_str}

    inst_result = {}   # keyed by identity
    pcr_data = {}      # ALL / NEAR

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        r = await client.post(url, data=payload)
        text = r.content.decode("ms950", errors="replace")

    reader = csv.reader(io.StringIO(text))
    # optContractsDateDown columns:
    # row[0]=身份別, row[1]=買賣權別(CALL/PUT), row[2]=多方OI, row[3]=多方金額,
    # row[4]=空方OI, row[5]=空方金額, row[6]=淨額OI, row[7]=淨額金額
    # (The CSV has separate rows for CALL and PUT per institution)

    call_oi_all = 0
    put_oi_all = 0
    call_vol_all = 0
    put_vol_all = 0

    for row in reader:
        if len(row) < 7:
            continue
        identity = row[0].strip()
        cp = row[1].strip()  # CALL or PUT

        is_call = "CALL" in cp.upper() or "買權" in cp
        is_put = "PUT" in cp.upper() or "賣權" in cp

        if not (is_call or is_put):
            continue

        long_oi = _int(row[2]) or 0
        long_val = _int(row[3]) or 0
        short_oi = _int(row[4]) or 0
        short_val = _int(row[5]) or 0
        net_oi = _int(row[6]) or 0
        net_val = _int(row[7]) if len(row) > 7 else 0

        # Aggregate for PCR
        if is_call:
            call_oi_all += long_oi + short_oi
        else:
            put_oi_all += long_oi + short_oi

        # Foreign institutional options
        if "外資" in identity:
            if identity not in inst_result:
                inst_result[identity] = {
                    "buy_call_oi": 0, "sell_call_oi": 0,
                    "buy_put_oi": 0, "sell_put_oi": 0,
                    "buy_call_value": 0, "sell_call_value": 0,
                    "buy_put_value": 0, "sell_put_value": 0,
                }
            d = inst_result[identity]
            if is_call:
                d["buy_call_oi"] += long_oi
                d["sell_call_oi"] += short_oi
                d["buy_call_value"] += long_val
                d["sell_call_value"] += short_val
            else:
                d["buy_put_oi"] += long_oi
                d["sell_put_oi"] += short_oi
                d["buy_put_value"] += long_val
                d["sell_put_value"] += short_val

    # PCR-OI
    pcr_oi_all = (put_oi_all / call_oi_all * 100) if call_oi_all else None

    # Foreign net:
    # Bullish: buy call + sell put (收取 put 權利金 = 空方保護)
    # Bearish: sell call + buy put
    foreign_row = None
    for k, v in inst_result.items():
        if "外資" in k:
            # net_value: (buy_call_value - sell_call_value) + (sell_put_value - buy_put_value)
            v["net_value"] = (
                (v["buy_call_value"] - v["sell_call_value"])
                + (v["sell_put_value"] - v["buy_put_value"])
            )
            # net_oi_value proxy (using OI counts as proxy)
            v["net_oi_value"] = (
                (v["buy_call_oi"] - v["sell_call_oi"])
                + (v["sell_put_oi"] - v["buy_put_oi"])
            )
            foreign_row = v
            break

    return {
        "pcr_oi_all": pcr_oi_all,
        "call_oi_all": call_oi_all,
        "put_oi_all": put_oi_all,
        "foreign": foreign_row or {},
    }, dt_str


# ── TWSE: institutional spot (T86) ───────────────────────────────────────────

async def fetch_twse_institutional_spot(target_date: date | None = None) -> dict:
    """
    Fetch 三大法人現貨 from TWSE T86.
    Returns foreign/trust/dealer net in 億元.
    """
    urls = [
        "https://openapi.twse.com.tw/v1/exchangeReport/T86",
        "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALL",
    ]

    data = None
    async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
        for url in urls:
            try:
                r = await client.get(url)
                j = r.json()
                # openapi returns list; twse returns {"data": [...], "fields": [...]}
                if isinstance(j, list):
                    # Find the "合計" row or last row with totals
                    for item in j:
                        if item.get("SecuritiesType") == "合計" or \
                           "合計" in item.get("Name", "") or \
                           item.get("Name") == "合計":
                            data = item
                            break
                    if not data and j:
                        data = j[-1]  # fallback to last row
                elif isinstance(j, dict) and "data" in j:
                    rows = j["data"]
                    fields = j.get("fields", [])
                    if rows:
                        last = rows[-1]
                        data = dict(zip(fields, last)) if fields else {"raw": last}
                if data:
                    break
            except Exception as e:
                log.warning(f"T86 fetch from {url} failed: {e}")
                continue

    if not data:
        return {}

    def _parse_bn(val):
        """Parse value string to 億元 (raw is 千元 from TWSE)."""
        try:
            # TWSE T86 unit is 千元; convert to 億元: /100000
            return round(float(str(val).replace(",", "")) / 100000, 2)
        except Exception:
            return None

    # Field name candidates (TWSE changes field names sometimes)
    def _get(d, *keys):
        for k in keys:
            if k in d:
                return d[k]
        return None

    foreign = _parse_bn(_get(data,
        "foreignDealersExcluded", "外陸資買賣超股數(不含外資自營商)",
        "foreignNetBuySell", "外資買賣超"))
    trust = _parse_bn(_get(data,
        "sitc", "投信買賣超股數", "trustNetBuySell", "投信買賣超"))
    dealer = _parse_bn(_get(data,
        "dealersTotal", "自營商買賣超股數(合計)", "dealerNetBuySell", "自營商買賣超"))

    return {
        "foreign_cash_net": foreign,
        "trust_cash_net": trust,
        "dealer_cash_net": dealer,
    }


# ── TAIFEX: total OI per contract ─────────────────────────────────────────────

async def fetch_taifex_total_oi(target_date: date | None = None) -> dict:
    """
    Fetch total market OI for TX, MTX, TMF from futContractsDateDown
    using the 全市場 row (not institutional).
    Also extracts market-wide volumes.
    """
    dt_str = _fmt(_to_trading_day(target_date)) if target_date else _last_trading_day_str()
    url = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
    payload = {"queryStartDate": dt_str, "queryEndDate": dt_str}

    result = {"total_tx_oi": None, "total_mtx_oi": None, "total_tmf_oi": None}

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        r = await client.post(url, data=payload)
        text = r.content.decode("ms950", errors="replace")

    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 9:
            continue
        identity = row[0].strip()
        contract = row[1].strip()
        # "全市場" row
        if "全市場" not in identity and identity != "":
            continue
        long_oi = _int(row[8]) if len(row) > 8 else None
        short_oi = _int(row[10]) if len(row) > 10 else None
        total = (long_oi or 0) + (short_oi or 0)
        if "臺股期貨" in contract:
            result["total_tx_oi"] = long_oi  # use long as proxy for total OI (symmetrical)
        elif "小型臺指" in contract:
            result["total_mtx_oi"] = long_oi
        elif "永續" in contract:
            result["total_tmf_oi"] = long_oi

    return result, dt_str


# ── Orchestrator ──────────────────────────────────────────────────────────────

async def fetch_all(target_date: date | None = None) -> dict:
    """
    Fetch all positioning data and store raw rows in DB.
    Returns a consolidated dict ready for calculator.
    """
    from .db import get_conn
    conn = get_conn()
    td = target_date or date.today()
    # Adjust to last weekday (TAIFEX has no data on weekends)
    while td.weekday() >= 5:
        td -= timedelta(days=1)
    td_str = td.strftime("%Y-%m-%d")

    # Parallel fetch
    (inst_fut, dt_str1), (large_trader, dt_str2), (options_data, dt_str3), \
    spot_data, (total_oi, dt_str4) = await asyncio.gather(
        fetch_taifex_inst_futures(target_date),
        fetch_taifex_large_trader(target_date),
        fetch_taifex_inst_options(target_date),
        fetch_twse_institutional_spot(target_date),
        fetch_taifex_total_oi(target_date),
    )

    # ── Store raw institutional futures ──
    for (identity, contract), vals in inst_fut.items():
        try:
            conn.execute("""
                INSERT INTO raw_taifex_inst_futures
                (observation_date, identity, contract, trade_long, trade_short, trade_net,
                 oi_long, oi_short, oi_net)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(observation_date, identity, contract) DO UPDATE SET
                trade_long=excluded.trade_long, trade_short=excluded.trade_short,
                trade_net=excluded.trade_net, oi_long=excluded.oi_long,
                oi_short=excluded.oi_short, oi_net=excluded.oi_net
            """, (td_str, identity, contract,
                  vals["trade_long"], vals["trade_short"], vals["trade_net"],
                  vals["oi_long"], vals["oi_short"], vals["oi_net"]))
        except Exception as e:
            log.warning(f"raw inst futures insert error: {e}")

    # ── Store raw large trader ──
    for contract, vals in large_trader.items():
        try:
            conn.execute("""
                INSERT INTO raw_taifex_large_trader
                (observation_date, contract, top5_long, top5_short,
                 top10_long, top10_short, market_long, market_short)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(observation_date, contract) DO UPDATE SET
                top5_long=excluded.top5_long, top5_short=excluded.top5_short,
                top10_long=excluded.top10_long, top10_short=excluded.top10_short,
                market_long=excluded.market_long, market_short=excluded.market_short
            """, (td_str, contract,
                  vals["top5_long"], vals["top5_short"],
                  vals["top10_long"], vals["top10_short"],
                  vals["market_long"], vals["market_short"]))
        except Exception as e:
            log.warning(f"raw large trader insert error: {e}")

    # ── Store raw options PCR ──
    try:
        conn.execute("""
            INSERT INTO raw_taifex_options_pcr
            (observation_date, scope, call_oi, put_oi)
            VALUES (?,?,?,?)
            ON CONFLICT(observation_date, scope) DO UPDATE SET
            call_oi=excluded.call_oi, put_oi=excluded.put_oi
        """, (td_str, "ALL",
              options_data.get("call_oi_all"), options_data.get("put_oi_all")))
    except Exception as e:
        log.warning(f"raw options pcr insert error: {e}")

    # ── Store raw TWSE institutional ──
    if spot_data:
        try:
            conn.execute("""
                INSERT INTO raw_twse_institutional
                (observation_date, foreign_net_bn, trust_net_bn, dealer_net_bn)
                VALUES (?,?,?,?)
                ON CONFLICT(observation_date) DO UPDATE SET
                foreign_net_bn=excluded.foreign_net_bn,
                trust_net_bn=excluded.trust_net_bn,
                dealer_net_bn=excluded.dealer_net_bn
            """, (td_str,
                  spot_data.get("foreign_cash_net"),
                  spot_data.get("trust_cash_net"),
                  spot_data.get("dealer_cash_net")))
        except Exception as e:
            log.warning(f"raw twse inst insert error: {e}")

    conn.commit()

    # ── Aggregate foreign futures OI (TX-equivalent) ──
    def _get_fut(identity_keyword, contract):
        for (ident, cont), vals in inst_fut.items():
            if identity_keyword in ident and cont == contract:
                return vals
        return {}

    foreign_tx = _get_fut("外資", "TX")
    foreign_mtx = _get_fut("外資", "MTX")
    foreign_tmf = _get_fut("外資", "TMF")

    # TX-equivalent: TX + MTX/4 + TMF/20
    def _eq(tx_val, mtx_val, tmf_val):
        return (tx_val or 0) + (mtx_val or 0) / 4 + (tmf_val or 0) / 20

    f_long = _eq(
        foreign_tx.get("oi_long"), foreign_mtx.get("oi_long"), foreign_tmf.get("oi_long")
    )
    f_short = _eq(
        foreign_tx.get("oi_short"), foreign_mtx.get("oi_short"), foreign_tmf.get("oi_short")
    )
    f_net = f_long - f_short

    # ── Large trader (use TX data as primary; merge MTX/TMF if available) ──
    tx_lt = large_trader.get("TX", {})

    # ── Retail MTX proxy ──
    # Retail = Market MTX - (自營商 + 投信 + 外資)
    inst_mtx_long = sum(
        v.get("oi_long") or 0 for (ident, cont), v in inst_fut.items()
        if cont == "MTX"
    )
    inst_mtx_short = sum(
        v.get("oi_short") or 0 for (ident, cont), v in inst_fut.items()
        if cont == "MTX"
    )

    mtx_data = large_trader.get("MTX", {})
    total_mtx_long = mtx_data.get("market_long") or 0
    total_mtx_short = mtx_data.get("market_short") or 0

    retail_long = max(0, total_mtx_long - inst_mtx_long)
    retail_short = max(0, total_mtx_short - inst_mtx_short)
    retail_net = retail_long - retail_short
    total_mtx_oi = total_mtx_long + total_mtx_short
    retail_ratio = (retail_net / total_mtx_oi * 100) if total_mtx_oi else None

    # ── Total OI TX-equivalent ──
    tx_total = total_oi.get("total_tx_oi") or 0
    mtx_total = total_oi.get("total_mtx_oi") or 0
    tmf_total = total_oi.get("total_tmf_oi") or 0
    tx_eq_total = tx_total + mtx_total / 4 + tmf_total / 20

    # ── Options ──
    foreign_opt = options_data.get("foreign", {})

    result = {
        "observation_date": td_str,
        # Cash
        "foreign_cash_net": spot_data.get("foreign_cash_net"),
        "trust_cash_net": spot_data.get("trust_cash_net"),
        "dealer_cash_net": spot_data.get("dealer_cash_net"),
        # Futures
        "foreign_futures_long_oi": round(f_long, 1),
        "foreign_futures_short_oi": round(f_short, 1),
        "foreign_futures_net_oi": round(f_net, 1),
        # Large traders
        "top5_long_oi": tx_lt.get("top5_long"),
        "top5_short_oi": tx_lt.get("top5_short"),
        "top5_net_oi": (tx_lt.get("top5_long") or 0) - (tx_lt.get("top5_short") or 0),
        "top10_long_oi": tx_lt.get("top10_long"),
        "top10_short_oi": tx_lt.get("top10_short"),
        "top10_net_oi": (tx_lt.get("top10_long") or 0) - (tx_lt.get("top10_short") or 0),
        # PCR
        "pcr_oi_all": options_data.get("pcr_oi_all"),
        "pcr_oi_near": None,  # V1: use ALL as proxy
        "pcr_volume_all": None,  # V1: not separately available from this endpoint
        # Foreign options
        "foreign_option_long_value": foreign_opt.get("buy_call_value"),
        "foreign_option_short_value": foreign_opt.get("sell_call_value"),
        "foreign_option_net_value": foreign_opt.get("net_value"),
        "foreign_option_net_oi_value": foreign_opt.get("net_oi_value"),
        # Retail
        "retail_mtx_long": retail_long,
        "retail_mtx_short": retail_short,
        "retail_mtx_net": retail_net,
        "retail_mtx_ratio": round(retail_ratio, 2) if retail_ratio is not None else None,
        # Total OI
        "total_tx_oi": total_oi.get("total_tx_oi"),
        "total_mtx_oi": total_oi.get("total_mtx_oi"),
        "total_tmf_oi": total_oi.get("total_tmf_oi"),
        "tx_equivalent_total_oi": round(tx_eq_total, 1),
        "data_status": "COMPLETE",
    }

    conn.close()
    return result
