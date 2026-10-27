"""B80 暫時檢查：線上 TX／TWII 快照的多層浪名、60 分 K（跟 @fanny55520 最新貼文比對）"""
import json
import httpx

BASE = "https://qiangni-tactics.fly.dev"


def short(c):
    if not c:
        return None
    return {"path": c.get("path"), "cost": c.get("cost"), "wt": c.get("with_trend"), "text": c.get("text"),
            "marks": [[m.get("p"), m.get("text")] for m in c.get("marks") or []],
            "rules": [[r.get("price"), r.get("side"), (r.get("why") or "")[:24]] for r in c.get("rules") or []],
            "tg": [[t.get("price"), t.get("label")] for t in c.get("targets") or []]}


for sym in ("TX", "TWII"):
    try:
        j = httpx.get(f"{BASE}/api/wave/snapshot", params={"sym": sym}, timeout=180).json()
    except Exception as e:  # noqa: BLE001
        print(sym, "失敗", e)
        continue
    print("=" * 30, sym, j.get("generated"), j.get("price"), json.dumps(j.get("asof"), ensure_ascii=False))
    ch = j.get("chart") or {}
    if sym == "TX":
        bars = ch.get("i60") or []
        print("BARS60", json.dumps([[x.get("time"), round(x.get("high")), round(x.get("low")), round(x.get("close"))] for x in bars]))
    for tf, n in (j.get("nest") or {}).items():
        if not n.get("ok"):
            print("NEST", tf, n)
            continue
        print(f"NEST_{sym}_{tf}", json.dumps({"anchor": n.get("anchor"), "extreme": n.get("extreme"), "fib": n.get("fib"),
                                              "tl": n.get("trendline"), "ev": n.get("evidence"), "dr": n.get("daily_role"),
                                              "gates": [[g["k"], g["price"], g["ok"], g["t"]] for g in n.get("gates") or []]},
                                             ensure_ascii=False))
        for k in ("primary", "alternate", "third"):
            print(f"  {k}", json.dumps(short(n.get(k)), ensure_ascii=False))
        print("  TL", json.dumps([[r.get("label"), r.get("price"), r.get("primary"), r.get("alternate"), r.get("changed"),
                                   r.get("step")] for r in n.get("timeline") or []], ensure_ascii=False))
    w = j.get("waves") or {}
    for dg in ("intra", "small"):
        x = w.get(dg) or {}
        pv = [[q.get("i"), q.get("p"), q.get("t")] for q in (x.get("pivots") or [])][-22:]
        print(f"WAVES_{sym}_{dg}", json.dumps({"pivots": pv, "tent": x.get("tentative"),
                                              "primary": {k: (x.get("primary") or {}).get(k) for k in ("kind", "current", "labels")}},
                                             ensure_ascii=False)[:4000])
    print(f"POS_{sym}", json.dumps(j.get("positioning"), ensure_ascii=False)[:3000])
