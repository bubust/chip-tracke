"""A 類訊號：系統現有 18 個做多策略，逐日用「截至當天、最多 520 根」的資料呼叫掃描同一個 screen 函式
（正式站掃描就是讀最近 520 根，見 yahoo_price._fetch_for_scan），只算股票池裡的日子。
用法：python signals_a.py <data_dir> <out.csv.gz>（6 個行程平行，約 40 分鐘；記憶體只剩 3GB，資料逐檔傳給子行程）"""
import os, sys, time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd

WINDOW = 520
TRADE_FROM = '20211001'
_G = {}


def _init():
    import scanner
    _G['fns'] = {k: f for k, f in scanner.PRICE_STRATEGY_FNS.items() if k not in scanner.SHORT_STRATEGIES and k != 'S_BEST'}


def _one(task):
    sid, df, days = task
    out = []
    for i in days:
        sub = df.iloc[max(0, i - WINDOW + 1):i + 1]
        for k, fn in _G['fns'].items():
            try:
                if fn({'BT': sub}, {'BT': ''}, params=None):
                    out.append((df.at[i, 'date'], sid, k))
            except Exception:
                pass
    return out


def main(data_dir, out):
    import engine
    P = engine.load_panel(data_dir)
    F = engine.features(P)
    liq = F['liquid']
    pk = {}
    for sid in P['close'].columns:
        df = pd.DataFrame({'date': P['close'].index,
                           **{k: P[k][sid].to_numpy() for k in ('open', 'high', 'low', 'close', 'volume')}})
        keep = df['close'].notna().to_numpy()
        ok = liq[sid].to_numpy() & keep & (df['date'].to_numpy() >= TRADE_FROM)
        df = df[keep].reset_index(drop=True)
        days = np.nonzero(ok[keep])[0].tolist()
        if days:
            pk[sid] = (df, days)
    del P, F, liq
    sids = sorted(pk, key=lambda s: -len(pk[s][1]))
    t0, rows = time.time(), []
    with Pool(6, initializer=_init) as pool:
        for n, r in enumerate(pool.imap_unordered(_one, ((s, *pk[s]) for s in sids), chunksize=2), 1):
            rows += r
            if n % 100 == 0:
                print(f'{n}/{len(sids)} {time.time() - t0:.0f}s', flush=True)
    res = pd.DataFrame(rows, columns=['date', 'stock_id', 'strategy'])
    res.to_csv(out, index=False)
    print('DONE', len(res), res.strategy.value_counts().to_dict(), flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
