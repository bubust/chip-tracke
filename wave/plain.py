"""B76 波浪數法 → 白話（跟 regime-frontend/wave.js 的 plain() 同一套文字；多週期一覽、操作建議、AI 圓桌用）"""
from __future__ import annotations

from typing import Optional


def plain(c: Optional[dict]) -> Optional[dict]:
    """engine 的數法 {kind, dir, current} → {title, meaning}；沒有或對不到 → None"""
    if not c:
        return None
    cur, up = str(c.get("current") or ""), (c.get("dir") or 0) > 0
    if c.get("kind") == "impulse" and cur in ("1", "2", "3", "4", "5"):
        if cur in ("1", "3", "5"):
            m = {"1": "新一波的第一段，還需要後面走勢確認", "3": "通常是整波裡最強、最長的一段",
                 "5": "這一波的最後一段，走完通常會有比較大的修正"}[cur]
            return {"title": f"上漲波・第 {cur} 段上漲中" if up else f"下跌波・第 {cur} 段下跌中", "meaning": m}
        return {"title": f"上漲途中的回檔（第 {cur} 段）" if up else f"下跌途中的反彈（第 {cur} 段）",
                "meaning": f"回檔走完，照規則後面還有第 {int(cur) + 1} 段上漲" if up else f"反彈走完，照規則後面還有第 {int(cur) + 1} 段下跌"}
    corr_down = (c.get("kind") == "impulse" and up) or (c.get("kind") == "correction" and not up)
    T = ({"A": ("漲多後的修正・第一段下跌（A）", "修正通常走「跌－彈－跌」三段，這是第一段"),
          "B": ("修正中的反彈（B）", "反彈走完，照規則還有最後一段下跌（C）"),
          "C": ("修正的最後一段下跌（C）", "這段跌完，修正可能結束、重新開始上漲")} if corr_down else
         {"A": ("跌深後的反彈・第一段（A）", "跌深反彈通常走「彈－回－彈」三段，這是第一段"),
          "B": ("反彈中的回落（B）", "回落走完，照規則還有最後一段反彈（C）"),
          "C": ("反彈的最後一段（C）", "這段反彈走完，可能再往下")})
    if cur not in T:
        return None
    return {"title": T[cur][0], "meaning": T[cur][1]}
