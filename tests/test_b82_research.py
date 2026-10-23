"""PLAN-B82 研究：資料時間點不偷看（融資前一天、月營收 15 日／2 月 20 日）、條件、升降單位、進場時機成交規則"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'research', 'b82'))
import common as CM  # noqa: E402


@pytest.mark.parametrize('p,t', [(9.99, 0.01), (10, 0.05), (49.95, 0.05), (50, 0.1), (99.9, 0.1), (100, 0.5), (499.5, 0.5), (500, 1.0), (999, 1.0), (1000, 5.0)])
def test_tick(p, t):
    assert float(CM.tick(p)) == pytest.approx(t)


def test_rev_avail_date():
    assert CM.rev_avail_date('202601') == '20260220'      # 1 月營收：春節常延後
    assert CM.rev_avail_date('202603') == '20260415'
    assert CM.rev_avail_date('202612') == '20270115'


def test_align_revenue_never_uses_unpublished_month():
    sids = np.array(['1101'])
    rev = {}
    for ym, y in (('202511', 11), ('202512', 12), ('202601', 1), ('202602', 2), ('202603', 3)):
        rev[ym] = pd.DataFrame({'rev': [100.0 + y], 'yoy': [float(y)], 'cum_yoy': [float(y) / 2]}, index=pd.Index(['1101'], name='stock_id'))
    dates = ['20260114', '20260115', '20260219', '20260220', '20260314', '20260315', '20260415']
    R = CM.align_revenue(rev, dates, sids)
    assert list(R['yoy'][:, 0]) == [11, 12, 12, 1, 1, 2, 3]
    assert R['yoy_prev'][3, 0] == 12                       # 2/20 看 1 月，前一個月＝12 月
    for t, d in enumerate(dates):                          # 任何一天用到的月份都已公布
        used = {11: '202511', 12: '202512', 1: '202601', 2: '202602', 3: '202603'}[int(R['yoy'][t, 0])]
        assert CM.rev_avail_date(used) <= d


def test_high12_needs_full_year():
    sids = np.array(['A'])
    rev = {}
    for k in range(13):
        y, m = 2025, 1 + k
        if m > 12:
            y, m = 2026, m - 12
        rev[f'{y}{m:02d}'] = pd.DataFrame({'rev': [100.0 + k], 'yoy': [1.0], 'cum_yoy': [1.0]}, index=pd.Index(['A'], name='stock_id'))
    R = CM.align_revenue(rev, ['20250315', '20260215'], sids)   # 2025-02 的前 11 個月不齊、2026-01 齊了而且是新高
    assert np.isnan(R['high12'][0, 0]) and R['high12'][1, 0] == 1
    assert CM.rev_flags(R)['M4'][:, 0].tolist() == [False, True]


def test_chip_flags_margin_uses_previous_day_and_streaks():
    T = 9
    f = np.ones((T, 1)); f[3] = -1
    inst = {'foreign': f * 1000, 'trust': np.ones((T, 1)) * 1000, 'dealer': np.zeros((T, 1))}
    margin = np.full((T, 1), 100.0); margin[7] = 50
    C = CM.chip_flags(inst, {'margin': margin}, np.full((T, 1), 10.0))
    assert C['C7'][7, 0] == False and C['C7'][8, 0] == True     # noqa: E712  當天融資 21:00 才公布 → 第 7 天看不到
    assert [bool(x) for x in C['C3'][:, 0]] == [False, False, True, False, False, False, True, True, True]
    assert C['C4'][0, 0] == False and C['C4'][1, 0] == True       # noqa: E712
    assert C['C6'][2, 0] == True                                    # noqa: E712  2 張 ≥ 10 張 × 10%
    assert C['C5'][3, 0] == False and C['C5'][4, 0] == True        # noqa: E712  前 5 天不齊不算


def test_res_counts():
    a = np.zeros((6, 1), bool); b = np.zeros((6, 1), bool); c = np.zeros((6, 1), bool)
    a[0] = True; b[3] = True; c[3] = True
    F = CM.res_flags({'A': a, 'B': b, 'C': c})
    assert F['K1'][3, 0] and not F['K1'][0, 0]
    assert F['K3'][3, 0] and F['K3'][4, 0] and not F['K3'][5, 0]
    today, five = CM.res_counts({'A': a, 'B': b, 'C': c})
    assert five[3, 0] == 3 and five[4, 0] == 3 and five[5, 0] == 2 and five[0, 0] == 1


def _fake_sim(o, h, l, c):
    from sim_entry import SimE
    s = object.__new__(SimE)
    s.o, s.h, s.l, s.c = (np.array(x, float).reshape(-1, 1) for x in (o, h, l, c))
    s.T, s.S = s.c.shape
    s.cumfac = np.ones_like(s.c)
    s.dates = np.array([f'2026010{i + 1}' for i in range(s.T)])
    s.last_idx_all = s.T - 1
    return s


def test_e1_breakout_needs_one_tick_and_not_one_price_limit():
    sig = np.zeros((4, 1), bool); sig[0] = True
    sim = _fake_sim([10, 9.9, 10, 10], [10, 10.05, 10, 10], [9.8, 9.8, 9.9, 9.9], [9.9, 10, 10, 10])
    t, s, e, px, intra = sim.entries_v(sig, 'E1')
    assert list(e) == [1] and px[0] == pytest.approx(10.05) and intra[0]
    sim2 = _fake_sim([10, 9.9, 10, 10], [10, 10.04, 10, 10], [9.8, 9.8, 9.9, 9.9], [9.9, 10, 10, 10])
    assert len(sim2.entries_v(sig, 'E1')[0]) == 0                        # 只碰到訊號高、沒過 1 檔
    sim3 = _fake_sim([10, 10.85, 10, 10], [10, 10.85, 10, 10], [9.8, 10.85, 9.9, 9.9], [9.9, 10.85, 10, 10])
    assert len(sim3.entries_v(sig, 'E1')[0]) == 0                        # 一價漲停買不到


def test_e2_limit_must_trade_through_and_no_tp_on_entry_day():
    sig = np.zeros((6, 1), bool); sig[0] = True
    # 訊號收 100 → 掛 98、要最低 ≤ 97.9；第 1 天最低 97.95 不算、第 2 天 97.9 買到 98（盤中）
    o = [100, 99, 99, 99, 99, 99]; h = [101, 100, 125, 100, 100, 100]; l = [99, 97.95, 97.9, 98, 98, 98]; c = [100, 99, 99, 99, 99, 99]
    sim = _fake_sim(o, h, l, c)
    t, s, e, px, intra = sim.entries_v(sig, 'E2')
    assert list(e) == [2] and px[0] == pytest.approx(98) and intra[0]
    tr = sim.trades_v(sig, 'E2')
    assert len(tr) == 1 and tr['why'].iloc[0] != 1                       # 進場當天最高 125 ≥ 停利，但盤中買進那天不算停利
    # 進場當天最低碰到停損 → 停損
    l2 = [99, 99, 90.0, 98, 98, 98]
    sim2 = _fake_sim(o, [101, 100, 100, 100, 100, 100], l2, c)
    tr2 = sim2.trades_v(sig, 'E2')
    assert tr2['why'].iloc[0] == 2 and tr2['x'].iloc[0] == 2


def test_e4_confirmation_buys_day_after():
    sig = np.zeros((5, 1), bool); sig[0] = True
    sim = _fake_sim([10, 10, 10.5, 10.5, 10.5], [10, 10.6, 10.6, 10.6, 10.6], [9.8, 9.9, 10.4, 10.4, 10.4], [10, 10.4, 10.5, 10.5, 10.5])
    t, s, e, px, intra = sim.entries_v(sig, 'E4')
    assert list(e) == [2] and px[0] == 10.5 and not intra[0]
    sim2 = _fake_sim([10, 10.5, 10.5, 10.5, 10.5], [10, 10.6, 10.6, 10.6, 10.6], [9.8, 9.9, 10.4, 10.4, 10.4], [10, 10.4, 10.5, 10.5, 10.5])
    assert len(sim2.entries_v(sig, 'E4')[0]) == 0                        # 隔天收黑（10.4 < 開 10.5）不買
