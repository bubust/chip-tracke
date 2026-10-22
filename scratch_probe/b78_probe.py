"""B78 暫時檢查（第 4 輪，最終參數）：跑 research/wave/b78_calibrate.py（真實資料）、防偷看驗證、今天各級數的讀法與複雜結構段落。"""
import json, os, subprocess, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "wave"))
import fetch as FE  # noqa: E402
from wave import engine as E  # noqa: E402

os.makedirs(os.path.join(ROOT, "research", "wave", "data"), exist_ok=True)
df = FE.yahoo("^TWII")
df.to_csv(os.path.join(ROOT, "research", "wave", "data", "TWII.csv"), index=False)
r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "wave", "b78_calibrate.py")], capture_output=True, text=True)
print("calibrate", r.returncode, r.stdout[-3000:], r.stderr[-3000:])
j = json.load(open(os.path.join(ROOT, "research", "wave", "b78_calibration.json"), encoding="utf-8"))
print("JSON", json.dumps({k: j[k] for k in ("data", "p", "e", "complex_share", "pick")}, ensure_ascii=False))
print("ENGINE", E.KIND_PRIOR, E.SUB_PRIOR)
df = df.dropna(subset=["o", "h", "l", "c"])
df = df[(df.h >= df.l) & (df.c > 0)].reset_index(drop=True)
o, h, l, c = (df[k].values.astype(float) for k in ("o", "h", "l", "c"))


def trend(c, t):
    return 0 if t + 1 < 240 else (1 if c[t] > np.mean(c[t - 239:t + 1]) else -1)


for deg in ("small", "mid", "big"):
    piv = E.zigzag(h, l, E.thresholds(h, l, c, deg))
    alt_cx = n = 0
    for t in range(260, len(c)):
        conf, tent = E.state_at(piv, h, l, t)
        p, a = E.primary_alternate(E.count_waves(conf + ([tent] if tent else []), trend=trend(c, t)))
        if p:
            n += 1
            alt_cx += bool(a) and a["kind"] in E.COMPLEX_KINDS and p["kind"] not in E.COMPLEX_KINDS
    print(f"{deg}: 主要劇本是簡單結構、替代劇本是複雜結構的天數 {alt_cx / n:.3f}")
    an = E.analyze(o, h, l, c, deg, trend=trend(c, len(c) - 1))
    for nm in ("primary", "alternate"):
        x = an.get(nm)
        if x:
            print(f"  今天 {deg} {nm}: {x['kind']} {x['current']} {x['score']} {x['text']} | 失效 {x['invalid']} {x['invalid_side']} | "
                  + " ".join(f"{q['disp']}@{df.date[q['i']]}:{q['p']:.0f}" for q in x["labels"]))
r = subprocess.run([sys.executable, os.path.join(ROOT, "research", "wave", "verify_impl.py")], capture_output=True, text=True)
print("verify_impl", r.returncode, r.stdout[-2000:], r.stderr[-2000:])
