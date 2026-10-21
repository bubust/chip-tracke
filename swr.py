"""過期先回舊資料、背景更新（stale-while-revalidate，PLAN-B77 C3／C4／E6）

處置股第一次打開要 14 秒、可轉債清單過期後第一個人要等：改成
- 有舊資料：馬上回舊的；過期的話開一條背景執行緒更新（同時只有一條，單飛）
- 完全沒有資料（剛開機、沒存檔）：當場算（第一個人等，之後就快了）
- persist：結果存檔，重開機後馬上有
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


class SWR:
    def __init__(self, name: str, ttl: float, builder: Callable[[], object], persist: Optional[Path] = None):
        self.name, self.ttl, self.builder, self.persist = name, ttl, builder, persist
        self.data = None
        self.t = 0.0
        self._lock = threading.Lock()
        self.error: Optional[str] = None
        if persist:
            try:
                saved = json.loads(Path(persist).read_text(encoding="utf-8"))
                self.data, self.t = saved.get("data"), float(saved.get("t") or 0)
            except Exception:
                pass

    def fresh(self) -> bool:
        return self.data is not None and time.time() - self.t < self.ttl

    def get(self, force: bool = False):
        if force or self.data is None:
            return self.refresh()
        if not self.fresh():
            self.refresh_async()
        return self.data

    def refresh(self):
        """同步重算；別人正在算就等他算完、直接用他的結果"""
        t_call = time.time()
        with self._lock:
            if self.data is not None and self.t >= t_call:      # 等鎖的時候別人剛算好
                return self.data
            data = self.builder()
            self.set(data)
            return data

    def set(self, data):
        self.data, self.t, self.error = data, time.time(), None
        if self.persist:
            try:
                import jobs
                jobs.write_json_atomic(Path(self.persist), {"t": self.t, "data": data})
            except Exception as e:
                log.warning(f"[swr] {self.name} 存檔失敗：{e}")

    def refresh_async(self) -> bool:
        if self._lock.locked():
            return False

        def _bg():
            try:
                self.refresh()
            except Exception as e:      # noqa: BLE001
                self.error = f"{type(e).__name__}: {e}"[:200]
                log.warning(f"[swr] {self.name} 背景更新失敗：{e}")
        threading.Thread(target=_bg, daemon=True, name=f"swr-{self.name}").start()
        return True

    def invalidate(self):
        self.t = 0.0
