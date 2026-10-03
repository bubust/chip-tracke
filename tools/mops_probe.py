"""臨時診斷：測試 MOPS 各種查詢方式哪個能用（GitHub Actions 上跑，看 log）"""
import re, json, time
import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def show(tag, r):
    t = r.text
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))
    print(f"== {tag}: HTTP {r.status_code} len={len(t)} 主旨={'主旨' in t} 公開收購={'公開收購' in t} 安全性={'安全性考量' in t}")
    print("   ", txt[:260])


def run(tag, fn):
    try:
        show(tag, fn())
    except Exception as e:
        print(f"== {tag}: EXC {type(e).__name__}: {e}")
    time.sleep(3)


for host in ("https://mopsov.twse.com.tw", "https://mops.twse.com.tw"):
    c = httpx.Client(timeout=30, verify=False, follow_redirects=True, headers={"User-Agent": UA})
    base = f"{host}/mops/web"
    run(f"{host} 庫藏股 t35sc09（對照組）", lambda: c.post(f"{base}/ajax_t35sc09", data={
        "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": "sii", "d1": "1150901", "d2": "1151002", "RD": "1"},
        headers={"Referer": f"{base}/t35sc09"}))
    run(f"{host} GET t05st02 頁面", lambda: c.get(f"{base}/t05st02"))
    variants = {
        "A 原本": {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": "all", "year": "115", "month": "10", "day": "02"},
        "B 不補零": {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": "all", "year": "115", "month": "10", "day": "2"},
        "C step00": {"encodeURIComponent": "1", "step": "1", "step00": "0", "firstin": "1", "off": "1", "TYPEK": "all", "year": "115", "month": "10", "day": "02"},
        "D 最少": {"step": "1", "firstin": "1", "TYPEK": "all", "year": "115", "month": "10", "day": "02"},
        "E co_id": {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": "all", "year": "115", "month": "10", "day": "02", "co_id": "", "keyword4": "", "code1": "", "TYPEK2": ""},
    }
    for name, form in variants.items():
        run(f"{host} t05st02 {name}", lambda form=form: c.post(f"{base}/ajax_t05st02", data=form, headers={"Referer": f"{base}/t05st02", "X-Requested-With": "XMLHttpRequest"}))
    run(f"{host} t05sr01_1 今日", lambda: c.post(f"{base}/ajax_t05sr01_1", data={"encodeURIComponent": "1", "step": "0", "firstin": "1", "off": "1", "TYPEK": "all"}, headers={"Referer": f"{base}/t05sr01_1"}))
    # 公開收購相關頁面（猜代號）
    for page in ("t146sb05", "t146sb10", "t178sb01", "t178sb02", "t05st01"):
        run(f"{host} {page} GET", lambda page=page: c.get(f"{base}/{page}"))

# 新版 MOPS JSON API
c = httpx.Client(timeout=30, verify=False, follow_redirects=True, headers={"User-Agent": UA, "Content-Type": "application/json"})
for path, body in (("t05st02", {"year": "115", "month": "10", "day": "02"}),
                   ("t05st02", {"year": "2026", "month": "10", "day": "02"}),
                   ("t05sr01_1", {}), ("t35sc09", {"marketKind": "sii"})):
    run(f"新版 API /mops/api/{path} {json.dumps(body)}", lambda path=path, body=body: c.post(f"https://mops.twse.com.tw/mops/api/{path}", json=body,
        headers={"Referer": "https://mops.twse.com.tw/mops/", "Origin": "https://mops.twse.com.tw"}))
