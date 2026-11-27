"""暫時檢查（B138 上線確認）：正式站個股深度分析的借券"""
import json
import httpx
B = "https://qiangni-tactics.fly.dev"
out = {}
for sid in ("3481", "2330"):
    try:
        j = httpx.get(B + f"/api/stock/{sid}/deep-analysis", params={"fresh": 1}, timeout=300).json()
        ch = j.get("chip") or {}
        out[sid] = {"sbl": {k: v for k, v in (ch.get("sbl") or {}).items() if k != "series"}, "n": len((ch.get("sbl") or {}).get("series") or []),
                    "err": ch.get("error") or j.get("error"), "short": (ch.get("margin") or {}).get("short")}
    except Exception as e:  # noqa: BLE001
        out[sid] = {"exc": repr(e)[:200]}
json.dump(out, open("scratch_probe/snap_TX.json", "w"), ensure_ascii=False)
print(out)
