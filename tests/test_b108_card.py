"""B108 結論卡（用戶 11/13：簡單說現在的位階、在哪個波形裡，然後怎麼試單、怎麼進出場）＋即時價更新時間
- 位階：日線 5-2 回檔（5-1 37,694→44,911 走完）；60 分 A-B-C 三段：A 到 42,371、B 反彈到 44,034（過了 0.618 43,941）、C 還沒走
- 怎麼做（她的對帳單推敲）：線先畫好 → 刺穿又收回才進 → 停損放尖端外；B 段不追多、反彈壓力小量試空、做多等三個大買點
- 「刺穿又收回」偵測用她四筆真實進場的 15 分 K 驗證（11/6 空 40,518、11/9 空 41,970、11/11 多 42,983）
python -m pytest tests/test_b108_card.py -q（不連網）"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b101_neck as T  # noqa: E402

FINE = [{"p": p, "t": t} for p, t in ((43147, "H"), (42165, "L"), (43327, "H"), (42712, "L"), (44911, "H"), (43822, "L"),
                                      (44555, "H"), (43057, "L"), (43532, "H"), (42371, "L"), (44034, "H"))]
K = lambda rows: [{"time": 1794530700 + 900 * i, "open": o, "high": h, "low": l, "close": c} for i, (o, h, l, c) in enumerate(rows)]  # noqa: E731


def _o(price, tail):
    sm = T.SMALL + [{"p": 41873, "t": "L"}, {"p": 44911, "t": "H"}] + tail
    return W.structure(T.BIG, sm, price, 43364.0, 43818.0, T.LB, first_leg=T.FIRST, full=17015.0, fine=FINE)


def test_52_stages_a_b_c_and_new_high():
    sb = lambda o: o["ext3"]["paths"]["push"]["sub"]                  # noqa: E731
    b = sb(_o(43990.0, [{"p": 42371, "t": "L"}]))
    assert (b["stage"], b["a_low"], b["b_hi"], b["c_low"]) == ("B", 42371, 44034, None)     # B 高點用 30 分的 44,034
    a = sb(_o(42450.0, []))
    assert a["stage"] == "A" and a["b_hi"] is None
    c = sb(_o(41900.0, [{"p": 42371, "t": "L"}, {"p": 44034, "t": "H"}]))
    assert (c["stage"], c["c_low"]) == ("C", 41900.0) and [z["hit"] for z in c["z52"]] == [True, False, False]
    assert [int(v + 0.5) for v, _ in c["c52"]] == [42464, 41494]                             # C＝0.618 倍 A、C＝A
    assert _o(45100.0, [{"p": 42371, "t": "L"}])["tag"] != "52"                              # 再創高＝5-1 還在延伸，不是 5-2


def test_card_now_position_and_plays():
    bars = K([(43665, 43707, 43637, 43659), (43595, 43678, 43582, 43676), (43925, 44094, 43774, 44002)])
    c = W.plan_card(_o(43990.0, [{"p": 42371, "t": "L"}]), 43990.0, bars, 100.0, 366.0)
    assert "5-2 回檔" in c["pos"][0] and "37,694→44,911" in c["pos"][0]
    assert "B 段反彈" in c["pos"][1] and "44,034" in c["pos"][1] and "C 段還沒走" in c["pos"][1]
    assert "A-B-C" in c["shape"] and "B 段" in c["shape"]
    assert [x["k"] for x in c["plays"]] == ["wait", "short", "long"]
    assert "43,941、44,034、44,367" in c["plays"][1]["t"] and "42,154～42,165、41,303、40,451～40,715" in c["plays"][2]["t"]
    assert c["tiles"]["up"]["price"] == 44034 and c["tiles"]["down"]["price"] == 42165 and c["tiles"]["stop"]["price"] == 44911
    sg = c["signal"]                                                  # 11/13 08:45：刺過 44,034 到 44,094、收回 44,002 → 試空
    assert sg and sg["side"] == -1 and sg["line"] == 44034 and sg["tip"] == 44094 and sg["stop"] == 44104 and sg["t1"] == 43900
    assert "44,911" in c["flip"] and "△" in c["method"]


def test_card_stage_c_and_fallback():
    c = W.plan_card(_o(41900.0, [{"p": 42371, "t": "L"}, {"p": 44034, "t": "H"}]), 41900.0)
    assert "C 段下跌" in c["pos"][1] and c["plays"][0]["tag"] == "不追空" and "（已到）" in c["plays"][1]["t"]
    assert c["tiles"]["up"]["price"] == 44034 and c["tiles"]["down"]["price"] == 41302.5
    g = W.plan_card(T._s(40286.0) if hasattr(T, "_s") else W.structure(T.BIG, T.SMALL, 40286.0, 41834.0, 43000.0, T.LB), 40286.0)
    assert g and len(g["pos"]) == 2 and g["plays"]


def test_pierce_reclaim_matches_her_entries():
    r = W.pierce_reclaim(K([(42942, 43248, 42892, 43145), (43142, 43327, 42646, 42808), (42809, 42990, 42712, 42957)]),
                         [(42925, "頸線")], 1, 170.0, 400.0)         # 11/11 早：洗到 42,646、09:15 收回 42,957
    assert r and r["tip"] == 42646 and r["close"] == 42957 and r["stop"] == 42629 and r["ago"] == 0
    r = W.pierce_reclaim(K([(39418, 40159, 39313, 40094), (40092, 40481, 39899, 40141), (40138, 40690, 40077, 40524)]),
                         [(40584, "她的線")], -1, 170.0, 400.0)      # 11/6：刺過 40,584 到 40,690、同一根收回
    assert r and r["side"] == -1 and r["tip"] == 40690 and r["stop"] == 40707
    r = W.pierce_reclaim(K([(41799, 41890, 41726, 41878), (41874, 42250, 41863, 42222), (42216, 42317, 42020, 42048)]),
                         [(42050, "3-1 低點")], -1, 170.0, 400.0)    # 11/9：衝到 42,317、10:30 收 42,048 沒站穩
    assert r and r["tip"] == 42317 and r["close"] == 42048


def test_pierce_reclaim_rejects_break_touch_and_stopped():
    deep = K([(43000, 43100, 42950, 43050), (43050, 43060, 42400, 42500), (42500, 43000, 42450, 42960)])
    assert W.pierce_reclaim(deep, [(42925, "線")], 1, 170.0, 400.0) is None            # 刺穿 525 點 > 1 ATR60＝真的跌破
    touch = K([(43000, 43100, 42950, 43050), (43050, 43060, 42915, 42960), (42960, 43000, 42940, 42990)])
    assert W.pierce_reclaim(touch, [(42925, "線")], 1, 170.0, 400.0) is None           # 只刺 10 點
    stopped = K([(42942, 43248, 42892, 43145), (43142, 43327, 42646, 42808), (42809, 42990, 42712, 42957), (42957, 42960, 42600, 42700)])
    assert W.pierce_reclaim(stopped, [(42925, "線")], 1, 170.0, 400.0) is None         # 收回之後又破尖端＝已經停損


def test_ladder_summary_mentions_small_timeframes():
    from wave import advice as AD
    rows = [{"tf": "15m", "dir": -1}, {"tf": "30m", "dir": -1}, {"tf": "60m", "dir": 1}, {"tf": "1d", "dir": 1}, {"tf": "1wk", "dir": 1}]
    t = AD.ladder_summary(rows)
    assert "大小週期都往上" not in t and t.endswith("60 分以上都往上；15 分、30 分短線在回檔")
    assert AD.ladder_summary([dict(r, dir=1) for r in rows]).endswith("大小週期都往上")


def test_quote_cached_and_closed(monkeypatch):
    from wave import futdata as FD, service as SV
    calls = []
    monkeypatch.setattr(FD, "in_session", lambda sym, now=None: True)
    monkeypatch.setattr(FD, "fetch_cnyes_quote", lambda sym: calls.append(sym) or {"price": 44012.0, "ts": int(time.time()) - 3})
    SV._quote_cache.clear()
    q = SV.quote("TX")
    assert q["ok"] and q["price"] == 44012.0 and len(q["time"]) == 8 and abs(q["ts"] - time.time()) < 10
    assert SV.quote("TX") is q and calls == ["TX"]                    # 10 秒內不重抓
    monkeypatch.setattr(FD, "in_session", lambda sym, now=None: False)
    SV._quote_cache.clear()
    assert SV.quote("TX")["ok"] is False and calls == ["TX"]          # 休市不抓
    SV._quote_cache.clear()
