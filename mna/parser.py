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
_EXCLUDE = re.compile(r"合併營收|合併財務|合併報表|合併損益|合併資產|子公司.*營收|自結|澄清媒體")
_PRICE = re.compile(r"每股(?:新[臺台]幣|現金)?\s*([0-9]+(?:\.[0-9]+)?)\s*元")
_SHARES = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(萬)?股")
_PERIOD = re.compile(r"(\d{2,4}[/.年]\d{1,2}[/.月]\d{1,2}日?)\s*(?:至|~|～|－|-)\s*(\d{2,4}[/.年]\d{1,2}[/.月]\d{1,2}日?)")
_PCT = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
_ACQ = re.compile(r"(?:代子公司|本公司)?(?:擬)?由?\s*([^\s，,、]{2,20}?(?:股份有限公司|公司|投資|基金|集團))\s*(?:擬)?(?:對|公開收購|收購)")


def classify(subject: str) -> Optional[str]:
    s = subject or ""
    if _EXCLUDE.search(s):
        return None
    for name, rx in _TYPES:
        if rx.search(s):
            return name
    return None


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
            rec.update(extract(subject))
            out.append(rec)
    return out
