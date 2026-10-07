"""戰略討論區：AI 給的股票一律拿 stocks.csv 對過（python -m pytest tests/test_discuss.py -q）"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from discuss import router
from discuss.ai import _extract_json


def _result():
    return {
        "mentions": [
            {"text": "全新", "stock_id": "2455", "name": "全新光電", "confidence": "high"},        # 全名 vs 簡稱
            {"text": "穩懋", "stock_id": "3150", "name": "穩懋", "confidence": "high"},            # 代號打錯（3150 是鈺寶）
            {"text": "8086", "stock_id": "", "name": "", "confidence": "medium"},                # 只寫代號
            {"text": "黑科技", "stock_id": "1234", "name": "黑科技光電", "confidence": "high"},     # 代號存在（黑松）但名稱對不上
            {"text": "新棒", "stock_id": "9999", "name": "新棒科技", "confidence": "medium",
             "candidates": [{"stock_id": "4979", "name": "華星光"}, {"stock_id": "0000", "name": "亂掰"}]},
        ],
        "themes": [{"name": "CPO", "chain": [{"segment": "上游", "stocks": [
            {"stock_id": "2455", "name": "全新"}, {"stock_id": "1234", "name": "不存在光電"}]}]}],
        "related": [{"stock_id": "4979", "name": "華星光", "why": "x"}, {"stock_id": "8888", "name": "幻想科技"}],
        "leader_follower": [{"leaders": ["2455", "3105", "9999"], "followers": ["8086"]}],
    }


def test_resolve_validates_codes():
    r = router.resolve(_result(), {})
    m = {x["text"]: x for x in r["mentions"]}
    assert (m["全新"]["stock_id"], m["全新"]["name"], m["全新"]["status"]) == ("2455", "全新", "ok")
    assert m["穩懋"]["stock_id"] == "3105" and m["穩懋"]["confidence"] == "medium"     # 相信名稱、降一級
    assert m["8086"]["stock_id"] == "8086" and m["8086"]["name"] == "宏捷科"
    assert m["黑科技"]["stock_id"] == "1234" and m["黑科技"]["status"] == "unsure"         # 讓使用者確認
    assert m["新棒"]["stock_id"] == "" and m["新棒"]["status"] == "unknown"
    assert m["新棒"]["candidates"] == [{"stock_id": "4979", "name": "華星光"}]          # 不存在的候選拿掉
    assert [s["stock_id"] for s in r["themes"][0]["chain"][0]["stocks"]] == ["2455"]
    assert [s["stock_id"] for s in r["related"]] == ["4979"]
    assert r["leader_follower"][0]["leaders"] == ["2455", "3105"]
    assert set(r["dropped"]) == {"不存在光電 1234", "幻想科技 8888"}


def test_alias_overrides_ai():
    r = router.resolve(_result(), {"新棒": {"stock_id": "4979", "name": "華星光"}})
    m = {x["text"]: x for x in r["mentions"]}
    assert (m["新棒"]["stock_id"], m["新棒"]["confidence"], m["新棒"]["status"]) == ("4979", "confirmed", "ok")


def test_session_stocks_roles(monkeypatch):
    monkeypatch.setattr(router, "_price_on", lambda sids, d: {s: (100.0, "20261006") for s in sids})
    r = router.resolve(_result(), {})
    rows = {s["stock_id"]: s for s in router.session_stocks(r, "2026-10-07")}
    assert rows["2455"]["kind"] == "mentioned" and rows["2455"]["role"] == "leader"
    assert rows["8086"]["role"] == "follower" and rows["8086"]["mention_text"] == "8086"
    assert rows["4979"]["kind"] == "related" and rows["4979"]["price_at"] == 100.0
    assert "9999" not in rows


def test_extract_json_tolerates_fence_and_trailing_comma():
    assert _extract_json('說明\n```json\n{"a": [1, 2,], "b": {"c": 1,},}\n```') == {"a": [1, 2], "b": {"c": 1}}
