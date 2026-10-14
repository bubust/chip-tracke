"""PLAN-B72 研究：停損 8%／停利 25%（盤中觸價、不限天數，上限 250 交易日）
C  全部做多策略 5 年回測（訊號＝網站現在的 screen 函式，sig_all.csv.gz）→ research/best2/results/fixed825.json
E2 研究候選放寬股票池（均量 500 → 300 張，同一出場 +1ATR／−2ATR、20 天）
E3 研究候選改用 8%/25% 出場 vs 原本
用法：python run825.py <data_dir> <sig_all.csv.gz> <sig_band.csv.gz> [c|e|all]
交易規則：訊號隔天開盤買（開盤一價漲停買不到不算）；停損＝買價×0.92、停利＝買價×1.25，盤中碰到就算（開盤跳空越過用開盤價，
進場當天開盤不算跳空）；同一天兩個都碰到算停損；沒碰到：250 天後開盤賣；資料結束還抱著＝最後收盤（標 open）；
持有中下市／停止交易＝最後一個成交日收盤（標 gone）；同一檔持有中不重複進場；成本 買 0.2425%、賣 0.5425%；含除權息。"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research', 'best')); sys.path.insert(0, os.path.join(ROOT, 'research', 'best2'))
import numpy as np
import pandas as pd
import engine
import run
from engine2 import Sim2

STP, TGT, CAP = 0.08, 0.25, 250
SEED = 20261014
OUT_JSON = os.path.join(ROOT, 'research', 'best2', 'results', 'fixed825.json')
OUT_E = os.path.join(HERE, 'best_retest.json')
REASONS = {1: 'tp', 2: 'sl', 3: 'cap', 4: 'open', 5: 'gone'}
ADOPT_E2 = {'new_oos_win': 0.70, 'new_oos_mean': 0.0, 'new_oos_pf': 1.3, 'combined_win_drop': 0.03}
ADOPT_E3 = {'mean_ge_orig': True, 'cagr_ge_orig': True, 'mdd_worse_max': 0.05}


class Sim825(Sim2):
    def exits825(self, t, s, e, stp=STP, tgt=TGT, M=CAP):
        n = len(e)
        ent = self.o[e, s]
        stop, tp = ent * (1 - stp), ent * (1 + tgt)
        x = np.full(n, -1, np.int64)
        px = np.full(n, np.nan)
        why = np.zeros(n, np.int8)
        done = np.zeros(n, bool)
        last_valid = np.full(n, -1, np.int64)
        for k in range(M):
            j = e + k
            alive = ~done & (j < self.T)
            if not alive.any():
                break
            jj = np.minimum(j, self.T - 1)
            oj, hj, lj, cj = self.o[jj, s], self.h[jj, s], self.l[jj, s], self.c[jj, s]
            fin = alive & np.isfinite(cj) & np.isfinite(lj) & np.isfinite(hj) & np.isfinite(oj)
            last_valid = np.where(fin, jj, last_valid)
            with np.errstate(invalid='ignore'):
                gap_sl = fin & (k > 0) & (oj <= stop)
                touch_sl = fin & ~gap_sl & (lj <= stop)
                sl = gap_sl | touch_sl
                gap_tp = fin & ~sl & (k > 0) & (oj >= tp)
                touch_tp = fin & ~sl & ~gap_tp & (hj >= tp)
                tq = gap_tp | touch_tp
            px = np.where(gap_sl, oj, np.where(touch_sl, stop, np.where(gap_tp, oj, np.where(touch_tp, tp, px))))
            hit = sl | tq
            x = np.where(hit, jj, x)
            why = np.where(sl, 2, np.where(tq, 1, why))
            done |= hit
        lv = np.where(last_valid >= 0, last_valid, e)
        nothit = ~done
        cap = e + M
        # 上限天數到了：第 e+M 天開盤賣（那天沒開盤＝往後找第一個有開盤的）
        capped = nothit & (cap < self.T)
        for i in np.nonzero(capped)[0]:
            j = cap[i]
            while j < self.T and not np.isfinite(self.o[j, s[i]]):
                j += 1
            if j < self.T:
                x[i], px[i], why[i] = j, self.o[j, s[i]], 3
            else:
                capped[i] = False
        rest = nothit & ~capped
        gone = rest & (lv < self.last_idx_all - 0)              # 最後成交日比整體資料早很多 → 下市／停止交易
        x = np.where(rest, lv, x)
        px = np.where(rest, self.c[lv, s], px)
        why = np.where(rest & gone, 5, np.where(rest, 4, why))
        return x, px, why

    def trades825(self, sig, stp=STP, tgt=TGT, M=CAP):
        t, s, e = self.entries(sig)
        if len(t) == 0:
            return pd.DataFrame(columns=['t', 's', 'e', 'x', 'ret', 'days', 'date', 'px_out', 'why', 'gone'])
        x, px, why = self.exits825(t, s, e, stp, tgt, M)
        ok = x >= e
        t, s, e, x, px, why = t[ok], s[ok], e[ok], x[ok], px[ok], why[ok]
        order = np.lexsort((e, s))
        t, s, e, x, px, why = t[order], s[order], e[order], x[order], px[order], why[order]
        keep = engine._non_overlap(s, e, x, self.T)
        t, s, e, x, px, why = t[keep], s[keep], e[keep], x[keep], px[keep], why[keep]
        div = self.cumfac[x, s] / self.cumfac[e, s]
        net = px / self.o[e, s] * div * (1 - engine.SELL_COST) / (1 + engine.BUY_COST) - 1
        return pd.DataFrame({'t': t, 's': s, 'e': e, 'x': x, 'ret': net, 'days': x - e, 'date': self.dates[t],
                             'px_out': px, 'why': why, 'gone': why >= 4})


def with_px_out(sim, tr):
    """base Sim.trades 的交易表補 px_out（gone＝收盤出場，否則 x 開盤）"""
    tr = tr.copy()
    if len(tr):
        tr['px_out'] = np.where(tr['gone'], sim.c[tr['x'], tr['s']], sim.o[tr['x'], tr['s']])
    return tr


def port(sim, tr, strength, start, end, slots=10):
    """10 個名額、每筆＝淨值 ÷ 10；開盤先賣（用交易自己的出場價 px_out）再買（同一天依強度排序）；收盤算淨值（含除權息）"""
    tr = tr.copy()
    tr['str'] = strength[tr['t'].to_numpy(), tr['s'].to_numpy()] if len(tr) else []
    by_e = {e: g.sort_values('str', ascending=False) for e, g in tr.groupby('e')}
    d0 = int(np.searchsorted(sim.dates, start))
    d1 = min(int(np.searchsorted(sim.dates, end, side='right')), sim.T)
    cash, eq, hold, curve, expo, taken, lastpx = 1.0, 1.0, {}, [], [], 0, {}

    def sell(when):
        nonlocal cash
        for k in [k for k, hd in hold.items() if hd[2] <= d and hd[5] == when]:
            s, e, x, sh, pxo, _ = hold.pop(k)
            cash += sh * pxo * sim.cumfac[x, s] / sim.cumfac[e, s] * (1 - engine.SELL_COST)
    for d in range(d0, d1):
        sell('open')                                     # 開盤賣（到期、收盤條件隔天開盤賣）
        for r in (by_e[d].itertuples() if d in by_e else []):
            if len(hold) >= slots:
                break
            amt = min(eq / slots, cash)
            if amt <= eq * 0.005:
                continue
            sh = amt / (sim.o[d, r.s] * (1 + engine.BUY_COST))
            cash -= amt
            hold[r.Index] = (r.s, r.e, r.x, sh, r.px_out, 'intraday' if r.why in (1, 2) else 'open' if r.why in (0, 3) else 'close')
            taken += 1
        sell('intraday')                                 # 盤中停損／停利（含進場當天就碰到）
        sell('close')                                    # 資料結束／下市：最後收盤
        val = 0.0
        for s, e, x, sh, _, _ in hold.values():
            p = sim.c[d, s]
            if np.isfinite(p):
                lastpx[(s, e)] = p
            else:
                p = lastpx.get((s, e), sim.o[e, s])
            val += sh * p * sim.cumfac[d, s] / sim.cumfac[e, s]
        eq = cash + val
        curve.append(eq)
        expo.append(val / eq if eq > 0 else 0)
    cv = pd.Series(curve)
    yrs = len(cv) / 245
    return {'cagr': float(cv.iloc[-1] ** (1 / yrs) - 1) if yrs > 0 else 0.0, 'mdd': float((cv / cv.cummax() - 1).min()),
            'exposure': float(np.mean(expo)), 'taken': taken, 'final': float(cv.iloc[-1])}


def split(tr, IS, OOS, years):
    d = tr['date'].to_numpy().astype(str)
    r, dy = tr['ret'].to_numpy(float), tr['days'].to_numpy(float)
    out = {}
    for name, (a, b) in (('is', IS), ('oos', OOS)):
        m = (d >= a) & (d <= b)
        out[name] = engine.stats(r[m], dy[m])
    allm = d <= OOS[1]
    out['all'] = engine.stats(r[allm], dy[allm])
    out['years'] = {y: engine.stats(r[allm & (d >= y + '0101') & (d <= y + '1231')]) for y in years}
    if 'why' in tr:
        w = tr['why'].to_numpy()[allm]
        out['reasons'] = {REASONS[k]: float((w == k).mean()) if len(w) else 0.0 for k in REASONS}
    return out


def random_825(sim, pool, sig, OOS, reps=20, seed=SEED, trades_fn=None):
    """同出場、隨機挑股票池裡的（股票, 日子）；每個月抽的筆數＝這個方法 OOS 那個月的訊號數"""
    rng = np.random.default_rng(seed)
    month = np.array([d[:6] for d in sim.dates])
    oos = (sim.dates >= OOS[0]) & (sim.dates <= OOS[1])
    cnt = pd.Series(month[np.nonzero(sig & oos[:, None])[0]]).value_counts()
    cells = {mo: np.argwhere(pool & (month == mo)[:, None]) for mo in cnt.index}
    res = []
    for _ in range(reps):
        m = np.zeros(sig.shape, bool)
        for mo, k in cnt.items():
            cl = cells[mo]
            if len(cl):
                pick = cl[rng.choice(len(cl), size=min(k, len(cl)), replace=False)]
                m[pick[:, 0], pick[:, 1]] = True
        tr = (trades_fn or sim.trades825)(m)
        res.append(engine.stats(tr['ret'].to_numpy(float)))
    ok = [r for r in res if r.get('n')]
    return {'win': float(np.mean([r['win'] for r in ok])) if ok else None,
            'mean': float(np.mean([r['mean'] for r in ok])) if ok else None, 'reps': reps}


def masks(sim, sig_path, pool):
    a = pd.read_csv(sig_path, dtype={'date': str, 'stock_id': str})
    di = {d: i for i, d in enumerate(sim.dates)}
    si = {s: i for i, s in enumerate(sim.sids)}
    a = a[a.date.isin(di) & a.stock_id.isin(si)]
    out = {}
    for k, g in a.groupby('strategy'):
        m = np.zeros((sim.T, sim.S), bool)
        m[g.date.map(di).to_numpy(), g.stock_id.map(si).to_numpy()] = True
        out[k] = m & pool
    return out


def taiex(P, start, end):
    tx = P['taiex']
    tx = tx[(tx.index >= start) & (tx.index <= end)]
    cv = tx / tx.iloc[0]
    yrs = len(cv) / 245
    return {'cagr': float(cv.iloc[-1] ** (1 / yrs) - 1), 'mdd': float((cv / cv.cummax() - 1).min())}


def load(data_dir):
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, data_dir)
    sim = Sim825(P, F, fac)
    fin = np.isfinite(sim.c)
    sim.last_idx_all = sim.T - 1 - 5                     # 最後 5 個交易日內還有成交＝還在交易（不是下市）
    return P, F, sim


def stage_c(P, F, sim, sig_path):
    from scanner import STRATEGIES
    last = str(sim.dates[-2])                          # 最後一天的訊號沒有隔天開盤
    IS, OOS = run.IS, ('20240701', last)
    years = ('2022', '2023', '2024', '2025', '2026')
    pool = F['liquid'].to_numpy() & (sim.dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    M = masks(sim, sig_path, pool)
    strength = np.nan_to_num(sim.c * P['volume'].to_numpy(float))       # 成交金額大的先
    out = {}
    t0 = time.time()
    for k, m in sorted(M.items()):
        tr = sim.trades825(m)
        ss = split(tr, IS, OOS, years)
        pf = port(sim, tr, strength, engine.TRADE_FROM, last)
        rb = random_825(sim, pool, m, OOS)
        o = ss['oos']
        out[k] = {'label': STRATEGIES.get(k, k), **{p: ss[p] for p in ('is', 'oos', 'all', 'years', 'reasons')},
                  'port': pf, 'random': rb,
                  'beats_random': bool(o.get('n') and rb['mean'] is not None and o['mean'] > rb['mean'] and o['win'] > rb['win']),
                  'open_n': int((tr['why'] == 4).sum())}
        print(f'{k}: n={ss["all"].get("n")} oos win={o.get("win")} mean={o.get("mean")} port={pf["cagr"]:.3f}/{pf["mdd"]:.3f} '
              f'rand={rb["mean"]} {time.time() - t0:.0f}s', flush=True)
    meta = {'exit': '停損 8%／停利 25%（盤中觸價、跳空用開盤價、同一天都碰到算停損）、不限天數（上限 250 交易日）',
            'entry': '訊號隔天開盤買（開盤一價漲停買不到不算）', 'cost': '買 0.2425%、賣 0.5425%（含手續費、證交稅、每邊 0.1% 滑價）',
            'pool': '4 碼普通股、收盤 ≥ 10、20 日均量 ≥ 500 張、≥ 120 根；60 天內有 >10.5% 跳動（除權息／減資）不算',
            'periods': {'is': IS, 'oos': OOS}, 'port': '最多 10 檔各 10%、同一天訊號多時成交金額大的先',
            'random': '同股票池、同月份筆數、同出場，20 次平均', 'taiex': taiex(P, engine.TRADE_FROM, last),
            'data_end': str(sim.dates[-1]), 'generated': time.strftime('%Y-%m-%d %H:%M')}
    json.dump({'meta': meta, 'strategies': out}, open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    return out


def vol_ratio_ok(P, k=2.0):
    """訊號當天成交量 ≥ 前一個交易日 × k（停牌日不算一天；前一天量 0 不算）"""
    v = P['volume']
    prev = engine.per_stock(v, lambda s: s.shift(1))
    with np.errstate(invalid='ignore', divide='ignore'):
        return ((v >= prev * k) & (prev > 0)).to_numpy()


def stage_v(P, F, sim, sig_path, k=2.0):
    """PLAN-B72 追加（10-14 用戶）：進場前加「訊號當天量 ≥ 前一天 2 倍」，跟不加比；結果併進 fixed825.json 的 vol2"""
    last = str(sim.dates[-2])
    IS, OOS = run.IS, ('20240701', last)
    years = ('2022', '2023', '2024', '2025', '2026')
    pool = F['liquid'].to_numpy() & (sim.dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    vx = vol_ratio_ok(P, k)
    poolv = pool & vx
    M = masks(sim, sig_path, pool)
    strength = np.nan_to_num(sim.c * P['volume'].to_numpy(float))
    J = json.load(open(OUT_JSON, encoding='utf-8'))
    t0 = time.time()
    for key, m in sorted(M.items()):
        mv = m & vx
        tr = sim.trades825(mv)
        ss = split(tr, IS, OOS, years)
        pf = port(sim, tr, strength, engine.TRADE_FROM, last)
        rb = random_825(sim, poolv, mv, OOS) if mv.any() else {'win': None, 'mean': None, 'reps': 0}
        o = ss['oos']
        base = J['strategies'].get(key, {}).get('oos', {})
        J['strategies'].setdefault(key, {})['vol2'] = {
            **{p: ss[p] for p in ('is', 'oos', 'all', 'years', 'reasons')}, 'port': pf, 'random': rb,
            'kept': float(mv.sum() / m.sum()) if m.sum() else None,
            'beats_random': bool(o.get('n') and rb['mean'] is not None and o['mean'] > rb['mean'] and o['win'] > rb['win']),
            'better_than_plain': bool(o.get('n') and base.get('n') and o['mean'] > base['mean'])}
        print(f'{key}: kept={mv.sum()}/{m.sum()} oos n={o.get("n")} win={o.get("win")} mean={o.get("mean")} '
              f'(plain {base.get("mean")}) rand={rb["mean"]} port={pf["cagr"]:.3f}/{pf["mdd"]:.3f} {time.time() - t0:.0f}s', flush=True)
    J['meta']['vol2'] = (f'訊號當天成交量 ≥ 前一個交易日 × {k:g}（訊號當天收盤就知道，隔天開盤買；進場那天的量要收盤才知道，不能用）；'
                         f'隨機進場也只從「當天量 ≥ 前一天 {k:g} 倍」的股票日裡抽')
    json.dump(J, open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)


def _c1(Mx, My):
    w = lambda m: m | np.r_[np.zeros((1, m.shape[1]), bool), m[:-1]] | np.r_[np.zeros((2, m.shape[1]), bool), m[:-2]]
    return (Mx & w(My)) | (My & w(Mx))


def stage_e(P, F, sim, sig_path, band_path):
    IS, OOS = run.IS, run.OOS                          # 跟原本研究同一個期間（2021-10～2024-06／2024-07～2026-08）
    years = ('2022', '2023', '2024', '2025', '2026')
    dates_ok = (sim.dates >= engine.TRADE_FROM)[:, None]
    c = sim.c
    gap = F['gap60'].to_numpy()
    liq500 = F['liquid'].to_numpy()
    liq300 = ((P['close'] >= 10) & (F['vol20'] >= 300) & (F['bars'] >= 120) & P['close'].notna()).to_numpy()
    band = liq300 & ~liq500
    everything = liq300 & dates_ok
    A = masks(sim, sig_path, everything)
    B = masks(sim, band_path, everything)
    Mx = A.get('S_BIAS', 0) | B.get('S_BIAS', 0)
    My = A.get('S_BREAKBOTTOM', 0) | B.get('S_BREAKBOTTOM', 0)
    sig = _c1(Mx, My)
    pool500 = liq500 & dates_ok & ~gap
    pool300 = liq300 & dates_ok & ~gap
    rule = run.exit_rules()['E3_t1_s2_20d']
    with np.errstate(invalid='ignore', divide='ignore'):
        vr = np.nan_to_num(P['volume'].to_numpy(float) / F['vol20p'].to_numpy(float))       # 原研究的強度（量比）
    res = {'adopt_rules': {'E2': ADOPT_E2, 'E3': ADOPT_E3}, 'periods': {'is': IS, 'oos': OOS}}
    # 原本（股票池 500）
    m500 = sig & pool500
    tr0 = with_px_out(sim, sim.trades(m500, rule))
    tr0['why'] = 0
    s0 = split(tr0, IS, OOS, years)
    p0 = port(sim, tr0, vr, engine.TRADE_FROM, OOS[1])
    r0 = run.random_baseline(sim, pool500, m500, rule)
    res['orig'] = {'n_sig': int(m500.sum()), **{k: s0[k] for k in ('is', 'oos', 'all', 'years')}, 'port': p0, 'random': r0}
    print('orig', s0['oos'], p0, flush=True)
    # E2：股票池 300（同出場）
    m300 = sig & pool300
    tr2 = with_px_out(sim, sim.trades(m300, rule))
    tr2['why'] = 0
    s2 = split(tr2, IS, OOS, years)
    newm = band[tr2['t'].to_numpy(), tr2['s'].to_numpy()] if len(tr2) else np.zeros(0, bool)
    sn = split(tr2[newm], IS, OOS, years)
    p2 = port(sim, tr2, vr, engine.TRADE_FROM, OOS[1])
    no, co = sn['oos'], s2['oos']
    adopt2 = bool(no.get('n') and no['win'] >= ADOPT_E2['new_oos_win'] and no['mean'] > ADOPT_E2['new_oos_mean']
                  and no['pf'] >= ADOPT_E2['new_oos_pf'] and co['win'] >= s0['oos']['win'] - ADOPT_E2['combined_win_drop'])
    res['e2'] = {'combined': {k: s2[k] for k in ('is', 'oos', 'all', 'years')}, 'new_only': {k: sn[k] for k in ('is', 'oos', 'all')},
                 'port': p2, 'adopt': adopt2, 'n_sig': int(m300.sum())}
    print('e2 new', no, 'combined', co, 'adopt', adopt2, flush=True)
    # E3：8%/25%（原本股票池）
    tr3 = sim.trades825(m500)
    s3 = split(tr3, IS, OOS, years)
    p3 = port(sim, tr3, vr, engine.TRADE_FROM, OOS[1])
    r3 = random_825(sim, pool500, m500, OOS)
    adopt3 = bool(s3['oos'].get('n') and s3['oos']['mean'] >= s0['oos']['mean'] and p3['cagr'] >= p0['cagr']
                  and p3['mdd'] >= p0['mdd'] - ADOPT_E3['mdd_worse_max'])
    res['e3'] = {**{k: s3[k] for k in ('is', 'oos', 'all', 'years', 'reasons')}, 'port': p3, 'random': r3, 'adopt': adopt3}
    print('e3', s3['oos'], p3, 'adopt', adopt3, flush=True)
    res['taiex'] = taiex(P, engine.TRADE_FROM, OOS[1])
    res['generated'] = time.strftime('%Y-%m-%d %H:%M')
    json.dump(res, open(OUT_E, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    return res


def check_vs_site(P, sim, sig_path, key='S_FBD', n=25, seed=1):
    """研究版 8/25 出場 vs 網站 backtest_engine.simulate：同一筆進場，出場日／出場價要一樣"""
    from backtest_engine import simulate, ExitConfig, CostConfig
    pool = np.ones((sim.T, sim.S), bool)
    m = masks(sim, sig_path, pool)[key]
    tr = sim.trades825(m)
    tr = tr[tr['why'].isin([1, 2])]
    rng = np.random.default_rng(seed)
    pick = tr.iloc[rng.choice(len(tr), size=min(n, len(tr)), replace=False)]
    ec = ExitConfig(stop='pct', stop_pct=8, trail='none', max_hold=0, take_profit=25, entry='next_open')
    bad = []
    for r in pick.itertuples():
        sid = sim.sids[r.s]
        ok = np.isfinite(sim.c[:, r.s])
        idx = np.nonzero(ok)[0]
        df = pd.DataFrame({'date': sim.dates[idx], 'open': sim.o[idx, r.s], 'high': sim.h[idx, r.s], 'low': sim.l[idx, r.s],
                           'close': sim.c[idx, r.s]})
        mask = np.zeros(len(idx), bool)
        mask[np.searchsorted(idx, r.t)] = True
        closed, _, _ = simulate(df, mask, 'long', ec, CostConfig())
        if not closed:
            bad.append((sid, sim.dates[r.t], 'site: no trade'))
            continue
        c0 = closed[0]
        same = c0['exit_date'] == sim.dates[r.x] and abs(c0['exit_price'] - r.px_out) <= max(0.011, r.px_out * 1e-6)
        if not same:
            bad.append((sid, sim.dates[r.t], c0['exit_date'], c0['exit_price'], sim.dates[r.x], float(r.px_out)))
    print(f'check_vs_site {key}: {len(pick)} 筆，不一致 {len(bad)}', bad[:10], flush=True)
    return len(pick), bad


if __name__ == '__main__':
    data, sig_all, sig_band = sys.argv[1:4]
    stage = sys.argv[4] if len(sys.argv) > 4 else 'all'
    P, F, sim = load(data)
    if stage in ('check', 'all'):
        check_vs_site(P, sim, sig_all)
    if stage in ('c', 'all'):
        stage_c(P, F, sim, sig_all)
    if stage in ('e', 'all'):
        stage_e(P, F, sim, sig_all, sig_band)
    if stage in ('v', 'all'):
        stage_v(P, F, sim, sig_all)
