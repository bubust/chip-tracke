"""PLAN-BEST 第 7 節驗證 2：網站版（best_strategy.py）跟研究版逐日一致。
- 訊號：抽 300 個（股票, 日期）（一半研究有訊號、一半沒有），網站版用「截至那天、最多 520 根」的資料算，結果要一樣；
- 出場：抽 100 筆研究交易，plan_for 算出的出場日（出場條件成立那天的隔天開盤）要等於研究的出場日。
用法：python verify_live.py <data_dir>"""
import os, sys, random

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import engine, run
import best_strategy as bs


def stock_df(P, sid, upto):
    s = P['close'][sid]
    ok = s.notna() & (s.index <= upto)
    return pd.DataFrame({'date': s.index[ok], **{k: P[k][sid][ok].to_numpy() for k in ('open', 'high', 'low', 'close', 'volume')}})


def main(data_dir):
    sk, rk, ek = bs.CONFIG['signal'], bs.CONFIG['regime'], bs.CONFIG['exit']
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    fac = engine.event_factor(P, data_dir)
    sigs = run.build_signals(P, F, os.path.join(os.path.dirname(os.path.abspath(data_dir)), 'sig_a.csv.gz'))
    sp = sigs[sk]
    dates, cols = P['close'].index, P['close'].columns
    pool = F['liquid'].to_numpy() & (np.array(dates) >= engine.TRADE_FROM)[:, None]
    random.seed(5)
    pos = random.sample(range(len(sp[0])), min(150, len(sp[0])))
    on = set(zip(sp[0].tolist(), sp[1].tolist()))
    cells = np.argwhere(pool)
    neg = [tuple(cells[k]) for k in random.sample(range(len(cells)), 400)]
    neg = [x for x in neg if (int(x[0]), int(x[1])) not in on][:150]
    bad = 0
    for t, s in [(int(sp[0][k]), int(sp[1][k])) for k in pos] + [(int(a), int(b)) for a, b in neg]:
        sid, day = cols[s], dates[t]
        df = stock_df(P, sid, day).tail(bs.WINDOW)
        A = bs._arrays(df)
        live = bs.signal_at(A, A['n'] - 1, sk)
        res = (t, s) in on
        if live != res:
            bad += 1
            print('訊號不一致', sid, day, '研究', res, '網站', live)
    print(f'訊號：{len(pos) + len(neg)} 個抽樣，不一致 {bad}')
    # 大盤濾網
    regs = run.regime_masks(P, F)
    tx = P['taiex']
    rbad = sum(1 for t in random.sample(range(250, len(dates)), 100)
               if bs.regime_ok(dates[t], rk, tx) != bool(regs[rk][t]))
    print(f'大盤濾網：100 天抽樣，不一致 {rbad}')
    # 出場
    sim = engine.Sim(P, F, fac)
    rule = run.exit_rules()[ek]
    if rule['kind'] == 'roll':
        sim.e5, sim.e5_stop = run.compute_e5(P, {sk: sp}, os.path.join(os.path.dirname(os.path.abspath(data_dir)), 'e5.csv'))
    m = run.dense(sp, (sim.T, sim.S)) & regs[rk][:, None]
    tr = sim.trades(m, rule)
    tr = tr[~tr['gone']]
    xbad = 0
    for r in tr.sample(min(100, len(tr)), random_state=3).itertuples():
        sid = cols[r.s]
        df = stock_df(P, sid, dates[min(r.x + 1, len(dates) - 1)])
        A = bs._arrays(df)
        di = {d: i for i, d in enumerate(A['date'])}
        p = bs.plan_for(A, di[dates[r.t]], di[dates[r.e]], bs.exit_rule(ek))
        ex = p.get('exit_date')
        live_x = A['date'][di[ex] + 1] if ex and di[ex] + 1 < A['n'] else None
        if live_x != dates[r.x]:
            xbad += 1
            print('出場不一致', sid, dates[r.t], '研究出場', dates[r.x], '網站', live_x, p.get('exit_reason'))
    print(f'出場：{min(100, len(tr))} 筆抽樣，不一致 {xbad}')
    return bad + rbad + xbad


if __name__ == '__main__':
    sys.exit(1 if main(sys.argv[1]) else 0)
