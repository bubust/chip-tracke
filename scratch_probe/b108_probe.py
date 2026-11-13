"""暫時檢查：存線上 TX 快照（B108：價格更新時間、結論卡改寫）＋量一下即時報價多久回來"""
import json
import time
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
t = time.time()
r = httpx.get("https://qiangni-tactics.fly.dev/api/wave/snapshot", params={"sym": "TX"}, timeout=120)
print("快取回應", round(time.time() - t, 2), "秒", len(r.content), "bytes")
