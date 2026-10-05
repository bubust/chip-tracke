"""注意：本檔的子集合（up/train/test）基準用「全部樣本」的距離洗牌，有偏差（見 PLAN-LEVELS.md 3.4）；只看 all 那一行。"""
"""支撐價定義比較（ATR 同距離基準）＋以它為錨的停損（−0.5ATR、夾 1.5～3.5ATR）"""
import pickle, numpy as np, pandas as pd
from research import sup_out, stop_out, pivots, H
samples = pickle.load(open('samples.pkl', 'rb'))
d = pd.read_csv('pd.csv.gz', dtype={'stock_id': str, 'date': str})
d = d[(d.close > 0) & (d.high > 0) & (d.low > 0)].sort_values(['stock_id', 'date'])
S = {sid: (g.high.values.astype(float), g.low.values.astype(float), g.close.values.astype(float)) for sid, g in d.groupby('stock_id')}
PL5 = {sid: pivots(v[1], 5, 'l') for sid, v in S.items()}
rng = np.random.default_rng(3)


def sup_def(name, s):
    h, l, c = S[s['sid']]; t = s['t']; p = s['p']
    if name == 'A_20low':
        m = l[t - 19:t + 1].min(); return m if m < p * 0.995 else None
    if name == 'B_20low_ex2>60':
        m = l[t - 21:t - 1].min()
        if m < p * 0.995: return m
        m = l[max(0, t - 61):t - 1].min(); return m if m < p * 0.995 else None
    if name == 'C_k5>60':
        il = [i for i in range(max(0, t - 249), t - 4) if PL5[s['sid']][i] and l[i] < p]
        if il: return l[il[-1]]
        m = l[max(0, t - 59):t + 1].min(); return m if m < p * 0.995 else None
    if name == 'D_k5_or_20low_nearer':      # 兩個取離現價近的
        a = sup_def('C_k5>60', s); b = sup_def('B_20low_ex2>60', s)
        xs = [x for x in (a, b) if x is not None]; return max(xs) if xs else None
    if name == 'E_k5_or_20low_lower':
        a = sup_def('C_k5>60', s); b = sup_def('B_20low_ex2>60', s)
        xs = [x for x in (a, b) if x is not None]; return min(xs) if xs else None


def stop_of(sup, p, a, clamp=True):
    if sup is None: return p - 2.5 * a
    x = sup - 0.5 * a
    return min(max(x, p - 3.5 * a), p - 1.5 * a) if clamp else x


COST = 0.00585
for name in ('A_20low', 'B_20low_ex2>60', 'C_k5>60', 'D_k5_or_20low_nearer', 'E_k5_or_20low_lower'):
    rows = []
    for s in samples:
        x = sup_def(name, s)
        if x is not None: rows.append((s, x))
    da = np.array([(x - s['p']) / s['atr'] for s, x in rows]); pa = rng.permutation(da)
    out = {}
    for sub, f in (('all', lambda s: True), ('up', lambda s: s['up']), ('train', lambda s: s['date'] < '20260101'), ('test', lambda s: s['date'] >= '20260101')):
        T = M = TB = MB = 0; far = 0; above = 0; n = 0; rets = []; whip = st = 0
        for j, (s, x) in enumerate(rows):
            if not f(s): continue
            h, l, c = S[s['sid']]; n += 1
            r = sup_out(l, c, s['t'], x); rb = sup_out(l, c, s['t'], s['p'] + pa[j] * s['atr'])
            T += r[0]; M += r[1] or 0; TB += rb[0]; MB += rb[1] or 0
            if s['p'] - x > 3.0 * s['atr']: far += 1
            X = stop_of(x, s['p'], s['atr'])
            if X > x: above += 1
            o = stop_out(c, s['t'], X)
            st += o['s']; whip += o.get('whip', 0)
            # 不設目標、40 天或停損出場
            p = s['p']; seg = c[s['t'] + 1:s['t'] + H + 1]; br = np.nonzero(seg < X)[0]
            rets.append((seg[br[0]] if len(br) else c[s['t'] + H]) / p - 1 - COST)
        out[sub] = f"edge {100 * (M / max(T, 1) - MB / max(TB, 1)):+.1f} touch {100 * T / n:.0f} | 支撐>3ATR遠 {100 * far / n:.0f}% 停損在支撐上方 {100 * above / n:.0f}% | 停損: 打到 {100 * st / n:.0f}% 洗 {100 * whip / max(st, 1):.0f}% 報酬 {100 * np.mean(rets):+.2f}"
    print(f"{name:22s} n={len(rows)} distA={np.median(da):.2f}")
    for k, v in out.items(): print('   ', k, v)
