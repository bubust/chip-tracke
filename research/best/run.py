"""PLAN-BEST 研究主程式：訊號 × 大盤濾網 × 出場 全部組合 → 樣本內排名 → 樣本外驗證 → 隨機基準、bootstrap、組合模擬。
用法：python run.py <data_dir> [stage]
  stage：all（預設）／e5（只算滾動停損快取）／grid（只算全部組合）／select（用 grid 結果做選擇與檢查）
需要 signals_a.py 先產生 <data_dir>/../sig_a.csv.gz（系統現有 18 個做多策略的逐日訊號）。
輸出：research/best/results/（grid.csv、report.json、REPORT.md、主推／備選的交易明細）"""
import json, os, sys, time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import engine
from engine import per_stock

OUT = os.path.join(HERE, 'results')
IS = ('20211001', '20240630')
OOS = ('20240701', '20260831')
YEARS = ('2022', '2023', '2024', '2025', '2026')
RULE = {'win': 0.60, 'pf': 1.3, 'n_is': 200, 'n_oos': 100, 'p5': -0.15, 'years_pos': 4, 'top': 20,
        'base_gap': 0.05, 'mdd': 0.30, 'boot': 2000}


# ── 出場規則（E1～E5）──────────────────────────────────────────────────────
def exit_rules():
    R = {}
    for n in (3, 5, 10, 20, 40, 60):
        R[f'E1_{n}d'] = {'kind': 'time', 'n': n}
    for m in (5, 10):
        R[f'E2_ma5rsi_{m}d'] = {'kind': 'ma5', 'max': m}
    for tg in (1, 1.5, 2, 3):
        for sp in (1, 2, 3):
            for m in (20, 40):
                R[f'E3_t{tg}_s{sp}_{m}d'] = {'kind': 'atr', 'tgt': tg, 'stp': sp, 'max': m}
    for n in (10, 20):
        R[f'E4_ma{n}'] = {'kind': f'ma{n}', 'max': 60}
    for m in (20, 40, 60):
        R[f'E5_roll_{m}d'] = {'kind': 'roll', 'max': m}
    return R


# ── 訊號 ────────────────────────────────────────────────────────────────────
def tech_raw_vec(ts: pd.DataFrame) -> np.ndarray:
    """deep_verdict.tech_raw 的向量版（逐列結果一樣，main() 會抽樣比對）"""
    def tier(x, cuts, pts):
        out = np.zeros(len(x))
        done = np.zeros(len(x), bool)
        for cut, p in zip(cuts, pts):
            h = ~done & (x >= cut)
            out[h] = p
            done |= h
        return out
    trend = np.where(ts['bull'], 8, np.where(ts['above60'], 4, 0))
    p52 = ts['pos52'].to_numpy(float); r120 = ts['r120'].to_numpy(float)
    with np.errstate(invalid='ignore'):
        return (trend + np.where(ts['ma60_up'], 6, 0) + np.where(ts['dif_pos'], 6, 0)
                + tier(np.nan_to_num(p52, nan=-9), (.8, .6, .4, .2), (10, 7, 4, 2))
                + tier(np.nan_to_num(r120, nan=-9), (.3, .1, 0, -.1), (10, 7, 4, 2)))


def deep_raw(P) -> pd.DataFrame:
    from deep_verdict import tech_series
    cols = {}
    for sid in P['close'].columns:
        c = P['close'][sid]
        ok = c.notna()
        if ok.sum() < 130:
            continue
        g = pd.DataFrame({k: P[k][sid][ok].to_numpy() for k in ('open', 'high', 'low', 'close', 'volume')})
        ts = tech_series(g)
        raw = tech_raw_vec(ts)
        raw[:129] = np.nan                         # deep_verdict.MIN_BARS＝130
        cols[sid] = pd.Series(raw, index=c.index[ok])
    return pd.DataFrame(cols).reindex(index=P['close'].index, columns=P['close'].columns)


def build_signals(P, F, sig_a_path):
    """{名稱: (t 陣列, s 陣列, 強度)}（稀疏）；都已經跟股票池、交易期間做 AND"""
    A = lambda x: x.to_numpy(dtype=float)
    c, o, h, l, v = A(P['close']), A(P['open']), A(P['high']), A(P['low']), A(P['volume'])
    atr, rsi2, vol20p = A(F['atr']), A(F['rsi2']), A(F['vol20p'])
    ma = {n: A(F[f'ma{n}']) for n in (10, 20, 60, 120, 200)}
    c3 = A(per_stock(P['close'], lambda s: s.shift(3)))
    ph = A(per_stock(P['high'], lambda s: s.shift(1)))
    ma60_5 = A(per_stock(F['ma60'], lambda s: s.shift(5)))
    dates = np.array(P['close'].index)
    pool = F['liquid'].to_numpy() & (dates >= engine.TRADE_FROM)[:, None] & ~F['gap60'].to_numpy()
    with np.errstate(invalid='ignore', divide='ignore'):
        vr = v / vol20p
        S = {}
        for n in (60, 120, 200):
            up = c > ma[n]
            for k in (5, 10):
                S[f'B1_ma{n}_rsi{k}'] = (up & (rsi2 <= k), -rsi2)
            for k in (1.5, 2):
                dev = (ma[20] - c) / atr
                S[f'B1_ma{n}_dev{k}'] = (up & (dev >= k), dev)
            for k in (2, 3):
                drop = (c3 - c) / atr
                S[f'B1_ma{n}_drop{k}'] = (up & (drop >= k), drop)
        trend = (ma[20] > ma[60]) & (ma[60] > ma60_5)
        for n in (10, 20):
            S[f'B2_pull_ma{n}'] = (trend & (l <= ma[n]) & (ma[n] <= c), vr)
        for n in (20, 55, 120):
            hh = A(per_stock(P['close'], lambda s, n=n: s.shift(1).rolling(n).max()))
            for k in (1.5, 2):
                S[f'B3_brk{n}_v{k}'] = ((c > hh) & (vr >= k), vr)
        raw = A(deep_raw(P))
        prev = A(per_stock(pd.DataFrame(raw, index=P['close'].index, columns=P['close'].columns), lambda s: s.shift(1)))
        S['B4_deep_strong'] = ((raw >= 32) & (prev < 32), vr)
        S['B5_gap'] = ((o > ph * 1.01) & (c >= o) & (vr >= 2), vr)
        # C4 強勢股超賣：深度分析技術分 ≥ 32（狀態，不限第一天）
        strong = raw >= 32
        for k in (5, 10):
            S[f'C4_strong_rsi{k}'] = (strong & (rsi2 <= k), -rsi2)
        S['C4_strong_dev1.5'] = (strong & ((ma[20] - c) / atr >= 1.5), (ma[20] - c) / atr)
        a = pd.read_csv(sig_a_path, dtype={'date': str, 'stock_id': str})
        di = {d: i for i, d in enumerate(dates)}
        si = {s: i for i, s in enumerate(P['close'].columns)}
        AM = {}
        for k, g in a.groupby('strategy'):
            m = np.zeros(c.shape, bool)
            m[g.date.map(di).to_numpy(), g.stock_id.map(si).to_numpy()] = True
            AM[k] = m
            S[f'A_{k}'] = (m, vr)
        # ── C 融合（用戶 10-09 要求）──
        win3 = {k: m | np.r_[np.zeros((1, m.shape[1]), bool), m[:-1]] | np.r_[np.zeros((2, m.shape[1]), bool), m[:-2]]
                for k, m in AM.items()}                                     # 今天或前 2 天出現過
        ks = sorted(AM)
        for i, x in enumerate(ks):                                          # C1 兩兩 3 天內都出現
            for y in ks[i + 1:]:
                m = (AM[x] & win3[y]) | (AM[y] & win3[x])
                if (m & pool).sum() >= 400:
                    S[f'C1_{x}+{y}'] = (m, vr)
        trend3 = {'c60': c > ma[60], 'c200': c > ma[200], 'up': trend}     # C2 策略 × 個股趨勢
        for k, m in AM.items():
            for tk, tm in trend3.items():
                S[f'C2_{k}&{tk}'] = (m & tm, vr)
        anyA = np.zeros(c.shape, bool)
        for m in AM.values():
            anyA |= m
        cnt = np.zeros(c.shape, np.int8)                                    # C3 共識：3 天內不同策略數
        for w in win3.values():
            cnt += w
        S['C3_consensus2'] = (anyA & (cnt >= 2), cnt.astype(float))
        S['C3_consensus3'] = (anyA & (cnt >= 3), cnt.astype(float))
    out = {}
    for k in list(S):                    # 存成稀疏（訊號格子的 t, s, 強度），省記憶體
        m, st = S.pop(k)
        t, s_ = np.nonzero(np.nan_to_num(m, nan=0).astype(bool) & pool)
        out[k] = (t.astype(np.int32), s_.astype(np.int32), np.nan_to_num(np.asarray(st)[t, s_], nan=0.0))
    return out


def dense(sp, shape):
    m = np.zeros(shape, bool)
    m[sp[0], sp[1]] = True
    return m


def strength_of(sp, shape):
    a = np.zeros(shape)
    a[sp[0], sp[1]] = sp[2]
    return a


def regime_masks(P, F):
    tx = P['taiex'].to_numpy(float)
    with np.errstate(invalid='ignore'):
        return {'none': np.ones(len(tx), bool), 'tx60': tx > F['tx_ma60'].to_numpy(float),
                'tx200': tx > F['tx_ma200'].to_numpy(float)}


# ── E5：滾動停損（price_levels 同一套函式，逐檔重播）────────────────────────
def _e5_stock(task):
    import price_levels as pl
    col, c, h, l, rows, ts, maxd = task
    atr = pl.atr_series(h, l, c)
    ma = {k: pd.Series(c).rolling(k).mean().values for k in (5, 10, 20)}
    S = pl.StructLows(h, l, c)
    out = []
    for j0 in ts:
        e = pl.entry_stop(c, l, atr, ma[5], ma[10], ma[20], S.at(j0), j0)
        stop, hit = e['price'], None
        for j in range(j0 + 1, min(j0 + maxd + 2, len(c))):
            if c[j] < stop:
                hit = j
                break
            i = pl.raise_candidate(c, h, l, atr, S.at(j), j)
            if i is not None and l[i] > stop:
                stop = float(l[i])
        out.append((col, int(rows[j0]), int(rows[hit]) if hit is not None else -1, float(e['price'])))
    return out


def compute_e5(P, sigs, path, procs=6):
    """所有訊號格子（股票, 訊號日）的滾動停損：第一個收盤跌破的日子＋進場停損價。有快取就只補缺的格子"""
    old = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=['s', 't', 'hit', 'stop'])
    have = set(zip(old.s.astype(int), old.t.astype(int)))
    anym = np.zeros(P['close'].shape, bool)
    for sp in sigs.values():
        anym[sp[0], sp[1]] = True
    for a_, b_ in have:
        anym[b_, a_] = False
    tasks = []
    C, H, L = (P[k].to_numpy(float) for k in ('close', 'high', 'low'))
    for col in range(C.shape[1]):
        ts_panel = np.nonzero(anym[:, col])[0]
        if not len(ts_panel):
            continue
        ok = np.isfinite(C[:, col])
        rows = np.nonzero(ok)[0]
        pos = {r: i for i, r in enumerate(rows)}
        tasks.append((col, C[ok, col], H[ok, col], L[ok, col], rows, [pos[t] for t in ts_panel], 61))
    if tasks:
        t0, res = time.time(), []
        with Pool(procs) as pool:
            for n, r in enumerate(pool.imap_unordered(_e5_stock, tasks, chunksize=4), 1):
                res += r
                if n % 200 == 0:
                    print(f'  E5 {n}/{len(tasks)} {time.time() - t0:.0f}s', flush=True)
        new = pd.DataFrame(res, columns=['s', 't', 'hit', 'stop'])
        old = pd.concat([old, new], ignore_index=True)
        old.to_csv(path, index=False)
    d = old
    T = len(P['close'])
    hit = {(int(a), int(b)): (int(x) if x >= 0 else T) for a, b, x in zip(d.s, d.t, d.hit)}
    stop = {(int(a), int(b)): float(p) for a, b, p in zip(d.s, d.t, d.stop)}
    return hit, stop


# ── 統計 ────────────────────────────────────────────────────────────────────
def split_stats(tr: pd.DataFrame) -> dict:
    """樣本內／樣本外／全期／各年（依訊號日；全期與各年只到樣本外結束日）"""
    out = {}
    d = tr['date'].to_numpy().astype(str)
    r, dy = tr['ret'].to_numpy(), tr['days'].to_numpy()
    for name, (a, b) in (('is', IS), ('oos', OOS)):
        m = (d >= a) & (d <= b)
        out[name] = engine.stats(r[m], dy[m])
    allm = d <= OOS[1]
    out['all'] = engine.stats(r[allm], dy[allm])
    out['years'] = {y: engine.stats(r[allm & (d >= y + '0101') & (d <= y + '1231')]) for y in YEARS}
    return out


def qualifies(st: dict, n_min: int) -> bool:
    return (st.get('n', 0) >= n_min and st['win'] >= RULE['win'] and st['mean'] > 0
            and st['pf'] >= RULE['pf'] and st['p5'] >= RULE['p5'])


def years_ok(ss) -> bool:
    return sum(1 for y in YEARS if ss['years'][y].get('n', 0) and ss['years'][y]['mean'] > 0) >= RULE['years_pos']


def flat(name, ss):
    row = {'combo': name}
    for k in ('is', 'oos', 'all'):
        for f in ('n', 'win', 'mean', 'median', 'pf', 'p5', 'avg_win', 'avg_loss', 'days'):
            row[f'{k}_{f}'] = ss[k].get(f)
    for y in YEARS:
        row[f'y{y}_n'] = ss['years'][y].get('n')
        row[f'y{y}_mean'] = ss['years'][y].get('mean')
        row[f'y{y}_win'] = ss['years'][y].get('win')
    return row


def run_grid(sim, sigs, regs, rules, path):
    rows, t0, n = [], time.time(), 0
    total = len(sigs) * len(regs) * len(rules)
    shape = (sim.T, sim.S)
    for sk, sp in sigs.items():
        m = dense(sp, shape)
        for rk, rm in regs.items():
            mm = m & rm[:, None]
            for ek, rule in rules.items():
                tr = sim.trades(mm, rule)
                ss = split_stats(tr)
                rows.append(flat(f'{sk}|{rk}|{ek}', ss))
                n += 1
        print(f'  grid {n}/{total} {time.time() - t0:.0f}s {sk}', flush=True)
    g = pd.DataFrame(rows)
    g.to_csv(path, index=False)
    return g


# ── 隨機基準、bootstrap ──────────────────────────────────────────────────────
def random_baseline(sim, pool, sig, rule, reps=20, seed=7):
    """同樣出場、隨機挑股票池裡的（股票, 日子）：每個月抽的筆數＝這個方法 OOS 那個月的訊號數"""
    rng = np.random.default_rng(seed)
    dates = sim.dates
    month = np.array([d[:6] for d in dates])
    oos = (dates >= OOS[0]) & (dates <= OOS[1])
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
        tr = sim.trades(m, rule)
        res.append(engine.stats(tr['ret'].to_numpy()))
    return {'win': float(np.mean([r['win'] for r in res])), 'mean': float(np.mean([r['mean'] for r in res])),
            'n': float(np.mean([r['n'] for r in res])), 'reps': reps}


def bootstrap_ci(tr, reps=RULE['boot'], seed=11):
    d = tr['date'].astype(str)
    t = tr[(d >= OOS[0]) & (d <= OOS[1])]
    groups = [g['ret'].to_numpy() for _, g in t.groupby(t['date'].astype(str).str[:6])]
    rng = np.random.default_rng(seed)
    k = len(groups)
    means = []
    for _ in range(reps):
        idx = rng.integers(0, k, k)
        allr = np.concatenate([groups[i] for i in idx])
        means.append(allr.mean())
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


# ── 組合模擬 ────────────────────────────────────────────────────────────────
def portfolio(sim, tr, strength, mode='slots', slots=10, risk=0.01, cap=0.2, stopdist=None):
    """逐日模擬：開盤先賣（到出場日）再買（同一天訊號依強度排序）；收盤算淨值（含除權息）。
    mode='slots'：10 個名額，每筆＝前一天淨值 ÷ 10；mode='risk'：每筆風險＝淨值 1%（部位＝1% ÷ 停損距離，單檔 ≤ 20%）"""
    T = sim.T
    tr = tr.copy()
    tr['str'] = strength[tr['t'].to_numpy(), tr['s'].to_numpy()]
    tr['sd'] = stopdist if stopdist is not None else 0.1
    by_e = {e: g.sort_values('str', ascending=False) for e, g in tr.groupby('e')}
    cash, eq = 1.0, 1.0
    hold = {}                                   # idx → (s, e, x, shares, gone)
    curve, taken, expo, log = [], 0, [], []
    start = int(np.searchsorted(sim.dates, engine.TRADE_FROM))
    end = int(np.searchsorted(sim.dates, OOS[1], side='right')) + 60
    end = min(end, T)
    lastpx = {}
    for d in range(start, end):
        for k in [k for k, hd in hold.items() if hd[2] == d]:
            s, e, x, sh, gone = hold.pop(k)
            px = sim.c[x, s] if gone else sim.o[x, s]
            cash += sh * px * sim.cumfac[x, s] / sim.cumfac[e, s] * (1 - engine.SELL_COST)
        if d in by_e and d <= int(np.searchsorted(sim.dates, OOS[1], side='right')):
            for r in by_e[d].itertuples():
                if mode == 'slots':
                    if len(hold) >= slots:
                        break
                    amt = min(eq / slots, cash)
                else:
                    amt = min(eq * min(risk / max(r.sd, 1e-4), cap), cash)
                if amt <= eq * 0.005:
                    continue
                px = sim.o[d, r.s]
                sh = amt / (px * (1 + engine.BUY_COST))
                cash -= amt
                hold[r.Index] = (r.s, r.e, r.x, sh, bool(r.gone))
                taken += 1
                log.append((int(r.s), int(r.e), int(r.x), float(amt / eq), float(r.ret)))
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
    peak = cv.cummax()
    mdd = float((cv / peak - 1).min())
    yrs = len(cv) / 245
    cagr = float(cv.iloc[-1] ** (1 / yrs) - 1) if yrs > 0 else 0.0
    yearly = {y: float(g.iloc[-1] / g.iloc[0] - 1) for y, g in cv.groupby(cv.index.str[:4])}
    return {'final': float(cv.iloc[-1]), 'cagr': cagr, 'mdd': mdd, 'taken': taken, 'n_signals': len(tr),
            'exposure': float(np.mean(expo)), 'yearly': yearly, 'curve': cv, 'log': log}


def taiex_bh(P):
    tx = P['taiex']
    tx = tx[(tx.index >= engine.TRADE_FROM) & (tx.index <= OOS[1])]
    cv = tx / tx.iloc[0]
    yrs = len(cv) / 245
    return {'cagr': float(cv.iloc[-1] ** (1 / yrs) - 1), 'mdd': float((cv / cv.cummax() - 1).min()),
            'final': float(cv.iloc[-1]), 'yearly': {y: float(g.iloc[-1] / g.iloc[0] - 1) for y, g in cv.groupby(cv.index.str[:4])},
            'curve': cv}


# ── 主程式 ──────────────────────────────────────────────────────────────────
def main(data_dir, stage='all'):
    os.makedirs(OUT, exist_ok=True)
    work = os.path.dirname(os.path.abspath(data_dir))
    t0 = time.time()
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, data_dir)
    print(f'load+features {time.time() - t0:.0f}s {P["close"].shape}', flush=True)
    sigs = build_signals(P, F, os.path.join(work, 'sig_a.csv.gz'))
    print(f'signals {len(sigs)} {time.time() - t0:.0f}s', {k: len(sp[0]) for k, sp in sigs.items()}, flush=True)
    sim = engine.Sim(P, F, fac)
    sim.e5, sim.e5_stop = compute_e5(P, sigs, os.path.join(work, 'e5.csv'))
    print(f'e5 {len(sim.e5)} {time.time() - t0:.0f}s', flush=True)
    if stage == 'e5':
        return
    regs = regime_masks(P, F)
    rules = exit_rules()
    gpath = os.path.join(OUT, 'grid.csv')
    if stage in ('all', 'grid') or not os.path.exists(gpath):
        g = run_grid(sim, sigs, regs, rules, gpath)
    else:
        g = pd.read_csv(gpath)
    if stage == 'grid':
        return
    select(P, F, fac, sim, sigs, regs, rules, g)


def combo_parts(name):
    sk, rk, ek = name.split('|')
    return sk, rk, ek


def stopdist_for(sim, tr, rule):
    t, s, e = tr['t'].to_numpy(), tr['s'].to_numpy(), tr['e'].to_numpy()
    ent = sim.c[t, s]
    if rule['kind'] == 'atr':
        return rule['stp'] * sim.atr[t, s] / ent
    if rule['kind'] == 'roll':
        st = np.array([sim.e5_stop.get((int(a), int(b)), np.nan) for a, b in zip(s, t)])
        return np.clip((ent - st) / ent, 0.01, 0.5)
    return 2 * sim.atr[t, s] / ent


def select(P, F, fac, sim, sigs, regs, rules, g):
    rep = {'rule': RULE, 'periods': {'is': IS, 'oos': OOS}, 'n_combos': int(len(g)),
           'n_signals': len(sigs), 'n_regimes': len(regs), 'n_exits': len(rules)}
    ism = g.apply(lambda r: qualifies({'n': r.is_n, 'win': r.is_win, 'mean': r.is_mean, 'pf': r.is_pf, 'p5': r.is_p5}, RULE['n_is']), axis=1)
    rep['n_is_qualified'] = int(ism.sum())
    top = g[ism].sort_values(['is_win', 'is_mean'], ascending=False).head(RULE['top'])
    pool = F['liquid'].to_numpy() & (sim.dates >= engine.TRADE_FROM)[:, None]
    cands = []
    for r in top.itertuples():
        sk, rk, ek = combo_parts(r.combo)
        st_oos = {'n': r.oos_n, 'win': r.oos_win, 'mean': r.oos_mean, 'pf': r.oos_pf, 'p5': r.oos_p5}
        yo = sum(1 for y in YEARS if (getattr(r, f'y{y}_n') or 0) and getattr(r, f'y{y}_mean') > 0)
        ok = bool(qualifies(st_oos, RULE['n_oos'])) and yo >= RULE['years_pos']
        cands.append({'combo': r.combo, 'is_win': r.is_win, 'is_mean': r.is_mean, 'is_n': r.is_n, 'is_pf': r.is_pf,
                      'oos_win': r.oos_win, 'oos_mean': r.oos_mean, 'oos_n': r.oos_n, 'oos_pf': r.oos_pf,
                      'oos_p5': r.oos_p5, 'years_pos': yo, 'oos_ok': ok})
    rep['top20'] = cands
    passed = [c for c in cands if c['oos_ok']]
    rep['n_top20_oos_ok'] = len(passed)
    if not passed:
        near = g[ism].copy() if ism.any() else g.copy()
        near['gap'] = (np.maximum(0, RULE['win'] - near.oos_win.fillna(0)) * 100
                       + np.maximum(0, -near.oos_mean.fillna(-1)) * 1000)
        rep['nearest'] = near.sort_values('gap').head(5)[['combo', 'is_n', 'is_win', 'is_mean', 'oos_n', 'oos_win', 'oos_mean', 'oos_pf', 'oos_p5']].to_dict('records')
    checks = []
    tx = taiex_bh(P)
    rep['taiex'] = {k: v for k, v in tx.items() if k != 'curve'}
    ordered = sorted(passed, key=lambda c: (-c['oos_win'], -c['oos_mean']))
    for c in ordered:
        chk = check_candidate(P, sim, sigs, regs, rules, pool, fac, c['combo'])
        checks.append(chk)
        if chk['pass']:
            break
    alt = max(passed, key=lambda c: c['oos_mean']) if passed else None
    alt_chk = None
    if alt is not None:
        alt_chk = next((k for k in checks if k['combo'] == alt['combo']), None) or check_candidate(P, sim, sigs, regs, rules, pool, fac, alt['combo'])
    rep['checks'] = [{k: v for k, v in c.items() if k not in ('_tr', '_curves')} for c in checks]
    main_c = next((c for c in checks if c['pass']), None)
    rep['main'] = main_c['combo'] if main_c else None
    rep['alt'] = alt['combo'] if alt else None
    rep['alt_check'] = {k: v for k, v in alt_chk.items() if k not in ('_tr', '_curves')} if alt_chk else None
    for tag, c in (('main', main_c), ('alt', alt_chk)):
        if c:
            c['_tr'].assign(stock_id=sim.sids[c['_tr']['s']], entry_date=sim.dates[c['_tr']['e']],
                            exit_date=sim.dates[c['_tr']['x']]).to_csv(os.path.join(OUT, f'trades_{tag}.csv'), index=False)
            cv = pd.DataFrame({k: v for k, v in c['_curves'].items()})
            cv['taiex'] = tx['curve'].reindex(cv.index)
            cv.to_csv(os.path.join(OUT, f'curve_{tag}.csv'))
            rep[f'{tag}_neighbors'] = neighbors(g, c['combo'])
    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, default=float)
    print(json.dumps({k: rep[k] for k in ('n_combos', 'n_is_qualified', 'n_top20_oos_ok', 'main', 'alt')}, ensure_ascii=False))


def check_candidate(P, sim, sigs, regs, rules, pool, fac, combo):
    sk, rk, ek = combo_parts(combo)
    m = dense(sigs[sk], (sim.T, sim.S)) & regs[rk][:, None]
    strength = strength_of(sigs[sk], (sim.T, sim.S))
    rule = rules[ek]
    tr = sim.trades(m, rule)
    tr = tr[tr['date'].astype(str) <= OOS[1]].reset_index(drop=True)
    ss = split_stats(tr)
    out = {'combo': combo, 'stats': {k: ss[k] for k in ('is', 'oos', 'all')}, 'years': ss['years']}
    # 除權息後 3 天內的訊號比例
    F_ = fac.to_numpy(float)
    near = np.zeros(len(tr), bool)
    for k in range(3):
        tt = np.maximum(tr['t'].to_numpy() - k, 0)
        near |= F_[tt, tr['s'].to_numpy()] != 1.0
    out['exdiv_share'] = float(near.mean()) if len(tr) else 0.0
    if out['exdiv_share'] > 0.05:
        # 加一條「除權息後 3 天內的訊號不算」重算
        ex = np.zeros(m.shape, bool)
        for k in range(3):
            ex[k:] |= (F_[:len(F_) - k] != 1.0)
        m = m & ~ex
        tr = sim.trades(m, rule)
        tr = tr[tr['date'].astype(str) <= OOS[1]].reset_index(drop=True)
        ss = split_stats(tr)
        out['exdiv_rule'] = True
        out['stats'] = {k: ss[k] for k in ('is', 'oos', 'all')}
        out['years'] = ss['years']
    base = random_baseline(sim, pool, m, rule)
    out['baseline'] = base
    lo, hi = bootstrap_ci(tr)
    out['boot_ci'] = (lo, hi)
    sd = stopdist_for(sim, tr, rule)
    pa = portfolio(sim, tr, strength, 'slots')
    pb = portfolio(sim, tr, strength, 'risk', stopdist=sd)
    out['port_slots'] = {k: v for k, v in pa.items() if k not in ('curve', 'log')}
    out['port_risk'] = {k: v for k, v in pb.items() if k not in ('curve', 'log')}
    oos = out['stats']['oos']
    reasons = []
    if not qualifies(oos, RULE['n_oos']):
        reasons.append('除權息規則重算後樣本外不合格')
    if oos.get('win', 0) < base['win'] + RULE['base_gap']:
        reasons.append(f"勝率沒比隨機基準高 5 個百分點（{oos.get('win', 0):.1%} vs {base['win']:.1%}）")
    if oos.get('mean', 0) <= base['mean']:
        reasons.append('平均每筆沒比隨機基準高')
    if lo <= 0:
        reasons.append(f'bootstrap 95% 信賴區間下限 ≤ 0（{lo:.2%}）')
    if min(pa['mdd'], pb['mdd']) < -RULE['mdd']:
        reasons.append(f"組合最大回撤超過 30%（名額 {pa['mdd']:.1%}／風險 {pb['mdd']:.1%}）")
    out['reasons'] = reasons
    out['pass'] = not reasons
    out['_tr'] = tr
    out['_curves'] = {'slots': pa['curve'], 'risk': pb['curve']}
    print('check', combo, 'PASS' if out['pass'] else reasons, flush=True)
    return out


def neighbors(g, combo):
    """同一族訊號、相鄰參數、同一類出場的結果（看是不是只有單一參數好）"""
    sk, rk, ek = combo_parts(combo)
    fam = sk.split('_')[0] + ('_' + sk.split('_')[1] if sk.startswith('B1') else '')
    efam = ek.split('_')[0]
    parts = g['combo'].str.split('|', expand=True)
    m = parts[0].str.startswith(fam) & (parts[2].str.split('_').str[0] == efam)
    cols = ['combo', 'is_n', 'is_win', 'is_mean', 'oos_n', 'oos_win', 'oos_mean', 'oos_pf']
    return g[m].sort_values('is_win', ascending=False)[cols].head(40).to_dict('records')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'all')
