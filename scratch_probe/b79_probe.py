"""B79 暫時檢查：跑 research/wave/b79_nest_research.py（需要 Yahoo）"""
import os, runpy, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "wave"))
runpy.run_path(os.path.join(ROOT, "research", "wave", "b79_nest_research.py"), run_name="__main__")
