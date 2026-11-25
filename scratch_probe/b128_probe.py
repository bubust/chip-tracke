"""暫時檢查：加權 11/12～11/25 收盤（對照借券金額）"""
import json, httpx
j = httpx.get("https://qiangni-tactics.fly.dev/api/wave/snapshot", timeout=240).json()
bars = (j.get("chart") or {}).get("bars") or []
json.dump(bars[-10:], open("scratch_probe/b128_live.json", "w", encoding="utf-8"), ensure_ascii=False)
