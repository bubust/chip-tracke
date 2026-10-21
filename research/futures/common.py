"""B75 研究共用：資料讀取、月份 block bootstrap、BH（跟 research/wave/run.py 同一套寫法）"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from wave import engine as E, futdata as FD, features as F  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WDATA = os.path.join(ROOT, "research", "wave", "data")
OUT = os.path.join(HERE, "results")
STATS = os.path.join(ROOT, "wave", "stats.json")
N_BOOT = 2000
RNG = np.random.default_rng(20261021)


def r4(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 4)


def block_boot_events(months: np.ndarray, stat_fn, n=N_BOOT):
    """事件依月份分組，抽月份（放回）重算 stat_fn(選到的事件索引)。回傳 (估計, 下限, 上限, 雙尾 p)"""
    ug = np.unique(months)
    idx_by = {g: np.where(months == g)[0] for g in ug}
    est = stat_fn(np.arange(len(months)))
    vals = []
    for _ in range(n):
        pick = RNG.choice(ug, size=len(ug), replace=True)
        ii = np.concatenate([idx_by[g] for g in pick]) if len(pick) else np.array([], dtype=int)
        v = stat_fn(ii)
        if v is not None and np.isfinite(v):
            vals.append(v)
    if not vals or est is None or not np.isfinite(est):
        return est, None, None, None
    vals = np.array(vals)
    lo, hi = np.quantile(vals, [0.025, 0.975])
    p = 2 * min((vals <= 0).mean(), (vals >= 0).mean())
    return float(est), float(lo), float(hi), float(min(1.0, max(p, 1.0 / n)))


def bh(pvals: dict) -> dict:
    items = sorted([(k, p) for k, p in pvals.items() if p is not None], key=lambda x: x[1])
    m = len(items)
    q, prev = {}, 1.0
    for rank in range(m, 0, -1):
        k, p = items[rank - 1]
        prev = min(prev, p * m / rank)
        q[k] = prev
    return q


def load_twii_daily():
    tw = pd.read_csv(os.path.join(WDATA, "TWII.csv")).dropna(subset=["o", "h", "l", "c"])
    return tw[(tw.h >= tw.l) & (tw.c > 0)].reset_index(drop=True)


def load_intraday(sym: str, tf: int) -> list:
    """研究用分 K：加權用 Yahoo 60m（2 年）、台指期用期交所 5 分 K（30 天）→ futdata.agg_bars"""
    if sym == "TWII":
        df = pd.read_csv(os.path.join(DATA, "twii_60m.csv")) if tf == 60 else pd.read_csv(os.path.join(DATA, "twii_5m.csv"))
    else:
        df = pd.read_csv(os.path.join(DATA, "tx_5m.csv"))
    rows = [(int(r.ts), r.o, r.h, r.l, r.c, r.v) for r in df.itertuples()]
    return FD.agg_bars(rows, sym, tf)


def arrays(bars):
    o = np.array([b["open"] for b in bars], float)
    h = np.array([b["high"] for b in bars], float)
    l = np.array([b["low"] for b in bars], float)
    c = np.array([b["close"] for b in bars], float)
    t = np.array([b["time"] for b in bars], int)
    return o, h, l, c, t


def trading_day_of(sym: str, ts: int) -> str:
    """分 K → 所屬交易日（台指期夜盤屬於下一個交易日：用「這一盤開始那天」＋夜盤往後找下一個有日盤的日子，由呼叫端處理）；這裡回日曆日"""
    return FD.tw_dt(ts).strftime("%Y-%m-%d")
