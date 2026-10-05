"""目標價 × 停損價 組合模擬：t 收盤進場；之後最高碰到目標 → 目標價出場；收盤跌破停損 → 當天收盤出場；
都沒有 → 第 H 天收盤出場。扣 0.585% 來回成本。比較平均報酬、勝率、平均虧損。"""
import pickle, numpy as np, pandas as pd, json, sys
H = 40
COST = 0.00585
samples = pickle.load(open('samples.pkl', 'rb'))
d = pd.read_csv('pd.csv.gz', dtype={'stock_id': str, 'date': str})
d = d[(d.close > 0) & (d.high > 0) & (d.low > 0)].sort_values(['stock_id', 'date'])
series = {sid: (g.high.values.astype(float), g.low.values.astype(float), g.close.values.astype(float)) for sid, g in d.groupby('stock_id')}


PRE = []
for s_ in samples:
    h_, l_, c_ = series[s_['sid']]; t_ = s_['t']
    cs = c_[t_ + 1:t_ + H + 1]; hs = h_[t_ + 1:t_ + H + 1]
    PRE.append((s_['p'], -np.minimum.accumulate(cs), np.maximum.accumulate(hs), cs, c_[t_ + H]))


def trade(i, T, X):
    p, ncmin, hmax, cs, last = PRE[i]
    js = int(np.searchsorted(ncmin, -X, side='right')) if X is not None else H   # 第一個 收盤 < X
    jt = int(np.searchsorted(hmax, T, side='left')) if T is not None else H      # 第一個 最高 >= T
    if js < H and js <= jt: return cs[js] / p - 1, 'stop'
    if jt < H: return T / p - 1, 'target'
    return last / p - 1, 'time'


def tgt(s, name):
    lv = s['lv']; p = s['p']; a = s['atr']
    f = lambda x: x if (x is not None and x > p * 1.005) else None
    if name == 'none': return None
    if name == 'T0_cur': return f(lv.get('T0_cur'))
    if name == 'mm>R9_2>3atr': return f(lv.get('T3_mm')) or f(lv.get('R9_2')) or p + 3 * a
    if name == 'mm>R0_2>3atr': return f(lv.get('T3_mm')) or f(lv.get('R0_2')) or p + 3 * a
    if name == 'mm65>R9_2>3atr': return f(lv.get('T3b_mm65')) or f(lv.get('R9_2')) or p + 3 * a
    if name == 'R9_2>3atr': return f(lv.get('R9_2')) or p + 3 * a
    if name == 'R0_2': return f(lv.get('R0_2'))
    if name == '3atr': return p + 3 * a
    if name == '4atr': return p + 4 * a
    if name == 'mm>4atr': return f(lv.get('T3_mm')) or p + 4 * a
    raise KeyError(name)


def stp(s, name):
    lv = s['lv']; p = s['p']; a = s['atr']
    g = lambda x: x if (x is not None and x < p) else None
    if name == 'none': return None
    if name == 'clamp(k5)':
        b = lv.get('S0k5')
        x = b - 0.5 * a if b else p - 2.5 * a
        return min(max(x, p - 3.5 * a), p - 1.5 * a)
    if name == 'clamp(20low)':
        b = lv.get('S3_20')
        x = b - 0.5 * a if b else p - 2.5 * a
        return min(max(x, p - 3.5 * a), p - 1.5 * a)
    return g(lv.get(name))


TG = ['none', 'T0_cur', 'R0_2', 'mm>R9_2>3atr', 'mm>R0_2>3atr', 'mm65>R9_2>3atr', 'R9_2>3atr', '3atr', '4atr', 'mm>4atr']
ST = ['none', 'X0_cur', 'X5_swing-0.5atr', 'X7b_k5', 'X7_20low', 'X7d_min', 'X8_sw_clamp', 'X9_min_clamp',
      'clamp(k5)', 'clamp(20low)', 'X2_2atr', 'X2_2.5atr', 'X3_10pct']
SUBS = {'all': lambda s: True, 'up': lambda s: s['up'], 'train': lambda s: s['date'] < '20260101', 'test': lambda s: s['date'] >= '20260101'}
out = {}
masks = {sub: np.array([fn(s) for s in samples]) for sub, fn in SUBS.items()}
for tn in TG:
    Ts = [tgt(s, tn) for s in samples]
    for sn in ST:
        Xs = [stp(s, sn) for s in samples]
        res = [trade(i, Ts[i], Xs[i]) for i in range(len(samples))]
        R = np.array([x[0] for x in res]) - COST; K = np.array([x[1] for x in res])
        row = {}
        for sub, m in masks.items():
            r, k = R[m], K[m]
            row[sub] = {'n': int(m.sum()), 'avg%': round(r.mean() * 100, 2), 'med%': round(float(np.median(r)) * 100, 2),
                        'win%': round((r > 0).mean() * 100, 1), 'stop%': round((k == 'stop').mean() * 100, 1),
                        'tgt%': round((k == 'target').mean() * 100, 1), 'p5%': round(float(np.percentile(r, 5)) * 100, 1)}
        out[f'{tn} | {sn}'] = row
        print(f'{tn:15s} {sn:16s} ' + ' | '.join(f"{sub}: {v['avg%']:+.2f} w{v['win%']} s{v['stop%']} t{v['tgt%']} p5 {v['p5%']}" for sub, v in row.items()), flush=True)
json.dump(out, open('combos_result.json', 'w'), ensure_ascii=False, indent=1)
