"""
從 MOPS 重大訊息列表（公司代號／名稱／發言日期／主旨）挑出收購併購事件，並盡量從主旨抓出價格、數量、期間。
主旨常只寫「代子公司公告公開收購XX公司普通股」，細節在公告內文 → 抓不到的欄位留空，畫面上可手動補。
"""
from __future__ import annotations

import re
from typing import Optional

from treasury.parser import _TableGrid, _expand, roc_to_iso, to_num

# 依序判斷（越前面越精確）
_TYPES = [
    ("公開收購", re.compile(r"公開收購")),
    ("股份轉換", re.compile(r"股份轉換|股份交換")),
    ("合併", re.compile(r"合併(?!報表|營收|財務|損益|資產負債)|併購")),
    ("收購股權", re.compile(r"(收購|取得).{0,12}(股權|股份|普通股)")),
]
_EXCLUDE = re.compile(r"合併營收|合併營業收入|合併財務|合併報表|合併損益|合併資產|合併及個體|合併中文財務|財務報告|財報|"
                      r"子公司.*營收|自結|澄清媒體|使用權資產|不動產|簡易合併|iXBRL")
_PRICE = re.compile(r"每股(?:新[臺台]幣|現金)?\s*([0-9]+(?:\.[0-9]+)?)\s*元")
_SHARES = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(萬)?股")
_PERIOD = re.compile(r"(\d{2,4}[/.年]\d{1,2}[/.月]\d{1,2}日?)\s*(?:至|~|～|－|-)\s*(\d{2,4}[/.年]\d{1,2}[/.月]\d{1,2}日?)")
_PCT = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
_ACQ = re.compile(r"(?:代子公司|本公司)?(?:擬)?由?\s*([^\s，,、]{2,20}?(?:股份有限公司|公司|投資|基金|集團))\s*(?:擬)?(?:對|公開收購|收購)")


# 減資／增資（老王筆記：虧損減資首日跳上、增資短線別碰…）；排除對子公司增資、轉投資、庫藏股註銷、公司債
_CAPITAL = [
    ("減資", re.compile(r"減資|減少資本|資本減少")),
    ("現金增資", re.compile(r"現金增資|私募普通股|私募.{0,6}股票|辦理私募")),
]
_CAPITAL_EXCLUDE = re.compile(r"子公司|孫公司|轉投資|被投資|(?:參與|認購|投資|增資).{0,20}(?:公司|Ltd|Inc).{0,10}(?:現金增資|增資)|"
                              r"(?:參與|認購).{0,25}增資|庫藏股|員工認股|可轉換|公司債|特別股|海外存託|GDR|全球存託|"
                              r"澄清|媒體報導|更正|補充")
CAPITAL_TYPES = ("減資", "現金增資")


def classify(subject: str) -> Optional[str]:
    s = subject or ""
    if _EXCLUDE.search(s):
        return None
    for name, rx in _TYPES:
        if rx.search(s):
            return name
    if not _CAPITAL_EXCLUDE.search(s):
        for name, rx in _CAPITAL:
            if rx.search(s):
                return name
    return None


def capital_info(subject: str, text: str = "") -> dict:
    """減資／增資：細分種類、減資比率、恢復買賣日（減資）或繳款期間（增資）、認購價"""
    s = f"{subject or ''} {text or ''}"
    out: dict = {}
    if re.search(r"減資|減少資本|資本減少", subject or "") or (not re.search(r"增資", subject or "") and "減資" in s):
        if re.search(r"減資.{0,40}(?:再|後|同時).{0,10}(?:現金)?增資|增資.{0,20}減資", s[:3000]):
            out["deal_kind"] = "減資再增資"
        elif re.search(r"彌補虧損|虧損", s[:3000]):
            out["deal_kind"] = "虧損減資"
        elif re.search(r"退還|返還|現金減資", s[:3000]):
            out["deal_kind"] = "現金減資"
        else:
            out["deal_kind"] = "減資"
        m = re.search(r"減資比率[^0-9%]{0,12}([0-9]+(?:\.[0-9]+)?)\s*%", s) or re.search(r"減資[^。；]{0,30}?([0-9]+(?:\.[0-9]+)?)\s*%", s)
        if m:
            out["offer_pct"] = float(m.group(1))
        m = re.search(r"(?:恢復買賣|新股上市|換發新股上市|恢復交易)[^。；]{0,30}?(\d{2,4}[/.年]\d{1,2}[/.月]\d{1,2})", s)
        if m:
            out["period_start"] = roc_to_iso(re.sub(r"[年月.]", "/", m.group(1)))
    else:
        out["deal_kind"] = "私募" if "私募" in s[:600] else "現金增資"
        m = re.search(r"(?:發行|認購|承銷)價(?:格)?[^0-9。]{0,15}([0-9]+(?:\.[0-9]+)?)\s*元", s)
        if m:
            out["offer_price"] = float(m.group(1))
        m = re.search(r"繳款期間[^。；]{0,10}?(\d{2,4}[/.年]\d{1,2}[/.月]\d{1,2})日?\s*(?:至|~|～|－|-)\s*(\d{2,4}[/.年]\d{1,2}[/.月]\d{1,2})", s)
        if m:
            out["period_start"] = roc_to_iso(re.sub(r"[年月.]", "/", m.group(1)))
            out["period_end"] = roc_to_iso(re.sub(r"[年月.]", "/", m.group(2)))
    return {k: v for k, v in out.items() if v not in (None, "")}


def extract(subject: str) -> dict:
    s = subject or ""
    out = {}
    m = _PRICE.search(s)
    if m:
        out["offer_price"] = float(m.group(1))
    shares = []
    for m in _SHARES.finditer(s):
        v = to_num(m.group(1))
        if v:
            shares.append(v * (10000 if m.group(2) else 1))
    if shares:
        out["max_shares"] = max(shares)
        if len(shares) >= 2:
            out["min_shares"] = min(shares)
    m = _PERIOD.search(s)
    if m:
        out["period_start"] = roc_to_iso(m.group(1).replace("年", "/").replace("月", "/").replace("日", ""))
        out["period_end"] = roc_to_iso(m.group(2).replace("年", "/").replace("月", "/").replace("日", ""))
    m = _PCT.search(s)
    if m and float(m.group(1)) <= 100:
        out["offer_pct"] = float(m.group(1))
    if re.search(r"全部|100\s*%|下市|百分之百", s):
        out["scope"] = "完全收購"
    elif re.search(r"部分|最高收購|上限|最低收購", s):
        out["scope"] = "部分收購"
    if re.search(r"現金", s) and re.search(r"換股|股份轉換|發行新股", s):
        out["consideration"] = "現金＋換股"
    elif re.search(r"現金", s):
        out["consideration"] = "現金"
    elif re.search(r"換股|股份轉換|發行新股", s):
        out["consideration"] = "換股"
    m = _ACQ.search(s)
    if m:
        out["acquirer"] = m.group(1)
    return out


def parse_announcements(html: str) -> list:
    """MOPS 重大訊息表格 → 收購併購候選 [{target_id, target_name, announce_date, subject, deal_type, ...}]"""
    p = _TableGrid()
    p.feed(html)
    out = []
    for t in p.tables:
        grid = [[txt for txt, _ in row] for row in _expand(t)]
        hdr_i = next((i for i, r in enumerate(grid) if any("代號" in x for x in r) and any("主旨" in x for x in r)), None)
        if hdr_i is None:
            continue
        hdr = [x.replace(" ", "") for x in grid[hdr_i]]
        def col(*keys):
            return next((i for i, h in enumerate(hdr) if any(k in h for k in keys)), None)
        ci, cn, cd, cs = col("代號"), col("名稱", "簡稱"), col("日期"), col("主旨")
        if ci is None or cs is None:
            continue
        for r in grid[hdr_i + 1:]:
            if len(r) <= max(ci, cs):
                continue
            sid, subject = r[ci].strip(), r[cs].strip()
            if not re.fullmatch(r"[0-9A-Z]{4,6}", sid):
                continue
            kind = classify(subject)
            if not kind:
                continue
            rec = {"target_id": sid, "target_name": r[cn].strip() if cn is not None and cn < len(r) else "",
                   "announce_date": roc_to_iso(r[cd]) if cd is not None and cd < len(r) else None,
                   "subject": subject[:500], "deal_type": kind, "source": "MOPS 重大訊息"}
            rec.update(capital_info(subject) if kind in CAPITAL_TYPES else extract(subject))
            out.append(rec)
    return out


# ── 公告內文（t05st02_detail）欄位解析：公告是「1.欄位名:內容 2.欄位名:內容 …」的固定樣板 ──
_FIELD = re.compile(r"(?:^|\s)(\d{1,2})\.([^:：\d][^:：]{0,110}?)[:：]")
_DATE_CN = re.compile(r"(\d{2,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日|(\d{2,4})/(\d{1,2})/(\d{1,2})")
_CASH = re.compile(r"現金(?:新[臺台]幣)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元")
_RATIO = re.compile(r"(?:可換取|換發|配發|換取)\s*(.{2,20}?)(?:股份有限公司)?(?:\(下稱[^)]*\))?\s*普通股\s*([0-9]+(?:\.[0-9]+)?)\s*股")


def split_fields(text: str) -> list:
    """回傳 [(欄位名, 內容), ...]"""
    ms = list(_FIELD.finditer(text or ""))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        out.append((m.group(2).strip(), text[m.end():end].strip()))
    return out


def _dates(s: str) -> list:
    out = []
    for m in _DATE_CN.finditer(s or ""):
        g = m.groups()
        y, mo, d = (g[0], g[1], g[2]) if g[0] else (g[3], g[4], g[5])
        iso = roc_to_iso(f"{y}/{mo}/{d}")
        if iso:
            out.append(iso)
    return out


def _company(s: str) -> str:
    s = re.sub(r"\(下稱.*?\)|（以下簡稱.*?）|\(以下簡稱.*?\)", "", s or "").strip()
    m = re.search(r"([^\s：:，,（(]{2,30}?股份有限公司|[^\s：:，,（(]{2,30}?(?:Inc\.|Ltd\.|Limited|Corporation))", s)
    return (m.group(1) if m else s[:30]).strip()


def short_company(name: str) -> str:
    return re.sub(r"股份有限公司|\(股\)公司|（股）公司|公司$", "", name or "").strip()


def parse_detail(text: str, subject: str = "") -> dict:
    """從公告內文抓：收購方、被收購公司、價格（現金＋換股比例）、最高／最低數量、比例、期間、範圍、類型"""
    out: dict = {}
    fields = split_fields(text)
    get = lambda *keys: next((v for k, v in fields if any(x in k for x in keys)), "")
    # 類型
    kind = get("併購種類")
    if kind:
        out["deal_kind"] = kind.split()[0][:20]
    # 被收購公司 / 收購方
    tgt = get("被收購有價證券之公開發行公司名稱", "被收購公司名稱")
    party = get("參與併購公司名稱")
    if tgt:
        out["target_company"] = _company(tgt)
    if party:
        m = re.search(r"(?:被收購公司|合併消滅公司|消滅公司|標的公司)\s*[:：]\s*(.+?)(?=\s*(?:收購公司|存續公司|合併存續|$))", party)
        if m:
            out["target_company"] = _company(m.group(1))
        m = re.search(r"(?:^|\s)(?:收購公司|合併存續公司|存續公司)\s*[:：]\s*(.+?)(?=\s*(?:被收購|消滅|合併消滅|$))", party)
        if m:
            out["acquirer"] = short_company(_company(m.group(1)))
    m = re.search(r"代(?:重要)?子公司(.{2,20}?)(?:\(股\)|（股）)?(?:股份有限)?公司公告", subject or "")
    if m and "acquirer" not in out:
        out["acquirer"] = short_company(m.group(1))
    m = re.search(r"接獲(.{2,30}?)(?:股份有限公司|公司)?公開收購", (subject or "") + " " + (text or "")[:600])
    if m and "acquirer" not in out:
        out["acquirer"] = short_company(m.group(1))
    # 價格（公開收購第 5 欄／併購第 7、10、11 欄）
    price_txt = get("有價證券價格", "收購價格", "收購對價") or get("對價條件", "併購目的及條件") or get("對價種類")
    m = _CASH.search(price_txt)
    if m:
        out["offer_price"] = float(m.group(1).replace(",", ""))
    m = _RATIO.search(price_txt)
    if m:
        out["stock_company"] = short_company(m.group(1))
        out["stock_ratio"] = float(m.group(2))
    if out.get("stock_ratio") and out.get("offer_price"):
        out["consideration"] = "現金＋換股"
    elif out.get("stock_ratio"):
        out["consideration"] = "換股"
    elif out.get("offer_price") or "現金為對價" in (text or ""):
        out["consideration"] = "現金"
    # 數量
    qty = get("有價證券數量")
    if qty:
        m = re.search(r"預定收購數量[為:：\s]*([0-9][0-9,]*)\s*股", qty) or re.search(r"([0-9][0-9,]*)\s*股", qty)
        if m:
            out["max_shares"] = float(m.group(1).replace(",", ""))
        m = re.search(r"([0-9][0-9,]*)\s*股[^。；]{0,80}?最低收購數量", qty)
        if m:
            out["min_shares"] = float(m.group(1).replace(",", ""))
        m = re.search(r"已發行股份總數[^。]{0,60}?之\s*([0-9]+(?:\.[0-9]+)?)\s*%", qty)
        if m:
            out["offer_pct"] = float(m.group(1))
    # 期間：延長後的期間優先
    per = get("延長公開收購期間") or get("公開收購期間", "收購期間")
    ds = _dates(per)
    if len(ds) >= 2:
        out["period_start"], out["period_end"] = ds[0], ds[-1]
    else:
        done = _dates(get("預定完成日程"))
        if done:
            out["period_end"] = done[0]
    # 範圍
    plan = get("併購完成後之計畫") + " " + get("其他與併購相關")
    if re.search(r"100\s*%\s*持股|百分之百|下市|下櫃|全部股份|全數收購", plan + " " + (text or "")[:1500]):
        out["scope"] = "完全收購"
    elif out.get("min_shares") or (out.get("offer_pct") and out["offer_pct"] < 100):
        out["scope"] = "部分收購"
    return out
