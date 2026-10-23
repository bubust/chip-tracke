"""B81 研究共用統計（PLAN-B81 §5b）：有漂移隨機漫步先碰機率、整年重抽 bootstrap、年內置換檢定、BH"""
import math

import numpy as np

SEED = 20261023
N_BOOT = 2000
PERIODS_D1 = (("2000", "2006"), ("2007", "2012"), ("2013", "2019"), ("2020", "2026"))


def drift_params(c, k: int, n: int = 250):
    """進場根 k（含）以前 n 根的對數報酬平均 μ、標準差 σ（不夠 n 根 → None）"""
    if k < n:
        return None
    r = np.diff(np.log(np.asarray(c[k - n:k + 1], float)))
    mu, sd = float(np.mean(r)), float(np.std(r, ddof=1))
    if not math.isfinite(sd) or sd <= 0:
        return None
    return mu, sd


def p_first(entry: float, target: float, stop: float, side: int, mu: float, sd: float) -> float:
    """布朗運動（對數價格、每根漂移 μ、波動 σ）從 entry 出發，先碰 target 的機率；side＝1 多單（target 在上）、−1 空單"""
    if side == 1:
        a, b, m = math.log(target / entry), math.log(entry / stop), mu
    else:
        a, b, m = math.log(entry / target), math.log(stop / entry), -mu
    if a <= 0 or b <= 0:
        return float("nan")
    k = 2.0 * m / (sd * sd)
    if abs(k * max(a, b)) < 1e-9:
        return b / (a + b)
    # P(先到 +a，不先到 −b)＝(1 − e^{k b}) / (e^{−k a} − e^{k b})
    try:
        num = 1.0 - math.exp(k * b)
        den = math.exp(-k * a) - math.exp(k * b)
        p = num / den
    except OverflowError:
        p = 1.0 if k > 0 else 0.0
    return min(1.0, max(0.0, p))


def year_boot(years, stat_fn, rng, n: int = N_BOOT):
    """整年重抽（年份有放回）→ 統計量分布；stat_fn(idx 陣列) → 數值"""
    years = np.asarray(years)
    uy = np.unique(years)
    groups = {y: np.where(years == y)[0] for y in uy}
    out = []
    for _ in range(n):
        pick = rng.choice(uy, size=len(uy), replace=True)
        idx = np.concatenate([groups[y] for y in pick]) if len(pick) else np.array([], int)
        v = stat_fn(idx)
        if v is not None and math.isfinite(v):
            out.append(v)
    return np.array(out)


def perm_within_year(years, groups, values, stat_fn, rng, n: int = N_BOOT):
    """同一年內打亂組別（A／B）→ 雙尾 p；stat_fn(groups, values) → 數值"""
    years = np.asarray(years)
    groups = np.asarray(groups)
    obs = stat_fn(groups, values)
    if obs is None or not math.isfinite(obs):
        return None, None
    idx_by_y = [np.where(years == y)[0] for y in np.unique(years)]
    cnt = 0
    g2 = groups.copy()
    for _ in range(n):
        for ix in idx_by_y:
            g2[ix] = rng.permutation(groups[ix])
        v = stat_fn(g2, values)
        if v is not None and abs(v) >= abs(obs) - 1e-12:
            cnt += 1
    return obs, (cnt + 1) / (n + 1)


def bh(pvals: dict) -> dict:
    """Benjamini–Hochberg：{名字: p} → {名字: q}（p 是 None 的跳過）"""
    items = [(k, p) for k, p in pvals.items() if p is not None]
    m = len(items)
    if not m:
        return {}
    items.sort(key=lambda x: x[1])
    q = {}
    prev = 1.0
    for rank in range(m, 0, -1):
        k, p = items[rank - 1]
        prev = min(prev, p * m / rank)
        q[k] = prev
    return q


def period_of(year: int, periods=PERIODS_D1):
    for a, b in periods:
        if int(a) <= year <= int(b):
            return f"{a}–{b[2:]}"
    return None
