"""事後分析（不是選方法的依據）：最接近的方法（照規則沒過）在不同部位大小下的帳戶表現、訊號叢集、崩盤第一波。
用法：python diag.py <data_dir> <combo>　→ results/diag.json"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE))); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import engine, run


def main(data_dir, combo):
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, data_dir)
    sigs = run.build_signals(P, F, os.path.join(os.path.dirname(os.path.abspath(data_dir)), 'sig_a.csv.gz'))
    sim = engine.Sim(P, F, fac)
    sk, rk, ek = run.combo_parts(combo)
    regs = run.regime_masks(P, F)
    rule = run.exit_rules()[ek]
    m = run.dense(sigs[sk], (sim.T, sim.S)) & regs[rk][:, None]
    strength = run.strength_of(sigs[sk], (sim.T, sim.S))
    tr = sim.trades(m, rule)
    tr = tr[tr['date'].astype(str) <= run.OOS[1]].reset_index(drop=True)
    out = {'combo': combo, 'note': '事後分析：照事先定好的規則這個方法沒有過（組合最大回撤 > 30%），這裡的試算不是選方法的依據'}
    # 不同部位大小（每筆固定佔總資金 w、最多 k 檔）
    sizing = []
    for slots, w in ((10, 0.10), (5, 0.10), (10, 0.05), (20, 0.05), (5, 0.05)):
        pa = run.portfolio(sim, tr, strength, 'slots', slots=slots)
        if w != 1 / slots:
            pa = _portfolio_w(sim, tr, strength, slots, w)
        sizing.append({'slots': slots, 'weight': w, 'max_exposure': slots * w, 'cagr': pa['cagr'], 'mdd': pa['mdd'],
                       'exposure': pa['exposure'], 'taken': pa['taken'], 'yearly': pa['yearly']})
        print(slots, w, round(pa['cagr'], 4), round(pa['mdd'], 4), pa['taken'], flush=True)
    out['sizing'] = sizing
    # 訊號叢集：每月訊號數、同一天最多幾個
    d = tr['date'].astype(str)
    per_day = d.value_counts()
    per_month = d.str[:6].value_counts().sort_index()
    out['signals_per_month'] = {k: int(v) for k, v in per_month.items()}
    out['max_signals_one_day'] = {'date': per_day.idxmax(), 'n': int(per_day.max())}
    out['share_top5_months'] = float(per_month.sort_values(ascending=False).head(5).sum() / len(tr))
    # 崩盤第一波：大量訊號的月份裡，最早 5 天進場的 vs 之後的
    waves = []
    for mo, n in per_month.sort_values(ascending=False).head(5).items():
        t = tr[d.str[:6] == mo].sort_values('e')
        days = sorted(t['e'].unique())
        first = t[t['e'].isin(days[:max(1, len(days) // 3)])]
        rest = t[~t.index.isin(first.index)]
        waves.append({'month': mo, 'n': int(n), 'first_n': len(first), 'first_win': float((first.ret > 0).mean()),
                      'first_mean': float(first.ret.mean()), 'rest_n': len(rest),
                      'rest_win': float((rest.ret > 0).mean()) if len(rest) else None,
                      'rest_mean': float(rest.ret.mean()) if len(rest) else None})
    out['waves'] = waves
    json.dump(out, open(os.path.join(HERE, 'results', 'diag.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    print(json.dumps(out, ensure_ascii=False, default=float)[:3000])


def _portfolio_w(sim, tr, strength, slots, w):
    """run.portfolio 的「名額」版，但每筆固定佔總資金 w（不是 1/名額）"""
    T = sim.T
    tr = tr.copy()
    tr['str'] = strength[tr['t'].to_numpy(), tr['s'].to_numpy()]
    by_e = {e: g.sort_values('str', ascending=False) for e, g in tr.groupby('e')}
    cash, eq, hold, curve, expo, taken, lastpx = 1.0, 1.0, {}, [], [], 0, {}
    start = int(np.searchsorted(sim.dates, engine.TRADE_FROM))
    oos_end = int(np.searchsorted(sim.dates, run.OOS[1], side='right'))
    end = min(oos_end + 60, T)
    for d in range(start, end):
        for k in [k for k, hd in hold.items() if hd[2] == d]:
            s, e, x, sh, gone = hold.pop(k)
            px = sim.c[x, s] if gone else sim.o[x, s]
            cash += sh * px * sim.cumfac[x, s] / sim.cumfac[e, s] * (1 - engine.SELL_COST)
        if d in by_e and d <= oos_end:
            for r in by_e[d].itertuples():
                if len(hold) >= slots:
                    break
                amt = min(eq * w, cash)
                if amt <= eq * 0.005:
                    continue
                sh = amt / (sim.o[d, r.s] * (1 + engine.BUY_COST))
                cash -= amt
                hold[r.Index] = (r.s, r.e, r.x, sh, bool(r.gone))
                taken += 1
        val = 0.0
        for s, e, x, sh, gone in hold.values():
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
    yrs = len(cv) / 245
    return {'cagr': float(cv.iloc[-1] ** (1 / yrs) - 1), 'mdd': float((cv / cv.cummax() - 1).min()),
            'exposure': float(np.mean(expo)), 'taken': taken,
            'yearly': {y: float(g.iloc[-1] / g.iloc[0] - 1) for y, g in cv.groupby(cv.index.str[:4])}}


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
