"""B99：research/b99/results/b99.json → wave/stats.json 的 entry_b99（她的進單規矩回測一句話結論，劇本分頁和研究摘要用）
用法：python research/b99/merge.py"""
import json
import os
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STATS = os.path.join(ROOT, "wave", "stats.json")


def main():
    st = json.load(open(STATS, encoding="utf-8"))
    R = json.load(open(os.path.join(HERE, "results", "b99.json"), encoding="utf-8"))
    d = {(x["k"], x["side"], x["fam"]): x for x in R["desc"]}
    zm = lambda k, side=0, fam="all": round(d[(k, side, fam)]["zone_mean"] * 100, 3)         # noqa: E731
    t = lambda x: {"mean": round(x["mean"] * 100, 3), "q": round(x["q"], 3), "verdict": x["verdict"]}  # noqa: E731
    knife_x = [x for x in R["desc"] if x["k"] == "V0E2" and x["side"] != 0 and x["fam"] == "X"]
    out = {"generated": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"), "span": [R["span"][0][:10], R["span"][1][:10]],
           "n_events": R["n_events"],
           "knife": zm("V0E2"), "knife_x": round(sum(x["zone_mean"] * x["events"] for x in knife_x)
                                                 / max(1, sum(x["events"] for x in knife_x)) * 100, 3),
           "knife_win": round(d[("V0E2", 0, "all")]["win"] * 100), "v1": zm("V1E2"), "v2": zm("V2E2"), "v4_rate": round(R["signal_rate"]["V4"] * 100),
           "v2_vs_knife": t(R["post"]["PV2"]), "v2_vs_rand": t(R["post"]["PV2plc"]), "v1_vs_knife": t(R["tests"]["H1"]),
           "e2_vs_e1": t(R["tests"]["H3"]), "v1_vs_v5": t(R["tests"]["H4"]), "v1_vs_rand": t(R["tests"]["H5"])}
    st["entry_b99"] = out
    with open(STATS, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    print("stats.json entry_b99 更新", json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
