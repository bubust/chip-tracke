"""B106：research/b106/results/b106.json → wave/stats.json 的 entry_b106（她的進場做法回測一句話結論，劇本分頁和研究摘要用）
用法：python research/b106/merge.py"""
import json
import os
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STATS = os.path.join(ROOT, "wave", "stats.json")


def main():
    st = json.load(open(STATS, encoding="utf-8"))
    R = json.load(open(os.path.join(HERE, "results", "b106.json"), encoding="utf-8"))
    m = R["desc"]["main"]
    t = lambda x: {"mean": round(x["mean"] * 100, 3), "q": round(x["q"], 3), "verdict": x["verdict"]}  # noqa: E731
    out = {"generated": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
           "span": [R["span"][0][:10], R["span"][1][:10]], "n": m["n"], "win": round(m["win"] * 100),
           "pts_mean": round(m["pts_mean"], 1), "pts": round(m["pts"]), "mdd": round(m["mdd"]), "r_mean": round(m["mean"] * 100, 3),
           "vs_fake": t(R["tests"]["H1"]), "vs_rand": t(R["tests"]["H2"]), "net": t(R["tests"]["H3"]), "e3_vs_e1": t(R["tests"]["H4"]),
           "trend": {"n": R["desc"]["D2"]["n"], "pts_mean": round(R["desc"]["D2"]["pts_mean"], 1), "verdict": R["post"]["P2"]["verdict"]}}
    st["entry_b106"] = out
    with open(STATS, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    print("stats.json entry_b106 更新", json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
