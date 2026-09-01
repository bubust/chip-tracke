"""
scanner.py - 策略選股引擎
S1多、S1空、S1.2、S2(W底)、S5(站上均線)、S17a、S17b、S10(漲停)、CHIP(主力)
"""
import pandas as pd

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

def screen_s1(prices: dict, names: dict = None) -> list:
    """S1 雙MACD選股（多）"""
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
        recent20 = osc1.iloc[-22:-1]
        if osc1.iloc[-2] > recent20.min() + 1e-9:
            continue
        if abs(osc1.iloc[-1]) >= abs(osc1.iloc[-2]):
            continue
        if dif2.iloc[-1] <= 0 or dea2.iloc[-1] <= 0 or osc2.iloc[-1] <= 0:
            continue
        if float(today['close']) < float(closes.iloc[-11:-1].min()):
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2), "strategy": "S1"})
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
        recent20 = osc1.iloc[-22:-1]
        if osc1.iloc[-2] < recent20.max() - 1e-9:
            continue
        if abs(osc1.iloc[-1]) >= abs(osc1.iloc[-2]):
            continue
        if dif2.iloc[-1] >= 0 or dea2.iloc[-1] >= 0 or osc2.iloc[-1] >= 0:
            continue
        if float(today['close']) > float(closes.iloc[-11:-1].max()):
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2), "strategy": "S1_SHORT"})
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
                        "close": round(float(today['close']), 2), "strategy": "S1_2"})
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
        if float(vol) < 300:
            continue
        ma10  = calc_ma(closes, 10)
        ma60  = calc_ma(closes, 60)
        ma200 = calc_ma(closes, 200)
        if any(pd.isna(x.iloc[-1]) for x in [ma10, ma60, ma200]):
            continue
        if not (ma10.iloc[-1] > ma60.iloc[-1] > ma200.iloc[-1]):
            continue
        if not (ma10.iloc[-1] > ma10.iloc[-2] and
                ma60.iloc[-1] > ma60.iloc[-2] and
                ma200.iloc[-1] > ma200.iloc[-2]):
            continue
        sub60 = closes.iloc[-61:]
        high_idx_in_sub = sub60.idxmax()
        days_from_high = len(closes) - 1 - high_idx_in_sub
        if not (10 <= days_from_high <= 14):
            continue
        db = find_double_bottom(df, lookback=40)
        if db is None:
            continue
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(float(today['close']), 2), "strategy": "S2"})
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
                        "close": round(c, 2), "strategy": "S5"})
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
                        "close": round(float(today['close']), 2), "strategy": "S17A"})
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
                        "neckline": round(neckline, 2)})
    return results

def screen_s10(prices: dict, names: dict = None) -> list:
    """S10 漲停（漲幅 >= 9.8%，顯示連續天數）"""
    results = []
    for sid, df in prices.items():
        if len(df) < 2:
            continue
        prev_c = float(df.iloc[-2]['close'])
        if prev_c <= 0:
            continue
        c = float(df.iloc[-1]['close'])
        change_pct = (c - prev_c) / prev_c * 100
        if change_pct < 9.8:
            continue
        consec = 1
        for i in range(len(df) - 2, 0, -1):
            c_i   = float(df.iloc[i]['close'])
            c_pre = float(df.iloc[i - 1]['close'])
            if c_pre <= 0:
                break
            if (c_i - c_pre) / c_pre * 100 >= 9.8:
                consec += 1
            else:
                break
        results.append({"stock_id": sid, "name": _name(sid, names),
                        "close": round(c, 2),
                        "change_pct": round(change_pct, 2),
                        "consec_limit_up": consec,
                        "strategy": "S10"})
    results.sort(key=lambda x: x['change_pct'], reverse=True)
    return results

def screen_chip(prices: dict, chip_data: list, stock_info: dict = None) -> list:
    """主力籌碼選股：法人買超>200張 + MA5>MA10>MA20 + 同族群上漲>50%"""
    chip_map = {r['stock_id']: r for r in (chip_data or [])}
    up_map = {}
    for sid, df in prices.items():
        if len(df) >= 2:
            up_map[sid] = float(df.iloc[-1]['close']) > float(df.iloc[-2]['close'])
    sector_sids = {}
    if stock_info:
        for sid, info in stock_info.items():
            ind = info.get('industry') or '未分類'
            sector_sids.setdefault(ind, []).append(sid)
    sector_ratio = {}
    for ind, sids in sector_sids.items():
        up = sum(1 for s in sids if up_map.get(s, False))
        sector_ratio[ind] = up / len(sids) if sids else 0
    results = []
    for sid, df in prices.items():
        if len(df) < 25:
            continue
        chip = chip_map.get(sid)
        if not chip or chip.get('whale_flow_lots', 0) < 200:
            continue
        closes = df['close']
        today = df.iloc[-1]
        if float(today['close']) <= 10:
            continue
        ma5  = calc_ma(closes, 5)
        ma10 = calc_ma(closes, 10)
        ma20 = calc_ma(closes, 20)
        if any(pd.isna(x.iloc[-1]) for x in [ma5, ma10, ma20]):
            continue
        if not (ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]):
            continue
        info = (stock_info or {}).get(sid, {})
        ind = info.get('industry', '')
        ratio = sector_ratio.get(ind, 0) if ind else 0
        if ind and ratio < 0.50:
            continue
        results.append({
            "stock_id": sid,
            "name": info.get('name') or chip.get('name', ''),
            "close": round(float(today['close']), 2),
            "whale_flow_lots": chip.get('whale_flow_lots', 0),
            "retail_flow_lots": chip.get('retail_flow_lots', 0),
            "industry": ind,
            "sector_up_ratio": round(ratio * 100, 1),
            "strategy": "CHIP",
        })
    results.sort(key=lambda x: x['whale_flow_lots'], reverse=True)
    return results

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
    }
    if s == "CHIP":
        return screen_chip(prices, chip_data or [], stock_info)
    fn = fn_map.get(s)
    return fn(prices, names) if fn else []
