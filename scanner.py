"""
scanner.py - 策略選股引擎
S1多、S1空、S1.2、S2(W底)、S5(站上均線)、S17a、S17b、S10(漲停)、CHIP(主力)
"""
import math

import pandas as pd


def _tick_size(price: float) -> float:
    """台股最小升降單位"""
    if price < 10:    return 0.01
    if price < 50:    return 0.05
    if price < 100:   return 0.10
    if price < 500:   return 0.50
    if price < 1000:  return 1.00
    return 5.00


def _limit_up_price(prev_close: float) -> float:
    """
    計算台股漲停價：前收 × 1.1，依「計算後價格所在區間」的 tick 向下取整。
    例：前收 9.92 → 10.912 → 落在 10~50 區間 tick=0.05 → 10.90
    例：前收 10.25 → 11.275 → tick=0.05 → 11.25
    """
    raw  = prev_close * 1.10
    tick = _tick_size(raw)
    return round(math.floor(raw / tick) * tick, 6)

STRATEGIES = {
    "S1":       "雙MACD選股（多）",
    "S_FBD":    "假跌破買進",           # 移至第 2 — 用戶常在 K 線看到此標記
    "S1_SHORT": "雙MACD選股（空）",

    "S2":       "W底（碗公底・不破前低・盤整後再攻擊）",
    "S5":       "站上均線做多",
    "S10":      "漲停",


    "S_WARRANT_TOP": "認購權證前十大（昨日）",
    "S_THUNDER":    "平地一聲雷（長期盤整後帶量突破）",
    "S_XIANREN":    "仙人指路（盤整→上攻收長上影線→再盤整→第二次出量）",
}

STRATEGY_PARAMS_SCHEMA = {
    "S1": [
        {"key": "min_price",        "label": "最低股價",             "type": "number", "default": 10,  "min": 1,   "max": 500,  "step": 1},
        {"key": "osc_lookback",     "label": "OSC局部谷底回溯天數",   "type": "number", "default": 12,  "min": 5,   "max": 30,   "step": 1},
        {"key": "close_lookback",   "label": "近期低點回溯天數",       "type": "number", "default": 10,  "min": 3,   "max": 20,   "step": 1},
    ],
    "S1_SHORT": [
        {"key": "min_price",        "label": "最低股價",             "type": "number", "default": 10,  "min": 1,   "max": 500,  "step": 1},
        {"key": "osc_lookback",     "label": "OSC局部頂部回溯天數",   "type": "number", "default": 12,  "min": 5,   "max": 30,   "step": 1},
        {"key": "close_lookback",   "label": "近期高點回溯天數",       "type": "number", "default": 10,  "min": 3,   "max": 20,   "step": 1},
    ],

    "S2": [
        {"key": "min_price",        "label": "最低股價",             "type": "number", "default": 10,  "min": 1,   "max": 500,  "step": 1},
        {"key": "min_vol_lots",     "label": "最低量（張）",          "type": "number", "default": 300, "min": 0,   "max": 5000, "step": 50},
        {"key": "bowl_days",        "label": "前低（碗底）＝第一波高點前幾天內的最低點", "type": "number", "default": 60, "min": 20, "max": 250, "step": 10},
        {"key": "wave_pct",         "label": "第一波漲幅至少%",       "type": "number", "default": 10,  "min": 3,   "max": 50,   "step": 1},
        {"key": "min_base",         "label": "盤整至少幾天",          "type": "number", "default": 3,   "min": 2,   "max": 15,   "step": 1},
        {"key": "max_base",         "label": "盤整最多幾天",          "type": "number", "default": 20,  "min": 5,   "max": 60,   "step": 1},
    ],
    "S5": [
        {"key": "min_price",        "label": "最低股價",             "type": "number", "default": 10,  "min": 1,   "max": 500,  "step": 1},
        {"key": "min_vol_lots",     "label": "最低量（張）",          "type": "number", "default": 0,   "min": 0,   "max": 5000, "step": 50},
        {"key": "vol_mult",         "label": "今日量 ≥ 昨日量×幾倍",   "type": "number", "default": 3,   "min": 0,   "max": 10,   "step": 0.5},
    ],
    "S10": [],
    "S_FBD": [
        {"key": "min_price",        "label": "最低股價",             "type": "number", "default": 10,  "min": 1,   "max": 500,  "step": 1},
        {"key": "min_vol_lots",     "label": "最低量（張）",          "type": "number", "default": 300, "min": 0,   "max": 5000, "step": 50},
        {"key": "break_window",     "label": "跌破MA10回溯天數",      "type": "number", "default": 4,   "min": 1,   "max": 10,   "step": 1},
        {"key": "break_vol_ratio",  "label": "跌破當天量≤均量×幾倍",  "type": "number", "default": 2.5, "min": 1,   "max": 5,    "step": 0.5},
        {"key": "vol_ref_days",     "label": "均量參考天數",          "type": "number", "default": 20,  "min": 5,   "max": 60,   "step": 5},
        {"key": "macd_ref_days",    "label": "MACD綠柱縮短比較天數",  "type": "number", "default": 3,   "min": 1,   "max": 8,    "step": 1},
    ],
    "S_THUNDER": [
        {"key": "min_price",       "label": "最低股價",                 "type": "number", "default": 10,   "min": 1,   "max": 500, "step": 1},
        {"key": "base_days",       "label": "盤整天數（≥）",             "type": "number", "default": 90,   "min": 30,  "max": 250, "step": 5},
        {"key": "base_range",      "label": "盤整區間（收盤高低差 %）",   "type": "number", "default": 15,   "min": 5,   "max": 40,  "step": 1},
        {"key": "vol_mult",        "label": "突破量（20 日均量倍數 ≥）",  "type": "number", "default": 2.5,  "min": 1.5, "max": 10,  "step": 0.5},
        {"key": "max_retrace",     "label": "回檔上限（第一段漲幅比例）", "type": "number", "default": 0.618,"min": 0.3, "max": 1,   "step": 0.01},
        {"key": "breakout_within", "label": "突破發生在近幾天內",         "type": "number", "default": 30,   "min": 1,   "max": 120, "step": 1},
    ],
    "S_XIANREN": [
        {"key": "min_price",    "label": "最低股價",                         "type": "number", "default": 10,  "min": 1,   "max": 500,  "step": 1},
        {"key": "min_vol_lots", "label": "今天最低量（張）",                  "type": "number", "default": 300, "min": 0,   "max": 5000, "step": 50},
        {"key": "box_days",     "label": "上攻前盤整天數",                    "type": "number", "default": 15,  "min": 5,   "max": 60,   "step": 1},
        {"key": "box_range",    "label": "盤整區間（收盤高低差 %）≤",          "type": "number", "default": 15,  "min": 5,   "max": 40,   "step": 1},
        {"key": "attack_max",   "label": "盤整結束到仙人指路最多幾天（上攻）",   "type": "number", "default": 5,   "min": 0,   "max": 15,   "step": 1},
        {"key": "sh_body",      "label": "上影線 ≥ 實體幾倍",                 "type": "number", "default": 1.5, "min": 0.5, "max": 5,    "step": 0.5},
        {"key": "sh_range",     "label": "上影線佔整根 K 棒 % ≥",             "type": "number", "default": 40,  "min": 10,  "max": 90,   "step": 5},
        {"key": "sh_min",       "label": "上影線長度 ≥ 股價 %",               "type": "number", "default": 2,   "min": 0,   "max": 10,   "step": 0.5},
        {"key": "probe_vol",    "label": "仙人指路量 ≥ 20 日均量幾倍（第一次出量）", "type": "number", "default": 2, "min": 1, "max": 10, "step": 0.5},
        {"key": "min_pause",    "label": "之後盤整至少幾天",                  "type": "number", "default": 1,   "min": 1,   "max": 10,   "step": 1},
        {"key": "max_pause",    "label": "之後盤整最多幾天",                  "type": "number", "default": 10,  "min": 1,   "max": 30,   "step": 1},
        {"key": "today_vol",    "label": "今天量 ≥ 20 日均量幾倍（第二次出量）", "type": "number", "default": 1.5, "min": 1, "max": 10, "step": 0.1},
    ],



    "S_WARRANT_TOP": [
        {"key": "limit",     "label": "取前N支",  "type": "number", "default": 10, "min": 3, "max": 30, "step": 1},
        {"key": "min_price", "label": "最低股價",  "type": "number", "default": 10, "min": 1, "max": 500, "step": 1},
    ],
}

def calc_macd(series: pd.Series, fast: int, slow: int, signal: int):
    """回傳 (dif, dea, osc)"""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea, dif - dea

def calc_ma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()

def calc_bb_score(df: pd.DataFrame, period: int = 20) -> float:
    """
    布林軌道分級：上軌~中軌 +10~0，中軌~下軌 0~-10
    score = (close - MA20) / (2σ) × 10，夾在 [-10, 10]
    """
    if len(df) < period:
        return 0.0
    closes = df['close']
    ma  = closes.rolling(period).mean().iloc[-1]
    std = closes.rolling(period).std(ddof=0).iloc[-1]
    if pd.isna(ma) or pd.isna(std) or std == 0:
        return 0.0
    score = (float(closes.iloc[-1]) - float(ma)) / (2 * float(std)) * 10
    return round(score, 1)

def find_local_minima(arr, window: int = 3) -> list:
    mins = []
    for i in range(window, len(arr) - window):
        if arr[i] <= min(arr[max(0, i - window):i]) and arr[i] <= min(arr[i + 1:i + window + 1]):
            mins.append(i)
    return mins

def find_double_bottom(df: pd.DataFrame, lookback: int = 60, tol: float = 0.08):
    """找 W 底形態，回傳 dict 或 None"""
    closes = df['close'].values
    n = len(closes)
    if n < lookback + 5:
        return None
    sub = closes[-lookback:]
    local_mins = find_local_minima(sub, window=3)
    if len(local_mins) < 2:
        return None
    w1_i, w2_i = local_mins[-2], local_mins[-1]
    w1_low, w2_low = sub[w1_i], sub[w2_i]
    if w1_low <= 0:
        return None
    if abs(w2_low - w1_low) / w1_low > tol:
        return None
    if w2_i <= w1_i + 2:
        return None
    neckline = float(sub[w1_i:w2_i + 1].max())
    df_sub = df.iloc[-lookback:].reset_index(drop=True)
    return {
        "wave1_idx": w1_i, "wave2_idx": w2_i,
        "wave1_low": float(w1_low), "wave2_low": float(w2_low),
        "neckline": neckline, "df_sub": df_sub,
    }

def _name(sid, names):
    return (names or {}).get(sid, "")

def _change_pct(df: pd.DataFrame) -> float:
    if len(df) < 2:
        return 0.0
    prev = float(df.iloc[-2]['close'])
    if prev <= 0:
        return 0.0
    return round((float(df.iloc[-1]['close']) - prev) / prev * 100, 2)

def _vol_ratio(df: pd.DataFrame):
    """今日量 / 昨日量，供前端標示量能倍數"""
    vol_col = "volume" if "volume" in df.columns else "Volume"
    if vol_col not in df.columns or len(df) < 2:
        return None
    v_today = float(df.iloc[-1].get(vol_col) or 0)
    v_prev  = float(df.iloc[-2].get(vol_col) or 0)
    if v_prev <= 0:
        return None
    return round(v_today / v_prev, 1)

def classify_stage(df: pd.DataFrame) -> dict:
    """
    根據日線資料自動判斷股票所在操作階段。
    需要至少 60 天資料（MA60）。
    回傳 {code, label, color, desc}
    """
    STAGE_UNKNOWN = {"code": "unknown", "label": "資料不足", "color": "muted",
                     "desc": "歷史資料不足，無法判斷趨勢"}
    if df is None or len(df) < 60:
        return STAGE_UNKNOWN

    closes = df["close"]
    lows   = df["low"]
    highs  = df["high"]

    ma10 = closes.rolling(10, min_periods=10).mean()
    ma60 = closes.rolling(60, min_periods=60).mean()

    m10 = float(ma10.iloc[-1])
    m60 = float(ma60.iloc[-1])
    if pd.isna(m10) or pd.isna(m60):
        return STAGE_UNKNOWN

    today_close = float(closes.iloc[-1])
    today_open  = float(df.iloc[-1]["open"])

    # ── 1. 空頭觀望 ─────────────────────────────────────────────────────
    if m10 < m60:
        return {"code": "bearish", "label": "🟢 空頭", "color": "green",
                "desc": "MA10 < MA60 均線空頭排列，不操作"}

    # ── 以下皆為 MA10 > MA60 多頭區間 ────────────────────────────────────

    # ── 2. 假跌破：近1~4天收盤跌破MA10，今日站回且收紅 ───────────────────
    today_is_red = today_close > today_open
    for i in range(1, 5):
        if i + 1 > len(closes):
            break
        past_close = float(closes.iloc[-(i + 1)])
        past_m10   = float(ma10.iloc[-(i + 1)])
        if pd.isna(past_m10):
            break
        if past_close < past_m10:          # 那天跌破MA10
            if today_close > m10 and today_is_red:
                return {"code": "fbd", "label": "🪤 假跌破", "color": "gold",
                        "desc": f"{i}天前跌破MA10今日站回，洗盤訊號，可試單，停損前低"}
            break                          # 跌破但今日未站回，不繼續找

    # ── 3. 拉回買點：MA10斜率向上 + 近5天低點碰MA10 + 今日站回 ────────────
    if len(ma10) >= 5 and not pd.isna(ma10.iloc[-5]):
        ma10_rising = float(ma10.iloc[-1]) > float(ma10.iloc[-5])
        if ma10_rising:
            touched = any(
                float(lows.iloc[-(i + 1)]) <= float(ma10.iloc[-(i + 1)]) * 1.02
                for i in range(5) if i + 1 <= len(lows) and not pd.isna(ma10.iloc[-(i + 1)])
            )
            if touched and today_close > m10:
                return {"code": "pullback", "label": "🎯 拉回買點", "color": "red",
                        "desc": "回測MA10後站回，均線向上，等K線確認後買進"}

    # ── 4. 強勢攻擊中：近10天漲>15% 或近5天有漲停，且仍在高位 ─────────────
    if len(closes) >= 20:
        high20    = float(highs.iloc[-20:].max())
        close10   = float(closes.iloc[-10]) if len(closes) >= 10 else today_close
        gain10pct = (today_close - close10) / close10 * 100 if close10 > 0 else 0
        has_limit = any(
            len(closes) >= i + 2 and float(closes.iloc[-(i + 1)]) / float(closes.iloc[-(i + 2)]) - 1 > 0.09
            for i in range(5)
        )
        if (gain10pct > 15 or has_limit) and today_close >= high20 * 0.90:
            return {"code": "attack", "label": "🚀 強勢攻擊", "color": "blue",
                    "desc": "攻擊進行中，不要追，等中繼整理後再找買點"}

    # ── 5. 剛翻多（黃金交叉）：MA10在近10天內由下穿越MA60 ──────────────────
    for i in range(1, 11):
        if i + 1 > len(ma10) or pd.isna(ma10.iloc[-(i + 1)]) or pd.isna(ma60.iloc[-(i + 1)]):
            break
        if float(ma10.iloc[-(i + 1)]) < float(ma60.iloc[-(i + 1)]):
            return {"code": "golden", "label": "🟡 剛翻多", "color": "yellow",
                    "desc": "近期黃金交叉，等第一段確認後找拉回，不追第一段"}

    # ── 6. 中繼整理：近8天高低振幅 < 6% ────────────────────────────────────
    if len(df) >= 8:
        h8 = float(highs.iloc[-8:].max())
        l8 = float(lows.iloc[-8:].min())
        if l8 > 0 and (h8 - l8) / l8 * 100 < 6:
            rng = round((h8 - l8) / l8 * 100, 1)
            return {"code": "consol", "label": "📦 中繼整理", "color": "gray",
                    "desc": f"近8日震幅{rng}%，等待突破方向，突破需帶量"}

    # ── 7. 多頭延續 ──────────────────────────────────────────────────────
    return {"code": "bull", "label": "📈 多頭延續", "color": "cyan",
            "desc": "多頭排列走勢穩定，等待拉回至MA10附近的買點"}


def screen_s1(prices: dict, names: dict = None, params: dict = None) -> list:
    """
    S1 雙MACD選股（多）
    條件：
    1. 收盤 > 10
    2. 今日紅K（close > open）
    3. 小MACD(12,26,9)：DIF > 0、DEA > 0、OSC < 0
    4. 昨日 OSC1 為近5~20天局部谷底（前一天比昨天大 OR 昨天是近10天最低）
    5. 今日 |OSC1| < 昨日 |OSC1|（柱子開始縮短，從谷底反轉）
    6. 大MACD(108,216,18)：DIF2 > 0、DEA2 > 0、OSC2 > 0（需 2y 資料才可靠）
    7. 收盤 ≥ 近10天最低收盤
    """
    p = params or {}
    min_price     = p.get("min_price", 10)
    osc_lookback  = int(p.get("osc_lookback", 12))
    close_lookback = int(p.get("close_lookback", 10))
    results = []
    for sid, df in prices.items():
        if len(df) < 235:
            continue
        closes = df['close']
        dif1, dea1, osc1 = calc_macd(closes, 12, 26, 9)
        dif2, dea2, osc2 = calc_macd(closes, 108, 216, 18)
        today = df.iloc[-1]
        if float(today['close']) <= min_price:
            continue
        if pd.isna(today.get('open')) or float(today['close']) <= float(today['open']):
            continue
        if dif1.iloc[-1] <= 0 or dea1.iloc[-1] <= 0:
            continue
        if osc1.iloc[-1] >= 0:
            continue
        if len(osc1) < 22:
            continue
        # 昨日是局部谷底：昨天比前天低（或昨天是近N天最低）
        osc_prev2 = osc1.iloc[-3]   # 前天
        osc_prev1 = osc1.iloc[-2]   # 昨天
        is_local_min = (osc_prev1 < osc_prev2) or (osc_prev1 <= osc1.iloc[-(osc_lookback+1):-1].min() + 1e-9)
        if not is_local_min:
            continue
        # 今日 OSC 絕對值比昨日小（柱子縮短，確認反轉）
        if abs(osc1.iloc[-1]) >= abs(osc_prev1):
            continue
        if dif2.iloc[-1] <= 0 or dea2.iloc[-1] <= 0 or osc2.iloc[-1] <= 0:
            continue
        if float(today['close']) < float(closes.iloc[-(close_lookback+1):-1].min()):
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2),
                        "change_pct": _change_pct(df),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S1"})
    return results

def screen_s1_short(prices: dict, names: dict = None, params: dict = None) -> list:
    """S1空 雙MACD選股（空）"""
    p = params or {}
    min_price      = p.get("min_price", 10)
    osc_lookback   = int(p.get("osc_lookback", 12))
    close_lookback = int(p.get("close_lookback", 10))
    results = []
    for sid, df in prices.items():
        if len(df) < 235:
            continue
        closes = df['close']
        dif1, dea1, osc1 = calc_macd(closes, 12, 26, 9)
        dif2, dea2, osc2 = calc_macd(closes, 108, 216, 18)
        today = df.iloc[-1]
        if float(today['close']) <= min_price:
            continue
        if pd.isna(today.get('open')) or float(today['close']) >= float(today['open']):
            continue
        if dif1.iloc[-1] >= 0 or dea1.iloc[-1] >= 0:
            continue
        if osc1.iloc[-1] <= 0:
            continue
        if len(osc1) < 22:
            continue
        osc_prev2 = osc1.iloc[-3]
        osc_prev1 = osc1.iloc[-2]
        # 昨日是局部頂部：昨天比前天高（或昨天是近N天最高）
        is_local_max = (osc_prev1 > osc_prev2) or (osc_prev1 >= osc1.iloc[-(osc_lookback+1):-1].max() - 1e-9)
        if not is_local_max:
            continue
        if abs(osc1.iloc[-1]) >= abs(osc_prev1):
            continue
        if dif2.iloc[-1] >= 0 or dea2.iloc[-1] >= 0 or osc2.iloc[-1] >= 0:
            continue
        if float(today['close']) > float(closes.iloc[-(close_lookback+1):-1].max()):
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2),
                        "change_pct": _change_pct(df),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S1_SHORT"})
    return results

def screen_s1_2(prices: dict, names: dict = None, params: dict = None) -> list:
    """S1.2 MACD延伸（創新高拉回）"""
    p = params or {}
    min_price       = p.get("min_price", 10)
    new_high_window = int(p.get("new_high_window", 20))
    min_vol_lots    = p.get("min_vol_lots", 0)
    results = []
    for sid, df in prices.items():
        if len(df) < 70:
            continue
        closes = df['close']
        dif1, dea1, osc1 = calc_macd(closes, 12, 26, 9)
        today = df.iloc[-1]
        if float(today['close']) <= min_price:
            continue
        vol = float(today.get('volume', 0) or 0)
        if min_vol_lots > 0 and vol < min_vol_lots:
            continue
        if dif1.iloc[-1] <= 0 or dea1.iloc[-1] <= 0:
            continue
        if (dif1.iloc[-new_high_window:] <= 0).any():
            continue
        if osc1.iloc[-1] >= 0:
            continue
        if len(closes) < new_high_window * 3 + 5:
            continue
        prior_high  = float(closes.iloc[-(new_high_window*3+5):-new_high_window].max())
        recent_high = float(closes.iloc[-new_high_window:].max())
        if recent_high <= prior_high:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2),
                        "change_pct": _change_pct(df),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S1_2"})
    return results

def screen_s2(prices: dict, names: dict = None, params: dict = None) -> list:
    """
    S2 W底（碗公底）：不破前低、第一波攻擊後盤整幾天再攻擊（2026-10-06 用戶重新定義，取代「跌破前低又收回」的騙線版）
    用戶：「我要的是 W 底，然後不可以破前低的股票，整體走勢要好，碗公底，10>20>60，第一波攻擊完之後盤個幾天再攻擊」
    1. 整體走勢好：MA10 > MA20 > MA60
    2. 第一波高點 H1：最近的波段高點（左右各 3 根；右邊還不滿 3 根的近期高點也算），離今天 min_base～max_base 天
    3. 前低 L1（碗底）：H1 之前 bowl_days 天內的最低點；第一波 H1 ≥ L1 ×（1 + wave_pct%）
    4. 盤整：H1 之後到今天的最低點 L2 > L1（不可以破前低）；盤整期間（不含今天）最高沒超過 H1
    5. 再攻擊：今天收盤 > 盤整期間（不含今天）的最高價
    停損＝盤整低點 L2（第二隻腳）
    回測（Yahoo 308 檔大型股、近一年）：每天中位 2 檔；20 天後平均 +8.5%（同期任一股 +6.75%）
    """
    from price_levels import pivots, recent_high
    p = params or {}
    min_price    = p.get("min_price", 10)
    min_vol_lots = p.get("min_vol_lots", 300)
    bowl_days    = int(p.get("bowl_days", 60))
    wave_pct     = float(p.get("wave_pct", 10))
    min_base     = max(2, int(p.get("min_base", 3)))
    max_base     = max(min_base, int(p.get("max_base", 20)))
    results = []
    for sid, df in prices.items():
        n = len(df)
        if n < 61:
            continue
        today = df.iloc[-1]
        c = float(today['close'])
        if c <= min_price:
            continue
        vol = float(today.get('volume', 0) or 0)
        if vol < min_vol_lots:
            continue
        close = df['close'].astype(float)
        m10, m20, m60 = (float(close.rolling(k).mean().iloc[-1]) for k in (10, 20, 60))
        if any(pd.isna(x) for x in (m10, m20, m60)) or not (m10 > m20 > m60):
            continue
        highs = df['high'].astype(float).values
        lows  = df['low'].astype(float).values
        if pd.isna(highs).any() or pd.isna(lows).any():
            continue
        t = n - 1
        hs = [i for i in pivots(highs, 3, "high") if t - max_base <= i <= t - min_base]
        rh = recent_high(highs, 3)
        if rh is not None and t - max_base <= rh <= t - min_base:
            hs.append(rh)
        if not hs:
            continue
        ih = max(hs)
        H1 = float(highs[ih])
        b0 = max(0, ih - bowl_days)
        if ih - b0 < 2:
            continue
        i1 = b0 + int(lows[b0:ih].argmin())
        L1 = float(lows[i1])
        if L1 <= 0 or H1 < L1 * (1 + wave_pct / 100):
            continue                      # 第一波漲幅不夠
        L2 = float(lows[ih + 1:t + 1].min())
        if L2 <= L1:
            continue                      # 破前低
        base_hi = float(highs[ih + 1:t].max())
        if base_hi > H1:
            continue                      # 盤整期間已經過了第一波高點，不是「盤整」
        if c <= base_hi:
            continue                      # 今天還沒再攻擊
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(c, 2),
                        "change_pct": _change_pct(df),
                        "volume": round(vol),
                        "bb_score": calc_bb_score(df),
                        "prev_low": round(L1, 2),
                        "prev_low_date": str(df.iloc[i1].get('date', '')),
                        "wave_high": round(H1, 2),
                        "wave_high_date": str(df.iloc[ih].get('date', '')),
                        "wave_pct": round((H1 / L1 - 1) * 100, 1),
                        "base_days": int(t - ih),
                        "base_low": round(L2, 2),
                        "base_high": round(base_hi, 2),
                        "stop": round(L2, 2),
                        "strategy": "S2"})
    return results

def _xianren_probe(o, h, l, c, v, p: int, P: dict):
    """第 p 根是不是「仙人指路」K 棒：前面有盤整箱、上攻衝過箱頂、收長上影線、出量（第一次出量）。
    是 → 回傳 (前 20 日均量, 箱底, 箱頂)；不是 → None"""
    vd, bd, am = P["vol_days"], P["box_days"], P["attack_max"]
    if p - vd < 0 or p - bd - am < 0:
        return None
    avg_v = float(v[p - vd:p].mean())
    if avg_v <= 0 or v[p] < avg_v * P["probe_vol"]:
        return None
    top = max(o[p], c[p])
    body, rng, upper = abs(c[p] - o[p]), h[p] - l[p], h[p] - top
    if rng <= 0 or upper < body * P["sh_body"] or upper < rng * P["sh_range"] / 100 \
            or upper < c[p - 1] * P["sh_min"] / 100:
        return None
    # 盤整箱：箱子結束在仙人指路前 0～attack_max 天（中間是上攻），箱內收盤高低差 ≤ box_range%
    for k in range(am + 1):
        e = p - k
        s = e - bd
        cs = c[s:e]
        if cs.max() / cs.min() - 1 <= P["box_range"] / 100:
            box_hi = float(h[s:e].max())
            return (avg_v, float(l[s:e].min()), box_hi) if h[p] > box_hi else None
    return None


def screen_xianren(prices: dict, names: dict = None, params: dict = None) -> list:
    """
    仙人指路（2026-10-07 老大哥：「盤整完上攻，收上引線後繼續盤整，第二次出量的時候抓出來，這邊是要進攻了」）
    1. 盤整：上攻前 box_days 天收盤高低差 ≤ box_range%
    2. 仙人指路 K 棒（第一次出量）：最高價衝過箱頂；上影線 ≥ 實體×sh_body、≥ 整根 sh_range%、≥ 前一天收盤 sh_min%；
       量 ≥ 前 20 日均量×probe_vol
    3. 繼續盤整 min_pause～max_pause 天：收盤沒跌破仙人指路低點（盤中跌破拉回不算）、最高沒過上影線頂
    4. 今天第二次出量：量 ≥ 仙人指路之前的 20 日均量×today_vol（不跟昨天比：漲停鎖住量會變小）、收紅（漲、收≥開）、
       收盤站上仙人指路的實體上緣；只抓第一次（盤整中已經出量攻過的不重複抓）
    停損＝仙人指路那根的低點；上影線頂＝第一個壓力
    例：華新科 2492 9/14～9/30 盤整 300～326 → 10/01、10/02 連兩根漲停 → 10/05 高 396 收 368.5、量＝均量 3.3 倍
        → 10/06 盤整 → 10/07 量＝均量 1.8 倍漲停 428
    回測（Yahoo 全市場 1,946 檔、近一年）：每天平均 1.7 檔；20 天後平均 +4.4%（同期任一股 +3.0%），
    但上漲比例 46%、中位數 −1.3%：贏的抱得大（20 天內最高平均 +18%），一半會失敗，停損要守
    """
    p = params or {}
    P = {"vol_days": 20,
         "box_days":   int(p.get("box_days", 15)),
         "box_range":  float(p.get("box_range", 15)),
         "attack_max": int(p.get("attack_max", 5)),
         "sh_body":    float(p.get("sh_body", 1.5)),
         "sh_range":   float(p.get("sh_range", 40)),
         "sh_min":     float(p.get("sh_min", 2)),
         "probe_vol":  float(p.get("probe_vol", 2)),
         "today_vol":  float(p.get("today_vol", 1.5))}
    min_price    = p.get("min_price", 10)
    min_vol_lots = p.get("min_vol_lots", 300)
    min_pause    = max(1, int(p.get("min_pause", 1)))
    max_pause    = max(min_pause, int(p.get("max_pause", 10)))
    results = []
    for sid, df in prices.items():
        n = len(df)
        if n < P["vol_days"] + P["box_days"] + P["attack_max"] + max_pause + 2:
            continue
        o, h, l, c, v = (df[k].astype(float).values for k in ("open", "high", "low", "close", "volume"))
        t = n - 1
        if c[t] <= min_price or v[t] < min_vol_lots:
            continue
        if any(pd.isna(x[t - max_pause - P["vol_days"] - P["box_days"] - P["attack_max"] - 1:]).any()
               for x in (o, h, l, c, v)):
            continue

        def attack(i, avg_v):            # 第 i 根是不是「第二次出量」
            return v[i] >= avg_v * P["today_vol"] and c[i] > c[i - 1] and c[i] >= o[i]

        for pause in range(min_pause, max_pause + 1):          # 由近往遠找仙人指路
            pi = t - 1 - pause
            probe = _xianren_probe(o, h, l, c, v, pi, P)
            if probe is None:
                continue
            avg_v, box_lo, box_hi = probe
            mid = slice(pi + 1, t)
            if (c[mid] < l[pi]).any() or (h[mid] > h[pi]).any():
                break                     # 盤整中收盤跌破低點／已經衝過上影線頂 → 這根仙人指路作廢
            if not attack(t, avg_v) or c[t] <= max(o[pi], c[pi]):
                break
            if any(attack(d, avg_v) for d in range(pi + 1 + min_pause, t)):
                break                     # 盤整中已經出量攻過一次，今天不是第一次
            top = float(h[pi])
            results.append({"stock_id": sid, "name": _name(sid, names),
                            "close": round(float(c[t]), 2),
                            "change_pct": _change_pct(df),
                            "volume": round(float(v[t])),
                            "bb_score": calc_bb_score(df),
                            "probe_date": str(df.iloc[pi].get("date", "")),
                            "probe_high": round(top, 2),
                            "probe_low": round(float(l[pi]), 2),
                            "probe_close": round(float(c[pi]), 2),
                            "probe_vol_ratio": round(float(v[pi]) / avg_v, 1),
                            "box_low": round(box_lo, 2),
                            "box_high": round(box_hi, 2),
                            "pause_days": pause,
                            "today_vol_ratio": round(float(v[t]) / avg_v, 1),
                            "broke_top": bool(c[t] > top),
                            "dist_top_pct": round((float(c[t]) / top - 1) * 100, 1),
                            "stop": round(float(l[pi]), 2),
                            "strategy": "S_XIANREN"})
            break
    return results


def screen_s5(prices: dict, names: dict = None, params: dict = None) -> list:
    """S5 站上均線做多（今日才剛全部突破5/10/20/60/200MA，且今日量 ≥ 昨日量 × vol_mult）"""
    p = params or {}
    min_price    = p.get("min_price", 10)
    min_vol_lots = p.get("min_vol_lots", 0)
    vol_mult     = float(p.get("vol_mult", 3))
    results = []
    for sid, df in prices.items():
        if len(df) < 205:
            continue
        closes = df['close']
        today = df.iloc[-1]
        if float(today['close']) <= min_price:
            continue
        vol = float(today.get('volume', 0) or 0)
        if min_vol_lots > 0 and vol < min_vol_lots:
            continue
        vol_prev = float(df.iloc[-2].get('volume', 0) or 0)
        if vol_mult > 0 and (vol_prev <= 0 or vol < vol_prev * vol_mult):
            continue
        ma5   = calc_ma(closes, 5)
        ma10  = calc_ma(closes, 10)
        ma20  = calc_ma(closes, 20)
        ma60  = calc_ma(closes, 60)
        ma200 = calc_ma(closes, 200)
        if any(pd.isna(x.iloc[-1]) for x in [ma5, ma10, ma20, ma60, ma200]):
            continue
        if any(pd.isna(x.iloc[-2]) for x in [ma5, ma10, ma20]):
            continue
        c     = float(today['close'])
        c_pre = float(closes.iloc[-2])
        if not (c > ma5.iloc[-1] and c > ma10.iloc[-1] and c > ma20.iloc[-1] and
                c > ma60.iloc[-1] and c > ma200.iloc[-1]):
            continue
        prev_all = (c_pre > ma5.iloc[-2] and c_pre > ma10.iloc[-2] and c_pre > ma20.iloc[-2])
        if prev_all:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(c, 2),
                        "change_pct": _change_pct(df),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S5"})
    return results

def _is_limit_up(close: float, prev_close: float) -> bool:
    """
    判斷是否漲停：收盤 >= 漲停價（允許一個 tick 誤差，處理浮點問題）。
    """
    if prev_close <= 0:
        return False
    limit = _limit_up_price(prev_close)
    tick  = _tick_size(limit)
    return close >= limit - tick * 0.1


def screen_s10(prices: dict, names: dict = None, params: dict = None) -> list:
    """
    S10 漲停（收盤達漲停價，依台股 tick 規則計算，顯示連續天數）。
    僅取最新一筆：最後一根 K 棒必須與倒數第二根日期不同（確認是獨立交易日）。
    """
    results = []
    for sid, df in prices.items():
        if len(df) < 2:
            continue
        # 確保最後兩根是不同交易日（避免 Yahoo 重複回傳同一天資料）
        last_date = str(df.iloc[-1].get('date', ''))
        prev_date = str(df.iloc[-2].get('date', ''))
        if last_date == prev_date:
            continue
        prev_c = float(df.iloc[-2]['close'])
        c      = float(df.iloc[-1]['close'])
        if not _is_limit_up(c, prev_c):
            continue
        change_pct = (c - prev_c) / prev_c * 100

        # 連續漲停天數（向前回溯）
        consec = 1
        for i in range(len(df) - 2, 0, -1):
            c_i   = float(df.iloc[i]['close'])
            c_pre = float(df.iloc[i - 1]['close'])
            if _is_limit_up(c_i, c_pre):
                consec += 1
            else:
                break

        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(c, 2),
                        "change_pct": round(change_pct, 2),
                        "consec_limit_up": consec,
                        "volume": round(float(df.iloc[-1].get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S10"})
    results.sort(key=lambda x: x['consec_limit_up'], reverse=True)
    return results


def screen_sfbd(prices: dict, names: dict = None, params: dict = None) -> list:
    """S_FBD 假跌破買進：MA10>MA60多頭中，小MACD綠柱縮短時跌破MA10後收復，洗盤完成"""
    p = params or {}
    min_price      = p.get("min_price", 10)
    min_vol_lots    = p.get("min_vol_lots", 300)
    break_window    = int(p.get("break_window", 4))
    break_vol_ratio = p.get("break_vol_ratio", 2.5)
    vol_ref_days    = int(p.get("vol_ref_days", 20))
    macd_ref_days   = int(p.get("macd_ref_days", 3))
    results = []
    for sid, df in prices.items():
        if len(df) < 65:
            continue
        closes = df['close']
        today  = df.iloc[-1]
        tc     = float(today['close'])
        to_    = float(today['open'])
        if tc <= min_price:
            continue
        vol = float(today.get('volume', 0) or 0)
        if vol < min_vol_lots:
            continue
        ma10 = calc_ma(closes, 10)
        ma60 = calc_ma(closes, 60)
        m10  = float(ma10.iloc[-1])
        m60  = float(ma60.iloc[-1])
        if pd.isna(m10) or pd.isna(m60):
            continue
        # 基本多頭格局：MA10 > MA60
        if not (m10 > m60):
            continue
        # ── 小MACD(12,26,9) 綠柱縮短 ──────────────────────────────────
        # 綠柱 = OSC(DIF-DEA) < 0，縮短 = 今天比 N 天前更接近 0
        if len(closes) < macd_ref_days + 2:
            continue
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        dif   = ema12 - ema26
        dea   = dif.ewm(span=9, adjust=False).mean()
        osc   = dif - dea
        osc_now = float(osc.iloc[-1])
        osc_ref = float(osc.iloc[-1 - macd_ref_days])
        # OSC 必須為負（綠柱）且比 N 天前縮短（向 0 靠近）
        if not (osc_now < 0 and osc_now > osc_ref):
            continue
        # 今日收紅且站回 MA10
        if not (tc > to_ and tc > m10):
            continue
        # 昨天收盤必須仍在 MA10 以下（確保今天才是站回的第一天）
        yst_c   = float(closes.iloc[-2])
        yst_m10 = float(ma10.iloc[-2])
        if pd.isna(yst_m10) or yst_c >= yst_m10:
            continue
        # 近 1~break_window 天有一天收盤跌破 MA10
        broke_idx = None
        for i in range(1, break_window + 1):
            if i + 1 > len(closes):
                break
            pm10 = float(ma10.iloc[-(i+1)])
            if not pd.isna(pm10) and float(closes.iloc[-(i+1)]) < pm10:
                broke_idx = i
                break
        if broke_idx is None:
            continue
        # 跌破當天量 ≤ 均量 × break_vol_ratio（非出貨）
        vol20 = df.iloc[-vol_ref_days:]['volume'].astype(float).mean() if len(df) >= vol_ref_days else 0
        broke_vol = float(df.iloc[-(broke_idx+1)].get('volume', 0) or 0)
        if vol20 > 0 and broke_vol > vol20 * break_vol_ratio:
            continue
        # 今日收盤吃回跌破那天的收盤
        if tc <= float(closes.iloc[-(broke_idx+1)]):
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(tc, 2), "change_pct": _change_pct(df),
                        "volume": round(vol), "bb_score": calc_bb_score(df),
                        "strategy": "S_FBD"})
    return results


def calc_kd(df: pd.DataFrame, n: int = 9) -> tuple:
    """
    計算 KD 指標（台灣標準）：
    RSV = (Close - LowestLow_N) / (HighestHigh_N - LowestLow_N) × 100
    K = prev_K × 2/3 + RSV × 1/3（初始50）
    D = prev_D × 2/3 + K × 1/3（初始50）
    回傳 (K series, D series)，長度與 df 相同
    """
    closes = df['close'].astype(float)
    highs  = df['high'].astype(float)
    lows   = df['low'].astype(float)
    size   = len(df)
    k_vals = [50.0] * size
    d_vals = [50.0] * size
    for i in range(n - 1, size):
        lo = lows.iloc[i - n + 1:i + 1].min()
        hi = highs.iloc[i - n + 1:i + 1].max()
        rsv = (float(closes.iloc[i]) - lo) / (hi - lo) * 100 if (hi - lo) > 0 else 50.0
        k_vals[i] = k_vals[i - 1] * 2 / 3 + rsv / 3
        d_vals[i] = d_vals[i - 1] * 2 / 3 + k_vals[i] / 3
    return pd.Series(k_vals, index=df.index), pd.Series(d_vals, index=df.index)


def screen_skd(prices: dict, names: dict = None, params: dict = None) -> list:
    """
    S_KD KD超賣反彈：
    1. 收盤 > min_price，量 >= min_vol_lots 張
    2. KD 的 K 值在近 1~lookback 天曾跌破 oversold_level（超賣區）
    3. 今日 K 值回升至 oversold_level 以上（離開超賣區）
    4. K 上穿 D（黃金交叉，或 K > D 且方向向上）
    """
    p = params or {}
    min_price      = p.get("min_price", 10)
    min_vol_lots   = p.get("min_vol_lots", 300)
    oversold_level = p.get("oversold_level", 20)
    lookback       = int(p.get("lookback", 5))
    kd_period      = int(p.get("kd_period", 9))
    results = []
    for sid, df in prices.items():
        if len(df) < 30:
            continue
        if 'high' not in df.columns or 'low' not in df.columns:
            continue
        today = df.iloc[-1]
        tc    = float(today['close'])
        if tc <= min_price:
            continue
        vol = float(today.get('volume', 0) or 0)
        if vol < min_vol_lots:
            continue
        k_ser, d_ser = calc_kd(df, n=kd_period)
        k_now = k_ser.iloc[-1]
        d_now = d_ser.iloc[-1]
        # 今日 K 必須已回到 oversold_level 以上
        if k_now <= oversold_level:
            continue
        # 近 1~lookback 天（不含今日）K 曾 <= oversold_level
        broke_oversold = any(
            k_ser.iloc[-(i+1)] <= oversold_level
            for i in range(1, lookback + 1) if i + 1 <= len(k_ser)
        )
        if not broke_oversold:
            continue
        # K > D（多頭排列或剛黃金交叉）
        if k_now <= d_now:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(tc, 2), "change_pct": _change_pct(df),
                        "volume": round(vol), "bb_score": calc_bb_score(df),
                        "kd_k": round(k_now, 1), "kd_d": round(d_now, 1),
                        "strategy": "S_KD"})
    return results


def screen_chip(prices: dict, tdcc_data: dict, stock_info: dict = None, params: dict = None) -> list:
    """
    CHIP 千張大戶增持選股（集保所週資料）：
    - 千張大戶本週持股比例 > 上週（change > 0）
    - MA5 > MA10 > MA20
    - 收盤 > min_price
    - 同族群上漲比 >= sector_ratio%（有傳入 stock_info 且有 industry 時才套用）
    """
    p = params or {}
    min_price        = p.get("min_price", 10)
    sector_ratio_pct = p.get("sector_ratio", 50)
    min_consec_up    = int(p.get("min_consec_up", 1))

    up_map = {}
    for sid, df in prices.items():
        if len(df) >= 2:
            up_map[sid] = float(df.iloc[-1]['close']) > float(df.iloc[-2]['close'])
    sector_sids = {}
    if stock_info:
        for sid, info in stock_info.items():
            ind = info.get('industry') or ''
            if ind:
                sector_sids.setdefault(ind, []).append(sid)
    sector_ratio = {}
    for ind, sids in sector_sids.items():
        up = sum(1 for s in sids if up_map.get(s, False))
        sector_ratio[ind] = up / len(sids) if sids else 0

    results = []
    for sid, df in prices.items():
        if len(df) < 25:
            continue
        tdcc = tdcc_data.get(sid)
        if not tdcc or tdcc.get('change', 0) <= 0:
            continue
        # 連續增持週數門檻
        if tdcc.get('consec_up', 1) < min_consec_up:
            continue
        closes = df['close']
        today  = df.iloc[-1]
        if float(today['close']) <= min_price:
            continue
        ma5  = calc_ma(closes, 5)
        ma10 = calc_ma(closes, 10)
        ma20 = calc_ma(closes, 20)
        if any(pd.isna(x.iloc[-1]) for x in [ma5, ma10, ma20]):
            continue
        if not (ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]):
            continue
        info  = (stock_info or {}).get(sid, {})
        ind   = info.get('industry', '')
        ratio = sector_ratio.get(ind, 0) if ind else 0
        if ind and ratio < sector_ratio_pct / 100:
            continue
        results.append({
            "stock_id":         sid,
            "name":             info.get('name', ''),
            "close":            round(float(today['close']), 2),
            "change_pct":       _change_pct(df),
            "volume":           round(float(today.get('volume', 0) or 0)),
            "bb_score":         calc_bb_score(df),
            "thousand_lot_pct": tdcc['current_pct'],
            "thousand_lot_chg": tdcc['change'],
            "strategy":         "CHIP",
        })
    results.sort(key=lambda x: x['thousand_lot_chg'], reverse=True)
    return results


def screen_s_warrant_top(
    warrant_flow_rows: list,
    prices: dict,
    names: dict,
    params: dict = None,
) -> list:
    """認購權證前十大：依 call_turnover 排序的 warrant_flow 緩衝列，過濾後取前 limit 支。"""
    p = params or {}
    limit     = int(p.get("limit", 10))
    min_price = float(p.get("min_price", 10))
    results = []
    for row in warrant_flow_rows:
        if len(results) >= limit:
            break
        sid = row.get("underlying_code", "")
        if not sid:
            continue
        df = prices.get(sid)
        if df is None or df.empty:
            continue
        last  = df.iloc[-1]
        close = float(last.get("close", 0) or 0)
        if close < min_price:
            continue
        results.append({
            "stock_id":          sid,
            "name":              names.get(sid, row.get("underlying_name", "")),
            "close":             round(close, 2),
            "change_pct":        _change_pct(df),
            "volume":            int(float(last.get("volume", 0) or 0)),
            "bb_score":          calc_bb_score(df),
            "call_turnover_wan": round(row.get("call_turnover", 0), 1),
            "cp_ratio":          row.get("cp_ratio"),
            "trade_date":        row.get("trade_date", ""),
            "strategy":          "S_WARRANT_TOP",
        })
    return results


def screen_sthunder(prices: dict, names: dict = None, params: dict = None) -> list:
    """平地一聲雷：盤整 base_days 天（收盤區間 ≤ base_range%）後，收盤帶量（≥ 20 日均量 vol_mult 倍）突破盤整上緣，
    突破在近 breakout_within 天內、現價仍在盤整上緣之上。回檔 ≤ max_retrace 時給目標價＝第一段高點 − 突破點 ＋ 回檔低點。"""
    from price_levels import detect_thunder
    p = params or {}
    tp = {"base_days": int(p.get("base_days", 90)), "base_range": float(p.get("base_range", 15)) / 100,
          "vol_mult": float(p.get("vol_mult", 2.5)), "max_retrace": float(p.get("max_retrace", 0.618)),
          "breakout_within": int(p.get("breakout_within", 30))}
    min_price = float(p.get("min_price", 10))
    results = []
    for sid, df in prices.items():
        if len(df) < tp["base_days"] + 22:
            continue
        c = float(df.iloc[-1]["close"])
        if c < min_price:
            continue
        try:
            th = detect_thunder(df.reset_index(drop=True), tp)
        except Exception:
            th = None
        if not th:
            continue
        results.append({
            "stock_id": sid, "name": _name(sid, names), "close": round(c, 2),
            "change_pct": _change_pct(df), "volume": round(float(df.iloc[-1].get("volume", 0) or 0)),
            "bb_score": calc_bb_score(df), "strategy": "S_THUNDER",
            "stage": th["stage"], "base_top": th["base_top"], "breakout_date": th["breakout_date"],
            "breakout_vol_ratio": th["breakout_vol_ratio"], "first_high": th["high"],
            "pullback_low": th["pullback_low"], "retrace": th["retrace"], "target": th["target"],
            "uptrend": th["uptrend"], "exit_prev_low": th["exit_prev_low"],
        })
    return results


# 純價格型策略（掃描、K 線回測共用同一份；CHIP / S_WARRANT_TOP 需外部資料不在此）
PRICE_STRATEGY_FNS = {
    "S1":           screen_s1,
    "S1_SHORT":     screen_s1_short,
    "S2":           screen_s2,
    "S5":           screen_s5,
    "S10":          screen_s10,
    "S_FBD":        screen_sfbd,
    "S_THUNDER":    screen_sthunder,
    "S_XIANREN":    screen_xianren,
}
SHORT_STRATEGIES = {"S1_SHORT"}


def _vol_prefilter_pass(df: pd.DataFrame, min_vol_ratio: float) -> bool:
    """量能翻倍前置過濾：min_vol_ratio > 0 時，今日量 < 昨日量 × min_vol_ratio 則不通過。"""
    if min_vol_ratio > 0 and len(df) >= 2:
        vol_col = "volume" if "volume" in df.columns else "Volume"
        _last_v = df.iloc[-1][vol_col] if vol_col in df.columns else None
        _prev_v = df.iloc[-2][vol_col] if vol_col in df.columns else None
        today_vol = float(_last_v) if pd.notna(_last_v) else 0.0
        prev_vol  = float(_prev_v) if pd.notna(_prev_v) else 0.0
        # 最低成交量門檻：昨日 < 500 張視為冷門股，跳過量能比對（避免 1→2 張假觸發）
        _MIN_ABS_VOL = 500
        if prev_vol < _MIN_ABS_VOL or today_vol < prev_vol * min_vol_ratio:
            return False
    return True


def strategy_signal_mask(df: pd.DataFrame, key: str, params: dict = None,
                         min_vol_ratio: float = 0.0, start: int = 30) -> list:
    """
    回測用：逐日以「截至當天」的資料呼叫策略掃描的同一個 screen 函式，
    回傳長度 = len(df) 的 bool list（True = 當天收盤符合策略）。
    """
    fn = PRICE_STRATEGY_FNS[key]
    df = df.reset_index(drop=True)
    mask = [False] * len(df)
    errors = 0
    for i in range(start, len(df)):
        sub = df.iloc[:i + 1]
        if not _vol_prefilter_pass(sub, min_vol_ratio):
            continue
        try:
            mask[i] = bool(fn({"BT": sub}, {"BT": ""}, params=params))
        except Exception as e:
            if errors == 0:
                print(f"[BACKTEST] {key} 第 {i} 根計算失敗（視為無訊號）: {type(e).__name__}: {e}")
            errors += 1
    if errors:
        print(f"[BACKTEST] {key} 共 {errors} 根計算失敗")
    return mask


def scan_one_stock(df: pd.DataFrame, sid: str, name: str = "",
                   strategy_params: dict = None,
                   min_vol_ratio: float = 0.0) -> dict:
    """
    檢查單支股票的所有策略，回傳 {strategy_key: result_dict or None}。
    供全市場掃描使用：一次抓取 → 同時跑所有策略，避免重複請求。
    strategy_params: {strategy_key: {param_key: value, ...}, ...}
    min_vol_ratio > 0 時，今日量 < 昨日量 × min_vol_ratio 則全部回傳 None（量能翻倍過濾）。
    """
    # 量能前置過濾
    if not _vol_prefilter_pass(df, min_vol_ratio):
        return {k: None for k in PRICE_STRATEGY_FNS}
    prices_single = {sid: df}
    names_single  = {sid: name}
    last_date = str(df.iloc[-1].get('date', '')) if not df.empty else ''
    out = {}
    for key, fn in PRICE_STRATEGY_FNS.items():
        p = strategy_params.get(key, {}) if strategy_params else None
        results = fn(prices_single, names_single, params=p)
        result = results[0] if results else None
        if result:
            if last_date:
                result['last_date'] = last_date  # YYYYMMDD，讓 UI 顯示資料日期
            if 'vol_ratio' not in result:
                result['vol_ratio'] = _vol_ratio(df)
        out[key] = result
    return out


def run_strategy(strategy: str, prices: dict, names: dict = None,
                 chip_data: list = None, stock_info: dict = None,
                 strategy_params: dict = None) -> list:
    s = strategy.upper()
    p = strategy_params.get(s, {}) if strategy_params else None
    fn = PRICE_STRATEGY_FNS.get(s)
    return fn(prices, names, params=p) if fn else []


# ── 上課筆記新增的技術面策略（scanner_course.py；舊策略不動，只是登記進來）──
from scanner_course import COURSE_FNS as _COURSE_FNS, COURSE_PARAMS as _COURSE_PARAMS, \
    COURSE_SHORT as _COURSE_SHORT, COURSE_STRATEGIES as _COURSE_STRATEGIES  # noqa: E402
STRATEGIES.update(_COURSE_STRATEGIES)
STRATEGY_PARAMS_SCHEMA.update(_COURSE_PARAMS)
PRICE_STRATEGY_FNS.update(_COURSE_FNS)
SHORT_STRATEGIES |= _COURSE_SHORT
# ── 講義策略（PLAN-COURSE，course2.py：研究跟掃描同一份函式）──
import course2 as _c2  # noqa: E402
STRATEGIES.update(_c2.COURSE2_STRATEGIES)
STRATEGY_PARAMS_SCHEMA.update(_c2.COURSE2_PARAMS)
PRICE_STRATEGY_FNS.update(_c2.COURSE2_FNS)
SHORT_STRATEGIES |= _c2.COURSE2_SHORT
PRICE_STRATEGY_FNS["S_LIMIT_OPEN"] = _c2.screen_limit_open2       # 盤中打開也算＋月營收年增（業績前提）


def screen_sthunder_merged(prices: dict, names: dict = None, params: dict = None) -> list:
    """平地一聲雷（合併版，PLAN-COURSE 項目 2）：原「盤整後帶量突破」＋原「底部量滾量站上季線」（S_VOLROLL）。
    講義的「底部起漲（爆量→量縮平台→帶量突破）」也測了，5 年回測比原本差 → 沒併入（research/course/results/REPORT.md）"""
    from scanner_course import screen_volroll
    out = screen_sthunder(prices, names, params)
    for r in out:
        r["sub"] = "盤整突破"
    have = {r["stock_id"] for r in out}
    for r in screen_volroll(prices, names, {"min_price": (params or {}).get("min_price", 10)}):
        if r["stock_id"] in have:
            continue
        r.update(strategy="S_THUNDER", sub="底部量滾量",
                 stage=f"🌋 底部量滾量：跌深後重新站上季線＋連續爆量 {r.get('vol_x')} 倍；停損 {r.get('stop')}",
                 base_top=r.get("ma60"), breakout_vol_ratio=r.get("vol_x"), pullback_low=r.get("vol_low"))
        out.append(r)
    return out


PRICE_STRATEGY_FNS["S_THUNDER"] = screen_sthunder_merged
from chip_course import CHIP_PARAMS as _CHIP_PARAMS, CHIP_STRATEGIES as _CHIP_STRATEGIES  # noqa: E402
STRATEGIES.update(_CHIP_STRATEGIES)          # 籌碼型：掃描後由 chip_course.run_all 另外算（不在 PRICE_STRATEGY_FNS）
STRATEGY_PARAMS_SCHEMA.update(_CHIP_PARAMS)
# ── 🔬 研究候選／🏆 研究最佳（PLAN-BEST，best_strategy.py；5 年回測，名稱看有沒有全過關）──
import best_strategy as _best  # noqa: E402
STRATEGIES[_best.KEY] = _best.LABEL.lstrip("🔬🏆 ")
STRATEGY_PARAMS_SCHEMA[_best.KEY] = []
PRICE_STRATEGY_FNS[_best.KEY] = _best.screen_best
