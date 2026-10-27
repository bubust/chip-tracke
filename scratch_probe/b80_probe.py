"""B80 暫時檢查：把線上 TX／TWII 快照的分 K、日 K 轉折存成檔案（本機重跑多層浪名用）"""
import json
import httpx

BASE = "https://qiangni-tactics.fly.dev"
out = {}
for sym in ("TX", "TWII"):
    j = httpx.get(f"{BASE}/api/wave/snapshot", params={"sym": sym}, timeout=180).json()
    ch = j.get("chart") or {}
    out[sym] = {"generated": j.get("generated"), "price": j.get("price"),
                "i60": ch.get("i60"), "i30": ch.get("i30"), "i15": ch.get("i15"),
                "daily": (ch.get("bars") or [])[-120:],
                "small": {k: (j.get("waves") or {}).get("small", {}).get(k) for k in ("pivots", "tentative", "primary", "alternate")},
                "nest_keys": list((j.get("nest") or {}).keys()), "chart_keys": list(ch.keys())}
with open("scratch_probe/live.json", "w") as f:
    json.dump(out, f, ensure_ascii=False)
print({k: (len(v["i60"] or []), len(v["i30"] or []), len(v["i15"] or []), v["chart_keys"]) for k, v in out.items()})
