"""B99 她的進單規矩回測（research/b99/run.py）：出場規則保守（同一根先算停損）、走一口留一口、研究摘要那句
python -m pytest tests/test_b99_entry.py -q（不連網、不用資料檔）"""
import importlib.util
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_spec = importlib.util.spec_from_file_location("b99_run", os.path.join(ROOT, "research", "b99", "run.py"))
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)


def _Y(rows):
    o, h, l, c = (np.array([r[k] for r in rows], float) for k in range(4))
    return {"o": o, "h": h, "l": l, "c": c}


def test_same_bar_stop_first():
    """同一根同時碰到停損和 T1＝算停損"""
    Y = _Y([(100, 100, 100, 100), (100, 106, 94, 100), (100, 100, 100, 100)])
    r, pts, tag = B.sim(Y, 0, 100.0, 95.0, True, 105.0, 110.0, "E1")
    assert tag == "stop" and pts == -5


def test_walk_one_keep_one():
    """E2：T1 出一半，剩下一半回到成本出場＝賺一半的 T1"""
    Y = _Y([(100, 100, 100, 100), (101, 106, 100.5, 105), (104, 104.5, 99, 100), (100, 100, 100, 100)])
    r, pts, tag = B.sim(Y, 0, 100.0, 95.0, True, 105.0, 110.0, "E2")
    assert tag == "BE" and abs(pts - 2.5) < 1e-9
    r1, pts1, tag1 = B.sim(Y, 0, 100.0, 95.0, True, 105.0, 110.0, "E1")
    assert tag1 == "T1" and pts1 == 5


def test_limit_fill_bar_ignores_target():
    """接刀（掛單成交那根）：碰到目標不算、碰到停損算"""
    Y = _Y([(100, 106, 99, 100), (100, 100, 100, 100)])
    assert B.sim(Y, 0, 100.0, 95.0, False, 105.0, 110.0, "E1")[2] == "time"
    Y = _Y([(100, 101, 94, 100), (100, 100, 100, 100)])
    assert B.sim(Y, 0, 100.0, 95.0, False, 105.0, 110.0, "E1")[2] == "stop"


def test_research_line():
    from wave import service as SV
    st = json.load(open(os.path.join(ROOT, "wave", "stats.json"), encoding="utf-8"))
    x = st.get("entry_b99")
    assert x and x["n_events"] > 0
    line = SV._research_b99(st)[0]
    assert "接刀" in line and "停損放在低點下方" in line
    assert SV._research_b99({}) == []
