"""B96 用 15 分 K 回測 15 分週期的劇本（research/b96）：網站 15 分的劇本卡改用 15 分自己的回測，30／60 分照舊用 60 分（B81）
python -m pytest tests/test_b96_setups15.py -q（不連網）"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from wave import service as S  # noqa: E402


def test_setup_tfc_uses_15m_results_only_for_15m():
    sres = {"intra": {"L": {}}, "intra15": {"L": {"順勢": {"n": 1}}}}
    assert S._setup_tfc("15m", sres) == "intra15"
    assert S._setup_tfc("30m", sres) == "intra" and S._setup_tfc("60m", sres) == "intra"
    assert S._setup_tfc("15m", {"intra": {}}) == "intra"                    # 還沒有 15 分結果 → 照舊用 60 分
    assert S._setup_tfc("1d", sres) == "1d" and S._setup_tfc("1wk", sres) == "1wk"


def test_stats_has_15m_setups():
    st = json.load(open(os.path.join(ROOT, "wave", "stats.json"), encoding="utf-8"))
    su = st["setups"]["intra15"]
    assert su["period"] and set(su) >= {"L", "S", "B"}
    for sid in ("L", "S", "B"):
        for tr, r in su[sid].items():
            assert tr in ("順勢", "逆勢") and {"n", "win", "rw", "edge", "pass", "worse"} <= set(r)
            assert 0 <= r["win"] <= 1 and 0 <= r["rw"] <= 1 and r["n"] >= 50


def test_load15_sums_three_5min_slots(tmp_path):
    import importlib.util                                                   # research 底下很多 run.py，用唯一的名字載入
    spec = importlib.util.spec_from_file_location("b96_run", os.path.join(ROOT, "research", "b96", "run.py"))
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    (tmp_path / "twii_15m.csv").write_text("date,o,h,l,c\n2026-11-04 09:00,1,2,0.5,1.5\n2026-11-04 13:15,1,2,0.5,1.5\n", encoding="utf-8")
    (tmp_path / "amt.csv").write_text("date,slot,amt\n2026-11-04,09:00,10\n2026-11-04,09:05,20\n2026-11-04,09:10,30\n2026-11-04,09:15,99\n"
                                      "2026-11-04,13:15,1\n2026-11-04,13:20,2\n2026-11-04,13:25,4\n", encoding="utf-8")
    D = R.load15(str(tmp_path), str(tmp_path / "amt.csv"))
    assert D["v"] == [60.0, 7.0] and D["has_vol"] and D["dates"] == ["2026-11-04", "2026-11-04"]
