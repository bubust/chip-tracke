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
import random
import threading
import time
from itertools import cycle

import httpx
import pandas as pd

# ── 多個 User-Agent 輪替，讓 Yahoo 無法用 UA 封鎖 ────────────────────────────
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
]
_UA = _UA_POOL[0]  # 預設（向下相容）

_SCAN_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://finance.yahoo.com/",
    "Origin": "https://finance.yahoo.com",
}

_host_cycle = cycle(["query1", "query2"])
_host_lock  = threading.Lock()


def _next_host() -> str:
    with _host_lock:
        return next(_host_cycle)


def _rand_ua() -> str:
    return random.choice(_UA_POOL)


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
            # 週末不補（台股不開市），避免掃描結果出現 09/13(六) 等錯誤日期
            if last_dt.weekday() >= 5:
                pass  # Saturday=5, Sunday=6 → skip
            # 只有在 df 裡沒有這天資料時才補（日期統一台灣時間，比對才準）
            elif df.empty or df.iloc[-1]["date"] != last_date:
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
        # 請求前加 0~150ms 隨機抖動，避免突刺流量觸發 Yahoo 限流
        await asyncio.sleep(random.uniform(0, 0.15))
        for suffix in suffixes:
            host = _next_host()
            url  = f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
            headers = {"User-Agent": _rand_ua(), **_SCAN_HEADERS}
            try:
                r = await client.get(url, params=params, headers=headers)
                if r.status_code == 429:
                    # Yahoo 限流：等候再試一次
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                    r = await client.get(url, params=params, headers={"User-Agent": _rand_ua(), **_SCAN_HEADERS})
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
    failed_sids = []
    for (sid, _), df in zip(stock_list, dfs):
        if isinstance(df, Exception) or df is None or df.empty:
            failed_sids.append(sid)
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
                stage = {"code": "unknown", "label": "—", "color": "muted", "desc": "無法計算階段"}
            result[sid] = {"close": round(close, 2), "change_pct": pct,
                           "bb_score": bb_score, "stage": stage}
            # 成功後快取 OHLCV（供 Yahoo 被限流時使用）
            try:
                from price_cache import save_stock_ohlcv
                save_stock_ohlcv(sid, df)
            except Exception:
                pass
        except Exception:
            failed_sids.append(sid)

    # Yahoo 失敗時：用 price_daily TWSE 快取補充（可計算 BB/stage）
    if failed_sids:
        try:
            from price_cache import get_stock_ohlcv
            from scanner import classify_stage
            for sid in failed_sids:
                try:
                    cached_df = get_stock_ohlcv(sid, days=60)
                    if cached_df.empty or len(cached_df) < 2:
                        continue
                    close = float(cached_df.iloc[-1]["close"])
                    prev  = float(cached_df.iloc[-2]["close"])
                    pct   = round((close - prev) / prev * 100, 2) if prev > 0 else 0.0
                    bb_score = 0.0
                    if len(cached_df) >= 20:
                        closes = cached_df['close']
                        ma  = closes.rolling(20).mean().iloc[-1]
                        std = closes.rolling(20).std(ddof=0).iloc[-1]
                        if not pd.isna(ma) and not pd.isna(std) and std > 0:
                            bb_score = round((close - float(ma)) / (2 * float(std)) * 10, 1)
                    try:
                        stage = classify_stage(cached_df)
                    except Exception:
                        stage = {"code": "unknown", "label": "—", "color": "muted", "desc": "快取資料"}
                    result[sid] = {"close": round(close, 2), "change_pct": pct,
                                   "bb_score": bb_score, "stage": stage}
                except Exception:
                    pass
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

STRATEGY_KEYS = ["S1", "S1_SHORT", "S2", "S5", "S17A", "S17B", "S10",
                 "S_PB", "S_FBD", "S_RES", "S_VOLX", "S_VOLX_SHORT", "S_WARRANT_TOP"]

_SCAN_WORKERS = 4    # Fly.io shared-cpu: 4 workers 避免 Yahoo 429 burst

# 各 worker thread 維護自己的 requests.Session，避免 race condition
_scan_thread_local = threading.local()

def _get_scan_session():
    """回傳當前 thread 專屬的 requests.Session（lazy init）。"""
    if not hasattr(_scan_thread_local, "session"):
        import requests as _req, urllib3 as _u3
        _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)
        s = _req.Session()
        s.verify = False
        s.headers.update({"User-Agent": _rand_ua(), **_SCAN_HEADERS})
        _scan_thread_local.session = s
    return _scan_thread_local.session


def _fetch_for_scan(sid: str, market: str) -> pd.DataFrame:
    """
    同步版 fetch（供 ThreadPoolExecutor worker 呼叫）：
    1. 優先讀 price_cache（5 天內的快取直接用，不打 Yahoo）
    2. Cache 缺/舊 → requests.get Yahoo，成功後存入 cache
    """
    import datetime as _dt
    # ── 1. price_cache ────────────────────────────────────────────────────────
    try:
        from price_cache import get_stock_ohlcv, save_stock_ohlcv as _save
        cached = get_stock_ohlcv(sid, days=520)
        if not cached.empty and len(cached) >= 100:
            # 14 天容忍：FinMind/backfill 資料可能落後 1-2 天，不需強制最新
            today_m14 = (_dt.date.today() - _dt.timedelta(days=14)).strftime("%Y%m%d")
            if str(cached.iloc[-1]["date"]) >= today_m14:
                return cached
    except Exception:
        pass
    # ── 2. Yahoo Finance ──────────────────────────────────────────────────────
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]
    now_ts = int(time.time())
    params = {"interval": "1d", "period1": now_ts - 730 * 86400, "period2": now_ts}
    try:
        sess = _get_scan_session()
    except Exception:
        return pd.DataFrame()
    for suffix in suffixes:
        for host in ["query1", "query2"]:
            try:
                url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{sid}{suffix}"
                r = sess.get(url, params=params,
                             headers={"User-Agent": _rand_ua(), **_SCAN_HEADERS},
                             timeout=20)
                # 429 快速失敗（第一輪），重試由外層 retry pass 負責
                if r.status_code == 429:
                    time.sleep(random.uniform(0.8, 1.5))
                    r = sess.get(url, params=params,
                                 headers={"User-Agent": _rand_ua(), **_SCAN_HEADERS},
                                 timeout=20)
                    if r.status_code == 429:
                        return pd.DataFrame()   # 快速放棄，讓 retry pass 處理
                r.raise_for_status()
                df = _parse_yahoo_json(r.json())
                if not df.empty and len(df) >= 5:
                    try:
                        from price_cache import save_stock_ohlcv as _save
                        _save(sid, df)
                    except Exception:
                        pass
                    return df
            except Exception:
                pass
    return pd.DataFrame()

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

# 掃描結果持久化路徑
import json as _json
from pathlib import Path as _Path
_SCAN_CACHE_FILE = _Path(__file__).parent / "chip_data" / "scan_results_cache.json"


def _save_scan_cache(results: dict):
    """將掃描結果存到磁碟，重啟後可還原訊號"""
    try:
        _SCAN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SCAN_CACHE_FILE, "w", encoding="utf-8") as f:
            _json.dump(results, f, ensure_ascii=False)
    except Exception as e:
        print(f"[SCAN] 儲存快取失敗: {e}")


def _load_scan_cache() -> dict:
    """啟動時載入上次掃描結果（讓訊號重啟後不消失）
    優先讀本地快取；若不存在（Render 重啟後），fallback 到 scan_data/latest.json
    （GitHub Actions 掃描後提交到 repo，Render deploy 時一同佈署）。
    """
    # 1. 本地快取（本次環境 run_market_scan 寫入的）
    try:
        if _SCAN_CACHE_FILE.exists():
            with open(_SCAN_CACHE_FILE, "r", encoding="utf-8") as f:
                data = _json.load(f)
                if data:
                    return data
    except Exception as e:
        print(f"[SCAN] 載入快取失敗: {e}")
    # 2. Fallback：讀 scan_data/latest.json（跟著 git deploy 到 Render）
    _latest = _Path(__file__).parent / "scan_data" / "latest.json"
    try:
        if _latest.exists():
            with open(_latest, "r", encoding="utf-8") as f:
                d = _json.load(f)
                results = d.get("results", {})
                if results:
                    print(f"[SCAN] 從 latest.json 載入結果 (掃描時間: {d.get('scanned_at', '')})")
                    return results
    except Exception as e:
        print(f"[SCAN] 載入 latest.json 失敗: {e}")
    return {}


# 啟動時自動載入快取
_scan_status["results"] = _load_scan_cache()


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


async def run_market_scan(strategy_params: dict = None):
    """
    背景執行全市場策略掃描（上市 + 上櫃，全部 stocks.csv 股票）。
    架構仿照 tw-macd-scan：
    - thread-local requests.Session（每 worker 自己的連線）
    - ThreadPoolExecutor(_SCAN_WORKERS=12)，不用 asyncio/Semaphore
    - 先查 price_cache，5 天內的快取直接跑計算，不打 Yahoo
    - Cache 缺/舊才 fetch Yahoo，並自動存回 cache
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from scanner import scan_one_stock
    _strategy_params = strategy_params or {}
    _min_vol_ratio = (_strategy_params.get("_global") or {}).get("min_vol_ratio", 0.0)
    _status_lock = threading.Lock()

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

        print(f"[SCAN] 全市場掃描：共 {len(tasks)} 支，{_SCAN_WORKERS} workers")
        _scan_status["total"] = len(tasks)

        _scan_status["phase"] = "yahoo"

        all_results = {k: [] for k in STRATEGY_KEYS}

        def _one(sid, mkt):
            """單支股票：fetch → scan，在 worker thread 執行。只回傳 result dict，不回傳 df（避免 Future 持有大量 DataFrame）"""
            try:
                df = _fetch_for_scan(sid, mkt)
            except Exception:
                df = pd.DataFrame()
            with _status_lock:
                _scan_status["progress"] += 1
                if df.empty or len(df) < 5:
                    _scan_status["yahoo_fail"] += 1
                    _scan_status["failed_stocks"].append(sid)
                    return None
                _scan_status["yahoo_ok"] += 1
            try:
                result = scan_one_stock(df, sid, names.get(sid, ""),
                                        strategy_params=_strategy_params,
                                        min_vol_ratio=_min_vol_ratio)
            except Exception as _scan_e:
                with _status_lock:
                    _ec = _scan_status.get("_scan_err_count", 0)
                    if _ec < 3:
                        import traceback as _tb
                        print(f"[SCAN] scan_one_stock 異常 {sid}: {_scan_e}")
                        _tb.print_exc()
                        _scan_status["_scan_err_count"] = _ec + 1
                result = {}
            return result  # 不回傳 df，讓 GC 立即釋放

        def _run_blocking():
            with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as ex:
                futures = {ex.submit(_one, sid, mkt): sid for sid, mkt in tasks}
                for fut in as_completed(futures):
                    try:
                        result = fut.result()
                        if result is None:
                            continue
                        sid = futures[fut]
                        for strat, r in result.items():
                            if r is not None:
                                all_results[strat].append(r)
                    except Exception:
                        pass

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _run_blocking)
        _first_pass_hits = sum(len(v) for v in all_results.values())
        print(f"[SCAN] 第一輪完成：yahoo_ok={_scan_status['yahoo_ok']}, yahoo_fail={_scan_status['yahoo_fail']}, 命中={_first_pass_hits}")
        # 第一輪結束立即存檔，不管後續 retry/S_WARRANT_TOP 是否成功
        _scan_status["results"] = all_results
        _save_scan_cache(all_results)
        if _first_pass_hits == 0 and _scan_status["yahoo_ok"] > 0:
            # 抽樣 2330 診斷
            try:
                _dbg_df = _fetch_for_scan("2330", "twse")
                if not _dbg_df.empty:
                    from scanner import scan_one_stock as _dbg_scan
                    _dbg_r = _dbg_scan(_dbg_df, "2330", "台積電")
                    print(f"[SCAN DEBUG] 2330 最後日={_dbg_df.iloc[-1].get('date','?')}, rows={len(_dbg_df)}, 結果={_dbg_r}")
            except Exception as _dbge:
                print(f"[SCAN DEBUG] 2330 診斷失敗: {_dbge}")

        # ── 重試：失敗股票補抓（整塊包 try/except，不影響主要結果）──
        try:
            market_type_map = dict(zip(stocks["stock_id"], stocks["type"]))

            def _retry_one(sid, mkt):
                """重試版 fetch+scan，只回傳 result dict。"""
                try:
                    df = _fetch_for_scan(sid, mkt)
                except Exception:
                    df = pd.DataFrame()
                if df.empty or len(df) < 5:
                    return None
                try:
                    result = scan_one_stock(df, sid, names.get(sid, ""),
                                            strategy_params=_strategy_params,
                                            min_vol_ratio=_min_vol_ratio)
                except Exception:
                    result = {}
                return result

            # ── 二次重試（失敗股票補抓一輪；兩次都失敗的非活躍股不再第三輪）──
            if _scan_status["failed_stocks"]:
                retry_list = [
                    (sid, market_type_map.get(sid, "twse"))
                    for sid in list(_scan_status["failed_stocks"])
                ]
                print(f"[SCAN] 第一輪失敗 {len(retry_list)} 支，開始二次重試...")

                def _run_retry_blocking():
                    RETRY_BATCH = 40
                    for i in range(0, len(retry_list), RETRY_BATCH):
                        chunk = retry_list[i: i + RETRY_BATCH]
                        time.sleep(2.0)  # 從 4s 縮短到 2s
                        with ThreadPoolExecutor(max_workers=4) as ex2:
                            fut2s = {ex2.submit(_retry_one, sid, mkt): sid for sid, mkt in chunk}
                            for fut2 in as_completed(fut2s):
                                try:
                                    result2 = fut2.result()
                                    if result2 is None:
                                        continue
                                    sid2 = fut2s[fut2]
                                    with _status_lock:
                                        if sid2 in _scan_status["failed_stocks"]:
                                            _scan_status["failed_stocks"].remove(sid2)
                                            _scan_status["yahoo_fail"] -= 1
                                            _scan_status["yahoo_ok"] += 1
                                        for strat, r2 in result2.items():
                                            if r2 is not None:
                                                all_results[strat].append(r2)
                                except Exception:
                                    pass

                await loop.run_in_executor(None, _run_retry_blocking)
                print(f"[SCAN] 二次重試完成，剩餘失敗 {_scan_status['yahoo_fail']} 支（非活躍股，不再重試）")

        except Exception as _retry_e:
            print(f"[SCAN] 重試異常（主要結果不受影響）: {_retry_e}")

        # 重試後更新存檔（含重試新增的命中）
        _scan_status["results"] = all_results
        _save_scan_cache(all_results)
        print(f"[SCAN] 主要策略完成，命中={sum(len(v) for v in all_results.values())}")

        # S_WARRANT_TOP：認購權證前十大（按需 fetch 價格，不再依賴已移除的 all_prices）
        try:
            from warrant.flow import get_available_dates as _wf_dates_fn, get_ranking as _wf_ranking
            from scanner import screen_s_warrant_top
            _wf_dates  = _wf_dates_fn()
            _wf_date   = _wf_dates[0] if _wf_dates else None
            if _wf_date:
                _wf_params = _strategy_params.get("S_WARRANT_TOP", {})
                _wf_limit  = int(_wf_params.get("limit", 10))
                _wf_fetch  = min(_wf_limit * 3, 60)
                _wf_rows   = _wf_ranking(date_str=_wf_date, sort_by="call", limit=_wf_fetch)
                # 只為權證標的股票按需取得價格（通常 10-30 支，不再累積全市場）
                _warrant_prices = {}
                def _fetch_warrant_prices():
                    for _wr in _wf_rows:
                        _wsid = _wr.get("underlying_code", "")
                        if _wsid and _wsid not in _warrant_prices:
                            try:
                                _wdf = _fetch_for_scan(_wsid, market_type_map.get(_wsid, "twse"))
                                if not _wdf.empty:
                                    _warrant_prices[_wsid] = _wdf
                            except Exception:
                                pass
                await loop.run_in_executor(None, _fetch_warrant_prices)
                all_results["S_WARRANT_TOP"] = screen_s_warrant_top(
                    _wf_rows, _warrant_prices, names, params=_wf_params
                )
                print(f"[SCAN] S_WARRANT_TOP {_wf_date} 命中：{len(all_results['S_WARRANT_TOP'])} 支")
            else:
                print("[SCAN] S_WARRANT_TOP 跳過（warrant_flow 無資料）")
        except Exception as _we:
            import traceback; traceback.print_exc()
            print(f"[SCAN] S_WARRANT_TOP 失敗: {_we}")
            all_results["S_WARRANT_TOP"] = []

        _scan_status["results"] = all_results
        _save_scan_cache(all_results)  # 持久化，重啟後訊號不消失

        # 同步到 Supabase（讓 GitHub Actions → Supabase → Render 的架構也能用）
        try:
            import supabase_store as _sb_scan
            import json as _json_scan
            import datetime as _dt_scan
            if _sb_scan._enabled():
                _payload = _json_scan.dumps({
                    "results": all_results,
                    "scanned_at": _dt_scan.datetime.now().isoformat(),
                    "yahoo_ok": _scan_status["yahoo_ok"],
                    "yahoo_fail": _scan_status["yahoo_fail"],
                }, ensure_ascii=False)
                _sb_scan.kv_set("scan_latest", _payload)
        except Exception:
            pass

    except Exception as e:
        _scan_status["error"] = str(e)
    finally:
        _scan_status["running"]     = False
        _scan_status["finished_at"] = datetime.datetime.now().isoformat()
        total_hits = sum(len(v) for v in _scan_status["results"].values())
        print(f"[SCAN] 完成：{total_hits} 支符合，共掃 {_scan_status['total']} 支")
        # 掃描後自動更新廣度指標 + regime 因子（供 Divergence 背離計算）
        try:
            from regime.fetcher import fetch_twse_market_breadth
            from regime.factor import calculate_factors
            fetch_twse_market_breadth(lookback=10)  # 廣度：直接用 TWSE 上漲家數占比
            calculate_factors()
            print("[SCAN] regime breadth + factors 已更新")
        except Exception as _re:
            print(f"[SCAN] regime 更新跳過: {_re}")
