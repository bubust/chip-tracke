"""
quality.py — ⭐ 品質分（PLAN-B73）：研究（research/b73/run_quality.py）跟網站掃描用同一份程式。

- stock_metrics(df)：單一股票每天的數字（只用當天以前的資料）。量要先換成「張」（網站呼叫端用 deep_verdict.lots_volume）
- day_flags(tab, taiex_ok, sector_of)：某一天的橫斷面 → 每檔 9 個條件 F1～F9
  F4／F9 用「股票池當天的分位數值」當門檻（不是排名）→ 不在股票池的股票（例：千張大戶的冷門股）也能比，沒有平手問題
- 品質分＝研究挑出的條件（score_keys）符合幾個；研究結果 research/b73/quality_research.json
"""
from __future__ import annotations

import json
import math
import os
from typing import Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH_PATH = os.path.join(HERE, "research", "b73", "quality_research.json")

FLAGS = {
    "F1": "大盤在 60 日線上",
    "F2": "格局多頭（站上 MA20 和 MA100）",
    "F3": "月線上揚（斜率 ≥ 0.4%）",
    "F4": "60 日漲幅在前 30%",
    "F5": "52 週位置 ≥ 0.6",
    "F6": "所屬產業 20 日強度前 1/3",
    "F7": "量 ≥ 前 20 日均量 1.5 倍",
    "F8": "不追高（收盤 ≤ 月線 +10%）",
    "F9": "成交金額 ≥ 股票池中位數",
}
MSLOPE_MIN = 0.4
RS_Q = 0.70
POS52_MIN = 0.6
VOLR_MIN = 1.5
EXT_MAX = 1.10
SECTOR_MIN_MEMBERS = 3
POOL_MIN_PRICE, POOL_MIN_VOL20, POOL_MIN_BARS = 10.0, 500.0, 120
COLS = ["close", "ret60", "ret20", "turn20", "bull", "mslope", "pos52", "volr", "ext", "vol20", "bars", "gap60", "pool"]


def stock_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """df：date／open／high／low／close／volume（張），停牌日已去掉、依日期排序 → 每天一列（index 跟 df 一樣）"""
    c = pd.to_numeric(df["close"], errors="coerce").astype(float)
    o = pd.to_numeric(df["open"], errors="coerce").astype(float)
    h = pd.to_numeric(df["high"], errors="coerce").astype(float)
    lo = pd.to_numeric(df["low"], errors="coerce").astype(float)
    v = pd.to_numeric(df["volume"], errors="coerce").astype(float)
    ma20 = c.rolling(20).mean()
    ma100 = c.rolling(100).mean()
    with np.errstate(invalid="ignore", divide="ignore"):
        out = pd.DataFrame(index=df.index)
        out["close"] = c
        out["ret60"] = c / c.shift(60) - 1
        out["ret20"] = c / c.shift(20) - 1
        out["turn20"] = (c * v).rolling(20).mean()
        out["bull"] = (c > ma20) & (c > ma100)
        out["mslope"] = (ma20 / ma20.shift(1) - 1) * 100
        hi = h.rolling(252, min_periods=120).max()
        lw = lo.rolling(252, min_periods=120).min()
        rng = hi - lw
        out["pos52"] = ((c - lw) / rng).where(rng > 0)
        out["volr"] = (v / v.shift(1).rolling(20).mean()).replace([np.inf, -np.inf], np.nan)
        out["ext"] = c / ma20
        out["vol20"] = v.rolling(20).mean()
        out["bars"] = np.arange(1, len(c) + 1)
        pc = c.shift(1)
        jump = ((c / pc - 1).abs() > 0.105) | ((o / pc - 1).abs() > 0.105)
        out["gap60"] = jump.astype(float).rolling(60, min_periods=1).max().fillna(0) > 0
        out["pool"] = (c >= POOL_MIN_PRICE) & (out["vol20"] >= POOL_MIN_VOL20) & (out["bars"] >= POOL_MIN_BARS) & ~out["gap60"]
    return out


def sector_strong(tab: pd.DataFrame, sector_of: dict) -> set:
    """股票池裡、所屬產業 20 日等權報酬排前 1/3 的產業（產業至少 3 檔才排；同分照產業名稱，固定順序）"""
    p = tab[tab["pool"].astype(bool)]
    sec = pd.Series({sid: sector_of.get(sid) for sid in p.index}, dtype=object)
    r = p["ret20"]
    d = pd.DataFrame({"sec": sec, "r": r}).dropna()
    if d.empty:
        return set()
    g = d.groupby("sec")["r"].agg(["mean", "count"])
    g = g[g["count"] >= SECTOR_MIN_MEMBERS]
    if g.empty:
        return set()
    g = g.reset_index().sort_values(["mean", "sec"], ascending=[False, True])
    n = math.ceil(len(g) / 3)
    return set(g["sec"].head(n))


def day_flags(tab: pd.DataFrame, taiex_ok: Optional[bool], sector_of: dict) -> pd.DataFrame:
    """tab：某一天、index＝股票代號、欄位＝stock_metrics 的那一列 → 每檔 F1～F9（bool）"""
    p = tab[tab["pool"].astype(bool)]
    q_rs = p["ret60"].dropna().quantile(RS_Q) if p["ret60"].notna().sum() >= 20 else np.nan
    med_turn = p["turn20"].dropna().median() if p["turn20"].notna().sum() >= 20 else np.nan
    strong = sector_strong(tab, sector_of)
    f = pd.DataFrame(index=tab.index)
    with np.errstate(invalid="ignore"):
        f["F1"] = bool(taiex_ok)
        f["F2"] = tab["bull"].fillna(False).astype(bool)
        f["F3"] = (tab["mslope"] >= MSLOPE_MIN).fillna(False)
        f["F4"] = (tab["ret60"] >= q_rs).fillna(False) if pd.notna(q_rs) else False
        f["F5"] = (tab["pos52"] >= POS52_MIN).fillna(False)
        f["F6"] = [sector_of.get(s) in strong for s in tab.index]
        f["F7"] = (tab["volr"] >= VOLR_MIN).fillna(False)
        f["F8"] = (tab["ext"] <= EXT_MAX).fillna(False)
        f["F9"] = (tab["turn20"] >= med_turn).fillna(False) if pd.notna(med_turn) else False
    return f.astype(bool)


def taiex_above_ma60(tx: Optional[pd.Series], day: str) -> Optional[bool]:
    """加權指數（YYYYMMDD → 收盤，依日期排序）在 day 那天是否站上 60 日線；資料不夠回 None"""
    if tx is None or len(tx) == 0:
        return None
    s = tx[tx.index.astype(str) <= day].astype(float)
    if len(s) < 60:
        return None
    return bool(s.iloc[-1] > s.iloc[-60:].mean())


# ── 研究結果 ─────────────────────────────────────────────────────────────────
def research() -> dict:
    try:
        with open(RESEARCH_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def score_keys() -> list:
    return list((research().get("score") or {}).get("keys") or [])


# ── 網站：掃描結束幫做多策略的每一列加 q＝{score, flags, date} ─────────────────────
def load_sector_map() -> dict:
    import sqlite3
    try:
        from sector.db import SECTOR_DB_PATH
        c = sqlite3.connect(str(SECTOR_DB_PATH), timeout=10)
        rows = c.execute("SELECT stock_id, sector_id FROM stock_sector_map ORDER BY effective_date").fetchall()
        c.close()
        return {str(a): b for a, b in rows}            # 同一檔多筆 → 最新的蓋掉舊的
    except Exception:
        return {}


def live_table(day: Optional[str] = None, rows_iter=None, bars: int = 300) -> tuple:
    """逐檔讀 price_daily（一個 SQL、依股票排序、一次只留一檔）→ 每檔最後一天的 stock_metrics 小表；回傳 (表, 日期)。
    只收最後一根＝最新交易日的股票（停牌、下市的不進橫斷面）"""
    import itertools
    from deep_verdict import lots_volume
    if rows_iter is None:
        import sqlite3
        from datetime import datetime, timedelta
        from price_cache import DB_PATH
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        last = day or conn.execute("SELECT MAX(date) FROM price_daily").fetchone()[0]
        since = (datetime.strptime(str(last), "%Y%m%d") - timedelta(days=int(bars * 1.6))).strftime("%Y%m%d")
        rows_iter = conn.execute("SELECT stock_id, date, open, high, low, close, volume FROM price_daily "
                                 "WHERE date >= ? AND date <= ? AND length(stock_id) = 4 AND substr(stock_id, 1, 1) BETWEEN '1' AND '9' "
                                 "ORDER BY stock_id, date", (since, str(last)))
    else:
        conn, last = None, day
    out = {}
    try:
        for sid, grp in itertools.groupby(rows_iter, key=lambda r: str(r[0])):
            if not (len(sid) == 4 and sid.isdigit() and sid[0] != "0"):
                continue
            g = pd.DataFrame(list(grp)[-bars:], columns=["stock_id", "date", "open", "high", "low", "close", "volume"])
            g = g[pd.to_numeric(g["close"], errors="coerce") > 0].reset_index(drop=True)
            if g.empty or (last and str(g["date"].iloc[-1]) != str(last)):
                continue
            g["volume"] = lots_volume(pd.to_numeric(g["volume"], errors="coerce").astype(float))
            m = stock_metrics(g)
            out[sid] = m.iloc[-1]
    finally:
        if conn is not None:
            conn.close()
    tab = pd.DataFrame(out).T if out else pd.DataFrame(columns=COLS)
    return tab, (str(last) if last else None)


def annotate(all_results: dict, long_keys: set, tab: Optional[pd.DataFrame] = None, day: Optional[str] = None,
             taiex_ok: Optional[bool] = None, sector_of: Optional[dict] = None) -> dict:
    """幫 long_keys 這些策略的每一列加 q；回傳摘要 {date, stocks, flagged}"""
    if tab is None:
        tab, day = live_table(day)
    if tab.empty:
        return {"date": day, "stocks": 0, "flagged": 0}
    for k in ("bull", "gap60", "pool"):
        tab[k] = tab[k].astype(bool)
    for k in [c for c in COLS if c not in ("bull", "gap60", "pool")]:
        tab[k] = pd.to_numeric(tab[k], errors="coerce")
    if taiex_ok is None:
        try:
            from best_strategy import taiex_series
            taiex_ok = taiex_above_ma60(taiex_series(), day)
        except Exception:
            taiex_ok = None
    flags = day_flags(tab, taiex_ok, sector_of if sector_of is not None else load_sector_map())
    keys = score_keys() or list(FLAGS)
    n = 0
    for strat, rows in all_results.items():
        if strat not in long_keys:
            continue
        for r in rows or []:
            sid = str(r.get("stock_id", ""))
            if sid not in flags.index:
                continue
            fl = [k for k in FLAGS if bool(flags.at[sid, k])]
            r["q"] = {"score": sum(1 for k in keys if k in fl), "max": len(keys), "flags": fl, "date": day}
            n += 1
    return {"date": day, "stocks": int(len(tab)), "flagged": n, "taiex_ok": taiex_ok, "keys": keys}
