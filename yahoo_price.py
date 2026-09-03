"""
yahoo_price.py - 用 Yahoo Finance 抓全市場日線資料
架構改為純 async（httpx.AsyncClient + asyncio.Semaphore）：
  - httpx 的 timeout=Timeout(total=8) 確保整個請求（含慢速回應）在 8s 內完成
  - asyncio.Semaphore 控制並發數（預設 20），不需要 Thread
  - 每支股票：抓資料 → 同時跑所有策略（一次掃描得全部結果）
  - TWSE openapi 預過濾有量股票（大幅減少 Yahoo 請求數）
  - query1 / query2 輪流使用，避免單一端點被封
"""
import asyncio
import datetime
import os
import threading
from itertools import cycle

import httpx
import pandas as pd

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_host_cycle = cycle(["query1", "query2"])
_host_lock  = threading.Lock()


def _next_host() -> str:
    with _host_lock:
        return next(_host_cycle)


_STOCKS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stocks.csv")
_stocks_df = None  # pd.DataFrame


def get_stock_list() -> pd.DataFrame:
    """回傳 stocks.csv，欄位：stock_id, stock_name, type(twse/tpex)"""
    global _stocks_df
    if _stocks_df is None:
        _stocks_df = pd.read_csv(_STOCKS_CSV, dtype=str, encoding="utf-8")
    return _stocks_df


# ── Yahoo Finance async fetch ─────────────────────────────────────────────────

def _parse_yahoo_json(data: dict) -> pd.DataFrame:
    result = (data.get("chart", {}).get("result") or [])
    if not result:
        return pd.DataFrame()
    result = result[0]
    quote  = result["indicators"]["quote"][0]
    timestamps = result.get("timestamp", [])
    df = pd.DataFrame({
        "open":   quote.get("open",   []),
        "high":   quote.get("high",   []),
        "low":    quote.get("low",    []),
        "close":  quote.get("close",  []),
        "volume": quote.get("volume", []),
    }, index=pd.to_datetime(timestamps, unit="s", utc=True).tz_localize(None))
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    df["date"] = df.index.strftime("%Y%m%d")
    return df.reset_index(drop=True)[["date", "open", "high", "low", "close", "volume"]]


async def _fetch_yahoo_async(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    stock_id: str,
    market: str,
    total_timeout: float = 8.0,
    range_: str = "1y",
) -> pd.DataFrame:
    """
    async fetch，Semaphore 控制最大並發數。
    asyncio.wait_for 強制 total_timeout 秒內完成（含慢速回應），
    避免 Yahoo Finance 用慢速傳輸繞過 per-phase timeout。
    range_ 預設 1y（約 248 根）：S1 最低需求 235 根，仍足夠，資料量只有 2y 一半。
    """
    suffix = ".TW" if market == "twse" else ".TWO"
    host   = _next_host()
    url    = f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
    async with sem:
        try:
            r = await asyncio.wait_for(
                client.get(url, params={"interval": "1d", "range": range_}),
                timeout=total_timeout,
            )
            r.raise_for_status()
            return _parse_yahoo_json(r.json())
        except Exception:
            return pd.DataFrame()


async def fetch_prices_for_stocks(stock_list: list) -> dict:
    """
    批次抓多支股票最新收盤價（供觀察清單用）。
    stock_list: [(stock_id, market_type), ...]
    回傳: {stock_id: {'close': float, 'change_pct': float}}
    """
    sem = asyncio.Semaphore(10)
    timeout_cfg = httpx.Timeout(8.0, connect=5.0)
    async with httpx.AsyncClient(
        headers={"User-Agent": _UA, "Accept": "application/json"},
        verify=False,
        timeout=timeout_cfg,
        follow_redirects=True,
    ) as client:
        tasks = [_fetch_yahoo_async(client, sem, sid, mkt) for sid, mkt in stock_list]
        dfs = await asyncio.gather(*tasks, return_exceptions=True)

    result = {}
    for (sid, _), df in zip(stock_list, dfs):
        if isinstance(df, Exception) or df is None or df.empty:
            continue
        try:
            close = float(df.iloc[-1]["close"])
            prev  = float(df.iloc[-2]["close"]) if len(df) >= 2 else close
            pct   = round((close - prev) / prev * 100, 2) if prev > 0 else 0.0
            # 布林軌道分級：(close - MA20) / (2σ) × 10，夾在 [-10, 10]
            bb_score = 0.0
            if len(df) >= 20:
                closes = df['close']
                ma  = closes.rolling(20).mean().iloc[-1]
                std = closes.rolling(20).std().iloc[-1]
                if not pd.isna(ma) and not pd.isna(std) and std > 0:
                    bb_score = round(max(-10.0, min(10.0, (close - float(ma)) / (2 * float(std)) * 10)), 1)
            result[sid] = {"close": round(close, 2), "change_pct": pct, "bb_score": bb_score}
        except Exception:
            pass
    return result


# 同步版（用於觀察清單個股查詢）
def fetch_yahoo(stock_id: str, market: str = "twse") -> pd.DataFrame:
    suffix = ".TW" if market == "twse" else ".TWO"
    host = _next_host()
    url  = f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
    try:
        r = httpx.get(
            url,
            params={"interval": "1d", "range": "2y"},
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=8.0,
            verify=False,
            follow_redirects=True,
        )
        r.raise_for_status()
        return _parse_yahoo_json(r.json())
    except Exception:
        return pd.DataFrame()


# ── TWSE / TPEX 今日有量股票過濾 ─────────────────────────────────────────────

def _get_twse_active_today() -> set[str]:
    """
    從 TWSE openapi 取今日上市有成交量股票 set。
    失敗時回傳空 set（代表不過濾）。
    """
    try:
        r = httpx.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            headers={"User-Agent": _UA},
            timeout=15,
            follow_redirects=True,
        )
        r.raise_for_status()
        data = r.json()
        active = set()
        for item in data:
            sid     = str(item.get("Code", "")).strip()
            vol_str = str(item.get("TradeVolume", "0")).replace(",", "")
            try:
                if int(vol_str) > 0:
                    active.add(sid)
            except Exception:
                pass
        print(f"[SCAN] TWSE今日有量股票：{len(active)} 支")
        return active
    except Exception as e:
        print(f"[SCAN] 無法取得TWSE今日資料：{e}")
        return set()


def _get_tpex_active_today() -> set[str]:
    """
    從 TPEX openapi 取今日上櫃有成交量股票 set。
    失敗時回傳空 set（代表不過濾）。
    """
    _TPEX_ENDPOINTS = [
        "https://www.tpex.org.tw/openapi/v1/tpex_esb_daily_close_quotes",
        "https://www.tpex.org.tw/openapi/v1/tpex_esb_latest_statistics",
    ]
    # 欄位名稱候選（不同 endpoint 欄位名不同）
    _CODE_KEYS   = ["Code", "code", "SecuritiesCompanyCode", "StockCode", "symbol"]
    _VOL_KEYS    = ["TradeVolume", "Volume", "TradingShares", "volume", "TradeValue"]

    for url in _TPEX_ENDPOINTS:
        try:
            r = httpx.get(
                url,
                headers={"User-Agent": _UA, "Accept": "application/json"},
                timeout=15,
                verify=False,
                follow_redirects=True,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if not data or not isinstance(data, list):
                continue
            sample   = data[0]
            code_key = next((k for k in _CODE_KEYS if k in sample), None)
            vol_key  = next((k for k in _VOL_KEYS  if k in sample), None)
            if not code_key:
                continue
            active = set()
            for item in data:
                sid = str(item.get(code_key, "")).strip()
                if not sid:
                    continue
                if vol_key:
                    vol_str = str(item.get(vol_key, "0")).replace(",", "")
                    try:
                        if int(float(vol_str)) <= 0:
                            continue
                    except Exception:
                        pass
                active.add(sid)
            if active:
                print(f"[SCAN] TPEX今日有量股票：{len(active)} 支（via {url.split('/')[-1]}）")
                return active
        except Exception as e:
            print(f"[SCAN] TPEX openapi 嘗試失敗 {url}: {e}")
            continue

    print(f"[SCAN] 無法取得TPEX今日資料，上櫃股票全包")
    return set()


# ── 全市場掃描 ────────────────────────────────────────────────────────────────

STRATEGY_KEYS = ["S1", "S1_SHORT", "S1_2", "S2", "S5", "S17A", "S17B", "S10"]

_scan_status: dict = {
    "running":     False,
    "progress":    0,
    "total":       0,
    "yahoo_ok":    0,   # 成功取得 Yahoo 資料的股票數
    "yahoo_fail":  0,   # Yahoo 回傳空/失敗的股票數
    "results":     {},
    "finished_at": None,
    "error":       None,
}


def get_scan_status() -> dict:
    counts = {k: len(v) for k, v in _scan_status["results"].items()} if _scan_status["results"] else {}
    return {
        "running":     _scan_status["running"],
        "progress":    _scan_status["progress"],
        "total":       _scan_status["total"],
        "yahoo_ok":    _scan_status["yahoo_ok"],
        "yahoo_fail":  _scan_status["yahoo_fail"],
        "counts":      counts,
        "finished_at": _scan_status["finished_at"],
        "error":       _scan_status["error"],
    }


def get_scan_results() -> dict:
    return _scan_status["results"]


async def run_market_scan(concurrency: int = 50):
    """
    背景執行全市場策略掃描（上市 + 上櫃，全部 stocks.csv 股票）。
    - 不做今日有量過濾，直接掃全部，確保不遺漏
    - Semaphore(50) 控制並發，range=1y 資料量只有 2y 一半
    """
    from scanner import scan_one_stock

    _scan_status["running"]     = True
    _scan_status["progress"]    = 0
    _scan_status["yahoo_ok"]    = 0
    _scan_status["yahoo_fail"]  = 0
    _scan_status["results"]     = {}
    _scan_status["error"]       = None
    _scan_status["finished_at"] = None

    try:
        stocks = get_stock_list()
        names  = dict(zip(stocks["stock_id"], stocks["stock_name"]))
        tasks  = list(stocks[["stock_id", "type"]].itertuples(index=False, name=None))
        print(f"[SCAN] 全市場掃描：共 {len(tasks)} 支")

        _scan_status["total"] = len(tasks)

        all_results = {k: [] for k in STRATEGY_KEYS}
        sem = asyncio.Semaphore(concurrency)

        timeout_cfg = httpx.Timeout(8.0, connect=5.0)
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA, "Accept": "application/json"},
            verify=False,
            timeout=timeout_cfg,
            follow_redirects=True,
        ) as client:

            async def _fetch_scan(sid, mkt):
                df = await _fetch_yahoo_async(client, sem, sid, mkt, range_="2y")
                _scan_status["progress"] += 1
                if df.empty or len(df) < 5:
                    _scan_status["yahoo_fail"] += 1
                    return {}
                _scan_status["yahoo_ok"] += 1
                return scan_one_stock(df, sid, names.get(sid, ""))

            coros   = [_fetch_scan(sid, mkt) for sid, mkt in tasks]
            results = await asyncio.gather(*coros, return_exceptions=True)

        for out in results:
            if isinstance(out, dict):
                for strat, result in out.items():
                    if result is not None:
                        all_results[strat].append(result)

        _scan_status["results"] = all_results

    except Exception as e:
        _scan_status["error"] = str(e)
    finally:
        _scan_status["running"]     = False
        _scan_status["finished_at"] = datetime.datetime.now().isoformat()
        total_hits = sum(len(v) for v in _scan_status["results"].values())
        print(f"[SCAN] 完成：{total_hits} 支符合，共掃 {_scan_status['total']} 支")
