"""PLAN-B73 研究：個股條件（quality.py F1～F9）能不能提高 20 個做多策略的勝率（出場固定 停損 8%／停利 25%）
B1 每個策略：單一條件 9＋兩兩 36＝45 種濾網，樣本內挑一個 → 樣本外驗（月份 block bootstrap、20 策略 BH 校正）
B2 品質分（全部策略共用）：樣本內合起來、單一條件讓勝率 +3 個百分點以上的入選 → 分數＝符合幾個；樣本外驗高分組 vs 低分組
用法：python run_quality.py <data_dir> <sig_all.csv.gz>
資料、股票池、成本、出場同 research/b72/run825.py；條件的計算跟網站掃描同一份 quality.py。"""
import itertools, json, math, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research', 'b72'))
sys.path.insert(0, os.path.join(ROOT, 'research', 'best')); sys.path.insert(0, os.path.join(ROOT, 'research', 'best2'))
import numpy as np
import pandas as pd
import engine
import quality as Q
from run825 import load, masks, split, random_825

IS = ('20211001', '20240630')
SEED = 20261014
BOOT = 2000
RULE_B1 = {'is_n': 100, 'oos_n': 50, 'win_gap': 0.05, 'bh_q': 0.10}
RULE_B2 = {'lift': 0.03, 'is_n_flag': 500, 'gap': 0.05, 'spearman': 0.8, 'level_n': 30}
OUT = os.path.join(HERE, 'quality_research.json')


def build_flags(P, sim, sector_of):
    """每檔跑 quality.stock_metrics（全部歷史）→ 每天呼叫 quality.day_flags（跟網站同一個函式）→ {F1..F9: T×S bool}"""
    T, S = sim.T, sim.S
    cols = [c for c in Q.COLS if c not in ('close',)]
    W = {c: np.full((T, S), np.nan) for c in cols}
    for j, sid in enumerate(sim.sids):
        ok = np.isfinite(sim.c[:, j])
        idx = np.nonzero(ok)[0]
        if len(idx) == 0:
            continue
        df = pd.DataFrame({'date': sim.dates[idx], 'open': sim.o[idx, j], 'high': sim.h[idx, j], 'low': sim.l[idx, j],
                           'close': sim.c[idx, j], 'volume': P['volume'][sid].to_numpy(float)[idx]})
        m = Q.stock_metrics(df)
        for c in cols:
            W[c][idx, j] = m[c].to_numpy(float)
    tx = P['taiex'].dropna()
    tx.index = tx.index.astype(str)
    Fl = {k: np.zeros((T, S), bool) for k in Q.FLAGS}
    start = int(np.searchsorted(sim.dates, engine.TRADE_FROM))
    for t in range(start, T):
        have = np.isfinite(sim.c[t])
        if not have.any():
            continue
        js = np.nonzero(have)[0]
        tab = pd.DataFrame({c: W[c][t, js] for c in cols}, index=sim.sids[js])
        for c in ('bull', 'gap60', 'pool'):
            tab[c] = tab[c] == 1
        f = Q.day_flags(tab, Q.taiex_above_ma60(tx, str(sim.dates[t])), sector_of)
        for k in Q.FLAGS:
            Fl[k][t, js] = f[k].to_numpy()
    return Fl


def month_boot_p(trA, trB, OOS, reps=BOOT, seed=SEED):
    """樣本外月份 block bootstrap：每次有放回抽月份，算 勝率(A) − 勝率(B)；回傳 (單邊 p＝差 ≤ 0 的比例, 95% 區間)"""
    def by_month(tr):
        d = tr['date'].astype(str)
        t = tr[(d >= OOS[0]) & (d <= OOS[1])]
        return {mo: g['ret'].to_numpy() for mo, g in t.groupby(t['date'].astype(str).str[:6])}
    A, B = by_month(trA), by_month(trB)
    months = sorted(set(A) | set(B))
    if not months:
        return 1.0, (None, None)
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(reps):
        pick = rng.choice(len(months), len(months), replace=True)
        a = np.concatenate([A.get(months[i], np.zeros(0)) for i in pick])
        b = np.concatenate([B.get(months[i], np.zeros(0)) for i in pick])
        if len(a) == 0 or len(b) == 0:
            continue
        diffs.append((a > 0).mean() - (b > 0).mean())
    if not diffs:
        return 1.0, (None, None)
    diffs = np.array(diffs)
    return float((diffs <= 0).mean()), (float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)))


def bh(pvals: dict) -> dict:
    """Benjamini-Hochberg 校正後的 p 值"""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj, prev = {}, 1.0
    for rank in range(m, 0, -1):
        k, p = items[rank - 1]
        prev = min(prev, p * m / rank)
        adj[k] = prev
    return adj


def b1_pass(oos, base_oos, p_adj, rule=RULE_B1) -> bool:
    return bool(oos.get('n', 0) >= rule['oos_n'] and oos['win'] >= base_oos.get('win', 1) + rule['win_gap']
                and oos['mean'] > base_oos.get('mean', 9) and p_adj < rule['bh_q'])


def per_day(m, OOS, dates):
    d = (dates >= OOS[0]) & (dates <= OOS[1])
    rows = m[d].sum(axis=1)
    return float(rows.mean()) if len(rows) else 0.0


def desc(combo):
    return '＋'.join(Q.FLAGS[k] for k in combo)


def main(data_dir, sig_path):
    t0 = time.time()
    P, F, sim = load(data_dir)
    last = str(sim.dates[-2])
    OOS = ('20240701', last)
    years = ('2022', '2023', '2024', '2025', '2026')
    sector_of = Q.load_sector_map()
    json.dump(sector_of, open(os.path.join(HERE, 'sector_map.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    Fl = build_flags(P, sim, sector_of)
    print(f'flags ready {time.time() - t0:.0f}s', {k: round(float(v.mean()), 3) for k, v in Fl.items()}, flush=True)
    pool = F['liquid'].to_numpy() & (sim.dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    M = masks(sim, sig_path, pool)
    from scanner import STRATEGIES
    combos = [(k,) for k in Q.FLAGS] + list(itertools.combinations(Q.FLAGS, 2))
    res, pv, base_trades = {}, {}, {}
    for key, m in sorted(M.items()):
        base = sim.trades825(m)
        base_trades[key] = base
        sb = split(base, IS, OOS, years)
        best = None
        for cb in combos:
            fm = np.ones_like(m)
            for k in cb:
                fm &= Fl[k]
            tr = sim.trades825(m & fm)
            s_is = split(tr, IS, OOS, years)['is']
            if s_is.get('n', 0) < RULE_B1['is_n'] or s_is['mean'] < sb['is'].get('mean', 9):
                continue
            score = (s_is['win'], s_is['mean'])
            if best is None or score > best[0]:
                best = (score, cb, tr, fm)
        r = {'label': STRATEGIES.get(key, key), 'base': {p: sb[p] for p in ('is', 'oos', 'years')},
             'per_day_base': per_day(m, OOS, sim.dates)}
        if best is None:
            r['b1'] = None
            pv[key] = 1.0
        else:
            _, cb, tr, fm = best
            ss = split(tr, IS, OOS, years)
            p, ci = month_boot_p(tr, base, OOS)
            pv[key] = p
            r['b1'] = {'combo': list(cb), 'desc': desc(cb), **{q: ss[q] for q in ('is', 'oos', 'years', 'reasons')},
                       'p': p, 'ci': ci, 'random': random_825(sim, pool & fm, m & fm, OOS),
                       'per_day': per_day(m & fm, OOS, sim.dates)}
        res[key] = r
        print(f'{key}: base oos {sb["oos"].get("n")}/{sb["oos"].get("win")} b1 {r["b1"] and r["b1"]["desc"]} '
              f'{r["b1"] and (r["b1"]["oos"].get("n"), r["b1"]["oos"].get("win"), r["b1"]["oos"].get("mean"), r["b1"]["p"])} {time.time() - t0:.0f}s', flush=True)
    adj = bh(pv)
    for key, r in res.items():
        if r['b1']:
            r['b1']['p_adj'] = adj[key]
            r['b1']['passed'] = b1_pass(r['b1']['oos'], r['base']['oos'], adj[key])
    # ── B2 品質分 ──
    rows = []
    for key, tr in base_trades.items():
        if len(tr) == 0:
            continue
        t, s = tr['t'].to_numpy(), tr['s'].to_numpy()
        d = pd.DataFrame({'strategy': key, 'date': tr['date'].astype(str).to_numpy(), 'win': tr['ret'].to_numpy() > 0,
                          'ret': tr['ret'].to_numpy()})
        for k in Q.FLAGS:
            d[k] = Fl[k][t, s]
        rows.append(d)
    A = pd.concat(rows, ignore_index=True)
    isA = A[(A.date >= IS[0]) & (A.date <= IS[1])]
    ooA = A[(A.date >= OOS[0]) & (A.date <= OOS[1])]
    lifts = {}
    for k in Q.FLAGS:
        sub = isA[isA[k]]
        lifts[k] = {'n': int(len(sub)), 'win': float(sub.win.mean()) if len(sub) else None,
                    'lift': float(sub.win.mean() - isA.win.mean()) if len(sub) else None,
                    'oos_lift': float(ooA[ooA[k]].win.mean() - ooA.win.mean()) if ooA[k].any() else None}
    keys = [k for k in Q.FLAGS if lifts[k]['n'] >= RULE_B2['is_n_flag'] and (lifts[k]['lift'] or 0) >= RULE_B2['lift']]
    score = {'keys': keys, 'lifts': lifts, 'is_win_all': float(isA.win.mean()), 'oos_win_all': float(ooA.win.mean())}
    if keys:
        cut = math.ceil(len(keys) / 2)
        for D in (A,):
            D['score'] = D[keys].sum(axis=1)
        ooA = A[(A.date >= OOS[0]) & (A.date <= OOS[1])]
        hi, lo = ooA[ooA.score >= cut], ooA[ooA.score < cut]
        tr_hi = pd.DataFrame({'date': hi.date, 'ret': hi.ret}); tr_lo = pd.DataFrame({'date': lo.date, 'ret': lo.ret})
        p, ci = month_boot_p(tr_hi, tr_lo, OOS)
        lv = ooA.groupby('score').agg(n=('win', 'size'), win=('win', 'mean'), mean=('ret', 'mean')).reset_index()
        lv_ok = lv[lv.n >= RULE_B2['level_n']]
        rho = float(lv_ok[['score', 'win']].corr(method='spearman').iloc[0, 1]) if len(lv_ok) >= 3 else None
        diff = float(hi.win.mean() - lo.win.mean()) if len(hi) and len(lo) else None
        passed = bool(diff is not None and diff >= RULE_B2['gap'] and ci[0] is not None and ci[0] > 0
                      and rho is not None and rho >= RULE_B2['spearman'])
        score.update({'cut': cut, 'oos_high': {'n': int(len(hi)), 'win': float(hi.win.mean()) if len(hi) else None, 'mean': float(hi.ret.mean()) if len(hi) else None},
                      'oos_low': {'n': int(len(lo)), 'win': float(lo.win.mean()) if len(lo) else None, 'mean': float(lo.ret.mean()) if len(lo) else None},
                      'diff': diff, 'p': p, 'ci': ci, 'spearman': rho, 'passed': passed,
                      'levels': lv.to_dict(orient='records')})
        isA2 = A[(A.date >= IS[0]) & (A.date <= IS[1])]
        score['is_levels'] = isA2.groupby('score').agg(n=('win', 'size'), win=('win', 'mean'), mean=('ret', 'mean')).reset_index().to_dict(orient='records')
        for key in res:
            o = ooA[ooA.strategy == key]
            res[key]['buckets'] = o.groupby('score').agg(n=('win', 'size'), win=('win', 'mean'), mean=('ret', 'mean')).reset_index().to_dict(orient='records')
            res[key]['high'] = {'n': int((o.score >= cut).sum()), 'win': float(o[o.score >= cut].win.mean()) if (o.score >= cut).any() else None,
                                'mean': float(o[o.score >= cut].ret.mean()) if (o.score >= cut).any() else None}
            mk = M[key]
            sc = sum(Fl[k].astype(np.int8) for k in keys)
            res[key]['per_day_high'] = per_day(mk & (sc >= cut), OOS, sim.dates)
        # 去掉 F6（產業對照表是現在的，下市股沒有）的對照
        k2 = [k for k in keys if k != 'F6']
        if k2 and len(k2) != len(keys):
            c2 = math.ceil(len(k2) / 2)
            s2 = ooA[k2].sum(axis=1)
            score['no_f6'] = {'keys': k2, 'cut': c2, 'high_win': float(ooA[s2 >= c2].win.mean()), 'low_win': float(ooA[s2 < c2].win.mean())}
    else:
        score['passed'] = False
    meta = {'exit': '停損 8%／停利 25%（盤中觸價、跳空用開盤價、同一天都碰到算停損）、不限天數（上限 250 交易日）',
            'periods': {'is': IS, 'oos': OOS}, 'rule_b1': RULE_B1, 'rule_b2': RULE_B2, 'boot': BOOT, 'seed': SEED,
            'pool': '4 碼普通股、收盤 ≥ 10、20 日均量 ≥ 500 張、≥ 120 根、60 天內沒有 >10.5% 跳動', 'data_end': str(sim.dates[-1]),
            'generated': time.strftime('%Y-%m-%d %H:%M'), 'sector_map': f'chip_data/sector.db（{len(sector_of)} 檔，現在的對照，下市股多半沒有）'}
    out = {'meta': meta, 'flags': Q.FLAGS, 'score': score, 'strategies': res}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    print('score', {k: score.get(k) for k in ('keys', 'cut', 'diff', 'ci', 'spearman', 'passed')}, f'{time.time() - t0:.0f}s', flush=True)
    return out, Fl, sim, P


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
