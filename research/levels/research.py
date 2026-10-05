"""
關鍵價位研究：用 1,931 檔台股兩年日 K，walk-forward 比較各種壓力／支撐／停損／目標價算法。
- 每檔在 t = 250, 260, ... 取樣，只用 t 以前（含）的資料算價位（波段點要等右邊 k 根確認）
- 壓力：之後 H 天內第一次碰到（高 ≥ R−0.5%），接下來 6 根收盤都沒站上 R+1% ＝「擋住」
- 支撐：第一次碰到（低 ≤ S+0.5%），接下來 6 根收盤都沒跌破 S−1% ＝「撐住」
- 基準：同一方法的距離分布洗牌後配給別的樣本（同距離的隨機價位），差值＝真正的預測力
- 停損：收盤跌破 X 出場；被洗＝出場後 20 天內收盤回到進場價；有救＝出場後 20 天內再跌 ≥5%
- 目標：H 天內最高價碰到 T 的比例；先碰停損算失敗
"""
import math, sys, json
import numpy as np, pandas as pd
from multiprocessing import Pool

H = 40          # 觀察期（交易日）
STEP = 10
LOOK = 250
START = 120     # 從第 120 根開始取樣（前面不足 250 根就用現有的）
AFTER = 20


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def pivots(a, k, kind):
    n = len(a); out = np.zeros(n, bool)
    for i in range(k, n - k):
        L, R = a[i - k:i], a[i + 1:i + k + 1]
        if kind == 'h' and a[i] > L.max() and a[i] >= R.max(): out[i] = True
        if kind == 'l' and a[i] < L.min() and a[i] <= R.min(): out[i] = True
    return out


def cluster(xs, ws, tol_fn):
    order = np.argsort(xs); zs = []
    for j in order:
        x, w = xs[j], ws[j]
        if zs and x - zs[-1]['high'] <= tol_fn(zs[-1]['high']):
            z = zs[-1]; z['high'] = x; z['n'] += 1; z['w'] += w
        else:
            zs.append({'low': x, 'high': x, 'n': 1, 'w': w})
    return zs


def round_above(p, mult=1.0):
    step = 10 ** math.floor(math.log10(p)) / 2 * mult
    return math.floor(p / step + 1e-9) * step + step


def round_below(p, mult=1.0):
    step = 10 ** math.floor(math.log10(p)) / 2 * mult
    r = math.floor(p / step - 1e-9) * step
    return r if r > 0 else None


def hvn(h, l, v, t, p, look=LOOK):
    """量價分布：近一年每根 K 的量平均攤到它的高低區間（1% 一格），回傳局部高峰（≥ 平均量）的價位"""
    s = max(0, t - look + 1)
    hs, ls, vs = h[s:t + 1], l[s:t + 1], v[s:t + 1]
    lo, hi = ls.min(), hs.max()
    if lo <= 0 or hi <= lo: return []
    nb = int(math.log(hi / lo) / math.log(1.01)) + 1
    edges = lo * 1.01 ** np.arange(nb + 1)
    prof = np.zeros(nb)
    a = np.clip((np.log(ls / lo) / math.log(1.01)).astype(int), 0, nb - 1)
    b = np.clip((np.log(hs / lo) / math.log(1.01)).astype(int), 0, nb - 1)
    for i in range(len(vs)):
        prof[a[i]:b[i] + 1] += vs[i] / (b[i] - a[i] + 1)
    sm = np.convolve(prof, np.ones(3) / 3, 'same')
    m = sm.mean()
    peaks = [i for i in range(1, nb - 1) if sm[i] >= sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] >= m]
    return [(edges[i] + edges[i + 1]) / 2 for i in peaks]


def res_out(h, c, t, R, a=None, l=None):
    seg = h[t + 1:t + H + 1]; hit = np.nonzero(seg >= R * 0.995)[0]
    if not len(hit): return 0, None, None
    tau = t + 1 + hit[0]
    react = int(c[tau:tau + 6].max() < R * 1.01)
    intr = None
    if a is not None:
        cc = c[tau:tau + 16]; ll = l[tau:tau + 16]
        up_ = np.nonzero(cc > R + a)[0]; dn_ = np.nonzero(ll < R - a)[0]
        intr = int(len(dn_) > 0 and (not len(up_) or dn_[0] < up_[0]))
    return 1, react, intr


def sup_out(l, c, t, S, a=None, h=None):
    seg = l[t + 1:t + H + 1]; hit = np.nonzero(seg <= S * 1.005)[0]
    if not len(hit): return 0, None, None
    tau = t + 1 + hit[0]
    react = int(c[tau:tau + 6].min() > S * 0.99)
    intr = None
    if a is not None:
        cc = c[tau:tau + 16]; hh = h[tau:tau + 16]
        dn_ = np.nonzero(cc < S - a)[0]; up_ = np.nonzero(hh > S + a)[0]
        intr = int(len(up_) > 0 and (not len(dn_) or up_[0] < dn_[0]))
    return 1, react, intr


def stop_out(c, t, X):
    p = c[t]; seg = c[t + 1:t + H + 1]; br = np.nonzero(seg < X)[0]
    if not len(br): return {'s': 0}
    tau = t + 1 + br[0]; aft = c[tau + 1:tau + 1 + AFTER]
    return {'s': 1, 'whip': int(aft.max() >= p), 'save': int(aft.min() <= c[tau] * 0.95), 'loss': c[tau] / p - 1}


def tgt_out(h, c, t, T, X):
    """H 天內最高碰到 T、且之前沒有收盤跌破 X"""
    seg_h = h[t + 1:t + H + 1]; hit = np.nonzero(seg_h >= T)[0]
    if X is not None:
        br = np.nonzero(c[t + 1:t + H + 1] < X)[0]
        if len(br) and (not len(hit) or br[0] < hit[0]): return 0
    return int(len(hit) > 0)


def tgt_stall(h, c, t, T):
    """碰到 T 之後 10 根收盤都沒超過 T+3%（目標價附近就是頭）；沒碰到回 None"""
    hit = np.nonzero(h[t + 1:t + H + 1] >= T)[0]
    if not len(hit): return None
    tau = t + 1 + hit[0]
    return int(c[tau:tau + 11].max() < T * 1.03)


def levels_at(o, h, l, c, v, A, ma, ph5, pl5, ph3, pl3, ph10, pl10, t):
    """t 當下（只用 t 以前）各方法的價位"""
    p = c[t]; a = A[t]; s = max(0, t - LOOK + 1)
    out = {}

    def first(*xs):
        return next((x for x in xs if x is not None), None)
    # ---- 壓力 ----
    # R0 現行：k=5 波段高點、合併 2%、現價 +0.5% 以上
    ih = [i for i in range(s, t - 5 + 1) if ph5[i] and h[i] > p * 1.005]
    z0 = cluster(np.array([h[i] for i in ih]), np.ones(len(ih)), lambda x: x * 0.02) if ih else []
    out['R0_1'] = z0[0]['low'] if z0 else None
    out['R0_2'] = z0[1]['low'] if len(z0) > 1 else None
    # R1 波段高＋低（支撐變壓力），k=5，ATR 容差，現價 +0.25ATR 以上，帶量的點加權
    vavg = pd.Series(v[s:t + 1]).rolling(20, min_periods=5).mean().shift(1).values
    pts, ws = [], []
    for i in range(s, t - 5 + 1):
        vv = vavg[i - s] if i - s < len(vavg) else np.nan
        w = 1 + (1 if (vv and not np.isnan(vv) and v[i] >= 1.5 * vv) else 0)
        if ph5[i]: pts.append(h[i]); ws.append(w)
        if pl5[i]: pts.append(l[i]); ws.append(w)
    pts, ws = np.array(pts), np.array(ws, float)
    tol = lambda x: max(0.5 * a, x * 0.01)
    up = pts > p + 0.25 * a if len(pts) else np.array([], bool)
    z1 = cluster(pts[up], ws[up], tol) if up.any() else []
    out['R1_1'] = z1[0]['low'] if z1 else None
    out['R1_2'] = z1[1]['low'] if len(z1) > 1 else None
    # R1s：同 R1 但只留強度 ≥ 2（碰兩次以上或帶量）的區
    z1s = [z for z in z1 if z['w'] >= 2]
    out['R1s_1'] = z1s[0]['low'] if z1s else None
    out['R1s_2'] = z1s[1]['low'] if len(z1s) > 1 else None
    # R1c：R1 區的中間價（不是下緣）
    out['R1c_1'] = (z1[0]['low'] + z1[0]['high']) / 2 if z1 else None
    # R2 量價高峰
    nodes = hvn(h, l, v, t, p)
    ab = [x for x in nodes if x > p * 1.005]
    out['R2_1'] = ab[0] if ab else None
    out['R2_2'] = ab[1] if len(ab) > 1 else None
    # R3 近 60 / 120 日最高
    for w_ in (60, 120):
        mx = h[max(0, t - w_ + 1):t + 1].max()
        out[f'R3_{w_}'] = mx if mx > p * 1.005 else None
    # R4 整數關卡
    out['R4_1'] = round_above(p)
    # R5 均線在上方
    for k in (60, 120, 240):
        m = ma[k][t]
        out[f'R5_{k}'] = m if (not np.isnan(m) and m > p * 1.005) else None
    # R6 匯集：R1 區附近有量價高峰／整數／均線各 +1，挑分數 ≥ 2 最近的
    def score(z):
        lo_, hi_ = z['low'] - tol(z['low']), z['high'] + tol(z['high'])
        sc = z['w']
        sc += any(lo_ <= x <= hi_ for x in nodes)
        sc += any(lo_ <= x <= hi_ for x in (round_above(z['low'] * 0.98), round_below(z['high'] * 1.02) or 0))
        sc += any((not np.isnan(ma[k][t])) and lo_ <= ma[k][t] <= hi_ for k in (60, 120, 240))
        return sc
    z6 = [z for z in z1 if score(z) >= 3]
    out['R6_1'] = z6[0]['low'] if z6 else None
    out['R6_2'] = z6[1]['low'] if len(z6) > 1 else None
    # R7：R1s 的區＋上方的 120／240 日均線也當壓力候選（合併後由近到遠）
    cand = [z['low'] for z in z1s]
    for k in (120, 240):
        m = ma[k][t]
        if not np.isnan(m) and m > p + 0.25 * a: cand.append(m)
    cand = sorted(cand)
    c7 = []
    for x in cand:
        if not c7 or x - c7[-1] > tol(c7[-1]): c7.append(x)
    out['R7_1'] = c7[0] if c7 else None
    out['R7_2'] = c7[1] if len(c7) > 1 else None
    # R8：k=10 大波段高低點
    pts10, ws10 = [], []
    for i in range(s, t - 10 + 1):
        if ph10[i]: pts10.append(h[i]); ws10.append(1.0)
        if pl10[i]: pts10.append(l[i]); ws10.append(1.0)
    pts10, ws10 = np.array(pts10), np.array(ws10)
    up10 = pts10 > p + 0.25 * a if len(pts10) else np.array([], bool)
    z8 = cluster(pts10[up10], ws10[up10], tol) if up10.any() else []
    out['R8_1'] = z8[0]['low'] if z8 else None
    out['R8_2'] = z8[1]['low'] if len(z8) > 1 else None
    # R9：只用波段高點（不含支撐變壓力）、ATR 容差
    ih5 = [i for i in range(s, t - 5 + 1) if ph5[i] and h[i] > p + 0.25 * a]
    z9 = cluster(np.array([h[i] for i in ih5]), np.ones(len(ih5)), tol) if ih5 else []
    out['R9_1'] = z9[0]['low'] if z9 else None
    out['R9_2'] = z9[1]['low'] if len(z9) > 1 else None
    # ---- 支撐 ----
    # S0 現行：最近一個 k=3 波段低點（在現價下方）
    il3 = [i for i in range(s, t - 3 + 1) if pl3[i] and l[i] < p]
    out['S0_swing'] = l[il3[-1]] if il3 else None
    # S0v 爆量 K 棒低點（近 60 根、≥ 2 倍 20 日均量）
    v20 = pd.Series(v[:t + 1]).rolling(20).mean().shift(1).values
    sv = None
    for i in range(t, max(20, t - 60) - 1, -1):
        if v20[i] > 0 and v[i] >= 2 * v20[i] and l[i] < p:
            sv = l[i]; break
    out['S0_vol'] = sv
    # S1 波段高低點群（壓力變支撐），現價 −0.25ATR 以下，最近一區的上緣
    dn = pts < p - 0.25 * a if len(pts) else np.array([], bool)
    zs = cluster(pts[dn], ws[dn], tol) if dn.any() else []
    out['S1_1'] = zs[-1]['high'] if zs else None
    out['S1_2'] = zs[-2]['high'] if len(zs) > 1 else None
    zss = [z for z in zs if z['w'] >= 2]
    out['S1s_1'] = zss[-1]['high'] if zss else None
    # S2 量價高峰在下方
    be = [x for x in nodes if x < p * 0.995]
    out['S2_1'] = be[-1] if be else None
    # S3 近 20 / 60 日最低
    for w_ in (20, 60):
        mn = l[max(0, t - w_ + 1):t + 1].min()
        out[f'S3_{w_}'] = mn if mn < p * 0.995 else None
    # S4 均線在下方
    for k in (20, 60):
        m = ma[k][t]
        out[f'S4_{k}'] = m if (not np.isnan(m) and m < p * 0.995) else None
    # S6 匯集
    z6s = [z for z in zs if score(z) >= 3]
    out['S6_1'] = z6s[-1]['high'] if z6s else None
    il5 = [i for i in range(s, t - 5 + 1) if pl5[i] and l[i] < p]
    out['S0k5'] = l[il5[-1]] if il5 else None
    il10 = [i for i in range(s, t - 10 + 1) if pl10[i] and l[i] < p]
    out['S0k10'] = l[il10[-1]] if il10 else None
    # 前低：最近波段低點之前、更低的那個
    out['S0_prev'] = None
    if il3:
        older = [i for i in il3[:-1] if l[i] < l[il3[-1]]]
        out['S0_prev'] = l[older[-1]] if older else None
    for w_ in (10, 40):
        mn = l[max(0, t - w_ + 1):t + 1].min()
        out[f'S3_{w_}'] = mn if mn < p * 0.995 else None
    # 波段低點（k=3）和 20 日低取較低的
    out['S7_min'] = min([x for x in (out['S0_swing'], out['S3_20']) if x is not None], default=None)
    # 最近 k=3 波段低點，但要離現價至少 1 ATR（太近的往下找下一個）
    far = [i for i in il3 if l[i] <= p - a]
    out['S8_swing1atr'] = l[far[-1]] if far else None
    # ---- 停損（收盤跌破）----
    st0 = first(out['S0_vol'], out['S0_swing'])
    out['X0_cur'] = st0
    sup = first(out['S6_1'], out['S1s_1'], out['S1_1'])
    out['X1_sup-0.5atr'] = sup - 0.5 * a if sup else None
    out['X1b_sup-1atr'] = sup - 1.0 * a if sup else None
    out['X1c_sup*0.99'] = sup * 0.99 if sup else None
    for m_ in (1.5, 2, 2.5, 3):
        out[f'X2_{m_}atr'] = p - m_ * a
    out['X3_10pct'] = p * 0.9
    # 支撐 −0.5ATR，但不超過 3ATR、不少於 1ATR
    if sup:
        x = sup - 0.5 * a
        out['X4_capped'] = min(max(x, p - 3 * a), p - 1 * a)
    else:
        out['X4_capped'] = p - 2 * a
    out['X5_swing-0.5atr'] = out['S0_swing'] - 0.5 * a if out['S0_swing'] else None
    out['X6_ma20'] = ma[20][t] * 0.99 if not np.isnan(ma[20][t]) and ma[20][t] < p else None
    for nm, base in (('X7_20low', out['S3_20']), ('X7b_k5', out['S0k5']), ('X7c_sw1atr', out['S8_swing1atr']), ('X7d_min', out['S7_min'])):
        out[nm] = base - 0.5 * a if base else None
    # 波段低點 −0.5ATR，距離夾在 1.5～3 ATR
    sw = out['S0_swing']
    out['X8_sw_clamp'] = min(max(sw - 0.5 * a, p - 3 * a), p - 1.5 * a) if sw else p - 2 * a
    out['X8b_sw_clamp25'] = min(max(sw - 0.5 * a, p - 3.5 * a), p - 2 * a) if sw else p - 2.5 * a
    m20 = out['S7_min']
    out['X9_min_clamp'] = min(max(m20 - 0.5 * a, p - 3.5 * a), p - 1.5 * a) if m20 else p - 2.5 * a
    # ---- 目標 ----
    out['T0_cur'] = first(out['R0_2'], out['R0_1'])
    out['T1_R1_1'] = out['R1_1']
    out['T1b_R1_1hi'] = z1[0]['high'] if z1 else None
    out['T2_R1_2'] = out['R1_2']
    out['T2b_R6_2'] = out['R6_2']
    # 等幅：最近 k=5 波段低 L0 → 之後波段高 H1 → 之後回檔低 L1（現價在 L1 之上）：L1 + (H1 − L0)
    hi5 = [i for i in range(s, t - 5 + 1) if ph5[i]]
    mm = None
    if hi5:
        i1 = hi5[-1]
        lo_before = [i for i in range(s, i1) if pl5[i]]
        if lo_before and i1 < t:
            L0 = l[lo_before[-1]]; H1 = h[i1]; L1 = l[i1 + 1:t + 1].min()
            leg = H1 - L0
            if leg > 0 and L1 > L0 and (H1 - L1) / leg <= 0.618 and p > L1:
                mm = (L1 + leg, L1 + 0.65 * leg)
    out['T3_mm'] = mm[0] if mm else None
    out['T3b_mm65'] = mm[1] if mm else None
    mm2 = None
    if hi5:
        i1 = hi5[-1]
        lo_before = [i for i in range(s, i1) if pl5[i]]
        if lo_before and i1 < t:
            L0 = l[lo_before[-1]]; H1 = h[i1]; L1 = l[i1 + 1:t + 1].min(); leg = H1 - L0
            if leg > 0 and L1 > L0 and (H1 - L1) / leg <= 0.618 and p > L1:
                mm2 = {f: L1 + f * leg for f in (0.5, 0.8)}
                mm2['ext1618'] = L0 + 1.618 * leg      # 費波南西 1.618 延伸
                mm2['h1'] = H1                          # 前高本身
    for f in ('0.5', '0.8'):
        out[f'T3_mm{f}'] = mm2[float(f)] if mm2 else None
    out['T3_ext1618'] = mm2['ext1618'] if mm2 else None
    out['T3_h1'] = mm2['h1'] if mm2 and mm2['h1'] > p * 1.005 else None
    risk = (p - out['X4_capped']) if out['X4_capped'] else None
    out['T4_2R'] = p + 2 * risk if risk and risk > 0 else None
    out['T5_3atr'] = p + 3 * a
    out['T8_combo'] = first(out['T3b_mm65'] if out['T3b_mm65'] and out['T3b_mm65'] > p * 1.01 else None,
                            out.get('R1s_2'), p + 3 * a)
    out['T8b_combo100'] = first(out['T3_mm'], out.get('R1s_2'), p + 3 * a)
    out['T5b_2atr'] = p + 2 * a
    out['T6_R7_2'] = out.get('R7_2')
    out['T6b_R7_1'] = out.get('R7_1')
    out['T6c_R9_2'] = out.get('R9_2')
    rk = p - out['X8_sw_clamp']
    out['T7_2R_sw'] = p + 2 * rk if rk > 0 else None
    out['T7b_1.5R_sw'] = p + 1.5 * rk if rk > 0 else None
    return out


KINDS = {'R': res_out, 'S': sup_out}
BASE = 'atr'
SPLIT = '20260101'
SUBS = ('all', 'up', 'train', 'test')
SUBF = {'all': lambda s: True, 'up': lambda s: s['up'],
        'train': lambda s: s['date'] < SPLIT, 'test': lambda s: s['date'] >= SPLIT}


def run_stock(args):
    sid, g = args
    o, h, l, c, v = (g[k].values.astype(float) for k in ('open', 'high', 'low', 'close', 'volume'))
    n = len(c)
    if n < START + H + AFTER + 10: return []
    A = atr(h, l, c)
    ma = {k: pd.Series(c).rolling(k).mean().values for k in (20, 60, 120, 240)}
    ph5, pl5 = pivots(h, 5, 'h'), pivots(l, 5, 'l')
    ph3, pl3 = pivots(h, 3, 'h'), pivots(l, 3, 'l')
    ph10, pl10 = pivots(h, 10, 'h'), pivots(l, 10, 'l')
    rows = []
    for t in range(START, n - H - AFTER - 2, STEP):
        if np.isnan(A[t]) or c[t] <= 0 or v[t - 20:t + 1].mean() < 300:   # 均量 < 300 張不看（成交量單位是張）
            continue
        lv = levels_at(o, h, l, c, v, A, ma, ph5, pl5, ph3, pl3, ph10, pl10, t)
        up = bool(c[t] > ma[20][t] > ma[60][t]) if not np.isnan(ma[60][t]) else False
        rows.append({'sid': sid, 't': t, 'p': c[t], 'atr': A[t], 'up': up, 'lv': lv, 'date': str(g['date'].iloc[t])})
    return rows


def evaluate(samples, series):
    rng = np.random.default_rng(7)
    res = {}
    keys = sorted({k for s in samples for k in s['lv']})
    for k in keys:
        kind = k[0]
        ok = (lambda s: s['lv'][k] > s['p']) if kind in 'RT' else (lambda s: s['lv'][k] < s['p'])
        idx = [i for i, s in enumerate(samples) if s['lv'].get(k) and ok(s)]
        if len(idx) < 300: continue
        d = np.array([samples[i]['lv'][k] / samples[i]['p'] - 1 for i in idx])
        da = np.array([(samples[i]['lv'][k] - samples[i]['p']) / samples[i]['atr'] for i in idx])
        kind = k[0]
        stats = {'n': len(idx), 'dist_med%': round(float(np.median(d)) * 100, 2), 'dist_atr': round(float(np.median(da)), 2)}
        for sub in SUBS:
            sel = [j for j, i in enumerate(idx) if SUBF[sub](samples[i])]
            if len(sel) < 200: continue
            # 基準：在這個子集合內洗牌（ATR 倍數距離），dp[j] 是樣本 idx[j] 配到的隨機距離（百分比）
            dp = np.zeros(len(idx))
            perm = rng.permutation(np.array([da[j] for j in sel]))
            for q, j in enumerate(sel):
                dp[j] = perm[q] * samples[idx[j]]['atr'] / samples[idx[j]]['p']
            if kind in 'RS':
                f = KINDS[kind]; t_, m_, tb, mb, it, ib = 0, 0, 0, 0, 0, 0
                for j in sel:
                    s = samples[idx[j]]; h, l, c = series[s['sid']]
                    arr, oth = (h, l) if kind == 'R' else (l, h)
                    x = f(arr, c, s['t'], s['lv'][k], s['atr'], oth); y = f(arr, c, s['t'], s['p'] * (1 + dp[j]), s['atr'], oth)
                    t_ += x[0]; m_ += (x[1] or 0); tb += y[0]; mb += (y[1] or 0); it += (x[2] or 0); ib += (y[2] or 0)
                stats[sub] = {'touch%': round(100 * t_ / len(sel), 1), 'react%': round(100 * m_ / max(t_, 1), 1),
                              'base_react%': round(100 * mb / max(tb, 1), 1),
                              'edge': round(100 * (m_ / max(t_, 1) - mb / max(tb, 1)), 1),
                              'intr%': round(100 * it / max(t_, 1), 1), 'base_intr%': round(100 * ib / max(tb, 1), 1),
                              'edge2': round(100 * (it / max(t_, 1) - ib / max(tb, 1)), 1)}
            elif kind == 'X':
                agg = {'s': 0, 'whip': 0, 'save': 0, 'loss': 0.0}; bw = {'s': 0, 'whip': 0, 'save': 0}
                for j in sel:
                    s = samples[idx[j]]; h, l, c = series[s['sid']]
                    if s['lv'][k] >= s['p']: continue
                    r = stop_out(c, s['t'], s['lv'][k]); rb = stop_out(c, s['t'], s['p'] * (1 + dp[j]))
                    agg['s'] += r['s']
                    if r['s']: agg['whip'] += r['whip']; agg['save'] += r['save']; agg['loss'] += r['loss']
                    bw['s'] += rb['s']
                    if rb['s']: bw['whip'] += rb['whip']; bw['save'] += rb['save']
                ns = max(agg['s'], 1)
                stats[sub] = {'stopped%': round(100 * agg['s'] / len(sel), 1), 'whip%': round(100 * agg['whip'] / ns, 1),
                              'save%': round(100 * agg['save'] / ns, 1), 'avg_loss%': round(100 * agg['loss'] / ns, 2),
                              'base_whip%': round(100 * bw['whip'] / max(bw['s'], 1), 1)}
            elif kind == 'T':
                hit = hit_x = hb = st = stn = sb = sbn = 0
                for j in sel:
                    s = samples[idx[j]]; h, l, c = series[s['sid']]
                    if s['lv'][k] <= s['p']: continue
                    hit += tgt_out(h, c, s['t'], s['lv'][k], None)
                    hit_x += tgt_out(h, c, s['t'], s['lv'][k], s['lv'].get('X8_sw_clamp'))
                    hb += tgt_out(h, c, s['t'], s['p'] * (1 + dp[j]), None)
                    z = tgt_stall(h, c, s['t'], s['lv'][k])
                    if z is not None: st += z; stn += 1
                    z = tgt_stall(h, c, s['t'], s['p'] * (1 + dp[j]))
                    if z is not None: sb += z; sbn += 1
                stats[sub] = {'hit%': round(100 * hit / len(sel), 1), 'base_hit%': round(100 * hb / len(sel), 1),
                              'hit_before_stop%': round(100 * hit_x / len(sel), 1),
                              'stall%': round(100 * st / max(stn, 1), 1), 'base_stall%': round(100 * sb / max(sbn, 1), 1)}
        res[k] = stats
    return res


if __name__ == '__main__':
    d = pd.read_csv('pd.csv.gz', dtype={'stock_id': str, 'date': str})
    d = d[(d.close > 0) & (d.high > 0) & (d.low > 0)].sort_values(['stock_id', 'date'])
    groups = [(sid, g.reset_index(drop=True)) for sid, g in d.groupby('stock_id')]
    if len(sys.argv) > 1 and int(sys.argv[1]) > 0: groups = groups[:int(sys.argv[1])]
    series = {sid: (g.high.values.astype(float), g.low.values.astype(float), g.close.values.astype(float)) for sid, g in groups}
    with Pool(8) as pool:
        parts = pool.map(run_stock, groups, chunksize=8)
    samples = [r for p in parts for r in p]
    print('samples', len(samples), 'stocks', len({s['sid'] for s in samples}), 'uptrend', sum(s['up'] for s in samples))
    import pickle; pickle.dump(samples, open('samples.pkl', 'wb'))
    if len(sys.argv) > 2 and sys.argv[2] == 'save-only': sys.exit(0)
    res = evaluate(samples, series)
    json.dump(res, open('research_result.json', 'w'), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(k, json.dumps(v, ensure_ascii=False))
