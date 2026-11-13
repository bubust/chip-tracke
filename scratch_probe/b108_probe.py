"""暫時檢查（B108 修正後）：快照裡結論卡回來了沒、即時報價"""
import json
import httpx
B = "https://qiangni-tactics.fly.dev"
out = {}
r = httpx.get(f"{B}/api/wave/quote", params={"sym": "TX"}, timeout=60)
out["quote"] = r.json() if r.status_code == 200 else {"status": r.status_code}
j = httpx.get(f"{B}/api/wave/snapshot", params={"sym": "TX", "force": 1}, timeout=300).json()
t = ((j.get("nest") or {}).get("60m") or {}).get("tiers") or {}
out["snap"] = {"generated": j.get("generated"), "price": j.get("price"), "asof": j.get("asof"), "ladder_text": j.get("ladder_text"),
               "tag": t.get("tag"), "status": t.get("status"), "card": t.get("card"), "advice": (j.get("advice") or {}).get("headline")}
with open("scratch_probe/check.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
with open("scratch_probe/snap_TX.json", "w") as f:
    json.dump(j, f, ensure_ascii=False)
print(json.dumps(out, ensure_ascii=False)[:1200])
