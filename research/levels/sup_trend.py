import pickle, numpy as np, pandas as pd
from research import sup_out, pivots
samples = pickle.load(open('samples.pkl', 'rb'))
d = pd.read_csv('pd.csv.gz', dtype={'stock_id': str, 'date': str})
d = d[(d.close > 0) & (d.high > 0) & (d.low > 0)].sort_values(['stock_id', 'date'])
S = {}
for sid, g in d.groupby('stock_id'):
    c = g.close.values.astype(float); l = g.low.values.astype(float)
    S[sid] = {'c': c, 'h': g.high.values.astype(float), 'l': l, 'pl3': pivots(l, 3, 'l'),
              **{f'ma{k}': pd.Series(c).rolling(k).mean().values for k in (5, 10, 20, 60)}}
rng = np.random.default_rng(5)
def trend(s): x = S[s['sid']]; t = s['t']; return x['c'][t] > x['ma5'][t] > x['ma10'][t]
def far(s): sup = s['lv'].get('S0k5'); return sup is not None and s['p'] - sup > 3.5 * s['atr']
def lvl(name, s):
    x = S[s['sid']]; t = s['t']; p = s['p']
    if name.startswith('MA'): v = x['ma' + name[2:]][t]; return v if v < p else None
    if name == 'k3swing':
        il = [i for i in range(max(0, t - 249), t - 2) if x['pl3'][i] and x['l'][i] < p]; return x['l'][il[-1]] if il else None
    if name.startswith('low'):
        w = int(name[3:]); m = x['l'][t - w + 1:t + 1].min(); return m if m < p * 0.995 else None
    if name == 'k5': return s['lv'].get('S0k5')
for sub, f in (('非趨勢＋前低>3.5ATR遠', lambda s: (not trend(s)) and far(s)), ('趨勢＋前低>3.5ATR遠', lambda s: trend(s) and far(s))):
    pool = [s for s in samples if f(s)]
    print('==', sub, len(pool))
    for name in ('MA5', 'MA10', 'MA20', 'MA60', 'low10', 'low20', 'k5'):
        rows = [(s, lvl(name, s)) for s in pool]; rows = [(s, v) for s, v in rows if v is not None]
        da = np.array([(v - s['p']) / s['atr'] for s, v in rows])
        Tt = M = 0
        for s, v in rows:
            x = S[s['sid']]; a_ = sup_out(x['l'], x['c'], s['t'], v); Tt += a_[0]; M += a_[1] or 0
        bases = []
        for k in range(20):                       # 20 組隨機基準取平均，降低基準本身的雜訊
            pa = rng.permutation(da); TB = MB = 0
            for j, (s, v) in enumerate(rows):
                x = S[s['sid']]; b_ = sup_out(x['l'], x['c'], s['t'], s['p'] + pa[j] * s['atr']); TB += b_[0]; MB += b_[1] or 0
            bases.append(MB / max(TB, 1))
        rate = M / max(Tt, 1); se = np.sqrt(rate * (1 - rate) / max(Tt, 1))
        print(f"   {name:8s} n={len(rows):5d} 距離 {np.median(da):5.2f}ATR 碰到 {100*Tt/len(rows):4.0f}% 撐住 {100*rate:4.1f}% vs 隨機 {100*np.mean(bases):4.1f}%（20 組 ±{100*np.std(bases):.1f}）edge {100*(rate-np.mean(bases)):+.1f}（自身抽樣誤差 ±{100*se:.1f}）", flush=True)
