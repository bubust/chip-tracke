"""戰略討論區：把對話（文字＋截圖）丟給 Gemini，找出提到的股票、題材、產業鏈、大哥／小弟、同族群
- 金鑰：環境變數 GEMINI_API_KEY（或 GOOGLE_API_KEY）
- 兩段：① 截圖先單獨讀成文字（一次做讀圖＋分析，小截圖會把「穩懋」讀成「穩穩」，2026-10-07 實測）
        ② 逐字稿＋Google 搜尋做產業分析（AI 自己記得的產業資訊可能過時，CPO 這種新題材尤其）
- 免費額度（2026-10 實測）：Google 搜尋只有 gemini-2.5-flash 能用（3.x 開搜尋回 429）；
  2.5-flash 失敗才換新模型、不開搜尋（結果標「沒查網路」）
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx

_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# (模型, 開 Google 搜尋)
ANALYZE_CHAIN = [("gemini-2.5-flash", True), ("gemini-flash-latest", False), ("gemini-3.6-flash", False),
                 ("gemini-2.5-flash", False)]
OCR_CHAIN = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-3.6-flash"]


def api_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


OCR_PROMPT = ("這是台股投資討論的聊天截圖（LINE 之類）。逐字讀出所有訊息，每則一行，格式「說話的人: 內容」，"
              "時間戳記不用。可能有台股股名、簡稱或代號（例：穩懋、全新、宏捷科、8086），照原樣寫，不要改字。"
              "看不清楚的字用 [?] 標示。只輸出文字。")


def build_prompt(transcript: str, chat_date: str, aliases: dict) -> str:
    alias_txt = "\n".join(f"- 「{k}」＝{v['stock_id']} {v['name']}" for k, v in aliases.items()) or "（目前沒有）"
    return f"""你是台股產業研究助理。使用者常跟一位老大哥討論股票，把對話貼給你，請幫他整理「在講哪些股票、什麼題材、產業鏈上的位置、還有哪些同族群」。
對話日期：{chat_date}（請用 Google 搜尋確認這個時間點前後的最新產業消息，不要只靠你記得的資料）

對話內容：
<<<
{transcript.strip() or "（沒有內容）"}
>>>

使用者確認過的暱稱（一定照這個對應）：
{alias_txt}

規則：
1. 只能是台灣上市櫃股票，stock_id 一定是 4 碼數字代號（ETF、權證不算）。
2. 對話裡常用簡稱、暱稱、錯字、同音字，也常把兩檔連在一起寫（例：「全新穩懋」＝全新 2455＋穩懋 3105；「小弟」指同族群較小較便宜的股票）。
   看得出來就對應；不確定的 confidence 給 "low"，candidates 列最多 3 個可能，**不要硬猜**；完全看不出來 stock_id 留空字串。
3. 「大哥」＝帶頭的高價／龍頭股、「小弟」＝跟漲的較小股票；對話有提到這種關係就填 leader_follower。
4. 產業鏈要分段（上游／中游／下游或材料／設備／代工／封測…），每段列台股代號，說明它在這段做什麼。
5. related 列對話沒提到、但同題材值得一起看的台股（最多 8 檔），說明理由。
6. checks 列你不確定、使用者要自己查證的地方。
7. 全部用繁體中文。

只輸出一個 JSON（放在 ```json 區塊裡），格式：
{{
  "summary": "一兩句話：他們在講什麼",
  "views": [{{"point": "對話裡的觀點或看法", "stance": "看多|看空|中性|觀望"}}],
  "mentions": [{{"text": "對話裡的原始寫法", "stock_id": "2455", "name": "全新", "confidence": "high|medium|low",
                 "reason": "為什麼判斷是這檔", "candidates": [{{"stock_id": "", "name": ""}}]}}],
  "themes": [{{"name": "題材名稱", "why_now": "為什麼現在被討論（引用最新消息）",
               "chain": [{{"segment": "上游：…", "stocks": [{{"stock_id": "", "name": "", "note": "在這段做什麼"}}]}}]}}],
  "leader_follower": [{{"leaders": ["3105"], "followers": ["8086"], "note": "關係說明"}}],
  "related": [{{"stock_id": "", "name": "", "why": ""}}],
  "checks": ["要自己查證的地方"]
}}"""


def _extract_json(txt: str) -> dict:
    m = re.search(r"```json\s*(\{.*\})\s*```", txt, re.S) or re.search(r"(\{.*\})", txt, re.S)
    if not m:
        raise ValueError("AI 沒有回傳 JSON")
    raw = m.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))       # 常見：結尾多逗號


def _call(model: str, parts: list, search: bool, key: str, timeout: float) -> dict:
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0.2}}
    if search:
        body["tools"] = [{"google_search": {}}]
    r = httpx.post(_API.format(model=model), params={"key": key}, json=body, timeout=timeout)
    try:
        d = r.json()
    except ValueError:
        raise RuntimeError(f"{r.status_code} 非 JSON 回應")
    if r.status_code != 200 or "error" in d:
        msg = (d.get("error") or {}).get("message", "") if isinstance(d, dict) else ""
        raise RuntimeError(f"{r.status_code} {msg[:120]}")
    cand = (d.get("candidates") or [{}])[0]
    txt = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    if not txt.strip():
        raise RuntimeError(f"空白回應（{cand.get('finishReason')}）")
    return {"text": txt, "grounding": cand.get("groundingMetadata") or {}}


def ocr(images: list, timeout: float = 90) -> tuple:
    """截圖逐字讀出來。回傳 (文字, 用的模型)"""
    key = api_key()
    errors = []
    texts, used = [], None
    for i, im in enumerate(images):
        part = {"inline_data": {"mime_type": im.get("mime") or "image/jpeg", "data": im["data"]}}
        for model in ([used] if used else []) + [m for m in OCR_CHAIN if m != used]:
            try:
                texts.append(_call(model, [{"text": OCR_PROMPT}, part], False, key, timeout)["text"].strip())
                used = model
                break
            except (httpx.HTTPError, RuntimeError) as e:
                errors.append(f"{model}: {e}")
        else:
            raise RuntimeError(f"第 {i + 1} 張截圖讀不出來：" + "；".join(errors[-3:]))
    return "\n".join(texts), used


def analyze(transcript: str, chat_date: str, aliases: dict, timeout: float = 170) -> dict:
    """回傳 {"result": dict, "model", "searched", "sources", "queries"}"""
    key = api_key()
    if not key:
        raise RuntimeError("還沒設定 Gemini 金鑰（Fly secret GEMINI_API_KEY）")
    parts = [{"text": build_prompt(transcript, chat_date, aliases)}]
    errors = []
    first = os.environ.get("GEMINI_MODEL")
    chain = ([(first, True), (first, False)] if first else []) + ANALYZE_CHAIN
    for model, search in chain:
        try:
            out = _call(model, parts, search, key, timeout)
            result = _extract_json(out["text"])
            gm = out["grounding"]
            sources, seen = [], set()
            for ch in gm.get("groundingChunks") or []:
                w = ch.get("web") or {}
                if w.get("uri") and w["uri"] not in seen:
                    seen.add(w["uri"])
                    sources.append({"title": w.get("title") or "", "uri": w["uri"]})
            return {"result": result, "model": model, "searched": bool(search and gm),
                    "sources": sources[:12], "queries": gm.get("webSearchQueries") or []}
        except (httpx.HTTPError, RuntimeError, ValueError) as e:
            errors.append(f"{model}{'＋搜尋' if search else ''}: {str(e)[:140]}")
            time.sleep(1)
    raise RuntimeError("AI 分析失敗：" + "；".join(errors))
