"""B74 每日特徵（PLAN-B74 §4.5～4.7）：研究與網站共用。
輸入加權日 K（date,o,h,l,c）、大盤籌碼（mkt_chips 格式）、國外指數日 K；輸出一列一天的 DataFrame。
- 籌碼：外資＝Foreign_Investor＋Foreign_Dealer_Self（億元）；期貨＝外資台指期多方未平倉−空方（口）；融資＝融資金額（億元）
- 國外指數用「台股這天之前」最後一個收盤（美股前一晚、日韓前一天收盤），不用今天還沒收的 K 棒
- 連買／連賣天數用交易日列計算（農曆年長假不會斷）"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import engine as E

DD_EDGES = (0.05, 0.10, 0.15)   # 離 60 日高點跌幅分組：0～5／5～10／10～15／>15%


def dd_bucket(dd: float) -> Optional[int]:
    if dd is None or not np.isfinite(dd):
        return None
    x = -dd
    for k, e in enumerate(DD_EDGES):
        if x < e:
            return k
    return len(DD_EDGES)


def _zscore_trailing(s: pd.Series, n: int = 250, minp: int = 120) -> pd.Series:
    m = s.rolling(n, min_periods=minp).mean()
    sd = s.rolling(n, min_periods=minp).std()
    return (s - m) / sd


def _pct_trailing(s: pd.Series, n: int = 250, minp: int = 120) -> pd.Series:
    return s.rolling(n, min_periods=minp).apply(lambda w: (w[:-1] <= w[-1]).mean() if len(w) > 1 else np.nan, raw=True)


def streak(vals) -> np.ndarray:
    """連續同號天數（正＝連買幾天、負＝連賣幾天；0 或缺資料就斷）"""
    out = np.zeros(len(vals), dtype=int)
    run = 0
    for i, v in enumerate(vals):
        if v is None or not np.isfinite(v) or v == 0:
            run = 0
        elif v > 0:
            run = run + 1 if run > 0 else 1
        else:
            run = run - 1 if run < 0 else -1
        out[i] = run
    return out


def align_prev(tw_dates: pd.Series, other: pd.DataFrame, col: str = "c") -> pd.Series:
    """台股每一天 → 國外指數「日期 < 台股日期」的最後一個值"""
    if other is None or other.empty:
        return pd.Series(np.nan, index=tw_dates.index)
    o = other[["date", col]].dropna().sort_values("date")
    od = o["date"].values.astype(str)
    ov = o[col].values.astype(float)
    pos = np.searchsorted(od, tw_dates.values.astype(str), side="left") - 1
    res = np.where(pos >= 0, ov[np.clip(pos, 0, len(ov) - 1)], np.nan)
    return pd.Series(res, index=tw_dates.index)


def build(tw: pd.DataFrame, chips: Optional[pd.DataFrame] = None, sox: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    df = tw[["date", "o", "h", "l", "c"]].copy().reset_index(drop=True)
    df["date"] = df["date"].astype(str)
    c = df["c"].astype(float)
    for n in (20, 60, 120, 240):
        df[f"ma{n}"] = c.rolling(n).mean()
    df["atr"] = E.atr(df.h.values, df.l.values, df.c.values)
    df["above_ma60"] = np.where(df.ma60.notna(), (c > df.ma60).astype(float), np.nan)
    df["dd60"] = c / c.rolling(60, min_periods=20).max() - 1
    df["dd_b"] = [dd_bucket(x) for x in df["dd60"]]
    for hz in (5, 20, 60):
        df[f"fwd{hz}"] = c.shift(-hz) / c - 1
    # 籌碼
    if chips is not None and not chips.empty:
        ch = chips.copy()
        ch["date"] = ch["date"].astype(str)
        df = df.merge(ch, on="date", how="left")
        if "f_net" in df:
            f = df["f_net"]
            df["f5"] = f.rolling(5, min_periods=5).sum()
            df["f20"] = f.rolling(20, min_periods=20).sum()
            df["f5_z"] = _zscore_trailing(df["f5"])
            df["f_streak"] = streak(f.values)
        if "fut_f_oi" in df:
            df["fut_pct"] = _pct_trailing(df["fut_f_oi"])
            df["fut_chg5"] = df["fut_f_oi"] - df["fut_f_oi"].shift(5)
        if "margin_amt" in df:
            df["margin_chg20"] = df["margin_amt"] / df["margin_amt"].shift(20) - 1
    # 費半
    if sox is not None and not sox.empty:
        s = sox.sort_values("date").copy()
        s["date"] = s["date"].astype(str)
        s["ma60"] = s["c"].rolling(60).mean()
        s["ret1"] = s["c"].pct_change()
        df["sox_c"] = align_prev(df["date"], s, "c")
        df["sox_above_ma60"] = (align_prev(df["date"], s, "c") > align_prev(df["date"], s, "ma60")).astype(float)
        df.loc[align_prev(df["date"], s, "ma60").isna(), "sox_above_ma60"] = np.nan
        df["sox_ret1"] = align_prev(df["date"], s, "ret1")
    return df


def tercile(values: pd.Series, edges: tuple) -> pd.Series:
    """依樣本內的兩個切點分成 0／1／2；缺值 NaN"""
    lo, hi = edges
    v = values.astype(float)
    out = np.where(v.isna(), np.nan, np.where(v <= lo, 0, np.where(v <= hi, 1, 2)))
    return pd.Series(out, index=values.index)


def chips_from_finmind(inst: pd.DataFrame, fut: pd.DataFrame, margin: pd.DataFrame) -> pd.DataFrame:
    """FinMind 三個資料集 → mkt_chips 格式（date, f_net, t_net, d_net 億元；fut_f_oi 口；margin_amt 億元）"""
    parts = []
    if inst is not None and not inst.empty:
        x = inst.copy()
        x["net"] = (x["buy"].astype(float) - x["sell"].astype(float)) / 1e8
        pv = x.pivot_table(index="date", columns="name", values="net", aggfunc="sum")
        g = lambda *cols: sum(pv[c2] for c2 in cols if c2 in pv) if any(c2 in pv for c2 in cols) else np.nan
        parts.append(pd.DataFrame({"f_net": g("Foreign_Investor", "Foreign_Dealer_Self"),
                                   "t_net": g("Investment_Trust"),
                                   "d_net": g("Dealer_self", "Dealer_Hedging")}))
    if fut is not None and not fut.empty:
        y = fut[fut["institutional_investors"].astype(str).str.contains("外資")].copy()
        y["fut_f_oi"] = y["long_open_interest_balance_volume"].astype(float) - y["short_open_interest_balance_volume"].astype(float)
        parts.append(y.groupby("date")[["fut_f_oi"]].sum())
    if margin is not None and not margin.empty:
        z = margin[margin["name"] == "MarginPurchaseMoney"].copy()
        z["margin_amt"] = z["TodayBalance"].astype(float) / 1e8
        parts.append(z.groupby("date")[["margin_amt"]].last())
    if not parts:
        return pd.DataFrame(columns=["date"])
    out = pd.concat(parts, axis=1).sort_index()
    out.index.name = "date"
    return out.reset_index()
