"""PLAN-STOP.md 第 6 節：實作版 price_levels.rolling_stop（kind=cost、trace）逐日停損 ＝ 研究版 stop_roll.py
（entry_rule＋raise_rule r=2.5）逐日停損。在放 pd.csv.gz 的資料夾執行：python verify_stop.py"""
import os, random, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
sys.path.insert(0, os.path.join(here, '..', '..'))
import stop_roll as R
from price_levels import rolling_stop

random.seed(7)
groups = {sid: g for sid, g in R.d.groupby('stock_id') if len(g) >= 180}
checked = bad = 0
for sid in random.sample(sorted(groups), 120):
    g = groups[sid].reset_index(drop=True)
    S, _ = R.prep(g)
    c = S['c']; n = len(c)
    for t in random.sample(range(130, n - R.H - 1), 3):
        if c[t] < 10:
            continue
        stop = R.entry_rule(S, t); want = [stop]
        for j in range(t + 1, t + R.H + 1):
            if c[j] < stop:
                break
            new = R.raise_rule(S, j, 2.5)
            if new is not None and new > stop:
                stop = new
            want.append(stop)
        got = rolling_stop(g.iloc[:t + R.H + 1], t, kind='cost', trace=True)['stops'][:len(want)]
        checked += 1
        if len(got) != len(want) or any(abs(x - y) > 1e-9 for x, y in zip(got, want)):
            bad += 1
            print('不一致', sid, g['date'].iloc[t], [round(x, 2) for x in want][:12], [round(x, 2) for x in got][:12])
print(f'比對 {checked} 個（股票, 進場日），逐日停損不一致 {bad} 個')
