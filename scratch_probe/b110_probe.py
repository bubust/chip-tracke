"""暫時檢查：等 B110 部署完（wave.js 有 stepsHtml），存線上 TX 快照，確認結論卡回來、有她 11/15 的三關三道"""
import json
import time
import httpx

B = "https://qiangni-tactics.fly.dev"
ok = False
for k in range(40):
    try:
        t = httpx.get(B + "/regime/static/wave.js", timeout=30).text
        if "stepsHtml" in t:
            ok = True
            break
    except Exception as e:  # noqa: BLE001
        print("等部署", k, e)
    time.sleep(20)
print("新版上線", ok, k)
j = None
for force in (1, 1, 0):
    try:
        j = httpx.get(B + "/api/wave/snapshot", params={"sym": "TX", "force": force}, timeout=300).json()
        break
    except Exception as e:  # noqa: BLE001
        print("失敗", force, e)
        time.sleep(20)
with open("scratch_probe/snap_TX.json", "w") as f:
    json.dump(j, f, ensure_ascii=False)
t = ((j.get("nest") or {}).get("60m") or {}).get("tiers") or {}
c = t.get("card") or {}
print(j.get("generated"), j.get("price"), j.get("asof"))
print("tag", t.get("tag"), "| pos", c.get("pos"))
print("steps", bool(c.get("steps")), "| tiles", c.get("tiles"))
