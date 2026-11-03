// 🎯 尾盤追蹤分頁（dashboard 內嵌）。資料：/api/tail/*
// B91（2026-11-03）：13:15 清單；日線低不破低、高過高才「計入」，不合格的收在「不計入」；每個進場日標 13:15 大盤盤面＋研究判斷；🔬 大盤盤勢研究卡
'use strict';

let _tailRows = [];
let _tailLoaded = 0;
let _tailStop = 8;
let _tailRes = {};
let _tailNgAll = false;
const _tailSort = { watch: { col: 'entry_date', dir: -1 }, stop: { col: 'stop_date', dir: -1 } };
const _tE = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const _tN = (v, dp = 2) => v == null ? '—' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: dp, minimumFractionDigits: dp });
const _tP = v => v == null ? '—' : `<span style="color:${v > 0 ? '#ef4444' : v < 0 ? '#22c55e' : 'var(--muted)'}">${v > 0 ? '+' : ''}${Number(v).toFixed(2)}%</span>`;
const _tD = d => d ? String(d).slice(5).replace('-', '/') : '—';
const _tPct = v => v == null ? '—' : Math.round(v * 100) + '%';
const _tMean = v => v == null ? '—' : _tP(v * 100);
// 計入＝13:15 日線結構合格（還沒算的先算計入、標「計算中」）
const _tailIn = r => r.struct_ok !== 0;
const _TAIL_MK = { good: ['✅', '#ef4444'], bad: ['⚠', '#f59e0b'], neutral: ['—', 'var(--muted)'], nodata: ['缺', 'var(--muted)'] };
const _tailPassed = () => (_tailRes.rules || []).filter(r => r.pass);

function tailOnShow() {
  if (typeof _guideRemember === 'function') _guideRemember('tail-guide');
  if (Date.now() - _tailLoaded > 60 * 1000) tailLoad();
}

async function tailLoad(force) {
  const st = document.getElementById('tail-status');
  st.textContent = '更新中…';
  try {
    const r = await api('GET', '/api/tail/list');
    _tailRows = r.rows || [];
    _tailStop = r.stop_pct || 8;
    _tailRes = r.research || {};
    _tailLoaded = Date.now();
    document.getElementById('tail-stop').value = _tailStop;
    document.getElementById('tail-stop-lbl').textContent = _tailStop;
    const days = [...new Set(_tailRows.map(x => x.entry_date))].sort().reverse();
    const sel = document.getElementById('tail-day'), cur = sel.value;
    sel.innerHTML = '<option value="">全部</option>' + days.map(d => `<option value="${d}">${_tD(d)}</option>`).join('');
    if (days.includes(cur)) sel.value = cur;
    const bf = r.backfill && r.backfill.running ? '（舊資料補算中…）' : '';
    st.textContent = `更新 ${new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}${bf}`;
    tailRender();
    _tailResearch();
    if (force) toast('已更新報價');
  } catch (e) { st.textContent = '載入失敗：' + e.message; }
}

const _TAIL_COLS = {   // 報酬放第二欄：手機不用往右滑就看得到
  watch: [['股票', 'stock_id'], ['報酬', 'ret_pct'], ['現價', 'price'], ['進場價', 'entry_price'], ['加入日', 'entry_date'], ['天數', 'days'],
          ['最高漲幅', 'max_up_pct'], ['最大回檔', 'max_down_pct'], ['離停損', 'to_stop_pct'], ['MA10', 'ma10_now'], ['備註', 'note'], ['', '']],
  stop: [['股票', 'stock_id'], ['停損報酬', 'stop_ret_pct'], ['現在報酬', 'ret_pct'], ['停損日', 'stop_date'], ['停損價', 'stop_price'],
         ['進場價', 'entry_price'], ['加入日', 'entry_date'], ['現價', 'price'], ['最高漲幅', 'max_up_pct'], ['備註', 'note'], ['', '']],
};

function tailSortBy(zone, col) {
  const s = _tailSort[zone];
  if (s.col === col) s.dir = -s.dir; else { s.col = col; s.dir = ['stock_id', 'note'].includes(col) ? 1 : -1; }
  tailRender();
}

// 股名下的小字：來源・大盤 13:15・結構狀態
function _tailSub(r) {
  const m = r.mkt || {};
  const [ic, col] = _TAIL_MK[m.label] || _TAIL_MK.nodata;
  const chg = m.chg == null ? '' : `${m.chg > 0 ? '+' : ''}${(m.chg * 100).toFixed(1)}%`;
  const mk = m.label === 'nodata' ? '<span title="13:15 大盤抓不到，之後補算">大盤缺</span>'
    : `<span style="color:${col}" title="${_tE(m.desc || '')}${m.src === '補算' ? '（補算）' : ''}">大盤 ${_tE(chg)} ${_tE(m.M2 || '')} ${ic}</span>`;
  let tag = '';
  if (r.struct_ok == null) tag = '・<span title="日線結構還在算">結構計算中</span>';
  else if (r.struct_ok === 1 && r.struct_eod === 0) tag = '・<span style="color:#f59e0b" title="13:15 合格，收盤前低點又跌破前低（研究用收盤算，這種會被算成不合格）">收盤後跌破前低</span>';
  return `<span style="font-size:.72rem;color:var(--muted)">${_tE(String(r.source || '').replace(' 假跌破', ''))}・${mk}${tag}</span>`;
}

function _tailName(r) {
  return `<b class="link" style="color:var(--accent);cursor:pointer" onclick="tailChart('${_tE(r.stock_id)}')">${_tE(r.stock_id)}</b> ${_tE(r.name || '')}<br>${_tailSub(r)}`;
}

function _tailAct(r) {
  return `<span class="tail-act" style="display:inline-flex;gap:3px">
      ${typeof wlRowBtn === 'function' ? wlRowBtn(r.stock_id, `tailAddWl('${_tE(r.stock_id)}')`) : ''}
      <button class="btn sm ghost" title="編輯／移區" onclick="tailEdit(${r.id})">✏️</button>
      <button class="btn sm ghost" title="刪除" onclick="tailDel(${r.id})">🗑</button></span>`;
}

function _tailRow(zone, r) {
  const ma = r.ma10_now == null ? '—'
    : `${_tN(r.ma10_now)}<br><span style="font-size:.72rem;color:${r.above_ma10 ? '#ef4444' : '#22c55e'}">${r.above_ma10 ? '站上' : '跌破'}</span>`;
  const px = r.price == null ? '—' : `${_tN(r.price)}<br><span style="font-size:.72rem;color:var(--muted)">${_tD(r.price_date)}</span>`;
  const note = `<span style="white-space:normal;display:inline-block;max-width:160px;text-align:left">${_tE(r.note || '')}</span>`;
  if (zone === 'watch') {
    return `<tr><td class="l">${_tailName(r)}</td><td><b>${_tP(r.ret_pct)}</b></td><td>${px}</td><td>${_tN(r.entry_price)}</td><td>${_tD(r.entry_date)}</td><td>${r.days ?? '—'}</td>
      <td>${_tP(r.max_up_pct)}</td><td>${_tP(r.max_down_pct)}</td>
      <td title="現價離停損線 ${_tN(r.stop_level)} 還有多少">${r.to_stop_pct == null ? '—' : r.to_stop_pct.toFixed(1) + '%'}</td>
      <td>${ma}</td><td class="l">${note}</td><td>${_tailAct(r)}</td></tr>`;
  }
  return `<tr><td class="l">${_tailName(r)}</td><td><b>${_tP(r.stop_ret_pct)}</b></td><td>${_tP(r.ret_pct)}</td><td>${_tD(r.stop_date)}</td><td>${_tN(r.stop_price)}</td>
    <td>${_tN(r.entry_price)}</td><td>${_tD(r.entry_date)}</td><td>${px}</td><td>${_tP(r.max_up_pct)}</td>
    <td class="l">${note}</td><td>${_tailAct(r)}</td></tr>`;
}

function _tailTable(zone, rows) {
  if (!rows.length) return `<div class="muted" style="padding:16px;text-align:center">${zone === 'watch' ? '目前沒有觀察中的股票' : '目前沒有停損的股票'}</div>`;
  const s = _tailSort[zone];
  const v = r => r[s.col];
  rows = [...rows].sort((a, b) => { const x = v(a), y = v(b);
    if (x == null && y == null) return 0; if (x == null || x === '') return 1; if (y == null || y === '') return -1;
    return (typeof x === 'string' ? x.localeCompare(y) : x - y) * s.dir; });
  const head = _TAIL_COLS[zone].map(([lab, key]) => key
    ? `<th onclick="tailSortBy('${zone}','${key}')">${lab}${s.col === key ? (s.dir > 0 ? ' ▲' : ' ▼') : ''}</th>` : '<th></th>').join('');
  return `<div class="tbl-wrap" style="overflow-x:auto"><table class="tail-tbl mc"><thead><tr>${head}</tr></thead>
    <tbody>${rows.map(r => _tailRow(zone, r)).join('')}</tbody></table></div>`;
}

const _tailReal = r => r.zone === 'stop' ? r.stop_ret_pct : r.ret_pct;   // 停損的用停損價算
function _tailStat(rows) {
  const v = rows.map(_tailReal).filter(x => x != null);
  return { n: rows.length, avg: v.length ? v.reduce((a, b) => a + b, 0) / v.length : null, win: v.length ? v.filter(x => x > 0).length / v.length : null };
}

// 盤勢分組：研究有通過的規則 → ✅／⚠／—；沒有 → 大盤日線 多頭／盤整轉折／空頭（只描述；「盤整」跟「空頭」表現相反，不能混在一起）
function _tailGroupOf(r) {
  const m = r.mkt || {};
  if (_tailPassed().length) return m.label || 'nodata';
  if (m.label === 'nodata' || !m.M4) return 'nodata';
  return { '多頭': 'bull', '盤整': 'side', '空頭': 'bear' }[m.M4] || 'nodata';
}
const _TAIL_GN = { good: '✅ 適合盤勢', bad: '⚠ 不適合盤勢', neutral: '— 一般盤勢', nodata: '大盤資料缺',
                   bull: '大盤日線多頭', side: '大盤日線盤整', bear: '大盤日線空頭' };

function tailRender() {
  const day = document.getElementById('tail-day').value, q = document.getElementById('tail-q').value.trim();
  const mf = document.getElementById('tail-mkt').value;
  const rows0 = _tailRows.filter(r => (!day || r.entry_date === day) && (!q || r.stock_id.includes(q) || (r.name || '').includes(q)));
  const rows = rows0.filter(r => !mf || _tailGroupOf(r) === mf);
  const inRows = rows.filter(_tailIn), ngRows = rows.filter(r => !_tailIn(r));
  const watch = inRows.filter(r => r.zone !== 'stop'), stop = inRows.filter(r => r.zone === 'stop');
  document.getElementById('tail-watch').innerHTML = _tailTable('watch', watch);
  document.getElementById('tail-stop-zone').innerHTML = _tailTable('stop', stop);
  document.getElementById('tail-n-watch').textContent = watch.length;
  document.getElementById('tail-n-stop').textContent = stop.length;
  _tailNg(ngRows);
  if (typeof _mcLabelAll === 'function') ['tail-watch', 'tail-stop-zone', 'tail-ng-body'].forEach(id => _mcLabelAll(document.getElementById(id)));   // 手機卡片的小標（B82 D）
  // 統計：只算計入的（停損的用停損價算）
  const s = _tailStat(inRows), wAvg = watch.filter(r => r.ret_pct != null);
  document.getElementById('tail-summary').innerHTML = inRows.length ? `
    <div>計入<b>${inRows.length}</b> 檔</div>
    <div>觀察區平均<b>${wAvg.length ? _tP(wAvg.reduce((a, r) => a + r.ret_pct, 0) / wAvg.length) : '—'}</b></div>
    <div>停損<b>${stop.length}</b> 檔</div>
    <div title="停損的用停損價算，其他用現價">整體平均<b>${s.avg == null ? '—' : _tP(s.avg)}</b></div>
    <div title="目前報酬 > 0 的比例（停損的算輸）">賺錢比例<b>${s.win == null ? '—' : Math.round(s.win * 100) + '%'}</b></div>` : '<div>還沒有計入的股票</div>';
  // 分盤勢統計（計入的）
  const groups = {};
  inRows.forEach(r => { (groups[_tailGroupOf(r)] = groups[_tailGroupOf(r)] || []).push(r); });
  const order = _tailPassed().length ? ['good', 'neutral', 'bad', 'nodata'] : ['bull', 'side', 'bear', 'nodata'];
  const parts = order.filter(k => groups[k]).map(k => { const g = _tailStat(groups[k]);
    return `<span>${_TAIL_GN[k]} <b>${g.n}</b> 檔，平均 ${g.avg == null ? '—' : _tP(g.avg)}、賺錢 ${g.win == null ? '—' : Math.round(g.win * 100) + '%'}</span>`; });
  document.getElementById('tail-bymkt').innerHTML = parts.length ? `<span class="muted">依進場那天的大盤分開看：</span>${parts.join('<span class="muted">｜</span>')}` +
    (_tailPassed().length ? '' : '<span class="muted">（5 年回測沒有通過檢定的盤勢，先用大盤日線結構分組參考；事後看到「盤整」6 年有 5 年比較差，見最下面研究卡）</span>') : '';
}

function _tailNg(rows) {
  const box = document.getElementById('tail-ng');
  const s = _tailStat(rows);
  document.getElementById('tail-ng-sum').innerHTML = `🚫 不計入（日線不是低不破低、高過高）<b>${rows.length}</b> 檔${rows.length ? `，平均 ${s.avg == null ? '—' : _tP(s.avg)}、賺錢 ${s.win == null ? '—' : Math.round(s.win * 100) + '%'}` : ''}`;
  box.style.display = rows.length ? '' : 'none';
  rows = [...rows].sort((a, b) => (b.entry_date || '').localeCompare(a.entry_date || '') || a.stock_id.localeCompare(b.stock_id));
  const show = _tailNgAll ? rows : rows.slice(0, 30);
  const tr = show.map(r => `<tr><td class="l">${_tailName(r)}</td><td><b>${_tP(_tailReal(r))}</b></td>
      <td>${r.zone === 'stop' ? '<span style="color:#22c55e">停損</span>' : '觀察'}</td><td>${_tN(r.entry_price)}</td><td>${_tD(r.entry_date)}</td>
      <td class="l" style="white-space:normal;max-width:220px">${_tE((r.struct && r.struct.reason) || '')}</td><td>${_tailAct(r)}</td></tr>`).join('');
  document.getElementById('tail-ng-body').innerHTML = rows.length ? `<div class="tbl-wrap" style="overflow-x:auto"><table class="tail-tbl mc"><thead><tr>
      <th>股票</th><th title="停損的用停損價算">報酬</th><th>狀態</th><th>進場價</th><th>加入日</th><th>為什麼不計入</th><th></th></tr></thead><tbody>${tr}</tbody></table></div>` +
    (rows.length > 30 ? `<div style="text-align:center;margin-top:6px"><button class="btn sm ghost" onclick="_tailNgAll=!_tailNgAll;tailRender()">${_tailNgAll ? '只看最近 30 筆' : `顯示全部 ${rows.length} 筆`}</button></div>` : '') : '';
}

// 🔬 大盤盤勢研究卡（tail_research.json）
function _tailResearch() {
  const el = document.getElementById('tail-research');
  const R = _tailRes;
  if (!R || !R.families) { el.style.display = 'none'; return; }
  el.style.display = '';
  const pass = _tailPassed();
  const concl = R.conclusion || (pass.length
    ? pass.map(r => `${r.side === 'good' ? '✅ 比較好' : '⚠ 比較差'}：${r.family_name}＝${r.bucket}`).join('；')
    : '5 年回測沒找到明顯比較好或比較差的盤勢');
  document.getElementById('tail-research-sum').innerHTML = `🔬 大盤盤勢研究：${_tE(concl)}`;
  const q1 = R.q1 || {}, A = (q1.A || {}).oos || {}, B = (q1.B || {}).oos || {}, rB = (q1.rand_B || {}).oos || {};
  const base = (R.base || {}).oos || B;
  const pick = {};
  (R.rules || []).forEach(r => { pick[r.family + '|' + r.bucket] = r; });
  const fam = Object.entries(R.families).map(([fk, f]) => {
    const cells = Object.entries(f.buckets || {}).map(([b, x]) => {
      const o = x.oos || {}, r = pick[fk + '|' + b];
      const mark = r ? (r.pass ? (r.side === 'good' ? ' ✅' : ' ⚠') : (r.side === 'good' ? ' <span class="muted" title="樣本內挑出來最好的，樣本外沒通過">（好✗）</span>' : ' <span class="muted" title="樣本內挑出來最差的，樣本外沒通過">（差✗）</span>')) : '';
      return `<td class="l">${_tE(b)}${mark}</td><td>${o.n || 0}</td><td>${_tPct(o.win)}</td><td>${_tMean(o.mean)}</td><td class="muted">${_tPct((x.rand_oos || {}).win)}</td>`;
    });
    // 不用 rowspan：tail-tbl 第一欄是固定在左邊的，合併儲存格會讓下一列錯位
    return cells.map((c, i) => `<tr${i === 0 ? ' style="border-top:2px solid #30363d"' : ''}><td class="l">${i === 0 ? `<b>${_tE(f.name)}</b>` : ''}</td>${c}</tr>`).join('');
  }).join('');
  const notes = (R.notes || []).map(n => `<li>${_tE(n)}</li>`).join('');
  const eod = R.eod_check ? `<li>${_tE(R.eod_check)}</li>` : '';
  document.getElementById('tail-research-body').innerHTML = `
    <div style="font-size:.86rem;line-height:1.7">
      <div>📌 <b>怎麼看</b>：同一套「13:15 假跌破＋日線結構合格」在不同大盤狀況下，5 年回測（樣本外 ${_tE((R.oos || [])[0] || '')}～${_tE((R.oos || [])[1] || '')}）的勝率和每筆平均報酬（停損 8%、停利 25%、扣成本）。
        <b>✅／⚠</b>＝樣本內挑出來、樣本外也通過檢定（勝率差 ≥ 5 個百分點、多重檢定校正後顯著）；「好✗／差✗」＝樣本內看起來好／差，但樣本外沒通過＝不能當真。</div>
      <div style="margin-top:6px">🧱 <b>日線結構有沒有幫助</b>：全部假跌破樣本外勝率 ${_tPct(A.win)}、平均 ${_tMean(A.mean)}（${A.n || 0} 筆）→ 加上低不破低、高過高 ${_tPct(B.win)}、平均 ${_tMean(B.mean)}（${B.n || 0} 筆）；同一天隨便挑結構合格的股票：${_tPct(rB.win)}、${_tMean(rB.mean)}。</div>
      <div style="margin-top:6px">🌐 <b>各種盤勢</b>（母體：結構合格的假跌破，樣本外勝率 ${_tPct(base.win)}、平均 ${_tMean(base.mean)}）：</div>
      <div class="tbl-wrap" style="overflow-x:auto;margin-top:4px"><table class="tail-tbl"><thead><tr><th style="text-align:left">族</th><th style="text-align:left">盤勢</th><th>筆數</th><th>勝率</th><th>每筆平均</th><th title="同一天隨便挑股票、同樣出場">隨機挑勝率</th></tr></thead>
        <tbody>${fam}</tbody></table></div>
      <ul style="margin:8px 0 0 18px;font-size:.8rem;color:var(--muted)">${notes}${eod}
        <li>研究用收盤價代替 13:15 價、全天日 K 代替 13:15 的日 K（個股 13:15 歷史價格拿不到）；大盤用的是真的 13:15 指數。產生 ${_tE(R.generated || '')}</li></ul>
    </div>`;
}

async function tailSetStop(v) {
  try {
    await api('PUT', '/api/tail/settings/stop', { stop_pct: Number(v) });
    toast(`停損改成 ${v}%，重新判斷`);
    tailLoad();
  } catch (e) { toast(e.message, true); document.getElementById('tail-stop').value = _tailStop; }
}

function _tailModal(html) {
  const m = document.createElement('div');
  m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:10001;display:flex;align-items:center;justify-content:center;padding:16px';
  m.onclick = e => { if (e.target === m) m.remove(); };
  m.innerHTML = `<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;max-width:440px;width:100%;max-height:90vh;overflow:auto">${html}</div>`;
  document.body.appendChild(m);
  return m;
}
const _tailField = (id, label, val = '', type = 'text', ph = '') =>
  `<label style="display:flex;flex-direction:column;gap:3px;font-size:.78rem;color:var(--muted)">${label}
    <input id="${id}" type="${type}" value="${_tE(val)}" placeholder="${_tE(ph)}" style="font-size:16px"></label>`;

function tailAdd() {
  const today = new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10);
  const m = _tailModal(`<b>＋ 新增追蹤</b>
    <div style="display:grid;gap:8px;margin-top:10px">
      ${_tailField('ta-sid', '股票代號 *', '', 'text', '例 2330')}
      ${_tailField('ta-px', '進場價（空白＝用現價）', '', 'number')}
      ${_tailField('ta-date', '進場日', today, 'date')}
      ${_tailField('ta-note', '備註')}
    </div>
    <div class="muted" style="font-size:.72rem;margin-top:6px">日線結構、那天的大盤會自動補算（幾秒～幾分鐘）</div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:12px">
      <button class="btn sm ghost" data-x>取消</button><button class="btn sm" data-ok>新增</button></div>`);
  m.querySelector('[data-x]').onclick = () => m.remove();
  m.querySelector('[data-ok]').onclick = async () => {
    const g = id => document.getElementById(id).value.trim();
    if (!g('ta-sid')) { toast('請填股票代號', true); return; }
    try {
      await api('POST', '/api/tail', { stock_id: g('ta-sid'), entry_price: g('ta-px') ? Number(g('ta-px')) : null, entry_date: g('ta-date'), note: g('ta-note') });
      m.remove(); toast('已加入追蹤'); tailLoad();
    } catch (e) { toast(e.message, true); }
  };
}

function tailEdit(id) {
  const r = _tailRows.find(x => x.id === id);
  if (!r) return;
  const other = r.zone === 'stop' ? 'watch' : 'stop';
  const m = _tailModal(`<b>✏️ ${_tE(r.stock_id)} ${_tE(r.name || '')}</b>
    <div style="display:grid;gap:8px;margin-top:10px">
      ${_tailField('te-px', '進場價', r.entry_price, 'number')}
      ${_tailField('te-date', '進場日', r.entry_date, 'date')}
      ${_tailField('te-note', '備註', r.note || '')}
    </div>
    <div class="muted" style="font-size:.72rem;margin-top:6px">改進場價／日期會重新判斷停損（手動移過區的不動）；改日期會重算日線結構</div>
    <div style="display:flex;justify-content:space-between;gap:8px;margin-top:12px;flex-wrap:wrap">
      <button class="btn sm ghost" data-move style="color:${other === 'stop' ? '#22c55e' : 'var(--accent)'}">${other === 'stop' ? '🛑 移到停損區' : '👀 移回觀察區'}</button>
      <span style="display:flex;gap:8px"><button class="btn sm ghost" data-x>取消</button><button class="btn sm" data-ok>儲存</button></span></div>`);
  m.querySelector('[data-x]').onclick = () => m.remove();
  m.querySelector('[data-move]').onclick = async () => {
    try { await api('PUT', `/api/tail/${id}`, { zone: other }); m.remove(); tailLoad(); } catch (e) { toast(e.message, true); }
  };
  m.querySelector('[data-ok]').onclick = async () => {
    const g = k => document.getElementById(k).value.trim();
    const body = { note: g('te-note') };
    if (g('te-px') !== '' && Number(g('te-px')) !== r.entry_price) body.entry_price = Number(g('te-px'));   // 空白＝不改
    if (g('te-date') !== r.entry_date) body.entry_date = g('te-date');
    try { await api('PUT', `/api/tail/${id}`, body); m.remove(); toast('已儲存'); tailLoad(); } catch (e) { toast(e.message, true); }
  };
}

async function tailDel(id) {
  const r = _tailRows.find(x => x.id === id);
  if (!r || !confirm(`刪除 ${r.stock_id} ${r.name || ''}（${_tD(r.entry_date)} 加入）？`)) return;
  try { await api('DELETE', `/api/tail/${id}`); toast('已刪除'); tailLoad(); } catch (e) { toast(e.message, true); }
}

function tailImport() {
  const today = new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10);
  const m = _tailModal(`<b>📋 貼上 Telegram 訊息匯入</b>
    <div class="muted" style="font-size:.76rem;margin:6px 0">把「⏰ 假跌破＋日線多頭：13:15 還成立」整段訊息複製貼上；只會抓「• 代號 名稱 價格（漲跌）」那幾行，價格當進場價（日線結構、大盤會自動補算）。</div>
    <textarea id="ti-text" rows="8" style="width:100%;box-sizing:border-box;font-size:14px;background:#0d1117;color:var(--text);border:1px solid #30363d;border-radius:6px;padding:8px"></textarea>
    <div style="margin-top:8px">${_tailField('ti-date', '進場日（訊息那天）', today, 'date')}</div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:12px">
      <button class="btn sm ghost" data-x>取消</button><button class="btn sm" data-ok>匯入</button></div>`);
  m.querySelector('[data-x]').onclick = () => m.remove();
  m.querySelector('[data-ok]').onclick = async () => {
    try {
      const r = await api('POST', '/api/tail/import', { text: document.getElementById('ti-text').value, date: document.getElementById('ti-date').value });
      m.remove(); toast(`找到 ${r.found} 檔，新增 ${r.added} 檔（已在清單的略過）`); tailLoad();
    } catch (e) { toast(e.message, true); }
  };
}

function tailChart(sid) {
  _frozenChartList = [...new Set(_tailRows.map(x => x.stock_id))];
  _frozenChartIdx = Math.max(0, _frozenChartList.indexOf(sid));
  _tailRows.forEach(x => { if (x.name) _chartNames[x.stock_id] = x.name; });
  _chartSource = '尾盤追蹤'; _chartOhlcvUrl = null; _resetChartPeriod();
  openChart(sid);
}

async function tailAddWl(sid) {
  try {
    await addFromMarket(sid, '尾盤追蹤');
    tailRender();
  } catch (e) { toast(e.message, true); }
}
