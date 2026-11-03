"""B91 融資維持率改一年（MAINT_DAYS 130 → 260）：_compute_all 記憶體／秒數（tracemalloc 尖峰），研究資料庫 data/margin_course.db
用法：python margin_mem.py"""
import os, sys, time, tracemalloc
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import chip_course as CC
import margin_maint as MM

CC.DB_PATH = Path(HERE) / 'data' / 'margin_course.db'
for n in (130, 260):
    MM._ALL.clear()
    tracemalloc.start()
    t0 = time.time()
    asof, est = MM._compute_all(n)
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    conf = sorted(e['conf'] for e in est.values())
    print(f'{n} 天：{len(est)} 檔、{time.time() - t0:.1f} 秒、尖峰 {peak / 1e6:.0f} MB、可信度中位數 {conf[len(conf) // 2]:.3f}、'
          f'≥90% {sum(c >= .9 for c in conf) / len(conf):.0%}、校正 {MM._ALL["v"][3]}')
