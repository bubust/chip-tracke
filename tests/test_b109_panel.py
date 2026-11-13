"""B109 AI 圓桌「都沒回應」（用戶 11/13）：提示太長（1.6 萬字，她的數法那一行就 5,000 多字）→ Groq 免費額度吃不下、Gemini 也常失敗
- 她的數法那一行改成只給結論卡（位階、波形、怎麼做），最多 1,800 字；另外準備約 2,000 字以內的精簡版給每分鐘額度小的 AI
- 被限流：照對方說的秒數等一下再試；太大／逾時：換精簡版；沒回應的原因帶到畫面；沒回應的那次不扣手動次數
python -m pytest tests/test_b109_panel.py -q（不連網）"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stock_wave as W  # noqa: E402
import test_b101_neck as T  # noqa: E402
from test_b74_wave import _snap, wave_db  # noqa: E402, F401
from wave import panel as P  # noqa: E402


class R:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


OK = R(200, {"choices": [{"message": {"content": '{"stance": "盤整"}'}}], "usage": {"total_tokens": 7}})
PV = {"id": "z", "kind": "openai", "base": "x", "key": "k", "models": ["m1"]}


def _nest():
    sm = T.SMALL + [{"p": 41873, "t": "L"}, {"p": 44911, "t": "H"}, {"p": 42371, "t": "L"}]
    t = W.structure(T.BIG, sm, 43990.0, 43364.0, 43818.0, T.LB, first_leg=T.FIRST, full=17015.0)
    t["card"] = W.plan_card(t, 43990.0)
    return {"ok": True, "anchor": {"p": 37694.0}, "extreme": {"p": 44911.0}, "primary": {"path": "C-4-b", "text": "x → b 段（反彈） 進行中"},
            "alternate": None, "gates": [{"k": "轉強", "ok": False, "t": "站上 44,034", "price": 44034.0}], "plan": [], "tiers": t}


def test_nest_line_is_compact_card_only():
    line = P._nest_line({"nest": {"60m": _nest()}})
    assert len(line) <= 1800 and "她的數法（現在位階）" in line and "5-2 回檔" in line and "做多等大買點" in line
    assert "另一種數法（她 11/6）" not in line and "三條路徑共用的短線考驗" not in line          # 舊的整段拆法不再貼進來
    assert len(P._nest_line({"nest": {"60m": _nest()}}, brief=True)) <= 800


EMPTY = {"short": {"support": [], "resistance": []}, "swing": {"support": [], "resistance": []}}
TX = lambda: {"ok": True, "price": 43990.0, "chg_pct": 1.9, "levels": EMPTY, "nest": {"60m": _nest()}}   # noqa: E731


def test_facts_sizes():
    snap = {**_snap(), "tx": TX()}
    fx, fs = P.facts(snap, None), P.facts_small(snap, None)
    assert len(fs) < 2500 and len(fs) < len(fx) and "照 @fanny55520 的拆法" in fs and "40,451～40,715" in fs


def test_ask_waits_then_retries_on_rate_limit(wave_db):  # noqa: F811
    seq = [R(429, {"error": {"message": "Rate limit reached. Please try again in 12.5s."}}), OK]
    slept = []
    a = P.ask(PV, "hi", post=lambda *a, **k: seq.pop(0), sleep=slept.append)
    assert a["json"] == {"stance": "盤整"} and slept == [13.5]


def test_ask_too_big_switches_to_small_prompt(wave_db):  # noqa: F811
    sent = []

    def post(url, headers=None, json=None, timeout=None):
        sent.append(json["messages"][0]["content"])
        return R(413, {"error": {"message": "Request too large on tokens per minute (TPM): Limit 8000, Requested 15000"}}) if len(sent) == 1 else OK
    a = P.ask(PV, "完整版", post=post, alt="精簡版", sleep=lambda s: None)
    assert sent == ["完整版", "精簡版"] and a["small"] is True
    with pytest.raises(RuntimeError) as e:                             # 沒有精簡版、等太久（> 30 秒）也不等
        P.ask(PV, "hi", post=lambda *a, **k: R(429, {"error": {"message": "quota. Please retry in 1m2s"}}), sleep=lambda s: pytest.fail("不該等"))
    assert "429" in str(e.value)


def test_error_text_hides_keys():
    assert "AIza" not in P._clean("https://x/y?key=AIzaSyABC-123 Bearer gsk_abc.DEF") and "gsk_" not in P._clean("Bearer gsk_abc.DEF")


def test_failed_run_shows_reason_and_keeps_manual_quota(wave_db, monkeypatch):  # noqa: F811
    ps = [{"id": "a", "name": "A", "kind": "openai", "base": "x", "key": "k", "models": ["ma"]}]
    monkeypatch.setattr(P, "providers", lambda: ps)
    ok = lambda p, prompt, post=None, alt=None: {"model": "ma", "json": {"stance": "盤整", "summary": "s"}, "tokens": 5}   # noqa: E731

    def bad(p, prompt, post=None, alt=None):
        raise RuntimeError("ma: 429 quota exceeded key=SECRET123")
    monkeypatch.setattr(P, "ask", ok)
    P.run(_snap(), "manual", news_fn=lambda post=None: {"items": []})
    assert P.manual_left() == P.MANUAL_LIMIT - 1
    monkeypatch.setattr(P, "ask", bad)
    r = P.run(_snap(), "manual", news_fn=lambda post=None: {"items": []})
    assert r["mode"] == "none" and P.manual_left() == P.MANUAL_LIMIT - 1                # 沒回應的那次不扣
    lt = P.latest()
    assert lt["result"]["mode"] == "single" and "AI 都沒回應" in lt["note"]
    assert lt["fail"]["errors"][0]["name"] == "A" and "429" in lt["fail"]["errors"][0]["error"] and "SECRET123" not in json.dumps(lt["fail"])
    assert r["prompt_chars"]["small"] <= r["prompt_chars"]["full"]


def test_groq_uses_small_prompt_directly(wave_db, monkeypatch):  # noqa: F811
    ps = [{"id": "g", "name": "G", "kind": "openai", "base": "x", "key": "k", "models": ["mg"], "small": True},
          {"id": "h", "name": "H", "kind": "openai", "base": "x", "key": "k", "models": ["mh"]}]
    monkeypatch.setattr(P, "providers", lambda: ps)
    seen = {}

    def fake(p, prompt, post=None, alt=None):
        seen.setdefault(p["id"], []).append((len(prompt), [len(x) for x in alt or []]))
        return {"model": p["models"][0], "json": {"stance": "盤整", "summary": "s"}, "tokens": 5}
    monkeypatch.setattr(P, "ask", fake)
    r = P.run({**_snap(), "tx": TX()}, "auto", news_fn=lambda post=None: {"items": []})
    g, h = seen["g"][0], seen["h"][0]
    assert len(g[1]) == 1 and len(h[1]) == 2                           # Groq：精簡版＋最短版；其他：完整版＋精簡版＋最短版
    assert g[0] == h[1][0] and g[0] < h[0] and g[1][0] < g[0]          # Groq 第一份就是精簡版；最短版更短
    assert r["mode"] == "roundtable" and set(r["round2"]) == {"g", "h"} and [x["round"] for x in r["log"]].count(1) == 2
    assert r["prompt_chars"]["tiny"] < r["prompt_chars"]["small"] < r["prompt_chars"]["full"]


def test_timeout_model_is_skipped_next_time(wave_db, monkeypatch):  # noqa: F811
    """正式站 11/13：gemini-3.6-flash 一直逾時，每一輪都重等 → 逾時過的模型 30 分鐘內排最後，後面直接用精簡版"""
    P._slow.clear(), P._good.clear()
    pv = {"id": "z", "kind": "openai", "base": "x", "key": "k", "models": ["slow", "fast"]}
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append((json["model"], json["messages"][0]["content"]))
        if json["model"] == "slow":
            raise TimeoutError("The read operation timed out")
        return OK
    a = P.ask(pv, "完整版", post=post, alt="精簡版", sleep=lambda s: None)
    assert calls == [("slow", "完整版"), ("fast", "精簡版")] and a["model"] == "fast" and a["small"] and "timed out" in a["errors"][0]
    calls.clear()
    P.ask(pv, "完整版", post=post, alt="精簡版", sleep=lambda s: None)
    assert calls == [("fast", "完整版")]                               # 第二次：逾時過的排最後，先問快的
    P._slow.clear()


def test_alt_list_small_then_tiny(wave_db):  # noqa: F811
    """Qwen3 連精簡版都被說太大（正式站 11/13 14:08）→ 再換最短版"""
    sent = []

    def post(url, headers=None, json=None, timeout=None):
        sent.append(json["messages"][0]["content"])
        return OK if len(sent) == 3 else R(429, {"error": {"message": "Request too large for model on tokens per minute (TPM): Limit 6000, Requested 7000"}})
    a = P.ask(PV, "完整版", post=post, alt=["精簡版", "最短版"], sleep=lambda s: None)
    assert sent == ["完整版", "精簡版", "最短版"] and a["small"]


def test_output_limit_lowers_max_tokens(wave_db):  # noqa: F811
    """正式站 11/13 14:18 Qwen3：「output tokens per minute (OTPM): Limit 1000, Requested 1400 … reduce max_tokens」→ 照上限調低再試"""
    asked = []

    def post(url, headers=None, json=None, timeout=None):
        asked.append(json["max_tokens"])
        if json["max_tokens"] > 1000:
            return R(429, {"error": {"message": "Request too large for model `q` on output tokens per minute (OTPM): Limit 1000, Requested 1400. "
                                                "The request's expected output tokens exceed the enforced limit; reduce max_tokens"}})
        return OK
    a = P.ask(PV, "hi", post=post, sleep=lambda s: pytest.fail("不用等"))
    assert asked == [1400, 900] and a["json"] == {"stance": "盤整"}
    asked.clear()
    P.ask({**PV, "max_tokens": 900}, "hi", post=post, sleep=lambda s: None)
    assert asked == [900]                                              # Qwen3 的設定直接用 900
    q = next(x for x in P.providers() if x["id"] == "qwen") if os.environ.get("GROQ_API_KEY") else {"max_tokens": 900}
    assert q["max_tokens"] <= 900


def test_busy_server_waits_twice_before_downgrading(wave_db):  # noqa: F811
    seq = [R(503, {"error": {"message": "This model is currently experiencing high demand."}})] * 2 + [OK]
    slept, sent = [], []

    def post(url, headers=None, json=None, timeout=None):
        sent.append(json["messages"][0]["content"])
        return seq.pop(0)
    a = P.ask(PV, "完整版", post=post, alt=["精簡版"], sleep=slept.append)
    assert sent == ["完整版"] * 3 and slept == [9.0, 17.0] and not a["small"]      # 伺服器忙：等兩次都還是用完整版


def test_quota_exhausted_model_is_skipped_and_remembered(wave_db):  # noqa: F811
    """正式站 11/13 14:28：gemini-3.6-flash「You exceeded your current quota」，卻在它身上完整版、精簡版、最短版各試兩次（白等 1 分多鐘）
    → 額度用完直接換模型、不等；記住（存資料庫，重啟也記得），下一輪先問上次成功的模型"""
    P._slow.clear(), P._good.clear()
    P._state["loaded"] = P._today()
    pv = {"id": "gm", "kind": "openai", "base": "x", "key": "k", "models": ["m36", "m25"]}
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append((json["model"], json["messages"][0]["content"]))
        if json["model"] == "m36":
            return R(429, {"error": {"message": "You exceeded your current quota, please check your plan and billing details."}})
        return OK
    a = P.ask(pv, "完整版", post=post, alt=["精簡版", "最短版"], sleep=lambda s: pytest.fail("額度用完不該等"))
    assert calls == [("m36", "完整版"), ("m25", "完整版")] and a["model"] == "m25" and not a["small"]
    calls.clear()
    P._slow.clear(), P._good.clear()
    P._state["loaded"] = None                                          # 模擬伺服器重啟：從資料庫讀回來
    P.ask(pv, "完整版", post=post, alt=["精簡版"], sleep=lambda s: None)
    assert calls == [("m25", "完整版")] and P._good == {"gm": "m25"} and "m36" in P._slow
    # 每分鐘額度（說了幾秒後再試、等得起）不算用完：等一下再試同一個模型
    assert not P._quota_out("429 You exceeded your current quota retry in 12.5s") and P._quota_out("429 You exceeded your current quota retry in 300s")
    assert P._quota_out("429 quota（每日額度用完）") and not P._quota_out("429 Rate limit reached. Please try again in 5s")
    P._slow.clear(), P._good.clear()


def test_gemini_error_keeps_retry_hint_and_daily_flag():
    long = "You exceeded your current quota. " + "x" * 400 + " Please retry in 23.4s."
    body = {"error": {"message": long, "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}
    with pytest.raises(RuntimeError) as e:
        P.call_gemini("m", "hi", post=lambda *a, **k: R(429, body))
    assert "retry in 23.4s" in str(e.value) and "每日額度用完" in str(e.value) and len(str(e.value)) < 260
