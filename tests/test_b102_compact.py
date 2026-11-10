"""B102 全系統整理（用戶：「版面太攏長，精簡、保留重要的、一樣的不要一直重複」）——伺服器端兩個矛盾修掉：
- 站穩 3-1 低點 42,050（三層驗證全過）以後，狀態不能再寫「還沒跌完、隨時再破低」→ 改成升級後的說法（頸線、第一道關上緣）
- 0.382 41,481 已經過了：進場改成「等反彈的第二隻腳」，目標給還沒到的下一個價位（0.5 42,651 已過 → 0.618 43,820）
python -m pytest tests/test_b102_compact.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b101_neck as T  # noqa: E402


def _o(price):
    return W.structure(T.BIG, T.SMALL, price, 41834.0, 43000.0, T.LB, first_leg=T.FIRST, full=17015.0)


def test_status_after_upgrade():
    o = _o(42844.0)
    assert o["tag"] == "up3" and "升級日線級反彈" in o["status"] and "隨時再跌" not in o["status"]
    assert "42,925～43,449" in o["status"] and "44,052" in o["status"] and o["lines"][2] == o["status"]


def test_entry_after_0382_targets_next_level():
    e = _o(42844.0)["entry"]
    assert e and [round(v) for v in e["zone"]] == [40401, 41040]                   # 37,694→43,108 的 0.382～0.5
    assert round(e["target"]) == 43820 and "0.618" in e["t"]                       # 0.5 42,651 已過 → 0.618


def test_before_upgrade_unchanged():
    """還沒站穩 42,050（11/8 的狀態）：照舊，不改狀態"""
    sm = T.SMALL[:9] + [{"p": 39129, "t": "L"}, {"p": 40845, "t": "H"}, {"p": 39977, "t": "L"}]
    o = W.structure(T.BIG, sm, 40286.0, 41677.0, 43000.0, T.LB, full=17015.0)
    assert o["tag"] == "below1" and "還在第一道關" in o["status"] and o["entry"] is None
