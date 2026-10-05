"""一致性驗證（PLAN-LEVELS.md 第 6 節，一次性腳本，不是 CI 測試）
用正式站 price_daily 匯出檔，抽樣 N 個時間點，只給 t 以前的資料呼叫「新版」與「舊版」compute_levels，
跑跟 research.py 同一套評估（ATR 同距離隨機價位當基準），確認實作跟研究規則一致。

用法：python research/levels/verify_impl.py PD_CSV_GZ OLD_PRICE_LEVELS_PY [N=3000]
  PD_CSV_GZ：date,stock_id,open,high,low,close,volume（正式站 cache.db price_daily 匯出）
  OLD_PRICE_LEVELS_PY：舊版 price_levels.py（git show 86daa8a:price_levels.py）
"""
import importlib.util, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import price_levels as new                      # noqa: E402
from research import sup_out, stop_out, tgt_stall, atr, H, AFTER   # noqa: E402

pd_path, old_path = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
spec = importlib.util.spec_from_file_location('price_levels_old', old_path)
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)

d = pd.read_csv(pd_path, dtype={'stock_id': str, 'date': str})
d = d[(d.close > 0) & (d.high > 0) & (d.low > 0)].sort_values(['stock_id', 'date'])
G = {sid: g.reset_index(drop=True) for sid, g in d.groupby('stock_id')}
rng = np.random.default_rng(11)
pool = []
for sid, g in G.items():
    n = len(g)
    if n < 120 + H + AFTER + 10: continue
    v = g.volume.values
    for t in range(120, n - H - AFTER - 2, 10):
        if v[t - 20:t + 1].mean() >= 300: pool.append((sid, t))
pick = [pool[i] for i in rng.choice(len(pool), size=min(N, len(pool)), replace=False)]

rows = []
old_crash = 0
for sid, t in pick:
    g = G[sid]; df = g.iloc[:t + 1]
    h, l, c = (g[k].values.astype(float) for k in ('high', 'low', 'close'))
    A = atr(h, l, c)[t]
    ma20, ma60 = (pd.Series(c).rolling(k).mean().values[t] for k in (20, 60))
    nv = new.compute_levels(df)
    try:
        ov = old.compute_levels(df)
    except TypeError:              # 舊版 detect_thunder 在「突破後第一段高點沒高過突破點」時會例外（新版已修）
        old_crash += 1
        continue
    if 'error' in nv or 'error' in ov: continue
    st = ov.get('stops') or {}
    old_stop = (st.get('uptrend_exit') or st.get('volume_low') or st.get('swing_low') or st.get('prev_low') or {}).get('price')
    rows.append({'sid': sid, 't': t, 'p': c[t], 'atr': A, 'up': bool(c[t] > ma20 > ma60), 'date': g.date.iloc[t],
                 'sup': (nv['support'] or {}).get('price'), 'stop': (nv['stop'] or {}).get('price'), 'basis': (nv['stop'] or {}).get('basis'),
                 'tgt': nv['target'], 'kind': nv['target_kind'], 'old_stop': old_stop, 'old_tgt': ov['target']})
print('樣本', len(rows), '多頭', sum(r['up'] for r in rows), '舊版例外（跳過）', old_crash)


def edge_support(sel):
    xs = [r for r in sel if r['sup']]
    da = np.array([(r['sup'] - r['p']) / r['atr'] for r in xs]); pa = rng.permutation(da)
    T = M = TB = MB = 0
    for j, r in enumerate(xs):
        h, l, c = (G[r['sid']][k].values.astype(float) for k in ('high', 'low', 'close'))
        a_ = sup_out(l, c, r['t'], r['sup']); b_ = sup_out(l, c, r['t'], r['p'] + pa[j] * r['atr'])
        T += a_[0]; M += a_[1] or 0; TB += b_[0]; MB += b_[1] or 0
    return 100 * (M / max(T, 1) - MB / max(TB, 1)), len(xs)


def stop_stats(sel, key):
    s = w = 0; rets = []
    for r in sel:
        X = r[key]
        if X is None or X >= r['p']: continue
        c = G[r['sid']].close.values.astype(float)
        o = stop_out(c, r['t'], X); s += o['s']; w += o.get('whip', 0)
        seg = c[r['t'] + 1:r['t'] + H + 1]; br = np.nonzero(seg < X)[0]
        rets.append((seg[br[0]] if len(br) else c[r['t'] + H]) / r['p'] - 1 - 0.00585)
    return 100 * s / max(len(rets), 1), 100 * w / max(s, 1), 100 * np.mean(rets), len(rets)


def stall(sel, key, kind=None):
    xs = [r for r in sel if r[key] and r[key] > r['p'] and (kind is None or r['kind'] == kind)]
    da = np.array([(r[key] - r['p']) / r['atr'] for r in xs]); pa = rng.permutation(da)
    st = n_ = sb = nb = hit = hb = 0
    for j, r in enumerate(xs):
        g = G[r['sid']]; h, c = g.high.values.astype(float), g.close.values.astype(float)
        z = tgt_stall(h, c, r['t'], r[key]); zb = tgt_stall(h, c, r['t'], r['p'] + pa[j] * r['atr'])
        if z is not None: st += z; n_ += 1; hit += 1
        if zb is not None: sb += zb; nb += 1; hb += 1
    return (100 * hit / max(len(xs), 1), 100 * hb / max(len(xs), 1), 100 * st / max(n_, 1), 100 * sb / max(nb, 1), len(xs))


for name, f in (('全部', lambda r: True), ('多頭', lambda r: r['up']), ('前段', lambda r: r['date'] < '20260101'), ('後段', lambda r: r['date'] >= '20260101')):
    sel = [r for r in rows if f(r)]
    e, ns = edge_support(sel)
    sn = stop_stats(sel, 'stop'); so = stop_stats(sel, 'old_stop')
    mm = stall(sel, 'tgt', 'measured'); tn = stall(sel, 'tgt'); to = stall(sel, 'old_tgt')
    print(f"== {name}（{len(sel)}）")
    print(f"   支撐 edge {e:+.1f}（{ns} 個有支撐；研究更正版：k5→60 日低 全部 +3.4；k5 單獨 全部 +2.8 多頭 +2.2 前段 +3.0 後段 +4.4）")
    print(f"   停損 新：打到 {sn[0]:.0f}% 洗 {sn[1]:.0f}% 報酬 {sn[2]:+.2f}  ｜ 舊：打到 {so[0]:.0f}% 洗 {so[1]:.0f}% 報酬 {so[2]:+.2f}"
          f"（研究 夾 1.5～3.5ATR：打到 44%、報酬 全部 +2.55 前段 +2.23 後段 +3.00 多頭 +4.62；舊 +1.47/+1.49/+1.45/+2.85）")
    print(f"   等幅目標 碰到 {mm[0]:.0f}% vs 隨機 {mm[1]:.0f}%、到頂 {mm[2]:.0f}% vs {mm[3]:.0f}%（{mm[4]} 個；研究更正版 全部 碰到 41.6 vs 40.5、到頂 42.8 vs 41.5）")
    print(f"   新目標（全部種類）碰到 {tn[0]:.0f}% vs {tn[1]:.0f}%、到頂 {tn[2]:.0f}% vs {tn[3]:.0f}% ｜ 舊目標 碰到 {to[0]:.0f}% vs {to[1]:.0f}%、到頂 {to[2]:.0f}% vs {to[3]:.0f}%")
from collections import Counter
print('停損依據', Counter(r['basis'] for r in rows), ' 目標種類', Counter(r['kind'] for r in rows))
