"""PLAN-B91 研究輸出：results.json → REPORT.md＋repo 根目錄 tail_research.json（網站 tail_market.load_research 讀）
用法：python b91_report.py（run.py 跑完會自動呼叫）"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
YEARS = ('2021', '2022', '2023', '2024', '2025', '2026')
ROOT = os.path.dirname(os.path.dirname(HERE))


def _p(v):
    return '—' if v is None else f'{v * 100:.1f}%'


def _s(x):
    x = x or {}
    mean = '—' if x.get('mean') is None else f"{x['mean'] * 100:+.2f}%"
    return f"{_p(x.get('win'))}／{mean}（{x.get('n', 0)}）"


def _ok(side, o, bo, rule):
    if o.get('n', 0) < rule['oos_n'] or not bo.get('n'):
        return False
    if side == 'good':
        return o['win'] >= bo['win'] + rule['gap'] and o['mean'] > bo['mean']
    return o['win'] <= bo['win'] - rule['gap'] and o['mean'] < bo['mean']


def write_outputs(res):
    q1, q2, rule = res['q1'], res['q2'], res['q2']['rule']
    IS, OOS = res['is'], res['oos']
    passed = [r for r in res['rules'] if r['pass']]
    concl = '；'.join(f"{'✅ 比較好' if r['side'] == 'good' else '⚠ 比較差'}：{r['family_name']}＝{r['bucket']}" for r in passed) \
        or '5 年回測沒找到明顯比較好或比較差的盤勢'
    a, b, rb = q1['A']['oos'], q1['B']['oos'], q1['rand_B']['oos']
    better = b.get('mean', -9) > a.get('mean', -9) and b.get('win', 0) >= a.get('win', 1)
    notes = [f"日線結構：全部假跌破樣本外 {_s(a)} → 加結構 {_s(b)}；同一天隨機挑結構合格的 {_s(rb)}"
             + ("（加結構比較好一點）" if better else "（加結構沒有明顯更好）")]
    rc = res.get('q3') or {}
    if rc.get('prod_n'):
        notes.append(f"正式站 10/20～11/03 的 {rc['prod_n']} 筆（13:10 清單）：收盤時假跌破還成立 {_p(rc.get('close_signal_rate'))}；"
                     f"13:10 價比收盤平均 {rc['price_diff_mean'] * 100:+.2f}%（絕對值平均 {rc['price_diff_abs_mean'] * 100:.2f}%）；"
                     f"日線結構合格 {_p(rc.get('struct_ok_share_prod'))}")
    sens = res.get('sensitivity')
    if sens:
        flip = [f"{r['family_name']}＝{r['bucket']}" for r, s2 in zip(res['rules'], sens['rows'])
                if r['pass'] and not _ok(r['side'], s2['oos'], s2['base_oos'], rule)]
        notes.append(f"敏感度：進場價往不利方向調 {sens['bump'] * 100:.2f}% 重算，" + (f"這些會不通過：{'、'.join(flip)}" if flip else "通過的結論不變"))
    fam = q2['families']
    worst = sorted(((fk, bk, x) for fk, f in fam.items() if fk != 'M9' for bk, x in f['buckets'].items() if (x['oos'].get('n') or 0) >= 100),
                   key=lambda z: z[2]['oos']['mean'])[:2]
    if worst:
        notes.append('樣本外最差的盤勢：' + '、'.join(f"{fam[fk]['name']}＝{bk}（樣本外 {_s(x['oos'])}、但樣本內 {_s(x['is'])}）" for fk, bk, x in worst)
                     + '——好壞會隨時期翻轉、同盤勢隨機挑股票也一樣差＝整個市場的事，不能當成規則')
    m4 = (fam.get('M4') or {}).get('buckets', {}).get('盤整')
    if m4:
        ys = [(y, v) for y, v in m4['years'].items() if (v or {}).get('n', 0) >= 20]
        neg = [y for y, v in ys if v['mean'] < 0]
        pos = [y for y, v in ys if v['mean'] >= 0]
        notes.append(f"事後觀察（沒經過檢定、不能當規則，只當提醒）：大盤日線「盤整」（不是多頭也不是空頭）{len(neg)}／{len(ys)} 年每筆平均是負的"
                     + (f"，只有 {'、'.join(pos)} 例外" if pos else '') + "；樣本內被 2023 大多頭拉高，所以事先定好的挑格沒挑到它")
    if rc.get('prod_by_struct'):
        pb = rc['prod_by_struct']
        notes.append(f"正式站 98 筆實際（11/03）：日線結構合格 {_s(pb.get('ok'))}、不合格 {_s(pb.get('ng'))}")
    notes.append(f"母體＝13:15 假跌破＋日線結構合格（樣本外 {_s(q2['base']['oos'])}）；每族樣本內挑最好／最差一格、樣本外驗一次，"
                 f"{len(res['rules'])} 個檢定 BH 校正 q＜{rule['q']}（各族互相相關，BH 在正相依下仍有效）；種子 {res['seed']}")
    out = {'generated': res['generated'], 'data': res['data'], 'is': IS, 'oos': OOS, 'base': q2['base'], 'q1': q1, 'rules': res['rules'],
           'families': q2['families'], 'recent': rc, 'notes': notes, 'conclusion': concl, 'sensitivity': sens,
           'verify_sfbd': res['verify_sfbd'], 'market_meta': res['market_meta'], 'struct_unknown_share': res['struct_unknown_share']}
    with open(os.path.join(ROOT, 'tail_research.json'), 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    v = res['verify_sfbd']
    L = ["# PLAN-B91 研究：尾盤 13:15 假跌破＋日線結構＋什麼大盤盤勢進場比較好", '',
         f"- 產生 {res['generated']}；資料 {res['data']['from']}～{res['data']['to']}；樣本內 {IS[0]}～{IS[1]}、樣本外 {OOS[0]}～{OOS[1]}",
         "- 進場＝訊號日收盤（代替 13:15 價），停損 8%（隔天起盤中觸價）、停利 25%、上限 250 天，扣成本、含除權息；同一檔持有中不重複進場",
         f"- S_FBD 向量化跟 B82 逐日呼叫網站函式比對：{v['both']}／{v['ref']} 一致（一致率 {v['agree'] * 100:.2f}%）",
         f"- 大盤 13:15：證交所每 5 秒指數 {res['market_meta']['tx_days']} 天（分 K 彙總的收盤跟 wave.db 日 K 最大差 {res['market_meta']['close_check_max']}）",
         f"- 波段點不夠（結構不明）占全部訊號 {_p(res['struct_unknown_share'])}；不合格原因 {res['struct_fail_reasons']}", '',
         f"## 結論：{concl}", '', *[f"- {n}" for n in notes], '',
         '## Q1 日線結構（低不破低、高過高）有沒有幫助', '', '| | 樣本內 勝率／平均（筆） | 樣本外 |', '|---|---|---|',
         f"| 全部假跌破 | {_s(q1['A']['is'])} | {_s(q1['A']['oos'])} |",
         f"| ＋結構（k=3，網站用） | {_s(q1['B']['is'])} | {_s(q1['B']['oos'])} |",
         f"| ＋結構 k=5（參考） | {_s(q1['B_k5']['is'])} | {_s(q1['B_k5']['oos'])} |",
         f"| ＋結構 k=8（參考） | {_s(q1['B_k8']['is'])} | {_s(q1['B_k8']['oos'])} |",
         f"| 隨機（同一天、全部） | | {_s(q1['rand_A']['oos'])} |", f"| 隨機（同一天、結構合格） | | {_s(q1['rand_B']['oos'])} |", '',
         '各年（全部 → ＋結構）：' + '、'.join(f"{y} {_s(q1['years_A'][y])} → {_s(q1['years_B'][y])}" for y in q1['years_A']), '',
         '## Q2 盤勢（母體＝＋結構）', '', '| 族 | 盤勢 | 樣本內 | 樣本外 | 隨機挑（樣本外） |', '|---|---|---|---|---|']
    for fk, f in q2['families'].items():
        for bk, x in f['buckets'].items():
            mark = ''
            for r in res['rules']:
                if r['family'] == fk and r['bucket'] == bk:
                    mark = (' ✅' if r['side'] == 'good' else ' ⚠') if r['pass'] else (' （好✗）' if r['side'] == 'good' else ' （差✗）')
            L.append(f"| {f['name']} | {bk}{mark} | {_s(x['is'])} | {_s(x['oos'])} | {_s(x['rand_oos'])} |")
    L += ['', '### 檢定（樣本內挑的格，樣本外驗一次）', '', '| 族 | 格 | 方向 | 樣本外 | p | BH 後 | 通過 |', '|---|---|---|---|---|---|---|']
    for r in res['rules']:
        L.append(f"| {r['family_name']} | {r['bucket']} | {'好' if r['side'] == 'good' else '差'} | {_s(r['oos'])} | {r['p']} | {r['p_adj']} | "
                 f"{'✅' if r['pass'] else '✗'} |")
    L += ['', '### 各盤勢逐年（勝率／每筆平均（筆）；看好壞會不會翻轉）', '', '| 族 | 盤勢 | ' + ' | '.join(YEARS) + ' |', '|---|---|' + '---|' * len(YEARS)]
    for fk in ('M4', 'M5', 'M9', 'M1'):
        f = q2['families'][fk]
        for bk, x in f['buckets'].items():
            L.append(f"| {f['name']} | {bk} | " + ' | '.join(_s(x['years'].get(y)) for y in YEARS) + ' |')
    if rc.get('prod_n'):
        pb = rc.get('prod_by_struct') or {}
        L += ['', '## Q3 最近 10/20～11/03', '', f"- {notes[1]}",
              f"- 正式站實際成績（11/03，停損的用停損價）：日線結構合格 {_s(pb.get('ok'))}、不合格 {_s(pb.get('ng'))}",
              f"- 研究收盤版每天訊號數：{rc['research_signals_by_day']}；結構合格：{rc['research_struct_ok_by_day']}",
              f"- 每天大盤：{json.dumps(rc['market_by_day'], ensure_ascii=False)}"]
    L += ['', '## 限制', '',
          '- 個股 13:15 歷史價格拿不到 → 用收盤價；結構用全天日 K（全天低點 ≤ 13:15 低點 → 研究比盤中嚴格）；大盤用真的 13:15 指數',
          '- 13:15～13:30 尾盤（含最後 5 分鐘集合競價）的漲跌算在研究的進場價裡，實際 13:15 買的價格會不一樣（見 Q3 的價差、敏感度）']
    with open(os.path.join(HERE, 'REPORT.md'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    return out


if __name__ == '__main__':
    write_outputs(json.load(open(os.path.join(HERE, 'results.json'), encoding='utf-8')))
