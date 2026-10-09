"""PLAN-LINK 第 3 節：產業輪動狀態有沒有預測力
用 sector/engine.py 同一套函式逐日重算 5 年每個產業的 trend_state／regime／rank_trend／structure_event／transition_state，
每天只用到當天為止的資料（波段點要右邊 10 根確認完才用＝跟正式站「今天」算出來的一樣，不用到未來）。
事件（第 t 天狀態變成…）→ t+1 收盤起 5／20／60 天產業指數報酬 − 全部產業平均（超額）；隨機產業日基準；月份 bootstrap p＋BH。
用法：python sector_study.py <price_data_dir>　→ results/sector_states.csv.gz、sector_events.csv、sector_summary.json"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research', 'best'))
import numpy as np
import pandas as pd
import engine as beng
from sector import engine as se

OUT = os.path.join(HERE, 'results')
IS, OOS = ('20211001', '20240630'), ('20240701', '20260831')
NEW_2023 = {'綠能環保', '數位雲端', '運動休閒', '居家生活', '其他'}
SEED = 20261009
H = (5, 20, 60)


def build_states(P):
    mp = pd.read_csv(os.path.join(HERE, 'data', 'sectors.csv'), dtype=str)
    C, V = P['close'], P['volume']
    dates = list(C.index)
    T = len(dates)
    secs = {}
    for sid, g in mp.groupby('sector_id'):
        mem = [s for s in g.stock_id if s in C.columns]
        if len(mem) >= 2:
            secs[sid] = mem
    # 產業等權指數（engine.calc_sector_index：當天有資料的成員平均日報酬）
    idx, rets = {}, {}
    for sid, mem in secs.items():
        r = C[mem].pct_change(fill_method=None).mean(axis=1, skipna=True)
        lvl = (1 + r.fillna(0)).cumprod() * 100
        idx[sid], rets[sid] = lvl, r
    rows = []
    t0 = time.time()
    # 個股 MA（內部健康用）
    ma20 = beng.per_stock(C, lambda s: s.rolling(20).mean())
    ma60 = beng.per_stock(C, lambda s: s.rolling(60).mean())
    pc = beng.per_stock(C, lambda s: s.shift(1))
    r1 = C / pc - 1
    for sid, lvl in idx.items():
        s = lvl
        m20, m60, m120 = s.rolling(20).mean(), s.rolling(60).mean(), s.rolling(120).mean()
        vals, ds = s.values, list(s.index)
        win = 10
        swing_h, swing_l = [], []                  # (value, date, confirm_index)
        for i in range(win, T - win):
            left, right, v = vals[i - win:i], vals[i + 1:i + win + 1], vals[i]
            if v >= left.max() and v >= right.max():
                swing_h.append((float(v), ds[i], i + win))
            if v <= left.min() and v <= right.min():
                swing_l.append((float(v), ds[i], i + win))
        mem = secs[sid]
        for t in range(130, T):
            part = s.iloc[:t + 1]
            sh = [(v, d) for v, d, ci in swing_h if ci <= t]
            sl = [(v, d) for v, d, ci in swing_l if ci <= t]
            slope = se.calc_slope(m60.iloc[:t + 1], 5)
            last = float(vals[t])
            trend = se.calc_trend_state(part, float(m20.iloc[t]), float(m60.iloc[t]), float(m120.iloc[t]), slope, sh, sl)
            psh, _, psl, _ = (sh[-1][0], None, sl[-1][0], None) if sh and sl else (None, None, None, None)
            ev, _, _ = se.detect_structure_events(part.iloc[-10:], psh, psl, lookback=5)
            # 內部健康（calc_internal_health 同一套門檻，向量化）
            rr = r1[mem].iloc[t]
            ok = rr.notna()
            n = int(ok.sum())
            if n:
                up = (rr[ok] > 0)
                br = up.mean()
                a20 = (C[mem].iloc[t][ok] > ma20[mem].iloc[t][ok]).mean()
                a60 = (C[mem].iloc[t][ok] > ma60[mem].iloc[t][ok]).mean()
                ab = rr[ok].abs().sort_values(ascending=False)
                top3 = ab.iloc[:3].sum() / (ab.sum() or 1e-9)
                if br >= 0.6 and a20 >= 0.6 and top3 < 0.5:
                    health = 'HEALTHY'
                elif top3 >= 0.6:
                    health = 'CONCENTRATED'
                elif br < 0.3 and a20 < 0.3:
                    health = 'WEAK'
                elif br > a60:
                    health = 'IMPROVING'
                elif br < a60 * 0.7:
                    health = 'DETERIORATING'
                else:
                    health = 'STABLE'
            else:
                health = 'WEAK'
            rows.append({'date': ds[t], 'sector': sid, 'level': last, 'trend': trend, 'event': ev, 'health': health,
                         'r5': last / vals[t - 5] - 1, 'r20': last / vals[t - 20] - 1, 'r60': last / vals[t - 60] - 1})
        print(f'  {sid} {time.time() - t0:.0f}s', flush=True)
    st = pd.DataFrame(rows)
    # 每天橫向排名、rank_trend、regime、transition（engine 同一套函式）
    out = []
    for d, g in st.groupby('date'):
        g = g.copy()
        tot = len(g)
        for k in (5, 20, 60):
            g[f'rank{k}'] = g[f'r{k}'].rank(ascending=False, method='first').astype(int)
        g['rank_trend'] = [se.calc_rank_trend(a, b, c) for a, b, c in zip(g.rank5, g.rank20, g.rank60)]
        g['regime'] = [se.determine_sector_regime(tr, rk, tot) for tr, rk in zip(g.trend, g.rank5)]
        g['transition'] = [se.determine_transition_state(tr, rt, ev, h, rk, tot)
                           for tr, rt, ev, h, rk in zip(g.trend, g.rank_trend, g.event, g.health, g.rank5)]
        g['total'] = tot
        out.append(g)
    st = pd.concat(out).sort_values(['sector', 'date']).reset_index(drop=True)
    return st, secs, idx


def events_of(st):
    """事件：第 t 天變成某狀態（前一天不是）"""
    st = st.copy()
    prev = st.groupby('sector').shift(1)
    E = {}
    E['H1_range_to_bull'] = (st.trend == 'BULL') & (prev.trend == 'RANGE')
    E['X_bear_to_range'] = (st.trend == 'RANGE') & (prev.trend == 'BEAR')
    E['X_regime_bull_strong'] = (st.regime == '多頭強勢') & (prev.regime != '多頭強勢')
    for tr in ('EMERGING_LEADER', 'FALSE_BREAKDOWN_TURN', 'STRONG_LEADER', 'LEADER_FAILURE'):
        key = ('H2_' if tr == 'EMERGING_LEADER' else 'X_') + tr.lower()
        E[key] = (st.transition == tr) & (prev.transition != tr)
    E['X_strengthening_top3rd'] = (st.rank_trend == 'STRENGTHENING') & (prev.rank_trend != 'STRENGTHENING') & (st.rank5 <= st.total / 3)
    for ev in ('BREAKOUT', 'FALSE_BREAKDOWN', 'RECLAIM'):
        E['X_ev_' + ev.lower()] = (st.event == ev) & (prev.event != ev)
    return {k: v.fillna(False) for k, v in E.items()}


def fwd_excess(st, idx):
    """t+1 收盤起 h 天：產業指數報酬 − 全部產業平均"""
    L = pd.DataFrame(idx)
    out = {}
    for h in H:
        fr = L.shift(-(1 + h)) / L.shift(-1) - 1
        ex = fr.sub(fr.mean(axis=1), axis=0)
        out[h] = ex
    return out


def boot_p(vals, months, reps=2000, seed=SEED):
    rng = np.random.default_rng(seed)
    dfm = pd.DataFrame({'v': vals, 'm': months})
    groups = [g.v.to_numpy() for _, g in dfm.groupby('m')]
    k = len(groups)
    if k < 3:
        return None, None
    ms = []
    for _ in range(reps):
        pick = rng.integers(0, k, k)
        ms.append(np.concatenate([groups[i] for i in pick]).mean())
    ms = np.array(ms)
    return float((ms <= 0).mean()), float(np.percentile(ms, 2.5))


def bh(pvals):
    p = np.array([x if x is not None else 1.0 for x in pvals])
    n = len(p)
    order = np.argsort(p)
    adj = np.empty(n)
    prev = 1.0
    for rank, i in enumerate(order[::-1]):
        k = n - rank
        prev = min(prev, p[i] * n / k)
        adj[i] = prev
    return adj.tolist()


def summarize(st, E, ex, subset_name, keep):
    res = []
    rng = np.random.default_rng(SEED)
    for k, m in E.items():
        ev = st[m & keep]
        row = {'event': k, 'subset': subset_name, 'n': int(len(ev))}
        for per, (a, b) in (('is', IS), ('oos', OOS), ('all', (IS[0], OOS[1]))):
            e2 = ev[(ev.date >= a) & (ev.date <= b)]
            for h in H:
                v = np.array([ex[h].at[d, s] if d in ex[h].index else np.nan for d, s in zip(e2.date, e2.sector)], float)
                ok = np.isfinite(v)
                row[f'{per}_n{h}'] = int(ok.sum())
                row[f'{per}_mean{h}'] = float(v[ok].mean()) if ok.any() else None
                row[f'{per}_win{h}'] = float((v[ok] > 0).mean()) if ok.any() else None
                if per == 'all' and h == 20 and ok.sum() >= 5:
                    p, lo = boot_p(v[ok], e2.date.to_numpy()[ok].astype(str).astype('U6'))
                    row['p20'], row['lo20'] = p, lo
        # 隨機產業日（同月份分布）
        months = ev.date.astype(str).str[:6]
        pool = st[keep & (st.date >= IS[0]) & (st.date <= OOS[1])]
        rv = []
        for mo, cnt in months.value_counts().items():
            cand = pool[pool.date.astype(str).str[:6] == mo]
            if len(cand):
                pick = cand.sample(n=min(len(cand), cnt * 20), replace=True, random_state=int(rng.integers(1e9)))
                rv += [ex[20].at[d, s] for d, s in zip(pick.date, pick.sector) if d in ex[20].index]
        rv = np.array(rv, float); rv = rv[np.isfinite(rv)]
        row['rand_mean20'] = float(rv.mean()) if len(rv) else None
        row['rand_win20'] = float((rv > 0).mean()) if len(rv) else None
        res.append(row)
    adj = bh([r.get('p20') for r in res])
    for r, a in zip(res, adj):
        r['p20_bh'] = a
        r['sufficient'] = r['n'] >= 30
    return res


def main(data_dir):
    os.makedirs(OUT, exist_ok=True)
    P = beng.load_panel(data_dir)
    st, secs, idx = build_states(P)
    st.to_csv(os.path.join(OUT, 'sector_states.csv.gz'), index=False)
    E = events_of(st)
    ex = fwd_excess(st, idx)
    allk = pd.Series(True, index=st.index)
    stable = ~st.sector.isin(NEW_2023)
    summ = summarize(st, E, ex, 'all', allk) + summarize(st, E, ex, 'stable', stable)
    rows = []
    for k, m in E.items():
        for _, r in st[m].iterrows():
            rows.append({'event': k, 'date': r.date, 'sector': r.sector, 'trend': r.trend, 'regime': r.regime,
                         **{f'ex{h}': (ex[h].at[r.date, r.sector] if r.date in ex[h].index else None) for h in H}})
    pd.DataFrame(rows).to_csv(os.path.join(OUT, 'sector_events.csv'), index=False)
    json.dump({'summary': summ, 'n_sectors': len(secs), 'stable_excluded': sorted(NEW_2023)},
              open(os.path.join(OUT, 'sector_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    for r in summ:
        print(r['subset'], r['event'], r['n'], 'IS20', r.get('is_mean20'), r.get('is_win20'), 'OOS20', r.get('oos_mean20'), r.get('oos_win20'),
              'rand', r.get('rand_mean20'), 'p_bh', round(r['p20_bh'], 3))


if __name__ == '__main__':
    main(sys.argv[1])
