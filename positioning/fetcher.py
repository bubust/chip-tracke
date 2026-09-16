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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

# TAIFEX POST 下載端點需要額外的 Referer / Content-Type
TAIFEX_HEADERS = {
    **HEADERS,
    "Referer": "https://www.taifex.com.tw/cht/3/futContractsDate",
    "Origin": "https://www.taifex.com.tw",
    "Content-Type": "application/x-www-form-urlencoded",
}

_FM_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9"
    ".eyJ1c2VyX2lkIjoiYnVidXN0IiwiZW1haWwiOiJidWJ1c3RAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0"
    ".LcLL157_bH6YbABE7JOlg0cAEwwzOV6GfJA6uK2cvIA"
)

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
    """
    回傳最近一個有 TAIFEX 盤後資料的交易日（格式 YYYY/MM/DD）。
    TAIFEX 盤後資料約 15:30~16:00 發布；台灣時間 16:00 前一律用前一交易日。
    """
    from datetime import datetime, timezone
    tw_now = datetime.now(timezone(timedelta(hours=8)))
    d = tw_now.date()
    if tw_now.hour < 16:          # 16:00 前，今天資料未發布
        d -= timedelta(days=1)
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

def _is_html(text: str) -> bool:
    """偵測 TAIFEX 回傳的是 HTML（表示資料未發布或 IP 被擋）而非 CSV。"""
    t = text.lstrip()
    return t.startswith("<!") or t.startswith("<html") or t.startswith("<HTML")


async def _taifex_post_csv(client: httpx.AsyncClient, url: str, payload: dict) -> str:
    """
    TAIFEX CSV 下載：先 GET 上頁建立 session cookie，再 POST 下載。
    若收到 HTML（非 CSV）回傳空字串。
    """
    # 先 GET 頁面，取得 session cookie
    page_url = url.replace("Down", "")   # e.g. futContractsDate
    try:
        await client.get(page_url, timeout=10)
    except Exception:
        pass
    r = await client.post(url, data=payload)
    text = r.content.decode("ms950", errors="replace")
    if _is_html(text):
        log.warning(f"[positioning] {url} 回傳 HTML（非 CSV），資料未發布或 IP 被擋")
        return ""
    return text


async def _finmind_futures_inst(dt: date) -> dict:
    """
    FinMind 備援：TaiwanFuturesInstitutionalInvestors（TX/MTX）
    Returns rows_out 格式與 fetch_taifex_inst_futures 相同。
    """
    rows_out: dict = {}
    dt_str = dt.strftime("%Y-%m-%d")
    # contract_map: FinMind name → contract key, identity keyword
    # FinMind dataset: data_id = contract code (TX/MTX/TMF)
    for data_id, contract_key in [("TX", "TX"), ("MTX", "MTX"), ("TMF", "TMF")]:
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
                r = await client.get(
                    "https://api.finmindtrade.com/api/v4/data",
                    params={
                        "dataset": "TaiwanFuturesInstitutionalInvestors",
                        "data_id": data_id,
                        "start_date": dt_str,
                        "end_date": dt_str,
                        "token": _FM_TOKEN,
                    },
                )
                rows = r.json().get("data", [])
                for row in rows:
                    name = row.get("name", "")   # 外資及陸資 / 投信 / 自營商
                    rows_out[(name, contract_key)] = {
                        "trade_long":  _int(str(row.get("buy_open_interest_balance", 0) or 0)),
                        "trade_short": _int(str(row.get("sell_open_interest_balance", 0) or 0)),
                        "trade_net":   _int(str(row.get("net_open_interest_balance", 0) or 0)),
                        "oi_long":     _int(str(row.get("buy_open_interest_balance", 0) or 0)),
                        "oi_short":    _int(str(row.get("sell_open_interest_balance", 0) or 0)),
                        "oi_net":      _int(str(row.get("net_open_interest_balance", 0) or 0)),
                    }
        except Exception as e:
            log.warning(f"[positioning] FinMind {data_id} inst futures 失敗: {e}")
    return rows_out


async def fetch_taifex_inst_futures(target_date: date | None = None) -> dict:
    """
    Download 三大法人期貨未平倉 from futContractsDateDown.
    Returns raw rows keyed by (identity, contract).
    Falls back to FinMind if TAIFEX returns HTML.
    """
    td = _to_trading_day(target_date) if target_date else None
    dt_str = _fmt(td) if td else _last_trading_day_str()
    if not td:
        # 反推 date 物件供 FinMind 備援
        from datetime import datetime as _dt, timezone as _tz
        td_dt = _dt.now(_tz(timedelta(hours=8)))
        td = td_dt.date()
        if td_dt.hour < 16:
            td -= timedelta(days=1)
        while td.weekday() >= 5:
            td -= timedelta(days=1)

    url = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
    payload = {"queryStartDate": dt_str, "queryEndDate": dt_str}

    rows_out = {}
    async with httpx.AsyncClient(headers=TAIFEX_HEADERS, timeout=30, follow_redirects=True) as client:
        text = await _taifex_post_csv(client, url, payload)

    if text:
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            # format: date[0], contract[1], identity[2], trade_long[3], trade_long_val[4],
            #         trade_short[5], trade_short_val[6], trade_net[7], trade_net_val[8],
            #         oi_long[9], oi_long_val[10], oi_short[11], oi_short_val[12], oi_net[13]
            if len(row) < 14:
                continue
            contract = row[1].strip()   # 商品名稱
            identity = row[2].strip()   # 身份別
            if not identity or not contract:
                continue
            key = None
            if "臺股期貨" in contract:
                key = (identity, "TX")
            elif "小型臺指" in contract:
                key = (identity, "MTX")
            elif "永續" in contract:
                key = (identity, "TMF")
            else:
                continue
            rows_out[key] = {
                "trade_long": _int(row[3]),
                "trade_short": _int(row[5]),
                "trade_net": _int(row[7]),
                "oi_long": _int(row[9]),
                "oi_short": _int(row[11]),
                "oi_net": _int(row[13]),
            }

    # FinMind 備援
    if not rows_out:
        log.info("[positioning] TAIFEX 期貨法人 → 切換 FinMind 備援")
        rows_out = await _finmind_futures_inst(td)

    return rows_out, dt_str


# ── TAIFEX: large trader futures ──────────────────────────────────────────────

async def fetch_taifex_large_trader(target_date: date | None = None) -> dict:
    """
    Download 期貨大額交易人未平倉 from largeTraderFutDown.
    Returns top5/top10 long/short and market total for TX-equivalent contracts.
    Falls back to FinMind if TAIFEX returns HTML.
    """
    dt_str = _fmt(_to_trading_day(target_date)) if target_date else _last_trading_day_str()
    url = "https://www.taifex.com.tw/cht/3/largeTraderFutDown"
    payload = {"queryStartDate": dt_str, "queryEndDate": dt_str}

    result = {}
    async with httpx.AsyncClient(headers=TAIFEX_HEADERS, timeout=30, follow_redirects=True) as client:
        text = await _taifex_post_csv(client, url, payload)

    if not text:
        # FinMind 備援: TaiwanFuturesLargeTrader
        try:
            td_fm = dt_str.replace("/", "-")
            async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
                r = await client.get(
                    "https://api.finmindtrade.com/api/v4/data",
                    params={
                        "dataset": "TaiwanFuturesLargeTrader",
                        "data_id": "TX",
                        "start_date": td_fm,
                        "end_date": td_fm,
                        "token": _FM_TOKEN,
                    },
                )
                for row in r.json().get("data", []):
                    contract_id = row.get("data_id", "TX")
                    result[contract_id] = {
                        "top5_long":  _int(str(row.get("top_5_oi_buy", 0) or 0)),
                        "top5_short": _int(str(row.get("top_5_oi_sell", 0) or 0)),
                        "top10_long":  _int(str(row.get("top_10_oi_buy", 0) or 0)),
                        "top10_short": _int(str(row.get("top_10_oi_sell", 0) or 0)),
                        "market_long":  _int(str(row.get("market_oi_buy", 0) or 0)),
                        "market_short": _int(str(row.get("market_oi_sell", 0) or 0)),
                    }
            log.info(f"[positioning] FinMind LargeTrader 備援: {len(result)} contracts")
        except Exception as e:
            log.warning(f"[positioning] FinMind LargeTrader 備援失敗: {e}")
        return result, dt_str

    rows = list(csv.reader(io.StringIO(text)))

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

        # Only use "所有序列" / combined row
        is_all = (not month) or any(kw in month for kw in ("所有", "全部", "全月"))
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
    Same 15-col CSV format as futContractsDateDown — no call/put split.
    商品名稱 is "臺指選擇權" (combined). Only extracts 外資 net OI.
    """
    dt_str = _fmt(_to_trading_day(target_date)) if target_date else _last_trading_day_str()
    url = "https://www.taifex.com.tw/cht/3/optContractsDateDown"
    payload = {"queryStartDate": dt_str, "queryEndDate": dt_str}

    async with httpx.AsyncClient(headers=TAIFEX_HEADERS, timeout=30, follow_redirects=True) as client:
        text = await _taifex_post_csv(client, url, payload)

    if not text:
        return {"foreign": {"oi_long": None, "oi_short": None, "oi_net": None}}, dt_str

    reader = csv.reader(io.StringIO(text))
    # Same 15-col format: date[0], contract[1], identity[2], trade_long[3], trade_long_val[4],
    #   trade_short[5], trade_short_val[6], trade_net[7], trade_net_val[8],
    #   oi_long[9], oi_long_val[10], oi_short[11], oi_short_val[12], oi_net[13]
    foreign_oi_long = None
    foreign_oi_short = None
    foreign_oi_net = None

    for row in reader:
        if len(row) < 14:
            continue
        contract = row[1].strip()
        identity = row[2].strip()
        if "臺指選擇權" not in contract and "TXO" not in contract:
            continue
        if "外資" not in identity:
            continue
        foreign_oi_long = _int(row[9])
        foreign_oi_short = _int(row[11])
        foreign_oi_net = _int(row[13])

    return {
        "foreign": {
            "oi_long": foreign_oi_long,
            "oi_short": foreign_oi_short,
            "oi_net": foreign_oi_net,
        },
    }, dt_str


async def fetch_taifex_pcr(target_date: date | None = None) -> dict:
    """
    Fetch PCR (Put/Call Ratio) from TAIFEX pcRatioDown endpoint.
    Returns pcr_oi_all (%), call_oi_all, put_oi_all.
    """
    dt_str = _fmt(_to_trading_day(target_date)) if target_date else _last_trading_day_str()
    url = "https://www.taifex.com.tw/cht/3/pcRatioDown"
    payload = {"queryStartDate": dt_str, "queryEndDate": dt_str}

    async with httpx.AsyncClient(headers=TAIFEX_HEADERS, timeout=30, follow_redirects=True) as client:
        text = await _taifex_post_csv(client, url, payload)

    if text:
        reader = csv.reader(io.StringIO(text))
        # pcRatioDown columns (typical TAIFEX format):
        # date[0], put_vol[1], call_vol[2], pcr_vol%[3], put_oi[4], call_oi[5], pcr_oi%[6]
        for row in reader:
            if len(row) < 7:
                continue
            try:
                put_oi = _int(row[4])
                call_oi = _int(row[5])
                pcr_oi = _float(row[6])
                if pcr_oi is not None and call_oi:
                    return {
                        "pcr_oi_all": pcr_oi,
                        "call_oi_all": call_oi,
                        "put_oi_all": put_oi,
                    }
            except Exception:
                continue

    # FinMind 備援: TaiwanPutCallRatio
    try:
        td_fm = dt_str.replace("/", "-")
        async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
            r = await client.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset": "TaiwanPutCallRatio",
                    "start_date": td_fm,
                    "end_date": td_fm,
                    "token": _FM_TOKEN,
                },
            )
            rows = r.json().get("data", [])
            if rows:
                row = rows[-1]
                return {
                    "pcr_oi_all": _float(str(row.get("put_call_ratio", "") or "")),
                    "call_oi_all": _int(str(row.get("call_open_interest", 0) or 0)),
                    "put_oi_all":  _int(str(row.get("put_open_interest", 0) or 0)),
                }
    except Exception as e:
        log.warning(f"[positioning] FinMind PCR 備援失敗: {e}")

    return {"pcr_oi_all": None, "call_oi_all": None, "put_oi_all": None}


# ── TWSE: institutional spot (T86) ───────────────────────────────────────────

async def fetch_twse_institutional_spot(target_date: date | None = None) -> dict:
    """
    Fetch 三大法人現貨 from TWSE T86.
    Returns foreign/trust/dealer net in 億元.
    """
    td = target_date or date.today()
    while td.weekday() >= 5:
        td -= timedelta(days=1)
    dt_str = td.strftime("%Y%m%d")

    urls = [
        "https://openapi.twse.com.tw/v1/exchangeReport/T86",
        f"https://www.twse.com.tw/rwd/zh/fund/T86?date={dt_str}&selectType=ALL&response=json",
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

    def _parse_bn(val):
        """Parse value string to 億元 (raw is 千元 from TWSE)."""
        try:
            return round(float(str(val).replace(",", "")) / 100000, 2)
        except Exception:
            return None

    def _get(d, *keys):
        for k in keys:
            if k in d:
                return d[k]
        return None

    if data:
        foreign = _parse_bn(_get(data,
            "foreignDealersExcluded", "外陸資買賣超股數(不含外資自營商)",
            "foreignNetBuySell", "外資買賣超"))
        trust = _parse_bn(_get(data,
            "sitc", "投信買賣超股數", "trustNetBuySell", "投信買賣超"))
        dealer = _parse_bn(_get(data,
            "dealersTotal", "自營商買賣超股數(合計)", "dealerNetBuySell", "自營商買賣超"))
        if any(v is not None for v in [foreign, trust, dealer]):
            return {
                "foreign_cash_net": foreign,
                "trust_cash_net": trust,
                "dealer_cash_net": dealer,
            }

    # FinMind 備援: TaiwanStockInstitutionalInvestors (市場全體)
    try:
        td_fm = td.strftime("%Y-%m-%d")
        async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
            r = await client.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset": "TaiwanStockTotalReturnIndex",   # fallback: 嘗試市場整體法人
                    "start_date": td_fm,
                    "end_date": td_fm,
                    "token": _FM_TOKEN,
                },
            )
    except Exception:
        pass

    # If all else fails, try FinMind TaiwanStockInstitutionalInvestors (總計)
    try:
        td_fm = td.strftime("%Y-%m-%d")
        async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
            r = await client.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset": "TaiwanStockInstitutionalInvestors",
                    "data_id": "市場",
                    "start_date": td_fm,
                    "end_date": td_fm,
                    "token": _FM_TOKEN,
                },
            )
            rows = r.json().get("data", [])
            foreign_bn = trust_bn = dealer_bn = None
            for row in rows:
                name = row.get("name", "")
                net = _float(str(row.get("buy", 0) or 0)) or 0
                net -= _float(str(row.get("sell", 0) or 0)) or 0
                net_bn = round(net / 100000, 2)   # 千元 → 億元
                if "外資" in name:
                    foreign_bn = net_bn
                elif "投信" in name:
                    trust_bn = net_bn
                elif "自營" in name:
                    dealer_bn = net_bn
            if any(v is not None for v in [foreign_bn, trust_bn, dealer_bn]):
                return {
                    "foreign_cash_net": foreign_bn,
                    "trust_cash_net": trust_bn,
                    "dealer_cash_net": dealer_bn,
                }
    except Exception as e:
        log.warning(f"[positioning] FinMind T86 備援失敗: {e}")

    return {}


# ── TAIFEX: total OI per contract ─────────────────────────────────────────────

def _derive_total_oi_from_large_trader(large_trader: dict) -> dict:
    """
    Derive total market OI from large_trader data (market_long = total long OI).
    largeTraderFutDown 市場未平倉口數 = the only reliable source of total market OI.
    """
    tx = large_trader.get("TX", {})
    mtx = large_trader.get("MTX", {})
    tmf = large_trader.get("TMF", {})
    return {
        "total_tx_oi": tx.get("market_long"),
        "total_mtx_oi": mtx.get("market_long"),
        "total_tmf_oi": tmf.get("market_long"),
    }


# ── TAIEX close price ─────────────────────────────────────────────────────────

async def fetch_taiex_close(target_date: date | None = None) -> float | None:
    """Fetch TAIEX (加權指數) closing price. Tries 4 sources in order."""
    td = target_date or date.today()
    while td.weekday() >= 5:
        td -= timedelta(days=1)
    dt_str = td.strftime("%Y%m%d")

    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        # 1. TWSE openapi
        try:
            r = await client.get("https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX?type=TW")
            if r.status_code == 200:
                for item in r.json():
                    idx_name = item.get("Index", "") or item.get("指數名稱", "")
                    if "加權" in idx_name or "發行量" in idx_name:
                        raw = item.get("ClosingIndex") or item.get("收盤指數") or item.get("收盤")
                        if raw:
                            v = float(str(raw).replace(",", ""))
                            if v > 1000:
                                return v
        except Exception as e:
            log.warning(f"[positioning] TAIEX openapi failed: {e}")

        # 2. Yahoo Finance query1 / query2
        for yhost in ("query1", "query2"):
            try:
                r = await client.get(
                    f"https://{yhost}.finance.yahoo.com/v8/finance/chart/%5ETWII",
                    params={"interval": "1d", "range": "5d"},
                    headers={**HEADERS, "User-Agent": "Mozilla/5.0"},
                )
                if r.status_code == 200:
                    result = (r.json().get("chart", {}).get("result") or [])
                    if result:
                        closes = result[0]["indicators"]["quote"][0].get("close", [])
                        closes = [c for c in closes if c is not None]
                        if closes:
                            return round(float(closes[-1]), 2)
            except Exception as e:
                log.warning(f"[positioning] TAIEX Yahoo {yhost} failed: {e}")

        # 3. TWSE afterTrading MI_INDEX (rwd endpoint, same as regime fetcher uses)
        try:
            r = await client.get(
                "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                params={"date": dt_str, "type": "ALLBUT0999", "response": "json"},
                headers={**HEADERS, "Referer": "https://www.twse.com.tw/"},
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("stat") == "OK":
                    for table in data.get("tables", []):
                        for row in table.get("data", []):
                            if len(row) < 2:
                                continue
                            label = str(row[0]).strip()
                            if "加權" in label or "發行量" in label:
                                for col in row[1:]:
                                    val_s = str(col).replace(",", "").strip()
                                    try:
                                        v = float(val_s)
                                        if v > 1000:
                                            return v
                                    except Exception:
                                        pass
        except Exception as e:
            log.warning(f"[positioning] TAIEX TWSE afterTrading failed: {e}")

        # 4. FinMind TaiwanStockMarketInfo (TAIEX closing)
        try:
            r = await client.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset": "TaiwanStockMarketInfo",
                    "start_date": td.strftime("%Y-%m-%d"),
                    "token": _FM_TOKEN,
                },
            )
            if r.status_code == 200:
                rows = r.json().get("data", [])
                for row in reversed(rows):
                    if "TAIEX" in str(row.get("type", "")) or "加權" in str(row.get("type", "")):
                        v = float(row.get("price", 0) or 0)
                        if v > 1000:
                            return round(v, 2)
        except Exception as e:
            log.warning(f"[positioning] TAIEX FinMind failed: {e}")

    log.error("[positioning] fetch_taiex_close: 所有來源均失敗")
    return None


# ── Orchestrator ──────────────────────────────────────────────────────────────

async def fetch_all(target_date: date | None = None) -> dict:
    """
    Fetch all positioning data and store raw rows in DB.
    Returns a consolidated dict ready for calculator.
    """
    from .db import get_conn
    from datetime import datetime, timezone
    conn = get_conn()
    if target_date:
        td = target_date
    else:
        # 16:00 前 TAIFEX 盤後資料未發布，預設用前一交易日
        tw_now = datetime.now(timezone(timedelta(hours=8)))
        td = tw_now.date()
        if tw_now.hour < 16:
            td -= timedelta(days=1)
    # Adjust to last weekday (TAIFEX has no data on weekends)
    while td.weekday() >= 5:
        td -= timedelta(days=1)
    td_str = td.strftime("%Y-%m-%d")

    # Parallel fetch
    (inst_fut, dt_str1), (large_trader, dt_str2), (options_data, dt_str3), \
    spot_data, pcr_data, taiex_close = await asyncio.gather(
        fetch_taifex_inst_futures(target_date),
        fetch_taifex_large_trader(target_date),
        fetch_taifex_inst_options(target_date),
        fetch_twse_institutional_spot(target_date),
        fetch_taifex_pcr(target_date),
        fetch_taiex_close(target_date),
    )

    total_oi = _derive_total_oi_from_large_trader(large_trader)

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
              pcr_data.get("call_oi_all"), pcr_data.get("put_oi_all")))
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

    # ── 成交量（億）：嘗試從 FinMind TaiwanStockPrice Y9999 取得 ──
    market_volume_bn = None
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=10) as _vc:
            _vr = await _vc.get("https://api.finmindtrade.com/api/v4/data",
                params={"dataset": "TaiwanStockPrice", "data_id": "Y9999",
                        "start_date": td_str, "end_date": td_str, "token": _FM_TOKEN})
            for _vrow in _vr.json().get("data", []):
                vol = _vrow.get("Trading_Volume") or _vrow.get("trading_volume")
                if vol:
                    market_volume_bn = round(float(vol) / 1e8, 1)
                    break
    except Exception:
        pass

    result = {
        "observation_date": td_str,
        # Market index
        "taiex_close": taiex_close,
        "market_volume_bn": market_volume_bn,
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
        # PCR (from pcRatioDown)
        "pcr_oi_all": pcr_data.get("pcr_oi_all"),
        "pcr_oi_near": None,
        "pcr_volume_all": None,
        # Foreign options net OI (from optContractsDateDown)
        "foreign_option_long_value": foreign_opt.get("oi_long"),
        "foreign_option_short_value": foreign_opt.get("oi_short"),
        "foreign_option_net_value": foreign_opt.get("oi_net"),
        "foreign_option_net_oi_value": foreign_opt.get("oi_net"),
        # Retail
        "retail_mtx_long": retail_long,
        "retail_mtx_short": retail_short,
        "retail_mtx_net": retail_net,
        "retail_mtx_ratio": round(retail_ratio, 2) if retail_ratio is not None else None,
        # Total OI (from large_trader market_long)
        "total_tx_oi": total_oi.get("total_tx_oi"),
        "total_mtx_oi": total_oi.get("total_mtx_oi"),
        "total_tmf_oi": total_oi.get("total_tmf_oi"),
        "tx_equivalent_total_oi": round(tx_eq_total, 1),
        "data_status": "COMPLETE",
    }

    conn.close()
    return result
