"""B74 大盤波浪引擎（PLAN-B74 §4.1～4.3）：ZigZag 轉折點、規則化艾略特數浪、費波那契。
純函式、不碰網路與資料庫；研究（research/wave）與網站共用同一份。

- 轉折點：θ = max(下限, m × ATR%)，ATR% = 近 60 天「ATR14 ÷ 收盤」的中位數（只用當天以前）
- 只有收完的日 K 能確認轉折：第 t 天收盤後用第 t 天的高低價判斷；確認的那天記在 ci
- 數浪：列舉最近最多 11 個轉折＋進行中的極值當起點，套推動浪 1-5（＋A-B-C）、單純 A-B-C 修正，
  B78 加：複合修正 W-X-Y／W-X-Y-X-Z（a-b-c－x－a-b-c…）、三角形 A-B-C-D-E、楔形（傾斜三角形）；
  硬規則淘汰、費波那契貼近度給分（分數越低越好）；上漲與下跌用 x = 方向 × 價格 對稱處理
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

FIB_RET = (0.236, 0.382, 0.5, 0.618, 0.786)
CTRL_RET = (0.32, 0.44, 0.56, 0.68)          # 研究 R1 的對照比例

# 級數：m、下限由 research/wave/calibrate.py 只用 2000–2015 依「平均波段長度」校準（不看之後漲跌）
# 結果 research/wave/calibration.json：小級平均 10.1 天、中級 37.9 天、大級 166.5 天
DEGREES = {
    "small": {"m": 2.0, "floor": 0.03, "label": "小級（短線）"},
    "mid":   {"m": 4.0, "floor": 0.06, "label": "中級（波段）"},
    "big":   {"m": 11.5, "floor": 0.12, "label": "大級（背景）"},
}

# B75 超短線：60 分 K 的級數（θ＝max(下限, m × 60 分 K ATR% 近 60 根中位數)；m 由 research/futures/calibrate_intraday.py 校準，
# 結果寫 wave/stats.json intraday，service 讀到就覆蓋這裡的預設）。不放進 DEGREES，B74 研究照舊只跑日 K 三個級數
INTRA = {"m": 3.0, "floor": 0.005, "label": "60 分 K（超短線）"}
# B76：30 分 K 自己的級數（下限 0.4%；m 由 research/futures/r30.py 校準，寫 stats.json intraday30）
INTRA30 = {"m": 2.5, "floor": 0.004, "label": "30 分 K（當沖～隔天）"}
# B80：15 分 K 自己的級數（下限 0.3%；m 由 research/b80/r15.py 校準平均每段 0.5 個交易日，寫 stats.json intraday15）
INTRA15 = {"m": 2.0, "floor": 0.003, "label": "15 分 K（當沖）"}


def deg_cfg(deg: str) -> dict:
    if deg in DEGREES:
        return DEGREES[deg]
    return {"intra30": INTRA30, "intra15": INTRA15}.get(deg, INTRA)


WAVE_SYM = {"1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤", "A": "Ⓐ", "B": "Ⓑ", "C": "Ⓒ", "0": "◯",
            # B78 複合修正 W-X-Y（-X-Z）的小段、三角形 D、E
            "Wa": "ⓐ", "Wb": "ⓑ", "W": "Ⓦ", "X": "Ⓧ", "Ya": "ⓐ", "Yb": "ⓑ", "Y": "Ⓨ", "X2": "Ⓧ", "Za": "ⓐ", "Zb": "ⓑ", "Z": "Ⓩ",
            "D": "Ⓓ", "E": "Ⓔ"}
# 圖上顯示的字（Wa＝W 裡的 a 段，畫成小寫 a）
WAVE_DISP = {"Wa": "a", "Wb": "b", "Ya": "a", "Yb": "b", "Za": "a", "Zb": "b", "X2": "X"}

# 軟指引（實際比例跟最近的指引比較，懲罰＝|ln(實際/指引)|）
GUIDE = {
    "r2": (0.5, 0.618),          # 第 2 浪回檔 ÷ 第 1 浪
    "r3": (1.618, 2.618),        # 第 3 浪 ÷ 第 1 浪
    "r4": (0.236, 0.382),        # 第 4 浪回檔 ÷ 第 3 浪
    "r5": (0.618, 1.0, 1.618),   # 第 5 浪 ÷ 第 1 浪
    "rB_zig": (0.5, 0.618),      # 鋸齒型 B ÷ A
    "rB_flat": (1.0,),           # 平台型 B ÷ A
}
PRIOR_PEN, PRIOR_N = 0.35, 1.0   # 分數＝(懲罰和＋PRIOR_PEN)÷(項數＋PRIOR_N)：沒驗證到的數法不會贏過驗證過且貼近的
TREND_BONUS = 0.03

# ── B78：補齊艾略特的其他結構 ──
# 複合修正（雙重三浪 W-X-Y＝a-b-c－x－a-b-c、三重三浪 W-X-Y-X-Z）、三角形（收斂／擴散 A-B-C-D-E）、楔形（傾斜三角形）
# 這三種在前 3 段時跟一般 A-B-C／推動浪分不出來 → 只在第 4 段開始後才列為候選（ENABLE_COMPLEX 可整個關掉，研究對照用）
# KIND_PRIOR／SUB_PRIOR：「先用簡單的解釋」（複雜結構很有彈性，隨機走勢也常湊得出來）→ 複雜結構的分數多加一點，
# 要明顯更貼近規則才當主要劇本；貼得更好但沒贏 → primary_alternate 放進替代劇本。
# 校準（research/wave/b78_calibrate.py，只用「加權指數報酬打亂後」沒有結構的資料，不看之後漲跌，選法事先定好）：
#   擴散型加分＝最小的值使擴散型 ≤ 收斂型；複雜度加分＝最小的值使複雜結構當主要劇本 ≤ 15%（三個級數都成立）
#   → 0.08／0.09；真實加權 2001–2026：小級 9.2%、中級 8.5%、大級 24.6% 的天數主要劇本是複雜結構（打亂後 10.4／10.8／9.7%）
ENABLE_COMPLEX = True
KIND_PRIOR = {"impulse": 0.0, "correction": 0.0, "combo": 0.08, "triangle": 0.08, "diagonal": 0.08}
SUB_PRIOR = {"expanding": 0.09}    # 擴散型（三角形、楔形）比收斂型少見 → 再多加
COMPLEX_KINDS = ("combo", "triangle", "diagonal")
GUIDE.update({
    "rX": (0.5, 0.618),            # X 浪回 W 的比例
    "rYW": (0.618, 1.0, 1.618),    # Y ÷ W（Z ÷ Y 同）
    "rTri": (0.618, 0.786),        # 收斂三角形：C÷A、D÷B、E÷C
    "rTriX": (1.272, 1.618),       # 擴散三角形
    "rDia": (0.66, 0.81),          # 楔形第 2、4 浪回檔（比推動浪深）
})
X_MAX = 1.0                        # X 浪不能回到 W 起點以外（再過去就是新趨勢，不是複合修正）
C_SHORT = 0.1                      # 複合修正裡完成的 a-b-c：c 最多比 a 的終點短 0.1 個 a
YW_MAX = 1.618                     # 同一個複合修正的各組大小要相近：Y（含進行中）≤ 1.618 倍 W、Z ≤ 1.618 倍 Y
LEG_MAX = 2.618                    # 擴散三角形／擴散楔形：每一段 ≤ 2.618 倍同方向的前一段（再大就不是同一個型態）
FLAT_MIN, FLAT_MAX = 0.9, 1.38   # B ÷ A：≥0.9 平台型；>1.38 淘汰


# ── 基本指標 ─────────────────────────────────────────────────────────────────
def atr(h, l, c, n: int = 14) -> np.ndarray:
    """14 日真實波幅簡單平均（跟 price_levels.atr_series 同定義）"""
    h, l, c = (np.asarray(x, dtype=float) for x in (h, l, c))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        cs = np.cumsum(tr)
        out[n - 1:] = (cs[n - 1:] - np.r_[0.0, cs[:-n]]) / n
    return out


def atr_pct_median(h, l, c, n: int = 14, look: int = 60) -> np.ndarray:
    """每天的「近 look 天 ATR% 中位數」（只用當天以前，含當天）；資料不夠的前段用目前有的"""
    a = atr(h, l, c, n) / np.asarray(c, dtype=float)
    out = np.full(len(a), np.nan)
    for t in range(len(a)):
        w = a[max(0, t - look + 1): t + 1]
        w = w[~np.isnan(w)]
        if len(w):
            out[t] = float(np.median(w))
    return out


def thresholds(h, l, c, deg: str) -> np.ndarray:
    cfg = deg_cfg(deg)
    ap = atr_pct_median(h, l, c)
    ap = np.where(np.isnan(ap), cfg["floor"] / cfg["m"], ap)
    return np.maximum(cfg["floor"], cfg["m"] * ap)


# ── ZigZag ───────────────────────────────────────────────────────────────────
def zigzag(h, l, theta) -> list:
    """因果（只往前看）ZigZag。回傳確認過的轉折點 [{i, p, t:'H'|'L', ci}]（ci＝確認那天）。
    同一根 K 棒先創新極值就不在同一根確認反轉（日 K 看不出先後，保守）。"""
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    th = np.broadcast_to(np.asarray(theta, dtype=float), h.shape)
    n = len(h)
    piv = []
    if n == 0:
        return piv
    d = 0
    hi_i = lo_i = 0
    for t in range(1, n):
        if d == 0:
            # 起始：還不知道方向，同時追蹤最高、最低；先從較早的那個極值反向走 θ 的就確認
            if h[t] > h[hi_i]:
                hi_i = t
            if l[t] < l[lo_i]:
                lo_i = t
            up = lo_i < t and h[t] >= l[lo_i] * (1 + th[t])
            dn = hi_i < t and l[t] <= h[hi_i] * (1 - th[t])
            if up and (not dn or lo_i < hi_i):
                piv.append({"i": lo_i, "p": float(l[lo_i]), "t": "L", "ci": t})
                hi_i = lo_i + 1 + int(np.argmax(h[lo_i + 1: t + 1]))
                d = 1
            elif dn:
                piv.append({"i": hi_i, "p": float(h[hi_i]), "t": "H", "ci": t})
                lo_i = hi_i + 1 + int(np.argmin(l[hi_i + 1: t + 1]))
                d = -1
            continue
        if d == 1:
            if h[t] > h[hi_i]:
                hi_i = t
                continue
            if l[t] <= h[hi_i] * (1 - th[t]):
                piv.append({"i": hi_i, "p": float(h[hi_i]), "t": "H", "ci": t})
                seg = l[hi_i + 1: t + 1]
                lo_i = hi_i + 1 + int(np.argmin(seg))
                d = -1
        else:
            if l[t] < l[lo_i]:
                lo_i = t
                continue
            if h[t] >= l[lo_i] * (1 + th[t]):
                piv.append({"i": lo_i, "p": float(l[lo_i]), "t": "L", "ci": t})
                seg = h[lo_i + 1: t + 1]
                hi_i = lo_i + 1 + int(np.argmax(seg))
                d = 1
    return piv


def state_at(piv: list, h, l, t: int) -> tuple:
    """第 t 天收盤後看得到的轉折：確認過的（ci ≤ t）＋進行中的極值（最後確認點之後到 t 的最高／最低，第一次出現的那根）。
    回傳 (confirmed, tentative or None)"""
    conf = [p for p in piv if p["ci"] <= t]
    if not conf:
        return [], None
    last = conf[-1]
    if last["i"] >= t:
        return conf, None
    if last["t"] == "H":
        seg = np.asarray(l[last["i"] + 1: t + 1], dtype=float)
        j = last["i"] + 1 + int(np.argmin(seg))
        tent = {"i": j, "p": float(l[j]), "t": "L", "ci": None}
    else:
        seg = np.asarray(h[last["i"] + 1: t + 1], dtype=float)
        j = last["i"] + 1 + int(np.argmax(seg))
        tent = {"i": j, "p": float(h[j]), "t": "H", "ci": None}
    return conf, tent


# ── 艾略特數浪 ───────────────────────────────────────────────────────────────
def _pen(r: float, guides) -> float:
    if r is None or r <= 0 or not math.isfinite(r):
        return 1.0
    return min(abs(math.log(r / g)) for g in guides)


def _impulse(x: list) -> Optional[dict]:
    """x 空間（推動方向往上）檢查推動浪＋之後的 A-B-C。x[0]＝起點，最後一點是進行中的極值。
    違反硬規則回 None；否則回 {pens, kind}"""
    k = len(x) - 1
    seg = [x[j] - x[j - 1] for j in range(1, k + 1)]           # 奇數浪 > 0、偶數浪 < 0（轉折交錯保證）
    if any(s == 0 for s in seg[:-1]):                           # 防呆：完成的浪長度是 0（ZigZag 不會產生，手動資料才可能）
        return None
    L = lambda w: abs(seg[w - 1]) if k >= w else None
    pens, info = {}, {}
    if k >= 2 and not x[2] > x[0]:
        return None                                             # 第 2 浪跌破第 1 浪起點
    if k >= 4 and not x[3] > x[1]:
        return None                                             # 第 3 浪沒超過第 1 浪終點
    if k >= 4 and not x[4] > x[1]:
        return None                                             # 第 4 浪進入第 1 浪價格區
    if k >= 5 and L(3) < L(1) and L(5) > L(3):
        return None                                             # 第 3 浪變成最短
    if k >= 3:
        pens["r2"] = _pen(L(2) / L(1), GUIDE["r2"])
    if k >= 4:
        pens["r3"] = _pen(L(3) / L(1), GUIDE["r3"])
    if k >= 5:
        pens["r4"] = _pen(L(4) / L(3), GUIDE["r4"])
    if k >= 6:
        pens["r5"] = _pen(L(5) / L(1), GUIDE["r5"])
    if k >= 7:                                                  # A＝seg[5]（往下）、B＝seg[6]（往上）
        lenA, lenB = abs(seg[5]), abs(seg[6])
        rB = lenB / lenA if lenA > 0 else 99
        if rB > FLAT_MAX:
            return None
        info["corr_kind"] = "flat" if rB >= FLAT_MIN else "zigzag"
        if k >= 8:                                              # B 已完成
            pens["rB"] = _pen(rB, GUIDE["rB_flat"] if rB >= FLAT_MIN else GUIDE["rB_zig"])
    return {"pens": pens, **info}


def _correction(x: list) -> Optional[dict]:
    """x 空間：單純 A-B-C（A 往上、B 往下、C 往上）。x[0]＝前一段的終點"""
    k = len(x) - 1
    info, pens = {}, {}
    if k >= 2:
        lenA, lenB = x[1] - x[0], x[1] - x[2]
        rB = lenB / lenA if lenA > 0 else 99
        if rB > FLAT_MAX:
            return None
        info["corr_kind"] = "flat" if rB >= FLAT_MIN else "zigzag"
        if k >= 3:
            pens["rB"] = _pen(rB, GUIDE["rB_flat"] if rB >= FLAT_MIN else GUIDE["rB_zig"])
    return {"pens": pens, **info}


def _abc_ok(x: list, i0: int, k: int, pens: dict, key: str) -> bool:
    """x[i0]→a→b→c 這組修正（a 往上）：b ≤ 1.38a；b 完成（c 已開始）才給 b 的分數；
    c 走完（下一段已開始）時 c 要到 a 的終點附近（鋸齒、平台的 c 幾乎都會過 a 的終點；差太多就不是完整的一組 a-b-c）"""
    if k < i0 + 2:
        return True
    a = x[i0 + 1] - x[i0]
    if a <= 0:
        return False
    rB = (x[i0 + 1] - x[i0 + 2]) / a
    if rB <= 0 or rB > FLAT_MAX:
        return False
    if k >= i0 + 3:
        pens[key] = _pen(rB, GUIDE["rB_flat"] if rB >= FLAT_MIN else GUIDE["rB_zig"])
    if k >= i0 + 4 and x[i0 + 3] < x[i0 + 1] - C_SHORT * a:
        return False
    return True


def _beyond_prior(x: list, pre: Optional[float]) -> bool:
    """修正類（複合修正、三角形）整段不能超過它所修正那段的起點（超過＝回檔 100% 以上，已經是新趨勢）"""
    return pre is not None and max(x[1:]) > pre


def _combo(x: list, pre: Optional[float] = None) -> Optional[dict]:
    """x 空間：複合修正 W-X-Y（-X-Z），每一組都是 a-b-c（第一段往上）。點：0 Wa Wb W X Ya Yb Y X2 Za Zb Z"""
    k = len(x) - 1
    if k < 4 or _beyond_prior(x, pre):
        return None                                             # 還沒出現 X：跟單純 A-B-C 一樣，不重複列
    pens: dict = {}
    if not _abc_ok(x, 0, k, pens, "rB_W"):
        return None
    lenW = x[3] - x[0]
    if lenW <= 0:
        return None                                             # W 整組沒有前進
    lenX = x[3] - x[4]
    if lenX <= 0 or lenX / lenW > X_MAX:
        return None                                             # X 回到 W 起點以外
    if k >= 5:
        pens["rX"] = _pen(lenX / lenW, GUIDE["rX"])
    if not _abc_ok(x, 4, k, pens, "rB_Y"):
        return None
    if k >= 5 and max(x[5:min(k, 7) + 1]) - x[4] > YW_MAX * lenW:
        return None                                             # Y（含進行中）比 W 大太多：不像同一組修正
    if k >= 8:                                                  # Y 完成、第二個 X 開始
        lenY = x[7] - x[4]
        if lenY <= 0:
            return None
        pens["rYW"] = _pen(lenY / lenW, GUIDE["rYW"])
        lenX2 = x[7] - x[8]
        if lenX2 <= 0 or lenX2 / lenY > X_MAX:
            return None
        if k >= 9:
            pens["rX2"] = _pen(lenX2 / lenY, GUIDE["rX"])
        if not _abc_ok(x, 8, k, pens, "rB_Z"):
            return None
        if k >= 9 and max(x[9:k + 1]) - x[8] > YW_MAX * lenY:
            return None
    return {"pens": pens, "corr_kind": "wxyxz" if k >= 8 else "wxy"}


def _triangle(x: list, pre: Optional[float] = None) -> Optional[dict]:
    """x 空間：三角形 A-B-C-D-E（A 往上）。只在 D 開始後列為候選。
    收斂：C 不超過 A 的終點、D 不超過 B 的終點、E 不超過 C 的終點（上下兩條線收斂），而且一段比一段短；
    擴散：C 超過 A 的終點、D（走完）超過 B 的終點，每段 ≤ 2.618 倍同方向的前一段。
    （高點、低點一起墊高的收斂形狀是楔形，不是三角形）"""
    k = len(x) - 1
    if k < 4 or _beyond_prior(x, pre):
        return None
    L = [None] + [abs(x[j] - x[j - 1]) for j in range(1, k + 1)]
    if L[1] <= 0 or L[2] <= 0 or L[3] <= 0:
        return None
    pens: dict = {}
    if L[3] < L[1]:                                             # 收斂
        if L[2] / L[1] > FLAT_MAX:
            return None                                         # B 不能比 A 長太多（跟平台型 B 同一條）
        if x[3] > x[1] or x[4] < x[2] or L[4] >= L[2] or (k >= 5 and (L[5] >= L[3] or x[5] > x[3])):
            return None
        pens["rC"] = _pen(L[3] / L[1], GUIDE["rTri"])
        if k >= 5:
            pens["rD"] = _pen(L[4] / L[2], GUIDE["rTri"])
        sub = "contracting"
    else:                                                       # 擴散
        if (x[3] <= x[1] or L[2] > LEG_MAX * L[1] or (k >= 5 and x[4] >= x[2])
                or any(L[j] > LEG_MAX * L[j - 2] for j in range(3, k + 1))):
            return None
        pens["rC"] = _pen(L[3] / L[1], GUIDE["rTriX"])
        if k >= 5:
            pens["rD"] = _pen(L[4] / L[2], GUIDE["rTriX"])
        sub = "expanding"
    return {"pens": pens, "corr_kind": sub}


def _diagonal(x: list, pre: Optional[float] = None) -> Optional[dict]:
    """x 空間：楔形（傾斜三角形）1-5：第 4 浪跟第 1 浪重疊（推動浪不行、楔形可以）。只在第 4 浪開始後列為候選"""
    k = len(x) - 1
    if k < 4:
        return None
    L = [None] + [abs(x[j] - x[j - 1]) for j in range(1, k + 1)]
    if L[1] <= 0 or L[2] <= 0 or L[3] <= 0:
        return None
    if not (x[2] > x[0] and x[3] > x[1]):
        return None                                             # 第 2 浪不能跌破起點、第 3 浪要過第 1 浪終點
    if not (x[4] < x[1] and x[4] > x[2]):
        return None                                             # 第 4 浪要進入第 1 浪區（才是楔形）、但不能過第 2 浪終點
    pens: dict = {"r2": _pen(L[2] / L[1], GUIDE["rDia"])}
    if L[3] < L[1]:                                             # 收斂楔形：3<1、4<2、5<3
        if L[4] >= L[2] or (k >= 5 and L[5] >= L[3]):
            return None
        sub = "contracting"
    else:                                                       # 擴散楔形：3>1、4>2（5>3 要走完才知道）
        if (k >= 5 and L[4] <= L[2]) or any(L[j] > LEG_MAX * L[j - 2] for j in range(3, k + 1)):
            return None
        sub = "expanding"
    if k >= 5:
        pens["r4"] = _pen(L[4] / L[3], GUIDE["rDia"])
    return {"pens": pens, "corr_kind": sub}


_IMP_LABELS = ["0", "1", "2", "3", "4", "5", "A", "B", "C"]
_COR_LABELS = ["0", "A", "B", "C"]
_COMBO_LABELS = ["0", "Wa", "Wb", "W", "X", "Ya", "Yb", "Y", "X2", "Za", "Zb", "Z"]
_TRI_LABELS = ["0", "A", "B", "C", "D", "E"]
_DIA_LABELS = ["0", "1", "2", "3", "4", "5"]


def _invalid_and_targets(kind: str, x: list, cur: str, corr_kind: Optional[str]):
    """回傳 (失效 x, 'below'|'above', [(標籤, x, 'end'|'next')])；全部在 x 空間"""
    k = len(x) - 1
    T = []
    if kind == "impulse":
        len1 = x[1] - x[0] if k >= 1 else None
        if cur == "1":
            return x[0], "below", T
        if cur == "2":
            for r in (0.5, 0.618):
                T.append((f"第 2 浪回 {r:g}", x[1] - r * len1, "end"))
            return x[0], "below", T
        if cur == "3":
            for r in (1.0, 1.618, 2.618):
                v = x[2] + r * len1
                if v > x[3]:
                    T.append((f"第 3 浪 {r:g} 倍第 1 浪", v, "end"))
            return x[2], "below", T
        if cur == "4":
            len3 = x[3] - x[2]
            for r in (0.236, 0.382, 0.5):
                v = x[3] - r * len3
                if v > x[1]:
                    T.append((f"第 4 浪回 {r:g}", v, "end"))
            for r in (0.618, 1.0):
                T.append((f"第 5 浪 {r:g} 倍第 1 浪", x[4] + r * len1, "next"))
            return x[1], "below", T
        if cur == "5":
            len3 = x[3] - x[2]
            cap = x[4] + len3 if len3 < len1 else None
            for r in (0.618, 1.0, 1.618):
                v = x[4] + r * len1
                if v > x[5] and (cap is None or v <= cap):
                    T.append((f"第 5 浪 {r:g} 倍第 1 浪", v, "end"))
            if cap is not None:
                T.append(("第 5 浪上限（第 3 浪不能最短）", cap, "end"))
            return x[4], "below", T
        if cur == "A":
            span = x[5] - x[0]
            for r in (0.382, 0.5, 0.618):
                T.append((f"修正 1-5 浪的 {r:g}", x[5] - r * span, "end"))
            T.append(("第 4 浪低點", x[4], "end"))
            return x[5], "above", T
        if cur == "B":
            lenA = x[5] - x[6]
            for r in (0.5, 0.618, 0.786, 1.0):
                T.append((f"B 浪反彈 {r:g}", x[6] + r * lenA, "end"))
            return x[6] + FLAT_MAX * lenA, "above", T
        if cur == "C":
            lenA = x[5] - x[6]
            for r in (1.0, 1.618):
                T.append((f"C 浪 {r:g} 倍 A 浪", x[7] - r * lenA, "end"))
            return x[7], "above", T
    elif kind == "combo":
        lenW = x[3] - x[0]
        if cur == "X":
            for r in (0.5, 0.618, 0.786):
                T.append((f"X 浪回 W 的 {r:g}", x[3] - r * lenW, "end"))
            return x[0], "below", T
        if cur in ("Ya", "Yb", "Y"):
            for r in (1.0, 1.618):
                T.append((f"Y 浪 {r:g} 倍 W 浪", x[4] + r * lenW, "end" if cur == "Y" else "next"))
            if cur == "Ya":
                return x[0], "below", T
            if cur == "Yb":
                la = x[5] - x[4]
                for r in (0.5, 0.618):
                    T.insert(0, (f"Y 裡的 b 回 {r:g}", x[5] - r * la, "end"))
                return x[5] - FLAT_MAX * la, "below", T
            return x[6], "below", T
        lenY = x[7] - x[4]
        if cur == "X2":
            for r in (0.5, 0.618, 0.786):
                T.append((f"第二個 X 回 Y 的 {r:g}", x[7] - r * lenY, "end"))
            return x[4], "below", T
        if cur in ("Za", "Zb", "Z"):
            for r in (1.0, 1.618):
                T.append((f"Z 浪 {r:g} 倍 Y 浪", x[8] + r * lenY, "end" if cur == "Z" else "next"))
            if cur == "Za":
                return x[4], "below", T
            if cur == "Zb":
                la = x[9] - x[8]
                return x[9] - FLAT_MAX * la, "below", T
            return x[10], "below", T
    elif kind == "triangle":
        L1, L2, L3 = x[1] - x[0], x[1] - x[2], x[3] - x[2]
        con = corr_kind == "contracting"
        if cur == "D":
            for r in ((0.618, 0.786) if con else (1.272, 1.618)):
                T.append((f"D 段 {r:g} 倍 B 段", x[3] - r * L2, "end"))
            return (x[2], "below", T) if con else (x[3], "above", T)
        if cur == "E":
            L4 = x[3] - x[4]
            for r in ((0.618, 0.786) if con else (1.272,)):
                T.append((f"E 段 {r:g} 倍 C 段", x[4] + r * L3, "end"))
            T.append(("三角形走完往原方向突破（≈ 最寬的 A 段）", x[4] + (0.618 if con else 1.272) * L3 - L1, "next"))
            return (min(x[3], x[4] + L3), "above", T) if con else (x[4], "below", T)
    elif kind == "diagonal":
        L1, L3 = x[1] - x[0], x[3] - x[2]
        con = corr_kind == "contracting"
        if cur == "4":
            for r in (0.66, 0.81):
                v = x[3] - r * L3
                if v > x[2]:
                    T.append((f"楔形第 4 浪回 {r:g}", v, "end"))
            return x[2], "below", T
        if cur == "5":
            if con:
                T.append(("楔形第 5 浪 0.618 倍第 3 浪", x[4] + 0.618 * L3, "end"))
                T.append(("第 5 浪上限（要比第 3 浪短）", x[4] + L3, "end"))
            else:
                T.append(("擴散楔形第 5 浪 ≥ 第 3 浪", x[4] + L3, "end"))
            T.append(("楔形走完常急速回到起點", x[0], "next"))
            return x[4], "below", T
    else:
        if cur == "A":
            return x[0], "below", T
        lenA = x[1] - x[0]
        if cur == "B":
            for r in (0.5, 0.618, 0.786, 1.0):
                T.append((f"B 浪 {r:g}", x[1] - r * lenA, "end"))
            return x[1] - FLAT_MAX * lenA, "below", T
        if cur == "C":
            for r in (1.0, 1.618):
                T.append((f"C 浪 {r:g} 倍 A 浪", x[2] + r * lenA, "end"))
            return x[2], "below", T
    return None, None, T


def _describe(kind: str, d: int, cur: str, corr_kind: Optional[str]) -> str:
    up = d > 0
    if kind == "impulse":
        if cur in "12345":
            role = "推進" if cur in "135" else "回檔" if up else "反彈"
            return f"{'上升' if up else '下跌'}推動浪・第 {cur} 浪（{role}）進行中"
        ck = {"flat": "平台型", "zigzag": "鋸齒型"}.get(corr_kind or "", "")
        role = {"A": "下跌" if up else "反彈", "B": "反彈" if up else "回落", "C": "下跌" if up else "反彈"}[cur]
        return f"{'上升' if up else '下跌'}五波結束後的 {ck}A-B-C 修正・{cur} 浪（{role}）進行中"
    if kind == "combo":
        pos = {"X": "X 浪（連接兩組修正）", "Ya": "Y 的 a 段", "Yb": "Y 的 b 段", "Y": "Y 的 c 段",
               "X2": "第二個 X 浪", "Za": "Z 的 a 段", "Zb": "Z 的 b 段", "Z": "Z 的 c 段"}.get(cur, cur)
        name = "W-X-Y-X-Z 三重三" if corr_kind == "wxyxz" else "W-X-Y 雙重三"
        return f"{'漲多後' if not up else '跌深後'}的複合修正（{name}）・{pos}進行中"
    if kind == "triangle":
        return (f"{'收斂' if corr_kind == 'contracting' else '擴散'}三角形整理・{cur} 段進行中"
                f"（{'漲多後' if not up else '跌深後'}的修正，走完通常順原方向突破）")
    if kind == "diagonal":
        return f"{'上升' if up else '下跌'}楔形（{'收斂' if corr_kind == 'contracting' else '擴散'}傾斜三角形）・第 {cur} 浪進行中"
    # 單純修正：d>0 表示 A 往上（空頭裡的反彈修正）；d<0 表示 A 往下（漲多後的修正）
    ck = {"flat": "平台型", "zigzag": "鋸齒型"}.get(corr_kind or "", "")
    role = {"A": "下跌" if not up else "反彈", "B": "反彈" if not up else "回落", "C": "下跌" if not up else "反彈"}[cur]
    return f"{'漲多後' if not up else '跌深後'}的 {ck}A-B-C 修正・{cur} 浪（{role}）進行中"


def _prior_start(pts: list, s: int, d: int) -> Optional[float]:
    """x 空間：起點之前那一段的起點（往回找同方向一路更高的轉折＝那段趨勢的開頭）；前面沒有轉折 → None"""
    j = s - 1
    if j < 0:
        return None
    best = d * pts[j]["p"]
    while j - 2 >= 0 and d * pts[j - 2]["p"] > best:
        j -= 2
        best = d * pts[j]["p"]
    return best


def count_waves(pts: list, trend: int = 0, max_back: int = 11) -> list:
    """pts：確認轉折＋最後一個進行中的極值（價格交錯 H/L）。回傳所有合格數法，依分數排序（低＝好）。
    trend：+1／−1＝大趨勢（例如收盤 vs 年線）；推動方向或「修正前那段」方向跟它一致的加一點分"""
    n = len(pts)
    out = []
    if n < 2:
        return out
    for s in range(max(0, n - 1 - max_back), n - 1):
        seq = pts[s:]
        m = len(seq) - 1
        d = 1 if seq[0]["t"] == "L" else -1
        x = [d * q["p"] for q in seq]
        kinds = [("impulse", _IMP_LABELS, _impulse), ("correction", _COR_LABELS, _correction)]
        if ENABLE_COMPLEX:
            kinds += [("combo", _COMBO_LABELS, _combo), ("triangle", _TRI_LABELS, _triangle), ("diagonal", _DIA_LABELS, _diagonal)]
        pre = _prior_start(pts, s, d) if ENABLE_COMPLEX else None
        for kind, labels, fn in kinds:
            if m > len(labels) - 1:
                continue
            res = fn(x, pre) if kind in COMPLEX_KINDS else fn(x)
            if res is None:
                continue
            pens = res["pens"]
            fit = (sum(pens.values()) + PRIOR_PEN) / (len(pens) + PRIOR_N)
            main_dir = d if kind in ("impulse", "diagonal") else -d     # 修正類：之前那段方向跟第一段相反
            if trend and main_dir == trend:
                fit -= TREND_BONUS
            score = fit + KIND_PRIOR.get(kind, 0.0) + SUB_PRIOR.get(res.get("corr_kind") or "", 0.0)
            cur = labels[m]
            inv_x, side, tg = _invalid_and_targets(kind, x, cur, res.get("corr_kind"))
            if d < 0:                                           # x 空間 → 價格
                side = {"below": "above", "above": "below"}.get(side, side)
            out.append({
                "kind": kind, "dir": d, "start": s, "current": cur, "score": round(score, 4), "fit": round(fit, 4),
                "pens": {k2: round(v, 3) for k2, v in pens.items()}, "corr_kind": res.get("corr_kind"),
                "labels": [{"i": q["i"], "p": q["p"], "label": labels[j], "sym": WAVE_SYM[labels[j]],
                            "disp": WAVE_DISP.get(labels[j], labels[j]),
                            "tentative": q.get("ci") is None} for j, q in enumerate(seq)],
                "invalid": None if inv_x is None else round(d * inv_x, 2), "invalid_side": side,
                "targets": [{"label": a, "price": round(d * v, 2), "kind": b} for a, v, b in tg],
                "text": _describe(kind, d, cur, res.get("corr_kind")),
            })
    out.sort(key=lambda c: (c["score"], -len(c["labels"])))
    return out


def primary_alternate(counts: list) -> tuple:
    """主要劇本＝分數最好；替代劇本＝目前浪別或結構不同的下一個。
    B78：主要劇本是簡單結構、但有複雜結構「不算複雜度加分時」比主要劇本更貼近規則 → 替代劇本改放它
    （複雜結構要明顯更好才當主要劇本，但貼得很好時一定看得到）"""
    if not counts:
        return None, None
    p = counts[0]
    alt = None
    for c in counts[1:]:
        if (c["kind"], c["current"], c["dir"]) != (p["kind"], p["current"], p["dir"]):
            alt = c
            break
    if p["kind"] not in COMPLEX_KINDS and (alt is None or alt["kind"] not in COMPLEX_KINDS):
        cx = [c for c in counts if c["kind"] in COMPLEX_KINDS and c.get("fit", c["score"]) < p["score"]]
        if cx:
            alt = min(cx, key=lambda c: (c["fit"], -len(c["labels"])))
    return p, alt


# ── 費波那契 ─────────────────────────────────────────────────────────────────
def fib_retrace(a: float, b: float, ratios=FIB_RET) -> list:
    """a→b 這段的回檔價位（b 往 a 方向）"""
    return [{"ratio": r, "price": round(b - r * (b - a), 2)} for r in ratios]


def analyze(o, h, l, c, deg: str = "mid", t: Optional[int] = None, trend: int = 0, piv: Optional[list] = None) -> dict:
    """單一級數在第 t 天（預設最後一天）收盤後的完整結果"""
    h = np.asarray(h, dtype=float)
    l = np.asarray(l, dtype=float)
    c = np.asarray(c, dtype=float)
    t = len(c) - 1 if t is None else t
    if piv is None:
        piv = zigzag(h[: t + 1], l[: t + 1], thresholds(h[: t + 1], l[: t + 1], c[: t + 1], deg))
    conf, tent = state_at(piv, h, l, t)
    pts = conf + ([tent] if tent else [])
    counts = count_waves(pts, trend=trend)
    prim, alt = primary_alternate(counts)
    fib = None
    if len(conf) >= 2:
        a, b = conf[-2], conf[-1]
        fib = {"from": {"i": a["i"], "p": a["p"]}, "to": {"i": b["i"], "p": b["p"]}, "levels": fib_retrace(a["p"], b["p"])}
    return {"deg": deg, "label": deg_cfg(deg)["label"], "t": t, "pivots": conf, "tentative": tent,
            "primary": prim, "alternate": alt, "n_counts": len(counts), "fib": fib}
