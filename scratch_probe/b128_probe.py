"""暫時檢查（跟進 @fanny55520 11/26）：正式站 TX 快照"""
import json
import httpx
B = "https://qiangni-tactics.fly.dev"
j = None
for force in (1, 0):
    try:
        j = httpx.get(B + "/api/wave/snapshot", params={"sym": "TX", "force": force}, timeout=300).json()
        break
    except Exception as e:  # noqa: BLE001
        print("err", e)
json.dump(j, open("scratch_probe/snap_TX.json", "w"), ensure_ascii=False)
print(j.get("generated"), j.get("price"))
