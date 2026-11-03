"""PLAN-B91 §5 驗證：網站算結構只拿最近 N 根（fbd_live 130＋今天、尾盤補算 260），研究用整段歷史 → 抽 500 個假跌破訊號比對 struct_check vs struct_series
python verify_impl.py snap：抽 3 天比對 13:15 快照：研究（分 K 檔）vs 網站補算（證交所原始每 5 秒 → tail_market.snap_from_5sec）"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
import run          # 先 import run：它把 research/best 加進 sys.path
import engine
import tail_market as TM


def main():
    P = engine.load_panel(run.DATA)
    raw, pool, stc = run.build(P)
    sig = raw & pool & (np.array(P['close'].index) >= run.IS[0])[:, None]
    t_, s_ = np.nonzero(sig)
    rng = np.random.default_rng(1)
    pick = rng.choice(len(t_), size=min(500, len(t_)), replace=False)
    h, l, c = (P[k].to_numpy(float) for k in ('high', 'low', 'close'))
    bad = {130: 0, 260: 0}
    for i in pick:
        t, s = t_[i], s_[i]
        idx = np.nonzero(np.isfinite(c[:t + 1, s]))[0]
        full = stc[3][t, s] == 0
        for n in (130, 260):
            j = idx[-(n + 1):]
            if TM.struct_check(h[j, s], l[j, s])['ok'] != full:
                bad[n] += 1
    print(f'結構：抽 {len(pick)} 個訊號，最近 131 根 vs 整段不一致 {bad[130]}、最近 261 根 vs 整段不一致 {bad[260]}')


if __name__ == '__main__' and len(sys.argv) == 1:
    main()


def verify_snap(days=('20220518', '20240903', '20261028')):
    import time, httpx
    for d in days:
        j = httpx.get('https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX', params={'date': d, 'response': 'json'},
                      headers={'User-Agent': 'Mozilla/5.0'}, timeout=60, verify=False).json()
        a = TM.snap_from_5sec(j.get('data') or [])
        b = run.load_tx_day(d)
        same = all(abs(a[k] - b[k]) < 1e-6 for k in ('y', 'o', 'h', 'l', 'x'))
        print(d, '網站補算', a, '研究', {k: b[k] for k in ('y', 'o', 'h', 'l', 'x')}, '一致' if same else '不一致')
        time.sleep(6)


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'snap':
    verify_snap()
