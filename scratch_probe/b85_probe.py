"""暫時檢查：存一份線上 TX 完整快照（本機重跑多層浪名用）"""
import json

import httpx

j = httpx.get("https://qiangni-tactics.fly.dev/api/wave/snapshot", params={"sym": "TX"}, timeout=240).json()
with open("scratch_probe/snap_TX_now.json", "w") as f:
    json.dump(j, f, ensure_ascii=False)
print(j.get("generated"), len(json.dumps(j)))
