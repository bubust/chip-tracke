"""
deep_verdict.py — 深度分析「綜合評價」（PLAN-DEEP2 §5，2026-10-07），純函式、可測

技術（50 分）是唯一回測過的部分（research/deep/backtest.py，1,910 檔、2025-04～2026-09）：
  趨勢 20：均線多頭排列 10>20>60 → 8（否則收盤 > 60 日線 → 4）；60 日線比 5 天前高 → 6；DIF > 0 → 6
  動能 20：52 週位置 ≥.8/.6/.4/.2 → 10/7/4/2；120 日報酬 ≥30%/10%/0/−10% → 10/7/4/2
  原始 0～40 分：強勢 ≥32、中性 8～31、弱勢 <8
  回測沒用而拿掉的：MACD 柱狀體（OSC）正負與變化、量比、BB 位置
籌碼 20、基本 15、產業 15：沒回測（本機沒有歷史），經驗權重，畫面標「參考」。
總分＝拿得到的分項加總 ÷ 拿得到的滿分 × 100（缺的分項分子分母都扣掉）。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# ── 回測常數（research/deep/backtest.py 產生；重跑後更新這裡）──────────────────
BACKTEST_PERIOD = "2025-04～2026-09"
# 母體：main＝20 日均量 ≥300 張且股價 ≥10；low＝20 日均量 30～300 張且股價 ≥10
# x20＝未來 20 日報酬 − 同一天所有樣本平均（超額）；med＝超額中位數；up＝20 日後上漲比例；mdd＝20 日內最大跌幅平均
BUCKET_STATS = {
    "main": {"strong": {"x20": 2.2, "med": -2.45, "up": 48.7, "mdd": -11.0, "n": 15915},
             "neutral": {"x20": -0.18, "med": -2.68, "up": 47.1, "mdd": -7.7, "n": 32719},
             "weak": {"x20": -1.42, "med": -2.78, "up": 51.8, "mdd": -5.8, "n": 20501}},
    "low": {"strong": {"x20": 0.31, "med": -2.2, "up": 38.6, "mdd": -8.4, "n": 2215},
             "neutral": {"x20": 0.09, "med": -1.43, "up": 41.2, "mdd": -5.9, "n": 18306},
             "weak": {"x20": -0.09, "med": -1.34, "up": 45.2, "mdd": -5.3, "n": 24296}},
}
# 40 天內「先碰到目標價／先收盤跌破停損」的比例（price_levels 的目標與停損），依 技術分類 × 風險報酬比
# 區間 lo＜0.5、mid 0.5～＜1、hi ≥1；(先到目標%, 先停損%, 筆數, 平均每筆結果%)
# 平均每筆：先到目標賣在目標、先破停損賣在那天收盤、都沒有賣在第 40 天收盤；未扣成本；期間大盤偏多（同期任一股 20 日平均 +2.2%）
ODDS = {
    "main": {"weak": {"lo": (81, 16, 720, 1.05), "mid": (64, 29, 854, 1.33), "hi": (34, 34, 822, 2.03)},
             "neutral": {"lo": (79, 16, 1875, 0.55), "mid": (62, 28, 1270, 1.1), "hi": (37, 33, 639, 1.19)},
             "strong": {"lo": (79, 16, 838, 0.86), "mid": (61, 31, 711, 1.26), "hi": (49, 32, 271, 3.15)}},
    "low": {"weak": {"lo": (76, 18, 1199, 0.3), "mid": (60, 28, 1535, 0.51), "hi": (33, 39, 1603, 1.04)},
             "neutral": {"lo": (78, 17, 1699, 0.27), "mid": (57, 31, 1037, 0.02), "hi": (35, 38, 535, 0.27)},
             "strong": {"lo": (66, 22, 195, -0.58), "mid": (55, 32, 146, 0.61), "hi": (39, 35, 51, -1.49)}},
}
ROUND_TRIP_COST = 0.585          # %：手續費 0.1425%×2＋證交稅 0.3%（未折扣）
RISK_PER_TRADE = 1.0             # %：單筆最多虧總資金
MAX_POSITION = 25.0              # %：單檔上限
MIN_BARS = 130
BUCKET_LABEL = {"strong": "強勢", "neutral": "中性", "weak": "弱勢"}
GRADES = [(70, "偏多", "#f85149"), (55, "略偏多", "#ff7b72"), (45, "中性", "#94a3b8"),     # 台股慣例：多＝紅、空＝綠
          (30, "略偏空", "#56d364"), (-1, "偏空", "#3fb950")]


# ── 技術 ─────────────────────────────────────────────────────────────────────

def lots_volume(v: pd.Series) -> pd.Series:
    """price_daily 有些舊列的量是「股」不是「張」（正式站約 270 檔到 2026-09-21 為止，之後才是張）：
    比這檔最近 10 根中位數大 200 倍以上的列當成股、除以 1000（單位換算，不影響價格因子）"""
    ref = v.dropna().tail(10).median()
    if ref and ref > 0:
        v = v.where(~(v > ref * 200), v / 1000)
    return v


def tech_series(df: pd.DataFrame) -> pd.DataFrame:
    """每根 K 棒的技術因子（價格因子只用當天以前的資料）；回測與線上共用"""
    c = df["close"].astype(float).reset_index(drop=True)
    h = df["high"].astype(float).reset_index(drop=True)
    lo = df["low"].astype(float).reset_index(drop=True)
    v = lots_volume(df["volume"].astype(float).reset_index(drop=True))
    ma10, ma20, ma60 = (c.rolling(k).mean() for k in (10, 20, 60))
    dif = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hi250 = h.rolling(250, min_periods=120).max()
    lo250 = lo.rolling(250, min_periods=120).min()
    rng = hi250 - lo250
    out = pd.DataFrame({
        "close": c, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "bull": (ma10 > ma20) & (ma20 > ma60),
        "above60": c > ma60,
        "ma60_up": ma60 > ma60.shift(5),
        "dif_pos": dif > 0,
        "pos52": ((c - lo250) / rng).where(rng > 0),
        "r5": c / c.shift(5) - 1, "r20": c / c.shift(20) - 1, "r60": c / c.shift(60) - 1, "r120": c / c.shift(120) - 1,
        "vol20": v.rolling(20, min_periods=15).mean(),   # 允許少數幾天沒有量的資料
        "bias20": c / ma20 - 1,
    })
    out["n"] = np.arange(1, len(c) + 1)
    return out


def _tier(x, cuts, pts):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0
    for cut, p in zip(cuts, pts):
        if x >= cut:
            return p
    return 0


def tech_raw(row) -> tuple:
    """(原始 0～40 分, [(理由, +分)])"""
    parts = []
    if row["bull"]:
        parts.append(("均線多頭排列（10>20>60 日線）", 8))
    elif row["above60"]:
        parts.append(("站上 60 日線（均線還沒排好）", 4))
    else:
        parts.append(("在 60 日線下", 0))
    parts.append(("60 日線上彎", 6) if row["ma60_up"] else ("60 日線下彎", 0))
    parts.append(("MACD DIF 在 0 軸上", 6) if row["dif_pos"] else ("MACD DIF 在 0 軸下", 0))
    p52 = row["pos52"]
    pp = _tier(p52, (.8, .6, .4, .2), (10, 7, 4, 2))
    if p52 is not None and not (isinstance(p52, float) and math.isnan(p52)):
        parts.append((f"52 週位置 {p52 * 100:.0f}%（0＝一年最低、100＝一年最高）", pp))
    r120 = row["r120"]
    rp = _tier(r120, (.3, .1, 0, -.1), (10, 7, 4, 2))
    if r120 is not None and not (isinstance(r120, float) and math.isnan(r120)):
        parts.append((f"半年（120 日）{'漲' if r120 >= 0 else '跌'} {abs(r120) * 100:.0f}%", rp))
    return sum(p for _, p in parts), parts


def bucket_of(raw: int) -> str:
    return "strong" if raw >= 32 else "weak" if raw < 8 else "neutral"


def population(vol20, price) -> str:
    """回測母體：main（20 日均量 ≥300 張、股價 ≥10）／low（30～300 張）／none（更小或股價 <10，沒回測）"""
    if vol20 is None or price is None or price < 10 or vol20 < 30:
        return "none"
    return "main" if vol20 >= 300 else "low"


# ── 其他分項（沒回測）────────────────────────────────────────────────────────

def chip_score(chip: dict | None, vol_sum: float | None, kpct_change: float | None):
    """(分, 滿分, [(理由, 分)])；沒有法人資料回 None"""
    if not chip or chip.get("error"):
        return None
    parts, mx = [], 0
    f, t = chip.get("foreign") or {}, chip.get("trust") or {}
    days = chip.get("days") or 0
    if vol_sum and vol_sum > 0 and days:
        net = (f.get("d20") or 0) + (t.get("d20") or 0)
        ratio = net / vol_sum * 100
        p = 10 if ratio >= 5 else 7 if ratio >= 2 else 5 if ratio > -2 else 2 if ratio > -5 else 0
        parts.append((f"外資＋投信近 {days} 日{'買超' if net >= 0 else '賣超'} {abs(net):,.0f} 張（占成交量 {ratio:+.1f}%）", p))
        mx += 10
    ts = t.get("streak") or 0
    p = 5 if ts >= 3 else 0 if ts <= -3 else 2
    parts.append((f"投信{'連買' if ts > 0 else '連賣' if ts < 0 else '今天沒買賣'}{f' {abs(ts)} 天' if ts else ''}", p))
    mx += 5
    if kpct_change is not None:
        p = 5 if kpct_change >= 0.3 else 0 if kpct_change <= -0.3 else 2
        parts.append((f"千張大戶持股週{'增' if kpct_change >= 0 else '減'} {abs(kpct_change):.2f} 個百分點", p))
        mx += 5
    return sum(p for _, p in parts), mx, parts


def fund_score(rev: dict | None, inc: dict | None, val: dict | None):
    if val and val.get("etf"):
        return None
    parts, mx = [], 0
    if rev and rev.get("yoy") is not None:
        y = rev["yoy"]
        parts.append((f"{(rev.get('ym') or '')[-2:].lstrip('0') or '最新'} 月營收年增 {y:+.1f}%",
                      6 if y >= 20 else 4 if y >= 0 else 2 if y >= -20 else 0))
        mx += 6
    if rev and rev.get("ytd_yoy") is not None:
        y = rev["ytd_yoy"]
        parts.append((f"今年累計營收年增 {y:+.1f}%", 3 if y >= 10 else 2 if y >= 0 else 0))
        mx += 3
    if inc and inc.get("eps") is not None:
        parts.append((f"{inc.get('label', '')} EPS {inc['eps']:g} 元", 3 if inc["eps"] > 0 else 0))
        mx += 3
    if val and val.get("peer_pe_median"):
        pe, med = val.get("per"), val["peer_pe_median"]
        if pe is None:
            parts.append((f"沒有本益比（虧損或無資料），同產業中位數 {med:g}", 0))
        else:
            parts.append((f"本益比 {pe:g}，同產業中位數 {med:g}（{val.get('peer_n')} 檔）",
                          3 if pe <= med else 2 if pe <= med * 1.5 else 0))
        mx += 3
    if not mx:
        return None
    return sum(p for _, p in parts), mx, parts


def sector_score(sector: dict | None):
    if not sector or sector.get("rank20d") is None or (sector.get("total") or 0) < 10 or sector.get("stale"):
        return None                       # 產業不到 10 個（資料不完整）或過期 → 不計
    r, n = int(sector["rank20d"]), int(sector["total"])
    p = round(15 * (1 - (r - 1) / (n - 1))) if n > 1 else 8
    return p, 15, [(f"{sector.get('sector_name', '所屬產業')} 20 日強度第 {r} 名／{n}", p)]


# ── 建議 ─────────────────────────────────────────────────────────────────────

def rr_band(rr) -> str | None:
    if rr is None or rr <= 0:
        return None
    return "lo" if rr < 0.5 else "mid" if rr < 1 else "hi"


def odds_of(bucket: str, rr, pop: str):
    if pop not in ODDS:
        return None
    band = rr_band(rr)
    if not band:
        return None
    win, lose, n, avg = ODDS[pop][bucket][band]
    if n < 30:
        return None
    return {"target_first": win, "stop_first": lose, "n": n, "small": n < 100, "band": band,
            "avg": avg, "net": round(avg - ROUND_TRIP_COST, 2)}


def best_band(bucket: str, pop: str):
    """同分類裡扣成本後平均最好的風險報酬比區間（樣本 ≥100）"""
    if pop not in ODDS:
        return None
    cands = [(v[3], k, v) for k, v in ODDS[pop][bucket].items() if v[2] >= 100]
    if not cands:
        return None
    avg, k, v = max(cands)
    return {"band": k, "avg": avg, "net": round(avg - ROUND_TRIP_COST, 2), "n": v[2]}


BAND_LABEL = {"lo": "目標近、停損遠（風險報酬比 <0.5）", "mid": "風險報酬比 0.5～1", "hi": "風險報酬比 ≥1"}


def position_pct(price, stop, pop: str):
    """單筆最多虧總資金 1% → 最多放 1%÷(停損距離＋來回成本)；低量股減半；上限 25%；停損 ≥ 現價不算"""
    if not price or not stop or stop >= price:
        return None
    dist = (price - stop) / price * 100 + ROUND_TRIP_COST
    pct = RISK_PER_TRADE / dist * 100
    if pop != "main":
        pct /= 2
    return round(min(pct, MAX_POSITION), 1)


def grade_of(score):
    for cut, g, col in GRADES:
        if score >= cut:
            return g, col
    return GRADES[-1][1], GRADES[-1][2]


def _pct(a, b):
    return round((a / b - 1) * 100, 1) if a and b else None


def verdict(tech_row, chip=None, vol_sum=None, kpct_change=None, rev=None, inc=None, val=None,
            sector=None, levels=None) -> dict:
    """綜合評價。tech_row＝tech_series(df).iloc[-1]（或同欄位的 dict）"""
    lv = levels if levels and not levels.get("error") else {}
    price = lv.get("price") or (tech_row["close"] if tech_row is not None else None)
    if tech_row is None or int(tech_row["n"]) < MIN_BARS:
        return {"ok": False, "reason": f"K 線不到 {MIN_BARS} 根（上市未滿半年或資料不足），只列資料、不給評價"}
    raw, tparts = tech_raw(tech_row)
    bk = bucket_of(raw)
    vol20 = tech_row["vol20"]
    vol20 = None if vol20 is None or (isinstance(vol20, float) and math.isnan(vol20)) else float(vol20)
    pop = population(vol20, price)
    comps = [{"key": "tech", "label": "技術（已回測）", "pts": round(raw * 50 / 40), "max": 50, "backtested": True,
              "reasons": [{"text": t, "pts": round(p * 50 / 40)} for t, p in tparts]}]
    for key, label, res in (("chip", "籌碼（參考）", chip_score(chip, vol_sum, kpct_change)),
                            ("fund", "基本面（參考）", fund_score(rev, inc, val)),
                            ("sector", "產業（參考）", sector_score(sector))):
        if res is None:
            note = {"chip": "沒有法人資料（不計）",
                    "fund": "ETF 沒有本益比與財報（不計）" if (val and val.get("etf")) else "沒有營收／財報資料（不計）",
                    "sector": "沒有產業排名或資料過期（不計）"}[key]
            comps.append({"key": key, "label": label, "pts": None, "max": None, "note": note, "reasons": []})
            continue
        pts, mx, parts = res
        full = {"chip": 20, "fund": 15, "sector": 15}[key]
        comps.append({"key": key, "label": label, "pts": round(pts * full / mx), "max": full, "backtested": False,
                      "reasons": [{"text": t, "pts": p} for t, p in parts]})
    have = [c for c in comps if c["pts"] is not None]
    score = round(sum(c["pts"] for c in have) / sum(c["max"] for c in have) * 100)
    grade, color = grade_of(score)

    stop = (lv.get("stop") or {}).get("price")
    target = lv.get("target")
    sup = (lv.get("support") or {}).get("price")
    p1 = (lv.get("pressure1") or {}).get("low")
    rr = lv.get("rr")
    odds = odds_of(bk, rr, pop)
    pos = position_pct(price, stop, pop)
    lines, notes = [], []
    def _cond():
        cond = []
        if p1 and price and p1 > price:
            cond.append(f"站上壓力 {p1:g}（{_pct(p1, price):+.1f}%）轉強")
        if sup and price and sup < price:
            cond.append(f"跌破支撐 {sup:g}（{_pct(sup, price):+.1f}%）轉弱")
        return "；".join(cond) if cond else "等方向出來"

    # 做多建議只給「技術強勢（回測有優勢）」，或技術中性但總分 ≥70（主要靠沒回測的籌碼／基本面，會註明）
    long_ok = (bk == "strong" and score >= 55) or (bk == "neutral" and score >= 70)
    if stop and price and price < stop:
        action = "已跌破停損"
        lines.append(f"收盤 {price:g} 已低於停損 {stop:g}：持有者照紀律出場，不建議新買")
    elif long_ok:
        action = "可以做多" if pop == "main" else "小量試單"
        s = f"停損 {stop:g}（{_pct(stop, price):+.1f}%，收盤跌破出場）" if stop else "停損：沒有可用的價位"
        tg = f"，目標 {target:g}（{_pct(target, price):+.1f}%）" if target and price and target > price else ""
        lines.append(f"{action}：{s}{tg}")
        if bk == "neutral":
            lines.append("技術只是中性（回測沒有優勢），這個建議主要靠籌碼／基本面（沒回測），部位放小")
    elif score >= 55 and bk == "weak":
        action = "觀望"
        lines.append("籌碼／基本面不錯，但趨勢還沒轉強（技術弱勢），等站上 60 日線再說")
    elif score >= 55:
        action = "觀望偏多"
        lines.append(f"偏多但趨勢還不夠強（技術中性）：{_cond()}")
    elif score >= 45:
        action = "觀望"
        lines.append("觀望：" + _cond())
    else:
        action = "避開"
        lines.append(f"不建議做多（{grade}）" + (f"；持有者守停損 {stop:g}" if stop else ""))
    p2 = (lv.get("pressure2") or {}).get("low")
    if lv.get("target_kind") == "pressure1" and p2 and price and p2 > (target or 0):
        lines.append(f"目標是前高 {target:g}；過了之後下一關 {p2:g}（{_pct(p2, price):+.1f}%）")
    if odds:
        lines.append(f"過去同類（技術{BUCKET_LABEL[bk]}、{BAND_LABEL[odds['band']]}）：40 天內先到目標 {odds['target_first']}%、"
                     f"先跌破停損 {odds['stop_first']}%；平均每筆 {odds['avg']:+.1f}%（扣成本 {odds['net']:+.1f}%）"
                     f"（{odds['n']:,} 筆{'，樣本少' if odds['small'] else ''}）")
        bb = best_band(bk, pop)
        if (pop == "main" and action == "可以做多" and bb and bb["band"] != odds["band"]
                and odds["net"] < 0.5 and bb["net"] >= odds["net"] + 1):
            action = "等突破或拉回"
            lines[0] = lines[0].replace("可以做多：", "要做多的話：", 1)
            lines.append(f"注意：現在這個位置過去扣成本後平均只有 {odds['net']:+.1f}%；同樣技術{BUCKET_LABEL[bk]}、"
                         f"{BAND_LABEL[bb['band']]}的位置平均 {bb['net']:+.1f}% → 方向偏多但不必追價，"
                         + (f"等突破 {target:g} 或拉回再看" if target else "等拉回再看"))
    if pos is not None and action in ("可以做多", "小量試單", "等突破或拉回"):
        lines.insert(1, f"部位：單筆最多虧總資金 {RISK_PER_TRADE:g}% 的話，這檔最多放總資金的 {pos:g}%"
                     + ("（低量股已減半）" if pop != "main" else ""))
    if pop == "low":
        notes.append(f"低量股（20 日均量 {vol20:,.0f} 張）：回測裡技術分類沒有明顯優勢、滑價大，部位已減半")
    elif pop == "none":
        notes.append("成交量太小或股價低於 10 元：不在回測範圍，機率與統計不適用")
    if bk == "strong" and pop == "main":
        notes.append(f"強勢股過去 20 天內平均最大回檔 {BUCKET_STATS['main']['strong']['mdd']}%，停損要設好")
    notes.append(f"總分含沒回測的籌碼／基本面／產業（經驗權重）；回測期間 {BACKTEST_PERIOD}（大盤偏多），過去不代表未來；"
                 f"機率與報酬未扣來回成本約 {ROUND_TRIP_COST:g}%；部位建議是單筆風險，所有持股合計的風險也要控制")
    entry = lv.get("entry") or {}
    if entry.get("kind") == "cost" and entry.get("price"):
        lines.append(f"持有：成本 {entry['price']:g}，目前 {entry.get('pnl_pct', 0):+.1f}%")

    summary = [f"技術{BUCKET_LABEL[bk]}"]
    for c in comps[1:]:
        if c["pts"] is not None and c["max"]:
            r = c["pts"] / c["max"]
            summary.append({"chip": "籌碼", "fund": "基本面", "sector": "產業"}[c["key"]]
                           + ("偏多" if r >= .65 else "偏弱" if r < .35 else "中性"))
    stats = BUCKET_STATS.get(pop, {}).get(bk) if pop in BUCKET_STATS else None
    return {
        "ok": True, "score": score, "grade": grade, "color": color, "action": action,
        "summary": "、".join(summary),
        "bucket": {"key": bk, "label": BUCKET_LABEL[bk], "raw": raw, "pop": pop, "stats": stats, "vol20": vol20},
        "components": comps, "advice": lines, "notes": notes, "odds": odds, "position_pct": pos,
        "period": BACKTEST_PERIOD,
    }
