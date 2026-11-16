"""暫時檢查（跟進 @fanny55520 11/16）：正式站 TX 快照（日夜盤基準、結論卡、夜盤 15 分 K）＋鉅亨報價原始欄位＋期交所 11/16 日行情（收盤價 vs 結算價）"""
import json
import httpx

B = "https://qiangni-tactics.fly.dev"
UA = {"User-Agent": "Mozilla/5.0"}
out = {}
try:
    j = httpx.get(B + "/api/wave/snapshot", params={"sym": "TX", "force": 1}, timeout=300).json()
    t = ((j.get("nest") or {}).get("60m") or {}).get("tiers") or {}
    out["snap"] = {k: j.get(k) for k in ("generated", "price", "prev_close", "chg", "chg_pct", "sess", "asof")}
    out["tiers"] = {"tag": t.get("tag"), "status": t.get("status"), "card": t.get("card"),
                    "sub": (((t.get("ext3") or {}).get("paths") or {}).get("push") or {}).get("sub")}
    ch = j.get("chart") or {}
    out["bars"] = (ch.get("bars") or [])[-4:]
    out["i15"] = (ch.get("i15") or [])[-140:]
    out["i60"] = (ch.get("i60") or [])[-40:]
    w = j.get("waves") or {}
    out["waves"] = {k: {"pivots": (w.get(k) or {}).get("pivots", [])[-10:], "tentative": (w.get(k) or {}).get("tentative")}
                    for k in ("small", "intra", "intra30", "intra15")}
    out["intra_atr"] = {"atr60": (j.get("intra") or {}).get("atr"), "atr15": ((j.get("intra") or {}).get("m15") or {}).get("atr")}
    json.dump(j, open("scratch_probe/snap_TX.json", "w"), ensure_ascii=False)
except Exception as e:  # noqa: BLE001
    out["snap_err"] = repr(e)
try:
    out["quote"] = httpx.get(B + "/api/wave/quote", params={"sym": "TX"}, timeout=30).json()
except Exception as e:  # noqa: BLE001
    out["quote"] = repr(e)
try:
    r = httpx.get("https://ws.api.cnyes.com/ws/api/v1/quote/quotes/TWF:TXF:FUTURES", params={"column": "G"}, headers=UA, timeout=20).json()
    out["cnyes_raw"] = (r.get("data") or [None])[0]
except Exception as e:  # noqa: BLE001
    out["cnyes_raw"] = repr(e)
try:
    r = httpx.post("https://www.taifex.com.tw/cht/3/futDataDown", headers=UA, timeout=60,
                   data={"down_type": "1", "commodity_id": "TX", "commodity_id2": "", "queryStartDate": "2026/11/12", "queryEndDate": "2026/11/16"})
    txt = r.content.decode("cp950", "replace")
    out["taifex_csv"] = [ln for ln in txt.splitlines() if ln.startswith("交易日期") or ",TX," in ln][:60]
except Exception as e:  # noqa: BLE001
    out["taifex_csv"] = repr(e)
with open("scratch_probe/b113.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(json.dumps({k: out.get(k) for k in ("snap", "quote", "cnyes_raw")}, ensure_ascii=False)[:2500])
print("\n".join(out["taifex_csv"]) if isinstance(out.get("taifex_csv"), list) else out.get("taifex_csv"))
