"""
可轉債篩選（老王筆記＋2026-10-04 上課筆記；兩份有出入時以上課筆記為主）

- 理論價值 ＝ 股價 ÷ 轉換價 × 100
- 上課筆記：CB 市價 > 理論價值（溢價）＝ 大戶搶購 CB、看好現股（CB 是現股的領先指標）
  → 「搶購訊號」：CB 價 > 理論價、CB ≥ 102（不是靠面額撐住），且 CB 量大增或 5 日漲 ≥ 3%
- 折價（理論價 > CB 價）＋現股高檔＋融券大增 ＝ CB 持有人用融券鎖利（高檔鎖利，偏出場）
- 面額 100 保底（公司不倒）：股災時 CB 跌近 100 是極高安全邊際買點（≤ 102 視為貼近面額）
- 兩波：定價完成後（發行約 3 個月、開放轉換前有拉抬）、快到期前；CB 發行前公司常壓低股價
- 六大流程：①低檔發債（利多出現，可參考進場）②營收成長 ③利多消息 ④融券大增（相對高點，考慮出場）
           ⑤可轉債成交量大增 ⑥融券大減
- 好債：股東人數少、已轉換率少、委買要高
- 沒有融券可以看就看技術分析（抱季線）；融券大增後就沒了，大部分撐不到轉換時間
"""
from __future__ import annotations

from datetime import date
from typing import Optional

NEW_DAYS = 100           # 沒有開放轉換日時：發行後 100 天內＝第一波
FLOOR = 102              # CB ≤ 102 視為貼近面額保底
NEAR_MATURITY = 365      # 到期前一年 / 賣回前半年＝第二波
NEAR_PUT = 180


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def low_issue(closes: list, issue_date: str) -> Optional[float]:
    """發債日股價在前 250 個交易日區間的位置（0＝最低、1＝最高）；資料不足回 None
    closes = [(YYYYMMDD 或 YYYY-MM-DD, close), ...] 由舊到新"""
    if not closes or not issue_date:
        return None
    key = issue_date.replace("-", "")
    idx = [i for i, (d, _) in enumerate(closes) if str(d).replace("-", "") <= key]
    if not idx or idx[-1] < 40:
        return None
    i = idx[-1]
    win = [c for _, c in closes[max(0, i - 250):i + 1] if c]
    lo, hi = min(win), max(win)
    return (closes[i][1] - lo) / (hi - lo) if hi > lo else 0.5


def short_signal(shorts: list) -> dict:
    """shorts = [(date, 融券餘額張), ...] 由舊到新 → {now, chg5, chg5_pct, surge, drop}"""
    out = {"now": None, "chg5": None, "chg5_pct": None, "surge": False, "drop": False, "peak20": None}
    vals = [(d, v) for d, v in shorts if v is not None]
    if not vals:
        return out
    now = vals[-1][1]
    out["now"] = now
    if len(vals) >= 6:
        prev = vals[-6][1]
        out["chg5"] = now - prev
        out["chg5_pct"] = _r((now / prev - 1) * 100, 1) if prev > 0 else None
        base = max(prev, 1)
        out["surge"] = now - prev >= 100 and now >= base * 1.3
        out["drop"] = prev - now >= 100 and now <= base * 0.7
    win = [v for _, v in vals[-20:]]
    peak = max(win)
    out["peak20"] = peak
    # 先大增、現在從高點掉 30% 以上 → 也算融券大減（⑥）
    if not out["drop"] and len(win) >= 10 and peak >= max(win[0], 1) * 1.5 and peak - now >= 100 and now <= peak * 0.7:
        out["drop"] = True
    return out


def vol_surge(quotes: list) -> tuple:
    """quotes = [{date, volume}, ...] 由舊到新 → (最近一日量, 20 日均量, 是否大增)"""
    if not quotes:
        return None, None, False
    last = quotes[-1].get("volume") or 0
    prior = [q.get("volume") or 0 for q in quotes[-21:-1]]
    avg = sum(prior) / len(prior) if prior else None
    surge = bool(avg is not None and len(prior) >= 5 and last >= max(avg * 3, 30))
    return last, _r(avg, 1), surge


def evaluate(b: dict, conv: Optional[float], conv_src: str, quotes: list, closes: list, shorts: list,
             rev: Optional[dict], today: date, ma60: Optional[float] = None, holders: Optional[int] = None) -> dict:
    """單一可轉債 → 指標＋分類（buy 可以買 / chance 有機會 / exit 該出場 / watch 觀察）"""
    traded = [q for q in quotes if q.get("close")]
    cb_5d = ((traded[-1]["close"] / traded[-6]["close"] - 1) * 100) if len(traded) >= 6 and traded[-6]["close"] else None
    lastq = quotes[-1] if quotes else {}
    cb_px = traded[-1]["close"] if traded else (lastq.get("ref") or lastq.get("avg"))
    cb_date = traded[-1]["date"] if traded else lastq.get("date")
    stock = closes[-1][1] if closes else None
    parity = stock / conv * 100 if stock and conv else None
    premium = (cb_px / parity - 1) * 100 if cb_px and parity else None
    gap = parity - cb_px if parity and cb_px else None
    done = 1 - b["outstanding"] / b["issue_amt"] if b.get("issue_amt") and b.get("outstanding") is not None else None
    d_issue = (today - date.fromisoformat(b["issue_date"])).days if b.get("issue_date") else None
    d_mat = (date.fromisoformat(b["maturity_date"]) - today).days if b.get("maturity_date") else None
    d_put = (date.fromisoformat(b["put_date"]) - today).days if b.get("put_date") else None
    if d_put is not None and d_put < 0:
        d_put = None
    pos = low_issue(closes, b.get("issue_date"))
    is_low = pos is not None and pos <= 0.4
    yoy = (rev or {}).get("yoy")
    cum = (rev or {}).get("cum_yoy")
    rev_up = yoy is not None and yoy > 0
    rev_turn = rev_up and cum is not None and cum <= 0          # 單月轉正、累計還是負＝營收負轉正
    sh = short_signal(shorts)
    vlast, vavg, vsurge = vol_surge(quotes)
    above_ma60 = bool(stock and ma60 and stock >= ma60)

    stage = []
    conv_start = b.get("conv_start")
    if d_issue is not None and d_issue >= 0 and (today.isoformat() < conv_start if conv_start else d_issue <= NEW_DAYS):
        stage.append("定價後・開放轉換前")
    if (d_mat is not None and 0 <= d_mat <= NEAR_MATURITY) or (d_put is not None and d_put <= NEAR_PUT):
        stage.append("快到期" if d_mat is not None and d_mat <= NEAR_MATURITY else "賣回日將到")

    grab = bool(cb_px and parity and cb_px > parity and cb_px >= FLOOR and (vsurge or (cb_5d is not None and cb_5d >= 3)))
    near_par = cb_px is not None and cb_px <= FLOOR
    high_zone = bool(closes and stock and stock >= max(c for _, c in closes[-250:]) * 0.9)
    lock = bool(gap is not None and gap > 0 and sh["surge"] and high_zone)

    flow = [  # 六大流程
        {"n": 1, "name": "低檔發債", "on": is_low, "unknown": pos is None},
        {"n": 2, "name": "營收成長", "on": rev_up, "unknown": yoy is None},
        {"n": 3, "name": "利多消息", "on": False, "unknown": True},
        {"n": 4, "name": "融券大增", "on": sh["surge"], "unknown": sh["now"] is None},
        {"n": 5, "name": "CB量大增", "on": vsurge, "unknown": not quotes},
        {"n": 6, "name": "融券大減", "on": sh["drop"], "unknown": sh["now"] is None},
    ]

    good, warn = [], []
    if grab:
        good.append(f"搶購訊號：CB {cb_px:.2f} > 理論價 {parity:.1f}（溢價 {premium:.1f}%）且" +
                    ("CB 量大增" if vsurge else f"5 日漲 {cb_5d:.1f}%") + "：大戶搶 CB、看好現股")
    if near_par:
        good.append(f"CB {cb_px:.2f} 貼近面額 100：保底、安全邊際高" + ("（低於面額現賺）" if cb_px < 100 else ""))
    if is_low:
        good.append(f"低檔發債（發債時股價在一年區間 {pos:.0%} 位置）")
    if rev_turn:
        good.append(f"營收負轉正（單月年增 {yoy:+.1f}%、累計 {cum:+.1f}%）")
    elif rev_up:
        good.append(f"營收成長（單月年增 {yoy:+.1f}%）")
    if vsurge and not grab:
        good.append(f"CB 成交量大增（{vlast:.0f} 張，20 日均 {vavg:.0f} 張）")
    if sh["drop"]:
        good.append("融券大減")
    if stage:
        good.append("、".join(stage) + "（可轉債兩波發動時機）")
    if done is not None and done <= 0.2:
        good.append(f"已轉換率低（{done:.0%}）")
    if above_ma60:
        good.append("股價站上季線")
    if lock:
        warn.append("折價＋現股高檔＋融券大增：CB 持有人在融券鎖利（高檔鎖利），考慮出場")
    elif sh["surge"]:
        warn.append(f"融券大增（5 日 {sh['chg5']:+.0f} 張）：相對高點，考慮出場")
    if done is not None and done >= 0.5:
        warn.append(f"已轉換 {done:.0%}：籌碼已大量換成股票")
    if yoy is not None and yoy < 0 and not rev_up:
        warn.append(f"營收衰退（單月年增 {yoy:+.1f}%）")
    if ma60 and stock and stock < ma60:
        warn.append("股價跌破季線")

    pts = (2 if grab else 0) + (2 if near_par else 0) + (2 if is_low else 0) \
        + (2 if rev_turn else 1 if rev_up else 0) + (1 if vsurge and not grab else 0) + (1 if sh["drop"] else 0) \
        + (1 if stage else 0) + (1 if done is not None and done <= 0.2 else 0) + (1 if above_ma60 else 0) \
        - (3 if sh["surge"] else 0) - (1 if done is not None and done >= 0.5 else 0)
    if sh["surge"]:
        tier = "exit"
    elif (grab or near_par) and (rev_up or is_low) and (done is None or done < 0.5) and (cb_px is None or cb_px <= 115):
        tier = "buy"
    elif pts >= 3:
        tier = "chance"
    else:
        tier = "watch"
    if cb_px is None:
        tier = "watch"

    return {
        "code": b["code"], "name": b.get("name"), "sid": b.get("sid"), "issuer": b.get("issuer"),
        "cb_price": _r(cb_px), "cb_date": cb_date, "cb_chg": lastq.get("chg") if traded and traded[-1] is lastq else None,
        "stock_price": _r(stock), "stock_date": closes[-1][0] if closes else None,
        "conv_price": _r(conv), "conv_src": conv_src,
        "shares_per_bond": round(100000 / conv) if conv else None,       # 每張（面額 10 萬）可換股數
        "parity": _r(parity), "premium_pct": _r(premium, 1), "gap": _r(gap),
        "grab": grab, "near_par": near_par, "lock": lock, "cb_5d_pct": _r(cb_5d, 1),
        "converted_pct": _r(done * 100, 1) if done is not None else None,
        "outstanding_yi": _r(b["outstanding"] / 1e8, 2) if b.get("outstanding") else None,
        "issue_date": b.get("issue_date"), "maturity_date": b.get("maturity_date"), "put_date": b.get("put_date"),
        "days_since_issue": d_issue, "days_to_maturity": d_mat, "days_to_put": d_put,
        "stage": stage, "issue_pos": _r(pos, 2),
        "rev_ym": (rev or {}).get("ym"), "rev_yoy": _r(yoy, 1), "rev_cum_yoy": _r(cum, 1), "rev_turn": rev_turn,
        "short_now": sh["now"], "short_chg5": sh["chg5"], "short_chg5_pct": sh["chg5_pct"],
        "short_surge": sh["surge"], "short_drop": sh["drop"],
        "cb_vol": vlast, "cb_vol_avg20": vavg, "cb_vol_surge": vsurge,
        "ma60": _r(ma60), "above_ma60": above_ma60, "holders": holders,
        "flow": flow, "good": good, "warn": warn, "score": pts, "tier": tier,
    }
