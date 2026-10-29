"""暫時檢查：線上台指期多層浪名（跟 @fanny55520 10/29 晚上的貼文比對）"""
import json

import httpx

BASE = "https://qiangni-tactics.fly.dev"


def short(c):
    if not c:
        return None
    return {"path": c.get("path"), "cost": c.get("cost"), "wt": c.get("with_trend"), "text": c.get("text"),
            "marks": [[m.get("p"), m.get("text")] for m in c.get("marks") or []],
            "rules": [[r.get("price"), r.get("side"), (r.get("why") or "")[:30]] for r in c.get("rules") or []],
            "tg": [[t.get("price"), t.get("label"), t.get("kind")] for t in c.get("targets") or []]}


for sym in ("TX", "TWII"):
    j = httpx.get(f"{BASE}/api/wave/snapshot", params={"sym": sym}, timeout=240).json()
    print("=" * 20, sym, j.get("generated"), j.get("price"), json.dumps(j.get("asof"), ensure_ascii=False))
    for tf, n in (j.get("nest") or {}).items():
        if not n.get("ok"):
            print(tf, "NOT OK", n.get("note"))
            continue
        print(f"--- {tf} anchor {n['anchor']} ext {n['extreme']} seg {n.get('n_seg')} merged {n.get('merged')} dir {n.get('dir')} cur {n.get('cur_dir')}")
        print("   tl", json.dumps(n.get("trendline"), ensure_ascii=False), "ev", n.get("evidence"), "fib", n.get("fib"))
        for k in ("primary", "alternate", "third"):
            print(f"   {k}", json.dumps(short(n.get(k)), ensure_ascii=False))
        for g in n.get("gates") or []:
            print("   gate", g["k"], g["price"], g["ok"], g["t"])
        for x in n.get("plan") or []:
            print("   plan", x)
        print("   ws", json.dumps(n.get("watershed"), ensure_ascii=False))
        print("   TL", json.dumps([[r.get("label"), r.get("price"), r.get("primary"), r.get("alternate"), r.get("changed")]
                                   for r in n.get("timeline") or []], ensure_ascii=False))
    if sym == "TX":
        ch = j.get("chart") or {}
        print("BARS60", json.dumps([[x.get("time"), x.get("open"), x.get("high"), x.get("low"), x.get("close"), x.get("volume")] for x in (ch.get("i60") or [])[-90:]]))
        print("BARS15", json.dumps([[x.get("time"), x.get("high"), x.get("low"), x.get("close")] for x in (ch.get("i15") or [])[-120:]]))
        w = j.get("waves") or {}
        for dg in ("intra", "intra30", "small", "mid"):
            x = w.get(dg) or {}
            print(f"WAVES_{dg}", json.dumps({"piv": [[q.get("time"), q.get("p"), q.get("t")] for q in (x.get("pivots") or [])][-14:],
                                            "tent": x.get("tentative"),
                                            "primary": {k: (x.get("primary") or {}).get(k) for k in ("kind", "current", "labels")}}, ensure_ascii=False)[:3000])
        print("POS", json.dumps(j.get("positioning"), ensure_ascii=False)[:2000])
