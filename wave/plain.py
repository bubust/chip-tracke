"""B76 波浪數法 → 白話（跟 regime-frontend/wave.js 的 plain() 同一套文字；多週期一覽、操作建議、AI 圓桌用）"""
from __future__ import annotations

from typing import Optional


def _combo(cur: str, up: bool) -> Optional[tuple]:
    """B78 複合修正 W-X-Y（-X-Z）。up＝第一段往上（跌深後的複合反彈）；否則是漲多後的複合修正"""
    dn, rb = ("下跌", "反彈") if not up else ("反彈", "回落")
    head = "複合修正" if not up else "複合反彈"
    three = "「跌－彈－跌」" if not up else "「彈－回－彈」"
    end = "修正可能結束、重新開始上漲" if not up else "可能再往下"
    T = {"X": (f"{head}中的{rb}（X 浪）", f"第一組{three}（W）走完了，這段是中間的連接；照規則後面還有第二組（Y）"),
         "Ya": (f"{head}・第二組的第一段{dn}（Y 的 a）", "修正拉長成兩組三段（W-X-Y），這是第二組的開始"),
         "Yb": (f"{head}・第二組中的{rb}（Y 的 b）", f"{rb}走完，照規則還有最後一段{dn}（Y 的 c）"),
         "Y": (f"{head}的最後一段{dn}（Y 的 c）", f"這段走完，兩組修正（W-X-Y）{end}；也可能再接一個 X 變成三組"),
         "X2": (f"{head}中的第二次{rb}（第二個 X）", "已經走了兩組三段（W、Y），這段連接到第三組（Z）；三組是上限"),
         "Za": (f"{head}・第三組的第一段{dn}（Z 的 a）", "修正拉長成三組三段（W-X-Y-X-Z），這是最後一組的開始"),
         "Zb": (f"{head}・第三組中的{rb}（Z 的 b）", f"{rb}走完，照規則還有最後一段{dn}（Z 的 c）"),
         "Z": (f"{head}的最後一段{dn}（Z 的 c）", f"三組是修正的上限，這段走完{end}")}
    return T.get(cur)


def _triangle(cur: str, up: bool, con: bool) -> Optional[tuple]:
    """B78 三角形：up＝A 往上（下跌途中的盤整，之後往下）；否則是漲多後的盤整，之後往上"""
    shape = "收斂" if con else "擴散"
    way = "往上" if not up else "往下"
    swing = "上下震盪越來越小" if con else "上下震盪越來越大"
    T = {"D": (f"{shape}三角形整理・第 4 段（D）", f"盤整走五段（A-B-C-D-E）{swing}，後面還有 E；走完通常{way}突破（順著原本的方向）"),
         "E": (f"{shape}三角形整理・最後一段（E）", f"E 走完通常{way}突破，幅度大約是三角形最寬那段（A）")}
    return T.get(cur)


def _diagonal(cur: str, up: bool) -> Optional[tuple]:
    """B78 楔形（傾斜三角形）：推進力道變弱的五段，第 4 段可以跌進第 1 段的價格區"""
    if cur == "4":
        return (("上升楔形・第 4 段回檔" if up else "下跌楔形・第 4 段反彈"),
                ("越漲越弱的五段（第 4 段可以跌進第 1 段的價格區），後面還有第 5 段上漲；照教科書，楔形走完常快速跌回起點附近" if up else
                 "越跌越弱的五段（第 4 段可以彈進第 1 段的價格區），後面還有第 5 段下跌；照教科書，楔形走完常快速彈回起點附近"))
    if cur == "5":
        return (("上升楔形・最後一段（第 5 段）上漲" if up else "下跌楔形・最後一段（第 5 段）下跌"),
                ("楔形的最後一段；照教科書，走完常快速跌回楔形起點附近" if up else "楔形的最後一段；照教科書，走完常快速彈回楔形起點附近"))
    return None


def plain(c: Optional[dict]) -> Optional[dict]:
    """engine 的數法 {kind, dir, current} → {title, meaning}；沒有或對不到 → None"""
    if not c:
        return None
    cur, up = str(c.get("current") or ""), (c.get("dir") or 0) > 0
    kind = c.get("kind")
    if kind in ("combo", "triangle", "diagonal"):
        r = (_combo(cur, up) if kind == "combo" else
             _triangle(cur, up, c.get("corr_kind") != "expanding") if kind == "triangle" else _diagonal(cur, up))
        return None if not r else {"title": r[0], "meaning": r[1]}
    if kind == "impulse" and cur in ("1", "2", "3", "4", "5"):
        if cur in ("1", "3", "5"):
            m = {"1": "新一波的第一段，還需要後面走勢確認", "3": "通常是整波裡最強、最長的一段",
                 "5": "這一波的最後一段，走完通常會有比較大的修正"}[cur]
            return {"title": f"上漲波・第 {cur} 段上漲中" if up else f"下跌波・第 {cur} 段下跌中", "meaning": m}
        return {"title": f"上漲途中的回檔（第 {cur} 段）" if up else f"下跌途中的反彈（第 {cur} 段）",
                "meaning": f"回檔走完，照規則後面還有第 {int(cur) + 1} 段上漲" if up else f"反彈走完，照規則後面還有第 {int(cur) + 1} 段下跌"}
    corr_down = (kind == "impulse" and up) or (kind == "correction" and not up)
    T = ({"A": ("漲多後的修正・第一段下跌（A）", "修正通常走「跌－彈－跌」三段，這是第一段"),
          "B": ("修正中的反彈（B）", "反彈走完，照規則還有最後一段下跌（C）"),
          "C": ("修正的最後一段下跌（C）", "這段跌完，修正可能結束、重新開始上漲")} if corr_down else
         {"A": ("跌深後的反彈・第一段（A）", "跌深反彈通常走「彈－回－彈」三段，這是第一段"),
          "B": ("反彈中的回落（B）", "回落走完，照規則還有最後一段反彈（C）"),
          "C": ("反彈的最後一段（C）", "這段反彈走完，可能再往下")})
    if cur not in T:
        return None
    return {"title": T[cur][0], "meaning": T[cur][1]}
