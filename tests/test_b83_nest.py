"""B83 她 10/28 的最新貼文（@fanny55520 台指期 60 分）：系統的多層浪名要跟她一樣看。
她：50265 起 (1) 48413、(2) 49594、(3) 46107、(4) 47555、45523 新低，現在反彈貼回 50265 下來的下降趨勢線（約 46,919）。
  版本 1「維持 C-3 架構（C-3-2）」：極限區 46,969～47,120，被壓回 → 跌破 46,779 脈動斷裂、再跌破 46,564～46,443 確認重啟 C-3-3
  版本 2「級數轉浪」：越過下降趨勢線並站穩 47,120 → 47,555＝C-1-4、45,523＝C-1-5，日線 C-2／C-B 反彈：
    0.382＝47,334（＝45,523→46,846→46,006 的 c＝a 47,329）、前高頸線 47,555→0.5＝47,894、0.618＝48,454
python -m pytest tests/test_b83_nest.py -q（不連網）"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import nest as N  # noqa: E402

# 線上台指期 60 分 K 的轉折（θ＝2×ATR% 中位數，50265 起 26 段；10/28 夜盤 46,962 用鉅亨 5 分 K 補）：(價, 高低, 第幾根)
LIVE = [(50265, "H", 0), (49842, "L", 10), (50117, "H", 12), (49253, "L", 20), (49692, "H", 29), (48788, "L", 36), (49226, "H", 40),
        (48413, "L", 43), (49594, "H", 51), (48240, "L", 67), (49200, "H", 87), (46674, "L", 110), (47166, "H", 112), (46456, "L", 115),
        (47634, "H", 124), (46107, "L", 141), (47033, "H", 155), (46222, "L", 161), (46920, "H", 162), (46136, "L", 171), (47288, "H", 180),
        (46596, "L", 184), (47555, "H", 196), (45523, "L", 216), (46846, "H", 218), (46006, "L", 223), (46962, "H", 235)]
# 日 K 主要劇本（線上）：39,442（7/29）→ 50,265（10/6）是第 1 浪，現在第 2 浪 → 60 分第一層用 A-B-C
DAILY = {"kind": "impulse", "current": "2", "labels": [{"i": 0, "p": 39442}, {"i": 1, "p": 50265}, {"i": 2, "p": 45523}]}
DATES = ["2026-07-29", "2026-10-06", "2026-10-27"]


def _build(price=46962.0, t_now=235):
    pts = [{"i": i, "p": float(p), "t": t, "ci": i + 2} for p, t, i in LIVE]
    pts[-1].update(p=float(price), i=t_now, ci=None)
    times = [1791288000 + 3600 * k for k in range(t_now + 1)]
    return N.build({"pivots": pts[:-1], "tentative": pts[-1]}, times, price, "60 分", DAILY, DATES,
                   tdate=lambda i: dt.date(2026, 10, 6) + dt.timedelta(days=i // 19), tlabel=lambda i: f"#{i}")


def test_too_many_legs_are_merged_not_blank():
    """以前：50265 起 26 段 > MAX_PIV → 網站的台指期 60 分多層浪名一片空白（「拆不出合規則的數法」）"""
    out = _build()
    assert out["ok"] and out["anchor"]["p"] == 50265 and out["anchor"]["how"] == "daily"
    assert out["n_seg"] <= N.NEST_SEG and out["merged"] == 26 - out["n_seg"]
    kept = {m["p"] for m in out["primary"]["marks"]}
    assert {48413, 49594, 46107, 47555, 45523, 46846, 46006} <= kept         # 她圖上的 (1)～(4)、新低、反彈的 a、b 都留著


def test_her_two_versions():
    out = _build()
    assert out["evidence"] == {"trend": False, "f382": False}
    P, A = out["primary"], out["alternate"]
    # 版本 1：C-3-2（她的字一模一樣）：C-1 到 46,107、C-2 弱勢橫臺到 47,555、C-3-1 到 45,523、現在 C-3-2 反彈
    assert P["path"] == "C-3-2-c" and P["with_trend"]
    labs = {m["p"]: m["text"] for m in P["marks"]}
    assert labs[46107] == "1-5" and labs[47555] == "2-c" and labs[45523] == "3-1"
    # 版本 2：五段走完（47,555＝第 4 段、45,523＝第 5 段）→ B 段反彈（她：C-2 或 C-B）
    assert A["path"] == "B-c" and not A["with_trend"]
    labs = {m["p"]: m["text"] for m in A["marks"]}
    assert labs[47555] == "4-c" and labs[45523] == "A／5"


def test_watershed_and_trendline_match_her():
    out = _build()
    tl = out["trendline"]
    assert tl["from"]["p"] == 50265 and tl["to"]["p"] == 47555                # 她的線：50265 → 49594 → 47555
    assert abs(tl["now"] / 46969 - 1) < 0.003
    g = {x["k"]: x for x in out["gates"]}
    assert list(g)[:2] == ["分水嶺", "前提"]
    ws = out["watershed"]
    assert round(ws["hi"]) == 47120 and ws["path"] == "C-3-2-c"               # 0.786 × (47555→45523)
    assert "47,555" in g["分水嶺"]["t"] and "B-c" in g["分水嶺"]["t"]
    v1 = next(x for x in out["plan"] if x.startswith("版本 1"))
    assert "47,120" in v1 and "46,779" in v1 and "46,539" in v1               # 她：46,779 脈動斷裂、46,564～46,443 確認
    assert next(x for x in out["plan"] if x.startswith("版本 2"))


def test_version2_targets_match_her():
    out = _build()
    g = {x["k"]: x for x in out["gates"]}
    assert round(g["第一關"]["price"]) == 47334 and "47,329" in g["第一關"]["t"]  # 0.382＝c＝a
    assert round(g["第二關"]["price"]) == 47894 and "47,555 → 47,894" in g["第二關"]["t"]
    assert round(g["第三關"]["price"]) == 48454
    assert [x["k"] for x in out["gates"]][-1] == "失敗"


def test_crossing_the_watershed_switches_to_version2():
    """越過趨勢線、站上 47,120 → 級數轉浪（B-c）變主要；C-3-2 已經超過 0.786 → 不在前三名；分水嶺換成下一個還成立的「大段還在走」數法"""
    out = _build(47250.0, 237)
    assert out["evidence"]["trend"] and not out["evidence"]["f382"]
    assert out["primary"]["path"] == "B-c"
    assert all(x["path"] != "C-3-2-c" for x in (out["primary"], out["alternate"], out["third"]) if x)
    assert out["watershed"] is None or out["watershed"]["far"] > 47250


def _walk(nd):
    yield nd
    for s in nd.get("subs") or []:
        yield from _walk(s)


def test_wave3_is_never_a_diagonal():
    seq = [{"i": i, "p": float(p), "t": t, "ci": i + 2} for p, t, i in LIVE]
    while len(seq) - 1 > N.NEST_SEG:
        seq = N.drop_smallest(seq)
    for c in N.parse(seq, 0, top_k=200):
        for nd in _walk(c["tree"]):
            if nd["k"] == "imp" and len(nd["subs"]) >= 3:
                assert nd["subs"][2]["k"] in ("imp", "atom")


def test_fifth_wave_taking_too_long_costs_more():
    P = N._Parser([{"i": i, "p": p, "t": t} for p, t, i in
                   [(100, "H", 0), (90, "L", 2), (95, "H", 4), (80, "L", 6), (86, "H", 8), (75, "L", 40)]])
    pens, extra = P._rules("imp", [0, 1, 2, 3, 4, 5], -1, 5, False)
    assert extra > 0                                                         # 第 5 段 32 根 > 2.618 × 2 根
    P2 = N._Parser([{"i": i, "p": p, "t": t} for p, t, i in
                    [(100, "H", 0), (90, "L", 2), (95, "H", 4), (80, "L", 6), (86, "H", 8), (75, "L", 12)]])
    assert P2._rules("imp", [0, 1, 2, 3, 4, 5], -1, 5, False)[1] == 0


def test_drop_smallest_keeps_start_extreme_and_now():
    seq = [{"i": i, "p": float(p), "t": t} for p, t, i in LIVE]
    out = N.drop_smallest(seq)
    assert len(out) == len(seq) - 2 and out[0]["p"] == 50265 and out[-1]["p"] == 46962
    assert any(q["p"] == 45523 for q in out)
    # 高點還是高點、低點還是低點，而且交錯
    assert all(out[k]["t"] != out[k + 1]["t"] for k in range(len(out) - 1))


def test_night_save_job(monkeypatch):
    from wave import router as R
    calls = []
    monkeypatch.setattr(R.FD, "in_session", lambda sym, *a: True)
    monkeypatch.setattr(R.FD, "live_bars", lambda sym, *a, **k: calls.append(sym) or [])
    R.scheduled("night_save")
    assert calls == ["TX"]
