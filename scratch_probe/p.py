import requests
for i in range(6):
    r=requests.get("https://qiangni-tactics.fly.dev/",timeout=60,headers={"User-Agent":"Mozilla/5.0 (iPhone)"})
    t=r.text
    print(i, r.status_code, len(t), "machine:", r.headers.get("fly-request-id","")[-12:], r.headers.get("cache-control"),
          "pushMarketRank" in t, "籌碼強買" in t, "chart-link-btn" in t, "notes.js?v=" in t and t.split("notes.js?v=")[1][:10])
for u in ["https://chip-tracker-tw.fly.dev/"]:
    try:
        r=requests.get(u,timeout=60); print("OLD", r.status_code, len(r.text), "pushMarketRank" in r.text)
    except Exception as e: print("OLD ERR", e)
