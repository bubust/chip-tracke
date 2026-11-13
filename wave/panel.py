"""B74 🤖 AI 圓桌（PLAN-B74 §6）：多個 AI 看同一份系統資料，各自寫看法 → 互相看、回應 → 主持人整理。
- 參加者（有金鑰才參加）：Gemini（GEMINI_PANEL_MODEL，預設 gemini-3.6-flash → flash-latest；不用 2.5-flash，留給個股 AI 解盤）、
  GPT-OSS-120B 與 Qwen3（Groq，GROQ_API_KEY）；選配 OPENAI_API_KEY＋OPENAI_PANEL_MODEL、XAI_API_KEY＋XAI_PANEL_MODEL、
  ANTHROPIC_API_KEY（＋ANTHROPIC_PANEL_MODEL）
- 新聞：Gemini 2.5-flash＋Google 搜尋，近 7 天，只留有來源網址的；12 小時快取；失敗＝沒有新聞照跑
- 每位各自 try/except（含 429、413、逾時 60 秒），單次圓桌內不重試；每模型每天 tokens 上限 PANEL_DAILY_TOKENS（預設 60,000）
- 價位檢查：文字裡 30,000～80,000 的數字離系統價位都超過 0.3% → 標「⚠ 非系統價位」"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Optional

import httpx

from . import data as D

log = logging.getLogger(__name__)
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_BASE = "https://api.groq.com/openai/v1"
TIMEOUT = 45                 # 一次呼叫最多等幾秒（正常 2～25 秒；等不到就換下一個模型）
NEWS_TIMEOUT = 90
MANUAL_LIMIT = 8
MANUAL_TRIES = 12            # 一天最多按幾次（沒回應的不算在手動次數裡，但總共不超過 12 次）
MAX_WAIT = 45                # 被限流時最多等幾秒再試
ROUND2_BUDGET = 200          # 第一輪花超過這麼多秒，第二輪就跳過
NEWS_TTL = 12 * 3600
DISCLAIMER = "劇本＝規則數浪＋歷史條件推估，不是投資建議；AI 看法不是系統計算"
_jobs: dict = {}
_lock = threading.Lock()


def daily_cap() -> int:
    try:
        return int(os.environ.get("PANEL_DAILY_TOKENS", "300000"))
    except ValueError:
        return 300000


def gemini_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def providers() -> list:
    out = []
    if gemini_key():
        first = os.environ.get("GEMINI_PANEL_MODEL") or "gemini-3.6-flash"
        out.append({"id": "gemini", "name": "Gemini（Google）", "kind": "gemini",
                    "models": [first] + [m for m in ("gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash") if m != first]})
    gk = (os.environ.get("GROQ_API_KEY") or "").strip()
    if gk:
        out.append({"id": "gptoss", "name": "GPT-OSS-120B（OpenAI 開源模型，Groq）", "kind": "openai", "base": GROQ_BASE,
                    "key": gk, "models": ["openai/gpt-oss-120b"], "extra": {"reasoning_effort": "low"}, "small": True})
        out.append({"id": "qwen", "name": "Qwen3（阿里巴巴，Groq）", "kind": "openai", "base": GROQ_BASE,
                    "key": gk, "models": ["qwen/qwen3.8-27b"], "extra": {"reasoning_format": "hidden"}, "small": True,
                    "max_tokens": 900})                                # Groq 免費額度：這個模型每分鐘最多輸出 1,000 token（要求 1,400 會被拒絕）
    for env, base, pid, name in (("OPENAI", "https://api.openai.com/v1", "openai", "GPT（OpenAI）"),
                                 ("XAI", "https://api.x.ai/v1", "grok", "Grok（xAI）")):
        k, m = (os.environ.get(f"{env}_API_KEY") or "").strip(), (os.environ.get(f"{env}_PANEL_MODEL") or "").strip()
        if k and m:
            out.append({"id": pid, "name": name, "kind": "openai", "base": base, "key": k, "models": [m], "extra": {}})
    ak = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if ak:
        out.append({"id": "claude", "name": "Claude（Anthropic）", "kind": "anthropic", "key": ak,
                    "models": [os.environ.get("ANTHROPIC_PANEL_MODEL") or "claude-sonnet-5-5"]})
    return out


# ── 用量 ─────────────────────────────────────────────────────────────────────
def _today() -> str:
    return D.tw_now().strftime("%Y-%m-%d")


def used_today(model: str) -> int:
    try:
        with D.db() as c:
            r = c.execute("SELECT tokens FROM ai_usage WHERE day=? AND model=?", (_today(), model)).fetchone()
        return int(r["tokens"]) if r else 0
    except Exception:     # noqa: BLE001
        return 0


def add_usage(model: str, tokens: int):
    if not tokens:
        return
    with D.db() as c:
        c.execute("INSERT INTO ai_usage(day,model,tokens) VALUES(?,?,?) ON CONFLICT(day,model) DO UPDATE SET tokens=tokens+excluded.tokens",
                  (_today(), model, int(tokens)))


def usage_today() -> dict:
    with D.db() as c:
        return {r["model"]: r["tokens"] for r in c.execute("SELECT model,tokens FROM ai_usage WHERE day=?", (_today(),)).fetchall()}


# ── 呼叫 ─────────────────────────────────────────────────────────────────────
def extract_json(txt: str) -> dict:
    t = (txt or "").strip()
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            return json.loads(t[a:b + 1])
        raise


def call_gemini(model: str, prompt: str, search: bool = False, json_mode: bool = True, post=None, timeout: Optional[float] = None) -> dict:
    post = post or httpx.post
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}}
    if search:
        body["tools"] = [{"google_search": {}}]
    elif json_mode:
        body["generationConfig"]["response_mime_type"] = "application/json"
    r = post(GEMINI_API.format(model=model), params={"key": gemini_key()}, json=body, timeout=timeout or TIMEOUT)
    d = r.json()
    if r.status_code != 200 or "error" in d:
        err = d.get("error") or {}
        msg = str(err.get("message", ""))
        m = re.search(r"retry in ([\d.]+)s", msg, re.I)              # 訊息很長，「幾秒後再試」在最後面：先抓出來再截短
        daily = any(re.search(r"per ?day", str(v.get("quotaId", "")), re.I)
                    for x in err.get("details") or [] if isinstance(x, dict) for v in x.get("violations") or [])
        raise RuntimeError(f"{r.status_code} {msg[:200]}" + (f" retry in {m.group(1)}s" if m else "") + ("（每日額度用完）" if daily else ""))
    cand = (d.get("candidates") or [{}])[0]
    txt = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    if not txt.strip():
        raise RuntimeError(f"空白回應（{cand.get('finishReason')}）")
    return {"text": txt, "tokens": int((d.get("usageMetadata") or {}).get("totalTokenCount") or 0),
            "grounding": cand.get("groundingMetadata") or {}}


def call_openai(p: dict, model: str, prompt: str, post=None) -> dict:
    post = post or httpx.post
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": int(p.get("max_tokens") or 1400),
            "response_format": {"type": "json_object"}, **(p.get("extra") or {})}
    r = post(f"{p['base']}/chat/completions", headers={"Authorization": f"Bearer {p['key']}"}, json=body, timeout=TIMEOUT)
    d = r.json()
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {str((d.get('error') or {}).get('message', ''))[:300]}")
    return {"text": d["choices"][0]["message"]["content"] or "", "tokens": int((d.get("usage") or {}).get("total_tokens") or 0)}


def call_anthropic(p: dict, model: str, prompt: str, post=None) -> dict:
    post = post or httpx.post
    r = post("https://api.anthropic.com/v1/messages",
             headers={"x-api-key": p["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
             json={"model": model, "max_tokens": 1400, "messages": [{"role": "user", "content": prompt + "\n只回 JSON。"}]},
             timeout=TIMEOUT)
    d = r.json()
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {str((d.get('error') or {}).get('message', ''))[:300]}")
    u = d.get("usage") or {}
    return {"text": "".join(b.get("text", "") for b in d.get("content") or [] if b.get("type") == "text"),
            "tokens": int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0))}


def _clean(msg) -> str:
    """錯誤訊息裡不要留金鑰（網址的 key=、Bearer）"""
    return re.sub(r"(key=|Bearer\s+)[\w\-.]+", r"\1***", str(msg))


def _wait_hint(msg: str) -> Optional[float]:
    """限流／伺服器忙的錯誤訊息 → 建議等幾秒（Groq「try again in 12.3s」「in 1m2.5s」、Gemini「retry in 23s」）；不是這類錯誤回 None"""
    if not re.search(r"\b(429|500|502|503|529)\b|rate limit|overloaded|unavailable|try again|retry in", msg, re.I):
        return None
    m = re.search(r"(?:try again|retry) in\s*(?:(\d+)m)?\s*([\d.]+)\s*s", msg, re.I)
    if m:
        return float(m.group(1) or 0) * 60 + float(m.group(2))
    return 8.0


def _out_limit(msg: str) -> Optional[int]:
    """「每分鐘輸出上限 Limit 1000, Requested 1400；reduce max_tokens」→ 1000；不是這種錯誤回 None"""
    m = re.search(r"output tokens per minute.*?Limit\s*(\d+),\s*Requested\s*(\d+)", msg, re.I | re.S)
    return int(m.group(1)) if m and int(m.group(2)) > int(m.group(1)) else None


def _too_big(msg: str) -> bool:
    return bool(re.search(r"\b413\b|too large|tokens per minute|\bTPM\b|context length|maximum context|reduce the length", msg, re.I))


_slow: dict = {}             # 模型 → 到什麼時候之前先不用（剛逾時過、或額度用完）
_good: dict = {}             # 哪一位 → 上次成功的模型（下次先問它）
_state = {"loaded": None}    # 這兩個表是哪一天從資料庫讀的
SLOW_TTL = 6 * 3600


def _load_state():
    """模型狀態存在 wave_snapshot（kind＝panel_models，一天一筆）：伺服器重啟也記得，隔天額度恢復就重來"""
    day = _today()
    if _state["loaded"] == day:
        return
    _state["loaded"] = day
    _slow.clear()
    _good.clear()
    try:
        with D.db() as c:
            r = c.execute("SELECT json FROM wave_snapshot WHERE day=? AND kind='panel_models'", (day,)).fetchone()
        if r:
            j = json.loads(r["json"])
            _slow.update({k: float(v) for k, v in (j.get("slow") or {}).items()})
            _good.update(j.get("good") or {})
    except Exception:     # noqa: BLE001
        pass


def _save_state():
    try:
        with D.db() as c:
            c.execute("INSERT INTO wave_snapshot(day,kind,created_at,json) VALUES(?,?,?,?) ON CONFLICT(day,kind) DO UPDATE SET "
                      "created_at=excluded.created_at, json=excluded.json",
                      (_today(), "panel_models", time.strftime("%Y-%m-%d %H:%M:%S"), json.dumps({"slow": _slow, "good": _good}, ensure_ascii=False)))
    except Exception:     # noqa: BLE001
        pass


def _is_timeout(msg: str) -> bool:
    return bool(re.search(r"timed out|timeout", msg, re.I))


def _quota_out(msg: str) -> bool:
    """這個模型的額度用完了（Gemini「You exceeded your current quota」）：換精簡版也沒用，要換模型。
    訊息有說幾秒後再試、而且等得起（每分鐘額度）就不算"""
    if "每日額度用完" in msg:
        return True
    if not re.search(r"exceeded your current quota|quota exceeded|RESOURCE_EXHAUSTED", msg, re.I):
        return False
    m = re.search(r"(?:try again|retry) in\s*(?:(\d+)m)?\s*([\d.]+)\s*s", msg, re.I)
    return not (m and float(m.group(1) or 0) * 60 + float(m.group(2)) <= MAX_WAIT)


def ask(p: dict, prompt: str, post=None, alt: Optional[str] = None, sleep=time.sleep) -> dict:
    """一位 AI 回答一次（JSON）。超過今日上限 → 丟 OverflowError。同一位的模型逐一試；
    B109：被限流／伺服器忙 → 照對方說的秒數等一下（最多 30 秒）再試一次；請求太大（413、每分鐘字數額度）→ 改用精簡版資料 alt 再試；
    逾時 → 這個模型 6 小時內排到最後（不要每一輪都重等一次），後面的模型直接用精簡版"""
    errors = []
    small = False                                                     # 逾時過一次以後，後面都用精簡版
    now = time.time()
    _load_state()
    for model in sorted(p["models"], key=lambda m: (_slow.get(m, 0) > now, m != _good.get(p["id"]))):   # 不能用的排最後、上次成功的排最前
        if used_today(model) >= daily_cap():
            errors.append(f"{model} 今日額度已達上限")
            continue
        alts = [(t, "（精簡版）" if k == 0 else "（最短版）") for k, t in enumerate([alt] if isinstance(alt, str) else list(alt or []))]
        variants = alts if alts and small else [(prompt, "")] + alts
        vi, waited = 0, 0
        while vi < len(variants):
            text, tag = variants[vi]
            try:
                if p["kind"] == "gemini":
                    out = call_gemini(model, text, post=post)
                elif p["kind"] == "anthropic":
                    out = call_anthropic(p, model, text, post=post)
                else:
                    out = call_openai(p, model, text, post=post)
                add_usage(model, out.get("tokens", 0))
                ans = {"model": model, "json": extract_json(out["text"]), "tokens": out.get("tokens", 0), "small": bool(tag), "errors": errors}
                if p.get("id") and _good.get(p["id"]) != model:
                    _good[p["id"]] = model
                    _save_state()
                return ans
            except Exception as e:     # noqa: BLE001  429／413／逾時／JSON 壞掉
                msg = _clean(e)[:300] or type(e).__name__
                errors.append(f"{model}{tag}: {msg}")
                w = _wait_hint(msg)
                lim = _out_limit(msg)
                if lim and int(p.get("max_tokens") or 1400) > lim * 0.9:
                    p = {**p, "max_tokens": int(lim * 0.9)}            # 輸出上限比我們要求的小 → 照它的上限調低，同一份再試
                    continue
                if _is_timeout(msg):
                    _slow[model] = time.time() + SLOW_TTL
                    _save_state()
                    small = True
                    break                                              # 逾時：不在同一個模型上再等，換下一個
                if _quota_out(msg):
                    _slow[model] = time.time() + SLOW_TTL
                    _save_state()
                    break                                              # 這個模型的額度用完：換精簡版也沒用，直接換模型
                if _too_big(msg) and vi + 1 < len(variants):
                    vi, waited = vi + 1, 0                             # 太大 → 直接換精簡版
                elif w is not None and waited < (2 if re.search(r"\b50[0-9]\b|529|overload|unavailable|high demand", msg, re.I) else 1) and w <= MAX_WAIT:
                    waited += 1
                    sleep(w * waited + 1)                              # 等一下，同一份再試（伺服器忙最多等兩次：9 秒、17 秒）
                else:
                    vi, waited = vi + 1, 0
    if errors and all("額度已達上限" in x for x in errors):
        raise OverflowError("；".join(errors))
    raise RuntimeError("；".join(errors) or "沒有可用模型")


# ── 新聞 ─────────────────────────────────────────────────────────────────────
NEWS_PROMPT = """用 Google 搜尋台股大盤（加權指數）最近 7 天最重要的消息（台股、台積電與權值股、美股科技股、聯準會、匯率、地緣政治），
挑 6～8 則真的會影響大盤的。只回 JSON：{{"items":[{{"date":"YYYY-MM-DD","title":"一句話標題","why":"為什麼影響大盤（≤40 字）"}}]}}
今天是 {today}。不要編造；找不到就少給。"""


def news(post=None, force: bool = False) -> dict:
    day = _today()
    if not force:
        try:
            with D.db() as c:
                r = c.execute("SELECT created_at, json FROM wave_snapshot WHERE day=? AND kind='news'", (day,)).fetchone()
            if r and time.time() - time.mktime(time.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S")) < NEWS_TTL:
                return json.loads(r["json"])
        except Exception:     # noqa: BLE001
            pass
    out = {"items": [], "sources": [], "searched": False}
    if not gemini_key():
        return out
    for model in ("gemini-2.5-flash", "gemini-flash-latest"):
        if used_today(model) >= daily_cap():
            continue
        try:
            r = call_gemini(model, NEWS_PROMPT.format(today=day), search=True, json_mode=False, post=post, timeout=NEWS_TIMEOUT)
            add_usage(model, r.get("tokens", 0))
            gm = r.get("grounding") or {}
            srcs = []
            for ch in gm.get("groundingChunks") or []:
                w = (ch or {}).get("web") or {}
                if w.get("uri"):
                    srcs.append({"title": w.get("title") or "", "uri": w["uri"]})
            try:
                items = (extract_json(r["text"]) or {}).get("items") or []
            except Exception:     # noqa: BLE001
                items = []
            if not srcs:          # 沒有搜尋來源＝不採用（避免 AI 自己編）
                items = []
            out = {"items": [x for x in items if isinstance(x, dict) and x.get("title")][:8], "sources": srcs[:10],
                   "searched": bool(srcs), "model": model}
            break
        except Exception as e:     # noqa: BLE001
            log.warning(f"[panel] 新聞 {model}：{str(e)[:120]}")
    try:
        with D.db() as c:
            c.execute("INSERT INTO wave_snapshot(day,kind,created_at,json) VALUES(?,?,?,?) ON CONFLICT(day,kind) DO UPDATE SET "
                      "created_at=excluded.created_at, json=excluded.json",
                      (day, "news", time.strftime("%Y-%m-%d %H:%M:%S"), json.dumps(out, ensure_ascii=False)))
    except Exception:     # noqa: BLE001
        pass
    return out


# ── 系統資料 → 文字 ──────────────────────────────────────────────────────────
def _z(z):
    h = z.get("hold") or {}
    hr = f"，歷史守住 {h['rate'] * 100:.0f}%（隨機價位 {h['placebo'] * 100:.0f}%，{'✅' if h.get('pass') else '△ 沒比隨機好'}）" if h.get("rate") is not None and h.get("placebo") is not None else ""
    return f"{z['price']:,.0f}（{z['type_name']}：{'、'.join(s['label'] for s in z['sources'][:3])}{hr}）"


def facts(snap: dict, nw: Optional[dict] = None) -> str:
    L = [f"資料日期 {snap['asof']['date']}；加權 {snap['price']:,.0f}（{snap.get('chg_pct')}%）；ATR14 約 {snap.get('atr')} 點"]
    L += ["【規則數浪（系統）】"] + [f"- {x}" for x in snap["scenario"]["lines"][:-1]]
    for k, nm in (("short", "短線"), ("swing", "波段")):
        lv = snap["levels"][k]
        L.append(f"【{nm}支撐】" + "；".join(_z(z) for z in lv["support"]) if lv["support"] else f"【{nm}支撐】無")
        L.append(f"【{nm}壓力】" + "；".join(_z(z) for z in lv["resistance"]) if lv["resistance"] else f"【{nm}壓力】無")
    ch = snap.get("chips") or {}
    if ch.get("ok"):
        L.append(f"【籌碼 {ch['date']}】外資今天 {ch['f_net']} 億、5 日 {ch['f5']} 億、連{'買' if ch['f_streak'] > 0 else '賣'} {abs(ch['f_streak'])} 天；"
                 f"投信 5 日 {ch['t5']} 億；外資台指期淨未平倉 {ch['fut_f_oi']} 口（5 日變化 {ch['fut_chg5']}）；融資 20 日變化 {ch['margin_chg20']}"
                 "（研究：這些對之後 5／20 天大盤都沒有預測力 △）")
    g = snap.get("global") or {}
    L.append("【國際】" + "；".join(f"{i['name']} {i['date']} 收 {i['close']}（1 日 {i['chg1']}%、20 日 {i['chg20']}%、{'60 日線上' if i['above_ma60'] else '60 日線下'}、與加權相關 {i['corr60']}）"
                                   for i in g.get("items", []) if i.get("ok")))
    so = g.get("sox_overnight")
    if so:
        L.append(f"【前一晚費半 → 加權】費半 {so['date']} {so['sox_ret']}% → 歷史平均加權隔天 {so['tw_expect']}%（±{so['sd']}%；樣本外 R² {so['oos_r2']}，這是唯一回測有效的國際關係 ✅）")
    if g.get("sox_wave"):
        sw = g["sox_wave"]
        L.append(f"【費半數浪】{sw['text']}；支撐 {sw['support']}、壓力 {sw['resistance']}")
    fc = snap.get("forecast") or {}
    for hz in ("h5", "h20", "h60"):
        x = fc.get(hz)
        if x:
            L.append(f"【歷史分布 {hz[1:]} 天】上漲 {x['p_up'] * 100:.0f}%、八成落在 {x['lo_px']:,.0f}～{x['hi_px']:,.0f}（全部歷史，不是預測）")
    ctx = snap.get("context") or {}
    if ctx.get("box"):
        L.append(f"【格局】{ctx['box']}；月線斜率 {((ctx.get('mslope') or {}).get('slope'))}%（{(ctx.get('mslope') or {}).get('tier')}）")
    if ctx.get("crash"):
        L.append(f"【大跌買點研究】比 60 日高點 {ctx['crash']['dd'] * 100:.1f}%；深跌訊號：{ctx['crash']['deep'] or '無'}")
    L += facts_b75(snap)
    L.append("【研究結論】" + "；".join((snap.get("research") or {}).get("summary") or []))
    if nw and nw.get("items"):
        L.append("【近 7 天新聞（Google 搜尋）】" + "；".join(f"{x.get('date', '')} {x['title']}（{x.get('why', '')}）" for x in nw["items"]))
    return "\n".join(L)


def _key(k: Optional[dict], nm: str) -> str:
    if not k:
        return f"{nm}：沒有"
    s = f"{nm}{k['kind']} {k['price']:,.0f}（{'跌破' if k['side'] == 'below' else '站上'}＝這一段可能結束；離現價 {k.get('dist_pct')}%"
    if k.get("broken"):
        s += "；現在已經" + ("跌破" if k["side"] == "below" else "站上")
    if k.get("wave_invalid") is not None:
        s += f"；波浪規則最後防線 {k['wave_invalid']:,.0f}"
    return s + "；回測跟隨便畫線差不多 △）"


def facts_b75(snap: dict) -> list:
    """B75：轉折點、超短線（60 分 K）、夜盤→開盤、台指期、綜合研判、散戶小台／外資選擇權、融資增減"""
    L = []
    ky = snap.get("key") or {}
    L.append("【轉折點（加權）】" + "；".join(_key(ky.get(m), nm) for m, nm in (("m30", "30 分 K"), ("ultra", "60 分 K"), ("short", "日 K"), ("swing", "週 K"))))
    if snap.get("ladder_text"):
        L.append(f"【多週期一覽（加權，小→大）】{snap['ladder_text']}")
    ad = snap.get("advice") or {}
    if ad.get("ok"):
        L.append(f"【系統操作建議（規則推的，不是預測）】{ad['headline']}；" + "；".join(f"{x['k']}：{x['t']}" for x in ad.get("lines") or []) +
                 "；條件：" + ("；".join(f"{'站上' if c['side'] == 'up' else '跌破'} {c['price']:,.0f}（{c['label']}）{c['act']}" for c in ad.get("conds") or []) or "無"))
    iw = (snap.get("waves") or {}).get("intra") or {}
    if iw.get("primary"):
        L.append(f"【超短線 60 分 K 數浪（加權）】{iw['primary'].get('text')}")
    nl = _nest_line(snap, brief=bool((snap.get("tx") or {}).get("ok")))   # 有台指期那一行（比較完整）時，加權只給主要／備選／關卡
    if nl:
        L.append(f"【多層浪名（加權 60 分，照 @fanny55520 的拆法）】{nl}")
    vo = snap.get("volume") or {}
    if vo:
        from .volume import describe as _vd
        L.append("【量能（加權；學 @fanny55520 的「帶量」「最後一推」，回測結果見研究）】"
                 + "；".join(_vd(vo.get(k), nm) for k, nm in (("60m", "60 分"), ("1d", "日 K"))))
    lu = (snap.get("levels") or {}).get("ultra") or {}
    if lu.get("support") or lu.get("resistance"):
        L.append("【超短線支撐】" + ("；".join(_z(z) for z in lu.get("support") or []) or "無") +
                 "【超短線壓力】" + ("；".join(_z(z) for z in lu.get("resistance") or []) or "無"))
    orf = snap.get("open_ref")
    if orf:
        L.append(f"【台指期夜盤 → 加權】夜盤 {orf['night_ret']}%（{orf.get('src')}）→ 歷史平均加權開盤 {orf['gap']}%（±{orf['gap_sd']}%）、"
                 f"收盤 {orf['r1']}%（±{orf['r1_sd']}%）；樣本外 R² {orf.get('oos_r2')} ✅（回測最有效的領先指標）")
    tx = snap.get("tx") or {}
    if tx.get("ok"):
        b = tx.get("basis") or {}
        txw = tx.get("waves") or {}
        L.append(f"【台指期（近月，含夜盤）】{tx['price']:,.0f}（{tx.get('chg_pct')}%，{(tx.get('asof') or {}).get('session', '')}）；"
                 + (f"期現價差 {b.get('pts')} 點（{b.get('label')}）；" if b else "")
                 + f"小級：{((txw.get('small') or {}).get('primary') or {}).get('text', '結構不清楚')}；"
                 + f"中級：{((txw.get('mid') or {}).get('primary') or {}).get('text', '結構不清楚')}；"
                 + f"60 分 K：{((txw.get('intra') or {}).get('primary') or {}).get('text', '—')}")
        nl = _nest_line(tx)
        if nl:
            L.append(f"【多層浪名（台指期 60 分，照 @fanny55520 的拆法）】{nl}")
        tk = tx.get("key") or {}
        L.append("【轉折點（台指期）】" + "；".join(_key(tk.get(m), nm) for m, nm in (("ultra", "超短線"), ("short", "短線"), ("swing", "波段"))))
        for k, nm in (("ultra", "超短線"), ("short", "短線")):
            lv = (tx.get("levels") or {}).get(k) or {}
            L.append(f"【台指期{nm}支撐／壓力】" + "、".join(f"{z['price']:,.0f}" for z in lv.get("support") or []) + "／" +
                     "、".join(f"{z['price']:,.0f}" for z in lv.get("resistance") or []))
    cp = snap.get("composite") or {}
    if cp.get("rows"):
        H = cp.get("horizons") or {}
        st = lambda c: "—" if c is None or c.get("state") is None else ("偏多" if c["state"] > 0 else "偏空" if c["state"] < 0 else "中性") + ("✅" if c.get("pass") else "△")
        L.append("【期貨＋籌碼綜合研判（✅＝回測有效，△＝沒有預測力只能描述）】" + "；".join(
            f"{r['name']} 現在 {r.get('value')}：" + "、".join(f"{H.get(h, h)}{st(c)}" for h, c in (r.get("cells") or {}).items()) for r in cp["rows"]))
        L.append("【綜合方向（只算 ✅）】" + "；".join(f"{H.get(h, h)}：{d.get('label')}" for h, d in (cp.get("dir") or {}).items()))
    fc = snap.get("fut_chips") or {}
    if fc.get("ok"):
        L.append(f"【散戶小台多空比 {fc['date']}】{fc['retail_ratio']}（正＝散戶淨多）、外資選擇權未平倉偏多金額 {fc.get('opt_f_bull')} 千元 △")
    mg = snap.get("margin") or {}
    if mg.get("ok"):
        L.append(f"【融資 {mg['date']}】餘額 {mg['amt']} 億；1 天 {mg['chg1']} 億、5 天 {mg['chg5']} 億、20 天 {mg['chg20']} 億（{mg['pct20']}%）；"
                 f"連續 {'增加' if mg['streak'] > 0 else '減少'} {abs(mg['streak'])} 天 △")
    return L


def facts_small(snap: dict, nw: Optional[dict] = None) -> str:
    """B109 精簡版系統資料（約 2,000 字）：每分鐘字數額度小的 AI（Groq 免費額度）吃不下完整版時改用這份"""
    L = [f"資料日期 {snap['asof']['date']}；加權 {snap['price']:,.0f}（{snap.get('chg_pct')}%）；ATR14 約 {snap.get('atr')} 點"]
    L += ["【規則數浪（系統）】"] + [f"- {_cut(x, 160)}" for x in snap["scenario"]["lines"][:3]]
    px = lambda zs: "、".join(f"{z['price']:,.0f}" for z in zs[:3]) or "無"       # noqa: E731
    for k, nm in (("short", "短線"), ("swing", "波段")):
        lv = snap["levels"][k]
        L.append(f"【{nm}】支撐 {px(lv['support'])}／壓力 {px(lv['resistance'])}（支撐壓力回測沒有比隨機好 △）")
    so = (snap.get("global") or {}).get("sox_overnight")
    if so:
        L.append(f"【前一晚費半 → 加權】費半 {so['sox_ret']}% → 歷史平均加權隔天 {so['tw_expect']}%（±{so['sd']}%，回測有效 ✅）")
    orf = snap.get("open_ref")
    if orf:
        L.append(f"【台指期夜盤 → 加權】夜盤 {orf['night_ret']}% → 歷史平均加權開盤 {orf['gap']}%、收盤 {orf['r1']}%（回測有效 ✅）")
    if snap.get("ladder_text"):
        L.append(f"【多週期一覽】{snap['ladder_text']}")
    tx = snap.get("tx") or {}
    src = tx if tx.get("ok") else snap
    if tx.get("ok"):
        b = tx.get("basis") or {}
        L.append(f"【台指期】{tx['price']:,.0f}（{tx.get('chg_pct')}%）" + (f"；期現價差 {b.get('pts')} 點" if b else ""))
    nz = ((src.get("nest") or {}).get("60m")) or {}
    her = _her_card(nz) if nz.get("ok") else ""
    if her:
        L.append("【照 @fanny55520 的拆法】" + _cut(her, 900))
    elif nz.get("ok"):
        L.append("【多層浪名 60 分】" + _nest_line(src, brief=True))
    cp = snap.get("composite") or {}
    if cp.get("dir"):
        H = cp.get("horizons") or {}
        L.append("【綜合方向（只算回測有效的）】" + "；".join(f"{H.get(h, h)}：{d.get('label')}" for h, d in cp["dir"].items()))
    L.append("【研究結論】只有前一晚費半、台指期夜盤對隔天有效 ✅；波浪、費波那契、支撐壓力、轉折點、籌碼回測都跟隨機差不多 △")
    if nw and nw.get("items"):
        L.append("【近 7 天新聞】" + "；".join(f"{x.get('date', '')} {_cut(x['title'], 40)}" for x in nw["items"][:4]))
    return "\n".join(L)


def facts_tiny(snap: dict) -> str:
    """B109 最短版（約 700 字）：連精簡版都被說太大時的最後一招"""
    L = [f"資料日期 {snap['asof']['date']}；加權 {snap['price']:,.0f}（{snap.get('chg_pct')}%）"]
    if snap["scenario"]["lines"]:
        L.append("【規則數浪】" + _cut(snap["scenario"]["lines"][0], 140))
    px = lambda zs: "、".join(f"{z['price']:,.0f}" for z in zs[:2]) or "無"       # noqa: E731
    lv = snap["levels"]["short"]
    L.append(f"【短線】支撐 {px(lv['support'])}／壓力 {px(lv['resistance'])}（△）")
    orf = snap.get("open_ref")
    if orf:
        L.append(f"【夜盤 → 加權】夜盤 {orf['night_ret']}% → 加權收盤參考 {orf['r1']}%（回測有效 ✅）")
    if snap.get("ladder_text"):
        L.append(f"【多週期】{snap['ladder_text']}")
    tx = snap.get("tx") or {}
    src = tx if tx.get("ok") else snap
    card = (((((src.get("nest") or {}).get("60m")) or {}).get("tiers")) or {}).get("card") or {}
    if card.get("shape") and card.get("pos"):
        L.append("【照 @fanny55520 的拆法】" + _cut("；".join(card["pos"]) + f"；波形：{card['shape']}", 330))
    L.append("【研究】只有前一晚費半、台指期夜盤對隔天有效 ✅；其他都跟隨機差不多 △")
    return "\n".join(L)


RULES = ("規則：只用繁體中文；價位只能用上面資料裡出現的數字（支撐壓力、劇本目標、失效價、歷史分布），不要自己算新點位；"
         "標 △ 的指標回測沒有預測力，不能當成證據；支撐壓力只是參考點——回測「碰支撐做多、碰壓力放空」沒有比隨便畫線好、"
         "扣成本是賠的（B94），不能把碰到支撐／壓力當成進場理由；不要給買賣建議；不確定就說不確定。")


def p_round1(name: str, fx: str) -> str:
    return (f"你是台股大盤分析師「{name}」，參加一場 AI 圓桌。先獨立寫你的看法。\n{RULES}\n\n系統資料：\n{fx}\n\n"
            '只回 JSON：{"stance":"偏多|偏空|盤整","short":"1～2 週看法（≤80 字）","swing":"1～3 個月看法（≤80 字）",'
            '"levels_used":[價位數字],"reasons":["≤3 點，每點 ≤40 字"],"risks":["≤3 點"]}')


def p_round2(name: str, fx: str, me: dict, others: dict) -> str:
    oth = "\n".join(f"- {k}：{json.dumps(v, ensure_ascii=False)}" for k, v in others.items())
    return (f"你是台股大盤分析師「{name}」。這是 AI 圓桌第二輪：看完其他人的第一輪，說你同意和不同意什麼，然後修正你的看法。\n{RULES}\n\n"
            f"系統資料：\n{fx}\n\n你的第一輪：{json.dumps(me, ensure_ascii=False)}\n其他人的第一輪：\n{oth}\n\n"
            '只回 JSON：{"agree":["≤3 點"],"disagree":["≤3 點，說清楚不同意誰的哪一點"],"stance":"偏多|偏空|盤整","view":"修正後看法（≤120 字）"}')


def p_moderate(fx: str, r1: dict, r2: dict) -> str:
    return ("你是 AI 圓桌的主持人。整理下面兩輪討論，寫給一般投資人看。\n" + RULES + "\n\n系統資料：\n" + fx +
            "\n\n第一輪：\n" + "\n".join(f"- {k}：{json.dumps(v, ensure_ascii=False)}" for k, v in r1.items()) +
            "\n第二輪：\n" + "\n".join(f"- {k}：{json.dumps(v, ensure_ascii=False)}" for k, v in r2.items()) +
            '\n\n只回 JSON：{"summary":"一句話結論（≤40 字）","stance":"偏多|偏空|盤整","agree_count":"幾位同意這個方向，例 3/3",'
            '"consensus":["大家都同意的（≤3 點）"],"disagreements":["分歧（≤3 點，說誰怎麼看）"],"short":"短線劇本（≤100 字）",'
            '"swing":"波段劇本（≤100 字）","watch_levels":[{"price":數字,"why":"≤30 字"}],"confidence":"低|中|高"}')


def _cut(t: str, n: int) -> str:
    """太長就在最後一個「；」切掉（給 AI 的資料要省字）"""
    t = str(t or "")
    if len(t) <= n:
        return t
    h = t[:n]
    k = h.rfind("；")
    return (h[:k] if k > n * 0.5 else h) + "…"


def _her_card(nz: dict) -> str:
    """B108 的結論卡（現在位階、波形、照她的進出場怎麼做）→ 一段話；沒有卡就用狀態句"""
    tz = nz.get("tiers") or {}
    card = tz.get("card") or {}
    if card.get("shape") and card.get("pos"):
        return ("她的數法（現在位階）：" + "；".join(card["pos"]) + f"；波形：{card['shape']}；照她的進出場："
                + "；".join(f"{x['tag']}——{x['t']}" for x in card.get("plays") or []) + (f"；{card['flip']}" if card.get("flip") else ""))
    return ""


def _nest_line(snap: dict, brief: bool = False) -> str:
    """B79 多層浪名一句話：主要／備選數法＋關卡。
    B109：原本把她每天的拆法整段貼進來，一行 5,000 多字（整份提示 1.6 萬字），Groq 的免費額度吃不下、Gemini 也常逾時 →
    現在這個階段有結論卡就只給結論卡（位階、波形、怎麼做），整行最多 1,800 字；brief＝只給主要／備選／關卡（加權那一行）"""
    nz = ((snap.get("nest") or {}).get("60m")) or {}
    if not nz.get("ok"):
        return ""
    p, a = nz.get("primary") or {}, nz.get("alternate") or {}
    s = f"起點 {nz['anchor']['p']:,.0f}；主要 {p.get('path')}（{p.get('text')}）"
    if a:
        s += f"；備選 {a.get('path')}（{a.get('text')}）"
    s += "；關卡：" + "；".join(_cut(f"{g['k']}{'✅' if g.get('ok') else ''} {g['t']}", 130) for g in (nz.get("gates") or [])[:5])
    if brief:
        return _cut(s, 800)
    her = _her_card(nz)
    big = snap.get("big") or {}
    if her:                                                           # 現在的階段：只給結論卡＋她看的日線定位
        s += "；" + her
        hx = next((x for x in big.get("scenarios") or [] if x.get("key") == big.get("her")), None)
        if hx:
            s += f"；日線定位（她看這個）：{hx['title']}（" + "、".join(f"{v['label']} {v['price']:,.0f}" for v in hx["levels"]) + "）"
        return _cut(s, 1800)
    vl = [x for x in nz.get("plan") or [] if x.startswith("版本")]       # B83 她 10/28 的兩個版本怎麼確認
    if vl:
        s += "；" + "；".join(vl)
    for x in (snap.get("positioning") or {}).values():
        if x:
            s += f"；{x['tf']}定位：" + _cut("；".join(x["lines"]), 400)
    tw = nz.get("two") or {}                                          # B87／B88 她 11/2 的兩種（版本那幾句已經在上面）
    if tw.get("one") and tw.get("two"):
        o, t = tw["one"], tw["two"]
        x = f"{o.get('text', '')}；第 5 小段目標 " + "、".join(f"{q['label']} {q['price']:,.0f}" for q in o.get("targets") or [])
        if o.get("gate"):
            g = o["gate"]
            x += (f"；決戰關卡 {g['lo']:,.0f}～{g['hi']:,.0f}（b 的 0.5 附近）、移動停利 {g['stop'][0]:,.0f}→{g['stop'][1]:,.0f}；小 c 目標 "
                  + "、".join(f"{c['t']} {c['lo']:,.0f}～{c['hi']:,.0f}（{c['label']}）" for c in o.get("c") or []))
        x += f"；{t.get('text', '')}"
        if t.get("A") and t.get("B"):
            x += (f"；走法 A：b 守 {t['A']['b_strict']:,.0f}、極限 {t['A']['b_ext']:,.0f}，c 依序 " + "→".join(f"{c['price']:,.0f}（{c['label']}）" for c in t["A"]["c"])
                  + f"；走法 B：{min(t['B']['lo'], t['B']['hi']):,.0f}～{max(t['B']['lo'], t['B']['hi']):,.0f} 來回 2～3 天（偏弱）")
        s += "；" + _cut(x + "；" + "；".join(tw.get("judge") or []), 900)
    tz = nz.get("tiers") or {}                                        # B93 她 11/4 的兩道關卡（日線＋60 分）
    if tz.get("lines"):
        s += "；兩道關卡：" + _cut("；".join(tz["lines"]), 900)
        if (tz.get("ext3") or {}).get("lines"):                       # B98 她 11/6 的延伸第 3 段（煞車區、3-4、第 5 段）
            s += "；" + _cut("；".join(tz["ext3"]["lines"]), 600)
    pz = nz.get("pulses") or {}                                       # B89 她 11/3 的三種細微脈動
    if pz.get("views"):
        x = (f"三種細微脈動（分水嶺 {pz['end1']:,.0f}、0.382 {pz['f382']:,.0f}、低點 {pz['low']:,.0f}"
             + (f"、60 分 5 均 {pz['ma5']:,.0f}" if pz.get("ma5") is not None else "")
             + (f"、日線中線支撐 {pz['mid']['price']:,.0f}" if pz.get("mid") else "") + "）：")
        x += "；".join(f"{v['fig']} {v['name']} 現在 {v['now']} → {v['next']}（目標 " + "、".join(f"{t['label']} {t['price']:,.0f}" for t in v["targets"]) + "）"
                      for v in pz["views"])
        s += "；" + _cut(x + "；" + "；".join(pz.get("judge") or []), 800)
    src = nz.get("source") or {}                                      # B86 她 11/1 的源頭兩種切組
    for k, nm in (("three", "第一種切組（三段式）"), ("five", "第二種切組（五段式・威脅）")):
        v = src.get(k)
        if v:
            s += f"；{nm}：" + _cut(f"{v['desc']}，目標 " + "、".join(f"{t['label']} {t['price']:,.0f}" for t in v.get("targets") or []), 300)
    for i, x in enumerate(big.get("scenarios") or [], 1):             # B86 三種日線定位
        s += f"；日線定位 {i}：{_cut(x['title'], 80)}（" + "、".join(f"{v['label']} {v['price']:,.0f}" for v in x["levels"]) + "）"
    if big.get("mid"):                                                # B89 日線黃金切割（中線支撐 0.5）
        s += "；日線黃金切割：" + "、".join(f"{v['label']} {v['price']:,.0f}" for v in big["mid"]["levels"])
    return _cut(s, 3500)


def _nest_prices(snap: dict) -> list:
    out = []
    for x in (snap.get("big") or {}).get("scenarios") or []:          # B86 三種日線定位的價位
        out += [v["price"] for v in x["levels"]]
    out += [v["price"] for v in ((snap.get("big") or {}).get("mid") or {}).get("levels") or []]   # B89 日線黃金切割
    for v in ((((snap.get("nest") or {}).get("60m") or {}).get("source")) or {}).values():
        if isinstance(v, dict):
            out += [t["price"] for t in v.get("targets") or []] + [m["p"] for m in v.get("marks") or []]
    for x in (snap.get("positioning") or {}).values():
        if x:
            out += list(x["ruler"]) + [float(v) for v in x["levels"].values()] + [x["iron"]]
    for nz in ((snap.get("nest") or {}).values()):
        if not (nz or {}).get("ok"):
            continue
        out += [nz["anchor"]["p"], nz["extreme"]["p"]] + [float(v) for v in (nz.get("fib") or {}).values()]
        out += [g["price"] for g in nz.get("gates") or []]
        if nz.get("trendline"):
            out.append(nz["trendline"]["now"])
        ws = nz.get("watershed") or {}
        out += [ws[k] for k in ("lo", "hi") if ws.get(k) is not None] + [v for v, _ in ws.get("lv") or []] + [v for v, _ in ws.get("brk") or []]
        tw = nz.get("two") or {}                         # B87 她 11/2 的兩種
        if tw.get("one") and tw.get("two"):
            o, t = tw["one"], tw["two"]
            out += list(o["std"]) + [o["ceil"], o["hard"], tw["R"], tw["low"]] + [x["price"] for x in o["targets"]]
            if t.get("A") and t.get("B"):
                out += [t["A"]["b_strict"], t["A"]["b_ext"], t["B"]["lo"], t["B"]["hi"]] + [c["price"] for c in t["A"]["c"]]
            if o.get("gate"):                            # B88 決戰關卡、移動停利、小 c 目標、第二種第 3 段／平台 b
                out += [o["gate"]["lo"], o["gate"]["hi"], o["gate"]["mid"]] + list(o["gate"]["stop"]) + list(o.get("b") or [])
                out += [v for c in o.get("c") or [] for v in (c["lo"], c["hi"])] + list(t.get("down") or []) + list(t.get("flat") or [])
        tz = nz.get("tiers") or {}                       # B93 兩道關卡
        if tz.get("gate1"):
            out += [v for v, _ in tz["gate1"]["lv"]] + [v for v, _ in ((tz.get("gate2") or {}).get("lv") or [])]
            out += [float(v) for v in (tz.get("fib") or {}).values()] + list(((tz.get("entry") or {}).get("zone")) or [])
            e3 = tz.get("ext3") or {}                    # B98 延伸第 3 段
            if e3:
                out += [e3["y"], e3["x"]] + [v for z in e3["brakes"] for v, _ in z["lv"]] + [float(v) for v in e3["ffib"].values()]
                out += [e3["reb"][k] for k in ("R", "f382", "f5", "hard", "from")]
                out += [v for z in (e3.get("five") or {}).values() for v, _ in z["lv"]]
                pz = e3.get("paths") or {}                   # B100 三條路徑、三層驗證
                if pz:
                    L1, L2, L3 = pz["layers"]
                    out += list(pz["a"]) + [pz["b"], pz["c1"], pz["c2"]] + [float(v) for v in pz["c"].values()]
                    out += [L1["defend"]] + list(L1["zone"]) + list(L2["prev"]) + [L2["c618"], L2["f5"], L3["gate"], L3["hard"]]
                    out += [v for v, _ in L3["chal"]]
                    nx = pz.get("next") or {}                # B101 升級以後：新脈動目標、撐壓互換頸線
                    if nx:
                        out += [v for v in (nx["from"], nx["prev_hi"], nx["proj"]) if v is not None] + [v for v, _ in nx.get("neck") or []]
                    pu = pz.get("push") or {}                # B103 初推小 5 段、壓回三種區
                    if pu:
                        out += list(pu["seq"]) + [float(v) for v in pu["fib"].values()] + [v for z in pu["zones"] for v, _ in z["lv"]]
                        out += [v for v, _ in pu.get("targets") or []] + [v for v in (pu.get("pull"), pu.get("new_hi")) if v is not None]
                        sb = pu.get("sub") or {}             # B105 大中小
                        if sb:
                            out += [sb["launch"], sb["top3"]] + list(sb["plat"]) + list(sb["limit"]) + [float(v) for v in sb["z4"].values()]
                            out += [v for v, _ in sb["t5"]] + [v for _, a, b in sb["d52"] for v in (a, b)] + ([sb["pb"]] if sb.get("pb") else [])
                            if sb.get("done"):                 # B107 5-1 結束、5-2：A 低點、B 反彈、三個大買點
                                out += [sb["top"]] + [v for v, _ in sb["b52"]] + [z["v"] for z in sb["z52"]] + [z["near"] for z in sb["z52"] if z["near"] is not None]
                                out += [sb["b_hi"]] if sb.get("b_hi") else []
                                out += [v for v, _ in sb.get("c52") or []] + ([sb["c_low"]] if sb.get("c_low") else []) + [sb["a_low"]]
        pz = nz.get("pulses") or {}                      # B89 三種細微脈動
        if pz.get("views"):
            out += [pz["end1"], pz["h2"], pz["low"], pz["f382"]] + ([pz["ma5"]] if pz.get("ma5") is not None else [])
            out += [t["price"] for v in pz["views"] for t in v["targets"]] + [m["p"] for v in pz["views"] for m in v["marks"]]
            out += [pz["mid"]["price"]] if pz.get("mid") else []
        lf = nz.get("life") or {}                        # B85 生死臨界線
        out += [v for v in (lf.get("r70"), lf.get("r618"), lf.get("origin")) if v is not None] + list(lf.get("zone") or [])
        for c in (nz.get("primary"), nz.get("alternate")):
            if c:
                out += [r["price"] for r in c.get("rules") or []] + [t["price"] for t in c.get("targets") or []]
                out += [m["p"] for m in c.get("marks") or []]
    return out


# ── 價位檢查 ─────────────────────────────────────────────────────────────────
NUM_RE = re.compile(r"(?<![\d.])(\d{2},\d{3}|\d{5})(?:\.\d+)?(?![\d,])")


def allowed_levels(snap: dict) -> list:
    out = [snap.get("price"), snap.get("prev_close")]
    for k in ("short", "swing"):
        for side in ("support", "resistance"):
            for z in snap["levels"][k][side]:
                out += [z["price"], z["lo"], z["hi"]] + [s["price"] for s in z["sources"]]
    for w in (snap.get("waves") or {}).values():
        for c in (w.get("primary"), w.get("alternate")):
            if c:
                out.append(c.get("invalid"))
                out += [t["price"] for t in c.get("targets", [])]
                out += [x["p"] for x in c.get("labels", [])]
        if w.get("fib"):
            out += [x["price"] for x in w["fib"]["levels"]]
        out += [p["p"] for p in w.get("pivots", [])]
    for hz in ("h5", "h20", "h60"):
        x = (snap.get("forecast") or {}).get(hz) or {}
        out += [x.get("lo_px"), x.get("mid_px"), x.get("hi_px")]
    # B75：超短線價位、轉折點、台指期（價格、價位、轉折、數浪）
    for z in [z for side in ("support", "resistance") for z in (((snap.get("levels") or {}).get("ultra") or {}).get(side) or [])]:
        out += [z["price"], z["lo"], z["hi"]] + [s_["price"] for s_ in z["sources"]]
    for k in (snap.get("key") or {}).values():
        if k:
            out += [k.get("price"), k.get("wave_invalid")]
    for lk in ("m30", "m15"):
        for z in [z for side in ("support", "resistance") for z in (((snap.get("levels") or {}).get(lk) or {}).get(side) or [])]:
            out += [z["price"], z["lo"], z["hi"]] + [s_["price"] for s_ in z["sources"]]
    for lm in (snap.get("levelmap") or {}).values():          # B80 價位梯（目標、母尺、成交密集區…）
        out += [it.get("price") for it in (lm or {}).get("items") or []]
    for vx in (snap.get("volume") or {}).values():
        out += [x for z in (vx or {}).get("zones") or [] for x in (z.get("lo"), z.get("hi"), z.get("mid"))]
    out += _nest_prices(snap)
    tx = snap.get("tx") or {}
    if tx.get("ok"):
        out += allowed_levels({k: v for k, v in tx.items() if k != "tx"})
        out += [(tx.get("basis") or {}).get("twii")]
    return [float(v) for v in out if v]


def flag_numbers(obj, allowed: list, lo: float = 30000, hi: float = 80000, tol: float = 0.003) -> list:
    txt = json.dumps(obj, ensure_ascii=False)
    bad = []
    for m in NUM_RE.finditer(txt):
        v = float(m.group(1).replace(",", ""))
        if lo <= v <= hi and not any(abs(v - a) / a <= tol for a in allowed):
            if v not in bad:
                bad.append(v)
    return bad


# ── 執行 ─────────────────────────────────────────────────────────────────────
def run(snap: dict, trigger: str = "auto", post=None, news_fn=None) -> dict:
    ps = providers()
    started = D.tw_now().strftime("%Y-%m-%d %H:%M:%S")
    res = {"day": _today(), "started": started, "trigger": trigger, "asof": snap["asof"]["date"], "price": snap["price"],
           "participants": [], "failed": [], "round1": {}, "round2": {}, "moderator": None, "disclaimer": DISCLAIMER}
    try:
        nw = (news_fn or news)(post=post)
    except Exception as e:     # noqa: BLE001
        log.warning(f"[panel] 新聞失敗：{e}")
        nw = {"items": [], "searched": False}
    res["news"] = nw
    fx, fxs, fxt = facts(snap, nw), facts_small(snap, nw), facts_tiny(snap)
    res["prompt_chars"] = {"full": len(fx), "small": len(fxs), "tiny": len(fxt)}

    res["log"] = []
    t_run = time.time()

    def _ask(p, build, rd=None):
        """B109：每分鐘字數額度小的（Groq）直接用精簡版；其他先用完整版，太大／逾時再換精簡版。每次呼叫記一筆（哪個模型、幾秒、中間的錯）"""
        t0 = time.time()
        try:
            a = (ask(p, build(fxs), post=post, alt=[build(fxt)]) if p.get("small")
                 else ask(p, build(fx), post=post, alt=[build(fxs), build(fxt)]))
            res["log"].append({"id": p["id"], "round": rd, "model": a.get("model"), "small": bool(a.get("small") or p.get("small")),
                               "sec": round(time.time() - t0), "retries": [_clean(x)[:200] for x in a.get("errors") or []]})
            return a
        except Exception:
            res["log"].append({"id": p["id"], "round": rd, "model": None, "sec": round(time.time() - t0)})
            raise
    def _all(jobs):
        """幾位 AI 同時問（各家的額度分開算；一場從各家加總變成最慢的那一家）→ [(p, 回答或例外)]，順序照 jobs"""
        if len(jobs) <= 1:
            out = []
            for p, build, rd in jobs:
                try:
                    out.append((p, _ask(p, build, rd)))
                except Exception as e:     # noqa: BLE001
                    out.append((p, e))
            return out
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futs = [(p, ex.submit(_ask, p, build, rd)) for p, build, rd in jobs]
            return [(p, f.exception() or f.result()) for p, f in futs]
    ok_ps = []
    for p, a in _all([(p, (lambda f, p=p: p_round1(p["name"], f)), 1) for p in ps]):
        if isinstance(a, Exception):
            res["failed"].append({"id": p["id"], "name": p["name"], "round": 1, "error": _clean(a)[:400]})
        else:
            res["round1"][p["id"]] = {"name": p["name"], "model": a["model"], **a["json"]}
            ok_ps.append(p)
    if len(ok_ps) >= 2:
        if time.time() - t_run > ROUND2_BUDGET:                        # 第一輪就花太久：第二輪跳過，直接請主持人整理
            res["failed"] += [{"id": p["id"], "name": p["name"], "round": 2, "error": "前面花太久，第二輪跳過"} for p in ok_ps]
        else:
            jobs = []
            for p in ok_ps:
                me = {k: v for k, v in res["round1"][p["id"]].items() if k not in ("name", "model")}
                oth = {res["round1"][q["id"]]["name"]: {k: v for k, v in res["round1"][q["id"]].items() if k not in ("name", "model")}
                       for q in ok_ps if q["id"] != p["id"]}
                jobs.append((p, (lambda f, p=p, me=me, oth=oth: p_round2(p["name"], f, me, oth)), 2))
            for p, a in _all(jobs):
                if isinstance(a, Exception):
                    res["failed"].append({"id": p["id"], "name": p["name"], "round": 2, "error": _clean(a)[:400]})
                else:
                    res["round2"][p["id"]] = {"name": p["name"], "model": a["model"], **a["json"]}
    res["participants"] = [{"id": p["id"], "name": p["name"], "model": res["round1"][p["id"]]["model"]} for p in ok_ps]
    if ok_ps:
        r1 = {v["name"]: {k: x for k, x in v.items() if k not in ("name", "model")} for v in res["round1"].values()}
        r2 = {v["name"]: {k: x for k, x in v.items() if k not in ("name", "model")} for v in res["round2"].values()}
        mods = [p for p in ps if p["id"] == "gemini"] + [p for p in ps if p["id"] == "gptoss"] + \
               [p for p in ps if p["id"] not in ("gemini", "gptoss")]
        for p in mods:
            try:
                a = _ask(p, lambda f: p_moderate(f, r1, r2), "主持")
                res["moderator"] = {"name": p["name"], "model": a["model"], **a["json"]}
                break
            except Exception as e:     # noqa: BLE001
                res["failed"].append({"id": p["id"], "name": p["name"], "round": "主持", "error": _clean(e)[:300]})
    res["mode"] = "roundtable" if len(ok_ps) >= 2 else "single" if ok_ps else "none"
    allowed = allowed_levels(snap)
    res["flagged"] = flag_numbers({"r1": res["round1"], "r2": res["round2"], "mod": res["moderator"]}, allowed)
    res["finished"] = D.tw_now().strftime("%Y-%m-%d %H:%M:%S")
    res["usage_today"] = usage_today()
    ok = 1 if res["mode"] != "none" and res["moderator"] else 0
    with D.db() as c:
        c.execute("INSERT INTO ai_panel(day,created_at,ok,json) VALUES(?,?,?,?)",
                  (res["day"], res["finished"], ok, json.dumps(res, ensure_ascii=False)))
    return res


def latest() -> dict:
    """最新一次；今天最新的失敗 → 附上一次成功的"""
    with D.db() as c:
        last = c.execute("SELECT json, ok FROM ai_panel ORDER BY id DESC LIMIT 1").fetchone()
        good = c.execute("SELECT json FROM ai_panel WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
    out = {"providers": [{"id": p["id"], "name": p["name"]} for p in providers()], "usage_today": usage_today(),
           "cap": daily_cap(), "manual_left": manual_left(), "running": running_job()}
    if not last:
        return {**out, "result": None}
    res = json.loads(last["json"])
    if not last["ok"]:                                                # B109：把沒回應的原因帶出去（畫面上看得到是額度、太大還是逾時）
        out["fail"] = {"at": res.get("finished"), "errors": [{"name": f.get("name"), "round": f.get("round"), "error": _clean(f.get("error", ""))[:300]}
                                                              for f in res.get("failed") or []]}
        if good:
            out["note"] = f"最近一次（{str(res.get('finished') or '')[5:16]}）AI 都沒回應，下面是上一次成功的圓桌"
            res = json.loads(good["json"])
    return {**out, "result": res}


def manual_left() -> int:
    try:
        with D.db() as c:
            rows = [(r["ok"], json.loads(r["json"])) for r in c.execute("SELECT ok, json FROM ai_panel WHERE day=?", (_today(),)).fetchall()]
        man = [ok for ok, j in rows if j.get("trigger") == "manual"]
        if len(man) >= MANUAL_TRIES:                                  # B109：AI 都沒回應的那次不扣次數，但一天總共最多按 MANUAL_TRIES 次
            return 0
        return max(0, MANUAL_LIMIT - sum(1 for ok in man if ok))
    except Exception:     # noqa: BLE001
        return MANUAL_LIMIT


def running_job() -> Optional[str]:
    with _lock:
        for k, v in _jobs.items():
            if v["status"] == "running" and time.time() - v["t"] < 900:
                return k
    return None


def start(snap_fn, trigger: str = "manual") -> str:
    """背景跑；同一時間只跑一個；手動每天最多 MANUAL_LIMIT 次（超過丟 OverflowError）"""
    with _lock:
        for k, v in _jobs.items():
            if v["status"] == "running" and time.time() - v["t"] < 900:
                return k
        if trigger == "manual" and manual_left() <= 0:
            raise OverflowError(f"今天手動圓桌已用完（每天 {MANUAL_LIMIT} 次）")
        jid = uuid.uuid4().hex[:10]
        _jobs[jid] = {"status": "running", "t": time.time()}

    def _run():
        try:
            snap = snap_fn()
            if not snap.get("ok"):
                raise RuntimeError(snap.get("error") or "大盤資料還沒準備好")
            r = run(snap, trigger)
            _jobs[jid].update(status="done", mode=r["mode"])
        except Exception as e:     # noqa: BLE001
            log.exception("[panel] 失敗")
            _jobs[jid].update(status="error", error=str(e)[:300])
    threading.Thread(target=_run, daemon=True).start()
    return jid


def job(jid: str) -> dict:
    with _lock:
        return dict(_jobs.get(jid) or {"status": "unknown"})
