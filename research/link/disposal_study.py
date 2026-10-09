"""PLAN-LINK 第 5 節：處置股（雙刀）
1. 處置前後每天：處置前 3～1 天、處置第 1～5 天、處置最後 3 天、出關後 1～5 天的平均漲跌（含除權息調整）、紅 K 比例、開盤跳空；初犯／再次處置分開
2. 多刀單做（主要＝處置股正偏差率才做）：處置第 1 天開盤買同產業 60 日相關最高（≥ 0.6）的配對股，出關後第 1 天開盤賣（或抱 5／10 天）
   比較：同產業其他成員同期間平均（超額）、隨機日子同規則
3. 出關買：處置期間跌（出關前最後收盤 < 處置前一天收盤）→ 出關後第 1 天開盤買處置股；變化：負偏差率、月線上彎＋布林 %b < 0.4；抱 5／10／20 天或停損 7%
4. 放空版（只有第一次處置）：處置第 1 天開盤 空處置股＋多配對股，各半資金，出關後第 1 天開盤平倉；放空成本 {0.2,0.5,1}%
月份 bootstrap p＋BH（同一家族）；樣本內外；事件 < 30 標樣本不足
用法：python disposal_study.py <price_data_dir>　→ results/disposal_*.csv、disposal_summary.json"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research', 'best')); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import engine
from sector_study import boot_p, bh, IS, OOS, SEED
from follow_study import trade_ret

OUT = os.path.join(HERE, 'results')


def load_events(dates):
    d = pd.read_csv(os.path.join(HERE, 'data', 'disposal.csv'), dtype=str)
    d = d[d.stock_id.str.fullmatch(r'[1-9]\d{3}') & d.start.str.len().eq(8) & d.end.str.len().eq(8)]
    d = d.drop_duplicates(['stock_id', 'start'])
    d['first'] = d.measure.str.contains('第一次') & ~d.measure.str.contains('第二次|再次')   # 第一次處置（5 分鐘撮合）vs 再次／第二次（20 分鐘、全部預收）
    pos = {x: i for i, x in enumerate(dates)}
    def idx_on_or_after(x):
        i = np.searchsorted(dates, x)
        return int(i) if i < len(dates) else None
    d['i0'] = d.start.map(idx_on_or_after)
    d['i1'] = d.end.map(lambda x: int(np.searchsorted(dates, x, side='right')) - 1)
    return d.dropna(subset=['i0']).astype({'i0': int, 'i1': int})


def main(data_dir):
    os.makedirs(OUT, exist_ok=True)
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, data_dir)
    dates = np.array(P['close'].index)
    sids = np.array(P['close'].columns)
    col = {s: i for i, s in enumerate(sids)}
    O, Hh, L, C = (P[k].to_numpy(float) for k in ('open', 'high', 'low', 'close'))
    cf = np.cumprod(fac.to_numpy(float), axis=0)
    pc = engine.per_stock(P['close'], lambda s: s.shift(1)).to_numpy(float)
    R = (C / pc) * (fac.to_numpy(float)) - 1                    # 含除權息調整的日報酬
    pool = F['liquid'].to_numpy() & ~F['gap60'].to_numpy()
    ma20 = F['ma20'].to_numpy(float)
    ma20_5 = engine.per_stock(F['ma20'], lambda s: s.shift(5)).to_numpy(float)
    sd20 = engine.per_stock(P['close'], lambda s: s.rolling(20).std()).to_numpy(float)
    mp = pd.read_csv(os.path.join(HERE, 'data', 'sectors.csv'), dtype=str)
    sec_of = {s: k for k, s in zip(mp.sector_id, mp.stock_id)}
    members = {k: [col[s] for s in g.stock_id if s in col] for k, g in mp.groupby('sector_id')}
    ev = load_events(dates)
    ev = ev[ev.stock_id.isin(col)]
    T = len(dates)
    rel_rows, peer_rows, rel_buy, short_rows = [], [], [], []
    rng = np.random.default_rng(SEED)
    for r in ev.itertuples():
        s = col[r.stock_id]
        i0, i1 = r.i0, r.i1
        if i0 < 65 or i1 + 21 >= T or i1 < i0:
            continue
        per = 'is' if IS[0] <= dates[i0] <= IS[1] else 'oos' if OOS[0] <= dates[i0] <= OOS[1] else None
        if per is None:
            continue
        # 1. 相對日
        def rel(k, lab):
            if 0 <= k < T and np.isfinite(R[k, s]):
                rel_rows.append({'stock_id': r.stock_id, 'start': dates[i0], 'first': bool(r.first), 'per': per, 'rel': lab,
                                 'ret': float(R[k, s]), 'red': bool(C[k, s] > O[k, s]),
                                 'gap': float(O[k, s] / pc[k, s] - 1) if np.isfinite(pc[k, s]) else None})
        for k in (3, 2, 1):
            rel(i0 - k, f'處置前{k}')
        for k in range(5):
            if i0 + k <= i1:
                rel(i0 + k, f'處置第{k + 1}天')
        for k in (2, 1, 0):
            if i1 - k >= i0:
                rel(i1 - k, f'出關前{k + 1}' if k else '處置最後一天')
        for k in range(1, 6):
            rel(i1 + k, f'出關後{k}')
        # 配對股（同產業、處置前一天在股票池、60 日相關最高且 ≥ 0.6）
        sec = sec_of.get(r.stock_id)
        peer, corr_best, dev = None, None, None
        if sec:
            mem = [m for m in members[sec] if m != s and pool[i0 - 1, m]]
            if mem:
                w = R[i0 - 60:i0]
                cs = [pd.Series(w[:, s]).corr(pd.Series(w[:, m])) for m in mem]
                cs = np.nan_to_num(np.array(cs), nan=-1)
                k = int(np.argmax(cs))
                if cs[k] >= 0.6:
                    peer, corr_best = mem[k], float(cs[k])
                    ratio = C[i0 - 60:i0, s] / C[i0 - 60:i0, peer]
                    dev = float(ratio[-1] / np.nanmean(ratio) - 1)
        exit_i = i1 + 1
        # 2. 多刀單做
        if peer is not None:
            for rk, rule in (('to_release', ('hold', exit_i - i0)), ('H5', ('hold', 5)), ('H10', ('hold', 10))):
                rp = trade_ret(O, C, cf, peer, i0, rule)
                others = [m for m in members[sec] if m not in (s, peer) and pool[i0 - 1, m]]
                ro = [trade_ret(O, C, cf, m, i0, rule) for m in others]
                ro = [x for x in ro if x is not None]
                if rp is not None and ro:
                    peer_rows.append({'stock_id': r.stock_id, 'peer': sids[peer], 'corr': corr_best, 'dev': dev, 'start': dates[i0],
                                      'first': bool(r.first), 'per': per, 'rule': rk, 'ret': rp, 'sector_avg': float(np.mean(ro)),
                                      'excess': rp - float(np.mean(ro))})
            # 4. 放空版（第一次處置）
            if r.first:
                rl = trade_ret(O, C, cf, peer, i0, ('hold', exit_i - i0))
                rs = (O[exit_i, s] / O[i0, s] * cf[exit_i, s] / cf[i0, s]) - 1 if np.isfinite(O[exit_i, s]) and np.isfinite(O[i0, s]) else None
                if rl is not None and rs is not None:
                    short_rows.append({'stock_id': r.stock_id, 'peer': sids[peer], 'dev': dev, 'start': dates[i0], 'per': per,
                                       'long': rl, 'short_stock_ret': float(rs)})
        # 3. 出關買
        if np.isfinite(C[i1, s]) and np.isfinite(C[i0 - 1, s]) and C[i1, s] < C[i0 - 1, s]:
            bb = (C[i1, s] - (ma20[i1, s] - 2 * sd20[i1, s])) / (4 * sd20[i1, s]) if sd20[i1, s] > 0 else np.nan
            up = ma20[i1, s] > ma20_5[i1, s]
            dev1 = None
            if peer is not None:
                ratio = C[i1 - 59:i1 + 1, s] / C[i1 - 59:i1 + 1, peer]
                dev1 = float(ratio[-1] / np.nanmean(ratio) - 1)
            for rk, rule in (('H5', ('hold', 5)), ('H10', ('hold', 10)), ('H20', ('hold', 20)), ('S7', ('stop', 0.07, 20))):
                x = trade_ret(O, C, cf, s, exit_i, rule)
                if x is not None:
                    rel_buy.append({'stock_id': r.stock_id, 'start': dates[i0], 'release': dates[exit_i], 'first': bool(r.first), 'per': per,
                                    'rule': rk, 'ret': x, 'bb': float(bb) if np.isfinite(bb) else None, 'ma20_up': bool(up), 'dev': dev1})
    rel_df, peer_df, buy_df, short_df = map(pd.DataFrame, (rel_rows, peer_rows, rel_buy, short_rows))
    for name, d in (('rel', rel_df), ('peer', peer_df), ('release', buy_df), ('short', short_df)):
        d.to_csv(os.path.join(OUT, f'disposal_{name}.csv'), index=False)
    summ = {'n_events': int(len(ev)), 'n_used': int(rel_df.drop_duplicates(['stock_id', 'start']).shape[0]) if len(rel_df) else 0}
    # 1. 相對日表
    tbl = []
    for (lab, fst), g in rel_df.groupby(['rel', 'first']):
        tbl.append({'rel': lab, 'first': fst, 'n': len(g), 'mean': g.ret.mean(), 'red': g.red.mean(), 'gap': g.gap.mean(),
                    'is_mean': g[g.per == 'is'].ret.mean(), 'oos_mean': g[g.per == 'oos'].ret.mean()})
    summ['relative_days'] = tbl
    # 2/3/4 家族
    fam = []
    def add(name, d, val='ret'):
        if not len(d):
            fam.append({'name': name, 'n': 0}); return
        row = {'name': name, 'n': len(d), 'mean': float(d[val].mean()), 'win': float((d[val] > 0).mean())}
        for per in ('is', 'oos'):
            x = d[d.per == per][val]
            row[f'{per}_n'], row[f'{per}_mean'] = len(x), float(x.mean()) if len(x) else None
            row[f'{per}_win'] = float((x > 0).mean()) if len(x) else None
        p, lo = boot_p(d[val].to_numpy(), d.start.astype(str).str[:6].to_numpy())
        row['p'], row['lo'] = p, lo
        fam.append(row)
    if len(peer_df):
        for rk in ('to_release', 'H5', 'H10'):
            g = peer_df[peer_df.rule == rk]
            add(f'peer_posdev_{rk}（主要）' if rk == 'to_release' else f'peer_posdev_{rk}', g[g.dev > 0], 'excess')
            add(f'peer_all_{rk}', g, 'excess')
            add(f'peer_posdev_{rk}_raw', g[g.dev > 0], 'ret')
    if len(buy_df):
        for rk in ('H5', 'H10', 'H20', 'S7'):
            g = buy_df[buy_df.rule == rk]
            add(f'release_buy_{rk}', g)
            add(f'release_buy_{rk}_negdev', g[g.dev.notna() & (g.dev < 0)])
            add(f'release_buy_{rk}_ma20up_bb04', g[g.ma20_up & g.bb.notna() & (g.bb < 0.4)])
    if len(short_df):
        for cost in (0.002, 0.005, 0.01):
            d = short_df.assign(pair=(short_df['long'] - short_df['short_stock_ret']) / 2 - cost / 2 - engine.BUY_COST / 2)
            add(f'short_pair_cost{cost}', d, 'pair')
            add(f'short_pair_cost{cost}_posdev', d[d.dev > 0], 'pair')
    for r, a in zip(fam, bh([r.get('p') for r in fam])):
        r['p_bh'] = a
        r['sufficient'] = r.get('n', 0) >= 30
    summ['family'] = fam
    json.dump(summ, open(os.path.join(OUT, 'disposal_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    print('events', summ['n_events'], 'used', summ['n_used'])
    for r in fam:
        print(r)


if __name__ == '__main__':
    main(sys.argv[1])
