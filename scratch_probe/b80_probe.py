"""B80 暫時檢查：線上 TX／TWII 快照的多層浪名、60／30 分 K（跟 @fanny55520 最新貼文比對）"""
import json
import httpx

BASE = "https://qiangni-tactics.fly.dev"
for sym in ("TX", "TWII"):
    try:
        j = httpx.get(f"{BASE}/api/wave/snapshot", params={"sym": sym}, timeout=180).json()
    except Exception as e:  # noqa: BLE001
        print(sym, "失敗", e)
        continue
    print("=" * 30, sym, j.get("generated"), j.get("price"), j.get("asof"))
    ch = j.get("chart") or {}
    for k in ("i60", "i30"):
        bars = ch.get(k) or []
        print(f"BARS_{sym}_{k}", json.dumps([[x.get("time"), x.get("open"), x.get("high"), x.get("low"), x.get("close")] for x in bars]))
    for tf, n in (j.get("nest") or {}).items():
        n = dict(n)
        tl = n.pop("timeline", None)
        print(f"NEST_{sym}_{tf}", json.dumps(n, ensure_ascii=False))
        print(f"TIMELINE_{sym}_{tf}", json.dumps(tl, ensure_ascii=False))
    w = j.get("waves") or {}
    for dg in ("intra", "intra30", "small", "mid"):
        x = w.get(dg) or {}
        print(f"WAVES_{sym}_{dg}", json.dumps({"pivots": x.get("pivots"), "tentative": x.get("tentative"),
                                              "primary": x.get("primary"), "alternate": x.get("alternate")}, ensure_ascii=False)[:20000])
    print(f"POS_{sym}", json.dumps(j.get("positioning"), ensure_ascii=False))
    print(f"DAILY_{sym}", json.dumps((ch.get("bars") or [])[-40:], ensure_ascii=False))
