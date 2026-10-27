"""B83 暫時檢查：存一份線上 TX／TWII 完整快照（本機畫面檢查用）"""
import json

import httpx

for sym in ("TX", "TWII"):
    j = httpx.get("https://qiangni-tactics.fly.dev/api/wave/snapshot", params={"sym": sym}, timeout=180).json()
    with open(f"scratch_probe/snap_{sym}.json", "w") as f:
        json.dump(j, f, ensure_ascii=False)
    print(sym, j.get("generated"), len(json.dumps(j)))
