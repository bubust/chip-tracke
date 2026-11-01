"""暫時檢查：部署後正式站的台指期快照（現價、源頭切組、三種日線定位）"""
import time
import httpx
B = "https://qiangni-tactics.fly.dev"
for attempt in range(6):
    try:
        j = httpx.get(f"{B}/api/wave/snapshot", params={"sym": "TX", "force": 1}, timeout=240).json()
        break
    except Exception as e:
        print("retry", e); time.sleep(30)
print("price", j.get("price"), "asof", j.get("asof"), "night", j.get("night"))
nz = (j.get("nest") or {}).get("60m") or {}
print("60m", nz.get("ok"), (nz.get("anchor") or {}).get("p"), (nz.get("primary") or {}).get("path"), (nz.get("alternate") or {}).get("path"), nz.get("evidence"))
src = nz.get("source") or {}
for k in ("three", "five"):
    v = src.get(k) or {}
    print(k, v.get("desc"), [(m["p"], m["text"]) for m in v.get("marks") or []], [t["price"] for t in v.get("targets") or []])
big = j.get("big") or {}
print("big favored", big.get("favored"), [[(l["label"], l["price"]) for l in x["levels"]] for x in big.get("scenarios") or []])
print("pos1d", ((j.get("positioning") or {}).get("1d") or {}).get("lines"))
