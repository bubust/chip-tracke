"""暫時檢查（B109 第四次）：AI 圓桌今天為什麼沒回應（讀失敗原因）→ 實際跑一次 → 看結果"""
import json
import time
import httpx
B = "https://qiangni-tactics.fly.dev"
out = {}


def brief(d):
    r = d.get("result") or {}
    return {"note": d.get("note"), "fail": d.get("fail"), "providers": d.get("providers"), "usage_today": d.get("usage_today"), "cap": d.get("cap"),
            "manual_left": d.get("manual_left"), "running": d.get("running"),
            "result": {k: r.get(k) for k in ("day", "started", "finished", "trigger", "mode", "participants", "failed", "prompt_chars", "flagged", "log")},
            "moderator": {k: (r.get("moderator") or {}).get(k) for k in ("name", "model", "summary", "stance", "agree_count", "confidence")},
            "round1": {k: {"model": v.get("model"), "stance": v.get("stance")} for k, v in (r.get("round1") or {}).items()},
            "round2": list((r.get("round2") or {}).keys())}


out["before"] = brief(httpx.get(f"{B}/api/wave/panel", timeout=60).json())
print(json.dumps(out["before"], ensure_ascii=False)[:1500])
r = httpx.post(f"{B}/api/wave/panel/run", timeout=60)
out["run"] = {"status": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]}
jid = (out["run"]["body"] or {}).get("job") if r.status_code == 200 else None
t0 = time.time()
while jid and time.time() - t0 < 540:
    time.sleep(10)
    j = httpx.get(f"{B}/api/wave/panel/job/{jid}", timeout=60).json()
    if j.get("status") != "running":
        out["job"] = {**j, "sec": round(time.time() - t0)}
        break
else:
    out["job"] = {"status": "還在跑或沒啟動", "sec": round(time.time() - t0)}
out["after"] = brief(httpx.get(f"{B}/api/wave/panel", timeout=60).json())
with open("scratch_probe/panel.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps(out.get("job"), ensure_ascii=False), json.dumps(out["after"], ensure_ascii=False)[:1500])
