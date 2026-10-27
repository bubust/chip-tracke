"""B81：research/b81/results（setups.json、advice.json、vol2.json、verify_pit.json）→ wave/stats.json（setups、advice_bt、vol2）＋ REPORT.md
用法：python research/b81/merge.py"""
import json
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STATS = os.path.join(ROOT, "wave", "stats.json")
RES = os.path.join(HERE, "results")
SNAME = {"L": "回測支撐試多", "S": "反彈壓力試空", "B": "站上回測追多"}
TFN = {"1d": "日 K", "1wk": "週 K", "intra": "分 K（60 分）"}
VNAME = {"V6": "量縮到 0.6 倍以下 → 之後 5 根波動", "V7u": "爆量長紅 → 先續漲 1 ATR", "V7d": "爆量長黑 → 先續跌 1 ATR",
         "V8": "創 20 根新高但量縮 → 先回 1 ATR", "V9": "5 根大漲且量放大 → 先續漲 1 ATR"}


def load(nm):
    p = os.path.join(RES, nm)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def worse(r):
    per = list((r.get("periods") or {}).values())
    return bool(r.get("n", 0) >= 50 and r.get("ci") and r["ci"][1] is not None and r["ci"][1] < 0 and per and all(v < 0 for v in per))


def pct(x, d=1):
    return "—" if x is None else f"{x * 100:.{d}f}%"


def main():
    st = json.load(open(STATS, encoding="utf-8"))
    su, ad, v2, vp = load("setups.json"), load("advice.json"), load("vol2.json"), load("verify_pit.json")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if su:
        out = {"generated": now, "note": "日 K／週 K＝加權 2001 年起逐日重算當時的價位梯；分 K＝加權 60 分近 3 年（15／30 分沿用 60 分的結果）；"
                                         "比的是「先到目標的比例」vs 有漂移的隨機漫步（依實際距離算）"}
        for tfc in ("1d", "1wk", "intra"):
            x = su.get(tfc)
            if not x:
                continue
            out[tfc] = {"period": x.get("period")}
            for sid in ("L", "S", "B"):
                out[tfc][sid] = {}
                for tr in ("順勢", "逆勢"):
                    r = x["rows"].get(f"{tfc}:{sid}:{tr}") or {}
                    if not r.get("n"):
                        continue
                    out[tfc][sid][tr] = {"n": r["n"], "win": r["win"], "rw": r["rw"], "edge": r["edge"], "avgR": r["avgR"],
                                         "pass": bool(r.get("pass")), "worse": worse(r)}
        st["setups"] = out
    if ad:
        rows = ad["rows"]
        st["advice_bt"] = {"generated": now, "period": ad["period"], "pass_S0": bool(rows["S0"]["pass"]),
                           "best": next((k for k in ("S1", "S2", "S3") if rows[k]["pass"]), None),
                           "S0": {k: rows["S0"][k] for k in ("diff", "ci", "q")} | {"mdd": rows["S0"]["strat"]["mdd"], "mdd_ctrl": rows["S0"]["ctrl"]["mdd"]},
                           "text": "方向一致調持股：回測 △（2000 年起，比同平均部位的固定持股 Sharpe 多 {:.2f}、區間 {:.2f}～{:.2f}，沒有顯著），當紀律參考".format(
                               rows["S0"]["diff"], rows["S0"]["ci"][0], rows["S0"]["ci"][1])}
    if v2:
        st["vol2"] = {"generated": now, "tests": {}}
        for k in VNAME:
            st["vol2"]["tests"][k] = {"text": VNAME[k], **{f"pass_{d.lower()}": bool((v2["rows"].get(f"{k}:{d}") or {}).get("pass")) for d in ("D1", "D4", "D2")}}
    json.dump(st, open(STATS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # REPORT.md
    L = [f"# B81 研究：試單地圖、建議持股規則、量能新角度（research/b81）", "", f"產生時間：{now}；門檻全部事先寫在 PLAN-B81.md，沒有事後調整。", ""]
    if vp:
        L += [f"## 0. 防偷看驗證", "", f"隨機 200 天 × 日 K／週 K：「截斷到當天的資料重算」vs「全資料＋只用當時已確認的轉折」，價位梯與試單 {vp['checked']} 個比對、**不一致 {vp['mismatch']} 個**。", ""]
    if su:
        L += ["## 1. 試單回測（R-C）", "",
              "每天（分 K 每根）用當時的價位梯算三種試單；之後觸發才算一筆；比「先到目標」的比例 vs 有漂移的隨機漫步（依實際距離）與隨機價位。",
              "✅＝比隨機漫步高 ≥5 點、整年重抽區間下限 >0、BH q<0.05（18 個一起）、比隨機價位高 ≥3 點、各時期同方向、≥50 筆。", "",
              "| 週期 | 試單 | 順逆勢 | 筆數 | 先到目標 | 隨機漫步 | 差距 | 95% 區間 | q | 隨機價位 | 平均 R | 各時期 | 到期 | 同根兩邊 | 結果 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for tfc in ("1d", "1wk", "intra"):
            x = su.get(tfc)
            if not x:
                continue
            for sid in ("L", "S", "B"):
                for tr in ("順勢", "逆勢"):
                    r = x["rows"].get(f"{tfc}:{sid}:{tr}") or {}
                    if not r.get("n"):
                        continue
                    res = "✅" if r.get("pass") else ("△（比隨機差）" if worse(r) else "△")
                    per = "、".join(f"{v:+.0f}" for v in (r.get("periods") or {}).values())
                    L.append(f"| {TFN[tfc]} | {SNAME[sid]} | {tr} | {r['n']} | {pct(r['win'])} | {pct(r['rw'])} | {r['edge'] * 100:+.1f} | "
                             f"{r['ci'][0] * 100:+.1f}～{r['ci'][1] * 100:+.1f} | {r['q']:.3f} | {pct(r.get('rand_win'))} | {r['avgR']:+.2f} | {per} | "
                             f"{pct(r.get('timeout'))} | {r.get('both')} | {res} |")
        L += ["", f"期間：日 K／週 K {su.get('1d', {}).get('period')}；分 K {su.get('intra', {}).get('period')}。"
                  "分 K 的價位梯沒有多層浪名那幾個價位（研究重算太慢），網站的分 K 試單用同一個函式但價位多幾個。", ""]
    if ad:
        L += ["## 2. 建議持股規則（R-A）", "",
              "訊號在當天收盤算、套用隔天報酬；部位 100%／50%／0%（S0）或 100%／0%（候選）；成本 0.1%；對照＝同平均部位的固定持股。",
              "✅＝Sharpe 差 ≥ +0.15、平穩區塊 bootstrap（20／60 天取保守）區間下限 >0、q<0.05、最大回撤 ≤ 對照 0.8 倍、四個時期 ≥3 個為正。", "",
              "| 策略 | 平均部位 | 年化 | Sharpe | 最大回撤 | 對照 Sharpe | 對照回撤 | Sharpe 差 | 95% 區間 | q | 各時期 | 結果 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        nm = {"S0": "S0 現行（日 K＋週 K 方向）", "S1": "S1 收盤 > 200 日線", "S2": "S2 月線上揚", "S3": "S3 收盤 > 60 日線"}
        for k, r in ad["rows"].items():
            per = "、".join(f"{v:+.2f}" for v in r["periods"].values())
            L.append(f"| {nm[k]} | {r['avg_w'] * 100:.0f}% | {pct(r['strat']['cagr'])} | {r['strat']['sharpe']:.2f} | {pct(r['strat']['mdd'], 0)} | "
                     f"{r['ctrl']['sharpe']:.2f} | {pct(r['ctrl']['mdd'], 0)} | {r['diff']:+.2f} | {r['ci'][0]:+.2f}～{r['ci'][1]:+.2f} | {r['q']:.3f} | {per} | {'✅' if r['pass'] else '△'} |")
        s = ad["site"]
        L += ["", f"網站實際版（基準 30～50%：都上 45%、不一致 40%、都下 35%）：Sharpe {s['strat']['sharpe']:.2f}、回撤 {pct(s['strat']['mdd'], 0)}；"
                  f"固定 40%：Sharpe {s['ctrl']['sharpe']:.2f}、回撤 {pct(s['ctrl']['mdd'], 0)}（只報告）。", "",
              "S0 各狀態之後 20 天（描述）：" + "；".join(f"{k} {v['days']} 天、平均 {v['fwd20_mean'] * 100:+.2f}%、波動 {v['fwd20_sd'] * 100:.1f}%" for k, v in ad["desc_S0"].items()), "",
              "**決策（事先定）**：S0 和候選都 △ → 規則不變，網站的持股範圍理由加「方向一致調持股：回測 △，紀律參考」。", ""]
    if v2:
        L += ["## 3. 量能新角度（R-B）", "",
              "虛無假設：A 組跟 B 組（一般量）之後沒有差別；p＝同一年內打亂組別 2,000 次；區間＝整年重抽；15 個一起 BH。", "",
              "| 檢定 | 資料 | A 筆數 | B 筆數 | A | B | 效果 | 95% 區間 | q | 各時期 | 結果 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, r in v2["rows"].items():
            t, d = k.split(":")
            if not r.get("nA") and not r.get("nB"):
                continue
            unit = "比例" if t == "V6" else "點"
            eff = "—" if r.get("effect") is None else (f"{r['effect'] * 100:+.1f}%" if t == "V6" else f"{r['effect'] * 100:+.1f} 點")
            ci = "—" if not r.get("ci") else f"{r['ci'][0] * 100:+.1f}～{r['ci'][1] * 100:+.1f}"
            per = "、".join(f"{float(v):+.0f}" for v in (r.get("periods") or {}).values())
            fa = lambda v: "—" if v is None else (f"{v:.2f} ATR" if t == "V6" else pct(v))  # noqa: E731
            L.append(f"| {VNAME[t]} | {d} | {r['nA']} | {r['nB']} | {fa(r.get('A'))} | {fa(r.get('B'))} | {eff} | {ci} | "
                     f"{'—' if r.get('q') is None else format(r['q'], '.3f')} | {per} | {'✅' if r.get('pass') else '△'} |")
        dd = v2["data"]
        L += ["", "資料：" + "；".join(f"{k} {x['from']}～{x['to']}（{x['bars']} 根、有量 {x['with_vol']}）" for k, x in dd.items())
              + f"；D4 換月前後排除 {dd.get('D4', {}).get('roll_days_excluded')} 天。", ""]
    L += ["## 總結（網站怎麼用）", "",
          "- 試單地圖照她的規則列出「回測支撐試多／反彈壓力試空（加權＝減碼區）／站上回測追多」，每筆寫回測結果；△ 的當紀律參考（停損明確、賠率夠才做）。",
          "- 比隨機還差的（例：日 K 在壓力試空）照實寫「比隨機差」。",
          "- 建議持股的方向調整維持原規則，標 △。",
          "- 量能新角度沒有通過的，不放結論卡。", ""]
    open(os.path.join(HERE, "REPORT.md"), "w", encoding="utf-8").write("\n".join(L))
    print("stats.json 更新：", [k for k in ("setups", "advice_bt", "vol2") if k in st], "；REPORT.md 寫好")


if __name__ == "__main__":
    main()
