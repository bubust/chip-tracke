"""移動停損研究（PLAN-LEVELS.md 第 7、8 節）。RULES 清單可換成檔內任何規則名稱重跑。"""
"""移動停損研究：用戶規則「收盤跌破 5 日線減碼一半、跌破 10 日線全部出場、收盤站回 5 日線再買回」
跟其他出場方式比較。t 收盤滿倉進場，持有 H=40 天（期末收盤結算），每天收盤決策、當天收盤成交。
成本：買進 0.1425%、賣出 0.1425%＋證交稅 0.3%（依成交部位比例）。
樣本：research.py 的 39,537 個時間點（samples.pkl），另分「趨勢模式」＝收盤 > MA5 > MA10。"""
import pickle, json, sys
import numpy as np, pandas as pd

H = 40
BUY, SELL = 0.001425, 0.004425
samples = pickle.load(open('samples.pkl', 'rb'))
d = pd.read_csv('pd.csv.gz', dtype={'stock_id': str, 'date': str})
d = d[(d.close > 0) & (d.high > 0) & (d.low > 0)].sort_values(['stock_id', 'date'])
S = {}
for sid, g in d.groupby('stock_id'):
    c = g.close.values.astype(float)
    S[sid] = {'c': c, 'h': g.high.values.astype(float), 'l': g.low.values.astype(float),
              **{f'ma{k}': pd.Series(c).rolling(k).mean().values for k in (5, 10, 20)}}


def init_stop(s, x, t, p, a):
    sup = s['lv'].get('S0k5')
    if sup is None:
        m = x['l'][max(0, t - 59):t + 1].min()
        sup = m if m < p * 0.995 else None
    return p - 2.5 * a if sup is None else min(max(sup - 0.5 * a, p - 3.5 * a), p - 1.5 * a)


def run(s, rule):
    """回傳 (40 天報酬, 交易次數, 期間最大回撤, 平均持股比例)"""
    x = S[s['sid']]; c = x['c']; t = s['t']; p = s['p']; a = s['atr']
    pos, val, peak, mdd, trades, held = 1.0, 1.0 - BUY, 1.0, 0.0, 1, 0.0
    hi = p
    stop = None
    if rule == 'fixed':                    # 現行新規則：支撐 −0.5ATR 夾 1.5～3.5ATR（不買回）
        stop = init_stop(s, x, t, p, a)
    for j in range(t + 1, t + H + 1):
        val *= 1 + pos * (c[j] / c[j - 1] - 1)
        held += pos
        ma5, ma10, ma20 = x['ma5'][j], x['ma10'][j], x['ma20'][j]
        hi = max(hi, c[j])
        new = pos
        if rule == 'hold':
            pass
        elif rule == 'fixed':
            if pos > 0 and c[j] < stop: new = 0.0
        elif rule == 'ma10':                       # 跌破 10 日線出場、站回 5 日線買回
            if pos > 0 and c[j] < ma10: new = 0.0
            elif pos == 0 and c[j] > ma5: new = 1.0
        elif rule == 'ma10_nobuy':
            if pos > 0 and c[j] < ma10: new = 0.0
        elif rule == 'user':                       # 用戶規則
            if c[j] < ma10: new = 0.0
            elif c[j] < ma5: new = min(pos, 0.5)
            elif c[j] > ma5: new = 1.0 if pos < 1.0 else pos
        elif rule == 'user_nobuy':                 # 用戶規則但不買回
            if c[j] < ma10: new = 0.0
            elif c[j] < ma5: new = min(pos, 0.5)
        elif rule == 'user_ma20':                  # 5 日線減碼、20 日線出場、站回 5 日線買回
            if c[j] < ma20: new = 0.0
            elif c[j] < ma5: new = min(pos, 0.5)
            elif c[j] > ma5: new = 1.0
        elif rule == 'ma20':
            if pos > 0 and c[j] < ma20: new = 0.0
            elif pos == 0 and c[j] > ma5: new = 1.0
        elif rule.startswith('chand'):             # 追蹤：最高收盤 −kATR（不買回）
            k = float(rule[5:])
            if pos > 0 and c[j] < hi - k * a: new = 0.0
        elif rule.startswith('ratchet'):           # 只上不下：max(初始停損, 最高收盤 −kATR)
            k = float(rule[7:])
            if stop is None: stop = init_stop(s, x, t, p, a)
            stop = max(stop, hi - k * a)
            if pos > 0 and c[j] < stop: new = 0.0
        elif rule == 'user_2d':                    # 連 2 天收盤跌破才算；連 2 天站回 5 日線才買回
            b5 = c[j] < ma5 and c[j - 1] < x['ma5'][j - 1]
            b10 = c[j] < ma10 and c[j - 1] < x['ma10'][j - 1]
            a5 = c[j] > ma5 and c[j - 1] > x['ma5'][j - 1]
            if b10: new = 0.0
            elif b5: new = min(pos, 0.5)
            elif a5: new = 1.0
        elif rule == 'user_buf':                   # 跌破要超過 0.5ATR 才算；站回 5 日線且 5 日線上彎才買回
            if c[j] < ma10 - 0.5 * a: new = 0.0
            elif c[j] < ma5 - 0.5 * a: new = min(pos, 0.5)
            elif c[j] > ma5 and ma5 > x['ma5'][j - 1]: new = 1.0
        elif rule.startswith('ma10b'):             # 收盤跌破 10 日線 −k×ATR 出場（停損跟著 10 日線上移），可選站回 5 日線且 5>10 買回
            k = float(rule[5:].split('_')[0])
            if pos > 0 and c[j] < ma10 - k * a: new = 0.0
            elif pos == 0 and rule.endswith('_rebuy') and c[j] > ma5 > ma10: new = 1.0
        elif rule.startswith('ma20b'):
            k = float(rule[5:].split('_')[0])
            if pos > 0 and c[j] < ma20 - k * a: new = 0.0
        elif rule == 'cap10hi':             # 20 日線 −1ATR，但不低於最高收盤 ×0.9（10% 移動上限）
            if pos > 0 and c[j] < max(ma20 - a, hi * 0.9): new = 0.0
        elif rule == 'cap10in':             # 20 日線 −1ATR，但不低於進場價 ×0.9
            if pos > 0 and c[j] < max(ma20 - a, p * 0.9): new = 0.0
        elif rule == 'cap15hi':
            if pos > 0 and c[j] < max(ma20 - a, hi * 0.85): new = 0.0
        elif rule == 'user_cross':                 # 跌破 5 日線減碼、5 日線跌破 10 日線（死叉）出場；黃金交叉且站上 5 日線買回
            if ma5 < ma10: new = 0.0
            elif c[j] < ma5: new = min(pos, 0.5)
            elif c[j] > ma5: new = 1.0
        if new != pos:
            if new < pos: val *= 1 - SELL * (pos - new)
            else: val *= 1 - BUY * (new - pos)
            trades += 1
            pos = new
        peak = max(peak, val); mdd = max(mdd, 1 - val / peak)
    if pos > 0: val *= 1 - SELL * pos
    return val - 1, trades, mdd, held / H


RULES = ['hold', 'fixed', 'ma20b1', 'cap10hi', 'cap10in', 'cap15hi', 'chand3']


def trend(s):
    x = S[s['sid']]; t = s['t']
    return x['c'][t] > x['ma5'][t] > x['ma10'][t]


SUBS = {'全部': lambda s: True, '趨勢模式(收>5日>10日)': trend,
        '趨勢＋支撐>3.5ATR遠': lambda s: trend(s) and far(s), '非趨勢＋支撐>3.5ATR遠': lambda s: (not trend(s)) and far(s),
        '趨勢・前段': lambda s: trend(s) and s['date'] < '20260101', '趨勢・後段': lambda s: trend(s) and s['date'] >= '20260101'}


def far(s):
    sup = s['lv'].get('S0k5')
    if sup is None: return False
    return s['p'] - sup > 3.5 * s['atr']


res = {}
for name, f in SUBS.items():
    sel = [s for s in samples if f(s)]
    print(f'== {name}  n={len(sel)}')
    res[name] = {}
    for r in RULES:
        out = np.array([run(s, r) for s in sel])
        ret, tr, mdd, held = out[:, 0], out[:, 1], out[:, 2], out[:, 3]
        res[name][r] = {'avg%': round(ret.mean() * 100, 2), 'med%': round(float(np.median(ret)) * 100, 2),
                        'p5%': round(float(np.percentile(ret, 5)) * 100, 1), 'mdd%': round(mdd.mean() * 100, 1),
                        'trades': round(tr.mean(), 1), 'held%': round(held.mean() * 100, 0)}
        v = res[name][r]
        print(f"   {r:12s} 平均 {v['avg%']:+6.2f}%  中位 {v['med%']:+6.2f}%  最差5% {v['p5%']:+6.1f}%  平均最大回撤 {v['mdd%']:5.1f}%  交易 {v['trades']:4.1f} 次  持股 {v['held%']:.0f}%", flush=True)
json.dump(res, open('trailing_result.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
