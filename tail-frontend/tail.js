// 🎯 尾盤追蹤分頁（dashboard 內嵌）。資料：/api/tail/*
'use strict';

let _tailRows = [];
let _tailLoaded = 0;
let _tailStop = 8;
const _tailSort = { watch: { col: 'entry_date', dir: -1 }, stop: { col: 'stop_date', dir: -1 } };
const _tE = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const _tN = (v, dp = 2) => v == null ? '—' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: dp, minimumFractionDigits: dp });
const _tP = v => v == null ? '—' : `<span style="color:${v > 0 ? '#ef4444' : v < 0 ? '#22c55e' : 'var(--muted)'}">${v > 0 ? '+' : ''}${Number(v).toFixed(2)}%</span>`;
const _tD = d => d ? String(d).slice(5).replace('-', '/') : '—';

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
    _tailLoaded = Date.now();
    document.getElementById('tail-stop').value = _tailStop;
    document.getElementById('tail-stop-lbl').textContent = _tailStop;
    const days = [...new Set(_tailRows.map(x => x.entry_date))].sort().reverse();
    const sel = document.getElementById('tail-day'), cur = sel.value;
    sel.innerHTML = '<option value="">全部</option>' + days.map(d => `<option value="${d}">${_tD(d)}</option>`).join('');
    if (days.includes(cur)) sel.value = cur;
    st.textContent = `更新 ${new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}`;
    tailRender();
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

function _tailRow(zone, r) {
  const ma = r.ma10_now == null ? '—'
    : `${_tN(r.ma10_now)}<br><span style="font-size:.72rem;color:${r.above_ma10 ? '#ef4444' : '#22c55e'}">${r.above_ma10 ? '站上' : '跌破'}</span>`;
  const name = `<b class="link" style="color:var(--accent);cursor:pointer" onclick="tailChart('${_tE(r.stock_id)}')">${_tE(r.stock_id)}</b> ${_tE(r.name || '')}` +
    `<br><span style="font-size:.72rem;color:var(--muted)">${_tE(r.source || '')}</span>`;
  const px = r.price == null ? '—' : `${_tN(r.price)}<br><span style="font-size:.72rem;color:var(--muted)">${_tD(r.price_date)}</span>`;
  const act = `<span class="tail-act" style="display:inline-flex;gap:3px">
      ${typeof wlRowBtn === 'function' ? wlRowBtn(r.stock_id, `tailAddWl('${_tE(r.stock_id)}')`) : ''}
      <button class="btn sm ghost" title="編輯／移區" onclick="tailEdit(${r.id})">✏️</button>
      <button class="btn sm ghost" title="刪除" onclick="tailDel(${r.id})">🗑</button></span>`;
  const note = `<span style="white-space:normal;display:inline-block;max-width:160px;text-align:left">${_tE(r.note || '')}</span>`;
  if (zone === 'watch') {
    return `<tr><td class="l">${name}</td><td><b>${_tP(r.ret_pct)}</b></td><td>${px}</td><td>${_tN(r.entry_price)}</td><td>${_tD(r.entry_date)}</td><td>${r.days ?? '—'}</td>
      <td>${_tP(r.max_up_pct)}</td><td>${_tP(r.max_down_pct)}</td>
      <td title="現價離停損線 ${_tN(r.stop_level)} 還有多少">${r.to_stop_pct == null ? '—' : r.to_stop_pct.toFixed(1) + '%'}</td>
      <td>${ma}</td><td class="l">${note}</td><td>${act}</td></tr>`;
  }
  return `<tr><td class="l">${name}</td><td><b>${_tP(r.stop_ret_pct)}</b></td><td>${_tP(r.ret_pct)}</td><td>${_tD(r.stop_date)}</td><td>${_tN(r.stop_price)}</td>
    <td>${_tN(r.entry_price)}</td><td>${_tD(r.entry_date)}</td><td>${px}</td><td>${_tP(r.max_up_pct)}</td>
    <td class="l">${note}</td><td>${act}</td></tr>`;
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
  return `<div class="tbl-wrap" style="overflow-x:auto"><table class="tail-tbl"><thead><tr>${head}</tr></thead>
    <tbody>${rows.map(r => _tailRow(zone, r)).join('')}</tbody></table></div>`;
}

function tailRender() {
  const day = document.getElementById('tail-day').value, q = document.getElementById('tail-q').value.trim();
  const rows = _tailRows.filter(r => (!day || r.entry_date === day) && (!q || r.stock_id.includes(q) || (r.name || '').includes(q)));
  const watch = rows.filter(r => r.zone !== 'stop'), stop = rows.filter(r => r.zone === 'stop');
  document.getElementById('tail-watch').innerHTML = _tailTable('watch', watch);
  document.getElementById('tail-stop-zone').innerHTML = _tailTable('stop', stop);
  document.getElementById('tail-n-watch').textContent = watch.length;
  document.getElementById('tail-n-stop').textContent = stop.length;
  // 統計：全部（停損的用停損價算）
  const realized = rows.map(r => r.zone === 'stop' ? r.stop_ret_pct : r.ret_pct).filter(v => v != null);
  const avg = realized.length ? realized.reduce((a, b) => a + b, 0) / realized.length : null;
  const win = realized.filter(v => v > 0).length;
  const wAvg = watch.filter(r => r.ret_pct != null);
  document.getElementById('tail-summary').innerHTML = rows.length ? `
    <div>追蹤<b>${rows.length}</b> 檔</div>
    <div>觀察區平均<b>${wAvg.length ? _tP(wAvg.reduce((a, r) => a + r.ret_pct, 0) / wAvg.length) : '—'}</b></div>
    <div>停損<b>${stop.length}</b> 檔</div>
    <div title="停損的用停損價算，其他用現價">整體平均<b>${avg == null ? '—' : _tP(avg)}</b></div>
    <div title="目前報酬 > 0 的比例（停損的算輸）">賺錢比例<b>${realized.length ? Math.round(win / realized.length * 100) + '%' : '—'}</b></div>` : '';
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
    <div class="muted" style="font-size:.72rem;margin-top:6px">改進場價／日期會重新判斷停損（手動移過區的不動）</div>
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
    if (Number(g('te-px')) !== r.entry_price) body.entry_price = Number(g('te-px'));
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
    <div class="muted" style="font-size:.76rem;margin:6px 0">把「⏰ 假跌破：收盤前還成立」整段訊息複製貼上；只會抓「• 代號 名稱 價格（漲跌）」那幾行，價格當進場價。</div>
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
  const r = _tailRows.find(x => x.stock_id === sid);
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
