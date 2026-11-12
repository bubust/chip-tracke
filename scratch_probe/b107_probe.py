"""暫時檢查：存線上 TX 快照（跟進 @fanny55520 11/12：5-1 在 44,911 結束、5-2-A 測 42,371）"""
import json
import httpx
j = None
for force in (1, 0):
    try:
        j = httpx.get("https://qiangni-tactics.fly.dev/api/wave/snapshot", params={"sym": "TX", "force": force}, timeout=300).json()
        break
    except Exception as e:  # noqa: BLE001
        print("失敗", force, e)
with open("scratch_probe/snap_TX.json", "w") as f:
    json.dump(j, f, ensure_ascii=False)
print(j.get("generated"), j.get("price"), j.get("asof"))
