"""PLAN-BEST2 第 6 節：大跌時買大盤（0050）／權值股（2330、2454、前 10 大成交金額股）
大跌訊號（第 t 天收盤後，只用到 t 為止的資料）：
  T1 加權 ≤ 60 日最高 ×(1−{8,10,15}%)；T2 加權 ≤ 60 日線 ×(1−{5,8,10}%)；
  T3 「負乖離抄底」家數 ≥ {50,100,200}；T4 「負乖離＋破底翻」家數 ≥ {20,50,100}
  只取第一天；進場後 20 個交易日內不重複觸發
買：t+1 開盤；出場：抱 {20,60,120} 天（開盤賣）／固定停損 {10,15,20}% 沒跌破抱（收盤判斷、最多 250 天）／停利 +10%、+20%（收盤到、最多 250 天）
比較：同標的、同出場，隨機日子進場（2,000 次）
用法：python crash.py <data_dir>　→ results/crash_events.csv、crash_summary.json"""
import glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research', 'best')); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import engine, run

OUT = os.path.join(HERE, 'results')
SEED = 20261009
COOLDOWN = 20


def load_etf(data_dir, code='0050'):
    """0050 日行情＋報酬調整（官方除權息表＋漲跌欄反推的參考價，抓得到 2025-06 一拆四）"""
    rows = []
    for f in sorted(glob.glob(os.path.join(data_dir, '20*.csv.gz'))):
        d = pd.read_csv(f, dtype={'stock_id': str, 'date': str})
        rows.append(d[d.stock_id == code])
    df = pd.concat(rows).drop_duplicates('date').set_index('date').sort_index()
    prev = df['close'].shift(1)
    ref = df['close'] - df['chg']
    f = (prev / ref).where(df['chg'].notna() & ref.gt(0) & prev.notna())
    f = f.where((f - 1).abs() > 0.003, 1.0).fillna(1.0)
    ev = pd.read_csv(os.path.join(data_dir, 'events.csv'), dtype={'date': str, 'stock_id': str})
    ev = ev[ev.stock_id == code].set_index('date')
    for d, r in ev.iterrows():
        if d in f.index:
            f.loc[d] = r['prev_close'] / r['ref']
    df['fac'] = f
    return df


def exit_single(o, c, cumfac, e, rule, T):
    """單一序列：回傳 (出場 index, 出場價, 還抱著)"""
    kind = rule['kind']
    if kind == 'hold_n':
        x = e + rule['n']
        return (x, o[x], False) if x < T else (T - 1, c[T - 1], True)
    ent = o[e]
    for k in range(rule['max']):
        j = e + k
        if j >= T:
            return T - 1, c[T - 1], True
        if not np.isfinite(c[j]):
            continue
        if (kind == 'stop' and c[j] < ent * (1 - rule['stp'])) or (kind == 'tp' and c[j] >= ent * (1 + rule['tgt'])):
            return (j + 1, o[j + 1], False) if j + 1 < T else (T - 1, c[T - 1], True)
    x = e + rule['max']
    return (x, o[x], False) if x < T else (T - 1, c[T - 1], True)


EXITS = {'H20': {'kind': 'hold_n', 'n': 20}, 'H60': {'kind': 'hold_n', 'n': 60}, 'H120': {'kind': 'hold_n', 'n': 120},
         'S10': {'kind': 'stop', 'stp': .10, 'max': 250}, 'S15': {'kind': 'stop', 'stp': .15, 'max': 250},
         'S20': {'kind': 'stop', 'stp': .20, 'max': 250},
         'TP10': {'kind': 'tp', 'tgt': .10, 'max': 250}, 'TP20': {'kind': 'tp', 'tgt': .20, 'max': 250}}


def main(data_dir):
    os.makedirs(OUT, exist_ok=True)
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, data_dir)
    dates = np.array(P['close'].index)
    T = len(dates)
    work = os.path.dirname(os.path.abspath(data_dir))
    sigs = run.build_signals(P, F, os.path.join(work, 'sig_a.csv.gz'))
    tx = P['taiex'].to_numpy(float)
    hi60 = pd.Series(tx).rolling(60, min_periods=60).max().to_numpy()
    ma60 = pd.Series(tx).rolling(60, min_periods=60).mean().to_numpy()
    cnt_bias = np.bincount(sigs['A_S_BIAS'][0], minlength=T)
    cnt_c1 = np.bincount(sigs['C1_S_BIAS+S_BREAKBOTTOM'][0], minlength=T)
    trade_ok = (dates >= engine.TRADE_FROM) & (dates <= run.OOS[1])
    with np.errstate(invalid='ignore'):
        triggers = {}
        for p in (8, 10, 15):
            triggers[f'T1_dd{p}'] = tx <= hi60 * (1 - p / 100)
        for q in (5, 8, 10):
            triggers[f'T2_ma60_{q}'] = tx <= ma60 * (1 - q / 100)
        for n in (50, 100, 200):
            triggers[f'T3_bias{n}'] = cnt_bias >= n
        for n in (20, 50, 100):
            triggers[f'T4_c1_{n}'] = cnt_c1 >= n
    # 標的
    etf = load_etf(data_dir).reindex(dates)
    inst = {'0050': (etf['open'].to_numpy(float), etf['close'].to_numpy(float), np.cumprod(etf['fac'].fillna(1.0).to_numpy(float)))}
    cum = np.cumprod(fac.to_numpy(float), axis=0)
    O, C = P['open'].to_numpy(float), P['close'].to_numpy(float)
    cols = {s: i for i, s in enumerate(P['close'].columns)}
    for sid in ('2330', '2454'):
        k = cols[sid]
        inst[sid] = (O[:, k], C[:, k], cum[:, k])
    turnover = pd.DataFrame(C * P['volume'].to_numpy(float)).rolling(20, min_periods=20).mean().to_numpy()

    def ret_single(o, c, cf, t, rule):
        e = t + 1
        if e >= T or not np.isfinite(o[e]):
            return None
        x, px, op = exit_single(o, c, cf, e, rule, T)
        r = px / o[e] * cf[x] / cf[e] * (1 - engine.SELL_COST) / (1 + engine.BUY_COST) - 1
        if not np.isfinite(r):                      # 停牌（例：0050 2025-06 分割暫停）出場那天沒價格 → 不算
            return None
        return {'ret': float(r), 'days': x - e, 'open': op}

    def ret_basket(t, rule):
        tv = np.nan_to_num(turnover[t], nan=-1)
        top = np.argsort(-tv)[:10]
        rs = [ret_single(O[:, k], C[:, k], cum[:, k], t, rule) for k in top]
        rs = [r for r in rs if r]
        if not rs:
            return None
        return {'ret': float(np.mean([r['ret'] for r in rs])), 'days': float(np.mean([r['days'] for r in rs])),
                'open': any(r['open'] for r in rs), 'names': [P['name'].iloc[k] for k in top]}

    def ret_of(name, t, rule):
        return ret_basket(t, rule) if name == 'TOP10' else ret_single(*inst[name], t, rule)

    events, summ = [], []
    rng = np.random.default_rng(SEED)
    valid_days = np.nonzero(trade_ok)[0]
    rand_days = rng.choice(valid_days, size=2000, replace=True)
    rand_cache = {}
    for tk, tm in triggers.items():
        ev_days, last = [], -10 ** 9
        for t in np.nonzero(tm & trade_ok)[0]:
            if t > 0 and tm[t - 1]:          # 只取第一天（前一天已觸發＝同一段）
                continue
            if t - last <= COOLDOWN:         # 上一次進場後 20 個交易日內不重複
                continue
            ev_days.append(t)
            last = t
        for name in ('0050', '2330', '2454', 'TOP10'):
            for ek, rule in EXITS.items():
                rs = []
                for t in ev_days:
                    r = ret_of(name, t, rule)
                    if r:
                        rs.append(r)
                        events.append({'trigger': tk, 'inst': name, 'exit': ek, 'date': dates[t], 'taiex': tx[t],
                                       'ret': r['ret'], 'days': r['days'], 'open': r['open']})
                key = (name, ek)
                if key not in rand_cache:
                    rr = [ret_of(name, int(d), rule) for d in rand_days[:600 if name == 'TOP10' else 2000]]
                    rr = [x['ret'] for x in rr if x]
                    rand_cache[key] = (float(np.mean(np.array(rr) > 0)), float(np.mean(rr)), len(rr))
                r = np.array([x['ret'] for x in rs])
                summ.append({'trigger': tk, 'inst': name, 'exit': ek, 'n_events': len(rs),
                             'win': float((r > 0).mean()) if len(r) else None, 'mean': float(r.mean()) if len(r) else None,
                             'median': float(np.median(r)) if len(r) else None, 'worst': float(r.min()) if len(r) else None,
                             'rand_win': rand_cache[key][0], 'rand_mean': rand_cache[key][1],
                             'dates': [str(dates[t]) for t in ev_days]})
        print(tk, len(ev_days), [str(dates[t]) for t in ev_days], flush=True)
    pd.DataFrame(events).to_csv(os.path.join(OUT, 'crash_events.csv'), index=False)
    # 0050 資料檢查：5 年含息報酬 vs 加權漲幅
    o50, c50, cf50 = inst['0050']
    a, b = np.searchsorted(dates, engine.TRADE_FROM), T - 1
    chk = {'etf_total_return': float(c50[b] / c50[a] * cf50[b] / cf50[a] - 1), 'taiex_return': float(tx[b] / tx[a] - 1),
           'years': float((b - a) / 245)}
    json.dump({'summary': summ, 'etf_check': chk, 'cooldown': COOLDOWN}, open(os.path.join(OUT, 'crash_summary.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)
    print('0050 check', chk)


if __name__ == '__main__':
    main(sys.argv[1])
