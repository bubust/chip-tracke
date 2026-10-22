"""B78 暫時檢查：真實加權指數上，新結構（複合修正、三角形、楔形）各當主要劇本的比例 vs KIND_PRIOR；
同一份報酬打亂後（隨機漫步、沒有結構）的比例當基準；防偷看驗證；跟舊引擎（只有推動浪＋A-B-C）的一致率。"""
import os, sys, subprocess, time
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "wave"))
import fetch as FE  # noqa: E402
from wave import engine as E  # noqa: E402

os.makedirs(os.path.join(ROOT, "research", "wave", "data"), exist_ok=True)
df = FE.yahoo("^TWII")
df.to_csv(os.path.join(ROOT, "research", "wave", "data", "TWII.csv"), index=False)
df = df.dropna(subset=["o", "h", "l", "c"])
df = df[(df.h >= df.l) & (df.c > 0)].reset_index(drop=True)
print("TWII", len(df), df.date.iloc[0], df.date.iloc[-1])
o, h, l, c = (df[k].values.astype(float) for k in ("o", "h", "l", "c"))
KINDS = ["impulse", "correction", "combo", "triangle", "diagonal"]
PRIOR0 = dict(E.KIND_PRIOR)


def trend(c, t):
    return 0 if t + 1 < 240 else (1 if c[t] > np.mean(c[t - 239:t + 1]) else -1)


def collect(h, l, c, deg):
    E.KIND_PRIOR = {k: 0.0 for k in KINDS}
    piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
    rows = []
    for t in range(260, len(c)):
        conf, tent = E.state_at(piv, h, l, t)
        best = {k: 9.0 for k in KINDS}
        for x in E.count_waves(conf + ([tent] if tent else []), trend=trend(c, t)):
            best[x["kind"]] = min(best[x["kind"]], x["score"])
        rows.append([best[k] for k in KINDS])
    E.KIND_PRIOR = dict(PRIOR0)
    return np.array(rows)


def shares(a, p):
    a = a + np.array([0, 0, p, p, p])
    v = a.min(1) < 9
    w = a[v].argmin(1)
    return [np.mean(w == i) for i in range(5)]


def shuffled(seed):
    rng = np.random.default_rng(seed)
    lr = np.diff(np.log(c))
    idx = rng.permutation(len(lr))
    cc = c[0] * np.exp(np.concatenate([[0], np.cumsum(lr[idx])]))
    hh = np.concatenate([[h[0]], (h[1:] / c[1:])[idx]]) * cc
    ll = np.concatenate([[l[0]], (l[1:] / c[1:])[idx]]) * cc
    return hh, ll, cc


t0 = time.time()
real = {deg: collect(h, l, c, deg) for deg in ("small", "mid", "big")}
null = {deg: np.vstack([collect(*shuffled(s), deg) for s in (1, 2, 3)]) for deg in ("small", "mid", "big")}
print(f"collect {time.time() - t0:.0f}s")
for p in (0.0, 0.03, 0.06, 0.09, 0.12, 0.15, 0.2):
    for name, D in (("REAL", real), ("NULL", null)):
        print(f"p={p:.2f} {name} " + " | ".join(
            f"{deg}: " + " ".join(f"{k[:3]} {s:.3f}" for k, s in zip(KINDS, shares(D[deg], p))) for deg in D))

# 跟舊引擎一致率＋現在各級數的讀法（用目前 engine 的 KIND_PRIOR）
print("KIND_PRIOR", E.KIND_PRIOR)
for deg in ("small", "mid", "big"):
    piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
    same = tot = 0
    kinds_new = {}
    for t in range(260, len(c)):
        conf, tent = E.state_at(piv, h, l, t)
        pts = conf + ([tent] if tent else [])
        E.ENABLE_COMPLEX = True
        pn, _ = E.primary_alternate(E.count_waves(pts, trend=trend(c, t)))
        E.ENABLE_COMPLEX = False
        po, _ = E.primary_alternate(E.count_waves(pts, trend=trend(c, t), max_back=9))
        E.ENABLE_COMPLEX = True
        if pn and po:
            tot += 1
            same += (pn["kind"], pn["current"], pn["dir"], pn["start"]) == (po["kind"], po["current"], po["dir"], po["start"])
            kinds_new[pn["kind"]] = kinds_new.get(pn["kind"], 0) + 1
    print(f"{deg}: 跟舊引擎主要劇本相同 {same / tot:.3f}（{tot} 天）；新引擎主要劇本結構 " +
          ", ".join(f"{k} {v / tot:.3f}" for k, v in sorted(kinds_new.items())))
    a = E.analyze(o, h, l, c, deg, trend=trend(c, len(c) - 1))
    for nm in ("primary", "alternate"):
        x = a.get(nm)
        if x:
            print(f"  今天 {deg} {nm}: {x['kind']} {x['current']} {x['score']} {x['text']} | 失效 {x['invalid']} {x['invalid_side']} | "
                  + " ".join(f"{q['disp']}@{df.date[q['i']]}:{q['p']:.0f}" for q in x["labels"]))

# 描述用（參數已固定，不拿來調參數）：各結構主要劇本那幾天之後 20 天報酬
fwd = np.full(len(c), np.nan)
fwd[:-20] = c[20:] / c[:-20] - 1
piv = E.zigzag(h, l, E.thresholds(h, l, c, "mid"))
grp = {}
for t in range(260, len(c) - 20):
    conf, tent = E.state_at(piv, h, l, t)
    p, _ = E.primary_alternate(E.count_waves(conf + ([tent] if tent else []), trend=trend(c, t)))
    if p:
        key = f"{p['kind'][:3]}{'+' if p['dir'] > 0 else '-'}:{p['current']}"
        grp.setdefault(key, []).append(fwd[t])
allv = np.array([v for vs in grp.values() for v in vs])
print(f"mid 全部 n={len(allv)} 20 天平均 {allv.mean():+.4f} 上漲比例 {np.mean(allv > 0):.3f}")
for k in sorted(grp):
    v = np.array(grp[k])
    print(f"  {k:10s} n={len(v):5d} 平均 {v.mean():+.4f} 上漲比例 {np.mean(v > 0):.3f}")

r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "wave", "verify_impl.py")], capture_output=True, text=True)
print("verify_impl", r.returncode, r.stdout[-2000:], r.stderr[-2000:])
