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
TIMEOUT = 60
MANUAL_LIMIT = 3
NEWS_TTL = 12 * 3600
DISCLAIMER = "劇本＝規則數浪＋歷史條件推估，不是投資建議；AI 看法不是系統計算"
_jobs: dict = {}
_lock = threading.Lock()


def daily_cap() -> int:
    try:
        return int(os.environ.get("PANEL_DAILY_TOKENS", "60000"))
    except ValueError:
        return 60000


def gemini_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def providers() -> list:
    out = []
    if gemini_key():
        first = os.environ.get("GEMINI_PANEL_MODEL") or "gemini-3.6-flash"
        out.append({"id": "gemini", "name": "Gemini（Google）", "kind": "gemini",
                    "models": [first] + [m for m in ("gemini-3.6-flash", "gemini-flash-latest") if m != first]})
    gk = (os.environ.get("GROQ_API_KEY") or "").strip()
    if gk:
        out.append({"id": "gptoss", "name": "GPT-OSS-120B（OpenAI 開源模型，Groq）", "kind": "openai", "base": GROQ_BASE,
                    "key": gk, "models": ["openai/gpt-oss-120b"], "extra": {"reasoning_effort": "low"}})
        out.append({"id": "qwen", "name": "Qwen3（阿里巴巴，Groq）", "kind": "openai", "base": GROQ_BASE,
                    "key": gk, "models": ["qwen/qwen3.8-27b"], "extra": {"reasoning_format": "hidden"}})
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


def call_gemini(model: str, prompt: str, search: bool = False, json_mode: bool = True, post=None) -> dict:
    post = post or httpx.post
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}}
    if search:
        body["tools"] = [{"google_search": {}}]
    elif json_mode:
        body["generationConfig"]["response_mime_type"] = "application/json"
    r = post(GEMINI_API.format(model=model), params={"key": gemini_key()}, json=body, timeout=TIMEOUT)
    d = r.json()
    if r.status_code != 200 or "error" in d:
        raise RuntimeError(f"{r.status_code} {str((d.get('error') or {}).get('message', ''))[:120]}")
    cand = (d.get("candidates") or [{}])[0]
    txt = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    if not txt.strip():
        raise RuntimeError(f"空白回應（{cand.get('finishReason')}）")
    return {"text": txt, "tokens": int((d.get("usageMetadata") or {}).get("totalTokenCount") or 0),
            "grounding": cand.get("groundingMetadata") or {}}


def call_openai(p: dict, model: str, prompt: str, post=None) -> dict:
    post = post or httpx.post
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 1400,
            "response_format": {"type": "json_object"}, **(p.get("extra") or {})}
    r = post(f"{p['base']}/chat/completions", headers={"Authorization": f"Bearer {p['key']}"}, json=body, timeout=TIMEOUT)
    d = r.json()
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {str((d.get('error') or {}).get('message', ''))[:120]}")
    return {"text": d["choices"][0]["message"]["content"] or "", "tokens": int((d.get("usage") or {}).get("total_tokens") or 0)}


def call_anthropic(p: dict, model: str, prompt: str, post=None) -> dict:
    post = post or httpx.post
    r = post("https://api.anthropic.com/v1/messages",
             headers={"x-api-key": p["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
             json={"model": model, "max_tokens": 1400, "messages": [{"role": "user", "content": prompt + "\n只回 JSON。"}]},
             timeout=TIMEOUT)
    d = r.json()
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {str((d.get('error') or {}).get('message', ''))[:120]}")
    u = d.get("usage") or {}
    return {"text": "".join(b.get("text", "") for b in d.get("content") or [] if b.get("type") == "text"),
            "tokens": int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0))}


def ask(p: dict, prompt: str, post=None) -> dict:
    """一位 AI 回答一次（JSON）。超過今日上限 → 丟 OverflowError；模型逐一試（同一位的備用模型），不重試同一個"""
    errors = []
    for model in p["models"]:
        if used_today(model) >= daily_cap():
            errors.append(f"{model} 今日額度已達上限")
            continue
        try:
            if p["kind"] == "gemini":
                out = call_gemini(model, prompt, post=post)
            elif p["kind"] == "anthropic":
                out = call_anthropic(p, model, prompt, post=post)
            else:
                out = call_openai(p, model, prompt, post=post)
            add_usage(model, out.get("tokens", 0))
            return {"model": model, "json": extract_json(out["text"]), "tokens": out.get("tokens", 0)}
        except Exception as e:     # noqa: BLE001  429／413／逾時／JSON 壞掉都換下一個
            errors.append(f"{model}: {str(e)[:140]}")
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
            r = call_gemini(model, NEWS_PROMPT.format(today=day), search=True, json_mode=False, post=post)
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
    L.append("【轉折點（加權）】" + "；".join(_key(ky.get(m), nm) for m, nm in (("ultra", "超短線"), ("short", "短線"), ("swing", "波段"))))
    iw = (snap.get("waves") or {}).get("intra") or {}
    if iw.get("primary"):
        L.append(f"【超短線 60 分 K 數浪（加權）】{iw['primary'].get('text')}")
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


RULES = ("規則：只用繁體中文；價位只能用上面資料裡出現的數字（支撐壓力、劇本目標、失效價、歷史分布），不要自己算新點位；"
         "標 △ 的指標回測沒有預測力，不能當成證據；不要給買賣建議；不確定就說不確定。")


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
    fx = facts(snap, nw)
    ok_ps = []
    for p in ps:
        try:
            a = ask(p, p_round1(p["name"], fx), post=post)
            res["round1"][p["id"]] = {"name": p["name"], "model": a["model"], **a["json"]}
            ok_ps.append(p)
        except Exception as e:     # noqa: BLE001
            res["failed"].append({"id": p["id"], "name": p["name"], "round": 1, "error": str(e)[:200]})
    if len(ok_ps) >= 2:
        for p in ok_ps:
            me = {k: v for k, v in res["round1"][p["id"]].items() if k not in ("name", "model")}
            oth = {res["round1"][q["id"]]["name"]: {k: v for k, v in res["round1"][q["id"]].items() if k not in ("name", "model")}
                   for q in ok_ps if q["id"] != p["id"]}
            try:
                a = ask(p, p_round2(p["name"], fx, me, oth), post=post)
                res["round2"][p["id"]] = {"name": p["name"], "model": a["model"], **a["json"]}
            except Exception as e:     # noqa: BLE001
                res["failed"].append({"id": p["id"], "name": p["name"], "round": 2, "error": str(e)[:200]})
    res["participants"] = [{"id": p["id"], "name": p["name"], "model": res["round1"][p["id"]]["model"]} for p in ok_ps]
    if ok_ps:
        r1 = {v["name"]: {k: x for k, x in v.items() if k not in ("name", "model")} for v in res["round1"].values()}
        r2 = {v["name"]: {k: x for k, x in v.items() if k not in ("name", "model")} for v in res["round2"].values()}
        mods = [p for p in ps if p["id"] == "gemini"] + [p for p in ps if p["id"] == "gptoss"] + \
               [p for p in ps if p["id"] not in ("gemini", "gptoss")]
        for p in mods:
            try:
                a = ask(p, p_moderate(fx, r1, r2), post=post)
                res["moderator"] = {"name": p["name"], "model": a["model"], **a["json"]}
                break
            except Exception as e:     # noqa: BLE001
                res["failed"].append({"id": p["id"], "name": p["name"], "round": "主持", "error": str(e)[:200]})
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
    if not last["ok"] and good:
        out["note"] = "今天 AI 都沒回應，下面是上一次成功的圓桌"
        res = json.loads(good["json"])
    return {**out, "result": res}


def manual_left() -> int:
    try:
        with D.db() as c:
            n = sum(1 for r in c.execute("SELECT json FROM ai_panel WHERE day=?", (_today(),)).fetchall()
                    if json.loads(r["json"]).get("trigger") == "manual")
        return max(0, MANUAL_LIMIT - n)
    except Exception:     # noqa: BLE001
        return MANUAL_LIMIT


def running_job() -> Optional[str]:
    with _lock:
        for k, v in _jobs.items():
            if v["status"] == "running" and time.time() - v["t"] < 900:
                return k
    return None


def start(snap_fn, trigger: str = "manual") -> str:
    """背景跑；同一時間只跑一個；手動每天最多 3 次（超過丟 OverflowError）"""
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
