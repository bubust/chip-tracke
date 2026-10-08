"""停損滾動修正研究 第 4 輪：結構低點＝k3 波段低（收盤確認）＋所有回檔低點（兩個波段高點之間的最低點）
進場：前低離現價 >3ATR 且強勢 → 20 日線−1ATR（現行）；否則離現價 ≥1ATR 的最近結構低點；沒有 → 現價−2.5ATR
上修：結構低點 i 已經 ≥3 根前、之後收盤沒跌破、之後最高價離它 ≥ r 倍 ATR、離現價 ≥1ATR → 停損上修到 l[i]（只上不下）"""
import sys, time, pickle
import numpy as np, pandas as pd

sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..'))   # repo 根目錄
from price_levels import atr_series, pivots, recent_high, STOP_MIN_ATR

H, STEP, K = 40, 10, 3
BUY, SELL = 0.001425, 0.004425
MAXS = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 9

d = pd.read_csv('pd.csv.gz', dtype={'stock_id': str, 'date': str})
d = d[(d.close > 0) & (d.high > 0) & (d.low > 0) & (d.volume > 0)]
d = d[d.stock_id.str.fullmatch(r'[1-9]\d{3}')].sort_values(['stock_id', 'date'])
dates_all = sorted(d.date.unique())
MID = dates_all[len(dates_all) // 2]


def struct_lows(h, l, c, j, look):
    """day j 收盤後看得到的結構低點 index（由新到舊、去重）"""
    out = set()
    for i in range(max(K, look), j - K + 1):                 # k3 波段低：左 3 根低點都比它高、右 3 根收盤沒跌破
        if l[i] < l[i - K:i].min() and c[i + 1:i + K + 1].min() >= l[i]:
            out.add(i)
    hs = [i for i in pivots(h[:j + 1], K, 'high') if i >= look]
    rh = recent_high(h[:j + 1], K)
    if rh is not None and rh >= look and rh not in hs:
        hs.append(rh)
    bounds = sorted(hs) + [j]
    for a, b in zip(bounds[:-1], bounds[1:]):               # 每兩個波段高點之間的回檔低點（最後一段到昨天，今天不算）
        if b - a >= 2:
            out.add(a + 1 + int(l[a + 1:b].argmin()))
    return sorted(out, reverse=True)


def prep(g):
    c = g.close.values.astype(float); h = g.high.values.astype(float); l = g.low.values.astype(float)
    v = g.volume.values.astype(float)
    S = {'c': c, 'h': h, 'l': l, 'atr': atr_series(h, l, c), 'date': g.date.values, 'lows': [None] * len(c),
         'ma': {k: pd.Series(c).rolling(k).mean().values for k in (5, 10, 20)}}
    return S, pd.Series(v).rolling(20).mean().values


def lows_at(S, j):
    if S['lows'][j] is None:
        S['lows'][j] = struct_lows(S['h'], S['l'], S['c'], j, max(0, j + 1 - 250))
    return S['lows'][j]


def a_at(S, j):
    x = S['atr'][j]
    return max(float(x) if np.isfinite(x) else 0.0, S['c'][j] * 0.005)


def trend_trail(S, j, sup):
    c = S['c']; p = c[j]; a = a_at(S, j)
    m5, m10, m20 = (S['ma'][k][j] for k in (5, 10, 20))
    if sup is not None and p - sup > 3 * a and p > m5 > m10:
        t = min(m20 - a, m10 - 0.5 * a, p - 1.5 * a)
        if t < m10:
            return t
    return None


def current_rule(S, j):
    c, l = S['c'], S['l']; p = c[j]; a = a_at(S, j)
    sup = next((l[i] for i in lows_at(S, j) if l[i] < p), None)
    t = trend_trail(S, j, sup)
    if t is not None:
        return t
    return p - 2.5 * a if sup is None else min(sup - 0.5 * a, p - STOP_MIN_ATR * a)


def entry_rule(S, j, m=1.0):
    c, l = S['c'], S['l']; p = c[j]; a = a_at(S, j)
    lows = lows_at(S, j)
    sup = next((l[i] for i in lows if l[i] < p), None)
    t = trend_trail(S, j, sup)
    if t is not None:
        return t
    lo = next((l[i] for i in lows if l[i] <= p - m * a), None)
    return p - 2.5 * a if lo is None else lo


def raise_rule(S, j, r, m=1.0):
    c, h, l = S['c'], S['h'], S['l']; p = c[j]; a = a_at(S, j)
    for i in lows_at(S, j):
        if i > j - K or l[i] > p - m * a:
            continue
        if c[i + 1:j + 1].min() >= l[i] and h[i:j + 1].max() - l[i] >= r * a:
            return l[i]
    return None


RULES = {'R0f 現行（進場算一次固定）': ('fixed', current_rule, None)}
for r in (1.5, 2.0, 2.5, 3.0):
    RULES[f'R8 進場結構＋平台上修 r{r}'] = ('roll', entry_rule, (lambda r: lambda S, j: raise_rule(S, j, r))(r))
RULES['R8x 進場結構、不上修'] = ('fixed', entry_rule, None)


def simulate(S, t, rule):
    kind, f0, f1 = rule
    c = S['c']; p = c[t]
    stop = f0(S, t); init = stop
    for j in range(t + 1, t + H + 1):
        if c[j] < stop:
            return c[j] / p * (1 - SELL) / (1 + BUY) - 1, True, j, init
        if kind == 'roll':
            new = f1(S, j)
            if new is not None and new > stop:
                stop = new
    return c[t + H] / p * (1 - SELL) / (1 + BUY) - 1, False, t + H, init


if __name__ == '__main__':
    rows, done = [], 0
    t0 = time.time()
    groups = list(d.groupby('stock_id'))
    for gi, (sid, g) in enumerate(groups):
        if len(g) < 180:
            continue
        if done >= MAXS:
            break
        done += 1
        S, v20 = prep(g)
        c = S['c']; n = len(c)
        for t in range(130, n - H - 1, STEP):
            if c[t] < 10 or not (v20[t] >= 500):
                continue
            p = c[t]; a = a_at(S, t)
            sup = next((S['l'][i] for i in lows_at(S, t) if S['l'][i] < p), None)
            trend = bool(p > S['ma'][20][t]); near = bool(sup is not None and p - sup < a)
            for name, rule in RULES.items():
                ret, hit, jx, init = simulate(S, t, rule)
                wash = bool(hit and c[jx + 1:jx + 21].max(initial=0) > p)
                rows.append((sid, S['date'][t], trend, near, name, ret, hit, wash, max((p - init) / p, 0.002), jx - t))
        if gi % 200 == 0:
            print(gi, len(groups), round(time.time() - t0), 's', flush=True)
    R = pd.DataFrame(rows, columns=['sid', 'date', 'trend', 'near', 'rule', 'ret', 'hit', 'wash', 'risk', 'days'])
    R.to_pickle('stop_rows4.pkl')

    def summ(x):
        return pd.Series({'n': len(x), 'mean%': x.ret.mean() * 100, 'median%': x.ret.median() * 100,
                          'p5%': x.ret.quantile(0.05) * 100, 'hit%': x.hit.mean() * 100, 'wash%': x.wash.mean() * 100,
                          'risk%': x.risk.median() * 100, 'R/筆': (x.ret / x.risk).mean(), 'days': x.days.mean()})
    for label, sub in (('全部', R), ('前半', R[R.date < MID]), ('後半', R[R.date >= MID]),
                       ('多頭(收>MA20)', R[R.trend]), ('支撐很近(<1ATR)', R[R.near])):
        print(f'\n=== {label} ===')
        print(sub.groupby('rule')[['ret', 'hit', 'wash', 'risk', 'days']].apply(summ).round(2).to_string())
