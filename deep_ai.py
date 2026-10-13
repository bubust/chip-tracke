"""
deep_ai.py — 深度分析「🤖 AI 解盤」（B67，2026-10-13；參考宏爺 AI 戰情室的五章報告）

跟宏爺不一樣的地方：
- 數字全部由系統先算好餵給 AI（官方行情、法人、營收、季報、回測），AI 只負責寫成白話
- 支撐／壓力／目標／停損只准用 price_levels 的價位（回測過），不讓 AI 自己編價位
- K 線型態用 deep_patterns（宏爺 16 種），附回測：高檔墓碑線／倒T、低檔鎚子／T字 不是反轉訊號
- 第四章產業與題材用 Gemini＋Google 搜尋（gemini-2.5-flash 才能開搜尋，跟戰略討論區同一條模型鏈）
結果存 chip_data/deep_ai.db（同一檔同一根 K 棒只跑一次，按「重新產生」才再叫 AI）
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "chip_data" / "deep_ai.db"
DAILY_LIMIT = int(os.environ.get("DEEP_AI_DAILY_LIMIT", "40"))     # 網址沒有密碼：保護 Gemini 免費額度
_TW = timezone(timedelta(hours=8))

_jobs: dict = {}
_lock = threading.Lock()
_daily = {"date": None, "n": 0}


def tw_today() -> str:
    return datetime.now(_TW).date().isoformat()


# ── 資料庫 ───────────────────────────────────────────────────────────────────

def get_conn(db_path=None):
    p = Path(db_path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("""CREATE TABLE IF NOT EXISTS deep_ai (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sid TEXT NOT NULL,
        kdate TEXT,                        -- 用到的最後一根 K 棒日期（YYYYMMDD）
        created_at TEXT,                   -- 台灣時間
        model TEXT, searched INTEGER, text TEXT, sources_json TEXT, queries_json TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_deep_ai_sid ON deep_ai(sid, id)")
    cols = {r[1] for r in c.execute("PRAGMA table_info(deep_ai)")}
    if "news_json" not in cols:                       # B70：第 1 段「近 30 天消息」
        c.execute("ALTER TABLE deep_ai ADD COLUMN news_json TEXT")
    c.execute("CREATE TABLE IF NOT EXISTS deep_ai_news (sid TEXT PRIMARY KEY, t REAL, data TEXT)")
    return c


def latest(sid: str, db_path=None) -> dict | None:
    with closing(get_conn(db_path)) as c:
        r = c.execute("SELECT * FROM deep_ai WHERE sid=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    if not r:
        return None
    return {"sid": r["sid"], "kdate": r["kdate"], "created_at": r["created_at"], "model": r["model"],
            "searched": bool(r["searched"]), "text": r["text"],
            "sources": json.loads(r["sources_json"] or "[]"), "queries": json.loads(r["queries_json"] or "[]"),
            "news": json.loads(r["news_json"] or "null") if "news_json" in r.keys() else None}


def save(sid: str, kdate: str, out: dict, db_path=None):
    with closing(get_conn(db_path)) as c:
        c.execute("INSERT INTO deep_ai (sid, kdate, created_at, model, searched, text, sources_json, queries_json, news_json) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (sid, kdate, datetime.now(_TW).strftime("%Y-%m-%d %H:%M"), out["model"], int(out["searched"]),
                   out["text"], json.dumps(out["sources"], ensure_ascii=False),
                   json.dumps(out["queries"], ensure_ascii=False), json.dumps(out.get("news"), ensure_ascii=False)))
        # 每檔只留最近 5 份
        c.execute("DELETE FROM deep_ai WHERE sid=? AND id NOT IN (SELECT id FROM deep_ai WHERE sid=? "
                  "ORDER BY id DESC LIMIT 5)", (sid, sid))
        c.commit()


# ── Prompt ───────────────────────────────────────────────────────────────────

def _n(v, nd=2):
    """數字 → 字串（None／NaN → —）；整數不帶小數"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(f):
        return "—"
    s = f"{f:,.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _s(v, nd=1):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return ("+" if f > 0 else "") + _n(f, nd) if math.isfinite(f) else "—"


def _ymd(s) -> str:
    s = str(s or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if re.fullmatch(r"\d{8}", s) else s


def kline_rows(df, chip: dict | None, n: int = 30) -> list:
    """近 n 天日 K 表（宏爺餵 AI 的那張）：日期、開高低收、量、MA20、MA100、外資、投信、K 線型態"""
    from deep_patterns import kbar_type
    if df is None or len(df) == 0:
        return []
    c = df["close"].astype(float)
    ma20, ma100 = c.rolling(20).mean(), c.rolling(100).mean()
    inst = {str(x["date"]).replace("-", ""): x for x in ((chip or {}).get("series") or [])}
    out = []
    for i in range(max(0, len(df) - n), len(df)):
        r = df.iloc[i]
        d = str(r.get("date", ""))
        x = inst.get(d.replace("-", ""))
        out.append({"date": _ymd(d), "open": r.get("open"), "high": r.get("high"), "low": r.get("low"),
                    "close": r.get("close"), "volume": r.get("volume"), "ma20": ma20.iloc[i], "ma100": ma100.iloc[i],
                    "foreign": x["foreign"] if x else None, "trust": x["trust"] if x else None,
                    "kbar": kbar_type(r.get("open"), r.get("high"), r.get("low"), r.get("close")) or "—"})
    return out


def _data_block(d: dict, rows: list) -> str:
    t, v, lv = d.get("technical") or {}, d.get("verdict") or {}, d.get("levels") or {}
    pat = d.get("patterns") or {}
    ch, val = d.get("chip") or {}, d.get("valuation") or {}
    rev, inc, eh, rh = d.get("revenue") or {}, d.get("income") or {}, d.get("eps_history") or {}, d.get("revenue_history") or {}
    sec = d.get("sector") or {}
    L = []
    L.append(f"股票：{d.get('stock_id')} {d.get('name')}（{'上櫃' if d.get('market') == 'tpex' else '上市'}）"
             f"　產業：{val.get('sector_name') or sec.get('sector_name') or '—'}")
    L.append(f"最新收盤 {_n(t.get('close'))}（{_s(t.get('change_pct'), 2)}%），K 線日期 {_ymd(t.get('date'))}，"
             f"今天量 {_n(t.get('volume'), 0)} 張、20 日均量 {_n(t.get('vol20'), 0)} 張")

    kb = pat.get("kbars") or []
    L.append(f"\n【日 K 型態（宏爺 16 種定義，近 {len(kb)} 根，舊→新）】")
    for k in kb:
        L.append(f"- {_ymd(k['date'])}：{k['type']}（漲跌 {_s(k.get('chg'), 2)}%）— {k['meaning']}")
    ks = pat.get("kbar_stat")
    if ks:
        line = (f"回測：今天這種 K 線在{ks['band_label']}出現後，5 天平均比同期 {_s(ks['x5'], 2)}%、"
                f"20 天 {_s(ks['x20'], 2)}%（{_n(ks['n'], 0)} 筆）")
        if ks.get("base_x20") is not None:
            line += f"；同位置所有股票 20 天平均 {_s(ks['base_x20'], 2)}%"
        if ks.get("claim"):
            line += f"。注意：一般說法把它當「{ks['claim']}」訊號，回測不成立"
        L.append(line)
    wk = pat.get("weekly") or []
    if wk:
        L.append(f"\n【週 K 型態（近 {len(wk)} 週，舊→新）】")
        for w in wk:
            L.append(f"- {_ymd(w['start'])}～{_ymd(w['end'])}{'（本週到目前，還沒走完）' if w.get('partial') else ''}："
                     f"{w['type']}（週漲跌 {_s(w.get('chg'), 2)}%）— {w['meaning']}")
        ws = pat.get("kbar_w_stat")
        if ws:
            line = (f"回測（最後一根完整週 {ws.get('type', '')}，{ws['band_label']}）：之後 20 個交易日平均比同期 {_s(ws['x20'], 2)}%"
                    f"（{_n(ws['n'], 0)} 筆）")
            if ws.get("base_x20") is not None:
                line += f"；同位置所有股票 {_s(ws['base_x20'], 2)}%"
            L.append(line)

    tr = pat.get("trend")
    if tr:
        L.append("\n【趨勢格局（宏爺 MA20／MA100）】")
        L.append(f"格局：{tr['box']}（{tr['desc']}）；MA20 {_n(tr['ma20'])}（{'上彎' if tr.get('ma20_up') else '下彎'}）、"
                 f"MA100 {_n(tr['ma100'])}（{'上彎' if tr.get('ma100_up') else '下彎'}）；"
                 f"乖離 MA20 {_s(tr['bias20'], 2)}%、MA100 {_s(tr['bias100'], 2)}%"
                 + (f"；月線斜率 {_s(tr.get('mslope'), 2)}%（{(tr.get('ms') or {}).get('tier', '')}："
                    f"{(tr.get('ms') or {}).get('desc', '')}；"
                    f"{'月線連續上揚' if ((tr.get('ms') or {}).get('streak') or 0) > 0 else '月線連續下降'} {abs((tr.get('ms') or {}).get('streak') or 0)} 天；"
                    f"回測這個強弱之後 20 天平均比同期 {_s((tr.get('ms') or {}).get('x20'), 2)}%）"
                    if tr.get("mslope") is not None else ""))
        bs = tr.get("stat")
        if bs:
            line = f"回測：{tr['box']}格局 20 天平均比同期 {_s(bs['x20'], 2)}%（{_n(bs['n'], 0)} 筆）"
            if bs.get("in_bucket"):
                line += f"；技術{(v.get('bucket') or {}).get('label', '')}又是{tr['box']}：{_s(bs['in_bucket']['x20'], 2)}%"
            L.append(line)

    ma, r = t.get("ma") or {}, t.get("ret") or {}
    m = t.get("macd") or {}
    L.append("\n【技術（系統，已回測）】")
    L.append(f"技術分類：{(v.get('bucket') or {}).get('label', '—')}（原始 {t.get('tech_raw')} / 40）；"
             f"10/20/60 日線 {_n(ma.get('ma10'))}／{_n(ma.get('ma20'))}／{_n(ma.get('ma60'))}，"
             f"{'多頭排列' if ma.get('bull') else '還沒排好'}、60 日線{'上彎' if ma.get('ma60_up') else '下彎'}；"
             f"MACD DIF {_n(m.get('dif'))}、DEA {_n(m.get('dea'))}、柱 {_n(m.get('osc'))}")
    L.append(f"52 週位置 {_n((t.get('pos52') or 0) * 100, 0)}%（{_n(t.get('w52_low'))}～{_n(t.get('w52_high'))}）；"
             f"近 5／20／60／120 日 {_s(r.get('5'))}%／{_s(r.get('20'))}%／{_s(r.get('60'))}%／{_s(r.get('120'))}%")
    bst = (v.get("bucket") or {}).get("stats")
    if bst:
        L.append(f"回測：技術{(v.get('bucket') or {}).get('label')}過去 20 天平均比同期 {_s(bst['x20'], 2)}%、"
                 f"上漲機率 {bst['up']}%、期間最大回檔平均 {bst['mdd']}%")

    L.append("\n【籌碼】")
    if ch.get("error"):
        L.append(f"法人：{ch['error']}")
    else:
        span = ch.get("span") or ch.get("days")
        for k, lbl in (("foreign", "外資"), ("trust", "投信"), ("dealer", "自營商"), ("main", "主力合計")):
            o = ch.get(k) or {}
            st = o.get("streak") or 0
            L.append(f"- {lbl}：今天 {_s(o.get('d1'), 0)}、5 日 {_s(o.get('d5'), 0)}、{ch.get('days')} 日 {_s(o.get('d20'), 0)}、"
                     f"{span} 日 {_s(o.get('dall'), 0)} 張；{'連買' if st > 0 else '連賣' if st < 0 else '最後一天沒買賣'}"
                     f"{f' {abs(st)} 天' if st else ''}")
    mg = ch.get("margin")
    if mg:
        L.append(f"- 融資餘額 {_n(mg.get('margin'), 0)} 張（{mg.get('span_all')} 日 {_s(mg.get('margin_chg_all'), 0)}）、"
                 f"融券餘額 {_n(mg.get('short'), 0)} 張（{mg.get('span_all')} 日 {_s(mg.get('short_chg_all'), 0)}）")
    if ch.get("kpct") is not None:
        L.append(f"- 千張大戶持股 {_n(ch['kpct'])}%（比上週 {_s(ch.get('kpct_change'), 2)} 個百分點）")

    L.append("\n【基本面】")
    if val.get("etf"):
        L.append("ETF：沒有本益比與財報")
    else:
        L.append(f"本益比 {_n(val.get('per'))}（同產業中位數 {_n(val.get('peer_pe_median'))}、{val.get('peer_n') or 0} 檔）、"
                 f"股價淨值比 {_n(val.get('pbr'))}、殖利率 {_n(val.get('dividend_yield'))}%、"
                 f"股本 {_n(val.get('capital'))} 億、市值 {_n(val.get('market_cap'), 0)} 億")
        if rev:
            L.append(f"最新月營收（{rev.get('ym')}）{_n((rev.get('revenue') or 0) / 1e5)} 億，月增 {_s(rev.get('mom'))}%、"
                     f"年增 {_s(rev.get('yoy'))}%；今年累計年增 {_s(rev.get('ytd_yoy'))}%"
                     + (f"；備註：{rev['note']}" if rev.get("note") else ""))
        if rh.get("months"):
            L.append("近 12 個月營收（億，年增%）：" + "、".join(
                f"{x['ym']} {_n(x['rev'])}（{_s(x['yoy'])}%）" for x in rh["months"]))
            if rh.get("yoy3") is not None:
                L.append(f"近 3 個月累計年增 {_s(rh['yoy3'])}%" + ("；最新月營收是拿到的資料裡最高" if rh.get("is_high") else ""))
        if eh.get("quarters"):
            L.append("近幾季（單季）：" + "、".join(
                f"{q['q']} 營收 {_n(q.get('rev'))} 億・毛利率 {_n(q.get('gm'), 1)}%・營益率 {_n(q.get('om'), 1)}%・EPS {_n(q.get('eps'))}"
                for q in eh["quarters"]))
            if eh.get("ttm") is not None:
                L.append(f"近四季 EPS 合計 {_n(eh['ttm'])} 元" +
                         (f"；最新一季 EPS 比去年同季 {_s(eh.get('eps_yoy'))}%" if eh.get("eps_yoy") is not None else ""))
        elif inc:
            L.append(f"{inc.get('label')}：EPS {_n(inc.get('eps'))} 元、毛利率 {_n(inc.get('gross_margin'), 1)}%、"
                     f"營益率 {_n(inc.get('op_margin'), 1)}%")
    if sec.get("rank20d") is not None and (sec.get("total") or 0) >= 10 and not sec.get("stale"):
        L.append(f"產業強度：{sec.get('sector_name')} 20 日漲幅在 {sec.get('total')} 個產業裡第 {sec['rank20d']} 名")

    L.append("\n【系統關鍵價位（只能用這些價位）】")
    price = lv.get("price") or t.get("close")
    def _lvl(lbl, p, note=""):
        if p:
            L.append(f"- {lbl} {_n(p)}（距現價 {_s((float(p) / float(price) - 1) * 100 if price else None)}%）"
                     + (f"：{note}" if note else ""))
    _lvl("目標", lv.get("target"), lv.get("target_method") or "")
    _lvl("壓力一", (lv.get("pressure1") or {}).get("low"), "最近的前高")
    _lvl("壓力二", (lv.get("pressure2") or {}).get("low"), "前面的高點區")
    _lvl("支撐", (lv.get("support") or {}).get("price"), (lv.get("support") or {}).get("label") or "")
    _lvl("停損", (lv.get("stop") or {}).get("price"), (lv.get("stop") or {}).get("label") or "收盤跌破出場")
    if not lv:
        L.append("- 沒有關鍵價位資料")

    L.append("\n【系統綜合評價】")
    if v.get("ok"):
        L.append(f"分數 {v.get('score')} / 100（{v.get('grade')}），動作：{v.get('action')}；{v.get('summary')}")
        for x in v.get("advice") or []:
            L.append(f"- {x}")
    else:
        L.append(v.get("reason") or "資料不足，不給評價")
    mk = v.get("market") or {}
    if mk:
        L.append(f"大盤（總經面板）：{mk.get('label')}（{mk.get('date')}）")
    st = (d.get("strategies_today") or {}).get("items") or []
    if st:
        L.append("今天符合的選股策略：" + "、".join(x.get("label", "") for x in st))

    if rows:
        L.append("\n【近 30 日日 K（量＝張，法人＝張）】")
        L.append("日期 | 開 | 高 | 低 | 收 | 量 | MA20 | MA100 | 外資 | 投信 | K線")
        for x in rows:
            L.append(" | ".join([x["date"], _n(x["open"]), _n(x["high"]), _n(x["low"]), _n(x["close"]),
                                 _n(x["volume"], 0), _n(x["ma20"]), _n(x["ma100"]),
                                 _s(x["foreign"], 0), _s(x["trust"], 0), x["kbar"]]))
    return "\n".join(L)


def _news_block(d: dict, digest: dict | None) -> str:
    L = ["【近 30 天消息（Google 搜尋整理，第四章只能用這裡和系統數字）】"]
    items = (digest or {}).get("items") or []
    if items:
        for x in items[:10]:
            L.append(f"- {x.get('date', '')} {x.get('title', '')}：{x.get('summary', '')}（{x.get('source', '')}）")
    else:
        L.append("- （這次沒有查到網路消息）")
    key = lambda t: re.sub(r"[\W_]+", "", str(t or ""))[:14]      # noqa: E731
    seen = {key(x.get("title")) for x in items}
    sys_news = [x for x in (d.get("news") or {}).get("items") or [] if key(x.get("title")) not in seen]
    if sys_news:
        L.append("【系統抓到的新聞標題（近 30 天，已去掉跟上面重複的）】")
        for x in sys_news[:8]:
            L.append(f"- {x.get('date', '')} {x.get('title', '')}（{x.get('publisher', '')}）")
    return "\n".join(L)


def build_prompt(d: dict, rows: list, digest: dict | None = None) -> str:
    return f"""你是台股研究員，幫使用者寫「{d.get('stock_id')} {d.get('name')}」的解盤重點。今天是 {tw_today()}。
【資料】的數字都是系統算好的（官方行情與法人、月營收、季報、系統回測），直接引用、不要改數字。

規則：
1. 繁體中文、白話、阿拉伯數字；全文 700～1,000 字（800～1,200 字是上限），寧可短、不要重複資料。
2. 開頭先寫一句話結論（30 字內、不要標題），再寫五章；章名照下面抄、不要加括號說明；每章 3～4 個「- 」重點，每點 1 句為主。
3. 支撐、壓力、目標、停損只能用【系統關鍵價位】的數字，不可以自己算或編新的價位（可以提 MA20、MA100 的位置）。
4. K 線用系統判斷的名稱：日 K 近 5 根、週 K 近 4 週，各用「→」串成一串並用「」框住；不要逐日描述。
5. 尊重回測：日 K 高檔墓碑線／倒T之後平均還是續漲、低檔鎚子／T字之後平均續跌，不能說成反轉；週 K 的回測數字照引用。
6. 第四章「產業與基本面」只能用【近 30 天消息】、系統新聞與系統財報數字，每個題材、目標價都寫日期；
   近 30 天沒有消息就寫「近 30 天沒有重大新聞」，不要拿舊聞或憑記憶補。
7. 沒有的資料就說沒有；不要表格、不要前言、不要逐月逐季照抄。

章名（照抄）：
## 一、K 線
## 二、均線與格局
## 三、籌碼
## 四、產業與基本面
## 五、操作策略
各章寫什麼：一＝日 K 近 5 根、週 K 近 4 週的組合與回測；二＝MA20／MA100 格局、乖離、月線斜率、系統技術分類；
三＝外資、投信、主力合計、融資融券、千張大戶；四＝近 30 天消息、營收與毛利率趨勢、本益比；
五＝系統評價與動作、積極型、保守型，最後「風險」用 1. 2. 3. 列 3 點。

【資料】
{_data_block(d, rows)}

{_news_block(d, digest)}
"""


NEWS_PROMPT = """請用 Google 搜尋台股「{sid} {name}」最近 30 天（今天是 {today}）的重要消息：法說會、月營收／財報、法人評等與目標價、
重大訊息（併購、擴產、接單、處分）、產業動態。優先最近 2 週；超過 90 天的不要。
只輸出 JSON（放在 ```json 區塊）：{{"items": [{{"date": "YYYY-MM-DD", "title": "標題", "summary": "一兩句重點", "source": "媒體名稱"}}]}}
最多 8 則、新到舊；查不到就回 {{"items": []}}。"""
NEWS_TTL = 12 * 3600


def news_digest(d: dict, timeout: float = 90, db_path=None) -> dict:
    """第 1 段：Gemini＋Google 搜尋整理近 30 天消息（每檔快取 12 小時）；失敗回 {"items": [], "searched": False}"""
    from discuss import ai
    sid = str(d.get("stock_id") or "")
    with closing(get_conn(db_path)) as c:
        r = c.execute("SELECT t, data FROM deep_ai_news WHERE sid=?", (sid,)).fetchone()
    if r and time.time() - r["t"] < NEWS_TTL:
        return json.loads(r["data"])
    key = ai.api_key()
    out = {"items": [], "searched": False, "model": None, "sources": []}
    if key:
        prompt = NEWS_PROMPT.format(sid=sid, name=d.get("name") or "", today=tw_today())
        for model in [m for m, srch in ai.ANALYZE_CHAIN if srch]:
            try:
                res = ai._call(model, [{"text": prompt}], True, key, timeout)
                items = ai._extract_json(res["text"]).get("items") or []
                gm = res["grounding"]
                srcs = [{"title": (ch.get("web") or {}).get("title") or "", "uri": (ch.get("web") or {}).get("uri")}
                        for ch in gm.get("groundingChunks") or [] if (ch.get("web") or {}).get("uri")]
                searched = bool(srcs or gm.get("webSearchQueries"))
                cut = (datetime.now(_TW).date() - timedelta(days=45)).isoformat()   # 30 天＋緩衝，擋掉 AI 拿舊聞
                items = [x for x in items if isinstance(x, dict) and str(x.get("date") or "")[:10] >= cut][:8]
                out = {"items": items if searched else [], "searched": searched, "model": model, "sources": srcs[:8]}
                break
            except Exception:    # noqa: BLE001  搜尋失敗不影響第 2 段
                continue
    if out["searched"]:
        with closing(get_conn(db_path)) as c:
            c.execute("INSERT OR REPLACE INTO deep_ai_news VALUES (?,?,?)", (sid, time.time(), json.dumps(out, ensure_ascii=False)))
            c.commit()
    return out


def _clean(txt: str) -> str:
    """拿掉 ```markdown 外框、開頭的客套話行（「好的，以下是…」）；B70：保留開頭一句話結論"""
    txt = txt.strip()
    m = re.fullmatch(r"```(?:markdown|md)?\s*(.*?)\s*```", txt, re.S)
    txt = m.group(1).strip() if m else txt
    lines = txt.split("\n")
    while lines and re.match(r"^\s*(好的|沒問題|當然|以下(是|為)|這是)", lines[0]):
        lines.pop(0)
    return "\n".join(lines).strip()


def generate(d: dict, rows: list, timeout: float = 170) -> dict:
    """叫 Gemini；回 {"text", "model", "searched", "sources", "queries"}"""
    from discuss import ai
    key = ai.api_key()
    if not key:
        raise RuntimeError("還沒設定 Gemini 金鑰（Fly secret GEMINI_API_KEY）")
    try:
        digest = news_digest(d)
    except Exception:    # noqa: BLE001
        digest = {"items": [], "searched": False, "sources": []}
    parts = [{"text": build_prompt(d, rows, digest)}]
    errors = []
    first = os.environ.get("GEMINI_MODEL")
    chain = ([(first, True), (first, False)] if first else []) + ai.ANALYZE_CHAIN
    for model, search in chain:
        try:
            out = ai._call(model, parts, search, key, timeout)
            text = _clean(out["text"])
            if len(text) < 150:
                raise RuntimeError(f"回應太短（{len(text)} 字）")
            gm = out["grounding"]
            sources, seen = [], set()
            for ch in gm.get("groundingChunks") or []:
                w = ch.get("web") or {}
                if w.get("uri") and w["uri"] not in seen:
                    seen.add(w["uri"])
                    sources.append({"title": w.get("title") or "", "uri": w["uri"]})
            queries = gm.get("webSearchQueries") or []
            # 開了搜尋不代表有查：沒有查詢字串也沒有來源就當沒查（避免畫面標「＋Google 搜尋」誤導）
            for x in digest.get("sources") or []:          # 第 1 段的搜尋來源也列出來
                if x.get("uri") and x["uri"] not in seen:
                    seen.add(x["uri"])
                    sources.append(x)
            return {"text": text, "model": model, "searched": bool((search and (sources or queries)) or digest.get("searched")),
                    "sources": sources[:12], "queries": queries,
                    "news": {"items": digest.get("items") or [], "searched": bool(digest.get("searched"))}}
        except Exception as e:    # noqa: BLE001  httpx／RuntimeError／JSON 都換下一個模型
            errors.append(f"{model}{'＋搜尋' if search else ''}: {str(e)[:140]}")
            time.sleep(1)
    raise RuntimeError("AI 解盤失敗：" + "；".join(errors))


# ── 背景工作 ─────────────────────────────────────────────────────────────────

def start_job(sid: str, kdate: str, d: dict, rows: list) -> str:
    """配額檢查＋開背景執行緒；超過今天上限丟 OverflowError；同一檔還在跑 → 回同一個工作（不重複扣額度）"""
    today = tw_today()
    with _lock:
        for k, v in _jobs.items():
            if v.get("sid") == sid and v.get("status") == "running" and time.time() - v["t"] < 600:
                return k
        if _daily["date"] != today:
            _daily.update(date=today, n=0)
        if _daily["n"] >= DAILY_LIMIT:
            raise OverflowError(f"今天已經產生 {DAILY_LIMIT} 份 AI 解盤，明天再來（保護免費額度）")
        _daily["n"] += 1
        for k in [k for k, v in _jobs.items() if time.time() - v["t"] > 3600]:
            _jobs.pop(k, None)
        jid = uuid.uuid4().hex[:12]
        _jobs[jid] = {"status": "running", "sid": sid, "t": time.time()}
    threading.Thread(target=_run, args=(jid, sid, kdate, d, rows), daemon=True, name="deep-ai").start()
    return jid


def _run(jid, sid, kdate, d, rows):
    try:
        out = generate(d, rows)
        save(sid, kdate, out)
        _set(jid, status="done")
    except Exception as e:      # noqa: BLE001
        _set(jid, status="error", error=str(e)[:600])


def _set(jid, **kw):
    with _lock:
        if jid in _jobs:
            _jobs[jid].update(kw)


def job(jid: str) -> dict | None:
    with _lock:
        j = _jobs.get(jid)
        return None if not j else {k: v for k, v in j.items() if k != "t"} | {"elapsed": round(time.time() - j["t"])}


def status() -> dict:
    from discuss import ai
    with _lock:
        n = _daily["n"] if _daily["date"] == tw_today() else 0
    return {"has_key": bool(ai.api_key()), "today": n, "limit": DAILY_LIMIT}
