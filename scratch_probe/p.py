import requests, json
s=requests.Session(); s.headers["User-Agent"]="Mozilla/5.0"
def show(tag,r):
    try:
        j=r.json(); print(tag,r.status_code,json.dumps(j,ensure_ascii=False)[:1200])
    except Exception: print(tag,r.status_code,r.text[:300])
show("T86",s.get("https://www.twse.com.tw/rwd/zh/fund/T86",params={"date":"20261002","selectType":"ALLBUT0999","response":"json"},timeout=30))
for u,d in [("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",{"date":"2026/10/02","type":"Daily","sect":"EW","response":"json"}),
            ("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",{"date":"2026/10/02","response":"json"}),
            ("https://www.tpex.org.tw/www/zh-tw/insti/sitcDetail",{"date":"2026/10/02","response":"json"})]:
    show("TPEX "+u.split('/')[-1],s.post(u,data=d,timeout=30))
show("TPEXOPEN",s.get("https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",timeout=30))
r=s.get("https://openapi.tdcc.com.tw/v1/opendata/1-5",timeout=60); j=r.json(); print("TDCC",len(j),j[:3]); print([x for x in j if x.get(list(x.keys())[1],'').strip()=='2330'])
