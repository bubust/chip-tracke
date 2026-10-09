"""PLAN-BEST2 主程式：
  strat：18 個現有做多策略各自「原本（網站預設出場）vs 改良（濾網＋出場）」
  e7：固定 % 停損、沒跌破一直抱 專題
  grid：全部訊號 × 濾網 × 出場（含新 E6／E7）→ 嚴格／放寬兩層選法
用法：python run2.py <data_dir> [strat|e7|grid|all]（資料、sig_a.csv.gz、e5.csv 跟 research/best 共用）
輸出：research/best2/results/"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research', 'best')); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import engine, run
import engine2
from engine2 import Sim2

OUT = os.path.join(HERE, 'results')
IS, OOS, YEARS = run.IS, run.OOS, run.YEARS
STRICT = dict(run.RULE)
RELAX = {'win': 0.55, 'pf': 1.2, 'n_is': 100, 'n_oos': 50, 'p5': -0.20, 'years_pos': 3, 'top': 20,
         'base_gap': 0.03, 'mdd': 0.30, 'boot': 2000}
SEED = 20261009


def load(data_dir):
    t0 = time.time()
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, data_dir)
    work = os.path.dirname(os.path.abspath(data_dir))
    sigs = run.build_signals(P, F, os.path.join(work, 'sig_a.csv.gz'))
    sim = Sim2(P, F, fac)
    sim.e5, sim.e5_stop = run.compute_e5(P, sigs, os.path.join(work, 'e5.csv'))
    print(f'load {time.time() - t0:.0f}s', flush=True)
    return P, F, fac, sigs, sim


def filters(P, F, sim):
    reg = run.regime_masks(P, F)
    c = P['close'].to_numpy(float)
    with np.errstate(invalid='ignore'):
        return {'none': None, 'tx60': reg['tx60'][:, None], 'tx200': reg['tx200'][:, None],
                'c60': c > F['ma60'].to_numpy(float), 'c200': c > F['ma200'].to_numpy(float)}


def apply_filter(m, f):
    return m if f is None else (m & f)


def all_exits():
    R = dict(run.exit_rules())
    R.update(engine2.new_exit_rules())
    return R


def stats_row(name, tr, extra=None):
    ss = run.split_stats(tr)
    row = run.flat(name, ss)
    d = tr['date'].astype(str)
    row['open_share'] = float(tr['open'][d <= OOS[1]].mean()) if len(tr) else None
    if extra:
        row.update(extra)
    return row


def boot_diff(tr_a, tr_b, reps=2000, seed=SEED):
    """樣本外 平均每筆（a − b）依月份 bootstrap 95% 區間（兩組同一批月份重抽）"""
    def by_month(tr):
        d = tr['date'].astype(str)
        t = tr[(d >= OOS[0]) & (d <= OOS[1])]
        return {m: g['ret'].to_numpy() for m, g in t.groupby(t['date'].astype(str).str[:6])}
    A, B = by_month(tr_a), by_month(tr_b)
    months = sorted(set(A) | set(B))
    if not months:
        return None, None
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(reps):
        pick = rng.choice(months, len(months), replace=True)
        a = np.concatenate([A.get(m, np.array([])) for m in pick])
        b = np.concatenate([B.get(m, np.array([])) for m in pick])
        if len(a) and len(b):
            diffs.append(a.mean() - b.mean())
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def port(sim, tr, strength, slots, weight):
    """逐日帳戶模擬：開盤先處理出場（用交易表的出場價 px_out：開盤、盤中停損價或最後收盤）再進場（同天依強度排序），
    最多 slots 檔、每筆＝前一天淨值 × weight（現金不夠就買少一點）；收盤算淨值（含除權息）"""
    tr = tr.copy()
    tr['str'] = strength[tr['t'].to_numpy(), tr['s'].to_numpy()]
    by_e = {e: g.sort_values('str', ascending=False) for e, g in tr.groupby('e')}
    cash, eq, hold, curve, expo, taken, lastpx = 1.0, 1.0, {}, [], [], 0, {}
    start = int(np.searchsorted(sim.dates, engine.TRADE_FROM))
    oos_end = int(np.searchsorted(sim.dates, OOS[1], side='right'))
    end = sim.T
    for d in range(start, end):
        for k in [k for k, hd in hold.items() if hd[2] == d]:
            s, e, x, sh, pxo = hold.pop(k)
            cash += sh * pxo * sim.cumfac[x, s] / sim.cumfac[e, s] * (1 - engine.SELL_COST)
        if d in by_e and d <= oos_end:
            for r in by_e[d].itertuples():
                if len(hold) >= slots:
                    break
                amt = min(eq * weight, cash)
                if amt <= eq * 0.005:
                    continue
                sh = amt / (sim.o[d, r.s] * (1 + engine.BUY_COST))
                cash -= amt
                hold[r.Index] = (r.s, r.e, r.x, sh, r.px_out)
                taken += 1
        val = 0.0
        for s, e, x, sh, pxo in hold.values():
            p = sim.c[d, s]
            if np.isfinite(p):
                lastpx[(s, e)] = p
            else:
                p = lastpx.get((s, e), sim.o[e, s])
            val += sh * p * sim.cumfac[d, s] / sim.cumfac[e, s]
        eq = cash + val
        curve.append((sim.dates[d], eq))
        expo.append(val / eq if eq > 0 else 0)
    cv = pd.Series([v for _, v in curve], index=[k for k, _ in curve])
    cv = cv[cv.index <= sim.dates[min(oos_end + 60, sim.T - 1)]]
    yrs = len(cv) / 245
    return {'cagr': float(cv.iloc[-1] ** (1 / yrs) - 1), 'mdd': float((cv / cv.cummax() - 1).min()),
            'exposure': float(np.mean(expo)), 'taken': taken,
            'yearly': {y: float(g.iloc[-1] / g.iloc[0] - 1) for y, g in cv.groupby(cv.index.str[:4])}}


# ── 1. 現有策略改良 ──────────────────────────────────────────────────────────
def stage_strat(P, F, fac, sigs, sim):
    os.makedirs(OUT, exist_ok=True)
    flt = filters(P, F, sim)
    exits = all_exits()
    shape = (sim.T, sim.S)
    keys = sorted(k for k in sigs if k.startswith('A_'))
    t0 = time.time()
    # E0：網站預設出場（backtest_engine.simulate），每個策略 × 濾網
    dense = {}
    for k in keys:
        m = run.dense(sigs[k], shape)
        for fk, fv in flt.items():
            dense[f'{k}|{fk}'] = apply_filter(m, fv)
    e0 = engine2.run_e0(sim, P, dense)
    cut = sim.trade_to - 60 - 1
    e0 = {k: v[v['t'] < cut].reset_index(drop=True) for k, v in e0.items()}
    print(f'E0 {time.time() - t0:.0f}s', flush=True)
    rows, trades_keep = [], {}
    for k in keys:
        for fk in flt:
            name = f'{k}|{fk}|E0_site'
            tr = e0[f'{k}|{fk}']
            rows.append(stats_row(name, tr))
            if fk == 'none':
                trades_keep[name] = tr
            m = dense[f'{k}|{fk}']
            for ek, rule in exits.items():
                tr = sim.trades2(m, rule)
                rows.append(stats_row(f'{k}|{fk}|{ek}', tr))
        print(f'  {k} {time.time() - t0:.0f}s', flush=True)
    g = pd.DataFrame(rows)
    g.to_csv(os.path.join(OUT, 'strat_grid.csv'), index=False)
    # 每個策略挑改良版
    pool = F['liquid'].to_numpy() & (sim.dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    res = []
    for k in keys:
        base = g[g.combo == f'{k}|none|E0_site'].iloc[0]
        sub = g[g.combo.str.startswith(k + '|') & (g.is_n >= 100) & (g.is_mean > 0) & (g.is_pf >= 1.2)]
        out = {'strategy': k, 'baseline': base.to_dict(), 'n_tested': int((g.combo.str.startswith(k + '|')).sum())}
        if len(sub) == 0:
            out.update(pick=None, improved=False, reasons=['樣本內沒有任何組合 筆數≥100、平均>0、PF≥1.2'])
            res.append(out)
            continue
        pick = sub.sort_values(['is_win', 'is_mean'], ascending=False).iloc[0]
        out['pick'] = pick.to_dict()
        _, fk, ek = pick.combo.split('|')
        m = dense[f'{k}|{fk}']
        tr_p = e0[f'{k}|{fk}'] if ek == 'E0_site' else sim.trades2(m, exits[ek])
        tr_b = trades_keep[f'{k}|none|E0_site']
        lo, hi = boot_diff(tr_p, tr_b)
        out['boot_diff'] = (lo, hi)
        rule = exits.get(ek)
        base_rand = _rand_e0(sim, P, pool, m) if ek == 'E0_site' else _rand2(sim, pool, m, rule)
        out['random'] = base_rand
        reasons = []
        if not (pick.oos_mean > 0):
            reasons.append(f'樣本外平均 {pick.oos_mean:+.2%} ≤ 0')
        if not (pick.oos_mean > base.oos_mean):
            reasons.append(f'樣本外平均沒比原本好（{pick.oos_mean:+.2%} vs {base.oos_mean:+.2%}）')
        if pick.oos_win < base.oos_win - 0.02:
            reasons.append(f'樣本外勝率比原本低超過 2 點（{pick.oos_win:.1%} vs {base.oos_win:.1%}）')
        if lo is None or lo <= 0:
            reasons.append(f'改良−原本 的樣本外差距 bootstrap 下限 ≤ 0（{(lo or 0):+.2%}）')
        if base_rand and pick.oos_win < base_rand['win'] + 0.05:
            reasons.append(f'樣本外勝率沒比隨機進場高 5 點（{pick.oos_win:.1%} vs {base_rand["win"]:.1%}）')
        out['reasons'] = reasons
        out['improved'] = not reasons
        st = run.strength_of(sigs[k], shape)
        out['port_base'] = {'10x10': port(sim, tr_b, st, 10, 0.1), '20x5': port(sim, tr_b, st, 20, 0.05)}
        out['port_pick'] = {'10x10': port(sim, tr_p, st, 10, 0.1), '20x5': port(sim, tr_p, st, 20, 0.05)}
        res.append(out)
        print(' ', k, 'pick', pick.combo, 'improved' if out['improved'] else reasons, flush=True)
    json.dump(res, open(os.path.join(OUT, 'strat_pick.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=_js)


def _rand_masks(sim, pool, sig, reps, seed):
    rng = np.random.default_rng(seed)
    month = np.array([d[:6] for d in sim.dates])
    oos = (sim.dates >= OOS[0]) & (sim.dates <= OOS[1])
    cnt = pd.Series(month[np.nonzero(sig & oos[:, None])[0]]).value_counts()
    cells = {mo: np.argwhere(pool & (month == mo)[:, None]) for mo in cnt.index}
    out = []
    for _ in range(reps):
        m = np.zeros(sig.shape, bool)
        for mo, k in cnt.items():
            cl = cells[mo]
            if len(cl):
                pick = cl[rng.choice(len(cl), size=min(k, len(cl)), replace=False)]
                m[pick[:, 0], pick[:, 1]] = True
        out.append(m)
    return out


def _rand_e0(sim, P, pool, sig, reps=3, seed=SEED):
    """E0（網站預設出場）的隨機基準：只做 3 次（每次要跑全部股票的 backtest_engine）"""
    ms = _rand_masks(sim, pool, sig, reps, seed)
    res = engine2.run_e0(sim, P, {f'R{i}': m for i, m in enumerate(ms)})
    st = [engine.stats(v['ret'].to_numpy()) for v in res.values()]
    st = [r for r in st if r.get('n')]
    return {'win': float(np.mean([r['win'] for r in st])), 'mean': float(np.mean([r['mean'] for r in st])), 'reps': reps} if st else None


def _rand2(sim, pool, sig, rule, reps=20, seed=SEED):
    """隨機基準（同出場、同月份筆數、股票池裡隨機挑），trades2 版"""
    res = []
    for m in _rand_masks(sim, pool, sig, reps, seed):
        tr = sim.trades2(m, rule)
        tr = tr[(tr['date'].astype(str) >= OOS[0]) & (tr['date'].astype(str) <= OOS[1])]
        res.append(engine.stats(tr['ret'].to_numpy()))
    res = [r for r in res if r.get('n')]
    if not res:
        return None
    return {'win': float(np.mean([r['win'] for r in res])), 'mean': float(np.mean([r['mean'] for r in res])), 'reps': reps}


def _js(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


# ── 2. 固定 % 停損、沒跌破一直抱 ─────────────────────────────────────────────
def stage_e7(P, F, fac, sigs, sim):
    os.makedirs(OUT, exist_ok=True)
    shape = (sim.T, sim.S)
    pool = F['liquid'].to_numpy() & (sim.dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    rng = np.random.default_rng(SEED)
    cells = np.argwhere(pool & (sim.dates <= OOS[1])[:, None])
    pick = cells[rng.choice(len(cells), size=30000, replace=False)]
    rnd = np.zeros(shape, bool)
    rnd[pick[:, 0], pick[:, 1]] = True
    srcs = {k: run.dense(sigs[k], shape) for k in sorted(sigs) if k.startswith('A_')}
    srcs['RANDOM'] = rnd
    rows = []
    tx = run.taiex_bh(P)
    for src, m in srcs.items():
        for sp in (5, 7, 10, 15, 20):
            for mode in ('close', 'intraday'):
                rule = {'kind': 'hold', 'stp': sp / 100, 'mode': mode, 'max': engine2.E7_CAP}
                tr = sim.trades2(m, rule)
                tr = tr[tr['date'].astype(str) <= OOS[1]]
                if not len(tr):
                    continue
                r = tr['ret'].to_numpy()
                stopped = (~tr['open'].to_numpy()) & (tr['days'].to_numpy() < engine2.E7_CAP)
                wash60 = stopped & (tr['days'].to_numpy() <= 60)
                st = run.strength_of(sigs[src], shape) if src != 'RANDOM' else np.ones(shape)
                pa = port(sim, tr.reset_index(drop=True), st, 10, 0.1)
                row = {'src': src, 'stop': sp, 'mode': mode, **engine.stats(r, tr['days'].to_numpy()),
                       'stopped_share': float(stopped.mean()), 'wash60': float(wash60.mean()),
                       'capped_share': float(((~tr['open']) & (tr['days'] >= engine2.E7_CAP)).mean()),
                       'open_share': float(tr['open'].mean()),
                       'mean_stopped': float(r[stopped].mean()) if stopped.any() else None,
                       'mean_kept': float(r[~stopped].mean()) if (~stopped).any() else None,
                       'port_cagr': pa['cagr'], 'port_mdd': pa['mdd'], 'port_exposure': pa['exposure']}
                is_ = tr['date'].astype(str) <= IS[1]
                row['is_win'] = float((r[is_.to_numpy()] > 0).mean()) if is_.any() else None
                row['oos_win'] = float((r[~is_.to_numpy()] > 0).mean()) if (~is_).any() else None
                row['is_mean'] = float(r[is_.to_numpy()].mean()) if is_.any() else None
                row['oos_mean'] = float(r[~is_.to_numpy()].mean()) if (~is_).any() else None
                rows.append(row)
        print('  e7', src, flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(os.path.join(OUT, 'e7_study.csv'), index=False)
    json.dump({'taiex': {k: v for k, v in tx.items() if k != 'curve'}}, open(os.path.join(OUT, 'e7_meta.json'), 'w', encoding='utf-8'), default=_js)


# ── 3. 全部組合：嚴格／放寬 ──────────────────────────────────────────────────
def stage_grid(P, F, fac, sigs, sim):
    os.makedirs(OUT, exist_ok=True)
    regs = run.regime_masks(P, F)
    exits = all_exits()
    shape = (sim.T, sim.S)
    rows, t0, n = [], time.time(), 0
    for sk, sp in sigs.items():
        m = run.dense(sp, shape)
        for rk, rm in regs.items():
            mm = m & rm[:, None]
            for ek, rule in exits.items():
                tr = sim.trades2(mm, rule)
                rows.append(stats_row(f'{sk}|{rk}|{ek}', tr))
                n += 1
        print(f'  grid {n} {time.time() - t0:.0f}s {sk}', flush=True)
    g = pd.DataFrame(rows)
    g.to_csv(os.path.join(OUT, 'grid2.csv'), index=False)
    pool = F['liquid'].to_numpy() & (sim.dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    out = {'n_combos': len(g), 'n_signals': len(sigs), 'n_exits': len(exits)}
    for tier, R in (('strict', STRICT), ('relaxed', RELAX)):
        out[tier] = select_tier(g, R, tier, sim, sigs, regs, exits, pool, P)
    json.dump(out, open(os.path.join(OUT, 'tiers.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=_js)


def _q(r, p, R, n_key):
    return (r[f'{p}_n'] >= R[n_key]) & (r[f'{p}_win'] >= R['win']) & (r[f'{p}_mean'] > 0) & (r[f'{p}_pf'] >= R['pf']) & (r[f'{p}_p5'] >= R['p5'])


def select_tier(g, R, tier, sim, sigs, regs, exits, pool, P):
    yrs = sum(((g[f'y{y}_mean'] > 0) & (g[f'y{y}_n'] > 0)).astype(int) for y in YEARS)
    ism = _q(g, 'is', R, 'n_is').fillna(False)
    top = g[ism].sort_values(['is_win', 'is_mean'], ascending=False).head(R['top'])
    oosm = (_q(top, 'oos', R, 'n_oos') & (yrs[top.index] >= R['years_pos'])).fillna(False)
    cands = top[oosm].sort_values(['oos_win', 'oos_mean'], ascending=False)
    res = {'rule': R, 'n_is_ok': int(ism.sum()), 'top': top[['combo', 'is_n', 'is_win', 'is_mean', 'oos_n', 'oos_win', 'oos_mean', 'oos_pf', 'oos_p5']].to_dict('records'),
           'n_top_oos_ok': int(oosm.sum()), 'checks': [], 'main': None}
    shape = (sim.T, sim.S)
    for c in cands.itertuples():
        sk, rk, ek = c.combo.split('|')
        m = run.dense(sigs[sk], shape) & regs[rk][:, None]
        rule = exits[ek]
        tr = sim.trades2(m, rule)
        tr = tr[tr['date'].astype(str) <= OOS[1]].reset_index(drop=True)
        base = _rand2(sim, pool, m, rule)
        lo, hi = run.bootstrap_ci(tr)
        st = run.strength_of(sigs[sk], shape)
        pa = port(sim, tr, st, 10, 0.1)
        pb = port(sim, tr, st, 20, 0.05)
        mdd = pa['mdd'] if tier == 'strict' else pb['mdd']
        reasons = []
        if base and c.oos_win < base['win'] + R['base_gap']:
            reasons.append(f"勝率沒比隨機高 {R['base_gap'] * 100:.0f} 點（{c.oos_win:.1%} vs {base['win']:.1%}）")
        if base and c.oos_mean <= base['mean']:
            reasons.append('平均每筆沒比隨機高')
        if lo <= 0:
            reasons.append(f'bootstrap 下限 ≤ 0（{lo:+.2%}）')
        if mdd < -R['mdd']:
            reasons.append(f"組合最大回撤 {mdd:.1%} 超過 {R['mdd']:.0%}（{'10 檔等分' if tier == 'strict' else '20 檔×5%'}）")
        chk = {'combo': c.combo, 'oos_win': c.oos_win, 'oos_mean': c.oos_mean, 'random': base, 'boot': (lo, hi),
               'port_10x10': pa, 'port_20x5': pb, 'reasons': reasons, 'pass': not reasons}
        res['checks'].append(chk)
        print(' ', tier, c.combo, 'PASS' if chk['pass'] else reasons, flush=True)
        if chk['pass']:
            res['main'] = c.combo
            break
    return res


if __name__ == '__main__':
    stage = sys.argv[2] if len(sys.argv) > 2 else 'all'
    P, F, fac, sigs, sim = load(sys.argv[1])
    if stage in ('strat', 'all'):
        stage_strat(P, F, fac, sigs, sim)
    if stage in ('e7', 'all'):
        stage_e7(P, F, fac, sigs, sim)
    if stage in ('grid', 'all'):
        stage_grid(P, F, fac, sigs, sim)
