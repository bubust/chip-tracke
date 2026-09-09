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
                std = closes.rolling(20).std().iloc[-1]
                if not pd.isna(ma) and not pd.isna(std) and std > 0:
                    bb_score = round(max(-10.0, min(10.0, (close - float(ma)) / (2 * float(std)) * 10)))
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
                if int(vol_str) >= 30000:   # 30張 = 30,000股
                    active.add(sid)
            except Exception:
                pass
        print(f"[SCAN] TWSE今日≥30張股票：{len(active)} 支")
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
                        if int(float(vol_str)) < 30000:  # 30張 = 30,000股
                            continue
                    except Exception:
                        pass
                active.add(sid)
            if active:
                print(f"[SCAN] TPEX今日≥30張股票：{len(active)} 支（via {url.split('/')[-1]}）")
                return active
        except Exception as e:
            print(f"[SCAN] TPEX openapi 嘗試失敗 {url}: {e}")
            continue

    print(f"[SCAN] 無法取得TPEX今日資料，上櫃股票全包")
    return set()


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


async def run_market_scan(concurrency: int = 60, strategy_params: dict = None):
    """
    背景執行全市場策略掃描（上市 + 上櫃，全部 stocks.csv 股票）。
    - 啟動時並行取 TWSE/TPEX 有量清單，過濾無量股（盤後效果最好）
    - Semaphore(60) 控制並發；range=1y（足夠所有策略的 235 天需求）
    - scan_one_stock 跑在 ThreadPoolExecutor(16)，不阻塞 event loop
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
        all_tasks = list(stocks[["stock_id", "type"]].itertuples(index=False, name=None))

        # ── 並行取 TWSE + TPEX 有量清單，過濾無量股 ──────────────────────
        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=16)
        try:
            twse_active, tpex_active = await asyncio.wait_for(
                asyncio.gather(
                    loop.run_in_executor(executor, _get_twse_active_today),
                    loop.run_in_executor(executor, _get_tpex_active_today),
                ),
                timeout=20.0,
            )
        except Exception as e:
            print(f"[SCAN] 有量過濾取得失敗({e})，掃全部")
            twse_active, tpex_active = set(), set()
        active_all = twse_active | tpex_active
        if active_all:
            tasks = [(sid, mkt) for sid, mkt in all_tasks if sid in active_all]
            print(f"[SCAN] 有量過濾後：{len(tasks)} 支（原 {len(all_tasks)} 支，跳過 {len(all_tasks)-len(tasks)} 支）")
        else:
            tasks = all_tasks
            print(f"[SCAN] 有量清單為空，掃全部 {len(tasks)} 支")

        print(f"[SCAN] 全市場掃描：共 {len(tasks)} 支")
        _scan_status["total"] = len(tasks)

        all_results  = {k: [] for k in STRATEGY_KEYS}
        all_prices   = {}   # 收集所有價格資料，供 CHIP 使用
        sem = asyncio.Semaphore(concurrency)

        timeout_cfg = httpx.Timeout(connect=3.0, read=8.0, write=3.0, pool=2.0)

        async with httpx.AsyncClient(
            headers={"User-Agent": _UA, "Accept": "application/json"},
            verify=False,
            timeout=timeout_cfg,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=80, max_keepalive_connections=60),
        ) as client:

            async def _fetch_scan(sid, mkt):
                # range=1y 足夠 235 天需求，資料量砍半加快下載
                df = await _fetch_yahoo_async(client, sem, sid, mkt, range_="1y")
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
