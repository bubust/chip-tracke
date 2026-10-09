"""
course2.py — 講義策略（PLAN-COURSE）：每個策略都是「整段算」的函式 sig_xxx(o, h, l, c, v, ...) → (訊號 bool 陣列, 資訊 dict)，
研究（research/course，5 年回測）跟正式站掃描（screen_xxx，只看最後一天）用同一份，不會兩邊不一樣。

波段高低點（講義：a／A 點做多、d／D 點放空）：
- 第 j 根是波段高點＝h[j] 比前 k 根都高、不低於後 k 根；要到第 j+k 根收盤才「確認」，每天只用已確認的點（不偷看未來）。
- 已確認的點依時間排成高低交錯的序列；連續兩個同類點只留比較極端的那個；同一根同時是高點和低點時先放高點。
- k＝3 → a／d 點（短波段）；k＝8 → A／D 點（大波段）。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

HIGH, LOW = 1, -1


# ── 工具 ─────────────────────────────────────────────────────────────────────
def _arr(x):
    return np.asarray(x, dtype=float)


def _prev(a, fill=np.nan):
    out = np.empty_like(a, dtype=float)
    out[0] = fill
    out[1:] = a[:-1]
    return out


def mean_prev(v, n=20):
    """前 n 天（不含今天）平均；不滿 n 天＝NaN"""
    return pd.Series(v).rolling(n).mean().shift(1).to_numpy()


def roll_max(a, n):
    return pd.Series(a).rolling(n, min_periods=1).max().to_numpy()


def roll_min(a, n):
    return pd.Series(a).rolling(n, min_periods=1).min().to_numpy()


def tick_size(p: float) -> float:
    if p < 10:
        return 0.01
    if p < 50:
        return 0.05
    if p < 100:
        return 0.1
    if p < 500:
        return 0.5
    if p < 1000:
        return 1.0
    return 5.0


def limit_up_price(prev_close: float) -> float:
    """漲停價＝前收 × 1.1，依計算後價格所在區間的升降單位往下取（同 scanner._limit_up_price）"""
    raw = prev_close * 1.10
    t = tick_size(raw)
    return round(math.floor(raw / t + 1e-9) * t, 6)


def limit_up_arr(pc: np.ndarray) -> np.ndarray:
    out = np.full(len(pc), np.nan)
    for i, p in enumerate(pc):
        if np.isfinite(p) and p > 0:
            out[i] = limit_up_price(float(p))
    return out


def is_limit_up_arr(c, pc):
    lim = limit_up_arr(pc)
    tk = np.array([tick_size(x) if np.isfinite(x) else 0.0 for x in lim])
    with np.errstate(invalid="ignore"):
        return np.isfinite(lim) & (c >= lim - tk * 0.1), lim


# ── 波段高低點 ───────────────────────────────────────────────────────────────
def pivot_flags(h, l, k):
    """第 j 根是不是波段高點／低點（要第 j+k 根才知道；陣列只標在 j）"""
    h, l = _arr(h), _arr(l)
    n = len(h)
    ph = np.zeros(n, bool)
    pl = np.zeros(n, bool)
    if n < 2 * k + 1:
        return ph, pl
    from numpy.lib.stride_tricks import sliding_window_view as sw
    H, L = sw(h, 2 * k + 1), sw(l, 2 * k + 1)
    mh, ml = h[k:n - k], l[k:n - k]
    with np.errstate(invalid="ignore"):
        ph[k:n - k] = (mh > H[:, :k].max(1)) & (mh >= H[:, k + 1:].max(1))
        pl[k:n - k] = (ml < L[:, :k].min(1)) & (ml <= L[:, k + 1:].min(1))
    return ph, pl


def swing_seq(h, l, k, depth=8):
    """每天（含當天收盤）為止「已確認」的高低交錯波段點，最近 depth 個（第 0 欄＝最近一個）：
    typ (n, depth) int8（1＝高、-1＝低、0＝沒有）、val (n, depth) 價格、idx (n, depth) 第幾根"""
    h, l = _arr(h), _arr(l)
    n = len(h)
    ph, pl = pivot_flags(h, l, k)
    ev = [(j, 0, HIGH, h[j]) for j in np.nonzero(ph)[0]] + [(j, 1, LOW, l[j]) for j in np.nonzero(pl)[0]]
    ev.sort()
    seq, days, snaps = [], [], []
    for j, _, t, v in ev:
        if seq and seq[-1][0] == t:
            if (t == HIGH and v > seq[-1][1]) or (t == LOW and v < seq[-1][1]):
                seq[-1] = (t, v, j)
            else:
                continue
        else:
            seq.append((t, v, j))
        conf = j + k
        snap = seq[-depth:][::-1]
        if days and days[-1] == conf:
            snaps[-1] = snap
        else:
            days.append(conf)
            snaps.append(snap)
    typ = np.zeros((n, depth), np.int8)
    val = np.full((n, depth), np.nan)
    idx = np.full((n, depth), -1, np.int64)
    if snaps:
        St = np.zeros((len(snaps), depth), np.int8)
        Sv = np.full((len(snaps), depth), np.nan)
        Si = np.full((len(snaps), depth), -1, np.int64)
        for r, snap in enumerate(snaps):
            for m, (t, v, j) in enumerate(snap):
                St[r, m], Sv[r, m], Si[r, m] = t, v, j
        pos = np.searchsorted(np.array(days), np.arange(n), side="right") - 1
        ok = pos >= 0
        typ[ok], val[ok], idx[ok] = St[pos[ok]], Sv[pos[ok]], Si[pos[ok]]
    return typ, val, idx


def _state_prev(seq):
    """把「第 i 天收盤後的狀態」改成「第 i 天開盤前（＝前一天收盤後）」：訊號日用前一天的波段點判斷"""
    typ, val, idx = seq
    t2 = np.zeros_like(typ)
    v2 = np.full_like(val, np.nan)
    i2 = np.full_like(idx, -1)
    t2[1:], v2[1:], i2[1:] = typ[:-1], val[:-1], idx[:-1]
    return t2, v2, i2


# ── 1. 突破前高（a／A 點）＝ N 字突破新版 ─────────────────────────────────────
def sig_abreak(o, h, l, c, v, k=3, vmult=0.0, pull=0.05, rally=0.0):
    """最近已確認的波段低點 L 在波段高點 H 之後（H→L 回檔 ≥ pull），今天收盤第一次站上 H；
    rally＞0：H 之前那個波段低點到 H 漲幅 ≥ rally（N 字的第一隻腳）；vmult＞0：量 ≥ 前 20 日均量 × vmult"""
    o, h, l, c, v = map(_arr, (o, h, l, c, v))
    n = len(c)
    typ, val, idx = _state_prev(swing_seq(h, l, k, depth=3))
    pc = _prev(c)
    H, L, L0 = val[:, 1], val[:, 0], val[:, 2]
    with np.errstate(invalid="ignore", divide="ignore"):
        cand = (typ[:, 0] == LOW) & (typ[:, 1] == HIGH) & (c > H) & (pc <= H) & ((H - L) / H >= pull)
        if rally > 0:
            cand &= (typ[:, 2] == LOW) & (H / L0 - 1 >= rally)
        if vmult > 0:
            cand &= v >= vmult * mean_prev(v)
    sig = np.zeros(n, bool)
    for i in np.nonzero(cand)[0]:
        j = idx[i, 0]
        if j >= 0 and np.nanmax(c[j:i]) <= H[i]:          # 低點之後還沒收盤站上過 H（第一次突破）
            sig[i] = True
    return sig, {"H": H, "L": L, "stop": L}


# ── 6. 跌破前低（d／D 點）放空 ────────────────────────────────────────────────
def sig_dbreak(o, h, l, c, v, k=3, vmult=0.0, bounce=0.0):
    """最近已確認的波段高點 H 在波段低點 L 之後，今天收盤第一次跌破 L（講義 d／D 點放空）；
    bounce＞0：L→H 反彈 ≥ bounce；vmult＞0：量 ≥ 前 20 日均量 × vmult"""
    o, h, l, c, v = map(_arr, (o, h, l, c, v))
    n = len(c)
    typ, val, idx = _state_prev(swing_seq(h, l, k, depth=3))
    pc = _prev(c)
    H, L = val[:, 0], val[:, 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        cand = (typ[:, 0] == HIGH) & (typ[:, 1] == LOW) & (c < L) & (pc >= L) & (H / L - 1 >= bounce)
        if vmult > 0:
            cand &= v >= vmult * mean_prev(v)
    sig = np.zeros(n, bool)
    for i in np.nonzero(cand)[0]:
        j = idx[i, 0]
        if j >= 0 and np.nanmin(c[j:i]) >= L[i]:
            sig[i] = True
    return sig, {"H": H, "L": L, "stop": H}


# ── 3. 強勢股（高低點不重疊）──────────────────────────────────────────────────
def sig_strong(o, h, l, c, v, k=3, nlow=2, trigger="break"):
    """最近 nlow 個已確認波段低點，每一個都高於「它前面那個波段高點的前一個高點」（拉回不碰前高＝高低點不重疊）。
    trigger：'confirm'＝最新那個低點剛確認的那天；'break'＝狀態成立中，收盤第一次站上最近的波段高點"""
    o, h, l, c, v = map(_arr, (o, h, l, c, v))
    n = len(c)
    depth = 2 * nlow + 2
    typ, val, idx = swing_seq(h, l, k, depth=depth)
    # 狀態：第 0 個是低點；序列（新→舊）L0 H0 L1 H1 L2 H2 …；條件 L_m > H_{m+1}（m＝0..nlow-1）
    ok = typ[:, 0] == LOW
    for m in range(nlow):
        lo, hi_prev = 2 * m, 2 * m + 3
        with np.errstate(invalid="ignore"):
            ok &= (typ[:, lo] == LOW) & (typ[:, hi_prev] == HIGH) & (val[:, lo] > val[:, hi_prev])
    H0 = val[:, 1]
    if trigger == "confirm":
        newlow = np.zeros(n, bool)
        newlow[1:] = (idx[1:, 0] != idx[:-1, 0]) | (typ[1:, 0] != typ[:-1, 0])
        sig = ok & newlow
        return sig, {"H": H0, "L": val[:, 0], "stop": val[:, 0]}
    okp = np.r_[False, ok[:-1]]
    Hp = _prev(H0)
    pc = _prev(c)
    with np.errstate(invalid="ignore"):
        sig = okp & (c > Hp) & (pc <= Hp)
    Lp = _prev(val[:, 0])
    return sig, {"H": Hp, "L": Lp, "stop": Lp}


# ── 5. 黃金切割回檔 ──────────────────────────────────────────────────────────
FIB = (0.382, 0.5, 0.618)


def sig_fib(o, h, l, c, v, k_low=5, k_high=3, rally=0.2, zone=0.5, trig="red"):
    """一段上漲 L→H（H/L−1 ≥ rally，用 k_high 已確認的高點、它前面 k_low 已確認的低點），
    之後回檔最低碰到 H − zone×(H−L)、收盤沒跌破 0.618 線，出現止跌 K：
    trig 'red'＝紅 K（收 > 開）；'red_hi'＝紅 K 且收盤 > 前一天最高。每段上漲只取第一次"""
    o, h, l, c, v = map(_arr, (o, h, l, c, v))
    n = len(c)
    th, vh, ih = swing_seq(h, l, k_high, depth=2)
    tl, vl, il = swing_seq(h, l, k_low, depth=4)
    sig = np.zeros(n, bool)
    lv618 = np.full(n, np.nan)
    Hs = np.full(n, np.nan)
    Ls = np.full(n, np.nan)
    done = set()
    ph = _prev(h)
    red = c > o
    if trig == "red_hi":
        with np.errstate(invalid="ignore"):
            red &= c > ph
    for i in np.nonzero(red)[0]:
        s = i - 1                                         # 用前一天收盤後已確認的點
        if s < 1:
            continue
        # 最近的已確認高點（k_high 序列裡的第一個高點）
        m = 0 if th[s, 0] == HIGH else (1 if th[s, 1] == HIGH else -1)
        if m < 0:
            continue
        H, jh = vh[s, m], ih[s, m]
        # H 之前的已確認低點（k_low 序列，idx < jh 的最近一個低點）
        cand = [(vl[s, q], il[s, q]) for q in range(4) if tl[s, q] == LOW and 0 <= il[s, q] < jh]
        if not cand:
            continue
        L, jl = cand[0]
        if not (H / L - 1 >= rally) or (jh, jl) in done:
            continue
        seg_h, seg_l, seg_c = h[jh + 1:i + 1], l[jh + 1:i + 1], c[jh + 1:i + 1]
        if len(seg_h) == 0 or np.nanmax(seg_h) > H:       # 已經創新高 → 這段結束
            continue
        lvl = H - zone * (H - L)
        l618 = H - 0.618 * (H - L)
        if np.nanmin(seg_l) > lvl or np.nanmin(seg_c) < l618:
            continue
        sig[i] = True
        done.add((jh, jl))
        lv618[i], Hs[i], Ls[i] = l618, H, L
    return sig, {"H": Hs, "L": Ls, "stop": lv618}


# ── 2. 底部起漲（平地一聲雷的新子型）────────────────────────────────────────
def sig_bottom_rise(o, h, l, c, v, m1=2.5, width=0.15, shrink=0.6, m2=1.5, near_low=1.35, min_plat=5, max_plat=30):
    """講義：前一波由最低點拉起來爆量，之後量縮平台整理（越縮越好），再帶量突破。
    爆量日 B：量 ≥ 前 20 日均量 × m1、紅 K、漲 ≥ 4%、收盤 ≤ 250 日最低 × near_low；
    平台＝B 之後 min_plat～max_plat 根：最高收盤／最低收盤 − 1 ≤ width、最低價不破 B 的最低、平台均量 ≤ B 量 × shrink；
    今天收盤 > B～昨天的最高價、量 ≥ 平台均量 × m2（每個 B 只取第一次突破）"""
    o, h, l, c, v = map(_arr, (o, h, l, c, v))
    n = len(c)
    pc = _prev(c)
    v20 = mean_prev(v)
    low250 = roll_min(l, 250)
    with np.errstate(invalid="ignore", divide="ignore"):
        burst = (v >= m1 * v20) & (c > o) & (c / pc - 1 >= 0.04) & (c <= low250 * near_low)
    sig = np.zeros(n, bool)
    stop = np.full(n, np.nan)
    top = np.full(n, np.nan)
    for b in np.nonzero(burst)[0]:
        hi_c = lo_c = None
        for i in range(b + 1, min(n, b + max_plat + 2)):
            plat = slice(b + 1, i)
            cnt = i - (b + 1)
            if cnt >= min_plat:
                pv = v[plat].mean()
                ph = np.nanmax(h[b:i])
                if (hi_c / lo_c - 1 <= width) and pv <= shrink * v[b] and c[i] > ph and v[i] >= m2 * pv:
                    sig[i] = True
                    stop[i] = np.nanmin(l[b:i])
                    top[i] = ph
                    break
            if i >= n or cnt >= max_plat:
                break
            # 把第 i 根加進平台
            if l[i] < l[b]:
                break
            hi_c = c[i] if hi_c is None else max(hi_c, c[i])
            lo_c = c[i] if lo_c is None else min(lo_c, c[i])
            if hi_c / lo_c - 1 > width:
                break
    return sig, {"stop": stop, "top": top}


# ── 4. 連續跳空漲停後爆量打開 ─────────────────────────────────────────────────
def limit_streak(o, c):
    """到第 i 天（含）為止連續「跳空漲停」天數：開盤 ≥ 前收 × 1.05 且收在漲停價"""
    o, c = _arr(o), _arr(c)
    pc = _prev(c)
    lu, _ = is_limit_up_arr(c, pc)
    with np.errstate(invalid="ignore"):
        g = lu & (o >= pc * 1.05)
    out = np.zeros(len(c), np.int64)
    run = 0
    for i, x in enumerate(g):
        run = run + 1 if x else 0
        out[i] = run
    return out


def sig_limit_open(o, h, l, c, v, n=2, m=3.0, opened="close"):
    """前面連續 ≥ n 天跳空漲停，今天爆量（≥ 昨量 × m）打開：
    opened 'close'＝收盤沒鎖漲停；'touch'＝盤中有打開（最低 < 漲停價）也算，收盤又鎖回也算"""
    o, h, l, c, v = map(_arr, (o, h, l, c, v))
    st = limit_streak(o, c)
    pst = np.r_[0, st[:-1]]
    pc = _prev(c)
    lu, lim = is_limit_up_arr(c, pc)
    pv = _prev(v)
    with np.errstate(invalid="ignore"):
        if opened == "close":
            op = ~lu
        else:
            op = ~lu | (l < lim - 1e-9)
        sig = (pst >= n) & op & (pv > 0) & (v >= m * pv)
    return sig, {"streak": pst, "limit": lim, "stop": l, "vol_x": v / np.where(pv > 0, pv, np.nan)}


def revenue_available(ym: str, day: str) -> bool:
    """ym（YYYYMM）的月營收在 day（YYYYMMDD）能不能用：保守算次月 13 日（含）起（法規 10 日前公布，遇假日順延）"""
    y, m = int(ym[:4]), int(ym[4:6])
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return day >= f"{y2:04d}{m2:02d}13"


def latest_revenue_ym(day: str) -> str:
    """day 那天可以用的最新營收月份"""
    y, m = int(day[:4]), int(day[4:6])
    # 本月 13 日（含）以後 → 上個月；之前 → 上上個月
    back = 1 if day[6:8] >= "13" else 2
    m -= back
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}{m:02d}"


# ── 7. 出貨日（個股）─────────────────────────────────────────────────────────
DIST_DOWNVOL, DIST_STALL = 1, 2


def sig_distribution(o, h, l, c, v, hz_ratio=0.9, rally=0.2, look=60, dv_drop=0.015, dv_mult=1.5, st_mult=2.0):
    """高檔（收盤 ≥ 60 日最高收盤 × 0.9，而且 60 日最低到今天漲 ≥ 20%）出現：
    1＝下跌出量（跌 ≥ 1.5%、量 ≥ 前 20 日均量 × 1.5 而且比昨天大）
    2＝量大不漲（量 ≥ 前 20 日均量 × 2，漲跌在 ±1% 內，或收黑長上影：上影 ≥ 實體 2 倍且 ≥ 昨收 2%）
    回傳 type 陣列（0＝沒有）"""
    o, h, l, c, v = map(_arr, (o, h, l, c, v))
    pc, pv = _prev(c), _prev(v)
    v20 = mean_prev(v)
    with np.errstate(invalid="ignore", divide="ignore"):
        hz = (c >= hz_ratio * roll_max(c, look)) & (c / roll_min(l, look) - 1 >= rally)
        chg = c / pc - 1
        dv = hz & (chg <= -dv_drop) & (v >= dv_mult * v20) & (v > pv)
        upper = h - np.maximum(o, c)
        body = np.abs(c - o)
        stall = hz & (v >= st_mult * v20) & ((np.abs(chg) <= 0.01) | ((c < o) & (upper >= 2 * body) & (upper >= 0.02 * pc)))
    typ = np.zeros(len(c), np.int8)
    typ[stall] = DIST_STALL
    typ[dv] = DIST_DOWNVOL
    return typ


# ── 10. 大盤出貨日 ────────────────────────────────────────────────────────────
def market_dist_day(close, overheat, k=3, hot=0.5, within=5):
    """加權收盤（只有收盤 → 波段點用收盤算）第一次跌破最近已確認的波段低點（d 點），而且最近 within 天內過熱指數 > hot。
    overheat 跟 close 同長度（缺值 NaN）。回傳 (出貨日 bool, 跌破 d 點 bool, d 點價位)"""
    c = _arr(close)
    oh = _arr(overheat)
    typ, val, idx = _state_prev(swing_seq(c, c, k, depth=2))
    m = np.where(typ[:, 0] == LOW, 0, np.where(typ[:, 1] == LOW, 1, -1))
    d = np.where(m >= 0, val[np.arange(len(c)), np.maximum(m, 0)], np.nan)
    pc = _prev(c)
    with np.errstate(invalid="ignore"):
        brk = (c < d) & (pc >= d)
        hotr = pd.Series(oh > hot).rolling(within, min_periods=1).max().to_numpy() > 0
    return brk & hotr, brk, d


# ── 股票池（跟研究一樣）───────────────────────────────────────────────────────
def pool_ok(df, min_price=10.0, min_vol20=500.0, min_bars=120) -> bool:
    """收盤 ≥ 10、20 日均量 ≥ 500 張、≥ 120 根、最近 60 根沒有單日跳動 > 10.5%（除權息／減資）"""
    if df is None or len(df) < min_bars:
        return False
    c = df["close"].astype(float).to_numpy()
    o = df["open"].astype(float).to_numpy()
    v = df["volume"].astype(float).to_numpy()
    if not np.isfinite(c[-1]) or c[-1] < min_price or np.nanmean(v[-20:]) < min_vol20:
        return False
    pc = c[-61:-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        j = (np.abs(c[-60:] / pc - 1) > 0.105) | (np.abs(o[-60:] / pc - 1) > 0.105)
    return not bool(np.nanmax(j.astype(float), initial=0))


def ohlcv(df):
    return tuple(df[k].astype(float).to_numpy() for k in ("open", "high", "low", "close", "volume"))


# ── 正式站掃描（只看最後一天；參數＝research/course 挑出的那組，結果沒通過驗證的網頁照實標示）──
LIVE_PARAMS = {
    "S_STRONG": dict(k=5, nlow=2, trigger="break"),          # ST_k5_n2_break
    "S_FIB": dict(rally=0.3, zone=0.618, trig="red"),        # FB_r0.3_z0.618_red
    "S_DBREAK": dict(k=3, vmult=1.5),                        # DB_k3_v1.5（季線下）
    "S_LIMIT_OPEN": dict(n=2, m=3.0, opened="touch"),        # 盤中打開也算；業績前提另外標
}


def _row(sid, df, names, key, **extra):
    from scanner_course import _base
    return _base(sid, df, names, key, **extra)


def _r2(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if np.isfinite(x) else None


def screen_strong(prices, names=None, params=None):
    """強勢股（講義：高低點不重疊）：最近 2 個波段低點都高於前一個前高，今天收盤第一次站上最近的波段高點"""
    p = params or {}
    kw = LIVE_PARAMS["S_STRONG"]
    out = []
    for sid, df in prices.items():
        if float(df.iloc[-1]["close"]) < float(p.get("min_price", 10)) or not pool_ok(df):
            continue
        o, h, l, c, v = ohlcv(df)
        sig, info = sig_strong(o, h, l, c, v, **kw)
        if sig[-1]:
            out.append(_row(sid, df, names, "S_STRONG", prev_high=_r2(info["H"][-1]), stop=_r2(info["stop"][-1]),
                            risk_pct=_r2((c[-1] / info["stop"][-1] - 1) * 100, 1),
                            note="突破前高；停損＝最近波段低點。5 年回測沒勝過隨機（見說明）"))
    return out


def screen_fib(prices, names=None, params=None):
    """黃金切割回檔：漲 ≥ 30% 的一段上漲後回檔碰到 0.618、收盤沒跌破，出現止跌紅 K"""
    p = params or {}
    kw = LIVE_PARAMS["S_FIB"]
    out = []
    for sid, df in prices.items():
        if float(df.iloc[-1]["close"]) < float(p.get("min_price", 10)) or not pool_ok(df):
            continue
        o, h, l, c, v = ohlcv(df)
        sig, info = sig_fib(o, h, l, c, v, **kw)
        if sig[-1]:
            H, L = info["H"][-1], info["L"][-1]
            out.append(_row(sid, df, names, "S_FIB", wave_low=_r2(L), wave_high=_r2(H),
                            fib382=_r2(H - 0.382 * (H - L)), fib500=_r2(H - 0.5 * (H - L)), stop=_r2(info["stop"][-1]),
                            note="回檔 0.618 止跌；停損＝收盤跌破 0.618。5 年回測沒勝過隨機（見說明）"))
    return out


def screen_dbreak(prices, names=None, params=None):
    """跌破前低（講義 d 點放空）：反彈高點出來後，收盤第一次跌破前一個波段低點、量 ≥ 1.5 倍、在季線下"""
    p = params or {}
    kw = LIVE_PARAMS["S_DBREAK"]
    out = []
    for sid, df in prices.items():
        if float(df.iloc[-1]["close"]) < float(p.get("min_price", 10)) or not pool_ok(df):
            continue
        o, h, l, c, v = ohlcv(df)
        ma60 = np.nanmean(c[-60:])
        if not c[-1] < ma60:
            continue
        sig, info = sig_dbreak(o, h, l, c, v, **kw)
        if sig[-1]:
            out.append(_row(sid, df, names, "S_DBREAK", d_point=_r2(info["L"][-1]), stop=_r2(info["H"][-1]), ma60=_r2(ma60),
                            note="跌破前低放空；停損＝反彈高點。5 年回測放空不賺（多頭年），見說明"))
    return out


def screen_limit_open2(prices, names=None, params=None):
    """連續 ≥ 2 天跳空漲停後，今天爆量（≥ 昨量 3 倍）打開（盤中打開又鎖回也算）；附最近已公布月營收年增（業績前提）"""
    p = params or {}
    kw = dict(LIVE_PARAMS["S_LIMIT_OPEN"])
    kw["n"] = int(p.get("min_limit_days", kw["n"]))
    kw["m"] = float(p.get("vol_mult", kw["m"]))
    out = []
    for sid, df in prices.items():
        if len(df) < 30 or float(df.iloc[-1]["close"]) < float(p.get("min_price", 10)):
            continue
        o, h, l, c, v = ohlcv(df)
        sig, info = sig_limit_open(o, h, l, c, v, **kw)
        if sig[-1]:
            out.append({"sid": sid, "df": df, "streak": int(info["streak"][-1]), "vol_x": _r2(info["vol_x"][-1], 1),
                        "stop": _r2(l[-1]), "relocked": bool(c[-1] >= info["limit"][-1] - 1e-9)})
    if not out:
        return []
    try:
        from course_live import revenue_lookup
        day = str(out[0]["df"]["date"].iloc[-1]).replace("-", "")[:8]
        rev = revenue_lookup([x["sid"] for x in out], day)
    except Exception:
        rev = {}
    res = []
    for x in out:
        rv = rev.get(x["sid"]) or {}
        yoy = rv.get("yoy")
        good = yoy is not None and yoy >= 20
        res.append(_row(x["sid"], x["df"], names, "S_LIMIT_OPEN", limit_days=x["streak"], vol_x=x["vol_x"], stop=x["stop"],
                        rev_yoy=_r2(yoy, 0), rev_ym=rv.get("ym"), fund_ok=good,
                        note=("✅ 月營收年增 ≥ 20%（業績前提成立）" if good else "⚠ 業績前提不成立或查無月營收，先確認真利多")
                        + ("；收盤又鎖回漲停" if x["relocked"] else "") + "。停損＝今天最低，收盤跌破就出（最多 10 天）"))
    return res


COURSE2_STRATEGIES = {
    "S_STRONG": "💪 強勢股（高低點不重疊、突破前高）",
    "S_FIB": "✨ 黃金切割回檔（0.618 止跌）",
    "S_DBREAK": "🔽 跌破前低放空（d 點）",
}
COURSE2_FNS = {"S_STRONG": screen_strong, "S_FIB": screen_fib, "S_DBREAK": screen_dbreak}
COURSE2_SHORT = {"S_DBREAK"}
_MP2 = {"key": "min_price", "label": "最低股價", "type": "number", "default": 10, "min": 1, "max": 500, "step": 1}
COURSE2_PARAMS = {"S_STRONG": [_MP2], "S_FIB": [_MP2], "S_DBREAK": [_MP2]}
