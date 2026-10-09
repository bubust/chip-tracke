"""PLAN-COURSE 講義策略：python -m pytest tests/test_course2.py -q
重點：整段算的第 i 天＝只給到第 i 天的資料算出來的最後一天（不偷看未來）"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import course2 as C  # noqa: E402


def _walk(n=420, seed=1):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.001, 0.025, n)
    r[rng.integers(0, n, 12)] = 0.0995                    # 幾天漲停
    c = 50 * np.exp(np.cumsum(r))
    o = c * (1 + rng.normal(0, 0.008, n))
    o[1:] = np.where(r[1:] > 0.09, c[1:], o[1:])          # 漲停日一字
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.01, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.01, n)))
    v = rng.lognormal(8, 0.6, n)
    v[rng.integers(0, n, 20)] *= 5
    return o, h, l, c, v


FNS = [
    ("abreak3", lambda o, h, l, c, v: C.sig_abreak(o, h, l, c, v, k=3)[0]),
    ("abreak8_vol", lambda o, h, l, c, v: C.sig_abreak(o, h, l, c, v, k=8, vmult=1.5, rally=0.2)[0]),
    ("dbreak", lambda o, h, l, c, v: C.sig_dbreak(o, h, l, c, v, k=3)[0]),
    ("strong_break", lambda o, h, l, c, v: C.sig_strong(o, h, l, c, v, k=3, nlow=2, trigger="break")[0]),
    ("strong_conf", lambda o, h, l, c, v: C.sig_strong(o, h, l, c, v, k=3, nlow=2, trigger="confirm")[0]),
    ("fib", lambda o, h, l, c, v: C.sig_fib(o, h, l, c, v, rally=0.15, zone=0.382)[0]),
    ("bottom", lambda o, h, l, c, v: C.sig_bottom_rise(o, h, l, c, v, m1=1.5, width=0.4, shrink=2.0, m2=0.5, near_low=10, min_plat=3)[0]),
    ("limit_open", lambda o, h, l, c, v: C.sig_limit_open(o, h, l, c, v, n=1, m=1.0, opened="touch")[0]),
    ("dist", lambda o, h, l, c, v: C.sig_distribution(o, h, l, c, v) > 0),
]


@pytest.mark.parametrize("name,fn", FNS)
def test_no_lookahead(name, fn):
    hits = 0
    for seed in (1, 2, 3):
        o, h, l, c, v = _walk(seed=seed)
        full = fn(o, h, l, c, v)
        hits += int(full.sum())
        rng = np.random.default_rng(seed + 10)
        sigdays = {int(j) for j in np.nonzero(full)[0] if j >= 150}
        days = sorted(set(rng.integers(150, len(c), 40).tolist()) | sigdays)
        for i in days:
            part = fn(o[:i + 1], h[:i + 1], l[:i + 1], c[:i + 1], v[:i + 1])
            assert part[-1] == full[i], (name, seed, i)
    assert hits > 0, f"{name} 在測試資料上完全沒有訊號，測試沒意義"


def test_pivots_confirm_after_k():
    h = np.array([1, 2, 3, 9, 3, 2, 1, 2, 3], float)
    l = h - 0.5
    typ, val, idx = C.swing_seq(h, l, 3)
    assert typ[5, 0] == 0                      # 高點在第 3 根，第 5 根收盤還不知道
    assert typ[6, 0] == C.HIGH and val[6, 0] == 9 and idx[6, 0] == 3


def test_market_dist_day():
    c = np.array([100, 99, 98, 97, 99, 101, 103, 102, 101, 100, 98, 96], float)
    oh = np.array([0.4] * 12)
    oh[9] = 0.55
    md, brk, d = C.market_dist_day(c, oh, k=3)
    # 低點 97（第 3 根）在第 6 根確認；第 11 根收 96 第一次跌破 97，第 9 根過熱 > 0.5 → 出貨日
    assert brk[11] and md[11] and d[11] == 97
    oh[9] = 0.45
    md2, _, _ = C.market_dist_day(c, oh, k=3)
    assert not md2[11]


def test_revenue_effective_date():
    assert C.latest_revenue_ym("20260312") == "202601"
    assert C.latest_revenue_ym("20260313") == "202602"
    assert C.latest_revenue_ym("20260105") == "202511"
    assert not C.revenue_available("202602", "20260312")
    assert C.revenue_available("202602", "20260313")
    assert C.revenue_available("202512", "20260113")


def test_limit_open_basic():
    pc0 = 100.0
    c = [pc0]
    o = [pc0]
    for _ in range(3):                           # 3 天一字漲停
        lim = C.limit_up_price(c[-1])
        c.append(lim); o.append(lim)
    lim = C.limit_up_price(c[-1])
    o.append(lim); c.append(lim * 0.97)         # 第 4 天開漲停、收盤打開
    c, o = np.array(c), np.array(o)
    h = np.maximum(o, c); l = np.minimum(o, c)
    v = np.array([1000, 50, 40, 30, 600], float)
    sig, info = C.sig_limit_open(o, h, l, c, v, n=2, m=3)
    assert sig[-1] and info["streak"][-1] == 3
    sig2, _ = C.sig_limit_open(o, h, l, c, v, n=4, m=3)
    assert not sig2[-1]


def test_limit_up_price_ticks():
    assert C.limit_up_price(9.92) == 10.9
    assert C.limit_up_price(10.25) == 11.25
    assert C.limit_up_price(455.0) == 500.0
    assert C.limit_up_price(950.0) == 1045.0


def test_bottom_rise_designed():
    # 跌到底 → 爆量長紅 → 8 天量縮小平台 → 帶量突破
    c = list(np.linspace(100, 60, 260)) + [63.0] + [62.5, 62.8, 62.2, 62.9, 62.6, 62.4, 62.7, 62.5] + [65.0]
    c = np.array(c)
    o = np.r_[c[0], c[:-1]]
    o[260] = 60.0
    h = np.maximum(o, c) * 1.003
    l = np.minimum(o, c) * 0.997
    v = np.full(len(c), 1000.0)
    v[260] = 5000; v[261:269] = 1500; v[269] = 4000
    sig, info = C.sig_bottom_rise(o, h, l, c, v)
    assert sig[269] and sig.sum() == 1
    assert info["stop"][269] == pytest.approx(l[260:269].min())
