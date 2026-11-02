"""B87 她 11/2 的貼文（@fanny55520 台指期 60 分）：44,052 之後的反彈有「兩種」
- 第一種：(3)-1 還沒走完，這段只是 3-1-4 → 標準 45,332～45,410、天花板 45,597；3-1-5 最可能 43,974～43,851、標準 43,704～43,449、
  失敗型雙底 44,417～44,150
- 第二種：3-1 五小波走完 → 3-2：走法 A（a 44,052→45,332；b 守 45,039、極限 44,804～44,881；c 站上 45,410、45,597 → 45,830～46,126）、
  走法 B（44,700↔45,350 來回 2～3 天、偏弱）
網站改之前（11/02 夜盤快照 45,255、高 45,487）：主要 2（＝第二種）、備選卻是 1-2（跟 2 反彈的是同一段、只差級數名稱），
她的第一種（4）排第三；分水嶺寫 46,846、「版本 2：站穩 46,846 → 目標 45,410、45,830、46,249」（目標反而在分水嶺裡面）。
python -m pytest tests/test_b87_nest.py -q（不連網）"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_b86_nest as B86  # noqa: E402
from wave import nest as N  # noqa: E402

NOON = (45332, "H", 297, "11-02")          # 11/02 11:45 日盤高點（她發文時）
NIGHT = (45487, "H", 305, "11-02")         # 11/02 21:00 夜盤高點（線上快照 22:27，現價 45,255）


def _build(tent, price):
    rows = B86.LIVE[:-1] + [tent]
    pts = [{"i": i, "p": float(p), "t": t, "ci": i + 2} for p, t, i, _ in rows]
    pts[-1].update(ci=None)
    day = {i: dt.date(2026, int(d[:2]), int(d[3:])) for _, _, i, d in rows}
    times = [1791288000 + 3600 * k for k in range(rows[-1][2] + 1)]
    tdate = lambda i: day.get(i) or max(v for k, v in day.items() if k <= i)   # noqa: E731
    return N.build({"pivots": pts[:-1], "tentative": pts[-1]}, times, price, "60 分", B86.DAILY, B86.DATES, tdate=tdate,
                   tlabel=lambda i: f"#{i}")


def test_two_kinds_are_primary_and_alternate():
    out = _build(NOON, 45210.0)
    assert out["primary"]["path"] == "2" and out["alternate"]["path"] == "4"                # 第二種 3-2 vs 第一種 3-1-4
    assert {m["p"]: m["text"] for m in out["alternate"]["marks"]}[44052] == "3／c"           # 44,052 只是第 3 小段的終點
    tw = out["two"]
    assert tw["one"]["her"] == "3-1-4" and tw["two"]["her"] == "3-2"                          # 對上源頭第二種切組（3-1、3-2）
    ws = next(g for g in out["gates"] if g["k"] == "分水嶺")
    assert ws["price"] == 45597 and "她 11/2 兩種的分界" in ws["t"] and "46,126" in ws["t"]


def test_first_kind_levels_match_her_numbers():
    o = _build(NOON, 45210.0)["two"]["one"]
    assert [round(v) for v in o["std"]] == [45344, 45410] and o["ceil"] == 45597 and o["hard"] == 46126   # 她：45,332～45,410、45,597
    tg = {round(t["price"]): t["grp"] for t in o["targets"]}
    assert tg[43974] == "main" and tg[43851] == "main"                                       # 她：最可能 43,974～43,851
    assert tg[43704] == "std" and tg[43449] == "std"                                         # 她：標準 43,704～43,449
    assert tg[44417] == "fail"                                                               # 她：失敗型雙底 44,417～
    g1 = next(g for g in _build(NOON, 45210.0)["gates"] if g["k"] == "第一關")
    assert "43,974、43,851" in g1["t"]


def test_second_kind_paths_a_and_b():
    t = _build(NOON, 45210.0)["two"]["two"]
    A, B = t["A"], t["B"]
    assert round(A["b_strict"]) == 45030 and round(A["b_ext"]) == 44843                       # 她：b 守 45,039、極限 44,804～44,881
    assert [round(c["price"]) for c in A["c"]] == [45410, 45597, 45830, 46126, 46249]         # 她：45,410、45,597 → 45,830～46,126
    assert round(B["lo"]) == 44692 and B["hi"] == 45332                                       # 她：44,700↔45,350


def test_plan_versions_follow_her_two_kinds():
    plan = _build(NOON, 45210.0)["plan"]
    v1, v2 = [x for x in plan if x.startswith("版本")]
    assert "第一種 4＝她的 3-1-4" in v1 and "最可能 43,974～43,851" in v1 and "標準 43,704～43,449" in v1
    assert "第二種 2＝她的 3-2" in v2 and "走法 A" in v2 and "走法 B" in v2 and "44,692～45,332" in v2


def test_night_high_updates_levels():
    """夜盤漲到 45,487（過了 0.382、沒過 45,597）：兩種都還在；1-2 退成第三個；第 5 小段目標跟著反彈高點更新"""
    out = _build(NIGHT, 45255.0)
    assert out["primary"]["path"] == "2" and out["alternate"]["path"] == "4" and out["third"]["path"] == "1-2"
    tw = out["two"]
    assert tw["R"] == 45487 and not tw["ceil_hit"]
    c = {round(x["price"]): x["hit"] for x in tw["two"]["A"]["c"]}
    assert c[45410] is True and c[45597] is False
    assert {round(t["price"]) for t in tw["one"]["targets"] if t["grp"] == "main"} == {44006}   # 0.382×(0→3) 變 44,129＞44,052 → 失敗型


def test_version2_targets_are_beyond_the_watershed(monkeypatch):
    """沒有「兩種」時回到 B83 分水嶺（1-2 的 0.786＝46,846）：版本 2 的目標要在分水嶺外面，不能寫「站穩 46,846 → 目標 45,410」"""
    monkeypatch.setattr(N, "two_ways", lambda *a, **k: None)
    out = _build(NIGHT, 45255.0)
    assert out["two"] is None and out["watershed"]["far"] == 46846.23
    v2 = next(x for x in out["plan"] if x.startswith("版本 2"))
    assert "目標 45,410" not in v2 and "下一個看 47,607" in v2
