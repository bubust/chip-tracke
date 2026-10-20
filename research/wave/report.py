"""B74 研究報告：research/wave/results/stats_full.json → research/wave/REPORT.md"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, "results", "stats_full.json"), encoding="utf-8"))
pct = lambda x: "—" if x is None else f"{x * 100:+.1f}%"
pp = lambda x: "—" if x is None else f"{x * 100:+.1f} 點"
rate = lambda x: "—" if x is None else f"{x * 100:.1f}%"
ci = lambda c: "—" if not c or c[0] is None else f"[{c[0] * 100:+.1f}, {c[1] * 100:+.1f}]"
ok = lambda b: "✅" if b else "△"
TN = {"pivot": "前高前低（ZigZag 轉折）", "pivot_k3": "近期高低點（左右 3 根）", "fib": "費波那契回檔", "target": "波浪目標價",
      "ma20": "月線 MA20", "ma60": "季線 MA60", "ma120": "半年線 MA120", "ma240": "年線 MA240", "round": "整數關卡", "multi": "≥2 種來源重疊"}
L = []
w = L.append
w("# B74 研究：加權指數的波浪＋費波那契＋籌碼＋國際（PLAN-B74 §5）\n")
w(f"- 資料：加權 {d['data_start']}～{d['data_end']}（Yahoo ^TWII 日 K）；樣本內 2000–2015、樣本外 2016–2026；籌碼（FinMind）樣本內 2016–2021、樣本外 2022–2026")
w("- 「守住」：第一次碰到價位後，先反彈 1×ATR14 → 守住；先收盤跌破 0.5×ATR14 → 跌破；碰到那天就收破、或同一根 K 棒兩邊都碰到 → 跌破；20 天沒結果不計")
w(f"- 對照：同樣距離（ATR 倍數）、隨機日子的價位；區間＝月份 block bootstrap 95%；所有假設（共 {d['n_tests']} 個）一起 BH 校正")
w("- ✅ 要：樣本外比對照高 ≥5 點且區間下限 >0、BH q<0.05、4 個時期 ≥3 個同方向；其他標 △\n")
cov = d["coverage"]
w("## 0. 轉折級數與數浪覆蓋率\n")
w("| 級數 | m（×ATR%） | 下限 | 主要劇本數到 ≥3 段的天數比例 |\n|---|---|---|---|")
for k, v in d["calibration"].items():
    w(f"| {k} | {v['m']} | {v['floor']:.0%} | {cov[k]['ge3_segments']:.0%} |")
w("\n（任何一天都至少能套「第 1 浪進行中」或「A 浪進行中」，所以「數得出浪」本身沒意義；這裡看數到 ≥3 段的比例）\n")
w("## R1 費波那契\n")
w("| 級數 | 期間 | 波段數 | log(費波那契比例附近密度 ÷ 對照比例附近密度) | 區間 | 結果 |\n|---|---|---|---|---|---|")
for deg, v in d["R1"]["density"].items():
    for per in ("IS", "OOS"):
        x = v.get(per, {})
        w(f"| {deg} | {per} | {x.get('n')} | {x.get('log_density_ratio')} | {x.get('ci')} | {ok(v.get('pass')) if per == 'OOS' else ''} |")
h = d["R1"]["hold"]
w(f"\n守住率：費波那契（0.382／0.5／0.618／0.786）樣本外 {rate(h['OOS']['fib'])}（{h['OOS']['n_fib']} 次） vs 對照比例（0.32／0.44／0.56／0.68）{rate(h['OOS']['ctrl'])}，"
  f"差 {pp(h['OOS']['diff'])} {ci(h['OOS']['ci'])}，q={h.get('q')} → {ok(h['pass'])}")
w("各比例樣本外守住率：" + "、".join(f"{k} {rate(v['rate'])}（{v['n']}）" for k, v in h["OOS"]["by_ratio"].items()))
w("\n**結論**：加權的實際回檔比例沒有集中在費波那契比例附近；費波那契價位守住的機率跟普通比例差不多。\n")
w("## R2 支撐壓力類型（樣本外）\n")
w("| 類型 | 次數 | 守住率 | 隨機價位 | 差 | 區間 | 4 個時期 | q | 結果 |\n|---|---|---|---|---|---|---|---|---|")
for k, v in d["R2"].items():
    o = v.get("OOS", {})
    subs = "／".join("—" if s is None else f"{s * 100:+.0f}" for s in v.get("sub", []))
    w(f"| {TN.get(k, k)} | {o.get('n')} | {rate(o.get('rate'))} | {rate(o.get('placebo'))} | {pp(o.get('diff'))} | {ci(o.get('ci'))} | {subs} | {v.get('q')} | {ok(v.get('pass'))} |")
w("\n**結論**：沒有一種價位通過；「≥2 種來源重疊」樣本外 +3 點、4 個時期都正，但沒到 +5 點門檻、BH 後不顯著。\n")
w("## R3 波浪狀態（中級主要劇本）→ 之後 20 天\n")
w("| 狀態 | 樣本外天數 | 平均 | 上漲比例 | 比其他天 | 區間 | q | 結果 |\n|---|---|---|---|---|---|---|---|")
for k, v in d["R3"].items():
    b = v["h20"]
    o = b["OOS"]
    w(f"| {k} | {o.get('n_a')} | {pct(o.get('mean_a'))} | {rate(o.get('up_a'))} | {pp(o.get('diff'))} | {ci(o.get('ci'))} | {b.get('q')} | {ok(b.get('pass'))} |")
w("\n（imp＝推動浪、cor＝單純 A-B-C；＋上漲推動或跌深反彈的修正、－相反；5／60 天結果在 stats_full.json）\n")
w("**結論**：沒有任何浪別之後的表現跟平常有顯著差別。\n")
w("## R4 籌碼（三分位最高 − 最低，之後報酬）\n")
w("| 因子 | 期間 | 樣本內差 | 樣本外差 | 樣本外區間 | q | 結果 |\n|---|---|---|---|---|---|---|")
FN = {"f5_z": "外資現貨 5 日累計（z）", "fut_pct": "外資台指期淨未平倉（250 日百分位）", "fut_chg5": "外資期貨 5 日變化", "margin_chg20": "融資 20 日變化"}
for k, v in d["R4"].items():
    for hz in ("h5", "h20"):
        b = v[hz]
        w(f"| {FN.get(k, k)} | {hz[1:]} 天 | {pp(b['IS'].get('diff'))} | {pp(b['OOS'].get('diff'))} | {ci(b['OOS'].get('ci'))} | {b.get('q')} | {ok(b.get('pass'))} |")
w("\n**結論**：大盤層級的外資、期貨、融資，對之後 5／20 天加權都沒有預測力。\n")
r5 = d["R5"]
sb = r5.get("sox_beta", {})
w("## R5 國際\n")
w(f"- 前一晚費半漲跌 vs 加權當天：相關 樣本內 {r5['sox_overnight_IS']['corr']}、樣本外 {r5['sox_overnight_OOS']['corr']}")
w(f"- 樣本內估的 β＝{sb.get('is_beta')}，拿到樣本外預測 → R²＝{sb.get('oos_r2_with_is_beta')}（有效）；2016 後重估 β＝{sb.get('beta')}、殘差標準差 {pct(sb.get('resid_sd'))}")
w("- 加權與費半 60 日相關中位數：" + "、".join(f"{k} {v}" for k, v in r5["corr60_median"].items()))
for hz, b in r5["sox_above_ma60"].items():
    w(f"- 費半在 60 日線上 vs 下 → 加權之後 {hz[1:]} 天：樣本內 {pp(b['IS'].get('diff'))}、樣本外 {pp(b['OOS'].get('diff'))} {ci(b['OOS'].get('ci'))} → {ok(b.get('pass'))}")
w("\n**結論**：費半只對「隔天」有解釋力（相關越來越高）；對 5／20 天沒有。\n")
r6 = d["R6"]
w("## R6 過去相似狀態預判（逐步往前）\n")
w(f"- 條件（只用樣本內選）：{r6['conds']}")
w("| 期間 | 天數 | Brier（相似狀態） | Brier（全部歷史） | 改善 | 區間 | 結果 |\n|---|---|---|---|---|---|---|")
for k in ("h5_2022-2026", "h20_2022-2026", "h5_2016-2026", "h20_2016-2026"):
    b = r6[k]
    w(f"| {k} | {b['n']} | {b['brier_model']} | {b['brier_base']} | {b['improve']} | {b['ci']} | {ok(b.get('pass'))} |")
w("\n**結論**：用相似狀態算的上漲機率**比直接用全部歷史還差一點** → 網站的預測區間改用全部歷史的分布，相似狀態只當參考（標 △）。\n")
w("## 總結（網站怎麼用）\n")
w("- 波浪、費波那契、支撐壓力照用戶要求畫出來，但每個價位都標樣本外守住率＋隨機對照，並寫明「回測沒有比隨機價位好」")
w("- 預測區間＝全部歷史的 5／20／60 天分布（20%～80%）；相似狀態列為參考")
w("- 08:30 推播加：前一晚費半 → 加權今天的歷史平均（唯一有效的國際關係）")
w("- 不能拿這些當買賣訊號；規則數浪＝一種劇本，不是預言")
open(os.path.join(HERE, "REPORT.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("ok", len(L))
