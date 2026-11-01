"""暫時檢查：存線上 TX／TWII 完整快照（本機重跑多層浪名用）＋確認融資維持率上線"""
import json
import httpx
B = "https://qiangni-tactics.fly.dev"
for sym in ("TX", "TWII"):
    j = httpx.get(f"{B}/api/wave/snapshot", params={"sym": sym}, timeout=240).json()
    with open(f"scratch_probe/snap_{sym}.json", "w") as f:
        json.dump(j, f, ensure_ascii=False)
    print(sym, j.get("generated"), j.get("price"), len(json.dumps(j)))
for u in ("/api/margin/market", "/api/screen/strategy/S_MAINT_LOW", "/api/margin/maint/3481"):
    try:
        r = httpx.get(B + u, timeout=120)
        t = r.text
        print(u, r.status_code, t[:600])
    except Exception as e:
        print(u, e)
