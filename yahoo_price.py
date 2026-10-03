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
_results_lock = threading.Lock()   # 保護 _scan_status["results"] 讀寫，防止 JSON 序列化競態


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

def _parse_yahoo_json(data: dict, adjusted: bool = False) -> pd.DataFrame:
    """adjusted=True 時多一欄 adjclose（除權息還原收盤，回測用）；預設不變，掃描不受影響。"""
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
    if adjusted:
        _adj = ((result["indicators"].get("adjclose") or [{}])[0] or {}).get("adjclose")
        df["adjclose"] = _adj if _adj and len(_adj) == len(df) else df["close"]
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    df["date"] = df.index.strftime("%Y%m%d")
    df = df.reset_index(drop=True)[["date", "open", "high", "low", "close", "volume"]
                                   + (["adjclose"] if adjusted else [])]
    # Yahoo 成交量為「股數（股）」，台股 1 張 = 1000 股，統一轉為張，與 price_cache 一致
    df["volume"] = (df["volume"].fillna(0) / 1000).round().astype(int)

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
                    vol = int(rmv) // 1000  # 股 → 張
                except Exception:
                    vol = 0
                # 用 meta 的真實 open/high/low，避免 open==close 造成策略誤判
                rmo = float(meta.get("regularMarketOpen") or rmp)
                rmh = float(meta.get("regularMarketDayHigh") or rmp)
                rml = float(meta.get("regularMarketDayLow") or rmp)
                new_row = pd.DataFrame([{
                    "date": last_date, "open": rmo, "high": rmh,
                    "low": rml, "close": float(rmp), "volume": vol,
                    **({"adjclose": float(rmp)} if adjusted else {}),
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

# 掃描目標日：快取最後日 >= 目標日才走快取，否則打 Yahoo。
# 由 run_market_scan() 每次開頭依台灣時鐘重新計算（_compute_scan_target），
# 不再用 update_price_cache() 的 latest（TWSE openapi 會延遲到隔天，導致停在前一日）。
_scan_cache_target_date: str = ""  # e.g. "20261001"

_MARKET_OPEN = (9, 0)

def _tw_now() -> datetime.datetime:
    """台灣時間（UTC+8，無夏令時間）。Fly 容器 TZ=UTC，不可用 date.today()。"""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

def _compute_scan_target(now: datetime.datetime = None) -> str:
    """平日 09:00 後 → 今日；否則 → 最近一個已收盤平日（盤前取前一平日、週末取週五）。"""
    now = now or _tw_now()
    d = now.date()
    if d.weekday() < 5 and (now.hour, now.minute) >= _MARKET_OPEN:
        return d.strftime("%Y%m%d")
    d -= datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y%m%d")

def _set_scan_target_date(date_str: str):
    """手動覆寫目標日（保留相容；run_market_scan() 開頭會重新計算覆寫）。"""
    global _scan_cache_target_date
    _scan_cache_target_date = date_str or ""

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


# 掃描失敗原因：not_found = Yahoo 查無（多半下市/暫停交易）；throttled = 被 Yahoo 限流；
# network = 連線錯誤/逾時；empty = 有回應但沒有 K 線
_fetch_fail_reason: dict = {}
_FAIL_LABELS = {"not_found": "Yahoo 查無此股（可能下市或暫停交易）", "throttled": "Yahoo 限流",
                "network": "連線失敗/逾時", "empty": "Yahoo 沒有 K 線資料"}


def _note_fail(sid: str, reason: str):
    """同一支多次嘗試時，可重試的原因（限流/連線）優先記下"""
    rank = {"not_found": 0, "empty": 1, "network": 2, "throttled": 3}
    old = _fetch_fail_reason.get(sid)
    if old is None or rank.get(reason, 0) > rank.get(old, 0):
        _fetch_fail_reason[sid] = reason


def _fetch_for_scan(sid: str, market: str) -> pd.DataFrame:
    """
    同步版 fetch（供 ThreadPoolExecutor worker 呼叫）：
    1. Cache 已達目標日期 → 直接用，跳過 Yahoo（快速路徑）
       目標日期 = update_price_cache() 成功取得的日期（可能是昨日收盤，非 date.today()）
    2. Cache 落後目標日期 → 先嘗試 Yahoo 取最新資料
    3. Yahoo 失敗 → 降級用 4 天內的 cache 備援（週末/假日場景）
    """
    import datetime as _dt
    _now = _tw_now()
    today_str = _now.strftime("%Y%m%d")
    target_date = _scan_cache_target_date or _compute_scan_target(_now)
    _cached_fallback = pd.DataFrame()  # Yahoo 失敗時的備援
    # ── 1. price_cache 快速路徑（cache 已達目標日期）────────────────────────
    try:
        from price_cache import get_stock_ohlcv, save_stock_ohlcv as _save
        cached = get_stock_ohlcv(sid, days=520)
        if not cached.empty and len(cached) >= 100:
            last_date = str(cached.iloc[-1]["date"])
            if last_date >= target_date:
                # Cache 已達目標日期，直接用，跳過 Yahoo
                return cached
            # Cache 落後目標 → 嘗試 Yahoo；4 天內的 cache 保留備援
            today_m4 = (_now.date() - _dt.timedelta(days=4)).strftime("%Y%m%d")
            if last_date >= today_m4:
                _cached_fallback = cached  # Yahoo 失敗時（週末/假日）可用
    except Exception:
        pass
    # ── 2. Yahoo Finance ──────────────────────────────────────────────────────
    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]
    now_ts = int(time.time())
    params = {"interval": "1d", "period1": now_ts - 730 * 86400, "period2": now_ts}
    try:
        sess = _get_scan_session()
    except Exception:
        if not _cached_fallback.empty:
            return _cached_fallback
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
                        _note_fail(sid, "throttled")
                        return pd.DataFrame()   # 快速放棄，讓 retry pass 處理
                if r.status_code == 404:
                    _note_fail(sid, "not_found")
                    continue
                r.raise_for_status()
                df = _parse_yahoo_json(r.json())
                if df.empty or len(df) < 5:
                    _note_fail(sid, "empty")
                if not df.empty and len(df) >= 5:
                    try:
                        from price_cache import save_stock_ohlcv as _save
                        # save_stock_ohlcv 盤中會略過今日未完成 K 棒；回傳給掃描的 df 仍含今日即時價
                        _save(sid, df)
                    except Exception:
                        pass
                    _fetch_fail_reason.pop(sid, None)
                    return df
            except Exception:
                _note_fail(sid, "network")
    # ── 3. Fallback：Yahoo 全失敗時用 cache 備援（週末/假日）──────────────────
    if not _cached_fallback.empty:
        return _cached_fallback
    return pd.DataFrame()

_scan_status: dict = {
    "running":      False,
    "progress":     0,
    "total":        0,
    "yahoo_ok":     0,   # 成功取得 Yahoo 資料的股票數
    "yahoo_fail":   0,   # Yahoo 回傳空/失敗的股票數
    "failed_stocks": [],  # 失敗的股票代號清單
    "phase":        "",  # 目前階段："yahoo" | "tdcc" | "done"
    "tdcc_total":    0,   # TDCC 需爬股票數
    "skipped_stale": 0,   # 久未更新的殭屍股，掃描前跳過不計入失敗
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
    import datetime as _dt
    try:
        _SCAN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SCAN_CACHE_FILE, "w", encoding="utf-8") as f:
            _json.dump(results, f, ensure_ascii=False)
        # 同時存時間戳，讓重啟後 finished_at 可正確還原
        _ts_file = _SCAN_CACHE_FILE.parent / "scan_timestamp.txt"
        _ts_file.write_text(_dt.datetime.now().isoformat())
    except Exception as e:
        print(f"[SCAN] 儲存快取失敗: {e}")


def _load_scan_cache() -> tuple:
    """啟動時載入上次掃描結果（讓訊號重啟後不消失）
    回傳 (results_dict, scanned_at_str)
    優先讀本地快取；若不存在（Render 重啟後），fallback 到 scan_data/latest.json
    （GitHub Actions 掃描後提交到 repo，Render deploy 時一同佈署）。
    """
    # 1. 本地快取（本次環境 run_market_scan 寫入的）
    try:
        if _SCAN_CACHE_FILE.exists():
            with open(_SCAN_CACHE_FILE, "r", encoding="utf-8") as f:
                data = _json.load(f)
                if data:
                    # 讀時間戳
                    _ts_file = _SCAN_CACHE_FILE.parent / "scan_timestamp.txt"
                    _ts = _ts_file.read_text().strip() if _ts_file.exists() else None
                    return data, _ts
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
                    scanned_at = d.get("scanned_at", "")
                    print(f"[SCAN] 從 latest.json 載入結果 (掃描時間: {scanned_at})")
                    return results, scanned_at
    except Exception as e:
        print(f"[SCAN] 載入 latest.json 失敗: {e}")
    return {}, None


# 啟動時自動載入快取
_cached_results, _cached_ts = _load_scan_cache()
_scan_status["results"] = _cached_results
if _cached_results and _cached_ts:
    _scan_status["finished_at"] = _cached_ts   # 讓前端 finished_at 路徑正常走


def get_scan_status() -> dict:
    counts = {k: len(v) for k, v in _scan_status["results"].items()} if _scan_status["results"] else {}
    return {
        "running":       _scan_status["running"],
        "progress":      _scan_status["progress"],
        "total":         _scan_status["total"],
        "yahoo_ok":      _scan_status["yahoo_ok"],
        "yahoo_fail":    _scan_status["yahoo_fail"],
        "failed_stocks": _scan_status["failed_stocks"],
        "phase":          _scan_status.get("phase", ""),
        "tdcc_total":     _scan_status.get("tdcc_total", 0),
        "skipped_stale":  _scan_status.get("skipped_stale", 0),
        "skipped_list":   _scan_status.get("skipped_list", []),
        "failed_detail":  _scan_status.get("failed_detail", {}),
        "warrant_note":   _scan_status.get("warrant_note", ""),
        "counts":         counts,
        "finished_at":    _scan_status["finished_at"],
        "error":          _scan_status["error"],
    }


def get_scan_results() -> dict:
    with _results_lock:
        raw = _scan_status["results"]
        if not raw:
            return {}
        # list(v) 複製各策略 list，避免 JSON 序列化時被 retry thread 同步 append 造成 RuntimeError
        return {k: list(v) for k, v in raw.items()}


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
    # 使用模組級 _results_lock（與 get_scan_results() 共用同一把鎖）
    # _status_lock = threading.Lock()  ← 已移除，改用 _results_lock

    _scan_status["running"]        = True
    _scan_status["progress"]       = 0
    _scan_status["phase"]          = "yahoo"
    _scan_status["tdcc_total"]     = 0
    _scan_status["yahoo_ok"]       = 0
    _scan_status["yahoo_fail"]     = 0
    _scan_status["skipped_stale"]  = 0
    _scan_status["failed_stocks"]  = []
    _scan_status["skipped_list"]   = []
    _scan_status["failed_detail"]  = {}
    _scan_status.pop("warrant_note", None)
    _fetch_fail_reason.clear()
    _scan_status["results"]        = {}
    _scan_status["error"]          = None
    _scan_status["finished_at"]    = None

    # 目標日每次重算（手動 / 18:00 排程同一路徑），不沿用上次殘留值
    global _scan_cache_target_date
    _scan_cache_target_date = _compute_scan_target()
    _scan_status["target_date"]    = _scan_cache_target_date
    _scan_status["target_hits"]    = 0   # 最後一根 K 棒已達目標日的股數
    print(f"[SCAN] 目標日 {_scan_cache_target_date}（台灣時間 {_tw_now():%Y-%m-%d %H:%M}）")

    try:
        stocks = get_stock_list()
        names  = dict(zip(stocks["stock_id"], stocks["stock_name"]))
        tasks  = list(stocks[["stock_id", "type"]].itertuples(index=False, name=None))

        # ── 預過濾殭屍股（> 60 天無更新）──
        try:
            from price_cache import get_stale_stocks
            stale_set = get_stale_stocks(days_threshold=60)
            if stale_set and len(stale_set) > len(tasks) * 0.25:
                print(f"[SCAN] 殭屍股 {len(stale_set)} 支超過四分之一，疑似快取異常，本次不過濾")
                stale_set = set()
            if stale_set:
                _scan_status["skipped_list"] = sorted(stale_set & {sid for sid, _ in tasks})
                before = len(tasks)
                tasks = [(sid, mkt) for sid, mkt in tasks if sid not in stale_set]
                _scan_status["skipped_stale"] = before - len(tasks)
                print(f"[SCAN] 跳過殭屍股 {_scan_status['skipped_stale']} 支（> 60 天無更新）")
        except Exception as _stale_e:
            print(f"[SCAN] 殭屍過濾失敗（非致命）: {_stale_e}")

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
            with _results_lock:
                _scan_status["progress"] += 1
                if df.empty or len(df) < 5:
                    _scan_status["yahoo_fail"] += 1
                    _scan_status["failed_stocks"].append(sid)
                    return None
                _scan_status["yahoo_ok"] += 1
                if str(df.iloc[-1]["date"]) >= _scan_cache_target_date:
                    _scan_status["target_hits"] += 1
            try:
                result = scan_one_stock(df, sid, names.get(sid, ""),
                                        strategy_params=_strategy_params,
                                        min_vol_ratio=_min_vol_ratio)
            except Exception as _scan_e:
                with _results_lock:
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
        print(f"[SCAN] 第一輪完成：yahoo_ok={_scan_status['yahoo_ok']}, yahoo_fail={_scan_status['yahoo_fail']}, 命中={_first_pass_hits}, "
              f"達目標日 {_scan_cache_target_date}={_scan_status['target_hits']}")
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
                """重試版 fetch+scan：輕量短 timeout，快速放棄 429。"""
                import requests as _req
                suffixes = [".TW"] if mkt == "twse" else [".TWO", ".TW"]
                now2  = int(time.time())
                p1    = now2 - 365 * 86400
                params2 = {"interval": "1d", "period1": p1, "period2": now2}
                df = pd.DataFrame()
                for sfx in suffixes:
                    for host2 in ["query1", "query2"]:
                        try:
                            url2 = f"https://{host2}.finance.yahoo.com/v8/finance/chart/{sid}{sfx}"
                            r2 = _req.get(url2, params=params2,
                                          headers={"User-Agent": _rand_ua(), **_SCAN_HEADERS},
                                          timeout=5)        # 短 timeout：快速放棄
                            if r2.status_code == 429:
                                break                       # 被限流直接放棄，不重試
                            if r2.ok:
                                df = _parse_yahoo_json(r2.json())
                                if not df.empty and len(df) >= 5:
                                    break
                        except Exception:
                            pass
                    if not df.empty:
                        break
                if df.empty or len(df) < 5:
                    return None
                try:
                    result = scan_one_stock(df, sid, names.get(sid, ""),
                                            strategy_params=_strategy_params,
                                            min_vol_ratio=_min_vol_ratio)
                except Exception:
                    result = {}
                return result

            # ── 二次重試（全部失敗股一批，workers=6，每批 0.5s 間隔）──
            if _scan_status["failed_stocks"]:
                retry_list = [
                    (sid, market_type_map.get(sid, "twse"))
                    for sid in list(_scan_status["failed_stocks"])
                ]
                print(f"[SCAN] 第一輪失敗 {len(retry_list)} 支，開始二次重試（workers=6, timeout=5s）...")

                def _run_retry_blocking():
                    RETRY_BATCH = 60          # 每批 60 支（原 40）
                    RETRY_WORKERS = 6         # 6 workers（原 4）
                    for i in range(0, len(retry_list), RETRY_BATCH):
                        chunk = retry_list[i: i + RETRY_BATCH]
                        time.sleep(0.5)       # 批次間短暫停（原 2s）
                        with ThreadPoolExecutor(max_workers=RETRY_WORKERS) as ex2:
                            fut2s = {ex2.submit(_retry_one, sid, mkt): sid for sid, mkt in chunk}
                            for fut2 in as_completed(fut2s):
                                try:
                                    result2 = fut2.result()
                                    if result2 is None:
                                        continue
                                    sid2 = fut2s[fut2]
                                    with _results_lock:
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
                print(f"[SCAN] 二次重試完成，剩餘失敗 {_scan_status['yahoo_fail']} 支")

            # ── 三次重試：只針對限流/連線失敗（Yahoo 查無的不重試），2 workers 慢慢來，被限流就等 3 秒 ──
            _retryable = [sid for sid in list(_scan_status["failed_stocks"])
                          if _fetch_fail_reason.get(sid, "network") in ("throttled", "network", "empty")]
            if _retryable:
                print(f"[SCAN] 三次重試 {len(_retryable)} 支（限流/連線失敗）…")

                def _slow_one(sid):
                    mkt = market_type_map.get(sid, "twse")
                    for attempt in range(2):
                        df = _fetch_for_scan(sid, mkt)
                        if not df.empty and len(df) >= 5:
                            return sid, df
                        if _fetch_fail_reason.get(sid) != "throttled":
                            break
                        time.sleep(3 + attempt * 3)
                    return sid, None

                def _run_slow_blocking():
                    with ThreadPoolExecutor(max_workers=2) as ex3:
                        for sid3, df3 in ex3.map(_slow_one, _retryable):
                            if df3 is None:
                                continue
                            try:
                                result3 = scan_one_stock(df3, sid3, names.get(sid3, ""),
                                                         strategy_params=_strategy_params,
                                                         min_vol_ratio=_min_vol_ratio)
                            except Exception:
                                result3 = {}
                            with _results_lock:
                                if sid3 in _scan_status["failed_stocks"]:
                                    _scan_status["failed_stocks"].remove(sid3)
                                    _scan_status["yahoo_fail"] -= 1
                                    _scan_status["yahoo_ok"] += 1
                                for strat, r3 in (result3 or {}).items():
                                    if r3 is not None:
                                        all_results[strat].append(r3)

                await loop.run_in_executor(None, _run_slow_blocking)
                print(f"[SCAN] 三次重試完成，剩餘失敗 {_scan_status['yahoo_fail']} 支")

        except Exception as _retry_e:
            print(f"[SCAN] 重試異常（主要結果不受影響）: {_retry_e}")

        # 每支失敗股票的原因（給畫面顯示）
        _scan_status["failed_detail"] = {
            sid: _FAIL_LABELS.get(_fetch_fail_reason.get(sid, ""), "未知原因")
            for sid in _scan_status["failed_stocks"]
        }

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
            _tgt = _scan_cache_target_date
            _tgt_dash = f"{_tgt[:4]}-{_tgt[4:6]}-{_tgt[6:]}" if len(_tgt) == 8 else ""
            if (not _wf_date or (_tgt_dash and _wf_date < _tgt_dash)):
                # 權證金流缺最新交易日：先試官方日報，再用權證盤外掃描（MIS 盤後成交量）聚合
                print(f"[SCAN] S_WARRANT_TOP：warrant_flow 最新 {_wf_date or '無'}，目標 {_tgt_dash}，補算中…")
                def _refresh_flow():
                    try:
                        from warrant.flow import calc_and_save as _wf_calc
                        if _tgt_dash and _wf_calc(_tgt_dash) > 0:
                            return
                    except Exception as _e1:
                        print(f"[SCAN] 權證官方日報失敗: {_e1}")
                    try:
                        from warrant.router import run_scanner as _w_scan, _is_market_open as _w_open
                        if not _w_open():
                            _w_scan()
                    except Exception as _e2:
                        print(f"[SCAN] 權證盤外掃描失敗: {_e2}")
                await loop.run_in_executor(None, _refresh_flow)
                _wf_dates = _wf_dates_fn()
                _wf_date = _wf_dates[0] if _wf_dates else None
            # 最多接受 7 天前的金流（連假時用最後一個交易日）
            if _wf_date and (datetime.date.today() - datetime.date.fromisoformat(_wf_date)).days > 7:
                print(f"[SCAN] S_WARRANT_TOP：最新金流 {_wf_date} 已超過 7 天，不採用")
                _scan_status["warrant_note"] = f"權證金流最新只有 {_wf_date}（超過 7 天），認購前十大暫停"
                _wf_date = None
            if _wf_date:
                _scan_status["warrant_note"] = f"認購前十大使用 {_wf_date} 權證成交"
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
                _scan_status.setdefault("warrant_note", "權證金流抓不到（證交所/櫃買被擋且 MIS 也沒有資料），認購前十大暫停")
        except Exception as _we:
            import traceback; traceback.print_exc()
            print(f"[SCAN] S_WARRANT_TOP 失敗: {_we}")
            _scan_status["warrant_note"] = f"認購前十大計算失敗：{type(_we).__name__}"
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
