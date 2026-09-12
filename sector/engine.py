"""
sector/engine.py — 台股產業輪動引擎 V1
核心計算：產業指數、均線、Swing、Trend、Rank、Internal Health、結構事件
"""
import logging
import time
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .db import db
from .universe import get_all_sectors, get_sector_stocks

log = logging.getLogger(__name__)

CHIP_DATA = Path(__file__).parent.parent / "chip_data"

# ─────────────────────────────────────────────────────────────────────────────
# 股價載入（Yahoo Finance）
# ─────────────────────────────────────────────────────────────────────────────

_PRICE_CACHE: dict[str, pd.DataFrame] = {}
_PRICE_CACHE_TS: float = 0.0
_PRICE_CACHE_TTL: float = 3600.0  # 1 小時內不重抓


def _load_stock_prices_yahoo(stock_id: str, market: str = "twse", min_dates: int = 60) -> Optional[pd.DataFrame]:
    """
    用 Yahoo Finance 抓取個股 OHLCV。
    回傳 DataFrame(date:str, open, high, low, close, volume) 或 None。
    date 格式：'YYYYMMDD'
    """
    import httpx
    import time as _time

    suffixes = [".TW"] if market == "twse" else [".TWO", ".TW"]
    now = int(_time.time())
    p1 = now - 400 * 86400  # 抓 ~13 個月
    params = {"interval": "1d", "period1": p1, "period2": now}
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

    for suffix in suffixes:
        for host in ["query1", "query2"]:
            url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{stock_id}{suffix}"
            try:
                with httpx.Client(
                    headers={"User-Agent": UA, "Accept": "application/json"},
                    verify=False,
                    timeout=10.0,
                    follow_redirects=True,
                ) as client:
                    r = client.get(url, params=params)
                    r.raise_for_status()
                    data = r.json()

                result_list = data.get("chart", {}).get("result") or []
                if not result_list:
                    continue
                result = result_list[0]
                meta = result.get("meta", {})
                quote = result["indicators"]["quote"][0]
                timestamps = result.get("timestamp", [])

                _TW_OFFSET = pd.Timedelta(hours=8)
                tw_idx = (
                    pd.to_datetime(timestamps, unit="s", utc=True) + _TW_OFFSET
                ).tz_localize(None)

                df = pd.DataFrame(
                    {
                        "open": quote.get("open", []),
                        "high": quote.get("high", []),
                        "low": quote.get("low", []),
                        "close": quote.get("close", []),
                        "volume": quote.get("volume", []),
                    },
                    index=tw_idx,
                )
                df = df.dropna(subset=["close"])
                df = df[df["close"] > 0]
                df["date"] = df.index.strftime("%Y%m%d")
                df = df.reset_index(drop=True)[
                    ["date", "open", "high", "low", "close", "volume"]
                ]

                # 補最新盤中 meta
                try:
                    rmp = meta.get("regularMarketPrice")
                    rmt = meta.get("regularMarketTime")
                    rmv = meta.get("regularMarketVolume") or 0
                    if rmp and rmt and float(rmp) > 0:
                        from datetime import datetime as _dt2, timedelta as _td
                        last_dt = datetime.utcfromtimestamp(int(rmt)) + timedelta(hours=8)
                        last_date = last_dt.strftime("%Y%m%d")
                        if df.empty or df.iloc[-1]["date"] != last_date:
                            rmo = float(meta.get("regularMarketOpen") or rmp)
                            rmh = float(meta.get("regularMarketDayHigh") or rmp)
                            rml = float(meta.get("regularMarketDayLow") or rmp)
                            new_row = pd.DataFrame(
                                [
                                    {
                                        "date": last_date,
                                        "open": rmo,
                                        "high": rmh,
                                        "low": rml,
                                        "close": float(rmp),
                                        "volume": int(rmv),
                                    }
                                ]
                            )
                            df = pd.concat([df, new_row], ignore_index=True)
                except Exception:
                    pass

                if len(df) >= min_dates:
                    return df
            except Exception:
                continue

    return None


def load_stock_prices(stock_id: str, market: str = "twse", min_dates: int = 60) -> Optional[pd.DataFrame]:
    """
    載入股票價格，先查快取，miss 再從 Yahoo 抓。
    """
    cached = _PRICE_CACHE.get(stock_id)
    if cached is not None and (time.time() - _PRICE_CACHE_TS) < _PRICE_CACHE_TTL:
        return cached if len(cached) >= min_dates else None

    df = _load_stock_prices_yahoo(stock_id, market=market, min_dates=min_dates)
    if df is not None:
        _PRICE_CACHE[stock_id] = df
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 產業等權重指數
# ─────────────────────────────────────────────────────────────────────────────

def calc_sector_index(
    price_dict: dict[str, pd.DataFrame], lookback: int = 250
) -> pd.DataFrame:
    """
    計算等權重產業指數（rebased to 100）。
    price_dict: {stock_id: DataFrame(date, close)}
    回傳 DataFrame(date, index_level, member_count)，date 為字串 'YYYYMMDD'
    """
    if not price_dict:
        return pd.DataFrame()

    # 對齊所有股票的 close 序列
    close_frames = []
    for sid, df in price_dict.items():
        s = df.set_index("date")["close"].rename(sid)
        close_frames.append(s)

    aligned = pd.concat(close_frames, axis=1).sort_index()

    # 取最近 lookback 天
    if len(aligned) > lookback:
        aligned = aligned.iloc[-lookback:]

    # 每日等權重報酬（各列使用當日有數據的股票均值）
    pct = aligned.pct_change()

    # 計算每日等權重平均報酬（忽略 NaN）
    ew_ret = pct.mean(axis=1, skipna=True)

    # 用累積報酬計算指數（rebase to 100）
    index_level = (1 + ew_ret).cumprod() * 100
    # 第一天設為 100（cumprod 後第一個有值的位置）
    first_valid = index_level.first_valid_index()
    if first_valid is not None:
        scale = 100.0 / index_level[first_valid]
        index_level = index_level * scale

    member_count = aligned.notna().sum(axis=1)

    result = pd.DataFrame(
        {
            "date": index_level.index,
            "index_level": index_level.values,
            "return_1d": ew_ret.values,
            "member_count": member_count.values,
        }
    )
    result = result.dropna(subset=["index_level"])
    return result.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# MA 計算
# ─────────────────────────────────────────────────────────────────────────────

def calc_ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=max(window // 2, 5)).mean()


def calc_slope(series: pd.Series, window: int = 5) -> float:
    """計算序列最後 window 個點的斜率（線性回歸斜率除以均值，正規化）"""
    s = series.dropna()
    if len(s) < window:
        return 0.0
    y = s.iloc[-window:].values.astype(float)
    x = np.arange(window, dtype=float)
    mean_y = np.mean(y)
    if mean_y == 0:
        return 0.0
    slope = np.polyfit(x, y, 1)[0]
    return float(slope / mean_y)  # 正規化斜率


# ─────────────────────────────────────────────────────────────────────────────
# Swing High / Low 偵測
# ─────────────────────────────────────────────────────────────────────────────

def detect_swing_points(
    series: pd.Series, window: int = 10
) -> tuple[Optional[float], Optional[str], Optional[float], Optional[str]]:
    """
    偵測已確認的 Swing High / Low（左右各 window 天）。
    series：index 為日期字串，值為 close（或 high/low）
    回傳 (swing_high, swing_high_date, swing_low, swing_low_date)
    """
    s = series.dropna()
    n = len(s)
    if n < window * 2 + 1:
        return None, None, None, None

    values = s.values
    dates = list(s.index)

    # 只看 [0 : n-window]，確保右側有 window 個確認點
    confirmed_end = n - window

    swing_highs = []  # (idx, value, date)
    swing_lows = []

    for i in range(window, confirmed_end):
        left = values[i - window: i]
        right = values[i + 1: i + window + 1]
        v = values[i]
        if v >= np.max(left) and v >= np.max(right):
            swing_highs.append((i, v, dates[i]))
        if v <= np.min(left) and v <= np.min(right):
            swing_lows.append((i, v, dates[i]))

    swing_high = None
    swing_high_date = None
    if swing_highs:
        # 取最近的
        sh = swing_highs[-1]
        swing_high = float(sh[1])
        swing_high_date = str(sh[2])

    swing_low = None
    swing_low_date = None
    if swing_lows:
        sl = swing_lows[-1]
        swing_low = float(sl[1])
        swing_low_date = str(sl[2])

    return swing_high, swing_high_date, swing_low, swing_low_date


# ─────────────────────────────────────────────────────────────────────────────
# Trend State
# ─────────────────────────────────────────────────────────────────────────────

def calc_trend_state(
    index_series: pd.Series,
    ma20: float,
    ma60: float,
    ma120: float,
    ma60_slope: float,
    swing_highs: list,  # [(value, date)] 最近幾個 swing high
    swing_lows: list,   # [(value, date)] 最近幾個 swing low
) -> str:
    """
    判斷 BULL / RANGE / BEAR，使用連續確認機制（避免單日翻轉）。
    """
    if index_series.empty or pd.isna(ma20) or pd.isna(ma60):
        return "RANGE"

    last = float(index_series.iloc[-1])

    # MA 多頭排列
    ma_bullish = (
        not pd.isna(ma120)
        and ma20 > ma60 > ma120
        and ma60_slope > 0
        and last > ma20
    )
    # MA 空頭排列
    ma_bearish = (
        not pd.isna(ma120)
        and ma20 < ma60 < ma120
        and ma60_slope < 0
        and last < ma20
    )

    # HH+HL pattern（需要至少 2 個 swing）
    hh_hl = False
    ll_lh = False
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        sh_vals = [sh[0] for sh in swing_highs[-2:]]
        sl_vals = [sl[0] for sl in swing_lows[-2:]]
        hh_hl = sh_vals[1] > sh_vals[0] and sl_vals[1] > sl_vals[0]
        ll_lh = sh_vals[1] < sh_vals[0] and sl_vals[1] < sl_vals[0]

    if ma_bullish and (hh_hl or ma60_slope > 0.002):
        return "BULL"
    elif ma_bearish and (ll_lh or ma60_slope < -0.002):
        return "BEAR"
    else:
        return "RANGE"


# ─────────────────────────────────────────────────────────────────────────────
# 結構事件偵測
# ─────────────────────────────────────────────────────────────────────────────

def detect_structure_events(
    index_series: pd.Series,
    swing_high: Optional[float],
    swing_low: Optional[float],
    lookback: int = 5,
) -> tuple[Optional[str], Optional[str], Optional[float]]:
    """
    偵測最近 lookback 天內的結構事件。
    回傳 (event_type, event_date, reference_price)
    """
    if len(index_series) < lookback + 1:
        return None, None, None
    if swing_high is None or swing_low is None:
        return None, None, None

    recent = index_series.iloc[-(lookback + 3):]  # 多取幾天給 FALSE 事件判斷
    dates = list(recent.index)
    vals = recent.values

    n = len(vals)

    # 從最近往前找事件
    for i in range(n - 1, max(n - lookback - 1, 0), -1):
        c = float(vals[i])
        d = str(dates[i])

        # BREAKOUT：Close > swing_high
        if c > swing_high:
            # 確認不是 FALSE_BREAKOUT（後面沒有跌回）
            is_false = False
            if i < n - 1:
                future_closes = [float(vals[j]) for j in range(i + 1, n)]
                if any(fc < swing_high for fc in future_closes):
                    is_false = True
            if is_false:
                return "FALSE_BREAKOUT", d, swing_high
            return "BREAKOUT", d, swing_high

        # BREAKDOWN：Close < swing_low
        if c < swing_low:
            # FALSE_BREAKDOWN：T~T+2 內有 close 回到 swing_low 以上
            is_false = False
            if i < n - 1:
                future_closes = [float(vals[j]) for j in range(i + 1, min(i + 4, n))]
                if any(fc >= swing_low for fc in future_closes):
                    is_false = True
            if is_false:
                return "FALSE_BREAKDOWN", d, swing_low
            return "BREAKDOWN", d, swing_low

        # RECLAIM：前期 breakdown 後重新站回 swing_low
        if i > 0:
            prev = float(vals[i - 1])
            if prev < swing_low and c >= swing_low:
                return "RECLAIM", d, swing_low

    return None, None, None


# ─────────────────────────────────────────────────────────────────────────────
# Internal Health
# ─────────────────────────────────────────────────────────────────────────────

def calc_internal_health(
    price_dict: dict[str, pd.DataFrame],
    target_date: str,
) -> dict:
    """
    計算產業內部健康指標。
    target_date: 'YYYYMMDD'
    """
    up_count = 0
    total_count = 0
    above_ma20 = 0
    above_ma60 = 0
    up_vol = 0.0
    total_vol = 0.0
    returns_weighted = []  # (return, is_up) 供 top contribution 計算
    returns_abs = []       # (stock_id, |return|) 供 top N 貢獻計算

    for sid, df in price_dict.items():
        dates = df["date"].tolist()
        if target_date not in dates:
            continue
        idx = dates.index(target_date)
        if idx < 1:
            continue

        close_today = float(df.iloc[idx]["close"])
        close_prev = float(df.iloc[idx - 1]["close"])
        vol = float(df.iloc[idx]["volume"]) if not pd.isna(df.iloc[idx]["volume"]) else 0.0

        if close_prev <= 0:
            continue

        ret_1d = (close_today - close_prev) / close_prev
        total_count += 1

        if ret_1d > 0:
            up_count += 1
            up_vol += vol

        total_vol += vol

        # MA20 / MA60
        closes = df.iloc[: idx + 1]["close"]
        if len(closes) >= 20:
            ma20 = closes.rolling(20).mean().iloc[-1]
            if close_today > ma20:
                above_ma20 += 1
        else:
            # 不足 20 天，不計入
            pass

        if len(closes) >= 60:
            ma60 = closes.rolling(60).mean().iloc[-1]
            if close_today > ma60:
                above_ma60 += 1

        returns_abs.append((sid, abs(ret_1d), ret_1d))

    if total_count == 0:
        return {
            "breadth_up_ratio": None,
            "above_ma20_ratio": None,
            "above_ma60_ratio": None,
            "up_volume_ratio": None,
            "top3_contribution": None,
            "top10_contribution": None,
            "internal_health": "WEAK",
            "median_return_1d": None,
        }

    breadth_up_ratio = up_count / total_count
    above_ma20_ratio = above_ma20 / total_count
    above_ma60_ratio = above_ma60 / total_count
    up_volume_ratio = (up_vol / total_vol) if total_vol > 0 else 0.0

    # Top N contribution（按絕對報酬排序）
    returns_abs_sorted = sorted(returns_abs, key=lambda x: x[1], reverse=True)
    all_abs_sum = sum(x[1] for x in returns_abs) or 1e-9
    top3_contribution = sum(x[1] for x in returns_abs_sorted[:3]) / all_abs_sum
    top10_contribution = sum(x[1] for x in returns_abs_sorted[:10]) / all_abs_sum

    # 中位數報酬
    all_rets = [x[2] for x in returns_abs]
    median_ret = float(np.median(all_rets)) if all_rets else None

    # Internal health 判斷
    if breadth_up_ratio >= 0.6 and above_ma20_ratio >= 0.6 and top3_contribution < 0.5:
        health = "HEALTHY"
    elif top3_contribution >= 0.6:
        health = "CONCENTRATED"
    elif breadth_up_ratio < 0.3 and above_ma20_ratio < 0.3:
        health = "WEAK"
    elif breadth_up_ratio > above_ma60_ratio:
        health = "IMPROVING"
    elif breadth_up_ratio < above_ma60_ratio * 0.7:
        health = "DETERIORATING"
    else:
        health = "STABLE"

    return {
        "breadth_up_ratio": round(breadth_up_ratio, 4),
        "above_ma20_ratio": round(above_ma20_ratio, 4),
        "above_ma60_ratio": round(above_ma60_ratio, 4),
        "up_volume_ratio": round(up_volume_ratio, 4),
        "top3_contribution": round(top3_contribution, 4),
        "top10_contribution": round(top10_contribution, 4),
        "internal_health": health,
        "median_return_1d": round(median_ret, 6) if median_ret is not None else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Rank Trend
# ─────────────────────────────────────────────────────────────────────────────

def calc_rank_trend(
    rank_5d: Optional[int],
    rank_20d: Optional[int],
    rank_60d: Optional[int],
) -> str:
    """
    STRENGTHENING / WEAKENING / STABLE
    rank 越小越強（1=最強）
    """
    if rank_5d is None or rank_60d is None:
        return "STABLE"
    diff = rank_60d - rank_5d  # 正數 = rank 變小（變強）
    if diff >= 3:
        return "STRENGTHENING"
    elif diff <= -3:
        return "WEAKENING"
    return "STABLE"


# ─────────────────────────────────────────────────────────────────────────────
# Sector Regime & Transition
# ─────────────────────────────────────────────────────────────────────────────

def determine_sector_regime(
    trend_state: str,
    rank_5d: Optional[int],
    total_sectors: int,
) -> str:
    """
    6 種 regime：
    多頭強勢 / 多頭弱勢 / 盤整強勢 / 盤整弱勢 / 空頭抗跌 / 空頭弱勢
    """
    if total_sectors == 0 or rank_5d is None:
        return "盤整弱勢"

    pct_rank = rank_5d / total_sectors  # 0~1，越小越強
    strong = pct_rank <= 0.33
    weak = pct_rank >= 0.67

    if trend_state == "BULL":
        return "多頭強勢" if strong else "多頭弱勢"
    elif trend_state == "BEAR":
        return "空頭抗跌" if strong else "空頭弱勢"
    else:  # RANGE
        return "盤整強勢" if strong else "盤整弱勢"


def determine_transition_state(
    trend_state: str,
    rank_trend: str,
    structure_event: Optional[str],
    internal_health: str,
    rank_5d: Optional[int],
    total_sectors: int,
) -> str:
    """
    STRONG_LEADER / EMERGING_LEADER / FALSE_BREAKDOWN_TURN / LEADER_FAILURE / None
    """
    if total_sectors == 0 or rank_5d is None:
        return "None"

    pct_rank = rank_5d / total_sectors
    top_tier = pct_rank <= 0.2  # 前 20%

    if trend_state == "BULL" and top_tier and rank_trend == "STRENGTHENING":
        return "STRONG_LEADER"
    if trend_state in ("RANGE", "BEAR") and rank_trend == "STRENGTHENING" and pct_rank <= 0.4:
        if structure_event in ("FALSE_BREAKDOWN", "RECLAIM"):
            return "FALSE_BREAKDOWN_TURN"
        if internal_health in ("HEALTHY", "IMPROVING"):
            return "EMERGING_LEADER"
    if trend_state == "BULL" and rank_trend == "WEAKENING" and pct_rank >= 0.6:
        return "LEADER_FAILURE"
    return "None"


# ─────────────────────────────────────────────────────────────────────────────
# 主引擎
# ─────────────────────────────────────────────────────────────────────────────

def _calc_period_return(index_series: pd.Series, window: int) -> Optional[float]:
    """計算最近 window 天的累積報酬"""
    s = index_series.dropna()
    if len(s) < window + 1:
        return None
    v_now = float(s.iloc[-1])
    v_prev = float(s.iloc[-(window + 1)])
    if v_prev == 0:
        return None
    return (v_now - v_prev) / v_prev


def _calc_median_return(price_dict: dict[str, pd.DataFrame], window: int, target_date: str) -> Optional[float]:
    """計算各股票 window 天報酬的中位數"""
    rets = []
    for sid, df in price_dict.items():
        dates = df["date"].tolist()
        if target_date not in dates:
            continue
        idx = dates.index(target_date)
        if idx < window:
            continue
        c_now = float(df.iloc[idx]["close"])
        c_prev = float(df.iloc[idx - window]["close"])
        if c_prev > 0:
            rets.append((c_now - c_prev) / c_prev)
    if not rets:
        return None
    return float(np.median(rets))


def _load_market_index_series(sector_indices: dict[str, pd.Series]) -> pd.Series:
    """用所有產業指數的平均作為大盤代理"""
    if not sector_indices:
        return pd.Series(dtype=float)
    aligned = pd.concat(list(sector_indices.values()), axis=1)
    return aligned.mean(axis=1, skipna=True)


def run_sector_engine(days_back: int = 120) -> dict:
    """
    主要執行入口
    1. 讀所有產業的股票
    2. 計算各股票價格
    3. 計算產業指數
    4. 計算所有指標
    5. Cross-sectional ranking
    6. 寫入 sector_daily
    7. 偵測並寫入 sector_events
    """
    from .universe import get_all_sectors, get_sector_stocks, is_initialized

    if not is_initialized():
        log.warning("[engine] sector_master 為空，請先執行 fetch_and_build_mapping()")
        return {"status": "not_initialized"}

    sectors = get_all_sectors()  # {sector_id: sector_name}
    if not sectors:
        return {"status": "no_sectors"}

    log.info(f"[engine] 開始計算 {len(sectors)} 個產業，days_back={days_back}")
    t0 = time.time()

    # ── 讀所有產業股票 ────────────────────────────────────────────────────────
    # 先讀 stocks.csv 取得市場類型
    try:
        import pandas as pd
        stocks_csv = Path(__file__).parent.parent / "stocks.csv"
        stocks_df = pd.read_csv(str(stocks_csv), dtype=str, encoding="utf-8")
        market_map = dict(zip(stocks_df["stock_id"], stocks_df["type"]))
    except Exception:
        market_map = {}

    # 每個產業 → 股票清單
    sector_stocks: dict[str, list[str]] = {}
    all_stock_ids: set[str] = set()
    for sid in sectors:
        slist = get_sector_stocks(sid)
        if slist:
            sector_stocks[sid] = slist
            all_stock_ids.update(slist)

    log.info(f"[engine] 共 {len(all_stock_ids)} 支股票需要載入價格")

    # ── 批次載入所有股票價格（帶快取）────────────────────────────────────────
    global _PRICE_CACHE_TS
    price_data: dict[str, pd.DataFrame] = {}
    loaded = 0
    failed = 0
    for stock_id in sorted(all_stock_ids):
        mkt = market_map.get(stock_id, "twse")
        df = load_stock_prices(stock_id, market=mkt, min_dates=60)
        if df is not None:
            price_data[stock_id] = df
            loaded += 1
        else:
            failed += 1
        # 避免太快打 Yahoo（每 20 支小延遲）
        if (loaded + failed) % 20 == 0:
            time.sleep(0.5)

    _PRICE_CACHE_TS = time.time()
    log.info(f"[engine] 價格載入完成：成功={loaded}，失敗={failed}")

    # ── 計算各產業指數 ────────────────────────────────────────────────────────
    sector_index_series: dict[str, pd.Series] = {}  # sector_id → index_level series
    sector_index_df: dict[str, pd.DataFrame] = {}

    for sector_id in sector_stocks:
        slist = sector_stocks[sector_id]
        p_dict = {sid: price_data[sid] for sid in slist if sid in price_data}
        if len(p_dict) < 2:
            continue
        idx_df = calc_sector_index(p_dict, lookback=max(days_back + 60, 250))
        if idx_df.empty:
            continue
        sector_index_df[sector_id] = idx_df
        level_series = idx_df.set_index("date")["index_level"]
        sector_index_series[sector_id] = level_series

    log.info(f"[engine] 成功計算指數的產業：{len(sector_index_series)} 個")

    # ── 大盤代理（所有產業等權平均）──────────────────────────────────────────
    market_proxy = _load_market_index_series(sector_index_series)

    # ── 決定要計算的日期範圍 ──────────────────────────────────────────────────
    cutoff_date = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")

    # ── 對每個產業每個日期計算所有指標 ───────────────────────────────────────
    all_rows: list[dict] = []
    all_events: list[dict] = []
    today_str = date.today().strftime("%Y%m%d")

    for sector_id, level_series in sector_index_series.items():
        # 過濾日期範圍
        dates_in_range = [d for d in level_series.index if d >= cutoff_date]
        if not dates_in_range:
            continue

        # 完整 series（含歷史，用於 MA 計算）
        full_series = level_series

        # MA 系列（在完整 series 上計算）
        ma20_series = calc_ma(full_series, 20)
        ma60_series = calc_ma(full_series, 60)
        ma120_series = calc_ma(full_series, 120)

        # Swing 偵測（用完整 series）
        sh_val, sh_date, sl_val, sl_date = detect_swing_points(full_series, window=10)

        # 累積 swing 點清單（供 trend_state 用）
        _sh_list, _sl_list = [], []
        s_vals = full_series.values
        s_dates = list(full_series.index)
        n = len(s_vals)
        win = 10
        for i in range(win, n - win):
            left = s_vals[i - win: i]
            right = s_vals[i + 1: i + win + 1]
            v = s_vals[i]
            if v >= np.max(left) and v >= np.max(right):
                _sh_list.append((float(v), s_dates[i]))
            if v <= np.min(left) and v <= np.min(right):
                _sl_list.append((float(v), s_dates[i]))

        # 取得該產業的股票 price_dict
        p_dict_sector = {
            sid: price_data[sid]
            for sid in sector_stocks.get(sector_id, [])
            if sid in price_data
        }

        # 對 target_date = 最新一天（計算最節省）
        # 但我們要計算 days_back 天，所以逐日計算
        for target_date in dates_in_range:
            # 截到 target_date 的 series
            partial = full_series[full_series.index <= target_date]
            if len(partial) < 20:
                continue

            last_val = float(partial.iloc[-1])

            # MA values for target_date
            ma20_val = ma20_series.get(target_date)
            ma60_val = ma60_series.get(target_date)
            ma120_val = ma120_series.get(target_date)

            ma20_f = float(ma20_val) if ma20_val is not None and not pd.isna(ma20_val) else None
            ma60_f = float(ma60_val) if ma60_val is not None and not pd.isna(ma60_val) else None
            ma120_f = float(ma120_val) if ma120_val is not None and not pd.isna(ma120_val) else None

            # MA slopes
            ma20_slope = calc_slope(ma20_series[ma20_series.index <= target_date], 5)
            ma60_slope = calc_slope(ma60_series[ma60_series.index <= target_date], 5)

            # Trend state
            sh_list_before = [x for x in _sh_list if x[1] <= target_date]
            sl_list_before = [x for x in _sl_list if x[1] <= target_date]
            trend_state = calc_trend_state(
                partial, ma20_f or last_val, ma60_f or last_val, ma120_f or last_val,
                ma60_slope, sh_list_before, sl_list_before
            )

            # Period returns
            ret_1d = _calc_period_return(partial, 1)
            ret_5d = _calc_period_return(partial, 5)
            ret_20d = _calc_period_return(partial, 20)
            ret_60d = _calc_period_return(partial, 60)

            # Median returns
            med_1d = _calc_median_return(p_dict_sector, 1, target_date)
            med_5d = _calc_median_return(p_dict_sector, 5, target_date)
            med_20d = _calc_median_return(p_dict_sector, 20, target_date)
            med_60d = _calc_median_return(p_dict_sector, 60, target_date)

            # Swing（截至 target_date）
            partial_sh, partial_shd, partial_sl, partial_sld = detect_swing_points(
                partial, window=10
            )

            # Structure events
            ev_type, ev_date, ev_ref = detect_structure_events(
                partial, partial_sh, partial_sl, lookback=5
            )

            # Internal health（只對最新日計算，歷史日跳過以省時）
            if target_date == dates_in_range[-1]:
                health_dict = calc_internal_health(p_dict_sector, target_date)
            else:
                health_dict = {
                    "breadth_up_ratio": None,
                    "above_ma20_ratio": None,
                    "above_ma60_ratio": None,
                    "up_volume_ratio": None,
                    "top3_contribution": None,
                    "top10_contribution": None,
                    "internal_health": None,
                    "median_return_1d": None,
                }

            # Stock count
            idx_df_ref = sector_index_df.get(sector_id)
            if idx_df_ref is not None:
                row_ref = idx_df_ref[idx_df_ref["date"] == target_date]
                stock_count = int(row_ref.iloc[0]["member_count"]) if not row_ref.empty else len(p_dict_sector)
            else:
                stock_count = len(p_dict_sector)

            row = {
                "observation_date": target_date,
                "sector_id": sector_id,
                "stock_count": stock_count,
                "index_level": round(last_val, 4),
                "return_ew_1d": round(ret_1d, 6) if ret_1d is not None else None,
                "return_ew_5d": round(ret_5d, 6) if ret_5d is not None else None,
                "return_ew_20d": round(ret_20d, 6) if ret_20d is not None else None,
                "return_ew_60d": round(ret_60d, 6) if ret_60d is not None else None,
                "return_median_1d": round(med_1d, 6) if med_1d is not None else None,
                "return_median_5d": round(med_5d, 6) if med_5d is not None else None,
                "return_median_20d": round(med_20d, 6) if med_20d is not None else None,
                "return_median_60d": round(med_60d, 6) if med_60d is not None else None,
                "ma20": round(ma20_f, 4) if ma20_f is not None else None,
                "ma60": round(ma60_f, 4) if ma60_f is not None else None,
                "ma120": round(ma120_f, 4) if ma120_f is not None else None,
                "ma20_slope": round(ma20_slope, 6),
                "ma60_slope": round(ma60_slope, 6),
                "swing_high": round(partial_sh, 4) if partial_sh is not None else None,
                "swing_low": round(partial_sl, 4) if partial_sl is not None else None,
                "swing_high_date": partial_shd,
                "swing_low_date": partial_sld,
                "trend_state": trend_state,
                # rank 留後面 cross-sectional 填入
                "relative_rank_5d": None,
                "relative_rank_20d": None,
                "relative_rank_60d": None,
                "rank_change_5d": None,
                "rank_change_20d": None,
                "rank_trend": None,
                "market_relative_5d": None,
                "market_relative_20d": None,
                "market_relative_60d": None,
                "breadth_up_ratio": health_dict["breadth_up_ratio"],
                "above_ma20_ratio": health_dict["above_ma20_ratio"],
                "above_ma60_ratio": health_dict["above_ma60_ratio"],
                "median_return_1d": health_dict["median_return_1d"],
                "up_volume_ratio": health_dict["up_volume_ratio"],
                "top3_contribution": health_dict["top3_contribution"],
                "top10_contribution": health_dict["top10_contribution"],
                "internal_health": health_dict["internal_health"],
                "structure_event": ev_type,
                "structure_event_date": ev_date,
                "structure_reference_price": round(ev_ref, 4) if ev_ref is not None else None,
                "sector_regime": None,
                "transition_state": None,
            }
            all_rows.append(row)

            # 收集結構事件
            if ev_type and target_date == dates_in_range[-1]:
                all_events.append({
                    "observation_date": target_date,
                    "sector_id": sector_id,
                    "event_type": ev_type,
                    "reference_price": round(ev_ref, 4) if ev_ref is not None else None,
                    "event_price": round(last_val, 4),
                    "event_strength": "MEDIUM",
                    "confirmation_status": "PENDING",
                    "created_at": datetime.now().isoformat(),
                })

    # ── Cross-sectional ranking（按日期分組）────────────────────────────────
    log.info(f"[engine] 共 {len(all_rows)} 列資料，開始 cross-sectional ranking")

    # 按 observation_date 分組，對每天做 ranking
    from collections import defaultdict
    date_groups: dict[str, list[dict]] = defaultdict(list)
    for row in all_rows:
        date_groups[row["observation_date"]].append(row)

    # 歷史 rank（用於 rank_change）
    prev_ranks_5d: dict[str, int] = {}  # {sector_id: rank}
    prev_ranks_20d: dict[str, int] = {}

    for obs_date in sorted(date_groups.keys()):
        group = date_groups[obs_date]
        total = len(group)
        if total == 0:
            continue

        # 5d ranking
        rank5_list = sorted(
            [r for r in group if r["return_ew_5d"] is not None],
            key=lambda x: x["return_ew_5d"],
            reverse=True,
        )
        for i, r in enumerate(rank5_list):
            r["relative_rank_5d"] = i + 1

        # 20d ranking
        rank20_list = sorted(
            [r for r in group if r["return_ew_20d"] is not None],
            key=lambda x: x["return_ew_20d"],
            reverse=True,
        )
        for i, r in enumerate(rank20_list):
            r["relative_rank_20d"] = i + 1

        # 60d ranking
        rank60_list = sorted(
            [r for r in group if r["return_ew_60d"] is not None],
            key=lambda x: x["return_ew_60d"],
            reverse=True,
        )
        for i, r in enumerate(rank60_list):
            r["relative_rank_60d"] = i + 1

        # rank_change（vs 前一個有 rank 的日期）
        for r in group:
            sid = r["sector_id"]
            if r["relative_rank_5d"] is not None and sid in prev_ranks_5d:
                r["rank_change_5d"] = prev_ranks_5d[sid] - r["relative_rank_5d"]
            if r["relative_rank_20d"] is not None and sid in prev_ranks_20d:
                r["rank_change_20d"] = prev_ranks_20d[sid] - r["relative_rank_20d"]

            r["rank_trend"] = calc_rank_trend(
                r["relative_rank_5d"], r["relative_rank_20d"], r["relative_rank_60d"]
            )

            # Market relative
            if market_proxy is not None and not market_proxy.empty:
                mkt_5d = _calc_period_return(
                    market_proxy[market_proxy.index <= obs_date], 5
                )
                mkt_20d = _calc_period_return(
                    market_proxy[market_proxy.index <= obs_date], 20
                )
                mkt_60d = _calc_period_return(
                    market_proxy[market_proxy.index <= obs_date], 60
                )
                r["market_relative_5d"] = (
                    round(r["return_ew_5d"] - mkt_5d, 6)
                    if r["return_ew_5d"] is not None and mkt_5d is not None
                    else None
                )
                r["market_relative_20d"] = (
                    round(r["return_ew_20d"] - mkt_20d, 6)
                    if r["return_ew_20d"] is not None and mkt_20d is not None
                    else None
                )
                r["market_relative_60d"] = (
                    round(r["return_ew_60d"] - mkt_60d, 6)
                    if r["return_ew_60d"] is not None and mkt_60d is not None
                    else None
                )

            # Regime & Transition
            r["sector_regime"] = determine_sector_regime(
                r["trend_state"], r["relative_rank_5d"], total
            )
            r["transition_state"] = determine_transition_state(
                r["trend_state"],
                r["rank_trend"],
                r["structure_event"],
                r["internal_health"] or "STABLE",
                r["relative_rank_5d"],
                total,
            )

        # 更新 prev_ranks
        for r in group:
            sid = r["sector_id"]
            if r["relative_rank_5d"] is not None:
                prev_ranks_5d[sid] = r["relative_rank_5d"]
            if r["relative_rank_20d"] is not None:
                prev_ranks_20d[sid] = r["relative_rank_20d"]

    # ── 寫入 DB ────────────────────────────────────────────────────────────────
    log.info(f"[engine] 寫入 sector_daily：{len(all_rows)} 列")
    with db() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO sector_daily (
                observation_date, sector_id, stock_count, index_level,
                return_ew_1d, return_ew_5d, return_ew_20d, return_ew_60d,
                return_median_1d, return_median_5d, return_median_20d, return_median_60d,
                ma20, ma60, ma120, ma20_slope, ma60_slope,
                swing_high, swing_low, swing_high_date, swing_low_date,
                trend_state, relative_rank_5d, relative_rank_20d, relative_rank_60d,
                rank_change_5d, rank_change_20d, rank_trend,
                market_relative_5d, market_relative_20d, market_relative_60d,
                breadth_up_ratio, above_ma20_ratio, above_ma60_ratio,
                median_return_1d, up_volume_ratio,
                top3_contribution, top10_contribution, internal_health,
                structure_event, structure_event_date, structure_reference_price,
                sector_regime, transition_state
            ) VALUES (
                :observation_date, :sector_id, :stock_count, :index_level,
                :return_ew_1d, :return_ew_5d, :return_ew_20d, :return_ew_60d,
                :return_median_1d, :return_median_5d, :return_median_20d, :return_median_60d,
                :ma20, :ma60, :ma120, :ma20_slope, :ma60_slope,
                :swing_high, :swing_low, :swing_high_date, :swing_low_date,
                :trend_state, :relative_rank_5d, :relative_rank_20d, :relative_rank_60d,
                :rank_change_5d, :rank_change_20d, :rank_trend,
                :market_relative_5d, :market_relative_20d, :market_relative_60d,
                :breadth_up_ratio, :above_ma20_ratio, :above_ma60_ratio,
                :median_return_1d, :up_volume_ratio,
                :top3_contribution, :top10_contribution, :internal_health,
                :structure_event, :structure_event_date, :structure_reference_price,
                :sector_regime, :transition_state
            )
            """,
            all_rows,
        )

        # 寫入 sector_events（只寫最新日的）
        if all_events:
            conn.executemany(
                """
                INSERT OR IGNORE INTO sector_events (
                    observation_date, sector_id, event_type,
                    reference_price, event_price, event_strength,
                    confirmation_status, created_at
                ) VALUES (
                    :observation_date, :sector_id, :event_type,
                    :reference_price, :event_price, :event_strength,
                    :confirmation_status, :created_at
                )
                """,
                all_events,
            )

        # 更新 meta
        conn.execute(
            "INSERT OR REPLACE INTO sector_meta (key, value) VALUES ('last_run', ?)",
            (datetime.now().isoformat(),),
        )

    elapsed = round(time.time() - t0, 1)
    log.info(f"[engine] 完成！耗時 {elapsed}s，寫入 {len(all_rows)} 列")
    return {
        "status": "ok",
        "sectors": len(sector_index_series),
        "rows": len(all_rows),
        "events": len(all_events),
        "elapsed": elapsed,
    }
