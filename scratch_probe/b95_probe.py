"""暫時檢查：存線上 TX、TWII 快照（核對 the.wave.dog.hk 回覆＋@fanny55520 11/5「推敲正確」）"""
import json
import httpx
for sym in ("TX", "TWII"):
    j = httpx.get("https://qiangni-tactics.fly.dev/api/wave/snapshot", params={"sym": sym}, timeout=240).json()
    with open(f"scratch_probe/snap_{sym}.json", "w") as f:
        json.dump(j, f, ensure_ascii=False)
    print(sym, j.get("generated"), j.get("price"), j.get("asof"))
