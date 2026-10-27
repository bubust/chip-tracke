"""B83 暫時檢查：部署後線上台指期 60 分多層浪名（不再空白、分水嶺、兩個版本）"""
import json

import httpx

for sym in ("TX", "TWII"):
    j = httpx.get("https://qiangni-tactics.fly.dev/api/wave/snapshot", params={"sym": sym, "force": 1}, timeout=240).json()
    print("=" * 20, sym, j.get("generated"), j.get("price"))
    for tf, n in (j.get("nest") or {}).items():
        if not n.get("ok"):
            print(tf, "NOT OK", n.get("note"))
            continue
        print(tf, "anchor", n["anchor"]["p"], "seg", n.get("n_seg"), "merged", n.get("merged"),
              "| P", (n.get("primary") or {}).get("path"), "| A", (n.get("alternate") or {}).get("path"),
              "| T", (n.get("third") or {}).get("path"), "| tl", (n.get("trendline") or {}).get("now"))
        for g in n.get("gates") or []:
            print("   ", g["k"], g["price"], g["t"][:150])
        for x in n.get("plan") or []:
            if x.startswith("版本"):
                print("   ", x)
