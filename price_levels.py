"""
price_levels.py — 依使用者的看盤邏輯算關鍵價位（觀察清單、K 線、平地一聲雷策略共用）

使用者規則（2026-10-03 截圖手寫＋確認）：
- 壓力區：現價上方的前高（波段高點）由近到遠＝第一壓力、第二壓力…（「0 是底，1、2、3、4 是上面的壓力」）
- 平地一聲雷：上方盤整很久（90 天、區間 ≤15%）後帶量（≥ 20 日均量 2.5 倍）突破盤整上緣；
  漲一段後回檔，回檔幅度 ≤ 第一段漲幅的 0.618，
  目標價 ＝ 第一段高點 − 突破點（盤整上緣）＋ 回檔低點（例：30 − 10 + 25 = 45，上方沒有前高時用）
- 上漲模式（平地一聲雷突破後、均線多頭排列）：收盤跌破前一天低點出場
- 停損一般看：爆量 K 棒低點、波段低點、前低；附近有均線（如 60 日線）一起看
- 跌破爆量低點出場，之後站回就是假跌破
- 區間整理：5 日 > 10 日 > 20 日、底部一直墊高、但還沒過區間高 → 加入自選觀察

2026-10-05 改版（PLAN-LEVELS.md、research/levels/）：用 1,810 檔兩年日 K walk-forward 回測、跟「同樣 ATR 距離的隨機價位」比
- 支撐價：前低＝最近一段回檔的最低點（pullback_low；沒有就 60 日低）——前低是唯一穩定有效的支撐（撐住 +3～3.4 個百分點）
  （10-05 版用 k=5 波段低點；10-06 用戶看群創、京元電子、友達：起漲前／盤整的低點才合理、盤中跌破又拉回不算破、
   急漲後的回檔低點也算 → 改成兩個波段高點之間的最低點，今天這根不算）
- 停損價：支撐 −0.5 ATR、至少離現價 2.5 ATR（10-06 前是 1.5；支撐改抓最近的前低後太常被洗，見 STOP_MIN_ATR），收盤跌破出場（舊版約 1 ATR、67% 會被打到；
  改善來自留足空間，前低錨定跟同距離純 ATR 一樣好，選它是因為符合用戶「停損看波段低點」）
  前低離現價 > 3 ATR 且強勢（收盤 > 5 日線 > 10 日線）→ 撐＝10 日線、損＝20 日線 −1 ATR（移動停損）；
  前低 > 3 ATR 但不強勢 → 10-05 版不顯示支撐、用風險上限；10-06 改回照樣顯示前低、損＝前低 −0.5 ATR（PLAN 第 10 節）
- 目標價：前高（壓力區一，離現價不到 0.5 ATR 就壓力區二）→ 平地一聲雷等幅 → 一般等幅（回檔低＋前高−起漲低）→ 現價＋3 ATR；
  （10-06 用戶：「有前高就要看前高，還沒過怎麼會先跳到另一種計算模式」——等幅只在上方沒有前高時用）
  各種目標算法都沒有比隨機準，所以照用戶規則排，另給報酬風險比 rr
- 壓力區：9 種算法都沒有比隨機準，維持「前高」定義；近幾天剛做的高點（右邊還不滿 5 根）也算前高
"""
from __future__ import annotations

import copy
import math
from typing import Optional

import numpy as np
import pandas as pd

# 停損至少離現價幾倍 ATR（支撐太近時）。2026-10-06 支撐改抓最近的前低，1.5 倍時停損被打到 40%、40 天中位報酬 +0.2%；
# 2.5 倍 29%、+3.1%（成交值前 300 檔、Yahoo 兩年、9,722 樣本；PLAN-LEVELS.md 第 11 節）
STOP_MIN_ATR = 2.5

THUNDER_DEFAULTS = {"base_days": 90, "base_range": 0.15, "vol_mult": 2.5, "max_retrace": 0.618,
                    "breakout_within": 60}


def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def pivots(values, k: int, kind: str) -> list:
    """波段高/低點：前後各 k 根都沒有更高（更低）的點。回傳 index 清單（最後 k 根不判斷）"""
    v = np.asarray(values, dtype=float)
    out = []
    # 平頭（同價）很常見：取同價的第一根（左邊嚴格、右邊可相等）
    for i in range(k, len(v) - k):
        left, right = v[i - k:i], v[i + 1:i + k + 1]
        if kind == "high" and v[i] > left.max() and v[i] >= right.max():
            out.append(i)
        elif kind == "low" and v[i] < left.min() and v[i] <= right.min():
            out.append(i)
    return out


def detect_thunder(df: pd.DataFrame, params: dict = None) -> Optional[dict]:
    """平地一聲雷：找最近一次「盤整 base_days 天、收盤區間 ≤ base_range，之後收盤帶量突破盤整上緣」，
    且突破發生在最近 breakout_within 根內、現價仍在盤整上緣之上。沒有就回 None。"""
    p = {**THUNDER_DEFAULTS, **(params or {})}
    n = len(df)
    nb = int(p["base_days"])
    if n < nb + 2:
        return None
    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    v = df["volume"].values.astype(float)
    last = n - 1
    found = None
    for b in range(last, max(nb, 20, last - int(p["breakout_within"])) - 1, -1):
        base = c[b - nb:b]
        lo, hi = base.min(), base.max()
        if lo <= 0 or (hi - lo) / lo > p["base_range"]:
            continue
        avg20 = v[b - 20:b].mean()
        if c[b] > hi and avg20 > 0 and v[b] >= avg20 * p["vol_mult"]:
            found = (b, hi, lo, v[b] / avg20)
            break
    if not found:
        return None
    b, base_top, base_low, vol_ratio = found
    if c[last] <= base_top:
        return None                      # 跌回盤整區：突破失敗，不算
    # 第一段：突破後第一個波段高點（後面有回檔）；回檔低點＝它之後、價格再創高之前的最低點
    first_hi = next((i for i in pivots(h, 3, "high") if i > b), None)
    if first_hi is None:
        hi_idx = b + int(h[b:].argmax())
        high, pull_low, reclaimed = float(h[hi_idx]), None, False
    else:
        hi_idx = first_hi
        high = float(h[hi_idx])
        after = np.where(h[hi_idx + 1:] > high)[0]
        end = hi_idx + 1 + int(after[0]) if len(after) else last + 1
        pull_low = float(l[hi_idx + 1:end].min()) if end > hi_idx + 1 else None
        reclaimed = bool(len(after))     # 回檔後已越過第一段高點
    leg = high - base_top
    retrace = (high - pull_low) / leg if (pull_low is not None and leg > 0) else None
    target = None
    if retrace is not None and retrace <= p["max_retrace"] and pull_low > base_top * 0.97:
        target = high - base_top + pull_low
    # 階段
    ma5 = pd.Series(c).rolling(5).mean().values
    ma10 = pd.Series(c).rolling(10).mean().values
    ma20 = pd.Series(c).rolling(20).mean().values
    uptrend = bool(c[last] > ma5[last] > ma10[last] > ma20[last]) if not np.isnan(ma20[last]) else False
    if pull_low is None:
        stage = "攻擊中（突破後還沒回檔）"
    elif retrace is None:                # 突破後第一個波段高點沒高過突破點（leg ≤ 0），量不出回檔比例
        stage = "突破後第一段沒拉開，等幅量不出來"
    elif retrace > p["max_retrace"]:
        stage = f"回檔過深（回檔 {retrace:.0%} > {p['max_retrace']:.1%}）"
    elif reclaimed:
        stage = f"回檔 {retrace:.0%} 不破、已越過第一段高點，往目標價前進"
    else:
        stage = f"回檔整理中（回檔 {retrace:.0%}，不破回檔低點才買）"
    return {
        "base_top": _r(base_top), "base_low": _r(base_low), "base_days": nb,
        "breakout_idx": int(b), "breakout_date": str(df["date"].iloc[b]),
        "breakout_vol_ratio": _r(vol_ratio, 1),
        "high": _r(high), "high_date": str(df["date"].iloc[hi_idx]),
        "pullback_low": _r(pull_low), "retrace": _r(retrace, 3),
        "target": _r(target), "stage": stage, "uptrend": uptrend,
        "exit_prev_low": _r(l[last]) if uptrend else None,   # 上漲模式：明天收盤跌破今天低點出場
    }


def atr_series(h, l, c, n: int = 14):
    """14 日真實波幅（TR＝max(高−低, |高−昨收|, |低−昨收|)）簡單平均"""
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def measured_move(h, l, look: int, last: int, price: float) -> Optional[dict]:
    """一般等幅（用戶等幅規則推廣）：最近一個已確認 k=5 波段高點 H1、它之前最近的 k=5 波段低點 L0（起漲）、
    H1 之後到現在的最低點 L1（回檔低）；L1 > L0、回檔 ≤ 0.618、現價 > L1 → 目標 ＝ L1 ＋（H1 − L0）"""
    hs = [i for i in pivots(h, 5, "high") if i >= look]
    if not hs:
        return None
    i1 = hs[-1]
    los = [i for i in pivots(l, 5, "low") if look <= i < i1]
    if not los or i1 >= last:
        return None
    i0 = los[-1]
    L0, H1 = float(l[i0]), float(h[i1])
    leg = H1 - L0
    if leg <= 0:
        return None
    seg = l[i1 + 1:last + 1]
    L1 = float(seg.min())
    if L1 <= L0 or (H1 - L1) / leg > 0.618 or price <= L1:
        return None
    return {"target": L1 + leg, "start_low": L0, "start_idx": int(i0), "high": H1, "high_idx": int(i1),
            "pullback_low": L1, "pullback_idx": int(i1 + 1 + int(seg.argmin())), "retrace": (H1 - L1) / leg}


def recent_high(h, k: int = 5) -> Optional[int]:
    """右邊還不滿 k 根、所以 pivots 還沒確認的近期高點（例：前天創高、這兩天拉回）。
    條件：比左邊 k 根都高、之後到今天都沒超過；不含今天自己（今天的上影線不算前高）。沒有回 None"""
    n = len(h)
    for i in range(n - 2, max(k, n - k) - 1, -1):
        if h[i] > h[i - k:i].max() and h[i] >= h[i + 1:].max():
            return i
    return None


def pullback_low(h, l, price: float, look: int, k: int = 3) -> Optional[int]:
    """前低＝最近一段回檔的最低點：相鄰兩個波段高點（k 根）之間、或最後一個高點到「昨天」的最低價，
    由近往遠取第一個低於現價的。回傳 index，沒有回 None。
    - 今天這根不算：盤中跌破前低又拉回（收盤還在上面）不算跌破，前低照樣是支撐（2026-10-06 京元電子：
      10/06 盤中 288.5 收 298，前低 292 仍是支撐）；收盤跌破 → 前低 > 現價 → 往前找下一個前低
    - 不要求左邊 k 根都比它高：急漲後的回檔低點（友達 9/23 33.4，左邊是更低的起漲 K 棒）也算"""
    last = len(h) - 1
    hs = [i for i in pivots(h, k, "high") if i >= look]
    rh = recent_high(h, k)
    if rh is not None and rh >= look and rh not in hs:
        hs.append(rh)
    bounds = sorted(hs) + [last]
    for a, b in reversed(list(zip(bounds[:-1], bounds[1:]))):
        if b - a < 2:
            continue
        j = a + 1 + int(l[a + 1:b].argmin())
        if l[j] < price:
            return j
    return None


def support_low(h, l, c, price: float, look: int, k: int = 3) -> Optional[int]:
    """支撐用的前低：下面兩種裡面最近的一個（都要低於現價）。回傳 index，沒有回 None
    1. 波段低點：左邊 k 根的低點都比它高、右邊 k 根的「收盤」都沒跌破它（盤中跌破又拉回不算破）
    2. 回檔低點 pullback_low：兩個波段高點之間的最低點（急漲後的回檔低點左邊比它低，1 抓不到）
    例：高點 15 → 跌到 12 → 彈到 14.5 → 回到 13.2 → 現在 14.6：13.2 是 1（較近的墊高低點）、12 是 2，取 13.2"""
    n = len(l)
    cands = [i for i in range(max(k, look), n - k)
             if l[i] < l[i - k:i].min() and c[i + 1:i + k + 1].min() >= l[i] and l[i] < price]
    pb = pullback_low(h, l, price, look, k)
    if pb is not None:
        cands.append(pb)
    return max(cands) if cands else None


def _zones(highs_idx, h, price, tol=0.02):
    """把現價上方的波段高點合併成壓力區（相差 2% 內算同一區），由近到遠"""
    above = sorted(float(h[i]) for i in highs_idx if h[i] > price * 1.005)
    zones = []
    for x in above:
        if zones and x <= zones[-1]["high"] * (1 + tol):
            zones[-1]["high"] = max(zones[-1]["high"], x)
            zones[-1]["touches"] += 1
        else:
            zones.append({"low": x, "high": x, "touches": 1})
    return [{"low": _r(z["low"]), "high": _r(z["high"]), "touches": z["touches"]} for z in zones]


def compute_levels(df: pd.DataFrame, thunder_params: dict = None) -> dict:
    """回傳 {price, mode, pressure1, pressure2, target, target_method, target_kind, support, stop, atr, rr, downside_pct,
    stops（參考：爆量低點／k=3 波段低點／前低／上漲模式出場）, thunder, measured, ma_near, notes}"""
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    n = len(df)
    if n < 30:
        return {"error": "K 線資料不足 30 根"}
    c = df["close"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    v = df["volume"].values.astype(float)
    last = n - 1
    price = float(c[last])
    notes = []
    look = max(0, n - 250)                 # 約一年內的前高前低

    # 壓力區（現價上方的前高）；近幾天剛做的高點右邊還不滿 5 根也算（2026-10-06 南茂：前天高 133 被漏掉、顯示無前高）
    ph = [i for i in pivots(h, 5, "high") if i >= look]
    rh = recent_high(h, 5)
    if rh is not None and rh not in ph:
        ph.append(rh)
    zones = _zones(ph, h, price)
    p1 = zones[0] if zones else None
    p2 = zones[1] if len(zones) > 1 else None

    # 平地一聲雷
    th = detect_thunder(df, thunder_params)

    # 區間整理（5>10>20、底部墊高、還沒過區間高）
    ma = {k: pd.Series(c).rolling(k).mean().values for k in (5, 10, 20, 60, 120, 240)}
    pl3 = [i for i in pivots(l, 3, "low") if i >= n - 60]
    box_high = float(h[max(0, n - 20):].max())
    rising = len(pl3) >= 2 and all(l[pl3[j]] < l[pl3[j + 1]] for j in range(len(pl3) - 1))
    aligned = not np.isnan(ma[20][last]) and ma[5][last] > ma[10][last] > ma[20][last]
    consolidating = aligned and rising and price < box_high * 0.995

    if th and th["uptrend"]:
        mode = "平地一聲雷・上漲模式"
    elif th:
        mode = f"平地一聲雷・{th['stage']}"
    elif consolidating:
        mode = "區間整理（底部墊高，待突破區間高）"
        if not p1 or box_high < p1["low"]:
            p2, p1 = p1, {"low": _r(box_high), "high": _r(box_high), "touches": 1}
        notes.append(f"還沒過區間高 {box_high:.2f}：可先加入自選觀察，帶量突破再進")
    else:
        mode = "一般"

    # ATR（下限 現價×0.5%：停牌／零波動／資料異常時不會是 0 或 NaN）
    atr_v = atr_series(h, l, c)[last]
    a = max(float(atr_v) if np.isfinite(atr_v) else 0.0, price * 0.005)
    fmtd = lambda i: str(df["date"].iloc[i])

    # 目標價：依序取第一個 > 現價 + 0.5 ATR 的（研究：沒有目標算法比隨機準 → 照用戶規則）
    # 用戶規則（2026-10-06 再確認）：上方有前高、還沒過 → 目標就是前高；沒有前高才用等幅（平地一聲雷、一般等幅）、3 ATR
    mm = measured_move(h, l, look, last, price)
    cands = []
    if p1:
        cands.append((p1["low"], "pressure1", "前高（壓力區一）還沒過：先看前高"))
    if p2:
        cands.append((p2["low"], "pressure2", "壓力區一離現價太近（不到 0.5 倍 ATR），看下一個前高（壓力區二）"))
    if th and th["target"]:
        cands.append((th["target"], "thunder",
                      f"上方沒有前高可看，用平地一聲雷等幅：高點 {th['high']} − 突破點 {th['base_top']} ＋ 回檔低點 {th['pullback_low']}"))
    if mm:
        cands.append((mm["target"], "measured",
                      f"上方沒有前高可看，用等幅：回檔低點 {mm['pullback_low']:.2f} ＋（前高 {mm['high']:.2f} − 起漲低點 {mm['start_low']:.2f}）"))
    cands.append((price + 3 * a, "atr", f"上方沒有前高、也沒有等幅可量：現價 ＋ 3×ATR（約 {3 * a / price * 100:.0f}%）"))
    target, target_kind, method = next((x for x in cands if x[0] is not None and x[0] > price + 0.5 * a), (None, None, ""))

    # 停損：爆量低點、波段低點、前低
    stops = {}
    avg20 = pd.Series(v).rolling(20).mean().shift(1).values
    for i in range(last, max(20, n - 60) - 1, -1):
        if avg20[i] > 0 and v[i] >= avg20[i] * 2 and l[i] < price:
            stops["volume_low"] = {"price": _r(l[i]), "date": str(df["date"].iloc[i]), "idx": int(i),
                                   "label": f"爆量 K 棒低點（{v[i] / avg20[i]:.1f} 倍量）"}
            break
    lows = [i for i in pivots(l, 3, "low") if l[i] < price and i >= look]
    if lows:
        i1 = lows[-1]
        stops["swing_low"] = {"price": _r(l[i1]), "date": str(df["date"].iloc[i1]), "label": "波段低點"}
        older = [i for i in lows if i < i1 and l[i] < l[i1]]
        if older:
            i2 = older[-1]
            stops["prev_low"] = {"price": _r(l[i2]), "date": str(df["date"].iloc[i2]), "label": "前低"}
    if th and th["exit_prev_low"]:
        stops["uptrend_exit"] = {"price": th["exit_prev_low"], "date": str(df["date"].iloc[last]),
                                 "label": "上漲模式：收盤跌破這天低點出場"}

    # 支撐價：最近的前低（support_low：波段低點或回檔低點，近一年、低於現價）；沒有就 60 日低點
    # 2026-10-06 用戶回饋：群創 起漲前的低點 48.55（不是更早的 46.25）、京元電子 盤中跌破又拉回不算破 → 前低 292、
    # 友達 急漲後的回檔低點 33.4。舊版 k=5 波段低點要求左右低點都比它高，這三個都抓不到
    support = None
    sl = support_low(h, l, c, price, look)
    if sl is not None:
        i = sl
        support = {"price": _r(l[i]), "date": fmtd(i), "label": "前低", "kind": "swing"}
    else:
        s60 = max(0, n - 60)
        i = s60 + int(l[s60:].argmin())
        if l[i] < price * 0.995:
            support = {"price": _r(l[i]), "date": fmtd(i), "label": "60 日低點", "kind": "low60"}

    # 停損價（PLAN-LEVELS.md 第 8 節，研究最佳做法）：
    # - 前低離現價 > 3 ATR 且強勢（收盤 > 5 日線 > 10 日線）→ 撐＝10 日線、損＝20 日線 −1 ATR（移動停損，跟著月線上移）
    #   （研究：強勢延伸股 40 天 +3.98%、最大回撤 12.7%；用戶原本的 5／10 日線進出 +1.12%、會被洗）
    # - 其他（含前低 > 3 ATR 但不是強勢）：支撐 −0.5 ATR，至少離現價 2.5 ATR（STOP_MIN_ATR）；沒有支撐用現價 −2.5 ATR
    #   （10-05 版前低遠又不強勢時不顯示支撐、停損用 現價 −3.5 ATR 風險上限；10-06 用戶：支撐要顯示前低 → 拿掉。
    #    研究 3.2：前低 −0.5ATR 不設上限 +2.59%、夾 1.5～3.5ATR +2.55%，差不多）
    # 每次都用當下的均線重算（無狀態），所以只要有支撐，停損一定低於支撐
    struct_support = None
    stop = None
    m5, m10, m20 = ma[5][last], ma[10][last], ma[20][last]
    far = support is not None and price - support["price"] > 3 * a
    trend = not any(np.isnan(x) for x in (m5, m10, m20)) and price > m5 > m10
    if far and trend:
        # 後兩項只在 20 日線偏高的少數情況生效：保證停損 < 10 日線支撐、且離現價至少 1.5 ATR
        trail_p = min(m20 - a, m10 - 0.5 * a, price - 1.5 * a)
        if trail_p > 0 and _r(trail_p) < _r(m10):
            struct_support = support
            support = {"price": _r(m10), "date": fmtd(last), "label": "10 日線（強勢股的支撐）", "kind": "ma10"}
            note = "" if trail_p == m20 - a else "（20 日線偏高，往下放到離 10 日線 0.5 ATR／離現價 1.5 ATR）"
            stop = {"price": _r(trail_p), "basis": "trail",
                    "label": f"移動停損：20 日線 {m20:.2f} − 1×ATR（{a:.2f}）{note}，跟著 20 日線每天上移，收盤跌破出場；"
                             f"前低 {struct_support['price']} 離現價超過 3 倍 ATR"}
    if stop is None:
        if support:
            sp = support["price"]
            raw = sp - 0.5 * a
            if raw > price - STOP_MIN_ATR * a:
                stop_p, basis = price - STOP_MIN_ATR * a, "floor"
                label = f"支撐 {sp} 離現價太近，停損放在現價 − {STOP_MIN_ATR:g}×ATR，避免盤中雜訊洗出場"
            else:
                stop_p, basis = raw, "support"
                label = f"支撐 {sp} − 0.5×ATR（{a:.2f}）" + ("；前低離現價超過 3 倍 ATR，停損比較寬，用部位大小控制風險" if far else "")
        else:
            stop_p, basis = price - 2.5 * a, "atr"
            label = "近一年沒有低於現價的低點可當支撐，停損用現價 − 2.5×ATR"
        stop = {"price": _r(stop_p), "basis": basis, "label": label + "，收盤跌破出場"} if stop_p > 0 else None

    # 附近均線（±3% 內）
    ma_near = []
    for k, name in ((20, "20 日線"), (60, "60 日線")):
        m = ma[k][last]
        if not np.isnan(m) and abs(price / m - 1) <= 0.03:
            ma_near.append({"name": name, "price": _r(m)})
    if ma_near:
        notes.append("附近有 " + "、".join(f"{x['name']} {x['price']}" for x in ma_near) + "，停損一起看")

    # 壓力區裡有半年線／年線（參考；研究中均線壓力沒有比隨機準，只提示）
    for zname, z in (("一", p1), ("二", p2)):
        if not z:
            continue
        for k, nm in ((120, "半年線"), (240, "年線")):
            m = ma[k][last]
            if not np.isnan(m) and z["low"] - 0.5 * a <= m <= z["high"] + 0.5 * a:
                notes.append(f"壓力區{zname}附近有{nm} {m:.2f}")

    # 報酬風險比：到目標的漲幅 ÷ 到停損的跌幅（用畫面上顯示的四捨五入價格算，手算對得起來）
    pr = _r(price)
    rr = _r((_r(target) - pr) / (pr - stop["price"]), 1) if (target and stop and pr > stop["price"]) else None

    # 假跌破：昨天收盤跌破爆量低點、今天站回
    vl = stops.get("volume_low")
    if vl and vl["idx"] < last - 1 and c[last - 1] < vl["price"] <= c[last]:
        notes.append(f"昨天跌破爆量低點 {vl['price']}、今天站回 → 假跌破")

    return {
        "price": _r(price), "high": _r(h[last]), "date": str(df["date"].iloc[last]), "mode": mode,
        "pressure1": p1, "pressure2": p2, "zones": zones[:4],
        "target": _r(target), "target_method": method, "target_kind": target_kind,
        "upside_pct": _r((target / price - 1) * 100, 1) if target else None,
        "support": support, "stop": stop, "struct_support": struct_support, "atr": _r(a, 3), "rr": rr,
        "ma5": _r(m5) if not np.isnan(m5) else None,
        "downside_pct": _r((stop["price"] / price - 1) * 100, 1) if stop else None,
        "measured": {k: (_r(x, 3) if isinstance(x, float) else x) for k, x in mm.items()} if mm else None,
        "stops": stops, "thunder": th, "ma_near": ma_near, "notes": notes,
    }


def apply_entry_floor(lv: dict, entry: Optional[float], kind: str = "added", prev: Optional[dict] = None) -> dict:
    """觀察／持有模式（PLAN-POSITIONS.md）：停損不低於 參考價 ×0.9。
    kind＝"cost"（持有：成本價）或 "added"（觀察：加入日收盤價）。不改傳入的 dict，回傳新的。
    研究（research/levels/trailing.py）：線上規則加這條，40 天平均 +2.39% → +2.15%，最差 5% −16.9% → −13.2%。
    alerts 跟 prev（到前一根 K 棒為止算出的 {stop, target}）比：價位用當下價格重算，跌下去停損也會往下移，
    跟「現在的停損」比永遠不會跌破。"""
    out = copy.deepcopy(lv)
    if not out or out.get("error") or not out.get("price") or out["price"] <= 0:
        return out
    price = out["price"]
    floor = round(entry * 0.9, 2) if entry and entry > 0 else None
    if floor is None:
        out["alerts"] = _alerts(out, None, prev)
        return out
    name = "成本" if kind == "cost" else "加入價"
    out["entry"] = {"price": _r(entry), "kind": kind, "floor": floor, "pnl_pct": _r((price / entry - 1) * 100, 1)}
    stop = out.get("stop")
    if stop is None or floor > stop["price"]:
        out["stop_before_floor"] = stop
        breached = floor >= price
        sup = out.get("support")
        # 底線高於支撐時支撐照樣顯示（10-06 用戶：支撐要看得到前低）；這條是「進場價 −10%」的資金控管線，不是線圖支撐
        over = f"（比支撐 {sup['price']} 還高：先守{name} −10%）" if sup is not None and floor >= sup["price"] else ""
        label = f"{name} {_r(entry)} −10% 底線{over}，收盤跌破出場"
        out["stop"] = {"price": floor, "basis": "entry10",
                       "label": ("已跌破！" if breached else "") + label, "breached": breached}
        tgt = out.get("target")
        if breached:
            out["rr"], out["downside_pct"] = None, None
        else:
            out["downside_pct"] = _r((floor / price - 1) * 100, 1)
            out["rr"] = _r((tgt - price) / (price - floor), 1) if tgt else None
    out["alerts"] = _alerts(out, floor, prev)
    return out


def _alerts(out: dict, floor: Optional[float], prev: Optional[dict]) -> dict:
    """今天有沒有跌破停損／碰到目標：有 prev 用前一根的停損（再套底線）與目標；沒有 prev 才用現在的"""
    if prev is not None:
        stop_ref = max([x for x in (prev.get("stop"), floor) if x is not None], default=None)
        target_ref = prev.get("target")
    else:
        stop_ref = (out.get("stop") or {}).get("price")
        target_ref = out.get("target")
    high = out.get("high")
    return {"stop_ref": stop_ref, "target_ref": target_ref,
            "stop_hit": bool(stop_ref is not None and out["price"] < stop_ref),
            "target_hit": bool(target_ref is not None and high is not None and high >= target_ref)}
