"""B75 期貨＋籌碼綜合研判（PLAN-B75 §6）：研究（research/futures/run.py）與網站共用同一份特徵定義。
- 每列＝加權的一個交易日 T；所有特徵只用「T 日結束前（夜盤＝T 日 05:00 前）已知」的資料
- 夜盤報酬 night_ret(T)：夜盤（T−1 15:00～T 05:00）收／同月份前一日盤收−1 → 預測 T 日加權（開盤跳空 gap、全天 r1）
- 收盤後才公布的（價差、外資期貨、選擇權、散戶小台、外資現貨、融資）：(a) 隔天＝扣掉隔天夜盤能解釋的部分後的殘差；
  (b) 5／20 天從隔天開盤起算
- 方向：研究通過（✅）的指標各 sign(狀態)×polarity 加總；沒通過的只描述（△）"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

# key → (名稱, 目標種類, 一句意思, 單位格式)
FACTORS = {
    "night_ret":   ("台指期夜盤漲跌", "night", "夜盤反映前一晚國際盤；回測看它對加權今天開盤／收盤的影響", "pct"),
    "sox_ret1":    ("前一晚費半", "night", "B74 研究唯一有效的國際關係（對隔天）", "pct"),
    "basis_z":     ("期現價差（跟近 60 天比）", "b", "期貨比現貨貴（正價差）通常代表期貨買方積極；跟自己近 60 天比較", "z"),
    "basis_d5":    ("期現價差 5 天變化", "b", "價差變大＝期貨相對轉強", "pct"),
    "fut_chg1":    ("外資台指期 1 天增減", "a", "外資期貨淨多單增加＝偏多", "lots"),
    "opt_chg1":    ("外資選擇權 1 天增減", "a", "外資買買權／賣賣權（偏多部位）增加", "k"),
    "opt_z":       ("外資選擇權部位（跟近 60 天比）", "b", "外資選擇權偏多部位相對水位", "z"),
    "retail":      ("散戶小台多空比", "b", "散戶（小台扣掉法人）淨多比例；常被當反向指標", "ratio"),
    "retail_chg1": ("散戶小台 1 天變化", "a", "散戶一天內加碼做多／做空", "ratio"),
    "f_net":       ("外資現貨買賣超", "a", "外資今天買超／賣超（億）", "yi"),
    "margin_chg5": ("融資 5 天增減", "b", "融資增加＝散戶加碼", "pct"),
}
HORIZONS = {"next": "隔天", "w2": "1～2 週", "m3": "1～3 個月"}
# 市場一般的解讀方向（回測沒通過的指標用這個標偏多偏空，只是描述；通過的才用研究的 polarity）
NATURAL = {"night_ret": 1, "sox_ret1": 1, "basis_z": 1, "basis_d5": 1, "fut_chg1": 1, "opt_chg1": 1, "opt_z": 1,
           "retail": -1, "retail_chg1": -1, "f_net": 1, "margin_chg5": -1}


def _z_prev(s: pd.Series, n: int = 60, minp: int = 40) -> pd.Series:
    """跟「前 n 天（不含當天）」比的 z 分數"""
    m = s.shift(1).rolling(n, min_periods=minp).mean()
    sd = s.shift(1).rolling(n, min_periods=minp).std()
    return (s - m) / sd


def build(tw: pd.DataFrame, fut_daily: Optional[pd.DataFrame] = None, chips: Optional[pd.DataFrame] = None,
          fchips: Optional[pd.DataFrame] = None, sox: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """tw：加權日 K（date,o,h,l,c）；fut_daily：futdata.load_fut_daily 格式；chips：mkt_chips；fchips：fut_chips；sox：費半日 K"""
    df = tw[["date", "o", "h", "l", "c"]].copy().reset_index(drop=True)
    df["date"] = df["date"].astype(str)
    c, o = df["c"].astype(float), df["o"].astype(float)
    df["r1"] = c / c.shift(1) - 1
    df["gap"] = o / c.shift(1) - 1
    df["r1_next"] = df["r1"].shift(-1)
    df["fwdo5"] = c.shift(-5) / o.shift(-1) - 1
    df["fwdo20"] = c.shift(-20) / o.shift(-1) - 1
    if fut_daily is not None and not fut_daily.empty:
        fd = fut_daily.copy()
        fd["date"] = fd["date"].astype(str)
        n = fd[(fd.sess == "night") & fd.ref_close.notna() & (fd.ref_close > 0)]
        df = df.merge(pd.DataFrame({"date": n.date, "night_ret": (n.c / n.ref_close - 1).values}), on="date", how="left")
        d = fd[fd.sess == "day"][["date", "c"]].rename(columns={"c": "tx_c"})
        df = df.merge(d, on="date", how="left")
        df["basis"] = df["tx_c"] / df["c"] - 1
        df["basis_z"] = _z_prev(df["basis"])
        df["basis_d5"] = df["basis"] - df["basis"].shift(5)
        df["night_ret_next"] = df["night_ret"].shift(-1)
    if chips is not None and not chips.empty:
        ch = chips.copy()
        ch["date"] = ch["date"].astype(str)
        df = df.merge(ch[[k for k in ("date", "f_net", "fut_f_oi", "margin_amt") if k in ch]], on="date", how="left")
        if "fut_f_oi" in df:
            df["fut_chg1"] = df["fut_f_oi"] - df["fut_f_oi"].shift(1)
        if "margin_amt" in df:
            df["margin_chg5"] = df["margin_amt"] / df["margin_amt"].shift(5) - 1
    if fchips is not None and not fchips.empty:
        fc = fchips.copy()
        fc["date"] = fc["date"].astype(str)
        df = df.merge(fc[[k for k in ("date", "retail_ratio", "opt_f_bull") if k in fc]], on="date", how="left")
        if "retail_ratio" in df:
            df["retail"] = df["retail_ratio"]
            df["retail_chg1"] = df["retail_ratio"] - df["retail_ratio"].shift(1)
        if "opt_f_bull" in df:
            df["opt_chg1"] = df["opt_f_bull"] - df["opt_f_bull"].shift(1)
            df["opt_z"] = _z_prev(df["opt_f_bull"])
    if sox is not None and not sox.empty:
        from .features import align_prev
        s = sox.sort_values("date").copy()
        s["date"] = s["date"].astype(str)
        s["ret1"] = s["c"].pct_change()
        df["sox_ret1"] = align_prev(df["date"], s, "ret1")
    return df


def state_of(key: str, value, res: dict) -> Optional[int]:
    """研究結果 res（stats.futures.factors[key]）→ 現在狀態 +1 偏多／−1 偏空／0 中性；沒資料 None。
    回測通過 → 用研究的 polarity；沒通過 → 用市場一般解讀 NATURAL（只是描述，不算方向）"""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    pol = (res.get("polarity") or 1) if res.get("pass") else NATURAL.get(key, 1)
    if res.get("kind") == "reg":
        a, b = res.get("alpha") or 0.0, res.get("beta")
        if b is None:
            return None
        exp = a + b * float(value)
        return 0 if abs(exp) < 0.001 else (1 if exp > 0 else -1)
    ed = res.get("edges")
    if not ed or None in ed:
        return 0 if value == 0 else (1 if value > 0 else -1) * pol
    raw = 1 if value > ed[1] else -1 if value <= ed[0] else 0
    return raw * pol


def direction(states: list) -> dict:
    """[(key, state, pass)] → 只用 pass 的指標加總；沒有 pass → None（不判斷方向）"""
    used = [(k, s) for k, s, p in states if p and s is not None]
    if not used:
        return {"score": None, "label": "沒有回測有效的指標，不判斷方向", "used": []}
    sc = sum(s for _, s in used)
    lab = "偏多" if sc > 0 else "偏空" if sc < 0 else "中性"
    return {"score": sc, "label": lab, "used": [k for k, _ in used]}


def margin_block(chips: pd.DataFrame, today: Optional[str] = None) -> dict:
    """融資餘額增減（PLAN §6.3）：餘額、今天／5 天／20 天增減、連增／連減、近 60 天每天增減"""
    if chips is None or chips.empty or "margin_amt" not in chips:
        return {"ok": False, "note": "融資資料暫缺"}
    m = chips[["date", "margin_amt"]].dropna().copy()
    if len(m) < 2:
        return {"ok": False, "note": "融資資料暫缺"}
    m["date"] = m["date"].astype(str)
    v = m["margin_amt"].astype(float).values
    d = np.diff(v)
    run = 0
    for x in d[::-1]:
        if x > 0 and run >= 0:
            run += 1
        elif x < 0 and run <= 0:
            run -= 1
        else:
            break
    f = lambda x: None if x is None or not math.isfinite(x) else round(float(x), 2)
    chg = lambda k: f(v[-1] - v[-1 - k]) if len(v) > k else None
    pct = lambda k: f((v[-1] / v[-1 - k] - 1) * 100) if len(v) > k and v[-1 - k] else None
    hist = [{"date": m["date"].iloc[i + 1], "chg": f(d[i]), "amt": f(v[i + 1])} for i in range(max(0, len(d) - 60), len(d))]
    out = {"ok": True, "date": m["date"].iloc[-1], "amt": f(v[-1]), "chg1": chg(1), "pct1": pct(1), "chg5": chg(5), "pct5": pct(5),
           "chg20": chg(20), "pct20": pct(20), "streak": int(run), "hist": hist}
    if today and m["date"].iloc[-1] < today:
        out["pending"] = "今天的融資晚上 21:30 後公布"
    return out
