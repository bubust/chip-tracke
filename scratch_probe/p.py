import requests, json
s=requests.Session(); s.headers["User-Agent"]="Mozilla/5.0"
def show(tag,fn):
    try:
        r=fn()
        try: print(tag,r.status_code,json.dumps(r.json(),ensure_ascii=False)[:1500])
        except Exception: print(tag,r.status_code,r.text[:300])
    except Exception as e: print(tag,"ERR",type(e).__name__,str(e)[:200])
show("T86",lambda: s.get("https://www.twse.com.tw/rwd/zh/fund/T86",params={"date":"20261002","selectType":"ALLBUT0999","response":"json"},timeout=40))
for u,d in [("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",{"date":"2026/10/02","type":"Daily","sect":"EW","response":"json"}),
            ("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade",{"date":"2026/10/02","sect":"AL","response":"json"}),
            ("https://www.tpex.org.tw/www/zh-tw/insti/sitcStat",{"date":"2026/10/02","response":"json"})]:
    show("TPEX "+str(d),lambda: s.post(u,data=d,timeout=40))
show("TPEXOPEN",lambda: s.get("https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",timeout=60))
def tdcc():
    r=s.get("https://openapi.tdcc.com.tw/v1/opendata/1-5",timeout=90); j=r.json(); print("TDCC",len(j),j[:2]); print([x for x in j if list(x.values())[1].strip()=='2330'])
    return r
try: tdcc()
except Exception as e: print("TDCC ERR",e)
