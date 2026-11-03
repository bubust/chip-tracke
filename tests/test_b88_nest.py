"""B88 她 11/2 晚上 23:00 的貼文（@fanny55520 台指期，夜盤 45,487 大噴之後回到 44,832）：
- 「也可能試到 1-4-b 落底還有一個小 c」vs「如果真的是啟動 1-5，也有一個反抽測 45,140～45,166」
- 44,873 短多、防守 44,832～44,810；決戰關卡 45,146～45,173：只是 1-5-2 反抽（死貓跳）會卡住；帶量實體紅 K 站穩 45,173＝真 c，
  移動停利推上 45,080 → 之後鎖利 45,145～45,160
- c 波目標階梯：T1 45,364～45,410 → T2 45,487～45,583（前高 45,597，1-4-c 極限區）→ T3 45,830～45,891（升格 3-2-c）
之後：c 到 45,347（差一點到 T1）就掉頭，她停利出場；夜盤跌到 44,271、11/3 早盤 44,216。
網站改之前（11/3 09:44）：60 分只剩「3（第 3 段主跌）／2-b」，她的第一種（4-b 小 c／第 5 小段）沒列；B87 的兩種只在反彈第一段才算。
python -m pytest tests/test_b88_nest.py -q（不連網）"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_b86_nest as B86  # noqa: E402
from wave import nest as N  # noqa: E402
from wave import panel as PN  # noqa: E402

H = (45487, "H", 305, "11-02")                     # 11/02 21:30 夜盤大噴
PULL = [H, (44832, "L", 306, "11-02")]             # 22:45 回到 44,832（她 23:00 發文）
UP2 = PULL + [(45347, "H", 307, "11-02")]          # 23:15 小 c 到 45,347
NOW = [H, (44271, "L", 312, "11-03")]              # 夜盤收在 44,271 附近（11/3 09:44 快照）


def _build(extra, price, tfn="60 分"):
    rows = B86.LIVE[:-1] + extra
    pts = [{"i": i, "p": float(p), "t": t, "ci": i + 1} for p, t, i, _ in rows]
    pts[-1].update(ci=None)
    day = {i: dt.date(2026, int(d[:2]), int(d[3:])) for _, _, i, d in rows}
    times = [1791288000 + 3600 * k for k in range(rows[-1][2] + 1)]
    tdate = lambda i: day.get(i) or max(v for k, v in day.items() if k <= i)   # noqa: E731
    return N.build({"pivots": pts[:-1], "tentative": pts[-1]}, times, price, tfn, B86.DAILY, B86.DATES, tdate=tdate,
                   tlabel=lambda i: f"#{i}")


def test_pullback_lists_her_two_kinds():
    out = _build(PULL, 44976.0)
    assert out["primary"]["path"] == "3" and out["alternate"]["path"] == "4-b"             # 第二種 3-3 vs 第一種 3-1-4-b
    tw = out["two"]
    assert tw["phase"] == "pull" and tw["one"]["her"] == "3-1-4-b" and tw["two"]["her"] == "3-3"
    assert tw["one"]["b"] == [45487, 44832]


def test_pullback_levels_match_her_2300_numbers():
    o = _build(PULL, 44976.0)["two"]["one"]
    g = o["gate"]
    assert [round(g["lo"]), round(g["hi"])] == [45146, 45173]                                # 她：決戰關卡 45,146～45,173
    assert [round(v) for v in g["stop"]] == [45082, 45160]                                   # 她：移動停利 45,080 → 45,145～45,160
    lad = {c["t"]: [round(c["lo"]), round(c["hi"])] for c in o["c"]}
    assert lad == {"T1": [45363, 45410], "T2": [45487, 45597], "T3": [45830, 45892]}         # 她：45,364～45,410／45,487～45,583（45,597）／45,830～45,891
    assert not any(c["hit"] for c in o["c"])


def test_pullback_gates_and_plan():
    out = _build(PULL, 44976.0)
    ks = [g["k"] for g in out["gates"]]
    assert ks[:2] == ["決戰關卡", "破底"]
    assert "45,146～45,173" in out["gates"][0]["t"] and "死貓跳" in out["gates"][0]["t"]
    v1, v2, v3 = [x for x in out["plan"] if x.startswith("版本")]
    assert "防守放 44,832 下方" in v1 and "45,082" in v1 and "T1 45,363～45,410" in v1
    assert "第 5 小段啟動＝她的 3-1-5" in v2 and "45,146～45,173 就卡住" in v2 and "44,006" in v2
    assert "41,932" in v3 and "39,735" in v3 and "44,196～44,052" in v3
    tw = out["two"]
    assert [round(v) for v in tw["two"]["down"]] == [41932, 39735] and tw["two"]["flat"] == [44195.5, 44052]


def test_small_c_in_progress_marks_what_is_done():
    """23:15 小 c 帶量站上 45,173（決戰關卡 ✅），到 45,347 還差一點到 T1；生死線照列，但版本用她的兩種"""
    out = _build(UP2, 45203.0)
    assert out["primary"]["path"] == "2-c" and out["alternate"]["path"] == "4-c"
    tw = out["two"]
    assert tw["phase"] == "up2" and tw["one"]["gate"]["hit"]
    assert [c["hit"] for c in tw["one"]["c"]] == [False, False, False]
    g = next(x for x in out["gates"] if x["k"] == "決戰關卡")
    assert g["ok"]
    assert next(x for x in out["gates"] if x["k"] == "分水嶺")["price"] == 45597              # 4-c 極限區
    v1 = next(x for x in out["plan"] if x.startswith("版本 1"))
    assert "第一種甲" in v1 and "已站上 45,173" in v1 and "小 c 進行中" in v1


def test_now_after_night_drop():
    out = _build(NOW, 44548.0)
    tw = out["two"]
    assert tw["phase"] == "pull" and out["alternate"]["path"] == "4-b"
    assert [round(tw["one"]["gate"]["lo"]), round(tw["one"]["gate"]["hi"])] == [44855, 44903]
    main = {round(t["price"]) for t in tw["one"]["targets"] if t["grp"] == "main"}
    assert main == {44006}


def test_labels_without_source_mapping():
    """30／15 分沒有源頭切組 → 不硬標「她的 3-1-4」、分水嶺也不寫「她 11/2」"""
    out = _build([(45332, "H", 297, "11-02")], 45210.0, tfn="30 分")
    tw = out["two"]
    assert tw and tw["one"]["her"] is None and tw["two"]["her"] is None
    ws = next(g for g in out["gates"] if g["k"] == "分水嶺")
    assert "她 11/2" not in ws["t"]
    assert not any("她的" in x for x in out["plan"] if x.startswith("版本"))


def test_ai_panel_reads_every_phase():
    for extra, px in ((PULL, 44976.0), (UP2, 45203.0), ([(45332, "H", 297, "11-02")], 45210.0)):
        snap = {"nest": {"60m": _build(extra, px)}}
        line, prices = PN._nest_line(snap), PN._nest_prices(snap)
        assert "第一種" in line and "第二種" in line
        if extra is PULL:
            assert "決戰關卡 45,146～45,173" in line and 45146.4 in [round(p, 1) for p in prices]
