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
    "S1_SHORT": "雙MACD選股（空）",
    "S1_2":     "MACD延伸（創新高拉回）",
    "S2":       "二次確認買進（W底）",
    "S5":       "站上均線做多",
    "S17A":     "底部破底翻試單",
    "S17B":     "突破確認加碼（撈底）",
    "S10":      "漲停",
    "CHIP":     "主力籌碼選股",
    "S_PB":     "均線拉回買點",
    "S_FBD":    "假跌破買進",
    "S_RES":    "共振起點（黃金交叉）",
    "S_KD":     "KD超賣反彈（KD跌破20後回升）",
    "S_VOLX":       "量爆拉升（成交量暴增3倍且站上20週線）",
    "S_VOLX_SHORT": "量爆下殺（成交量暴增3倍且跌破20週線）",
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
    std = closes.rolling(period).std().iloc[-1]
    if pd.isna(ma) or pd.isna(std) or std == 0:
        return 0.0
    score = (float(closes.iloc[-1]) - float(ma)) / (2 * float(std)) * 10
    return round(score)

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
        return {"code": "bearish", "label": "🔴 空頭", "color": "red",
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
                return {"code": "pullback", "label": "🎯 拉回買點", "color": "green",
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


def screen_s1(prices: dict, names: dict = None) -> list:
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
    results = []
    for sid, df in prices.items():
        if len(df) < 235:
            continue
        closes = df['close']
        dif1, dea1, osc1 = calc_macd(closes, 12, 26, 9)
        dif2, dea2, osc2 = calc_macd(closes, 108, 216, 18)
        today = df.iloc[-1]
        if float(today['close']) <= 10:
            continue
        if pd.isna(today.get('open')) or float(today['close']) <= float(today['open']):
            continue
        if dif1.iloc[-1] <= 0 or dea1.iloc[-1] <= 0:
            continue
        if osc1.iloc[-1] >= 0:
            continue
        if len(osc1) < 22:
            continue
        # 昨日是局部谷底：昨天比前天低（或昨天是近10天最低）
        osc_prev2 = osc1.iloc[-3]   # 前天
        osc_prev1 = osc1.iloc[-2]   # 昨天
        is_local_min = (osc_prev1 < osc_prev2) or (osc_prev1 <= osc1.iloc[-12:-1].min() + 1e-9)
        if not is_local_min:
            continue
        # 今日 OSC 絕對值比昨日小（柱子縮短，確認反轉）
        if abs(osc1.iloc[-1]) >= abs(osc_prev1):
            continue
        if dif2.iloc[-1] <= 0 or dea2.iloc[-1] <= 0 or osc2.iloc[-1] <= 0:
            continue
        if float(today['close']) < float(closes.iloc[-11:-1].min()):
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2),
                        "change_pct": _change_pct(df),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S1"})
    return results

def screen_s1_short(prices: dict, names: dict = None) -> list:
    """S1空 雙MACD選股（空）"""
    results = []
    for sid, df in prices.items():
        if len(df) < 235:
            continue
        closes = df['close']
        dif1, dea1, osc1 = calc_macd(closes, 12, 26, 9)
        dif2, dea2, osc2 = calc_macd(closes, 108, 216, 18)
        today = df.iloc[-1]
        if float(today['close']) <= 10:
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
        # 昨日是局部頂部：昨天比前天高（或昨天是近10天最高）
        is_local_max = (osc_prev1 > osc_prev2) or (osc_prev1 >= osc1.iloc[-12:-1].max() - 1e-9)
        if not is_local_max:
            continue
        if abs(osc1.iloc[-1]) >= abs(osc_prev1):
            continue
        if dif2.iloc[-1] >= 0 or dea2.iloc[-1] >= 0 or osc2.iloc[-1] >= 0:
            continue
        if float(today['close']) > float(closes.iloc[-11:-1].max()):
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2),
                        "change_pct": _change_pct(df),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S1_SHORT"})
    return results

def screen_s1_2(prices: dict, names: dict = None) -> list:
    """S1.2 MACD延伸（創新高拉回）"""
    results = []
    for sid, df in prices.items():
        if len(df) < 70:
            continue
        closes = df['close']
        dif1, dea1, osc1 = calc_macd(closes, 12, 26, 9)
        today = df.iloc[-1]
        if float(today['close']) <= 10:
            continue
        if dif1.iloc[-1] <= 0 or dea1.iloc[-1] <= 0:
            continue
        if (dif1.iloc[-20:] <= 0).any():
            continue
        if osc1.iloc[-1] >= 0:
            continue
        if len(closes) < 65:
            continue
        prior_60_high = float(closes.iloc[-65:-20].max())
        recent_20_high = float(closes.iloc[-20:].max())
        if recent_20_high <= prior_60_high:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2),
                        "change_pct": _change_pct(df),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S1_2"})
    return results

def screen_s2(prices: dict, names: dict = None) -> list:
    """S2 二次確認買進（W底）"""
    results = []
    for sid, df in prices.items():
        if len(df) < 205:
            continue
        closes = df['close']
        today = df.iloc[-1]
        if float(today['close']) <= 10:
            continue
        vol = today.get('volume', 0) or 0
        if float(vol) < 300_000:   # 300張 = 300,000股（Yahoo回傳股數）
            continue
        ma10  = calc_ma(closes, 10)
        ma60  = calc_ma(closes, 60)
        ma200 = calc_ma(closes, 200)
        if any(pd.isna(x.iloc[-1]) for x in [ma10, ma60, ma200]):
            continue
        if not (ma10.iloc[-1] > ma60.iloc[-1] > ma200.iloc[-1]):
            continue
        # MA10/MA60 持續向上；MA200 不下彎即可（不要求嚴格上揚）
        if not (ma10.iloc[-1] > ma10.iloc[-2] and
                ma60.iloc[-1] > ma60.iloc[-2] and
                ma200.iloc[-1] >= float(ma200.iloc[-5]) if len(ma200) >= 5 and not pd.isna(ma200.iloc[-5]) else True):
            continue
        sub60 = closes.iloc[-61:]
        high_idx_in_sub = sub60.idxmax()
        days_from_high = len(closes) - 1 - high_idx_in_sub
        if not (5 <= days_from_high <= 40):
            continue
        db = find_double_bottom(df, lookback=40)
        if db is None:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2),
                        "change_pct": _change_pct(df),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S2"})
    return results

def screen_s5(prices: dict, names: dict = None) -> list:
    """S5 站上均線做多（今日才剛全部突破5/10/20/60/200MA）"""
    results = []
    for sid, df in prices.items():
        if len(df) < 205:
            continue
        closes = df['close']
        today = df.iloc[-1]
        if float(today['close']) <= 10:
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

def screen_s17a(prices: dict, names: dict = None) -> list:
    """S17a 底部破底翻試單"""
    results = []
    for sid, df in prices.items():
        if len(df) < 125:
            continue
        closes = df['close']
        today = df.iloc[-1]
        if float(today['close']) <= 10:
            continue
        high_120 = float(closes.iloc[-121:].max())
        if high_120 <= 0 or float(today['close']) >= high_120 * 0.70:
            continue
        db = find_double_bottom(df, lookback=60, tol=0.08)
        if db is None:
            continue
        w1_i, w2_i = db['wave1_idx'], db['wave2_idx']
        df_sub = db['df_sub']
        if 'volume' in df_sub.columns:
            w1_vol = float(df_sub.iloc[max(0, w1_i - 4):w1_i + 5]['volume'].mean())
            w2_vol = float(df_sub.iloc[max(0, w2_i - 4):w2_i + 5]['volume'].mean())
            if w1_vol > 0 and w2_vol < w1_vol * 0.60:
                continue
        low_10 = float(closes.iloc[-11:-1].min())
        broke = (float(closes.iloc[-1]) <= low_10 or float(closes.iloc[-2]) <= low_10)
        if not broke:
            continue
        if 'open' in df.columns and not pd.isna(df.iloc[-2].get('open')):
            if float(today['close']) <= float(df.iloc[-2]['open']):
                continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2),
                        "change_pct": _change_pct(df),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df),
                        "strategy": "S17A"})
    return results

def screen_s17b(prices: dict, names: dict = None) -> list:
    """S17b 突破確認加碼（撈底）"""
    results = []
    for sid, df in prices.items():
        if len(df) < 125:
            continue
        closes = df['close']
        today = df.iloc[-1]
        if float(today['close']) <= 10:
            continue
        high_120 = float(closes.iloc[-121:].max())
        if high_120 <= 0 or float(today['close']) >= high_120 * 0.70:
            continue
        db = find_double_bottom(df, lookback=60, tol=0.08)
        if db is None:
            continue
        df_sub = db['df_sub']
        if len(df_sub) - 1 - db['wave2_idx'] > 30:
            continue
        neckline = db['neckline']
        c = float(today['close'])
        if not (neckline * 0.90 <= c < neckline):
            continue
        if 'open' in df.columns and not pd.isna(df.iloc[-2].get('open')):
            if c <= float(df.iloc[-2]['open']):
                continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(c, 2), "strategy": "S17B",
                        "change_pct": _change_pct(df),
                        "neckline": round(neckline, 2),
                        "volume": round(float(today.get('volume', 0) or 0)),
                        "bb_score": calc_bb_score(df)})
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


def screen_s10(prices: dict, names: dict = None) -> list:
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

def screen_spb(prices: dict, names: dict = None) -> list:
    """S_PB 均線拉回買點：多頭排列中，股價回測MA10後站回，出現多方K線"""
    results = []
    for sid, df in prices.items():
        if len(df) < 65:
            continue
        closes = df['close']
        lows   = df['low']
        today  = df.iloc[-1]
        tc     = float(today['close'])
        to_    = float(today['open'])
        if tc <= 10:
            continue
        vol = float(today.get('volume', 0) or 0)
        if vol < 300_000:
            continue
        ma10 = calc_ma(closes, 10)
        ma60 = calc_ma(closes, 60)
        m10  = float(ma10.iloc[-1])
        m60  = float(ma60.iloc[-1])
        if pd.isna(m10) or pd.isna(m60):
            continue
        if not (m10 > m60):
            continue
        # MA10 斜率向上（近5天）
        if pd.isna(ma10.iloc[-5]) or not (m10 > float(ma10.iloc[-5])):
            continue
        # 近5天低點曾碰 MA10 (±2%)
        touched = any(
            not pd.isna(ma10.iloc[-(i+1)]) and float(lows.iloc[-(i+1)]) <= float(ma10.iloc[-(i+1)]) * 1.02
            for i in range(5) if i + 1 <= len(lows)
        )
        if not touched:
            continue
        # 今日站回 MA10
        if tc <= m10:
            continue
        # 多方K線：收紅 or 下引線 >= 實體 × 1.5
        body       = abs(tc - to_)
        low_wick   = min(tc, to_) - float(today['low'])
        is_bullish = (tc > to_) or (body > 0 and low_wick >= body * 1.5)
        if not is_bullish:
            continue
        # 量能不能萎縮超過 40%（5日均量）
        vol5 = df.iloc[-5:]['volume'].astype(float).mean() if len(df) >= 5 else 0
        if vol5 > 0 and vol < vol5 * 0.6:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(tc, 2), "change_pct": _change_pct(df),
                        "volume": round(vol), "bb_score": calc_bb_score(df),
                        "strategy": "S_PB"})
    return results


def screen_sfbd(prices: dict, names: dict = None) -> list:
    """S_FBD 假跌破買進：多頭中近期跌破MA10後當日/隔日收復，洗盤完成"""
    results = []
    for sid, df in prices.items():
        if len(df) < 65:
            continue
        closes = df['close']
        today  = df.iloc[-1]
        tc     = float(today['close'])
        to_    = float(today['open'])
        if tc <= 10:
            continue
        vol = float(today.get('volume', 0) or 0)
        if vol < 300_000:
            continue
        ma10 = calc_ma(closes, 10)
        ma60 = calc_ma(closes, 60)
        m10  = float(ma10.iloc[-1])
        m60  = float(ma60.iloc[-1])
        if pd.isna(m10) or pd.isna(m60):
            continue
        if not (m10 > m60):
            continue
        # 今日收紅且站回 MA10
        if not (tc > to_ and tc > m10):
            continue
        # 近1~4天有一天收盤跌破 MA10
        broke_idx = None
        for i in range(1, 5):
            if i + 1 > len(closes):
                break
            pm10 = float(ma10.iloc[-(i+1)])
            if not pd.isna(pm10) and float(closes.iloc[-(i+1)]) < pm10:
                broke_idx = i
                break
        if broke_idx is None:
            continue
        # 跌破當天量 ≤ 20日均量 × 2.5（非出貨）
        vol20 = df.iloc[-20:]['volume'].astype(float).mean() if len(df) >= 20 else 0
        broke_vol = float(df.iloc[-(broke_idx+1)].get('volume', 0) or 0)
        if vol20 > 0 and broke_vol > vol20 * 2.5:
            continue
        # 今日收盤吃回跌破那天的收盤
        if tc <= float(closes.iloc[-(broke_idx+1)]):
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(tc, 2), "change_pct": _change_pct(df),
                        "volume": round(vol), "bb_score": calc_bb_score(df),
                        "strategy": "S_FBD"})
    return results


def screen_sres(prices: dict, names: dict = None) -> list:
    """S_RES 共振起點：MA10/MA60 近期由空翻多，三線同時轉揚"""
    results = []
    for sid, df in prices.items():
        if len(df) < 65:
            continue
        closes = df['close']
        today  = df.iloc[-1]
        tc     = float(today['close'])
        if tc <= 10:
            continue
        vol = float(today.get('volume', 0) or 0)
        if vol < 300_000:
            continue
        ma10 = calc_ma(closes, 10)
        ma60 = calc_ma(closes, 60)
        m10  = float(ma10.iloc[-1])
        m60  = float(ma60.iloc[-1])
        if pd.isna(m10) or pd.isna(m60):
            continue
        # 收盤在兩條均線上方
        if not (tc > m10 and tc > m60):
            continue
        # MA10 斜率向上（近5天）
        if pd.isna(ma10.iloc[-6]) or not (m10 > float(ma10.iloc[-6])):
            continue
        # MA60 斜率向上（近10天）
        if pd.isna(ma60.iloc[-11]) or not (m60 > float(ma60.iloc[-11])):
            continue
        # 現在 MA10 > MA60（剛翻多）
        if not (m10 > m60):
            continue
        # 近15天內 MA10 曾在 MA60 下方（確認是轉折，不是長期多頭延續）
        was_below = any(
            not pd.isna(ma10.iloc[-(i+1)]) and not pd.isna(ma60.iloc[-(i+1)])
            and float(ma10.iloc[-(i+1)]) < float(ma60.iloc[-(i+1)])
            for i in range(1, 16) if i + 1 <= len(ma10)
        )
        if not was_below:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(tc, 2), "change_pct": _change_pct(df),
                        "volume": round(vol), "bb_score": calc_bb_score(df),
                        "strategy": "S_RES"})
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


def screen_skd(prices: dict, names: dict = None) -> list:
    """
    S_KD KD超賣反彈：
    1. 收盤 > 10，量 >= 300張
    2. KD 的 K 值在近 1~5 天曾跌破 20（超賣區）
    3. 今日 K 值回升至 20 以上（離開超賣區）
    4. K 上穿 D（黃金交叉，或 K > D 且方向向上）
    """
    results = []
    for sid, df in prices.items():
        if len(df) < 30:
            continue
        if 'high' not in df.columns or 'low' not in df.columns:
            continue
        today = df.iloc[-1]
        tc    = float(today['close'])
        if tc <= 10:
            continue
        vol = float(today.get('volume', 0) or 0)
        if vol < 300_000:
            continue
        k_ser, d_ser = calc_kd(df)
        k_now = k_ser.iloc[-1]
        d_now = d_ser.iloc[-1]
        # 今日 K 必須已回到 20 以上
        if k_now <= 20:
            continue
        # 近 1~5 天（不含今日）K 曾 <= 20
        broke_oversold = any(
            k_ser.iloc[-(i+1)] <= 20
            for i in range(1, 6) if i + 1 <= len(k_ser)
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


def screen_svolx(prices: dict, names: dict = None) -> list:
    """S_VOLX 量爆拉升（多）：今日量 >= 昨日量 × 3 且上漲且站上20週均線(MA100)"""
    results = []
    for sid, df in prices.items():
        if len(df) < 101:
            continue
        today = df.iloc[-1]
        prev  = df.iloc[-2]
        tc  = float(today['close'])
        pc  = float(prev['close'])
        vol     = float(today.get('volume', 0) or 0)
        vol_yd  = float(prev.get('volume', 0) or 0)
        if tc <= 10:
            continue
        if vol_yd <= 0 or vol < vol_yd * 3:
            continue
        if tc <= pc:
            continue
        ma100 = float(calc_ma(df['close'], 100).iloc[-1])
        if pd.isna(ma100) or tc <= ma100:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(tc, 2), "change_pct": _change_pct(df),
                        "volume": round(vol), "bb_score": calc_bb_score(df),
                        "vol_ratio": round(vol / vol_yd, 1),
                        "strategy": "S_VOLX"})
    return results


def screen_svolx_short(prices: dict, names: dict = None) -> list:
    """S_VOLX_SHORT 量爆下殺（空）：今日量 >= 昨日量 × 3 且下跌且跌破20週均線(MA100)"""
    results = []
    for sid, df in prices.items():
        if len(df) < 101:
            continue
        today = df.iloc[-1]
        prev  = df.iloc[-2]
        tc  = float(today['close'])
        pc  = float(prev['close'])
        vol     = float(today.get('volume', 0) or 0)
        vol_yd  = float(prev.get('volume', 0) or 0)
        if tc <= 10:
            continue
        if vol_yd <= 0 or vol < vol_yd * 3:
            continue
        if tc >= pc:
            continue
        ma100 = float(calc_ma(df['close'], 100).iloc[-1])
        if pd.isna(ma100) or tc >= ma100:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(tc, 2), "change_pct": _change_pct(df),
                        "volume": round(vol), "bb_score": calc_bb_score(df),
                        "vol_ratio": round(vol / vol_yd, 1),
                        "strategy": "S_VOLX_SHORT"})
    return results


def screen_chip(prices: dict, tdcc_data: dict, stock_info: dict = None) -> list:
    """
    CHIP 千張大戶增持選股（集保所週資料）：
    - 千張大戶本週持股比例 > 上週（change > 0）
    - MA5 > MA10 > MA20
    - 收盤 > 10
    - 同族群上漲比 >= 50%（有傳入 stock_info 且有 industry 時才套用）
    """
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
        # 需連續兩週增加（有第三週資料才嚴格要求，否則退回單週）
        if tdcc.get('consec_up', 1) < 1:
            continue
        closes = df['close']
        today  = df.iloc[-1]
        if float(today['close']) <= 10:
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
        if ind and ratio < 0.50:
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

def scan_one_stock(df: pd.DataFrame, sid: str, name: str = "") -> dict:
    """
    檢查單支股票的所有策略，回傳 {strategy_key: result_dict or None}。
    供全市場掃描使用：一次抓取 → 同時跑所有策略，避免重複請求。
    """
    prices_single = {sid: df}
    names_single  = {sid: name}
    last_date = str(df.iloc[-1].get('date', '')) if not df.empty else ''
    out = {}
    for key, fn in [
        ("S1",       screen_s1),
        ("S1_SHORT", screen_s1_short),
        ("S1_2",     screen_s1_2),
        ("S2",       screen_s2),
        ("S5",       screen_s5),
        ("S17A",     screen_s17a),
        ("S17B",     screen_s17b),
        ("S10",      screen_s10),
        ("S_PB",     screen_spb),
        ("S_FBD",    screen_sfbd),
        ("S_RES",    screen_sres),
        ("S_KD",          screen_skd),
        ("S_VOLX",        screen_svolx),
        ("S_VOLX_SHORT",  screen_svolx_short),
    ]:
        results = fn(prices_single, names_single)
        result = results[0] if results else None
        if result and last_date:
            result['last_date'] = last_date  # YYYYMMDD，讓 UI 顯示資料日期
        out[key] = result
    return out


def run_strategy(strategy: str, prices: dict, names: dict = None,
                 chip_data: list = None, stock_info: dict = None) -> list:
    s = strategy.upper()
    fn_map = {
        "S1":       screen_s1,
        "S1_SHORT": screen_s1_short,
        "S1_2":     screen_s1_2,
        "S2":       screen_s2,
        "S5":       screen_s5,
        "S17A":     screen_s17a,
        "S17B":     screen_s17b,
        "S10":      screen_s10,
        "S_PB":     screen_spb,
        "S_FBD":    screen_sfbd,
        "S_RES":    screen_sres,
        "S_KD":          screen_skd,
        "S_VOLX":        screen_svolx,
        "S_VOLX_SHORT":  screen_svolx_short,
    }
    if s == "CHIP":
        return screen_chip(prices, chip_data or {}, stock_info)
    fn = fn_map.get(s)
    return fn(prices, names) if fn else []
