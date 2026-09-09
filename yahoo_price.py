"""
yahoo_price.py - 用 Yahoo Finance 抓全市場日線資料
架構：純 async（httpx.AsyncClient + asyncio.Semaphore）
  - Semaphore(100) 控制並發，range=6mo 下載量減半
  - scan_one_stock 跑在 ThreadPoolExecutor(24) 釋放 event loop
  - 掃全部 stocks.csv 股票（不做有量過濾，避免漏掉低量漲停股）
  - query1 / query2 輪流使用，避免單一端點被封
"""
import asyncio
import datetime
import os
import threading
import time
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
    meta   = result.get("meta", {})
    quote  = result["indicators"]["quote"][0]
    timestamps = result.get("timestamp", [])
    # Yahoo timestamp 是 UTC，台股是 UTC+8；統一換成台灣時間後再取日期，
    # 避免 00:00 CST = 前一天 16:00 UTC 造成 date 少一天的問題。
    _TW_OFFSET = pd.Timedelta(hours=8)
    tw_idx = (pd.to_datetime(timestamps, unit="s", utc=True) + _TW_OFFSET).tz_localize(None)
    df = pd.DataFrame({
        "open":   quote.get("open",   []),
        "high":   quote.get("high",   []),
        "low":    quote.get("low",    []),
        "close":  quote.get("close",  []),
        "volume": quote.get("volume", []),
    }, index=tw_idx)
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    df["date"] = df.index.strftime("%Y%m%d")
    df = df.reset_index(drop=True)[["date", "open", "high", "low", "close", "volume"]]

    # 午夜換日補丁：Yahoo 換日時最後一行 close 會暫時變 None，
    # 用 meta.regularMarketPrice + regularMarketTime 補回最新收盤。
    # regularMarketTime 也換成台灣時間，才能與 df["date"] 正確比對。
    try:
        rmp  = meta.get("regularMarketPrice")
        rmt  = meta.get("regularMarketTime")
        rmv  = meta.get("regularMarketVolume") or 0
        if rmp and rmt and float(rmp) > 0:
            import datetime as _dt
            last_dt   = _dt.datetime.utcfromtimestamp(int(rmt)) + _dt.timedelta(hours=8)
            last_date = last_dt.strftime("%Y%m%d")
            # 只有在 df 裡沒有這天資料時才補（日期統一台灣時間，比對才準）
            if df.empty or df.iloc[-1]["date"] != last_date:
                try:
                    vol = int(rmv)
                except Exception:
                    vol = 0
                # 用 meta 的真實 open/high/low，避免 open==close 造成策略誤判
                rmo = float(meta.get("regularMarketOpen") or rmp)
                rmh = float(meta.get("regularMarketDayHigh") or rmp)
                rml = float(meta.get("regularMarketDayLow") or rmp)
                new_row = pd.DataFrame([{
                    "date": last_date, "open": rmo, "high": rmh,
                    "low": rml, "close": float(rmp), "volume": vol,
                }])
                df = pd.concat([df, new_row], ignore_index=True)
    except Exception:
        pass

    return df


async def _fetch_yahoo_async(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    stock_id: str,
    market: str,
    total_timeout: float = 8.0,  # 保留參數相容性，實際由 client timeout 控制
    range_: str = "1y",
) -> pd.DataFrame:
    """
    async fetch，Semaphore 控制最大並發數。
    用 period1/period2 取代 range，強制 Yahoo 回傳到當下最新資料（避免快取延遲）。
    timeout 由 httpx.AsyncClient 自帶機制控制（不用 asyncio.wait_for，避免衝突）。
    """
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]
    # 換算 range 字串為天數，再換成 period1/period2（period2=now 強制最新）
    _range_days = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
                   "1y": 365, "2y": 730, "5y": 1825}
    days = _range_days.get(range_, 365)
    now  = int(time.time())
    p1   = now - days * 86400
    params = {"interval": "1d", "period1": p1, "period2": now}
    async with sem:
        for suffix in suffixes:
            host = _next_host()
            url  = f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
            try:
                r = await client.get(url, params=params)
                r.raise_for_status()
                df = _parse_yahoo_json(r.json())
                if not df.empty and len(df) >= 5:
                    return df
            except Exception:
                pass
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
                std = closes.rolling(20).std(ddof=0).iloc[-1]
                if not pd.isna(ma) and not pd.isna(std) and std > 0:
                    bb_score = round((close - float(ma)) / (2 * float(std)) * 10, 1)
            # 自動階段判斷
            try:
                from scanner import classify_stage
                stage = classify_stage(df)
            except Exception:
                stage = {"code": "unknown", "label": "—", "color": "muted", "desc": ""}
            result[sid] = {"close": round(close, 2), "change_pct": pct,
                           "bb_score": bb_score, "stage": stage}
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


# ── 全市場掃描 ────────────────────────────────────────────────────────────────

STRATEGY_KEYS = ["S1", "S1_SHORT", "S1_2", "S2", "S5", "S17A", "S17B", "S10", "CHIP",
                 "S_PB", "S_FBD", "S_RES", "S_KD", "S_VOLX", "S_VOLX_SHORT"]

_scan_status: dict = {
    "running":      False,
    "progress":     0,
    "total":        0,
    "yahoo_ok":     0,   # 成功取得 Yahoo 資料的股票數
    "yahoo_fail":   0,   # Yahoo 回傳空/失敗的股票數
    "failed_stocks": [],  # 失敗的股票代號清單
    "phase":        "",  # 目前階段："yahoo" | "tdcc" | "done"
    "tdcc_total":   0,   # TDCC 需爬股票數
    "results":      {},
    "finished_at":  None,
    "error":        None,
}


def get_scan_status() -> dict:
    counts = {k: len(v) for k, v in _scan_status["results"].items()} if _scan_status["results"] else {}
    return {
        "running":       _scan_status["running"],
        "progress":      _scan_status["progress"],
        "total":         _scan_status["total"],
        "yahoo_ok":      _scan_status["yahoo_ok"],
        "yahoo_fail":    _scan_status["yahoo_fail"],
        "failed_stocks": _scan_status["failed_stocks"],
        "phase":         _scan_status.get("phase", ""),
        "tdcc_total":    _scan_status.get("tdcc_total", 0),
        "counts":        counts,
        "finished_at":   _scan_status["finished_at"],
        "error":         _scan_status["error"],
    }


def get_scan_results() -> dict:
    return _scan_status["results"]


async def run_market_scan(concurrency: int = 100, strategy_params: dict = None):
    """
    背景執行全市場策略掃描（上市 + 上櫃，全部 stocks.csv 股票）。
    - 掃全部股票，不做有量過濾（避免漏掉低量漲停或上櫃股票）
    - Semaphore(100) 控制並發；range=1y（S1 大 MACD 需 235 天）
    - scan_one_stock 跑在 ThreadPoolExecutor(24)，不阻塞 event loop
    - strategy_params: {strategy_key: {param_key: value}} 各策略自訂參數
    """
    import concurrent.futures
    from scanner import scan_one_stock, screen_chip
    from tdcc_chip import get_tdcc_data
    _strategy_params = strategy_params or {}

    _scan_status["running"]       = True
    _scan_status["progress"]      = 0
    _scan_status["phase"]         = "yahoo"
    _scan_status["tdcc_total"]    = 0
    _scan_status["yahoo_ok"]      = 0
    _scan_status["yahoo_fail"]    = 0
    _scan_status["failed_stocks"] = []
    _scan_status["results"]       = {}
    _scan_status["error"]         = None
    _scan_status["finished_at"]   = None

    try:
        stocks = get_stock_list()
        names  = dict(zip(stocks["stock_id"], stocks["stock_name"]))
        tasks  = list(stocks[["stock_id", "type"]].itertuples(index=False, name=None))

        print(f"[SCAN] 全市場掃描：共 {len(tasks)} 支（無量過濾）")
        _scan_status["total"] = len(tasks)

        all_results  = {k: [] for k in STRATEGY_KEYS}
        all_prices   = {}   # 收集所有價格資料，供 CHIP 使用
        sem = asyncio.Semaphore(concurrency)
        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=24)

        timeout_cfg = httpx.Timeout(connect=3.0, read=8.0, write=3.0, pool=2.0)

        async with httpx.AsyncClient(
            headers={"User-Agent": _UA, "Accept": "application/json"},
            verify=False,
            timeout=timeout_cfg,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=120, max_keepalive_connections=80),
        ) as client:

            async def _fetch_scan(sid, mkt):
                # range=2y：S1 大MACD(108,216,18) 的 216-period EWM 需約 430 天才收斂
                # 1y≈252 天不夠，2y≈504 天可讓 EWM 誤差降至 <0.1%
                df = await _fetch_yahoo_async(client, sem, sid, mkt, range_="2y")
                _scan_status["progress"] += 1
                if df.empty or len(df) < 5:
                    _scan_status["yahoo_fail"] += 1
                    _scan_status["failed_stocks"].append(sid)
                    return {}
                _scan_status["yahoo_ok"] += 1
                all_prices[sid] = df
                # CPU-bound pandas 運算放到 thread pool，釋放 event loop
                import functools
                return await loop.run_in_executor(
                    executor,
                    functools.partial(scan_one_stock, df, sid, names.get(sid, ""),
                                      strategy_params=_strategy_params)
                )

            coros   = [_fetch_scan(sid, mkt) for sid, mkt in tasks]
            results = await asyncio.gather(*coros, return_exceptions=True)

        executor.shutdown(wait=False)

        for out in results:
            if isinstance(out, dict):
                for strat, result in out.items():
                    if result is not None:
                        all_results[strat].append(result)

        # CHIP：MA 預篩 → TDCC 爬蟲（只爬通過的股票）→ screen_chip
        from tdcc_chip import refresh_for_stocks, get_tdcc_data

        ma_candidates = []
        for sid, df in all_prices.items():
            if len(df) < 20:
                continue
            if float(df.iloc[-1]['close']) <= 10:
                continue
            closes = df['close']
            ma5  = closes.rolling(5).mean().iloc[-1]
            ma10 = closes.rolling(10).mean().iloc[-1]
            ma20 = closes.rolling(20).mean().iloc[-1]
            if pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20):
                continue
            if float(ma5) > float(ma10) > float(ma20):
                ma_candidates.append(sid)

        # 最多爬 400 支（避免 TDCC 爬太久），按收盤價降序優先
        if len(ma_candidates) > 400:
            ma_candidates.sort(key=lambda s: float(all_prices[s].iloc[-1]['close']), reverse=True)
            ma_candidates = ma_candidates[:400]
        _scan_status["phase"]      = "tdcc"
        _scan_status["tdcc_total"] = len(ma_candidates)
        print(f"[SCAN] CHIP MA預篩：{len(ma_candidates)} 支符合，開始爬 TDCC...")
        if ma_candidates:
            await refresh_for_stocks(ma_candidates)
            tdcc_data = get_tdcc_data()
            if tdcc_data and all_prices:
                print(f"[SCAN] CHIP 掃描：TDCC {len(tdcc_data)} 支，價格 {len(all_prices)} 支")
                chip_names = {sid: names.get(sid, '') for sid in all_prices}
                stock_info = {sid: {'name': chip_names[sid]} for sid in all_prices}
                all_results["CHIP"] = screen_chip(all_prices, tdcc_data, stock_info,
                                                   params=_strategy_params.get("CHIP"))
                print(f"[SCAN] CHIP 命中：{len(all_results['CHIP'])} 支")
            else:
                print("[SCAN] CHIP 跳過（TDCC 快取為空）")
        else:
            print("[SCAN] CHIP 跳過（無 MA 預篩通過股票）")

        _scan_status["results"] = all_results

    except Exception as e:
        _scan_status["error"] = str(e)
    finally:
        _scan_status["running"]     = False
        _scan_status["finished_at"] = datetime.datetime.now().isoformat()
        total_hits = sum(len(v) for v in _scan_status["results"].values())
        print(f"[SCAN] 完成：{total_hits} 支符合，共掃 {_scan_status['total']} 支")
