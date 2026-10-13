"""
deep_patterns.py — 宏爺 AI 戰情室的 K 線型態與 MA20／MA100 趨勢格局（2026-10-13，B67），純函式、可測

K 線型態：照宏爺 ai_engine.classify_kbar 的 16 種定義（實體／影線佔整根比例、實體佔開盤價 %）
趨勢格局：多頭＝站上 MA20 與 MA100；空頭＝都在下面；多箱＝MA20 下、MA100 上；空箱＝MA20 上、MA100 下
回測（research/deep/hongye.py，1,200 萬筆不還原日 K、2025-04～2026-09、20 日均量 ≥300 張且股價 ≥10、每天取樣）：
  - 格局有用：多頭 20 天平均比同期 +1.12%、空頭 −1.07%，兩年都一樣；技術強勢裡 多頭 +2.31% vs 多箱 +1.04%
  - K 線型態主要反映位置（動能）：宏爺說「高檔墓碑線／倒T＝見頂」「低檔鎚子／T字＝止跌」，回測剛好相反
    （高檔出現後 20 天平均 +3.5～4.7%，比高檔平均 +2.2% 還好；低檔出現後 −1.6～−2.8%，比低檔平均 −1.3% 還差）
常數格式 (x5, x20, 20 日後上漲%, 筆數)；x＝未來報酬 − 同一天所有樣本平均（%）
"""
from __future__ import annotations

import math

import pandas as pd

# 每種型態一句話（宏爺 prompt 的定義）
KBAR_MEANING = {
    "大紅K": "實體大、漲幅 ≥7%，多方強勢",
    "中紅K": "實體中等、漲 3～7%，多方明確",
    "小紅K": "實體小、漲不到 3%，多方偏弱",
    "大黑K": "實體大、跌幅 ≥7%，空方強勢",
    "中黑K": "實體中等、跌 3～7%，空方明確",
    "小黑K": "實體小、跌不到 3%，空方偏弱",
    "倒鎚紅K(墓碑線-上漲)": "上影線長：買方追高遇到賣壓",
    "倒鎚黑K(墓碑線-下跌)": "上影線長：拉高後被壓下來",
    "紅K鎚子(吊人線-上漲)": "下影線長：殺下去有買盤接回",
    "黑K鎚子(吊人線-下跌)": "下影線長：殺盤後略有反彈",
    "紡錘紅K": "上下影線都長：多空交戰",
    "紡錘黑K": "上下影線都長：多空交戰",
    "十字線": "開盤≈收盤：多空平衡，可能轉折",
    "T字線": "開＝高＝收、長下影線：低檔有支撐",
    "倒T線": "開＝低＝收、長上影線：上面壓力大",
    "一字線": "開高低收幾乎一樣：漲跌停或沒量",
}
UP_TYPES = {"大紅K", "中紅K", "小紅K", "倒鎚紅K(墓碑線-上漲)", "紅K鎚子(吊人線-上漲)", "紡錘紅K"}
DOWN_TYPES = {"大黑K", "中黑K", "小黑K", "倒鎚黑K(墓碑線-下跌)", "黑K鎚子(吊人線-下跌)", "紡錘黑K"}

# ── 回測常數（research/deep/hongye.py → hongye_result.json；重跑後更新這裡）──────────────
HONGYE_PERIOD = "2025-04～2026-09"
BOX_STATS = {"多頭": (0.29, 1.12, 47, 124853), "多箱": (-0.03, 0.09, 46, 55595), "空箱": (-0.19, -0.59, 48, 47221), "空頭": (-0.23, -1.07, 52, 109921)}
BOX_IN_BUCKET = {
    "strong": {"多頭": (0.65, 2.31, 49, 64744), "多箱": (0.22, 1.04, 47, 14760)},
    "neutral": {"多頭": (-0.1, -0.16, 45, 59680), "多箱": (-0.11, -0.24, 46, 40520), "空箱": (-0.02, 0.08, 48, 23373), "空頭": (0.05, -0.08, 51, 36487)},
    "weak": {"多頭": (-0.15, -0.77, 46, 429), "多箱": (-0.41, -1.63, 49, 315), "空箱": (-0.37, -1.24, 47, 23820), "空頭": (-0.37, -1.56, 53, 73326)},
}
BAND_BASE = {"hi": (0.62, 2.23, 50, 81829), "mid": (-0.11, -0.23, 47, 142617), "lo": (-0.31, -1.33, 49, 113144)}
KBAR_STATS = {
    "紡錘黑K": {"all": (-0.06, -0.08, 49, 136493), "hi": (0.39, 2.02, 50, 29750), "mid": (-0.1, -0.11, 48, 59485), "lo": (-0.31, -1.35, 50, 47258)},
    "紡錘紅K": {"all": (-0.03, 0.13, 49, 101844), "hi": (0.56, 2.2, 51, 28598), "mid": (-0.18, -0.19, 48, 42349), "lo": (-0.37, -1.34, 49, 30897)},
    "小黑K": {"all": (-0.16, -1.01, 49, 18629), "hi": (0.28, 0.66, 50, 1827), "mid": (-0.21, -0.99, 48, 7499), "lo": (-0.21, -1.36, 50, 9303)},
    "中黑K": {"all": (0.05, 0.01, 48, 16521), "hi": (0.23, 1.49, 47, 3061), "mid": (0.01, -0.14, 45, 7684), "lo": (0.03, -0.56, 52, 5776)},
    "十字線": {"all": (-0.22, -0.62, 49, 16506), "hi": (0.33, 1.56, 51, 3600), "mid": (-0.36, -0.88, 47, 6835), "lo": (-0.4, -1.61, 49, 6071)},
    "中紅K": {"all": (0.37, 1.57, 51, 7677), "hi": (1.34, 4.15, 53, 3255), "mid": (-0.22, 0.11, 48, 2766), "lo": (-0.57, -1.05, 51, 1656)},
    "小紅K": {"all": (-0.13, -0.93, 49, 7269), "hi": (0.88, 1.08, 51, 1437), "mid": (-0.31, -1.12, 47, 3015), "lo": (-0.45, -1.74, 49, 2817)},
    "大紅K": {"all": (1.31, 2.64, 48, 6098), "hi": (2.02, 4.3, 50, 3428), "mid": (0.54, 0.79, 46, 1976), "lo": (0.04, -0.34, 42, 694)},
    "倒鎚紅K(墓碑線-上漲)": {"all": (0.13, 0.07, 49, 5985), "hi": (1.3, 3.48, 52, 1160), "mid": (-0.19, -0.61, 46, 2567), "lo": (-0.12, -0.9, 50, 2258)},
    "倒鎚黑K(墓碑線-下跌)": {"all": (0.01, 0.34, 50, 4942), "hi": (0.39, 3.47, 53, 903), "mid": (0.07, 0.35, 49, 2219), "lo": (-0.26, -1.23, 49, 1820)},
    "黑K鎚子(吊人線-下跌)": {"all": (-0.25, -1.42, 46, 4512), "hi": (0.81, 0.31, 46, 983), "mid": (-0.1, -1.05, 46, 1801), "lo": (-1.0, -2.78, 46, 1728)},
    "大黑K": {"all": (0.51, 1.17, 47, 3155), "hi": (0.1, 1.05, 45, 1323), "mid": (0.73, 1.41, 47, 1425), "lo": (1.09, 0.73, 53, 407)},
    "紅K鎚子(吊人線-上漲)": {"all": (0.11, -0.34, 48, 2770), "hi": (0.58, 1.68, 49, 851), "mid": (0.23, -0.97, 48, 1049), "lo": (-0.49, -1.57, 48, 870)},
    "倒T線": {"all": (0.45, 0.61, 50, 2126), "hi": (1.5, 4.69, 57, 410), "mid": (0.22, 0.08, 49, 881), "lo": (0.18, -0.83, 48, 835)},
    "T字線": {"all": (0.53, 0.54, 46, 1835), "hi": (1.62, 4.57, 49, 629), "mid": (0.16, -1.04, 46, 663), "lo": (-0.29, -2.2, 43, 543)},
    "一字線": {"all": (3.02, 3.27, 50, 1228), "hi": (4.42, 6.11, 52, 614), "mid": (2.27, 2.86, 51, 403), "lo": (0.37, -4.21, 44, 211)},
}
# 位置：hi＝52 週位置 ≥70%、lo＝≤30%、mid＝中間
BAND_LABEL = {"hi": "高檔（52 週位置 ≥70%）", "mid": "中段", "lo": "低檔（52 週位置 ≤30%）"}
# 宏爺說是反轉訊號的型態（位置 → 型態），回測都不成立
HONGYE_CLAIMS = {"hi": {"倒鎚紅K(墓碑線-上漲)", "倒鎚黑K(墓碑線-下跌)", "倒T線"},
                 "lo": {"紅K鎚子(吊人線-上漲)", "黑K鎚子(吊人線-下跌)", "T字線"}}

BOX_DESC = {
    "多頭": "站上 20 日線與 100 日線",
    "空頭": "跌破 20 日線與 100 日線",
    "多箱": "在 20 日線下、100 日線上（中期多、短期整理）",
    "空箱": "在 20 日線上、100 日線下（中期空、短期反彈）",
}


def _bad(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def kbar_type(o, h, l, c) -> str | None:
    """宏爺 classify_kbar 原樣移植；資料不完整回 None"""
    if any(_bad(x) for x in (o, h, l, c)) or o <= 0:
        return None
    o, h, l, c = float(o), float(h), float(l), float(c)
    body = abs(c - o)
    rng = h - l
    if rng < 0.001:
        return "一字線"
    if c >= o:
        upper, lower = h - c, o - l
    else:
        upper, lower = h - o, c - l
    body_ratio = body / rng
    chg = body / o * 100
    if body_ratio < 0.05:                                   # 十字線系列
        if rng / o < 0.003:
            return "一字線"
        if upper < rng * 0.1 and lower > body * 2:
            return "T字線"
        if lower < rng * 0.1 and upper > body * 2:
            return "倒T線"
        return "十字線"
    if (upper + lower) / rng <= 0.2:                        # 實體 K（影線 ≤20%）
        size = "大" if body_ratio > 0.7 and chg >= 7 else "中" if body_ratio > 0.4 and chg >= 3 else "小"
        return f"{size}{'紅' if c > o else '黑'}K"
    if upper > body * 2 and lower < body * 0.3:
        return "倒鎚紅K(墓碑線-上漲)" if c >= o else "倒鎚黑K(墓碑線-下跌)"
    if lower > body * 2 and upper < body * 0.3:
        return "紅K鎚子(吊人線-上漲)" if c >= o else "黑K鎚子(吊人線-下跌)"
    return "紡錘紅K" if c >= o else "紡錘黑K"


def kbar_chain(df: pd.DataFrame, n: int = 3) -> list:
    """最近 n 根 [{date, type, meaning, chg}]，舊→新；chg＝跟前一天收盤比的漲跌 %"""
    if df is None or len(df) == 0:
        return []
    tail = df.tail(n + 1).reset_index(drop=True)
    out = []
    for i in range(max(0, len(tail) - n), len(tail)):
        r = tail.iloc[i]
        t = kbar_type(r.get("open"), r.get("high"), r.get("low"), r.get("close"))
        if t is None:
            continue
        prev = float(tail.iloc[i - 1]["close"]) if i > 0 else None
        chg = round((float(r["close"]) / prev - 1) * 100, 2) if prev else None
        out.append({"date": str(r.get("date", "")), "type": t, "meaning": KBAR_MEANING.get(t, ""), "chg": chg})
    return out


def trend_box(close, ma20, ma100) -> str | None:
    """宏爺的四種格局；均線不足回 None。剛好等於均線算「在下面」（宏爺原本會落到「盤整／不明」）"""
    if any(_bad(x) for x in (close, ma20, ma100)):
        return None
    above20, above100 = close > ma20, close > ma100
    if above20 and above100:
        return "多頭"
    if not above20 and not above100:
        return "空頭"
    return "多箱" if above100 else "空箱"


# ── 月線斜率分級（B71）：0.4%、1%、3% 來自權證小哥（商周財富網、CMoney 筆記），負的對稱 ──
# 回測 research/course/mslope.py（40 萬筆、2025-04～2026-09）：之後 20 天平均比同期，兩段同方向
MSLOPE_TIERS = [   # (下限, 名稱, 白話, 20 天超額 %)
    (3.0, "妖股", "月線極陡往上（權證小哥：>3% 妖股）", 3.46),
    (1.0, "強勢", "月線陡升（權證小哥：>1% 強勢股）", 2.19),
    (0.4, "上揚", "月線穩定往上", 0.92),
    (-0.4, "走平", "月線幾乎沒動，方向不明", -0.49),
    (-1.0, "下彎", "月線往下", -0.97),
    (float("-inf"), "急跌", "月線急跌（跌深之後常有反彈）", 0.80),
]


def mslope_tier(v) -> dict | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    # ≥3 妖股、≥1 強勢、≥0.4 上揚、>−0.4 走平、>−1 下彎、≤−1 急跌（跟回測分組一樣）
    i = 0 if v >= 3 else 1 if v >= 1 else 2 if v >= 0.4 else 3 if v > -0.4 else 4 if v > -1 else 5
    _, name, desc, x20 = MSLOPE_TIERS[i]
    return {"tier": name, "desc": desc, "x20": x20}


def mslope_info(closes, n: int = 30) -> dict | None:
    """月線斜率全套：今天斜率、分級、月線連續上揚／下彎天數（+／−）、近 n 天月線與斜率（畫走勢用）；不到 21 根回 None"""
    c = [float(x) for x in closes if x is not None and x == x]
    if len(c) < 21:
        return None
    ma = [sum(c[i - 19:i + 1]) / 20 for i in range(19, len(c))]                 # 每天的月線
    sl = [round((ma[i] / ma[i - 1] - 1) * 100, 2) for i in range(1, len(ma)) if ma[i - 1] > 0]
    if not sl:
        return None
    streak, sign = 0, 0
    for v in reversed(sl):
        sg = (v > 0) - (v < 0)
        if sg == 0 or (sign and sg != sign):
            break
        sign, streak = sg, streak + 1
    t = mslope_tier(sl[-1]) or {}
    return {"slope": sl[-1], **t, "streak": streak * sign,
            "ma20": [round(x, 2) for x in ma[-n:]], "slopes": sl[-n:]}


def month_slope(closes) -> float | None:
    """權證小哥月線斜率（%）＝(今天 MA20 − 昨天 MA20) ÷ 昨天 MA20 × 100；>1% 強勢、>3% 妖股；不到 21 根回 None"""
    c = [float(x) for x in closes if x is not None and x == x]
    if len(c) < 21:
        return None
    today, yday = sum(c[-20:]) / 20, sum(c[-21:-1]) / 20
    return round((today / yday - 1) * 100, 2) if yday > 0 else None


def trend_info(df: pd.DataFrame) -> dict | None:
    """{box, desc, ma20, ma100, bias20, bias100}；K 線不到 100 根回 None"""
    if df is None or len(df) < 100:
        return None
    c = df["close"].astype(float)
    close = float(c.iloc[-1])
    ma20, ma100 = float(c.tail(20).mean()), float(c.tail(100).mean())
    box = trend_box(close, ma20, ma100)
    if box is None:
        return None
    ma20_prev = float(c.iloc[-25:-5].mean()) if len(c) >= 25 else None
    ma100_prev = float(c.iloc[-105:-5].mean()) if len(c) >= 105 else None
    return {
        "box": box, "desc": BOX_DESC[box],
        "ma20": round(ma20, 2), "ma100": round(ma100, 2),
        "bias20": round((close / ma20 - 1) * 100, 2), "bias100": round((close / ma100 - 1) * 100, 2),
        "ma20_up": (ma20 > ma20_prev) if ma20_prev else None,
        "ma100_up": (ma100 > ma100_prev) if ma100_prev else None,
        "mslope": month_slope(c.tail(21).tolist()),
        "ms": mslope_info(c.tail(60).tolist()),
    }


def band_of(pos52) -> str | None:
    if _bad(pos52):
        return None
    return "hi" if pos52 >= 0.7 else "lo" if pos52 <= 0.3 else "mid"


def kbar_stat(ktype: str | None, pos52=None) -> dict | None:
    """今天這種 K 線過去的表現；有 52 週位置就用同位置的（跟同位置所有股票比），沒有就用全部"""
    e = KBAR_STATS.get(ktype or "")
    if not e:
        return None
    band = band_of(pos52)
    key = band if band and band in e else "all"
    x5, x20, up, n = e[key]
    out = {"band": key, "band_label": BAND_LABEL.get(key, "全部位置"), "x5": x5, "x20": x20, "up": up, "n": n}
    if key in BAND_BASE:
        out["base_x20"] = BAND_BASE[key][1]
        out["diff"] = round(x20 - BAND_BASE[key][1], 2)
    if band and ktype in HONGYE_CLAIMS.get(band, ()):
        out["claim"] = "見頂" if band == "hi" else "止跌"
    return out


def box_stat(box: str | None, bucket: str | None = None) -> dict | None:
    """格局過去的表現；bucket（deep_verdict 的 strong／neutral／weak）有樣本就一起給"""
    if box not in BOX_STATS:
        return None
    x5, x20, up, n = BOX_STATS[box]
    out = {"x5": x5, "x20": x20, "up": up, "n": n}
    ib = BOX_IN_BUCKET.get(bucket or "", {}).get(box)
    if ib:
        out["in_bucket"] = {"x5": ib[0], "x20": ib[1], "up": ib[2], "n": ib[3]}
    return out


# ── 週 K（B70：AI 解盤／技術分頁看週線組合）────────────────────────────────────

def weekly_bars(df: pd.DataFrame, today=None) -> list:
    """日 K → 週 K（ISO 週）：[{wk, start, end, open, high, low, close, days, partial}]，舊→新
    partial＝最後一根而且是「今天這週」還沒走完（today 預設台灣今天；週六日看的是上週，算完整）"""
    if df is None or len(df) == 0 or "date" not in df.columns:
        return []
    d = df.dropna(subset=["open", "high", "low", "close"])
    if not len(d):
        return []
    dt = pd.to_datetime(d["date"].astype(str).str.replace("-", ""), format="%Y%m%d", errors="coerce")
    d = d.assign(_dt=dt.values).dropna(subset=["_dt"])
    iso = d["_dt"].dt.isocalendar()
    d = d.assign(_wk=(iso.year.astype(int) * 100 + iso.week.astype(int)).values)
    out = []
    for wk, g in d.groupby("_wk", sort=True):
        out.append({"wk": int(wk), "start": g["_dt"].iloc[0].strftime("%Y%m%d"), "end": g["_dt"].iloc[-1].strftime("%Y%m%d"),
                    "open": float(g["open"].iloc[0]), "high": float(g["high"].max()), "low": float(g["low"].min()),
                    "close": float(g["close"].iloc[-1]), "days": int(len(g)), "partial": False})
    if out:
        if today is None:
            from datetime import datetime, timedelta, timezone
            today = datetime.now(timezone(timedelta(hours=8))).date()
        ty, tw, twd = today.isocalendar()
        out[-1]["partial"] = bool(out[-1]["wk"] == ty * 100 + tw and twd <= 5)
    return out


def weekly_chain(df: pd.DataFrame, n: int = 4, today=None) -> list:
    """最近 n 根週 K [{start, end, type, meaning, chg, partial}]；chg＝跟前一週收盤比"""
    ws = weekly_bars(df, today)
    out = []
    for i in range(max(0, len(ws) - n), len(ws)):
        w = ws[i]
        t = kbar_type(w["open"], w["high"], w["low"], w["close"])
        if t is None:
            continue
        prev = ws[i - 1]["close"] if i > 0 else None
        out.append({"start": w["start"], "end": w["end"], "type": t, "meaning": KBAR_MEANING.get(t, ""),
                    "chg": round((w["close"] / prev - 1) * 100, 2) if prev else None, "partial": w["partial"],
                    "days": w["days"]})
    return out


KBAR_W_STATS = {          # research/deep/hongye.py --weekly（2025-04～2026-09，只用走完的週，未來 20 個交易日）
    "紡錘紅K": {"all": (-0.07, 0.27, 48, 27346), "hi": (0.67, 2.55, 51, 8448), "mid": (-0.25, -0.14, 47, 11270), "lo": (-0.62, -1.65, 47, 7628)},
    "紡錘黑K": {"all": (0.0, -0.46, 48, 26835), "hi": (0.52, 1.66, 49, 4647), "mid": (0.02, -0.28, 48, 12007), "lo": (-0.26, -1.64, 49, 10181)},
    "十字線": {"all": (-0.13, 0.27, 51, 3258), "hi": (0.83, 3.35, 53, 704), "mid": (-0.41, 0.3, 51, 1386), "lo": (-0.38, -1.62, 50, 1168)},
    "大黑K": {"all": (-0.15, 0.16, 47, 3137), "hi": (-0.51, -1.77, 41, 278), "mid": (-0.09, 1.07, 47, 1730), "lo": (-0.15, -0.75, 48, 1129)},
    "大紅K": {"all": (1.17, 3.18, 50, 3019), "hi": (1.86, 4.98, 53, 1845), "mid": (0.34, 0.39, 46, 890), "lo": (-0.71, 0.22, 45, 284)},
    "中黑K": {"all": (-0.28, -0.98, 49, 2248), "mid": (-0.05, -0.22, 49, 798), "lo": (-0.46, -1.69, 50, 1328)},
    "倒鎚紅K(墓碑線-上漲)": {"all": (-0.07, -0.97, 42, 1058), "hi": (0.78, -0.03, 44, 247), "mid": (-0.04, -0.6, 41, 484), "lo": (-0.77, -2.24, 41, 327)},
    "倒鎚黑K(墓碑線-下跌)": {"all": (0.33, -0.01, 47, 849), "mid": (0.33, -0.2, 44, 414), "lo": (0.12, -0.23, 48, 289)},
    "中紅K": {"all": (-0.08, -1.0, 42, 705), "hi": (-0.51, -2.02, 42, 197), "mid": (0.06, -0.97, 40, 305), "lo": (0.11, -0.06, 44, 203)},
    "黑K鎚子(吊人線-下跌)": {"all": (-0.23, -0.55, 53, 535), "mid": (0.37, 0.96, 56, 203), "lo": (-0.2, -1.27, 53, 238)},
    "小黑K": {"all": (-0.37, -1.86, 45, 410), "lo": (-0.39, -2.44, 44, 246)},
    "紅K鎚子(吊人線-上漲)": {"all": (0.28, -0.11, 50, 277)},
    "倒T線": {"all": (-0.11, -2.17, 40, 273)},
}
BAND_BASE_W = {"hi": (0.71, 2.35, 50, 16973), "mid": (-0.1, -0.12, 47, 29940), "lo": (-0.4, -1.57, 48, 23277)}


def kbar_w_stat(ktype: str | None, pos52=None) -> dict | None:
    """最後一根「完整」週 K 型態的回測；沒有常數回 None（畫面標未回測）"""
    e = KBAR_W_STATS.get(ktype or "")
    if not e:
        return None
    band = band_of(pos52)
    key = band if band and band in e else "all"
    x5, x20, up, n = e[key]
    out = {"band": key, "band_label": BAND_LABEL.get(key, "全部位置"), "x5": x5, "x20": x20, "up": up, "n": n}
    if key in BAND_BASE_W:
        out["base_x20"] = BAND_BASE_W[key][1]
    return out
