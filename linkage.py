"""
linkage.py — 🔗 股票連動性（PLAN-LINK 第 4 節）

每天收盤後（18:00 掃描之後）算一次、存 cache.db 的 link_peers：
- 每檔（股票池內）跟全市場股票池 60 日日報酬相關係數前 10 名＋同產業前 5 名
- 股價比值＝A 收盤 ÷ B 收盤；平均比值＝60 日平均；偏差率＝今天比值 ÷ 平均比值 − 1（講義定義：正＝A 相對貴）
- 領先：corr(A[t−1], B[t]) − corr(B[t−1], A[t])（120 日），> 0.05 → A 領先 B
每天「先發動」：同產業今天漲幅 ≥ 5%、收盤創 20 日新高、量 ≥ 前 20 日均量 2 倍，而且同產業前 10 天沒人做到（研究同一個定義）；
跟進候選＝同產業、股票池、跟它 60 日相關 ≥ 0.5、今天漲幅 < 它一半（研究：research/link/follow_study.py）。
數值都用前一個交易日（含）為止的收盤算，盤中不更新。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
WIN_CORR, WIN_LEAD, WIN_RATIO = 60, 120, 60
MIN_PRICE, MIN_VOL20, MIN_BARS = 10.0, 500.0, 120


def _conn():
    from chip_tracker_v2 import DB_PATH
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _init(c):
    c.execute("CREATE TABLE IF NOT EXISTS link_peers (stock_id TEXT PRIMARY KEY, date TEXT, data TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS link_meta (k TEXT PRIMARY KEY, v TEXT)")


def load_panel(days: int = 260):
    """price_daily 最近 days 個交易日（4 碼普通股）→ close、volume 寬表（日期 × 股票）"""
    c = _conn()
    ds = [r[0] for r in c.execute("SELECT DISTINCT date FROM price_daily ORDER BY date DESC LIMIT ?", (days,)).fetchall()]
    if not ds:
        c.close()
        return None, None, {}
    df = pd.read_sql("SELECT date, stock_id, name, open, close, volume FROM price_daily WHERE date >= ?", c, params=(min(ds),))
    c.close()
    df = df[df.stock_id.str.fullmatch(r"[1-9]\d{3}")]
    names = df.drop_duplicates("stock_id", keep="last").set_index("stock_id")["name"].to_dict()
    close = df.pivot_table(index="date", columns="stock_id", values="close").sort_index()
    vol = df.pivot_table(index="date", columns="stock_id", values="volume").sort_index()
    opn = df.pivot_table(index="date", columns="stock_id", values="open").sort_index().reindex_like(close)
    vol.attrs["open"] = opn                     # 除權缺口檢查用（_pool）
    return close, vol, names


def sector_map() -> dict:
    """{stock_id: sector_id}（產業輪動的分類）"""
    try:
        from sector.db import db
        with db() as sc:
            return {r["stock_id"]: r["sector_id"] for r in sc.execute("SELECT sector_id, stock_id FROM stock_sector_map").fetchall()}
    except Exception as e:
        log.warning(f"[link] sector map: {e}")
        return {}


def gap_recent(close: pd.DataFrame, opn: pd.DataFrame | None, bars: int = 60) -> pd.Series:
    """最近 bars 根有沒有單日跳動 > 10.5%（台股漲跌幅 10% → 一定是除權息／減資／面額變更）；
    有的話不還原價的報酬、相關係數都被扭曲，不放進股票池（研究 engine.features 的 gap60 同一套）"""
    pc = close.shift(1)
    j = (close / pc - 1).abs() > 0.105
    if opn is not None:
        j |= (opn / pc - 1).abs() > 0.105
    return j.iloc[-bars:].any()


def _pool(close: pd.DataFrame, vol: pd.DataFrame) -> pd.Series:
    """股票池：收盤 ≥ 10、20 日均量 ≥ 500 張、≥ 120 根、最近 60 根沒有除權息／減資跳動"""
    last = close.ffill().iloc[-1]
    v20 = vol.iloc[-20:].mean()
    bars = close.notna().sum()
    gap = gap_recent(close, vol.attrs.get("open")).reindex(close.columns).fillna(False)
    return (last >= MIN_PRICE) & (v20 >= MIN_VOL20) & (bars >= MIN_BARS) & ~gap


def _corr_matrix(R: np.ndarray) -> np.ndarray:
    """欄＝股票；有缺值的欄用該欄平均補（停牌日），標準差 0 的欄相關＝NaN"""
    X = R - np.nanmean(R, axis=0)
    X = np.where(np.isnan(X), 0.0, X)
    sd = np.sqrt((X ** 2).sum(axis=0))
    sd[sd == 0] = np.nan
    Z = X / sd
    return Z.T @ Z


def compute_all(save: bool = True) -> dict:
    close, vol, names = load_panel(260)
    if close is None or len(close) < WIN_LEAD + 2:
        return {"error": "價格資料不夠"}
    pool = _pool(close, vol)
    ids = list(pool[pool].index)
    C = close[ids]
    R = (C / C.shift(1) - 1).to_numpy()
    day = str(close.index[-1])
    rc = R[-WIN_CORR:]
    cm = _corr_matrix(rc)
    # 領先：A[t−1] 對 B[t]
    rl = R[-WIN_LEAD:]
    a_prev, b_now = rl[:-1], rl[1:]
    Za = _std(a_prev); Zb = _std(b_now)
    lead = Za.T @ Zb                                     # lead[i, j]＝corr(i[t−1], j[t])
    lead_diff = lead - lead.T
    secs = sector_map()
    cl = C.iloc[-WIN_RATIO:].to_numpy()
    chg = (C.iloc[-1] / C.iloc[-2] - 1).to_numpy()
    out = {}
    for i, sid in enumerate(ids):
        row = np.nan_to_num(cm[i], nan=-9.0)
        row[i] = -9.0
        top = list(np.argsort(-row)[:10])
        sec = secs.get(sid)
        same = [j for j in np.argsort(-row) if secs.get(ids[j]) == sec and row[j] > -9][:5] if sec else []
        peers = []
        for j in dict.fromkeys(top + same):
            ratio = cl[:, i] / cl[:, j]
            mean = float(np.nanmean(ratio))
            peers.append({"id": ids[j], "name": names.get(ids[j], ""), "corr": round(float(cm[i, j]), 3),
                          "same_sector": bool(sec and secs.get(ids[j]) == sec),
                          "ratio": round(float(ratio[-1]), 4), "ratio_mean": round(mean, 4),
                          "dev": round(float(ratio[-1] / mean - 1), 4) if mean else None,
                          "lead": round(float(lead_diff[i, j]), 3), "chg": round(float(chg[j]), 4) if np.isfinite(chg[j]) else None})
        out[sid] = {"date": day, "sector": sec, "chg": round(float(chg[i]), 4) if np.isfinite(chg[i]) else None, "peers": peers}
    if save:
        c = _conn()
        _init(c)
        c.execute("DELETE FROM link_peers")
        c.executemany("INSERT INTO link_peers VALUES (?,?,?)", [(k, v["date"], json.dumps(v, ensure_ascii=False)) for k, v in out.items()])
        c.execute("INSERT OR REPLACE INTO link_meta VALUES ('updated', ?)", (json.dumps({"date": day, "at": datetime.now().isoformat(), "n": len(out)}),))
        c.commit()
        c.close()
    log.info(f"[link] {day} 連動股 {len(out)} 檔")
    return {"date": day, "n": len(out)}


def _std(A: np.ndarray) -> np.ndarray:
    X = A - np.nanmean(A, axis=0)
    X = np.where(np.isnan(X), 0.0, X)
    sd = np.sqrt((X ** 2).sum(axis=0))
    sd[sd == 0] = np.nan
    return X / sd


def peers_of(sid: str) -> dict | None:
    c = _conn()
    _init(c)
    r = c.execute("SELECT data FROM link_peers WHERE stock_id=?", (sid,)).fetchone()
    c.close()
    return json.loads(r["data"]) if r else None


def movers(close=None, vol=None, names=None) -> list:
    """今天各產業的「先發動」＋跟進候選（同產業、股票池、60 日相關 ≥ 0.5、今天漲幅 < 它一半）"""
    if close is None:
        close, vol, names = load_panel(130)
    if close is None or len(close) < 62:
        return []
    secs = sector_map()
    pool = _pool(close, vol)
    R = close / close.shift(1) - 1
    hh20 = close.shift(1).rolling(20).max()
    vr = vol / vol.shift(1).rolling(20).mean()
    mover = (R >= 0.05) & (close > hh20) & (vr >= 2)
    mover = mover & pool
    today = close.index[-1]
    out = []
    by_sec = {}
    for sid, sec in secs.items():
        if sid in close.columns:
            by_sec.setdefault(sec, []).append(sid)
    for sec, mem in by_sec.items():
        m_today = [s for s in mem if bool(mover.at[today, s])]
        if not m_today:
            continue
        prev10 = mover[mem].iloc[-11:-1].to_numpy().any()
        lead = max(m_today, key=lambda s: R.at[today, s])
        rr = R[mem].iloc[-WIN_CORR:]
        cs = rr.corrwith(rr[lead])
        cand = [s for s in mem if s != lead and bool(pool.get(s, False)) and cs.get(s, 0) >= 0.5
                and np.isfinite(R.at[today, s]) and R.at[today, s] < R.at[today, lead] / 2]
        cand.sort(key=lambda s: -cs[s])
        out.append({"sector": sec, "date": str(today), "first": not prev10,
                    "movers": [{"id": s, "name": names.get(s, ""), "chg": round(float(R.at[today, s]), 4),
                                "vr": round(float(vr.at[today, s]), 1)} for s in sorted(m_today, key=lambda s: -R.at[today, s])],
                    "leader": lead,
                    "candidates": [{"id": s, "name": names.get(s, ""), "corr": round(float(cs[s]), 3),
                                    "chg": round(float(R.at[today, s]), 4)} for s in cand[:8]]})
    out.sort(key=lambda x: (not x["first"], -x["movers"][0]["chg"]))
    return out
