"""
scanner_course.py — 上課筆記的技術面選股（2026-10-04 新增，不改動舊策略）

做多：
  S_WMACD     週 MACD(10,20,50)：大跌後站回 20 週線＋週柱由綠翻紅（長線大波段）
  S_BIAS      負乖離抄底：60BIAS（或 20BIAS）≤ −20%，附定海神針／向上跳空確認
  S_RSI_OS    RSI(6) 跌破 20 後第一次勾起突破 20（短線跌深反彈）
  S_RSI_HOT   RSI(6) ≥ 80 連 3 天以上（第一次高檔鈍化），打橫盤整靠近 5 日線
  S_BB1       布林(20, 1 倍標準差)：開布林大漲、收在上軌之外（飆股抱牢，跌回上軌內出場）
  S_GAP_BOTTOM 急跌爆天量後出現第一個向上跳空缺口（收盤不補）
  S_LIMIT_OPEN 連續跳空漲停後爆大量打開
做空／避險：
  S_W60_BREAK 跌破 60 週均線（翻空）
  S_MA_ALLDOWN 跌破 5/10/20/60 日線且四條均線下彎
  S_DANGER    危險量（觸及歷史高點量）＋高檔第一個往下跳空缺口
第二份筆記（2026-10-04）：
  做多 S_KDJ_LOW 低檔金叉、S_BREAKBOTTOM 破底翻、S_NBREAK N 字關鍵價突破、S_VOLROLL 底部量滾量
  出場 S_KDJ_HIGH 高檔死叉、S_KDJ_DIV 高檔背離

每個結果都帶 stop（停損／防守價）與 note（進出場提醒），畫面欄位可排序。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd



# scanner 的共用函式（scanner.py 底部會 import 本檔登記策略 → 用延遲取用避免循環 import）
def _change_pct(df):
    return _sc._change_pct(df)


def _is_limit_up(c, pc):
    return _sc._is_limit_up(c, pc)


def _name(sid, names):
    return _sc._name(sid, names)


def calc_bb_score(df):
    return _sc.calc_bb_score(df)


def calc_ma(s, n):
    return _sc.calc_ma(s, n)


def calc_macd(s, f, sl, sig):
    return _sc.calc_macd(s, f, sl, sig)


def _r(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else round(x, nd)


def _base(sid, df, names, key, **extra):
    last = df.iloc[-1]
    d = {"stock_id": sid, "name": _name(sid, names), "close": round(float(last["close"]), 2),
         "change_pct": _change_pct(df), "volume": round(float(last.get("volume", 0) or 0)),
         "bb_score": calc_bb_score(df), "strategy": key}
    d.update(extra)
    return d


def rsi(close: pd.Series, n: int = 6) -> pd.Series:
    """Wilder RSI"""
    diff = close.diff()
    up = diff.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-diff.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0)


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    """日 K → 週 K（以 ISO 週分組；本週未完成也算一根）"""
    d = df.copy()
    dt = pd.to_datetime(d["date"].astype(str).str.replace("-", ""), format="%Y%m%d", errors="coerce")
    d = d[dt.notna()]
    dt = dt[dt.notna()]
    iso = dt.dt.isocalendar()
    d["_wk"] = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    g = d.groupby("_wk", sort=True)
    w = pd.DataFrame({"date": g["date"].last(), "open": g["open"].first(), "high": g["high"].max(),
                      "low": g["low"].min(), "close": g["close"].last(), "volume": g["volume"].sum()})
    return w.reset_index(drop=True)


def _ok_price(df, p, n):
    return len(df) >= n and float(df.iloc[-1]["close"]) >= float(p.get("min_price", 10))


# ── 做多 ─────────────────────────────────────────────────────────────────────

def screen_wmacd(prices, names=None, params=None):
    """週 MACD(10,20,50) 由綠翻紅＋站上 20 週線，且之前有波段大跌（近 52 週高點回落 ≥ drop_pct%、曾跌破 20 週線）"""
    p = params or {}
    drop = float(p.get("drop_pct", 25)) / 100
    within = int(p.get("flip_within", 1))           # 翻紅發生在最近幾週內
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 150):
            continue
        w = weekly(df)
        if len(w) < 30:
            continue
        c = w["close"]
        ma20 = calc_ma(c, 20)
        _, _, osc = calc_macd(c, 10, 20, 50)
        if pd.isna(ma20.iloc[-1]) or c.iloc[-1] <= ma20.iloc[-1]:
            continue
        flip = None
        for k in range(1, within + 1):
            if osc.iloc[-k] > 0 and osc.iloc[-k - 1] <= 0:
                flip = k
                break
        if flip is None or osc.iloc[-1] <= 0:
            continue
        look = w.iloc[-52:]
        hi = float(look["high"].max())
        lo = float(look["low"].min())
        if hi <= 0 or (hi - lo) / hi < drop:
            continue
        if not (c.iloc[-26:] < ma20.iloc[-26:]).any():          # 之前曾在 20 週線下（大跌後才「重新站上」）
            continue
        ma60 = calc_ma(c, 60).iloc[-1]
        out.append(_base(sid, df, names, "S_WMACD", ma20w=_r(ma20.iloc[-1]), ma60w=_r(ma60),
                         w_osc=_r(osc.iloc[-1], 3), drawdown_pct=_r((hi - lo) / hi * 100, 1),
                         stop=_r(ma20.iloc[-1]),
                         note="週 K 抱牢：沒跌破 20 週線、週 MACD 沒翻綠就續抱；任一發生全數出場"))
    return out


def screen_bias(prices, names=None, params=None):
    """負乖離 ≤ −20%（預設 60 日＝季線），附確認訊號：定海神針（長下影不破低）／第一個向上跳空"""
    p = params or {}
    n = int(p.get("ma_period", 60))
    th = -abs(float(p.get("bias_pct", 20)))
    need_confirm = bool(int(p.get("need_confirm", 0)))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, n + 5):
            continue
        c = df["close"].astype(float)
        ma = calc_ma(c, n)
        bias = (c / ma - 1) * 100
        recent = bias.iloc[-3:]
        if recent.isna().all() or recent.min() > th:
            continue
        o, h, l = (df[k].astype(float) for k in ("open", "high", "low"))
        conf = []
        # 定海神針：最近 3 根內，下影線 ≥ 實體 2 倍、≥ 全長 50%，之後沒跌破它的低點
        for i in range(len(df) - 3, len(df)):
            body = abs(c.iloc[i] - o.iloc[i])
            rng = h.iloc[i] - l.iloc[i]
            lower = min(c.iloc[i], o.iloc[i]) - l.iloc[i]
            pin = rng > 0 and lower >= max(body * 2, rng * 0.5)
            after = l.iloc[i + 1:]
            if pin and (after.empty or after.min() >= l.iloc[i]):
                conf.append("定海神針")
                break
        if l.iloc[-1] > h.iloc[-2] or l.iloc[-2] > h.iloc[-3]:
            conf.append("向上跳空")
        if need_confirm and not conf:
            continue
        low = float(l.iloc[-5:].min())
        out.append(_base(sid, df, names, "S_BIAS", bias=_r(bias.iloc[-1], 1), bias_min=_r(recent.min(), 1),
                         confirm="、".join(conf) or "—", stop=_r(max(low, float(c.iloc[-1]) * 0.9)),
                         note=f"{n}日負乖離 {recent.min():.1f}%：分批布局（每跌 3~5% 一次）或 10% 硬停損；跌破當日低／前低停損"))
    return out


def screen_rsi_os(prices, names=None, params=None):
    """RSI(6) 掉到 20 以下後，今天重新突破 20；只取這段下跌的第一次勾起"""
    p = params or {}
    lv = float(p.get("level", 20))
    look = int(p.get("first_lookback", 20))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 30):
            continue
        r6 = rsi(df["close"].astype(float), 6)
        if not (r6.iloc[-2] < lv <= r6.iloc[-1]):
            continue
        prev = r6.iloc[-look - 1:-1]
        crosses = ((prev.shift(1) < lv) & (prev >= lv)).sum()
        if crosses > 0:                                  # 之前已經勾起過 → 第二次以後無效
            continue
        low = float(df["low"].astype(float).iloc[-look:].min())
        out.append(_base(sid, df, names, "S_RSI_OS", rsi6=_r(r6.iloc[-1], 1), rsi6_min=_r(r6.iloc[-look:].min(), 1),
                         stop=_r(low), note="跌破前波低點立刻出場；不加碼、不攤平"))
    return out


def screen_rsi_hot(prices, names=None, params=None):
    """RSI(6) ≥ 80 連續 ≥ 3 天（第一次高檔鈍化），近 3 天打橫盤整、收盤靠近且在 5 日線上"""
    p = params or {}
    lv = float(p.get("level", 80))
    days = int(p.get("min_days", 3))
    flat = float(p.get("flat_pct", 4)) / 100
    near = float(p.get("ma5_near_pct", 3)) / 100
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 70):
            continue
        c = df["close"].astype(float)
        r6 = rsi(c, 6)
        streak = 0
        for v in reversed(r6.values):
            if v >= lv:
                streak += 1
            else:
                break
        if streak < days:
            continue
        # 第一次：這段鈍化之前 60 天內沒有另一段 ≥ days 天的鈍化
        before = r6.iloc[:-streak].iloc[-60:].values
        run, other = 0, False
        for v in before:
            run = run + 1 if v >= lv else 0
            if run >= days:
                other = True
                break
        if other:
            continue
        last3 = c.iloc[-3:]
        if (last3.max() - last3.min()) / last3.min() > flat:
            continue
        ma5 = calc_ma(c, 5).iloc[-1]
        if c.iloc[-1] < ma5 or c.iloc[-1] > ma5 * (1 + near):
            continue
        out.append(_base(sid, df, names, "S_RSI_HOT", rsi6=_r(r6.iloc[-1], 1), hot_days=streak, ma5=_r(ma5),
                         stop=_r(ma5), note="跌破 5 日線出場；只做第一次高檔鈍化"))
    return out


def screen_bb1(prices, names=None, params=None):
    """布林(20, k=1)：收在上軌之外，且布林正在打開（帶寬比 5 天前擴大）"""
    p = params or {}
    n, k = int(p.get("period", 20)), float(p.get("k", 1))
    expand = float(p.get("expand", 1.2))
    rise = float(p.get("rise_pct", 10)) / 100
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, n + 10):
            continue
        c = df["close"].astype(float)
        mid = calc_ma(c, n)
        sd = c.rolling(n).std(ddof=0)
        up = mid + k * sd
        if pd.isna(up.iloc[-1]) or c.iloc[-1] <= up.iloc[-1]:
            continue
        if sd.iloc[-6] <= 0 or sd.iloc[-1] < sd.iloc[-6] * expand:
            continue
        if c.iloc[-1] < c.iloc[-21] * (1 + rise):                # 開布林「大漲」：20 天漲幅門檻
            continue
        streak = 0
        for i in range(len(c) - 1, -1, -1):
            if not pd.isna(up.iloc[i]) and c.iloc[i] > up.iloc[i]:
                streak += 1
            else:
                break
        out.append(_base(sid, df, names, "S_BB1", bb_upper=_r(up.iloc[-1]), above_days=streak,
                         width_x=_r(sd.iloc[-1] / sd.iloc[-6], 2), stop=_r(up.iloc[-1]),
                         note="收在上軌外續抱；收盤跌回上軌內立即出場"))
    return out


def screen_gap_bottom(prices, names=None, params=None):
    """急跌（距 120 日高 ≥ drop_pct%）中出現資料期間最大量（換手天量），之後出現第一個向上跳空缺口且沒補"""
    p = params or {}
    drop = float(p.get("drop_pct", 25)) / 100
    vol_win = int(p.get("vol_within", 20))
    gap_win = int(p.get("gap_within", 5))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 150):
            continue
        h, l, v = (df[k].astype(float).values for k in ("high", "low", "volume"))
        n = len(df)
        vi = n - vol_win + int(np.argmax(v[-vol_win:]))
        if v[vi] < v[:max(1, n - vol_win)].max():         # 不是資料期間（約 1~2 年）最大量
            continue
        hi120 = h[max(0, vi - 120):vi + 1].max()
        if hi120 <= 0 or (hi120 - l[vi]) / hi120 < drop:
            continue
        gap = None
        for i in range(vi + 1, n):
            if l[i] > h[i - 1]:
                gap = i
                break                                       # 只看第一個缺口
        if gap is None or gap < n - gap_win:
            continue
        if l[gap:].min() <= h[gap - 1]:                     # 缺口被回補
            continue
        out.append(_base(sid, df, names, "S_GAP_BOTTOM", big_vol_date=str(df["date"].iloc[vi]),
                         big_vol_x=_r(v[vi] / max(np.mean(v[max(0, vi - 20):vi]), 1), 1),
                         gap_date=str(df["date"].iloc[gap]), gap_low=_r(h[gap - 1]),
                         stop=_r(h[gap - 1]), note="以缺口下緣（或缺口當日低點）為停損防守"))
    return out


def screen_limit_open(prices, names=None, params=None):
    """前面連續 ≥ 2 天跳空漲停（開高就漲停、量縮），今天爆量（≥ 昨量 × vol_mult）打開沒收在漲停"""
    p = params or {}
    need = int(p.get("min_limit_days", 2))
    mult = float(p.get("vol_mult", 3))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, need + 3):
            continue
        c, o, v = (df[k].astype(float).values for k in ("close", "open", "volume"))
        n = len(df)
        cnt = 0
        for i in range(n - 2, 0, -1):
            if _is_limit_up(c[i], c[i - 1]) and o[i] > c[i - 1] * 1.05:
                cnt += 1
            else:
                break
        if cnt < need:
            continue
        if _is_limit_up(c[-1], c[-2]) or v[-2] <= 0 or v[-1] < v[-2] * mult:
            continue
        out.append(_base(sid, df, names, "S_LIMIT_OPEN", limit_days=cnt, vol_x=_r(v[-1] / v[-2], 1),
                         stop=_r(df["low"].iloc[-1]),
                         note="先確認是真的基本面／財報利多；分批掛單，以爆量當日低點停損"))
    return out


# ── 做空／避險 ───────────────────────────────────────────────────────────────

def screen_w60_break(prices, names=None, params=None):
    """週收盤跌破 60 週均線（上週還在線上）"""
    p = params or {}
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 290):
            continue
        w = weekly(df)
        if len(w) < 62:
            continue
        c = w["close"]
        ma60 = calc_ma(c, 60)
        if pd.isna(ma60.iloc[-2]) or not (c.iloc[-1] < ma60.iloc[-1] and c.iloc[-2] >= ma60.iloc[-2]):
            continue
        out.append(_base(sid, df, names, "S_W60_BREAK", ma60w=_r(ma60.iloc[-1]),
                         below_pct=_r((c.iloc[-1] / ma60.iloc[-1] - 1) * 100, 1),
                         stop=_r(ma60.iloc[-1]), note="跌破 60 週線即翻空：持股出場／不再做多"))
    return out


def screen_ma_alldown(prices, names=None, params=None):
    """收盤跌破 5/10/20/60 日線，四條均線都下彎（今天 < 5 天前），今天才剛形成（昨天還沒全破）"""
    p = params or {}
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 70):
            continue
        c = df["close"].astype(float)
        mas = {k: calc_ma(c, k) for k in (5, 10, 20, 60)}
        below = lambda i: all(c.iloc[i] < m.iloc[i] for m in mas.values())
        if not below(-1) or below(-2):
            continue
        if not all(m.iloc[-1] < m.iloc[-6] for m in mas.values()):
            continue
        out.append(_base(sid, df, names, "S_MA_ALLDOWN", ma60=_r(mas[60].iloc[-1]),
                         stop=_r(max(m.iloc[-1] for m in mas.values())),
                         note="跌破所有短中長均線且下彎：翻空，持股出場"))
    return out


def screen_danger(prices, names=None, params=None):
    """高檔（距一年高點 ≤ 10%）近 5 天量觸及資料期間最大量的 90%（危險量）、高點不過前高；
    若再出現第一個往下跳空缺口 → 強烈賣訊"""
    p = params or {}
    ratio = float(p.get("vol_ratio", 0.9))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 200):
            continue
        h, l, c, v = (df[k].astype(float).values for k in ("high", "low", "close", "volume"))
        n = len(df)
        hi = h[-250:].max()
        if c[-1] < hi * 0.9:
            continue
        hist_max = v[:n - 5].max()
        vmax5 = v[-5:].max()
        if hist_max <= 0 or vmax5 < hist_max * ratio:
            continue
        stall = h[-5:].max() <= h[:n - 5][-60:].max() * 1.01      # 爆量但高點不過前高（滯漲）
        gap = next((i for i in range(n - 5, n) if h[i] < l[i - 1]), None)
        if not stall and gap is None:
            continue
        level = "空方缺口（強烈賣訊）" if gap is not None else "危險量預警"
        out.append(_base(sid, df, names, "S_DANGER", level=level, vol_vs_max=_r(vmax5 / hist_max, 2),
                         year_high=_r(hi), gap_date=str(df["date"].iloc[gap]) if gap is not None else "",
                         stop=_r(hi), note="危險量＋高點不過：減碼預警；高檔第一個往下跳空缺口：反轉賣訊／放空點"))
    return out


# ── 2026-10-04 上課筆記（第二份）：KDJ、破底翻、N 字突破、底部量滾量 ───────────────

def kdj(df: pd.DataFrame, n: int = 9):
    """KDJ(9,3,3)：K、D 從 50 起算，J = 3K − 2D"""
    c, h, l = (df[k].astype(float).values for k in ("close", "high", "low"))
    hn = pd.Series(h).rolling(n, min_periods=1).max().values
    ln = pd.Series(l).rolling(n, min_periods=1).min().values
    rng = hn - ln
    rsv = np.where(rng > 0, (c - ln) / np.where(rng > 0, rng, 1) * 100, 50.0)
    k = np.empty(len(c))
    d = np.empty(len(c))
    pk = pdv = 50.0
    for i, r in enumerate(rsv):
        pk = pk * 2 / 3 + r / 3
        pdv = pdv * 2 / 3 + pk / 3
        k[i], d[i] = pk, pdv
    return k, d, 3 * k - 2 * d


def screen_kdj_low(prices, names=None, params=None):
    """KDJ 低檔轉強：大跌修正後 K、D < 20 且 J 曾 < 0，今天 J 往上穿越 K 與 D（黃金交叉）"""
    p = params or {}
    drop = float(p.get("drop_pct", 20)) / 100
    lv, within = float(p.get("level", 20)), int(p.get("j_within", 3))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 70):
            continue
        k, d, j = kdj(df)
        if not (j[-1] > k[-1] and j[-1] > d[-1] and (j[-2] <= k[-2] or j[-2] <= d[-2])):
            continue
        if not (k[-2] < lv and d[-2] < lv) or j[-within - 1:-1].min() >= 0:
            continue
        h, l, v = (df[x].astype(float).values for x in ("high", "low", "volume"))
        hi60 = h[-60:].max()
        if hi60 <= 0 or (hi60 - l[-10:].min()) / hi60 < drop:
            continue
        gap = j[-1] - max(k[-1], d[-1])
        big = v[-1] >= v[-21:-1].mean() * 2
        out.append(_base(sid, df, names, "S_KDJ_LOW", k=_r(k[-1], 1), d=_r(d[-1], 1), j=_r(j[-1], 1),
                         j_open=_r(gap, 1), stop=_r(l[-20:].min()), day_low=_r(l[-1]), big_vol="爆量" if big else "",
                         drop_pct=_r((hi60 - l[-10:].min()) / hi60 * 100, 1),
                         note=("J 跟 K、D 黏在一起、開口不明顯 → 多觀察一天確認" if gap < 5 else "極端超賣區轉折買點")
                              + ("；今天爆量，停損可設今天低點" if big else "") + "；停損：前波最低點"))
    return out


def screen_breakbottom(prices, names=None, params=None):
    """破底翻：跌深後昨天一根長黑收在最低（破近期低），今天守住昨天低點沒再破底"""
    p = params or {}
    drop = float(p.get("drop_pct", 20)) / 100
    body = float(p.get("body_pct", 3)) / 100
    nl = int(p.get("new_low_days", 20))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 65):
            continue
        o, h, l, c = (df[x].astype(float).values for x in ("open", "high", "low", "close"))
        if not (o[-2] > c[-2] and (o[-2] - c[-2]) / c[-3] >= body):          # 昨天長黑
            continue
        if c[-2] > l[-2] + (h[-2] - l[-2]) * 0.15:                          # 收在最低附近
            continue
        if c[-2] > c[-nl - 2:-2].min():                                      # 破近期收盤低點
            continue
        hi = h[-62:-1].max()
        if hi <= 0 or (hi - c[-2]) / hi < drop:
            continue
        if l[-1] < l[-2]:                                                    # 今天又破底 → 失敗
            continue
        out.append(_base(sid, df, names, "S_BREAKBOTTOM", black_low=_r(l[-2]),
                         black_pct=_r((c[-2] - o[-2]) / c[-3] * 100, 1), drop_pct=_r((hi - c[-2]) / hi * 100, 1),
                         stop=_r(l[-2]), note="急跌末端賣壓被吸收的反彈點；停損設在長黑最低點，之後跌破就失效"))
    return out


def _neck_break(o, h, l, c, v, b, p):
    """第 b 根是否為「長紅帶量突破頸線」；回傳頸線價或 None。頸線＝b 之前 look 天內的波段高點"""
    look, rally = int(p.get("look", 60)), float(p.get("rally_pct", 20)) / 100
    pull, body, vm = float(p.get("pull_pct", 5)) / 100, float(p.get("body_pct", 2)) / 100, float(p.get("vol_mult", 1.5))
    if b < look + 25:
        return None
    seg = h[b - look:b - 4]
    pi = b - look + int(np.argmax(seg))
    neck = h[pi]
    if c[b - 1] > neck or c[pi + 1:b].max() > neck:                        # 之前還沒站上頸線
        return None
    lo0 = l[max(0, pi - look):pi + 1].min()
    if lo0 <= 0 or neck / lo0 - 1 < rally:                                  # 頸線前有一段大漲
        return None
    if (neck - l[pi + 1:b].min()) / neck < pull:                            # 之後有拉回整理
        return None
    if c[b] <= neck or c[b] <= o[b] or (c[b] - o[b]) / c[b - 1] < body:      # 長紅實體突破
        return None
    avg = v[b - 20:b].mean()
    if avg <= 0 or v[b] < avg * vm:
        return None
    return float(neck)


def screen_nbreak(prices, names=None, params=None):
    """關鍵價突破（N 字）：大漲→拉回整理→長紅帶量實體突破前波高點（頸線）；或突破後回測頸線守住"""
    p = params or {}
    within = int(p.get("retest_within", 10))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 90):
            continue
        o, h, l, c, v = (df[x].astype(float).values for x in ("open", "high", "low", "close", "volume"))
        n = len(df)
        neck, stage, bday = _neck_break(o, h, l, c, v, n - 1, p), "突破當天（積極進場）", n - 1
        if neck is None:
            for b in range(n - 2, max(n - 1 - within, 0), -1):
                nk = _neck_break(o, h, l, c, v, b, p)
                if nk is None:
                    continue
                if l[b + 1:].min() >= nk * 0.97 and l[-1] <= nk * 1.03 and c[-1] >= nk:
                    neck, stage, bday = nk, "回測頸線守住（保守進場）", b
                break
        if neck is None:
            continue
        out.append(_base(sid, df, names, "S_NBREAK", stage=stage, neckline=_r(neck),
                         break_date=str(df["date"].iloc[bday]), above_pct=_r((c[-1] / neck - 1) * 100, 1),
                         stop=_r(neck), note="跌回頸線下方停損"))
    return out


def screen_volroll(prices, names=None, params=None):
    """底部量滾量：長期跌深盤整後重新站上季線（60MA），近幾天連續爆量（≥ 前期均量 vol_mult 倍）"""
    p = params or {}
    drop = float(p.get("drop_pct", 25)) / 100
    vm, rd, cw = float(p.get("vol_mult", 2)), int(p.get("roll_days", 3)), int(p.get("cross_within", 5))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 200) or float(df.iloc[-1].get("volume", 0) or 0) < float(p.get("min_vol_lots", 500)):
            continue
        h, l, c, v = (df[x].astype(float).values for x in ("high", "low", "close", "volume"))
        ma60 = calc_ma(df["close"].astype(float), 60).values
        if np.isnan(ma60[-1]) or c[-1] <= ma60[-1]:
            continue
        if not any(c[i] <= ma60[i] for i in range(len(c) - cw - 1, len(c) - 1)):   # 最近才重新站上
            continue
        prior = slice(-60 - cw, -cw)
        if np.mean(c[prior] < ma60[prior]) < 0.6:                                   # 之前長期在季線下
            continue
        hi = h[-250:].max()
        if hi <= 0 or (hi - l[-120:].min()) / hi < drop:
            continue
        base = v[-60 - rd:-rd].mean()
        rec = v[-rd:]
        if base <= 0 or rec.mean() < base * vm or (rec >= base * vm).sum() < max(2, rd - 1):
            continue
        bi = len(df) - rd + int(np.argmax(rec))
        out.append(_base(sid, df, names, "S_VOLROLL", ma60=_r(ma60[-1]), vol_x=_r(rec.mean() / base, 1),
                         vol_low=_r(l[bi]), stop=_r(max(ma60[-1], l[bi]) if l[bi] < c[-1] else ma60[-1]),
                         note="主力資金進場；量要持續放大才續攻。停損：跌破季線或爆量 K 棒低點"))
    return out


def screen_kdj_high(prices, names=None, params=None):
    """KDJ 高檔轉弱（出場）：大漲後 K、D > 80 且 J 曾 > 100，今天 J 往下穿越 K 與 D（死亡交叉）→ 先賣一半"""
    p = params or {}
    rise = float(p.get("rise_pct", 20)) / 100
    lv, jl, within = float(p.get("level", 80)), float(p.get("j_level", 100)), int(p.get("j_within", 3))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, 70):
            continue
        k, d, j = kdj(df)
        if not (j[-1] < k[-1] and j[-1] < d[-1] and (j[-2] >= k[-2] or j[-2] >= d[-2])):
            continue
        if not (k[-2] > lv and d[-2] > lv) or j[-within - 1:-1].max() <= jl:
            continue
        l, cl = df["low"].astype(float).values, df["close"].astype(float)
        if cl.iloc[-1] / l[-60:].min() - 1 < rise:
            continue
        dull = 0
        for i in range(len(k) - 2, 0, -1):
            if k[i] > lv and d[i] > lv:
                dull += 1
            else:
                break
        out.append(_base(sid, df, names, "S_KDJ_HIGH", k=_r(k[-1], 1), d=_r(d[-1], 1), j=_r(j[-1], 1),
                         dull_days=dull, ma5=_r(calc_ma(cl, 5).iloc[-1]), ma10=_r(calc_ma(cl, 10).iloc[-1]),
                         ma20=_r(calc_ma(cl, 20).iloc[-1]),
                         note=("先前 K、D 黏在 80 以上 %d 天（高檔鈍化＝極強趨勢）：只賣一半，別放空、別賣光；" % dull if dull > 3 else "")
                              + "死叉先賣一半，另一半跌破 5MA／10MA 或月線再全賣"))
    return out


def screen_kdj_div(prices, names=None, params=None):
    """KDJ 高檔背離（出場）：股價創前波新高，但 K 值高點低於前波高點，且近幾天出現死叉"""
    p = params or {}
    look, within = int(p.get("look", 60)), int(p.get("cross_within", 3))
    out = []
    for sid, df in prices.items():
        if not _ok_price(df, p, look + 20):
            continue
        k, d, j = kdj(df)
        h = df["high"].astype(float).values
        n = len(df)
        pi = n - look + int(np.argmax(h[-look:-8]))
        if h[-5:].max() < h[pi]:                                                    # 沒創前波新高
            continue
        kp, kn = k[max(0, pi - 2):pi + 3].max(), k[-5:].max()
        if kp < float(p.get("k_high", 80)) or kn > kp - float(p.get("k_gap", 5)):  # 前波在高檔、這次指標高點明顯較低
            continue
        if not any(j[i] < d[i] and j[i - 1] >= d[i - 1] for i in range(n - within, n)):
            continue
        out.append(_base(sid, df, names, "S_KDJ_DIV", prev_high=_r(h[pi]), prev_high_date=str(df["date"].iloc[pi]),
                         k_prev=_r(kp, 1), k_now=_r(kn, 1),
                         note="多頭動能衰退、大多頭尾聲易大回檔：逢高減碼或出場避險"))
    return out


COURSE_STRATEGIES = {
    "S_WMACD":      "📅 週MACD大波段（站回20週線＋週柱翻紅）",
    "S_BIAS":       "🧲 負乖離抄底（季線乖離 ≤ −20%）",
    "S_RSI_OS":     "🔄 RSI6 超賣勾起（第一次）",
    "S_RSI_HOT":    "🔥 RSI6 高檔鈍化（打橫靠5日線）",
    "S_BB1":        "🎈 布林(20,1) 上軌外飆股",
    "S_GAP_BOTTOM": "🕳️ 爆天量＋第一個向上跳空",
    "S_LIMIT_OPEN": "🚪 連續漲停爆量打開",
    "S_W60_BREAK":  "⛔ 跌破60週線（翻空）",
    "S_MA_ALLDOWN": "⛔ 跌破所有均線且下彎",
    "S_DANGER":     "☠️ 危險量＋高檔空方缺口",
    "S_KDJ_LOW":    "🪝 KDJ 低檔金叉（K、D<20、J<0 往上穿）",
    "S_BREAKBOTTOM": "🔻 破底翻（長黑收最低、隔天不破低）",
    "S_NBREAK":     "📐 關鍵價突破（N 字、長紅過頸線）",
    "S_VOLROLL":    "🌋 底部量滾量站上季線",
    "S_KDJ_HIGH":   "🎢 KDJ 高檔死叉（先賣一半）",
    "S_KDJ_DIV":    "📉 KDJ 高檔背離",
}

COURSE_FNS = {
    "S_WMACD": screen_wmacd, "S_BIAS": screen_bias, "S_RSI_OS": screen_rsi_os, "S_RSI_HOT": screen_rsi_hot,
    "S_BB1": screen_bb1, "S_GAP_BOTTOM": screen_gap_bottom, "S_LIMIT_OPEN": screen_limit_open,
    "S_W60_BREAK": screen_w60_break, "S_MA_ALLDOWN": screen_ma_alldown, "S_DANGER": screen_danger,
    "S_KDJ_LOW": screen_kdj_low, "S_BREAKBOTTOM": screen_breakbottom, "S_NBREAK": screen_nbreak,
    "S_VOLROLL": screen_volroll, "S_KDJ_HIGH": screen_kdj_high, "S_KDJ_DIV": screen_kdj_div,
}
COURSE_SHORT = {"S_W60_BREAK", "S_MA_ALLDOWN", "S_DANGER", "S_KDJ_HIGH", "S_KDJ_DIV"}

_MP = {"key": "min_price", "label": "最低股價", "type": "number", "default": 10, "min": 1, "max": 500, "step": 1}
COURSE_PARAMS = {
    "S_WMACD": [_MP, {"key": "drop_pct", "label": "近一年波段跌幅%（≥）", "type": "number", "default": 25, "min": 10, "max": 70, "step": 5},
                {"key": "flip_within", "label": "週柱翻紅在近幾週內", "type": "number", "default": 1, "min": 1, "max": 4, "step": 1}],
    "S_BIAS": [_MP, {"key": "ma_period", "label": "乖離均線（60＝季線、20＝月線）", "type": "number", "default": 60, "min": 20, "max": 60, "step": 40},
               {"key": "bias_pct", "label": "負乖離%（≤ −）", "type": "number", "default": 20, "min": 5, "max": 40, "step": 1},
               {"key": "need_confirm", "label": "需要確認訊號（1＝要、0＝不用）", "type": "number", "default": 0, "min": 0, "max": 1, "step": 1}],
    "S_RSI_OS": [_MP, {"key": "level", "label": "超賣線", "type": "number", "default": 20, "min": 10, "max": 30, "step": 1},
                 {"key": "first_lookback", "label": "「第一次」回看天數", "type": "number", "default": 20, "min": 5, "max": 60, "step": 5}],
    "S_RSI_HOT": [_MP, {"key": "level", "label": "鈍化線", "type": "number", "default": 80, "min": 70, "max": 90, "step": 1},
                  {"key": "min_days", "label": "連續天數（≥）", "type": "number", "default": 3, "min": 2, "max": 10, "step": 1},
                  {"key": "flat_pct", "label": "打橫：近3天收盤高低差%（≤）", "type": "number", "default": 4, "min": 1, "max": 10, "step": 0.5},
                  {"key": "ma5_near_pct", "label": "靠近5日線%（≤）", "type": "number", "default": 3, "min": 0.5, "max": 8, "step": 0.5}],
    "S_BB1": [_MP, {"key": "period", "label": "布林週期", "type": "number", "default": 20, "min": 10, "max": 60, "step": 1},
              {"key": "k", "label": "標準差倍數", "type": "number", "default": 1, "min": 0.5, "max": 3, "step": 0.5},
              {"key": "expand", "label": "帶寬擴大倍數（比 5 天前 ≥）", "type": "number", "default": 1.2, "min": 1, "max": 3, "step": 0.1},
              {"key": "rise_pct", "label": "20 天漲幅%（≥）", "type": "number", "default": 10, "min": 0, "max": 100, "step": 5}],
    "S_GAP_BOTTOM": [_MP, {"key": "drop_pct", "label": "距120日高點跌幅%（≥）", "type": "number", "default": 25, "min": 10, "max": 70, "step": 5},
                     {"key": "vol_within", "label": "天量出現在近幾天", "type": "number", "default": 20, "min": 5, "max": 60, "step": 5},
                     {"key": "gap_within", "label": "缺口出現在近幾天", "type": "number", "default": 5, "min": 1, "max": 20, "step": 1}],
    "S_LIMIT_OPEN": [_MP, {"key": "min_limit_days", "label": "先前連續跳空漲停天數（≥）", "type": "number", "default": 2, "min": 1, "max": 10, "step": 1},
                     {"key": "vol_mult", "label": "打開當天量（昨量倍數 ≥）", "type": "number", "default": 3, "min": 1.5, "max": 20, "step": 0.5}],
    "S_W60_BREAK": [_MP],
    "S_MA_ALLDOWN": [_MP],
    "S_DANGER": [_MP, {"key": "vol_ratio", "label": "近5日量 ÷ 歷史最大量（≥）", "type": "number", "default": 0.9, "min": 0.5, "max": 1.5, "step": 0.05}],
    "S_KDJ_LOW": [_MP, {"key": "drop_pct", "label": "近60日高點跌幅%（≥）", "type": "number", "default": 20, "min": 5, "max": 60, "step": 5},
                  {"key": "level", "label": "K、D 低於", "type": "number", "default": 20, "min": 10, "max": 30, "step": 1},
                  {"key": "j_within", "label": "J<0 在近幾天內", "type": "number", "default": 3, "min": 1, "max": 10, "step": 1}],
    "S_BREAKBOTTOM": [_MP, {"key": "drop_pct", "label": "距60日高點跌幅%（≥）", "type": "number", "default": 20, "min": 5, "max": 60, "step": 5},
                      {"key": "body_pct", "label": "長黑實體%（≥）", "type": "number", "default": 3, "min": 1, "max": 10, "step": 0.5},
                      {"key": "new_low_days", "label": "破近幾天收盤低點", "type": "number", "default": 20, "min": 5, "max": 60, "step": 5}],
    "S_NBREAK": [_MP, {"key": "rally_pct", "label": "頸線前漲幅%（≥）", "type": "number", "default": 20, "min": 5, "max": 100, "step": 5},
                 {"key": "pull_pct", "label": "拉回幅度%（≥）", "type": "number", "default": 5, "min": 2, "max": 30, "step": 1},
                 {"key": "look", "label": "頸線回看天數", "type": "number", "default": 60, "min": 20, "max": 120, "step": 5},
                 {"key": "body_pct", "label": "長紅實體%（≥）", "type": "number", "default": 2, "min": 0.5, "max": 8, "step": 0.5},
                 {"key": "vol_mult", "label": "突破量（20日均量倍數 ≥）", "type": "number", "default": 1.5, "min": 1, "max": 5, "step": 0.5},
                 {"key": "retest_within", "label": "回測守住：突破在近幾天內", "type": "number", "default": 10, "min": 3, "max": 30, "step": 1}],
    "S_VOLROLL": [_MP, {"key": "min_vol_lots", "label": "今日量（張 ≥）", "type": "number", "default": 500, "min": 0, "max": 10000, "step": 100},
                  {"key": "drop_pct", "label": "一年高點到半年低點跌幅%（≥）", "type": "number", "default": 25, "min": 10, "max": 70, "step": 5},
                  {"key": "vol_mult", "label": "爆量（前期均量倍數 ≥）", "type": "number", "default": 2, "min": 1.5, "max": 6, "step": 0.5},
                  {"key": "roll_days", "label": "連續爆量天數", "type": "number", "default": 3, "min": 2, "max": 6, "step": 1},
                  {"key": "cross_within", "label": "站上季線在近幾天內", "type": "number", "default": 5, "min": 1, "max": 15, "step": 1}],
    "S_KDJ_HIGH": [_MP, {"key": "rise_pct", "label": "距60日低點漲幅%（≥）", "type": "number", "default": 20, "min": 5, "max": 100, "step": 5},
                   {"key": "level", "label": "K、D 高於", "type": "number", "default": 80, "min": 70, "max": 90, "step": 1},
                   {"key": "j_level", "label": "J 曾高於", "type": "number", "default": 100, "min": 80, "max": 120, "step": 5},
                   {"key": "j_within", "label": "J 過熱在近幾天內", "type": "number", "default": 3, "min": 1, "max": 10, "step": 1}],
    "S_KDJ_DIV": [_MP, {"key": "look", "label": "前波高點回看天數", "type": "number", "default": 60, "min": 20, "max": 120, "step": 5},
                  {"key": "k_high", "label": "前波 K 值高點（≥，高檔）", "type": "number", "default": 80, "min": 60, "max": 95, "step": 5},
                  {"key": "k_gap", "label": "這次 K 高點比前波低（≥）", "type": "number", "default": 5, "min": 1, "max": 30, "step": 1},
                  {"key": "cross_within", "label": "死叉在近幾天內", "type": "number", "default": 3, "min": 1, "max": 10, "step": 1}],
}


import scanner as _sc  # noqa: E402  放最後：不管先 import 哪一個都不會循環失敗
