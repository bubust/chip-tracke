"""B96：research/b96/results/setups15.json → wave/stats.json 的 setups.intra15（15 分週期的劇本卡改用 15 分自己的回測）
用法：python research/b96/merge.py"""
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STATS = os.path.join(ROOT, "wave", "stats.json")


def main():
    st = json.load(open(STATS, encoding="utf-8"))
    res = json.load(open(os.path.join(HERE, "results", "setups15.json"), encoding="utf-8"))
    x = res["intra15"]
    out = {"period": res["period"], "generated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    for sid in ("L", "S", "B"):
        out[sid] = {}
        for tr in ("順勢", "逆勢"):
            r = x["rows"].get(f"intra15:{sid}:{tr}") or {}
            if not r.get("n"):
                continue
            out[sid][tr] = {"n": r["n"], "win": r["win"], "rw": r["rw"], "edge": r["edge"], "avgR": r["avgR"],
                            "pass": bool(r.get("pass")), "worse": bool(r.get("worse")), "pts": r.get("pts_mean"),
                            "rr_real": r.get("rr_med")}
    su = st.setdefault("setups", {})
    su["intra15"] = out
    su["note"] = ("日 K／週 K＝加權 2001 年起逐日重算當時的價位梯；60 分＝加權 60 分近 3 年（30 分沿用 60 分的結果）；"
                  "15 分＝加權 15 分近 3 年（B96，證交所每 5 秒指數）；比的是「先到目標的比例」vs 有漂移的隨機漫步（依實際距離算）")
    with open(STATS, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    print("stats.json setups.intra15 更新", json.dumps(out, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
