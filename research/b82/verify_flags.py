"""PLAN-B82：網站版條件（opt_flags.chip_flags_pure／rev_flags_pure）跟研究版（b82common）逐日比對
用法：python verify_flags.py [data_dir（預設 research/b82/data）] [抽幾天，預設 50]"""
import os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT, 'research', 'best'), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
import numpy as np
import engine
import b82common as CM
import opt_flags as OF


def main(raw, n_days=50):
    P = engine.load_panel(os.path.join(raw, 'best'))
    dates = np.array([str(d) for d in P['close'].index])
    sids = np.array(P['close'].columns)
    inst, _ = CM.load_daily(raw, 'inst', ['foreign', 'trust', 'dealer'], dates, sids)
    marg, _ = CM.load_daily(raw, 'margin', ['margin', 'short'], dates, sids)
    vol = P['volume'].to_numpy(float)
    RC = CM.chip_flags(inst, marg, vol)
    revd = CM.load_revenue(raw)
    RR = CM.rev_flags(CM.align_revenue(revd, dates, sids))
    rev_site = {ym: {s: (r.rev, r.yoy, r.cum_yoy) for s, r in df.iterrows()} for ym, df in revd.items()}
    rev_site = {ym: {s: tuple(None if (v != v) else float(v) for v in t) for s, t in d.items()} for ym, d in rev_site.items()}
    ok_t = [t for t in range(len(dates)) if dates[t] >= '20210901']
    random.seed(20261024)
    pick = sorted(random.sample(ok_t, min(n_days, len(ok_t))))
    bad, checked = 0, 0
    to_none = lambda x: None if not np.isfinite(x) else float(x)      # noqa: E731
    for t in pick:
        lo = max(0, t - 7)
        cal = list(dates[lo:t + 1])
        inst_d = {dates[j]: {sids[s]: (to_none(inst['foreign'][j, s]), to_none(inst['trust'][j, s]), to_none(inst['dealer'][j, s]))
                             for s in np.nonzero(np.isfinite(inst['foreign'][j]) | np.isfinite(inst['trust'][j]))[0]} for j in range(lo, t + 1)}
        marg_d = {dates[j]: {sids[s]: float(marg['margin'][j, s]) for s in np.nonzero(np.isfinite(marg['margin'][j]))[0]} for j in range(lo, t + 1)}
        vol_d = {sids[s]: float(vol[t, s]) for s in np.nonzero(np.isfinite(vol[t]))[0]}
        site_c = OF.chip_flags_pure(cal, inst_d, marg_d, vol_d, list(sids))
        site_r = OF.rev_flags_pure(dates[t], rev_site, list(sids))
        for si, sid in enumerate(sids):
            for k in CM.CHIP:
                checked += 1
                if bool(RC[k][t, si]) != (k in site_c.get(sid, set())):
                    bad += 1
                    if bad <= 10:
                        print('籌碼不一致', dates[t], sid, k, bool(RC[k][t, si]), sorted(site_c.get(sid, set())))
            for k in CM.REV:
                checked += 1
                if bool(RR[k][t, si]) != (k in site_r.get(sid, set())):
                    bad += 1
                    if bad <= 10:
                        print('營收不一致', dates[t], sid, k, bool(RR[k][t, si]), sorted(site_r.get(sid, set())))
    print(f'抽 {len(pick)} 天 × {len(sids)} 檔 × {len(CM.CHIP) + len(CM.REV)} 條件＝{checked:,} 個比對，不一致 {bad}')
    return bad


if __name__ == '__main__':
    sys.exit(1 if main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'data'), int(sys.argv[2]) if len(sys.argv) > 2 else 50) else 0)
