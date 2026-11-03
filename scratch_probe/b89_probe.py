"""暫時檢查：存線上 TX 快照（比對 @fanny55520 11/3 下午的三種細微脈動）"""
import json
import httpx
j = httpx.get("https://qiangni-tactics.fly.dev/api/wave/snapshot", params={"sym": "TX"}, timeout=240).json()
with open("scratch_probe/snap_TX.json", "w") as f:
    json.dump(j, f, ensure_ascii=False)
print(j.get("generated"), j.get("price"), j.get("asof"))
