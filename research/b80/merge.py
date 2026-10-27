"""B80：research/b80/results（r15.json、vol.json）→ wave/stats.json 的 intraday15、volume（網站讀這裡標 ✅／△）"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STATS = os.path.join(ROOT, "wave", "stats.json")

if __name__ == "__main__":
    st = json.load(open(STATS, encoding="utf-8"))
    r15 = json.load(open(os.path.join(HERE, "results", "r15.json"), encoding="utf-8"))
    st["intraday15"] = {k: r15[k] for k in ("m", "floor", "target_days", "cal_period", "n_days") if k in r15}
    vp = os.path.join(HERE, "results", "vol.json")
    if os.path.exists(vp):
        v = json.load(open(vp, encoding="utf-8"))
        st["volume"] = {"generated": v["generated"], "rule": v["rule"], "data": v["data"],
                        "tests": {k: {"pass_d1": bool(x.get("pass_d1")), "pass_d2": bool(x.get("pass_d2")), "text": x["text"]}
                                  for k, x in v["tests"].items()},
                        "note": "日 K 用加權 2000 年起（證交所成交金額）、60 分用加權近 3 年（證交所每 5 秒成交統計）；"
                                "分 K（15／30／60 分）看 60 分的結果、日 K／週 K 看日 K 的結果；" + v["rule"]}
    json.dump(st, open(STATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("merged", list(st.get("volume", {}).get("tests", {}).keys()), st["intraday15"])
