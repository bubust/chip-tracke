"""PLAN-COURSE 研究主程式（講義策略 1～11）。
用法：python run_course.py <best_data_dir> <course_data_dir> [stage ...]
  stage：sigs（逐檔算全部參數組的訊號，存 signals.pkl）、long（1/2/3/5 做多）、short（6 跌破前低放空）、
         limit（4 漲停打開）、dist（7 出貨日）、disp（8 二次處置）、sector（9 族群大跌）、market（10 大盤出貨日）、
         daytrade（11 當沖名單）、all
資料：<best_data_dir>＝PLAN-BEST 的 5 年官方日行情（含下市）＋除權息事件表；<course_data_dir>＝revenue.csv、mi5.csv、stock_futures.csv。
交易規則、樣本內外、成本跟 PLAN-BEST／BEST2 一樣（research/best/engine.py、research/best2/engine2.py）。
輸出：research/course/results/*.json、*.csv（report_course.py 再寫成 REPORT.md）"""
import json, os, pickle, sys, time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT, 'research', 'best'), os.path.join(ROOT, 'research', 'best2'), HERE):
    sys.path.insert(0, p)
import numpy as np
import pandas as pd
import engine, run, engine2, run2          # noqa: E402
from engine import per_stock, _non_overlap  # noqa: E402
from engine2 import Sim2                    # noqa: E402
import course2 as C                         # noqa: E402

OUT = os.path.join(HERE, 'results')
IS, OOS, YEARS = run.IS, run.OOS, run.YEARS
SEED = 20261009
BORROW = 0.0008                                    # 融券手續費（借券費）0.08%
DT_COST = 0.001425 * 2 + 0.0015 + 0.0005 * 2      # 當沖：手續費兩邊＋當沖稅 0.15%＋滑價每邊 0.05%


# ── 參數組 ───────────────────────────────────────────────────────────────────
def variants():
    V = {}
    for k in (3, 8):
        for vm in (0, 1.5):
            for pull in (0.05, 0.10):
                for ra in (0, 0.2):
                    V[f'NB_k{k}_v{vm}_p{pull}_r{ra}'] = ('sig_abreak', dict(k=k, vmult=vm, pull=pull, rally=ra))
    for m1 in (2.5, 4):
        for w in (0.12, 0.2):
            for s in (0.5, 0.7):
                for m2 in (1.5, 2):
                    V[f'BR_m{m1}_w{w}_s{s}_v{m2}'] = ('sig_bottom_rise', dict(m1=m1, width=w, shrink=s, m2=m2))
    for k in (3, 5):
        for nl in (2, 3):
            for tr in ('confirm', 'break'):
                V[f'ST_k{k}_n{nl}_{tr}'] = ('sig_strong', dict(k=k, nlow=nl, trigger=tr))
    for ra in (0.2, 0.3):
        for z in C.FIB:
            for tr in ('red', 'red_hi'):
                V[f'FB_r{ra}_z{z}_{tr}'] = ('sig_fib', dict(rally=ra, zone=z, trig=tr))
    for k in (3, 8):
        for vm in (0, 1.5):
            V[f'DB_k{k}_v{vm}'] = ('sig_dbreak', dict(k=k, vmult=vm))
    for n in (2, 3):
        for m in (3, 5):
            for op in ('close', 'touch'):
                V[f'LO_n{n}_m{m}_{op}'] = ('sig_limit_open', dict(n=n, m=m, opened=op))
    V['DI'] = ('sig_distribution', {})
    return V


# ── 訊號（逐檔整段算）────────────────────────────────────────────────────────
_V = {}


def _init_sig():
    _V.update(variants())


def _sig_one(task):
    col, rows, o, h, l, c, v = task
    out = {}
    for name, (fn, kw) in _V.items():
        try:
            r = getattr(C, fn)(o, h, l, c, v, **kw)
        except Exception as e:                        # 一檔失敗不影響其他
            print('ERR', name, col, e, flush=True)
            continue
        if fn == 'sig_distribution':
            sig, info = r > 0, r.astype(float)
        else:
            sig, d = r
            info = d.get('stop', np.full(len(c), np.nan))
        k = np.nonzero(sig)[0]
        if len(k):
            out[name] = (rows[k].astype(np.int32), np.asarray(info, float)[k].astype(np.float32))
    return col, out


def compute_sigs(P, path, procs=5):
    cols = P['close'].columns
    A = {k: P[k].to_numpy(float) for k in ('open', 'high', 'low', 'close', 'volume')}
    tasks = []
    for j in range(len(cols)):
        ok = np.isfinite(A['close'][:, j])
        if ok.sum() < 130:
            continue
        rows = np.nonzero(ok)[0]
        tasks.append((j, rows, *(A[k][ok, j] for k in ('open', 'high', 'low', 'close', 'volume'))))
    res = {}
    t0 = time.time()
    with Pool(procs, initializer=_init_sig) as pool:
        for n, (col, out) in enumerate(pool.imap_unordered(_sig_one, tasks, chunksize=8), 1):
            for name, (t, info) in out.items():
                res.setdefault(name, []).append((t, np.full(len(t), col, np.int32), info))
            if n % 300 == 0:
                print(f'  sigs {n}/{len(tasks)} {time.time() - t0:.0f}s', flush=True)
    sigs = {k: tuple(np.concatenate([x[i] for x in v]) for i in range(3)) for k, v in res.items()}
    pickle.dump(sigs, open(path, 'wb'))
    print('sigs', {k: len(v[0]) for k, v in sigs.items()}, flush=True)
    return sigs


def dense(sp, shape, info=False):
    m = np.zeros(shape, np.float32 if info else bool)
    if info:
        m[:] = np.nan
        m[sp[0], sp[1]] = sp[2]
    else:
        m[sp[0], sp[1]] = True
    return m


def load_sig_a(P, best_dir, keys):
    work = os.path.dirname(os.path.abspath(best_dir))
    a = pd.read_csv(os.path.join(work, 'sig_a.csv.gz'), dtype={'date': str, 'stock_id': str})
    a = a[a.strategy.isin(keys)]
    di = {d: i for i, d in enumerate(P['close'].index)}
    si = {s: i for i, s in enumerate(P['close'].columns)}
    out = {}
    for k, g in a.groupby('strategy'):
        m = np.zeros(P['close'].shape, bool)
        t, s = g.date.map(di), g.stock_id.map(si)
        ok = t.notna() & s.notna()
        m[t[ok].astype(int).to_numpy(), s[ok].astype(int).to_numpy()] = True
        out[k] = m
    return out


# ── 模擬：結構停損（訊號給的停損價）＋放空 ───────────────────────────────────
class SimC(Sim2):
    stop_mat = None                                   # 結構停損：T×S，訊號那天的停損價

    def exits2(self, t, s, e, rule):
        if rule['kind'] != 'struct':
            return super().exits2(t, s, e, rule)
        stop = self.stop_mat[t, s].astype(float)
        M = rule['max']
        n = len(e)
        x = np.full(n, -1, np.int64)
        done = np.zeros(n, bool)
        last_valid = np.full(n, -1, np.int64)
        for k in range(M):
            j = e + k
            alive = ~done & (j < self.T)
            if not alive.any():
                break
            jj = np.minimum(j, self.T - 1)
            cj = self.c[jj, s]
            fin = alive & np.isfinite(cj)
            last_valid = np.where(fin, jj, last_valid)
            with np.errstate(invalid='ignore'):
                hit = fin & (cj < stop)
            x = np.where(hit, jj + 1, x)
            done |= hit
        cap = e + M
        nothit = ~done
        x = np.where(nothit & (cap < self.T), cap, x)
        is_open = (nothit & (cap >= self.T)) | (done & (x >= self.T))
        lv = np.where(last_valid >= 0, last_valid, e)
        px = np.full(n, np.nan)
        x = np.where(is_open, lv, x)
        px = np.where(is_open, self.c[lv, s], px)
        bad = np.nonzero(~is_open & ~np.isfinite(self.o[np.minimum(x, self.T - 1), s]))[0]
        for i in bad:
            j = x[i]
            while j < self.T and not np.isfinite(self.o[j, s[i]]):
                j += 1
            if j < self.T:
                x[i] = j
            else:
                x[i] = lv[i]; px[i] = self.c[lv[i], s[i]]; is_open[i] = True
        return x, px, is_open

    # 放空：t 收盤訊號 → t+1 開盤賣出（一價跌停空不到不算）；回補用開盤（觸發隔天）
    def short_trades(self, sig, rule, ma=None):
        sig = sig.copy()
        M = rule['max']
        sig[max(0, self.trade_to - M - 1):] = False
        t, s = np.nonzero(sig[:-1])
        e = t + 1
        o_e = self.o[e, s]
        ok = np.isfinite(o_e) & (o_e > 0)
        with np.errstate(invalid='ignore'):
            ok &= ~((o_e <= self.c[t, s] * 0.905) & (o_e == self.h[e, s]) & (o_e == self.l[e, s]))
        t, s, e = t[ok], s[ok], e[ok]
        if len(t) == 0:
            return engine2._empty2()
        ent = self.o[e, s]
        hitday = np.full(len(e), self.T)
        if rule['kind'] != 'time':
            for k in range(M):
                j = e + k
                jj = np.minimum(j, self.T - 1)
                cj = self.c[jj, s]
                with np.errstate(invalid='ignore'):
                    if rule['kind'] == 'stop':
                        h_ = cj > ent * (1 + rule['stp'])
                    else:
                        h_ = cj > ma[jj, s]
                h_ &= (j < self.T) & (hitday == self.T)
                hitday = np.where(h_, j, hitday)
        cap = e + M
        x = np.where(hitday < cap, hitday + 1, cap).astype(np.int64)
        x = np.minimum(x, self.T)
        bad = np.nonzero((x < self.T) & ~np.isfinite(self.o[np.minimum(x, self.T - 1), s]))[0]
        for i in bad:
            j = x[i]
            while j < self.T and not np.isfinite(self.o[j, s[i]]):
                j += 1
            x[i] = j
        keep = x < self.T                                 # 資料內回補不了（下市）：去掉（放空遇下市其實是賺，保守不算）
        t, s, e, x = t[keep], s[keep], e[keep], x[keep]
        order = np.lexsort((e, s))
        t, s, e, x = t[order], s[order], e[order], x[order]
        kk = _non_overlap(s, e, x, self.T)
        t, s, e, x = t[kk], s[kk], e[kk], x[kk]
        px_in, px_out = self.o[e, s], self.o[x, s]
        div = self.cumfac[x, s] / self.cumfac[e, s]       # 放空期間除權息：要賠股利（等於回補價乘回去）
        net = (1 - engine.SELL_COST) - px_out * div / px_in * (1 + engine.BUY_COST) - BORROW
        return pd.DataFrame({'t': t, 's': s, 'e': e, 'x': x, 'ret': net, 'days': x - e, 'date': self.dates[t],
                             'open': np.zeros(len(t), bool), 'gone': np.zeros(len(t), bool), 'px_out': px_out})


def load(best_dir):
    t0 = time.time()
    P = engine.load_panel(best_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, best_dir)
    sim = SimC(P, F, fac)
    dates = np.array(P['close'].index)
    pool = F['liquid'].to_numpy() & (dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    lite = (P['close'].to_numpy(float) >= 10) & (F['bars'].to_numpy() >= 120) & (dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    print(f'load {time.time() - t0:.0f}s', flush=True)
    return P, F, fac, sim, pool, lite


def _struct_rule(sim, tr):
    if not len(tr):
        return {'kind': 'pct', 'stp': 0.08, 'tgt': None, 'max': 60}
    ent = sim.o[tr['e'].to_numpy(), tr['s'].to_numpy()]
    dist = 1 - sim.stop_mat[tr['t'].to_numpy(), tr['s'].to_numpy()] / ent
    d = float(np.nanmedian(dist)) if np.isfinite(dist).any() else 0.08
    return {'kind': 'pct', 'stp': min(max(d, 0.02), 0.3), 'tgt': None, 'max': 60}


def long_exits():
    R = {}
    for n in (5, 10, 20, 40):
        R[f'E1_{n}d'] = {'kind': 'time', 'n': n}
    R['E2_ma5rsi_10d'] = {'kind': 'ma5', 'max': 10}
    for tg in (1.5, 2, 3):
        for sp in (2, 3):
            R[f'E3_t{tg}_s{sp}_40d'] = {'kind': 'atr', 'tgt': tg, 'stp': sp, 'max': 40}
    R['E4_ma20'] = {'kind': 'ma20', 'max': 60}
    for sp in (7, 10):
        for tg in (None, 20):
            R[f'E6_s{sp}_t{tg or 0}_60d'] = {'kind': 'pct', 'stp': sp / 100, 'tgt': tg / 100 if tg else None, 'max': 60}
    for sp in (10, 15, 20):
        R[f'E7c_s{sp}'] = {'kind': 'hold', 'stp': sp / 100, 'mode': 'close', 'max': engine2.E7_CAP}
    R['S_struct60'] = {'kind': 'struct', 'max': 60}
    return R


def _js(o):
    return run2._js(o)


def _save(name, obj):
    os.makedirs(OUT, exist_ok=True)
    json.dump(obj, open(os.path.join(OUT, name), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=_js)


def _filters(P, F, short=False):
    tx = P['taiex'].to_numpy(float)
    c = P['close'].to_numpy(float)
    m60 = F['ma60'].to_numpy(float)
    txm = F['tx_ma60'].to_numpy(float)
    with np.errstate(invalid='ignore'):
        if short:
            return {'none': None, 'c60dn': c < m60, 'tx60dn': (tx < txm)[:, None]}
        return {'none': None, 'tx60': (tx > txm)[:, None], 'c60': c > m60}


def _rand_trades(sim, pool, sig, rule, reps=20, short=False, ma=None):
    """隨機基準：同出場、同月份筆數、股票池隨機挑；回傳 (平均統計, 全部隨機交易合併)"""
    res, alltr = [], []
    for m in run2._rand_masks(sim, pool, sig, reps, SEED):
        tr = sim.short_trades(m, rule, ma) if short else sim.trades2(m, rule)
        tr = tr[(tr['date'].astype(str) >= OOS[0]) & (tr['date'].astype(str) <= OOS[1])]
        if len(tr):
            res.append(engine.stats(tr['ret'].to_numpy()))
            alltr.append(tr)
    if not res:
        return None, None
    st = {'win': float(np.mean([r['win'] for r in res])), 'mean': float(np.mean([r['mean'] for r in res])), 'reps': reps}
    return st, pd.concat(alltr, ignore_index=True)


def rand_month_table(sim, cellmask, rules, per_month=300, short=False, MA=None):
    """每個出場規則：股票池裡每個月隨機挑 per_month 格進場，算「每個月平均每筆報酬」→ {規則名: Series(月份 → 平均)}；
    用來算每個組合的「超額報酬」＝組合平均 − 同樣月份分布的隨機平均（扣掉大盤多空的影響，PLAN-COURSE-LOG 偏離紀錄）"""
    month = np.array([d[:6] for d in sim.dates])
    rng = np.random.default_rng(SEED)
    m = np.zeros(cellmask.shape, bool)
    for mo in np.unique(month):
        cl = np.argwhere(cellmask & (month == mo)[:, None])
        if len(cl):
            pick = cl[rng.choice(len(cl), min(per_month, len(cl)), replace=False)]
            m[pick[:, 0], pick[:, 1]] = True
    out = {}
    for ek, rule in rules.items():
        tr = sim.short_trades(m, rule, MA.get(rule.get('ma')) if MA else None) if short else sim.trades2(m, rule)
        out[ek] = tr.groupby(tr['date'].astype(str).str[:6])['ret'].mean() if len(tr) else pd.Series(dtype=float)
    return out


def _excess(tr, table):
    """組合的樣本內／樣本外 超額報酬＝平均 −（同月份隨機平均，依這組每個月的筆數加權）"""
    out = {}
    d = tr['date'].astype(str)
    for per, (a, b) in (('is', IS), ('oos', OOS)):
        m = ((d >= a) & (d <= b)).to_numpy()
        if not m.any():
            out[f'{per}_excess'] = None
            continue
        exp = table.reindex(d[m].str[:6]).to_numpy(float)
        r = tr['ret'].to_numpy()[m]
        ok = np.isfinite(exp)
        out[f'{per}_excess'] = float(r[ok].mean() - exp[ok].mean()) if ok.any() else None
    return out


def _boot_lo(tr_a, tr_b, q=2.5, reps=2000):
    """樣本外 平均每筆 a − b，依月份 bootstrap 的下限（q 百分位）"""
    d = lambda tr: tr[(tr['date'].astype(str) >= OOS[0]) & (tr['date'].astype(str) <= OOS[1])]
    A = {m: g['ret'].to_numpy() for m, g in d(tr_a).groupby(d(tr_a)['date'].astype(str).str[:6])}
    B = {m: g['ret'].to_numpy() for m, g in d(tr_b).groupby(d(tr_b)['date'].astype(str).str[:6])}
    months = sorted(set(A) | set(B))
    if not months:
        return None
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(reps):
        pick = rng.choice(months, len(months), replace=True)
        a = np.concatenate([A.get(m, np.array([])) for m in pick])
        b = np.concatenate([B.get(m, np.array([])) for m in pick])
        if len(a) and len(b):
            diffs.append(a.mean() - b.mean())
    return float(np.percentile(diffs, q)) if diffs else None


# ── 1/2/3/5 做多策略 ─────────────────────────────────────────────────────────
LONG = {
    'NB': {'title': '突破前高（a／A 點）＝N 字突破新版', 'orig': ['S_NBREAK']},
    'BR': {'title': '底部起漲（平地一聲雷新子型）', 'orig': ['S_THUNDER', 'S_VOLROLL']},
    'ST': {'title': '強勢股（高低點不重疊）', 'orig': []},
    'FB': {'title': '黃金切割回檔買', 'orig': []},
}


def stage_long(P, F, fac, sim, pool, sigs, best_dir, only=None):
    shape = (sim.T, sim.S)
    flt = _filters(P, F)
    exits = long_exits()
    orig = load_sig_a(P, best_dir, ['S_NBREAK', 'S_THUNDER', 'S_VOLROLL'])
    orig = {k: v & pool for k, v in orig.items()}
    summary = {}
    t0 = time.time()
    rtab = {fk: rand_month_table(sim, pool if fv is None else pool & fv, {k: r for k, r in exits.items() if k != 'S_struct60'})
            for fk, fv in flt.items()}
    print(f'  隨機月表 {time.time() - t0:.0f}s', flush=True)
    for pre, meta in LONG.items():
        if only and pre not in only:
            continue
        t0 = time.time()
        names = sorted(k for k in sigs if k.startswith(pre + '_'))
        rows = []
        for nm in names:
            base = dense(sigs[nm], shape) & pool
            sim.stop_mat = dense(sigs[nm], shape, info=True)
            for fk, fv in flt.items():
                m = base if fv is None else (base & fv)
                for ek, rule in exits.items():
                    tr = sim.trades2(m, rule)
                    if ek == 'S_struct60':                # 結構停損的隨機對照：用這組停損距離中位數當固定 % 停損
                        key = (fk, ek, nm)
                        if key not in rtab:
                            rr = _struct_rule(sim, tr)
                            rtab[key] = rand_month_table(sim, pool if fv is None else pool & fv, {'x': rr})['x']
                        table = rtab[key]
                    else:
                        table = rtab[fk][ek]
                    rows.append(run2.stats_row(f'{nm}|{fk}|{ek}', tr, {'variant': nm, 'filter': fk, 'exit': ek, **_excess(tr, table)}))
            print(f'  {pre} {nm} {time.time() - t0:.0f}s', flush=True)
        # 原本（網站預設出場 E0）＋原本的最好出場（同一套出場清單）
        base_rows = []
        orig_e0 = {}
        if meta['orig']:
            e0 = engine2.run_e0(sim, P, {k: orig[k] for k in meta['orig']})
            for k in meta['orig']:
                orig_e0[k] = e0[k]
                base_rows.append(run2.stats_row(f'{k}|none|E0_site', e0[k], {'variant': k, 'filter': 'none', 'exit': 'E0_site'}))
        g = pd.DataFrame(rows)
        g.to_csv(os.path.join(OUT, f'grid_{pre}.csv.gz'), index=False)
        sub = g[(g.is_n >= 100) & (g.is_mean > 0) & (g.is_pf >= 1.2) & (g.is_excess > 0)]
        out = {'title': meta['title'], 'n_tested': int(len(g)), 'n_variants': len(names),
               'baseline': [r for r in base_rows]}
        if len(sub) == 0:
            out.update(pick=None, passed=False, reasons=['樣本內沒有任何組合 筆數 ≥ 100、平均 > 0、PF ≥ 1.2、比隨機多賺'])
            # 還是記下樣本內超額最高的那組（給網站顯示「最好的也不行」）
            best = g[g.is_n >= 30].sort_values('is_excess', ascending=False).head(1)
            out['best_any'] = best.iloc[0].to_dict() if len(best) else None
            summary[pre] = out
            _save('long_summary.json', summary)
            continue
        pick = sub.sort_values(['is_excess', 'is_win'], ascending=False).iloc[0]
        nm, fk, ek = pick['variant'], pick['filter'], pick['exit']
        base = dense(sigs[nm], shape) & pool
        sim.stop_mat = dense(sigs[nm], shape, info=True)
        m = base if flt[fk] is None else (base & flt[fk])
        tr_p = sim.trades2(m, exits[ek])
        rule_r = exits[ek]
        if ek == 'S_struct60':                            # 隨機基準沒有結構停損 → 用這組交易停損距離的中位數當固定 % 停損
            rule_r = _struct_rule(sim, tr_p)
        rnd, rnd_tr = _rand_trades(sim, pool, m, rule_r)
        out['pick'] = pick.to_dict()
        out['random'] = rnd
        out['random_rule'] = rule_r if ek == 'S_struct60' else None
        lo_r = _boot_lo(tr_p, rnd_tr) if rnd_tr is not None else None
        lo_r99 = _boot_lo(tr_p, rnd_tr, q=0.3) if rnd_tr is not None else None
        out['boot_vs_random'] = {'lo95': lo_r, 'lo99_4': lo_r99}
        reasons = []
        if not pick.oos_mean > 0:
            reasons.append(f'樣本外平均 {pick.oos_mean:+.2%} ≤ 0')
        if pick.oos_n < 50:
            reasons.append(f'樣本外只有 {int(pick.oos_n)} 筆（< 50）')
        if rnd and pick.oos_win < rnd['win'] + 0.05:
            reasons.append(f'樣本外勝率沒比隨機進場高 5 點（{pick.oos_win:.1%} vs {rnd["win"]:.1%}）')
        if lo_r is None or lo_r <= 0:
            reasons.append(f'跟隨機比 樣本外平均差距 bootstrap 下限 ≤ 0（{(lo_r or 0):+.2%}）')
        # 合併類：跟原本（網站預設出場）比
        out['vs_orig'] = {}
        for k, tr_b in orig_e0.items():
            lo_b = _boot_lo(tr_p, tr_b)
            ob = run.split_stats(tr_b)['oos']
            out['vs_orig'][k] = {'oos': ob, 'boot_lo95': lo_b}
            if k == meta['orig'][0]:
                if not pick.oos_mean > ob.get('mean', -9):
                    reasons.append(f'樣本外平均沒比原本好（{pick.oos_mean:+.2%} vs {ob.get("mean", 0):+.2%}）')
                if lo_b is None or lo_b <= 0:
                    reasons.append(f'新版−原本 樣本外差距 bootstrap 下限 ≤ 0（{(lo_b or 0):+.2%}）')
        # 同一組訊號用網站預設出場（E0）的表現（網站 K 線回測會看到的）
        e0p = engine2.run_e0(sim, P, {'pick': m})['pick']
        out['pick_e0'] = run.split_stats(e0p)['oos']
        strength = np.ones(shape)
        out['port'] = run2.port(sim, tr_p, strength, 10, 0.1)
        out['reasons'] = reasons
        out['passed'] = not reasons
        out['oos_trades'] = int(pick.oos_n)
        # 每個參數組的樣本外（給報告看穩不穩：同出場、同濾網）
        same = g[(g['filter'] == fk) & (g['exit'] == ek)][['variant', 'is_n', 'is_win', 'is_mean', 'is_excess', 'oos_n', 'oos_win', 'oos_mean', 'oos_excess']]
        out['variants_same_exit'] = same.to_dict('records')
        # 只看「勝率」的人：樣本內勝率最高的合格組合（參考，不是挑法）
        hw = sub.sort_values('is_win', ascending=False).head(1)
        out['top_win_alt'] = hw.iloc[0].to_dict() if len(hw) else None
        summary[pre] = out
        print(pre, 'pick', nm, fk, ek, 'PASS' if not reasons else reasons, f'{time.time() - t0:.0f}s', flush=True)
        _save('long_summary.json', summary)
    return summary


# ── 6 跌破前低放空 ───────────────────────────────────────────────────────────
def short_exits():
    R = {}
    for n in (5, 10, 20):
        R[f'X1_{n}d'] = {'kind': 'time', 'max': n}
    for sp in (7, 10):
        for m in (20, 40):
            R[f'X2_s{sp}_{m}d'] = {'kind': 'stop', 'stp': sp / 100, 'max': m}
    for n in (10, 20):
        R[f'X3_ma{n}'] = {'kind': f'ma{n}', 'max': 40, 'ma': n}
    return R


def stage_short(P, F, fac, sim, pool, sigs):
    shape = (sim.T, sim.S)
    flt = _filters(P, F, short=True)
    exits = short_exits()
    MA = {n: F[f'ma{n}'].to_numpy(float) for n in (10, 20)}
    rows = []
    t0 = time.time()
    rtab = {fk: rand_month_table(sim, pool if fv is None else pool & fv, exits, short=True, MA=MA) for fk, fv in flt.items()}
    names = sorted(k for k in sigs if k.startswith('DB_'))
    for nm in names:
        base = dense(sigs[nm], shape) & pool
        for fk, fv in flt.items():
            m = base if fv is None else (base & fv)
            for ek, rule in exits.items():
                tr = sim.short_trades(m, rule, MA.get(rule.get('ma')))
                rows.append(run2.stats_row(f'{nm}|{fk}|{ek}', tr, {'variant': nm, 'filter': fk, 'exit': ek, **_excess(tr, rtab[fk][ek])}))
        print(f'  DB {nm} {time.time() - t0:.0f}s', flush=True)
    g = pd.DataFrame(rows)
    g.to_csv(os.path.join(OUT, 'grid_DB.csv.gz'), index=False)
    out = {'title': '跌破前低（d／D 點）放空', 'n_tested': int(len(g)), 'n_variants': len(names)}
    sub = g[(g.is_n >= 100) & (g.is_mean > 0) & (g.is_pf >= 1.2) & (g.is_excess > 0)]
    if len(sub) == 0:
        best = g[g.is_n >= 30].sort_values('is_excess', ascending=False).head(1)
        out.update(pick=None, passed=False, reasons=['樣本內沒有任何組合 筆數 ≥ 100、平均 > 0、PF ≥ 1.2、比隨機放空多賺'],
                   best_any=best.iloc[0].to_dict() if len(best) else None)
    else:
        pick = sub.sort_values(['is_excess', 'is_win'], ascending=False).iloc[0]
        nm, fk, ek = pick['variant'], pick['filter'], pick['exit']
        base = dense(sigs[nm], shape) & pool
        m = base if flt[fk] is None else (base & flt[fk])
        rule = exits[ek]
        tr_p = sim.short_trades(m, rule, MA.get(rule.get('ma')))
        rnd, rnd_tr = _rand_trades(sim, pool, m, rule, short=True, ma=MA.get(rule.get('ma')))
        lo = _boot_lo(tr_p, rnd_tr) if rnd_tr is not None else None
        reasons = []
        if not pick.oos_mean > 0:
            reasons.append(f'樣本外平均 {pick.oos_mean:+.2%} ≤ 0')
        if rnd and pick.oos_win < rnd['win'] + 0.05:
            reasons.append(f'樣本外勝率沒比隨機放空高 5 點（{pick.oos_win:.1%} vs {rnd["win"]:.1%}）')
        if lo is None or lo <= 0:
            reasons.append(f'跟隨機放空比 樣本外平均差距 bootstrap 下限 ≤ 0（{(lo or 0):+.2%}）')
        same = g[(g['filter'] == fk) & (g['exit'] == ek)][['variant', 'is_n', 'is_win', 'is_mean', 'is_excess', 'oos_n', 'oos_win', 'oos_mean', 'oos_excess']]
        out.update(pick=pick.to_dict(), random=rnd, boot_vs_random={'lo95': lo, 'lo99_4': _boot_lo(tr_p, rnd_tr, q=0.3) if rnd_tr is not None else None},
                   reasons=reasons, passed=not reasons, variants_same_exit=same.to_dict('records'))
        print('DB pick', nm, fk, ek, 'PASS' if not reasons else reasons, flush=True)
    _save('short_summary.json', out)
    return out


# ── 4 漲停打開 ───────────────────────────────────────────────────────────────
def _revenue(course_dir, P):
    r = pd.read_csv(os.path.join(course_dir, 'revenue.csv'), dtype={'ym': str, 'stock_id': str})
    r = r.drop_duplicates(['ym', 'stock_id'], keep='last')
    return {(a, b): (y, cy) for a, b, y, cy in zip(r.ym, r.stock_id, r.yoy, r.cum_yoy)}


def _period(d):
    return 'is' if IS[0] <= d <= IS[1] else ('oos' if OOS[0] <= d <= OOS[1] else None)


def _desc(r):
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    if not len(r):
        return {'n': 0}
    return {'n': int(len(r)), 'win': float((r > 0).mean()), 'mean': float(r.mean()), 'median': float(np.median(r)),
            'p5': float(np.percentile(r, 5)), 'p95': float(np.percentile(r, 95))}


def stage_limit(P, F, fac, sim, lite, sigs, course_dir):
    rev = _revenue(course_dir, P)
    T = sim.T
    sids = sim.sids
    events = []
    for nm in sorted(k for k in sigs if k.startswith('LO_')):
        t, s, _ = sigs[nm]
        ok = lite[t, s]
        for ti, si in zip(t[ok], s[ok]):
            day = sim.dates[ti]
            ym = C.latest_revenue_ym(day)
            yoy, cyoy = rev.get((ym, sids[si]), (np.nan, np.nan))
            row = {'variant': nm, 'date': day, 'sid': sids[si], 't': int(ti), 's': int(si), 'ym': ym, 'yoy': yoy, 'cum_yoy': cyoy}
            c0 = sim.c[ti, si]
            buy = c0 * (1 + engine.BUY_COST)
            for n in (1, 2, 3, 5):                         # D 收盤買、D+n 收盤賣
                j = ti + n
                if j < T and np.isfinite(sim.c[j, si]):
                    row[f'c_{n}'] = sim.c[j, si] * sim.cumfac[j, si] / sim.cumfac[ti, si] * (1 - engine.SELL_COST) / buy - 1
            # D 收盤買；收盤跌破 D 最低 → 當天收盤賣；最多 10 天
            lo = sim.l[ti, si]
            for j in range(ti + 1, min(T, ti + 11)):
                cj = sim.c[j, si]
                if not np.isfinite(cj):
                    continue
                if cj < lo or j == min(T, ti + 11) - 1:
                    row['c_stop10'] = cj * sim.cumfac[j, si] / sim.cumfac[ti, si] * (1 - engine.SELL_COST) / buy - 1
                    row['c_stop10_days'] = j - ti
                    break
            # D+1 開盤買、D+n 收盤賣
            if ti + 1 < T and np.isfinite(sim.o[ti + 1, si]):
                b1 = sim.o[ti + 1, si] * (1 + engine.BUY_COST)
                for n in (1, 2, 3, 5):
                    j = ti + n
                    if j < T and np.isfinite(sim.c[j, si]):
                        row[f'o_{n}'] = sim.c[j, si] * sim.cumfac[j, si] / sim.cumfac[ti + 1, si] * (1 - engine.SELL_COST) / b1 - 1
            # 當天打開後的空間：D 收盤到之後 5 天最高
            j5 = min(T, ti + 6)
            hh = np.nanmax(sim.h[ti + 1:j5, si]) if j5 > ti + 1 else np.nan
            row['mfe5'] = hh / c0 - 1 if np.isfinite(hh) else np.nan
            events.append(row)
    ev = pd.DataFrame(events)
    ev.to_csv(os.path.join(OUT, 'limit_events.csv'), index=False)
    fund = {'none': lambda d: np.ones(len(d), bool), 'yoy20': lambda d: d.yoy.to_numpy() >= 20,
            'cum20': lambda d: d.cum_yoy.to_numpy() >= 20}
    exits_ = ['c_1', 'c_2', 'c_3', 'c_5', 'c_stop10', 'o_1', 'o_2', 'o_3', 'o_5']
    res = []
    for nm, g in ev.groupby('variant'):
        for fk, f in fund.items():
            sub = g[f(g)]
            for ek in exits_:
                if ek not in sub:
                    continue
                row = {'variant': nm, 'fund': fk, 'exit': ek}
                for per in ('is', 'oos'):
                    d = sub[sub.date.map(_period) == per]
                    for kk, vv in _desc(d[ek]).items():
                        row[f'{per}_{kk}'] = vv
                res.append(row)
    g = pd.DataFrame(res)
    g.to_csv(os.path.join(OUT, 'grid_LO.csv'), index=False)
    cand = g[(g.is_n >= 15) & (g.is_mean > 0)]
    out = {'title': '連續跳空漲停後爆量打開', 'n_tested': int(len(g)), 'events': int(ev[['date', 'sid']].drop_duplicates().shape[0])}
    if len(cand):
        pick = cand.sort_values('is_mean', ascending=False).iloc[0]
        out['pick'] = pick.to_dict()
        # 同參數：基本面不限 vs 有基本面
        same = g[(g.variant == pick.variant) & (g.exit == pick.exit)]
        out['fund_compare'] = same.to_dict('records')
        reasons = []
        if not (pick.get('oos_n', 0) >= 10):
            reasons.append(f'樣本外只有 {int(pick.get("oos_n", 0) or 0)} 筆')
        if not (pick.get('oos_mean', -1) > 0):
            reasons.append(f'樣本外平均 {pick.get("oos_mean", 0):+.2%} ≤ 0')
        out['reasons'] = reasons
        out['passed'] = not reasons
    else:
        out.update(pick=None, passed=False, reasons=['樣本內沒有任何組合 筆數 ≥ 15、平均 > 0'])
    # 樣本最多的那組，全部事件的描述（網站說明用）
    out['all_events_by_fund'] = {}
    base_v = 'LO_n2_m3_close'
    for fk, f in fund.items():
        d = ev[(ev.variant == base_v)]
        d = d[f(d)]
        out['all_events_by_fund'][fk] = {ek: _desc(d[ek]) for ek in exits_ if ek in d} | {'mfe5': _desc(d['mfe5'])}
    _save('limit_summary.json', out)
    print('LO', out.get('pick'), out.get('reasons'), flush=True)
    return out


# ── 7 出貨日 ─────────────────────────────────────────────────────────────────
def _fwd(sim, n):
    """第 t 天收盤到第 t+n 個交易日收盤（含除權息）"""
    c = sim.c
    cf = sim.cumfac
    out = np.full(c.shape, np.nan)
    with np.errstate(invalid='ignore', divide='ignore'):
        out[:-n] = c[n:] * cf[n:] / (c[:-n] * cf[:-n]) - 1
    return out


def _dd(sim, n=20):
    """之後 n 天最低價（含除權息）相對第 t 天收盤"""
    l = sim.l * sim.cumfac
    base = sim.c * sim.cumfac
    out = np.full(sim.c.shape, np.nan)
    for t in range(sim.T - n):
        out[t] = np.nanmin(l[t + 1:t + n + 1], axis=0) / base[t] - 1
    return out


def _month_boot(dates_a, ra, dates_b, rb, reps=2000):
    A = pd.Series(ra).groupby(pd.Series(dates_a).str[:6])
    B = pd.Series(rb).groupby(pd.Series(dates_b).str[:6])
    A = {m: g.to_numpy() for m, g in A}
    B = {m: g.to_numpy() for m, g in B}
    months = sorted(set(A) & set(B))
    if not months:
        return None, None
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(reps):
        pick = rng.choice(months, len(months), replace=True)
        a = np.concatenate([A[m] for m in pick])
        b = np.concatenate([B[m] for m in pick])
        diffs.append(np.nanmean(a) - np.nanmean(b))
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def stage_dist(P, F, fac, sim, pool, sigs):
    shape = (sim.T, sim.S)
    typ = dense(sigs['DI'], shape, info=True)
    c, l = sim.c, sim.l
    hi = P['close'].to_numpy(float)
    rm = per_stock(P['close'], lambda s: s.rolling(60, min_periods=1).max()).to_numpy(float)
    rl = per_stock(P['low'], lambda s: s.rolling(60, min_periods=1).min()).to_numpy(float)
    with np.errstate(invalid='ignore', divide='ignore'):
        hz = (hi >= 0.9 * rm) & (hi / rl - 1 >= 0.2) & pool
    F5, F10, F20, DD = _fwd(sim, 5), _fwd(sim, 10), _fwd(sim, 20), _dd(sim, 20)
    out = {'title': '出貨日（下跌出量／量大不漲）'}
    for per, (a, b) in (('is', IS), ('oos', OOS), ('all', (IS[0], OOS[1]))):
        pm = ((sim.dates >= a) & (sim.dates <= b))[:, None]
        ctrl = hz & pm & ~(typ > 0)
        res = {}
        for name, msk in (('downvol', hz & pm & (typ == C.DIST_DOWNVOL)), ('stall', hz & pm & (typ == C.DIST_STALL)),
                          ('any', hz & pm & (typ > 0)), ('control', ctrl)):
            t, s = np.nonzero(msk)
            r = {'n': int(len(t))}
            for k, arr in (('f5', F5), ('f10', F10), ('f20', F20)):
                x = arr[t, s]
                r[k] = float(np.nanmean(x))
                r[k + '_up'] = float(np.nanmean(x > 0))
            r['dd10'] = float(np.nanmean(DD[t, s] <= -0.10))
            res[name] = r
        # 出貨日 − 對照 的 10 天報酬差，依月份 bootstrap
        ta, sa = np.nonzero(hz & pm & (typ > 0))
        tb, sb = np.nonzero(ctrl)
        lo, hi_ = _month_boot(sim.dates[ta], F10[ta, sa], sim.dates[tb], F10[tb, sb])
        res['diff_f10_ci'] = (lo, hi_)
        out[per] = res
    _save('dist_summary.json', out)
    print('DIST', json.dumps(out['oos'], ensure_ascii=False, default=_js)[:600], flush=True)
    return out


# ── 8 二次處置門檻放空 ───────────────────────────────────────────────────────
def stage_disp(P, F, fac, sim, pool):
    d = pd.read_csv(os.path.join(ROOT, 'research', 'link', 'data', 'disposal.csv'), dtype=str)
    d = d[d.stock_id.str.fullmatch(r'[1-9]\d{3}')]
    si = {s: i for i, s in enumerate(sim.sids)}
    dates = sim.dates
    pos = lambda day: int(np.searchsorted(dates, day))       # 第一個 ≥ day 的交易日
    shape = (sim.T, sim.S)
    Ea = np.zeros(shape, bool)
    Eb = np.zeros(shape, bool)
    c = sim.c
    up = np.zeros(shape, bool)
    with np.errstate(invalid='ignore'):
        up[1:] = c[1:] > c[:-1]
    up5 = up.copy()
    for k in range(1, 5):
        up5[k:] &= up[:-k]
    up5[:4] = False
    for r in d.itertuples():
        s = si.get(r.stock_id)
        if s is None:
            continue
        tp = pos(r.date_pub)
        if tp >= sim.T or dates[tp] != r.date_pub:
            continue
        if r.measure in ('第二次處置', '再次處置'):
            Ea[tp, s] = True
        elif r.measure == '第一次處置':
            a, b = pos(r.start), min(sim.T - 1, pos(r.end) + 10)
            hits = np.nonzero(up5[a:b + 1, s])[0]
            if len(hits):
                Eb[a + hits[0], s] = True
    lite = (dates >= engine.TRADE_FROM)[:, None] & np.isfinite(c) & (c >= 10)
    Ea &= lite
    Eb &= lite
    # 對照：20 日漲幅 ≥ 30% 的熱門股（股票池）
    with np.errstate(invalid='ignore', divide='ignore'):
        r20 = np.full(shape, np.nan)
        r20[20:] = c[20:] / c[:-20] - 1
    hot = pool & (r20 >= 0.3)
    exits = {'X1_3d': {'kind': 'time', 'max': 3}, 'X1_5d': {'kind': 'time', 'max': 5}, 'X1_10d': {'kind': 'time', 'max': 10},
             'X1_20d': {'kind': 'time', 'max': 20}, 'X2_s10_20d': {'kind': 'stop', 'stp': 0.10, 'max': 20}}
    out = {'title': '二次處置門檻放空'}
    for nm, m in (('Ea_second_disposal', Ea), ('Eb_up5_after_first', Eb)):
        res = {'events': int(m.sum())}
        for ek, rule in exits.items():
            tr = sim.short_trades(m, rule)
            ss = run.split_stats(tr)
            rnd, _ = _rand_trades(sim, hot, m, rule, reps=20, short=True)
            res[ek] = {'is': ss['is'], 'oos': ss['oos'], 'all': ss['all'], 'random_hot_oos': rnd}
        out[nm] = res
    _save('disp_summary.json', out)
    print('DISP', json.dumps({k: v.get('X1_5d', {}).get('oos') for k, v in out.items() if isinstance(v, dict)}, default=_js)[:500], flush=True)
    return out


# ── 9 主流族群同步大跌 ───────────────────────────────────────────────────────
def stage_sector(P, F, fac, sim, pool):
    sec = pd.read_csv(os.path.join(ROOT, 'research', 'link', 'data', 'sectors.csv'), dtype=str)
    si = {s: i for i, s in enumerate(sim.sids)}
    groups = {}
    for a, b in zip(sec.sector_id, sec.stock_id):
        if b in si:
            groups.setdefault(a, set()).add(si[b])
    groups = {k: np.array(sorted(v)) for k, v in groups.items() if len(v) >= 5}
    c, v = sim.c, P['volume'].to_numpy(float)
    with np.errstate(invalid='ignore', divide='ignore'):
        r1 = np.full(c.shape, np.nan)
        r1[1:] = c[1:] * sim.cumfac[1:] / (c[:-1] * sim.cumfac[:-1]) - 1
    turn = np.nan_to_num(c * v, nan=0.0) * pool
    mkt20 = pd.Series(turn.sum(1)).rolling(20).sum().to_numpy()
    F5, F10, F20 = _fwd(sim, 5), _fwd(sim, 10), _fwd(sim, 20)
    names = sorted(groups)
    G = len(names)
    T = sim.T
    share = np.zeros((T, G)); ew = np.full((T, G), np.nan); brd = np.full((T, G), np.nan)
    vr = np.full((T, G), np.nan); fw = {k: np.full((T, G), np.nan) for k in ('f5', 'f10', 'f20')}
    for gi, nm in enumerate(names):
        mem = groups[nm]
        pm = pool[:, mem]
        rr = np.where(pm, r1[:, mem], np.nan)
        cnt = pm.sum(1)
        ok = cnt >= 5
        with np.errstate(invalid='ignore'):
            ew[:, gi] = np.where(ok, np.nanmean(rr, axis=1), np.nan)
            brd[:, gi] = np.where(ok, np.nansum(rr <= -0.03, axis=1) / np.maximum(cnt, 1), np.nan)
        tv = turn[:, mem].sum(1)
        share[:, gi] = pd.Series(tv).rolling(20).sum().to_numpy() / mkt20
        vv = np.nansum(np.where(pm, v[:, mem], 0), axis=1)
        vr[:, gi] = vv / pd.Series(vv).rolling(20).mean().shift(1).to_numpy()
        for k, arr in (('f5', F5), ('f10', F10), ('f20', F20)):
            with np.errstate(invalid='ignore'):
                fw[k][:, gi] = np.where(ok, np.nanmean(np.where(pm, arr[:, mem], np.nan), axis=1), np.nan)
    rank = (-np.nan_to_num(share, nan=-1)).argsort(1).argsort(1)
    main = rank < 5
    crash = main & (brd >= 0.6) & (ew <= -0.03) & (vr >= 1.2)
    any_crash = (brd >= 0.6) & (ew <= -0.03) & (vr >= 1.2)
    out = {'title': '主流族群同步大跌', 'sectors': G}
    for per, (a, b) in (('is', IS), ('oos', OOS), ('all', (IS[0], OOS[1]))):
        pm = ((sim.dates >= a) & (sim.dates <= b))[:, None]
        res = {}
        for nm, msk in (('main_crash', crash & pm), ('main_normal', main & pm & ~crash), ('any_crash', any_crash & pm & ~main)):
            t, g = np.nonzero(msk)
            r = {'n': int(len(t))}
            for k in ('f5', 'f10', 'f20'):
                x = fw[k][t, g]
                r[k] = float(np.nanmean(x)) if len(x) else None
                r[k + '_up'] = float(np.nanmean(x > 0)) if len(x) else None
            r['f10_le_m5'] = float(np.nanmean(fw['f10'][t, g] <= -0.05)) if len(t) else None
            res[nm] = r
        out[per] = res
    ev = [{'date': sim.dates[t], 'sector': names[g], 'ew': ew[t, g], 'breadth': brd[t, g], 'f10': fw['f10'][t, g]}
          for t, g in zip(*np.nonzero(crash & (sim.dates >= IS[0])[:, None]))]
    pd.DataFrame(ev).to_csv(os.path.join(OUT, 'sector_crash_events.csv'), index=False)
    _save('sector_summary.json', out)
    print('SECTOR', json.dumps(out['oos'], default=_js)[:500], flush=True)
    return out


# ── 10 大盤出貨日 ────────────────────────────────────────────────────────────
def stage_market(P, sim, course_dir):
    tx = P['taiex'].to_numpy(float)
    mi = pd.read_csv(os.path.join(course_dir, 'mi5.csv'), dtype={'date': str}).drop_duplicates('date').set_index('date')
    ratio = (mi.deal_q / mi.buy_q).reindex(sim.dates).to_numpy(float)
    T = len(tx)
    fwd = {n: np.r_[tx[n:] / tx[:-n] - 1, np.full(n, np.nan)] for n in (5, 10, 20)}
    dd = np.full(T, np.nan)
    for t in range(T - 20):
        dd[t] = np.nanmin(tx[t + 1:t + 21]) / tx[t] - 1
    have = np.isfinite(ratio)
    out = {'title': '大盤出貨日', 'ratio_days': int(have.sum()),
           'ratio_pct_over_0.5': float(np.nanmean(ratio[have] > 0.5)) if have.any() else None,
           'ratio_quantiles': {q: float(np.nanpercentile(ratio[have], q)) for q in (10, 25, 50, 75, 90)} if have.any() else None}
    for k in (3, 5):
        md, brk, d = C.market_dist_day(tx, ratio, k=k)
        valid = (sim.dates >= IS[0]) & (sim.dates <= OOS[1]) & np.isfinite(fwd[20])
        res = {}
        for nm, msk in (('dist_day', md & valid & have), ('dbreak_only', brk & ~md & valid & have), ('all_days', valid & have)):
            r = {'n': int(msk.sum())}
            for n in (5, 10, 20):
                r[f'f{n}'] = float(np.nanmean(fwd[n][msk])) if msk.any() else None
                r[f'f{n}_up'] = float(np.nanmean(fwd[n][msk] > 0)) if msk.any() else None
            r['dd20'] = float(np.nanmean(dd[msk])) if msk.any() else None
            r['dd20_le_m5'] = float(np.nanmean(dd[msk] <= -0.05)) if msk.any() else None
            res[nm] = r
        res['events'] = [{'date': sim.dates[t], 'close': float(tx[t]), 'd': float(d[t]), 'ratio_max5': float(np.nanmax(ratio[max(0, t - 4):t + 1])),
                          'f5': fwd[5][t], 'f10': fwd[10][t], 'f20': fwd[20][t], 'dd20': dd[t]}
                         for t in np.nonzero(md & (sim.dates >= IS[0]))[0]]
        out[f'k{k}'] = res
    _save('market_summary.json', out)
    print('MARKET', json.dumps({k: out[k] for k in ('ratio_days', 'ratio_pct_over_0.5')}, default=_js),
          json.dumps({k: v for k, v in out['k3'].items() if k != 'events'}, default=_js)[:600], flush=True)
    return out


# ── 11 當沖名單 ──────────────────────────────────────────────────────────────
def stage_daytrade(P, F, sim, course_dir):
    fut = pd.read_csv(os.path.join(course_dir, 'stock_futures.csv'), dtype=str)
    futset = set(fut[fut.futures == '1'].stock_id)
    c, o, h, l = sim.c, sim.o, sim.h, sim.l
    v = P['volume'].to_numpy(float)
    T, S = c.shape
    pc = np.full(c.shape, np.nan); pc[1:] = c[:-1]
    turn = c * v
    t20 = per_stock(pd.DataFrame(turn, index=sim.dates, columns=sim.sids), lambda s: s.rolling(20).mean()).to_numpy(float)
    v20p = F['vol20p'].to_numpy(float)
    hh20 = per_stock(P['close'], lambda s: s.shift(1).rolling(20).max()).to_numpy(float)
    ll20 = per_stock(P['close'], lambda s: s.shift(1).rolling(20).min()).to_numpy(float)
    isfut = np.array([s in futset for s in sim.sids])
    rank_t = (-np.nan_to_num(t20, nan=-1)).argsort(1).argsort(1)
    base = (isfut[None, :] | (rank_t < 100)) & (c >= 20) & (F['bars'].to_numpy() >= 120) & ~F['gap60'].to_numpy()
    with np.errstate(invalid='ignore', divide='ignore'):
        chg = c / pc - 1
        rng_ = h - l
        vr = v / v20p
        longc = base & (chg >= 0.03) & (c >= h - 0.25 * rng_) & (c > hh20) & (vr >= 1.5)
        shortc = base & (chg <= -0.03) & (c <= l + 0.25 * rng_) & (c < ll20) & (vr >= 1.5)
        score = turn * rng_ / pc
    tx = P['taiex'].to_numpy(float)
    tx5 = pd.Series(tx).rolling(5).mean().to_numpy()
    rngr = np.random.default_rng(SEED)
    rec = {k: [] for k in ('long', 'short', 'long_mkt', 'short_mkt', 'rand_long', 'rand_short')}
    for t in range(T - 1):
        d = sim.dates[t]
        if d < engine.TRADE_FROM or d > OOS[1]:
            continue
        for side, cand in (('long', longc[t]), ('short', shortc[t])):
            idx = np.nonzero(cand)[0]
            if not len(idx):
                continue
            idx = idx[np.argsort(-np.nan_to_num(score[t, idx]))][:10]
            oo, cc, hh, ll = o[t + 1, idx], c[t + 1, idx], h[t + 1, idx], l[t + 1, idx]
            ok = np.isfinite(oo) & np.isfinite(cc) & (oo > 0)
            if side == 'long':
                r, mfe = cc / oo - 1 - DT_COST, hh / oo - 1
            else:
                r, mfe = 1 - cc / oo - DT_COST, 1 - ll / oo
            for x, y in zip(r[ok], mfe[ok]):
                rec[side].append((d, x, y))
                mk = tx[t] > tx5[t] if side == 'long' else tx[t] < tx5[t]
                if mk:
                    rec[side + '_mkt'].append((d, x, y))
            # 隨機對照：同一天、同股票池、同數量
            pool_t = np.nonzero(base[t] & np.isfinite(o[t + 1]) & np.isfinite(c[t + 1]))[0]
            if len(pool_t) >= len(idx):
                ri = rngr.choice(pool_t, size=int(ok.sum()), replace=False)
                rr = (c[t + 1, ri] / o[t + 1, ri] - 1 - DT_COST) if side == 'long' else (1 - c[t + 1, ri] / o[t + 1, ri] - DT_COST)
                rec['rand_' + side] += [(d, x, np.nan) for x in rr]
    out = {'title': '盤前當沖多空名單', 'cost': DT_COST, 'futures_n': len(futset)}
    for k, lst in rec.items():
        df = pd.DataFrame(lst, columns=['date', 'ret', 'mfe'])
        res = {}
        for per in ('is', 'oos'):
            dd_ = df[df.date.map(_period) == per]
            res[per] = _desc(dd_.ret) | {'mfe_mean': float(dd_.mfe.mean()) if len(dd_) else None,
                                          'days': int(dd_.date.nunique())}
        out[k] = res
    _save('daytrade_summary.json', out)
    print('DAYTRADE', json.dumps({k: v['oos'] for k, v in out.items() if isinstance(v, dict) and 'oos' in v}, default=_js)[:800], flush=True)
    return out


def main(best_dir, course_dir, stages):
    os.makedirs(OUT, exist_ok=True)
    P, F, fac, sim, pool, lite = load(best_dir)
    sp = os.path.join(os.path.dirname(os.path.abspath(course_dir)), 'signals.pkl')
    if 'sigs' in stages or not os.path.exists(sp):
        sigs = compute_sigs(P, sp)
    else:
        sigs = pickle.load(open(sp, 'rb'))
    allst = 'all' in stages
    longs = [s[5:] for s in stages if s.startswith('long:')]
    if allst or 'long' in stages or longs:
        stage_long(P, F, fac, sim, pool, sigs, best_dir, only=longs or None)
    if allst or 'short' in stages:
        stage_short(P, F, fac, sim, pool, sigs)
    if allst or 'limit' in stages:
        stage_limit(P, F, fac, sim, lite, sigs, course_dir)
    if allst or 'dist' in stages:
        stage_dist(P, F, fac, sim, pool, sigs)
    if allst or 'disp' in stages:
        stage_disp(P, F, fac, sim, pool)
    if allst or 'sector' in stages:
        stage_sector(P, F, fac, sim, pool)
    if allst or 'market' in stages:
        stage_market(P, sim, course_dir)
    if allst or 'daytrade' in stages:
        stage_daytrade(P, F, sim, course_dir)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3:] or ['all'])
