"""B123 她 11/22～11/23（@fanny55520 台指期「T3 MONTHLY／DAILY MOTHER MAP」四張＋11/23 夜盤漲停）
- 日線：50,265→37,694 中間 45,523→47,607 只是停頓（5T、12T 下壓斜率沒切開）＝同一筆；37,694→44,911 第一個有效反彈（4 天 +7,217）；
  44,911→33,719 再跌 11,192 點（距尋底帶上緣 33,640 還有 79 點）
- 月線：50,265 是從 8,268 起算的六年大頂，還是從 12,652 起算的大四浪洗盤；底線 33,640～32,340、極限 29,717；延伸區 31,740～29,717
- 兩類：① 五波下跌（第 4 浪頂過不了 37,694、再殺第 5 浪）② 三波末端：帶量實體站穩第一道牆 37,694，
  第二道牆 40,040→41,992→43,944（50,265→33,719 的 0.382／0.5／0.618）過第一道卡第二道＝大 B 波；連過兩道並站穩 44,911＝大四浪完成
- 11/23 夜盤漲停 40,324：50,265→33,719 正式結束，先當反彈大 B 波；短線鎖利 15 分 K 跌破 5T 或 0.236 39,370（36,280→40,324）；可以去拼 41,992～43,944
python -m pytest tests/test_b123_two_walls.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
from wave import service as SV  # noqa: E402

DAILY = [{"p": p, "t": t} for p, t in ((31740, "L"), (49240, "H"), (39442, "L"), (50265, "H"), (45523, "L"), (47607, "H"),
                                        (37694, "L"), (44911, "H"), (33719, "L"))]
H60 = [{"p": p, "t": t} for p, t in ((44911, "H"), (41627, "L"), (41828, "H"), (39010, "L"), (41071, "H"), (38403, "L"),
                                      (39765, "H"), (35289, "L"), (36396, "H"), (33719, "L"))]
LB = {"big": "日線", "small": "60 分"}
WAVES = {"mid": {"pivots": [{"p": p, "t": t} for p, t in ((17015, "L"), (35879, "H"), (31124, "L"), (34734, "H"), (31740, "L"),
                                                           (49240, "H"), (39442, "L"), (50265, "H"), (37694, "L"), (44911, "H"))]},
         "big": {"pivots": [{"p": p, "t": t} for p, t in ((9231, "L"), (12199, "H"), (8268, "L"), (18650, "H"), (12652, "L"),
                                                           (24449, "H"), (18836, "L"), (23990, "H"), (17015, "L"), (50265, "H"))]},
         "intra15": {"pivots": [{"p": p, "t": t} for p, t in ((36396, "H"), (33719, "L"), (36786, "H"), (35634, "L"), (36642, "H"),
                                                               (35712, "L"), (37195, "H"), (36280, "L"), (40324, "H"), (39617, "L"))],
                     "tentative": {"p": 40324, "t": "H"}}}


def _t(price):
    big = W.merge_pause(DAILY)
    small = H60 + ([{"p": 40324, "t": "H"}] if price < 40324 else [])   # 11/23 夜盤漲停的高點
    return W.structure(big, small, price, 38290.0, 39000.0, LB, full=17015.0)


def _fr(price):
    t = _t(price)
    t["frame"] = SV._frame_for(t, WAVES, {}, price)
    return t


def test_merge_pause():
    m = W.merge_pause(DAILY)
    assert [q["p"] for q in m[-4:]] == [50265, 37694, 44911, 33719]
    old = DAILY[:-1] + [{"p": 42371, "t": "L"}]                              # 11/13：42,371 沒破 37,694 → 不併（她那時還用 5-2）
    assert W.merge_pause(old) == old
    wide = DAILY[:5] + [{"p": 48500, "t": "H"}] + DAILY[6:]                  # 停頓彈太多（超過一半）→ 不併
    assert W.merge_pause(wide) == wide


def test_frame_numbers():
    t = _fr(40324.0)
    fr = t["frame"]
    assert (t["big"]["T"], t["big"]["L1"], t["big"]["H2"], t["big"]["ext"]) == (50265, 37694, 44911, 33719)
    assert [W._fmt(v) for _, v in fr["w2"]] == ["40,040", "41,992", "43,944"]               # 她：40,040／41,992／43,944
    assert [W._fmt(v) for v in fr["band"]] == ["33,640", "32,340"]                          # 她：33,640～32,340
    assert [W._fmt(v) for v in fr["ext_band"]] == ["31,740", "29,717"]                      # 她：31,740～29,717
    assert fr["mo"] == {"a": 8268, "b": 12652}                                              # 她：從 8,268／12,652 起算
    assert W._fmt(fr["d236"]["v"]) == "39,370" and fr["d236"]["lo"] == 36280                # 她：0.236 39,370
    assert fr["stage"] == "w2" and fr["dev"] == 2 and "正式結束" in fr["status"] and "大 B 波" in fr["status"]


def test_frame_card():
    c = W.plan_card(_fr(40324.0), 40324.0)
    tl = c["tiles"]
    assert (tl["up"]["price"], round(tl["down"]["price"]), tl["stop"]["price"]) == (41992, 39370, 37694)
    assert [x["tag"] for x in c["plays"]] == ["波段多單", "短線鎖利", "第二道牆"] and "41,992～43,944" in c["plays"][2]["t"]
    mp = c["map"]
    assert [v["now"] for v in mp["versions"]] == [False, True, False]
    assert [p["p"] for p in mp["path"]][:4] == [50265, 37694, 44911, 33719] and mp["path"][-1]["now"]
    assert "37,694" in c["flip"] and "44,911" in c["flip"]


def test_stages():
    assert _fr(38500.0)["frame"]["stage"] == "w2"            # 碰過 40,324 又拉回，還在第二道牆的發展裡
    f0 = _fr(37000.0)["frame"]                               # 跌回第一道牆下＝回到五波看法
    assert f0["stage"] == "w0" and f0["dev"] == 1
    c = W.plan_card(_fr(37000.0), 37000.0)
    assert c["tiles"]["up"]["price"] == 37694 and c["map"]["versions"][0]["now"]
    assert _fr(44000.0)["frame"]["stage"] == "w2p" and _fr(45000.0)["frame"]["dev"] == 3


def test_no_frame_for_her_52():
    """5-2 那套（11/13～11/17：44,911 之後 42,371 沒破 37,694）不會被兩道牆蓋掉"""
    t = W.structure(DAILY[:-1] + [{"p": 42371, "t": "L"}], H60[:3], 42500.0, None, None, LB)
    assert t is None or W.big_frame(t, 42500.0) is None
    t2 = _t(40324.0)                                          # 沒跌破起漲點（只給到 31,740 之前的低點）→ 不升級
    assert W.big_frame(t2, 40324.0, 17015.0, lows=[31740.0, 39442.0]) and W.big_frame(t2, 40324.0, 17015.0, lows=[31740.0, 33000.0]) is None


def _bars():
    """日 K：11/06 37,694（232,573 口）、11/12 44,911、11/23 33,719（205,533 口）、11/24 還沒收"""
    import datetime as dt
    out, d = [], dt.date(2026, 10, 1)
    while d <= dt.date(2026, 11, 24):
        if d.weekday() < 5:
            k = d.isoformat()
            v = {"2026-11-06": 232573, "2026-11-23": 205533, "2026-10-15": 150000}.get(k, 100000)
            lo = {"2026-11-23": 33719, "2026-11-06": 37694}.get(k, 40000)
            out.append({"time": k, "open": 45395 if k == "2026-11-02" else 41000, "high": 42000, "low": lo, "close": 40324 if k == "2026-11-24" else 41000, "volume": v})
        d += dt.timedelta(days=1)
    out = [b for b in out if b["time"] not in ("2026-11-09",)] + []
    return out


def test_b124_clock():
    """B124 用戶：注意時間——她的條件都帶天數、收線日期、換手量"""
    wk = [{"time": f"{2025 + (m - 1) // 12}-{(m - 1) % 12 + 1:02d}-01", "close": 30000.0} for m in range(1, 24)]
    ck = W.frame_clock(_bars(), wk, "2026-11-06", "2026-11-12", "2026-11-23", "2026-11-24")
    assert ck["wk_close"] == "2026-11-27" and ck["mo_close"] == "2026-11-30"          # 她：11/27 收週線、11/30 月 K
    assert ck["reb_days"] == 1 and ck["up_days"] == 3                                   # 合成資料拿掉了 11/9（4 天→3 天）
    assert ck["vol"]["l1"] == 232573 and ck["vol"]["reb"] == 205533 and not ck["vol"]["big"]
    assert ck["month"]["low"] == 33719 and ck["month"]["shadow"] == 40324 - 33719 and ck["m20"] is not None
    t = _t(40324.0)
    fr = W.big_frame(t, 40324.0, 17015.0, lows=[31740.0, 39442.0], clock=ck)
    assert any(x.startswith("時間：") and "11/27（五）收週線" in x and "11/30（一）收月線" in x for x in fr["lines"])
    assert any(x.startswith("量：") and "還沒超過" in x for x in fr["lines"])
    c = W.plan_card({**t, "frame": fr}, 40324.0)
    assert any(x.startswith("時間：") for x in c["pos"]) and "現在第 1 天" in c["map"]["versions"][0]["notes"][0]


def test_b125_trapped_zone():
    """B125 她 11/23：開高會湧出 39,500～41,500 的套牢賣壓＝44,911→33,719 這段下跌成交最密的地方"""
    from wave import volume as V
    bars, t = [], 0
    def leg(a, b, n, vol):
        nonlocal t
        for k in range(n):
            p = a + (b - a) * k / n
            q = a + (b - a) * (k + 1) / n
            bars.append({"time": t, "high": max(p, q) + 50, "low": min(p, q) - 50, "volume": vol})
            t += 1
    leg(44911, 43200, 10, 3000)          # 高檔先換手一陣
    for _ in range(4):
        leg(43200, 44300, 3, 3000)
        leg(44300, 43200, 3, 3000)
    leg(43200, 41400, 4, 1500)           # 急殺
    for _ in range(8):                   # 39,000～41,400 箱體來回（量大）
        leg(41400, 39000, 4, 4000)
        leg(39000, 41400, 4, 4000)
    leg(41400, 33719, 12, 2000)          # 再急殺到底
    z = V.trapped(bars, 40324.0)
    assert z[0]["side"] == "at" and 38800 <= z[0]["lo"] <= 39300 and 41200 <= z[0]["hi"] <= 41700 and z[0]["share"] > 0.3
    assert any(x["side"] == "up" and x["lo"] > 42500 for x in z)
    tt = _t(40324.0)
    fr = W.big_frame(tt, 40324.0, 17015.0, lows=[31740.0, 39442.0], supply=z)
    assert any(x.startswith("套牢區") and "現價就在裡面" in x for x in fr["lines"])
    c = W.plan_card({**tt, "frame": fr}, 40324.0)
    assert "套牢賣壓" in [p["tag"] for p in c["plays"]] and c["map"]["when"][-1].startswith("🧱 ")


def test_b126_tf_cards():
    """B126 用戶：切週期，結論卡也要跟著換——週 K 月線格局、60 分反彈、15／30 分短線鎖利線"""
    tt = _t(40324.0)
    fr = W.big_frame(tt, 40324.0, 17015.0, lows=[31740.0, 39442.0], cyc=[8268.0, 12652.0], leg=(36280.0, 40324.0))
    pw = [{"p": p, "t": t} for p, t in ((17015, "L"), (28594, "H"), (26247, "L"), (49240, "H"), (39442, "L"), (50265, "H"), (37694, "L"),
                                         (44911, "H"), (33719, "L"))]
    p60 = [{"p": p, "t": t} for p, t in ((44824, "H"), (39010, "L"), (41071, "H"), (38403, "L"), (39765, "H"), (33719, "L"), (40324, "H"))]
    p15 = [{"p": p, "t": t} for p, t in ((36396, "H"), (33719, "L"), (36786, "H"), (35634, "L"), (37195, "H"), (36280, "L"), (40324, "H"))]
    o = W.frame_tfs(fr, 40324.0, {"1wk": pw, "60m": p60, "15m": p15}, {"15m": 40224.0})
    assert set(o) == {"1wk", "60m", "15m"}
    assert o["1wk"]["map"]["tag"] == "T3 MONTHLY MOTHER MAP" and [v["title"].split("｜")[0] for v in o["1wk"]["map"]["versions"]] == ["從 8,268 起算", "從 12,652 起算"]
    assert (o["1wk"]["tiles"]["up"]["price"], o["1wk"]["tiles"]["down"]["price"], W._fmt(o["1wk"]["tiles"]["stop"]["price"])) == (44911, 33640, "29,717")
    assert o["60m"]["map"]["path"][0]["p"] == 44911 and round(o["60m"]["tiles"]["down"]["price"]) == 37801   # 60 分窗口沒有 44,911 → 接在最前面
    assert o["15m"]["tiles"]["down"]["price"] == 40224.0 and "36,280→40,324" in o["15m"]["map"]["title"]


def test_b127_after_33719_confirmed_and_pullback():
    """B127 11/25：33,719 確認成日線低點、多了暫定高點 40,324 → 還是要併停頓；33,719→40,900 之後壓回 → 她的劇本 A／B；三段版面"""
    m = W.merge_pause(DAILY + [{"p": 40324, "t": "H"}])
    assert [q["p"] for q in m[-5:]] == [50265, 37694, 44911, 33719, 40324]
    small = H60 + [{"p": 40900, "t": "H"}]
    t = W.structure(W.merge_pause(DAILY), small, 37807.0, 37846.0, 39000.0, LB, full=17015.0)
    ck = {"ma5": 37846.2, "ma12": 40328.33, "mid_lows": [35634.0, 35712.0]}
    fr = W.big_frame(t, 37807.0, 17015.0, lows=[31740.0, 39442.0], cyc=[8268.0, 12652.0], leg=(36280.0, 40900.0), clock=ck)
    pl = fr["pull"]
    assert (round(pl["r5"]), round(pl["r618"]), pl["base"], pl["prev_low"], pl["state"]) == (37310, 36462, 36280, 35712, "A")   # 她：37,310～36,462、36,280、35,712
    assert any(x.startswith("壓回（她 11/25）") for x in fr["lines"]) and "健康壓回" in fr["status"]
    t["frame"] = fr
    c = W.plan_card(t, 37807.0)
    pw = [{"p": p, "t": tt} for p, tt in ((28594, "H"), (26247, "L"), (49240, "H"), (39442, "L"), (50265, "H"), (37694, "L"), (44911, "H"), (33719, "L"))]
    c["tfs"] = W.frame_tfs(fr, 37807.0, {"1wk": pw, "60m": [{"p": 41000, "t": "H"}] + small[1:], "15m": small[5:]}, {})
    assert c["tfs"]["1wk"]["map"]["path"][0]["p"] == 17015                         # 週 K 窗口沒有 17,015 → 接在最前面
    v = W.frame_views(c, fr, 37807.0)
    assert set(v) >= {"1d", "1wk", "60m"}
    d = v["1d"]
    assert [s_["title"] for s_ in d["scen"]] == ["劇本 A｜健康壓回", "劇本 B｜失速"] and d["scen"][0]["now"]
    assert d["tiles"]["stop"]["price"] == 36280 and "40,328" in d["plays"][2]["t"] and "40,040" in d["plays"][2]["t"]
    assert all(not x.startswith(("時間：", "量：", "套牢區")) for x in d["detail"])
    assert v["60m"]["scen"][0]["title"] == "60 分 a-b-c 洗盤" and v["60m"]["where"].startswith("60 分：")
    b = W.big_frame(t, 36000.0, 17015.0, lows=[31740.0, 39442.0], leg=(36280.0, 40900.0), clock=ck)
    assert b["pull"]["state"] == "B" and "失速" in b["status"]
