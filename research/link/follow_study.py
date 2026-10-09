"""PLAN-LINK 第 4 節：龍頭（先發動）大漲後，跟進同產業高相關的「第二名」有沒有用
事件：某檔第 t 天「先發動」＝漲幅 ≥ 5%、收盤創 20 日新高、量 ≥ 前 20 日均量 2 倍、在股票池，且同產業前 10 天沒有別檔做到（同一天好幾檔 → 取漲幅最大）
候選：同產業、股票池、跟先發動那檔 60 日日報酬相關 ≥ 0.5、今天漲幅 < 它的一半
F1 買相關最高的一檔（主要假設：抱 5 天）／F2 買今天同產業漲幅第二名／F3 候選全部等權
t+1 開盤買；抱 {1,3,5,10} 天（開盤賣）或固定停損 7% 收盤判斷（最多 20 天）
基準：同產業隨機一檔（同一天）、隨機日子；月份 bootstrap p＋BH
用法：python follow_study.py <price_data_dir>　→ results/follow_events.csv、follow_summary.json"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research', 'best')); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import engine
from sector_study import boot_p, bh, IS, OOS, SEED

OUT = os.path.join(HERE, 'results')
HOLDS = (1, 3, 5, 10)


def trade_ret(o, c, cf, s, e, rule):
    """單筆（第 s 檔、第 e 天開盤買）報酬；rule＝('hold', n) 或 ('stop', pct, max)"""
    T = o.shape[0]
    if e >= T or not np.isfinite(o[e, s]):
        return None
    if rule[0] == 'hold':
        x = e + rule[1]
        while x < T and not np.isfinite(o[x, s]):
            x += 1
        if x >= T:
            return None
        px = o[x, s]
    else:
        stop = o[e, s] * (1 - rule[1])
        x = None
        for k in range(rule[2]):
            j = e + k
            if j >= T - 1:
                return None
            if np.isfinite(c[j, s]) and c[j, s] < stop:
                x = j + 1
                break
        if x is None:
            x = e + rule[2]
        while x < T and not np.isfinite(o[x, s]):
            x += 1
        if x >= T:
            return None
        px = o[x, s]
    r = px / o[e, s] * cf[x, s] / cf[e, s] * (1 - engine.SELL_COST) / (1 + engine.BUY_COST) - 1
    return float(r) if np.isfinite(r) else None


def main(data_dir):
    os.makedirs(OUT, exist_ok=True)
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, data_dir)
    dates = np.array(P['close'].index)
    sids = np.array(P['close'].columns)
    O, C, V = (P[k].to_numpy(float) for k in ('open', 'close', 'volume'))
    cf = np.cumprod(fac.to_numpy(float), axis=0)
    pool = F['liquid'].to_numpy() & ~F['gap60'].to_numpy() & (dates >= engine.TRADE_FROM)[:, None] & (dates <= OOS[1])[:, None]
    pc = engine.per_stock(P['close'], lambda s: s.shift(1)).to_numpy(float)
    R = C / pc - 1
    hh20 = engine.per_stock(P['close'], lambda s: s.shift(1).rolling(20).max()).to_numpy(float)
    vr = V / F['vol20p'].to_numpy(float)
    with np.errstate(invalid='ignore'):
        mover = pool & (R >= 0.05) & (C > hh20) & (vr >= 2)
    mp = pd.read_csv(os.path.join(HERE, 'data', 'sectors.csv'), dtype=str)
    col = {s: i for i, s in enumerate(sids)}
    secs = {k: [col[s] for s in g.stock_id if s in col] for k, g in mp.groupby('sector_id')}
    rng = np.random.default_rng(SEED)
    rules = {f'H{h}': ('hold', h) for h in HOLDS}
    rules['S7'] = ('stop', 0.07, 20)
    events = []
    for sec, mem in secs.items():
        mem = np.array(mem)
        last_mv = -10 ** 9                     # 同產業上一次有人「發動」的日子（不管有沒有記成事件）
        for t in range(len(dates) - 1):
            m = mem[mover[t, mem]]
            if not len(m):
                continue
            first = t - last_mv > 10
            last_mv = t
            if not first:
                continue
            a = m[np.argmax(R[t, m])]
            others = mem[(mem != a) & pool[t, mem]]
            if not len(others):
                continue
            win = R[max(0, t - 59):t + 1]
            ra = win[:, a]
            corr = np.array([pd.Series(ra).corr(pd.Series(win[:, b])) for b in others])
            lag = R[t, others] < R[t, a] / 2
            cand = others[(corr >= 0.5) & lag & np.isfinite(corr)]
            cc = corr[(corr >= 0.5) & lag & np.isfinite(corr)]
            picks = {}
            if len(cand):
                picks['F1'] = [cand[np.argmax(cc)]]
                picks['F3'] = list(cand)
            sec_today = others[np.argsort(-np.nan_to_num(R[t, others], nan=-9))]
            if len(sec_today):
                picks['F2'] = [sec_today[0]]
            picks['RAND_SECTOR'] = [rng.choice(others)]
            e = t + 1
            for fk, ss in picks.items():
                for rk, rule in rules.items():
                    rs = [trade_ret(O, C, cf, s, e, rule) for s in ss]
                    rs = [x for x in rs if x is not None]
                    if rs:
                        events.append({'sector': sec, 'date': dates[t], 'leader': sids[a], 'leader_ret': float(R[t, a]),
                                       'variant': fk, 'rule': rk, 'ret': float(np.mean(rs)), 'n_names': len(rs),
                                       'pick': ','.join(sids[s] for s in ss[:5])})
    ev = pd.DataFrame(events)
    ev.to_csv(os.path.join(OUT, 'follow_events.csv'), index=False)
    # 隨機日子基準：同樣規則，股票池裡隨機挑（同月份分布，用 F1 的事件月份）
    summ = []
    d = ev['date'].astype(str)
    for (fk, rk), g in ev.groupby(['variant', 'rule']):
        row = {'variant': fk, 'rule': rk, 'n': len(g)}
        gd = g['date'].astype(str)
        for per, (a, b) in (('is', IS), ('oos', OOS)):
            x = g[(gd >= a) & (gd <= b)]['ret'].to_numpy()
            row[f'{per}_n'] = len(x)
            row[f'{per}_mean'] = float(x.mean()) if len(x) else None
            row[f'{per}_win'] = float((x > 0).mean()) if len(x) else None
        p, lo = boot_p(g['ret'].to_numpy(), gd.str[:6].to_numpy())
        row['p'], row['lo'] = p, lo
        summ.append(row)
    # 隨機日子（股票池任一檔）
    cells = np.argwhere(pool)
    rd = cells[rng.choice(len(cells), 4000, replace=False)]
    for rk, rule in rules.items():
        rs = [trade_ret(O, C, cf, s, t + 1, rule) for t, s in rd]
        rs = np.array([x for x in rs if x is not None])
        summ.append({'variant': 'RAND_DAY', 'rule': rk, 'n': len(rs), 'all_mean': float(rs.mean()), 'all_win': float((rs > 0).mean())})
    fam = [r for r in summ if r['variant'] in ('F1', 'F2', 'F3')]
    for r, a in zip(fam, bh([r.get('p') for r in fam])):
        r['p_bh'] = a
        r['sufficient'] = r['n'] >= 30
    json.dump({'summary': summ, 'n_events': int(ev[(ev.variant == 'RAND_SECTOR') & (ev.rule == 'H5')].shape[0])},
              open(os.path.join(OUT, 'follow_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    for r in summ:
        print(r)


if __name__ == '__main__':
    main(sys.argv[1])
