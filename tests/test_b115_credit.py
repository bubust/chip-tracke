"""B115 證交所台股儀表板（BFIJ3U）：全市場整戶擔保維持率、低於 130% 戶數、補繳、處分
用戶 11/17 貼別的網站：11/16 整戶 165.98%、追繳 733 戶 3.97 億、處分 247 戶 5.67 億 → 官方 BFIJ3U 一模一樣
python -m pytest tests/test_b115_credit.py -q（不連網）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wave import data as D, service as SV  # noqa: E402

J = {"stat": "OK", "date": "20261116", "days": 3, "data": [
    {"date": "20261106", "crdAmt": 1, "keepRate": 158.05, "belowAccNum": 3382, "callAccNum": 1, "callAmt": 3806000000, "exeAccNum": 171,
     "exeAmt": 517000000, "marginAccNum": 1, "marginAccRate": 0.2},
    {"date": "20261113", "crdAmt": 95939008660, "keepRate": 177.48, "belowAccNum": 209, "callAccNum": 39, "callAmt": 7485100, "exeAccNum": 27,
     "exeAmt": 16722680, "marginAccNum": 60177, "marginAccRate": 0.22},
    {"date": "20261116", "crdAmt": 102384474990, "keepRate": 165.98, "belowAccNum": 733, "callAccNum": 514, "callAmt": 397022000, "exeAccNum": 247,
     "exeAmt": 566802830, "marginAccNum": 71142, "marginAccRate": 0.26}]}


def test_parse_and_summary():
    rows = D.parse_credit_keep(J)
    assert [r["date"] for r in rows] == ["2026-11-06", "2026-11-13", "2026-11-16"] and rows[-1]["below_acc"] == 733
    one = D.parse_credit_keep({k: v for k, v in J["data"][2].items()} | {"stat": "OK"})             # 單日 BFIJ3U 的格式
    assert len(one) == 1 and one[0]["keep"] == 165.98
    assert D.parse_credit_keep({"stat": "很抱歉，沒有符合條件的資料!"}) == []
    c = SV.credit_out(rows)
    assert (c["keep"], c["below"], c["call_yi"], c["exe"], c["exe_yi"]) == (165.98, 733, 3.97, 247, 5.67)   # 跟別的網站一樣
    assert c["chg"] == -11.5 and c["low"] == 158.05 and c["mult"] == round(733 / ((3382 + 209) / 2), 1)
    assert SV.credit_out([])["ok"] is False
