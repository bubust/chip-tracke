"""B78 暫時檢查（第 2 輪）：真實加權指數上，新結構各當主要劇本的比例 vs KIND_PRIOR／SUB_PRIOR（擴散型）；
同一份報酬打亂後（隨機漫步、沒有結構）的比例當基準；防偷看驗證；跟舊引擎的一致率；大、中級的複雜結構段落列表。"""
import os, sys, subprocess, time
import numpy as np
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
KS = ["impulse", "correction", "combo", "tri_c", "tri_x", "dia_c", "dia_x"]
P0, S0 = dict(E.KIND_PRIOR), dict(E.SUB_PRIOR)


def kk(x):
    if x["kind"] in ("triangle", "diagonal"):
        return x["kind"][:3] + ("_x" if x["corr_kind"] == "expanding" else "_c")
    return x["kind"]


def trend(c, t):
    return 0 if t + 1 < 240 else (1 if c[t] > np.mean(c[t - 239:t + 1]) else -1)


def collect(h, l, c, deg):
    E.KIND_PRIOR = {k: 0.0 for k in P0}
    E.SUB_PRIOR = {k: 0.0 for k in S0}
    piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
    rows = []
    for t in range(260, len(c)):
        conf, tent = E.state_at(piv, h, l, t)
        best = {k: 9.0 for k in KS}
        for x in E.count_waves(conf + ([tent] if tent else []), trend=trend(c, t)):
            best[kk(x)] = min(best[kk(x)], x["score"])
        rows.append([best[k] for k in KS])
    E.KIND_PRIOR, E.SUB_PRIOR = dict(P0), dict(S0)
    return np.array(rows)


def shares(a, p, e):
    a = a + np.array([0, 0, p, p, p + e, p, p + e])
    v = a.min(1) < 9
    w = a[v].argmin(1)
    return [np.mean(w == i) for i in range(len(KS))]


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
null = {deg: np.vstack([collect(*shuffled(s), deg) for s in (1, 2, 3, 4, 5)]) for deg in ("small", "mid", "big")}
print(f"collect {time.time() - t0:.0f}s")
for p in (0.06, 0.09, 0.12, 0.15):
    for e in (0.0, 0.03, 0.06):
        for name, D in (("REAL", real), ("NULL", null)):
            print(f"p={p:.2f} e={e:.2f} {name} " + " | ".join(
                f"{deg}: " + " ".join(f"{k} {s:.3f}" for k, s in zip(KS, shares(D[deg], p, e))) + f" cx {sum(shares(D[deg], p, e)[2:]):.3f}"
                for deg in D))

print("KIND_PRIOR", E.KIND_PRIOR, "SUB_PRIOR", E.SUB_PRIOR)
for deg in ("small", "mid", "big"):
    piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
    same = tot = 0
    kinds_new = {}
    eps = []
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
            kinds_new[kk(pn)] = kinds_new.get(kk(pn), 0) + 1
        if pn and pn["kind"] in ("combo", "triangle", "diagonal"):
            key = (pn["kind"], pn["labels"][0]["i"])
            if eps and eps[-1]["key"] == key and eps[-1]["t1"] == t - 1:
                eps[-1].update(t1=t, last=pn)
            else:
                eps.append({"key": key, "t0": t, "t1": t, "last": pn})
    print(f"{deg}: 跟舊引擎主要劇本相同 {same / tot:.3f}（{tot} 天）；新引擎主要劇本 " +
          ", ".join(f"{k} {v / tot:.3f}" for k, v in sorted(kinds_new.items())))
    if deg != "small":
        print(f"  複雜結構段落 {len(eps)} 個；最長 12 個：")
        for ep in sorted(eps, key=lambda z: z["t0"] - z["t1"])[:12]:
            x = ep["last"]
            print(f"   {df.date[ep['t0']]}～{df.date[ep['t1']]} {ep['t1'] - ep['t0'] + 1}天 {kk(x)} {x['corr_kind']} 到 {x['current']} | "
                  + " ".join(f"{q['disp']}@{df.date[q['i']][2:]}:{q['p']:.0f}" for q in x["labels"]))
    a = E.analyze(o, h, l, c, deg, trend=trend(c, len(c) - 1))
    for nm in ("primary", "alternate"):
        x = a.get(nm)
        if x:
            print(f"  今天 {deg} {nm}: {x['kind']} {x['current']} {x['score']} {x['text']} | 失效 {x['invalid']} {x['invalid_side']} | "
                  + " ".join(f"{q['disp']}@{df.date[q['i']]}:{q['p']:.0f}" for q in x["labels"]))

r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "wave", "verify_impl.py")], capture_output=True, text=True)
print("verify_impl", r.returncode, r.stdout[-2000:], r.stderr[-2000:])
