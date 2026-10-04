// 🤝 收購／併購分頁（dashboard 內嵌）。資料：/api/mna/*
'use strict';

let _mnaRows = [];
let _mnaFilter = '進行中';
let _mnaLoaded = false;
let _mnaPoll = null;
let _mnaSort = { col: null, dir: 1 };
const _MNA_COLS = [
  ['標的', 'target_id'], ['收購方', 'acquirer'], ['類型', 'deal_type'], ['狀態', 'status'],
  ['訊號', 'signal', '溢價 ≥15% 可進場、100% 收購隔天掛漲停；減資 Day2/3 畫線、現增用途與繳款前拉抬'],
  ['公告日', 'first_announce'], ['收購價', 'offer_value', '每股收購價（增資＝認購價）'], ['現價', 'price'],
  ['公告溢價', 'premium_pre_pct', '收購價 ÷ 公告前一天收盤 − 1（15% 以上才進）'], ['現價溢價', 'premium_pct', '收購價比現價高多少（還剩多少價差）'],
  ['數量(張)', 'max_lots', '最低～最高收購張數'], ['範圍', 'scope'], ['收購期間', 'period_end'],
  ['年化', 'annualized_pct', '現價溢價換算成年報酬（以剩餘天數計）'], ['對價', 'consideration'],
];
function mnaSortBy(col) {
  _mnaSort = _mnaSort.col === col ? { col, dir: -_mnaSort.dir }
    : { col, dir: ['target_id', 'acquirer', 'deal_type', 'status', 'signal', 'period_end', 'scope', 'consideration'].includes(col) ? 1 : -1 };
  mnaRender();
}
const _MNA_STATUS_COLOR = { '進行中': '#f59e0b', '未開始': '#58a6ff', '待補期間': '#a78bfa', '已公告': '#22c55e', '已結束': '#64748b' };
const _mnaE = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const _mnaN = (v, dp = 0) => v == null ? '—' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: dp, minimumFractionDigits: dp });
const _mnaD = d => d ? String(d).slice(2).replace(/-/g, '/') : '—';
const _mnaPct = v => v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`;

const _MNA_TYPES = ['公開收購', '合併', '股份轉換', '收購股權'];
const _isCap = r => r.deal_type === '減資' || r.deal_type === '現金增資';
const _mnaSig = s => s ? `<span class="sig sig-${s.level}" title="${_mnaE((s.tips || []).join('\n'))}">${_mnaE(s.label)}</span>` : '<span class="muted">—</span>';

// 使用說明：記住收合狀態（每個瀏覽器自己記）
function _guideRemember(id) {
  const el = document.getElementById(id);
  if (!el || el._bound) return;
  el._bound = true;
  try { if (localStorage.getItem('guide_' + id) === '0') el.open = false; } catch (e) {}
  el.addEventListener('toggle', () => { try { localStorage.setItem('guide_' + id, el.open ? '1' : '0'); } catch (e) {} });
}

function mnaOnShow() { _guideRemember('mna-guide'); if (!_mnaLoaded) { _mnaLoaded = true; mnaLoad(); } }

async function mnaLoad() {
  const body = document.getElementById('mna-body');
  body.innerHTML = '<div style="color:var(--muted);text-align:center;padding:30px">載入中...</div>';
  try {
    const r = await api('GET', `/api/mna/list?days=${document.getElementById('mna-days').value}`);
    _mnaRows = r.rows || [];
    _mnaStatus(r.status);
    mnaRender();
    if (r.status?.refresh?.running) _mnaWatch();
  } catch (e) { body.innerHTML = `<div style="color:var(--red)">載入失敗：${_mnaE(e.message)}</div>`; }
}

function _mnaStatus(s) {
  const el = document.getElementById('mna-status'), err = document.getElementById('mna-error');
  if (!s) return;
  el.textContent = [`共 ${s.rows || 0} 筆`, s.last_refresh ? `上次更新 ${s.last_refresh}：${s.last_message || ''}` : '尚未從公開資訊觀測站更新'].join(' · ');
  if (s.last_errors && !s.rows) {
    err.style.display = '';
    err.innerHTML = `⚠️ 伺服器抓不到公開資訊觀測站重大訊息：${_mnaE(s.last_errors.split('\n')[0])}${s.last_snippet ? `<br><span class="muted">回應：${_mnaE(s.last_snippet.slice(0, 160))}</span>` : ''}<br>可以用「＋ 手動新增」或匯入 CSV。`;
  } else err.style.display = 'none';
}

function mnaRender() {
  const counts = {};
  _mnaRows.forEach(r => { counts[r.status] = (counts[r.status] || 0) + 1; });
  counts['🔥 可進場'] = _mnaRows.filter(r => r.signal?.level === 'buy').length;
  document.getElementById('mna-chips').innerHTML = ['🔥 可進場', '進行中', '未開始', '待補期間', '已公告', '已結束', '全部'].map(k => {
    const n = k === '全部' ? _mnaRows.length : (counts[k] || 0), on = _mnaFilter === k, c = k === '🔥 可進場' ? '#ef4444' : (_MNA_STATUS_COLOR[k] || 'var(--accent)');
    return `<button onclick="_mnaFilter='${k}';mnaRender()" style="cursor:pointer;border-radius:14px;padding:3px 12px;font-size:.8rem;border:1px solid ${on ? c : '#30363d'};background:${on ? c + '22' : 'transparent'};color:${on ? c : 'var(--muted)'}">${k} <b>${n}</b></button>`;
  }).join('');
  const type = document.getElementById('mna-type').value, q = document.getElementById('mna-search').value.trim();
  const rows = _mnaRows.filter(r => (_mnaFilter === '全部' || r.status === _mnaFilter || (_mnaFilter === '🔥 可進場' && r.signal?.level === 'buy'))
    && (!type || r.deal_type === type || (type === '@mna' && _MNA_TYPES.includes(r.deal_type)))
    && (!q || r.target_id.includes(q) || (r.target_name || '').includes(q) || (r.acquirer || '').includes(q)));
  if (_mnaSort.col) {
    const k = _mnaSort.col, d = _mnaSort.dir, lv = { buy: 0, watch: 1, info: 2, avoid: 3 };
    const v = r => k === 'signal' ? (r.signal ? lv[r.signal.level] : 9) : k === 'first_announce' ? (r.first_announce || r.announce_date)
      : k === 'max_lots' ? r.max_lots : r[k];
    rows.sort((a, b) => { const x = v(a), y = v(b);
      if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
      return (typeof x === 'string' ? x.localeCompare(y) : x - y) * d; });
  }
  const body = document.getElementById('mna-body');
  if (!rows.length) { body.innerHTML = `<div style="color:var(--muted);text-align:center;padding:30px">${_mnaRows.length ? '沒有符合條件的資料' : '尚無資料'}</div>`; return; }
  const td = (v, x = '') => `<td style="padding:5px 8px;white-space:nowrap;${x}">${v}</td>`;
  body.innerHTML = `<div class="tbl-wrap" style="overflow-x:auto"><table style="width:100%;font-size:.8rem;border-collapse:collapse">
    <thead><tr style="background:#1c2128;color:var(--muted)"><th style="padding:6px 4px;white-space:nowrap">自選</th>${_MNA_COLS.map(([lab, key, tip]) => {
      const arrow = _mnaSort.col === key ? (_mnaSort.dir > 0 ? ' ▲' : ' ▼') : '';
      return `<th title="${_mnaE(tip || '點一下排序')}" onclick="mnaSortBy('${key}')" style="cursor:pointer;user-select:none;padding:6px 8px;white-space:nowrap${key === 'target_id' || key === 'acquirer' ? ';text-align:left' : ''}">${lab}${arrow}</th>`;
    }).join('')}
    </tr></thead><tbody>${rows.map(r => {
      const c = _MNA_STATUS_COLOR[r.status] || '#64748b';
      return `<tr style="border-top:1px solid #21262d;cursor:pointer" onclick="mnaDetail(${r.id})">
        ${td(wlRowBtn(r.target_id, `mnaAddWl(${r.id})`), 'padding:5px 4px;text-align:center')}
        ${td(`<b style="color:var(--accent)">${_mnaE(r.target_id)}</b> ${_mnaE(r.target_name || '')}${r.target_company && r.target_id === r.announcer_id
            ? `<br><span style="font-size:.7rem;color:var(--muted)">收購 ${_mnaE(r.target_company.replace('股份有限公司', ''))}（未上市櫃）</span>` : ''}`)}
        ${td(_mnaE(r.acquirer || '—'), 'max-width:160px;overflow:hidden;text-overflow:ellipsis')}
        ${td(_mnaE(r.deal_type || '—') + (_isCap(r) && r.deal_kind && r.deal_kind !== r.deal_type ? `<br><span style="font-size:.68rem;color:var(--muted)">${_mnaE(r.deal_kind)}</span>` : ''))}
        ${td(`<span style="font-size:.72rem;padding:1px 7px;border-radius:10px;background:${c}22;color:${c};border:1px solid ${c}55">${_mnaE(r.status)}</span>`)}
        ${td(_mnaSig(r.signal))}
        ${td(_mnaD(r.first_announce || r.announce_date) + ((r.related || []).length > 1 ? `<br><span style="font-size:.66rem;color:var(--muted)">${r.related.length} 則公告</span>` : ''))}
        ${td(r.offer_value != null ? `<b title="${_mnaE(r.offer_value_note || '')}">${_mnaN(r.offer_value, 2)}</b>${r.offer_value_note ? '<br><span style="font-size:.66rem;color:var(--muted)">含換股</span>' : _isCap(r) ? '<br><span style="font-size:.66rem;color:var(--muted)">認購價</span>' : ''}` : _isCap(r) ? '—' : '<span class="muted">待補</span>', 'text-align:right')}
        ${td(r.price != null ? _mnaN(r.price, 2) : '—', 'text-align:right')}
        ${td(_mnaPct(r.premium_pre_pct), `text-align:right;font-weight:700;color:${r.premium_pre_pct == null ? 'var(--muted)' : r.premium_pre_pct >= 15 ? '#ef4444' : r.premium_pre_pct > 0 ? '#f59e0b' : '#22c55e'}`)}
        ${td(_mnaPct(r.premium_pct), `text-align:right;color:${r.premium_pct == null ? 'var(--muted)' : r.premium_pct > 0 ? '#ef4444' : '#22c55e'}`)}
        ${td(r.max_lots != null ? `${r.min_lots != null ? _mnaN(r.min_lots) + '～' : ''}${_mnaN(r.max_lots)}` : '—', 'text-align:right')}
        ${td(_isCap(r) ? (r.offer_pct ? `減資 ${r.offer_pct}%` : r.consideration ? `用途：${_mnaE(r.consideration)}` : '—') : _mnaE(r.scope || '—'))}
        ${td(_isCap(r) && r.deal_type === '減資' ? (r.period_start ? `恢復買賣 ${_mnaD(r.period_start)}` : '—') : r.period_start ? `${_mnaD(r.period_start)}～${_mnaD(r.period_end)}${r.days_left != null ? `<br><span style="font-size:.7rem;color:#f59e0b">剩 ${r.days_left} 天</span>` : ''}` : '—')}
        ${td(_mnaPct(r.annualized_pct), 'text-align:right')}
        ${td(_mnaE(r.consideration || '—'))}
      </tr>`;
    }).join('')}</tbody></table></div>`;
}

function mnaDetail(id) {
  const r = _mnaRows.find(x => x.id === id);
  if (!r) return;
  const m = document.createElement('div');
  m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:10001;display:flex;align-items:center;justify-content:center;padding:16px';
  m.onclick = e => { if (e.target === m) m.remove(); };
  const line = (k, v) => `<div><span class="muted">${k}</span>　${v}</div>`;
  m.innerHTML = `<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;max-width:520px;width:100%;max-height:85vh;overflow:auto;font-size:.85rem;line-height:1.8">
    <div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:1rem">${_mnaE(r.target_id)} ${_mnaE(r.target_name || '')}</b>
      <button class="btn sm ghost" onclick="this.closest('div[style*=fixed]').remove()">✕</button></div>
    ${r.signal ? `<div style="margin:6px 0;padding:8px 10px;border-radius:8px;background:#0d1117;border:1px solid #30363d">${_mnaSig(r.signal)}
      <ul style="margin:4px 0 0;padding-left:18px;font-size:.8rem">${(r.signal.tips || []).map(t => `<li>${_mnaE(t)}</li>`).join('')}</ul></div>` : ''}
    ${line('類型', _mnaE(r.deal_type || '—') + (r.deal_kind && _isCap(r) ? `（${_mnaE(r.deal_kind)}）` : ''))}${_isCap(r) ? '' : line('收購方', _mnaE(r.acquirer || '—'))}${line('狀態', _mnaE(r.status))}
    ${r.target_company ? line('被收購公司', _mnaE(r.target_company)) : ''}
    ${_isCap(r) ? line('認購價', r.offer_value != null ? _mnaN(r.offer_value, 2) : '—') + (r.offer_pct ? line('減資比率', r.offer_pct + '%') : '') + (r.consideration ? line('資金用途', _mnaE(r.consideration)) : '') : line('每股收購價', r.offer_value != null ? `<b>${_mnaN(r.offer_value, 2)}</b>${r.offer_value_note ? `（${_mnaE(r.offer_value_note)}，以換發股票現價計）` : ''}（公告前收盤 ${_mnaN(r.pre_price, 2)}，公告溢價 ${_mnaPct(r.premium_pre_pct)}；現價 ${_mnaN(r.price, 2)}，現價溢價 ${_mnaPct(r.premium_pct)}）` : '待補')}
    ${_isCap(r) ? '' : line('收購數量', r.max_shares ? `最低 ${_mnaN(r.min_lots)} 張～上限 ${_mnaN(r.max_lots)} 張${r.offer_pct ? `（約 ${r.offer_pct}%）` : ''}${r.amount_yi ? `，約 ${r.amount_yi} 億` : ''}` : '待補')}
    ${_isCap(r) ? '' : line('範圍', _mnaE(r.scope || '—')) + line('對價', _mnaE(r.consideration || '—'))}
    ${line(r.deal_type === '減資' ? '恢復買賣日' : r.deal_type === '現金增資' ? '繳款期間' : '期間', r.period_start ? `${r.period_start}${r.period_end ? ' ～ ' + r.period_end : ''}${r.days_left != null ? `（剩 ${r.days_left} 天，年化 ${_mnaPct(r.annualized_pct)}）` : ''}` : '待補')}
    ${(r.related || []).length ? `<div style="margin-top:6px"><span class="muted">相關公告（${r.related.length} 則）</span>${r.related.map(x =>
      `<div style="margin-top:4px;padding:6px 8px;background:#0d1117;border-radius:6px;font-size:.76rem">${_mnaD(x.date)}　${_mnaE((x.subject || '').slice(0, 160))}</div>`).join('')}</div>`
      : (r.subject ? `<div style="margin-top:6px;padding:8px;background:#0d1117;border-radius:6px;font-size:.78rem">${_mnaE(r.subject)}</div>` : '')}
    ${r.notes ? line('備註', _mnaE(r.notes)) : ''}
    <div class="muted" style="font-size:.72rem">來源：${_mnaE(r.source || '—')}　細節以公開資訊觀測站公告內文為準</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">
      <button class="btn sm" onclick="this.closest('div[style*=fixed]').remove();mnaEdit(${r.id})">✏️ 編輯／補資料</button>
      <button class="btn sm ghost" onclick="this.closest('div[style*=fixed]').remove();mnaChart(${r.id})">📈 K 線</button>
      <button class="btn sm ghost" style="color:#22c55e" onclick="mnaAddWl(${r.id})">+ 觀察清單</button>
      <a class="btn sm ghost" href="https://mopsov.twse.com.tw/mops/web/t05st01" target="_blank" rel="noopener">公開資訊觀測站</a>
    </div></div>`;
  document.body.appendChild(m);
}

function mnaChart(id) {
  const r = _mnaRows.find(x => x.id === id);
  if (!r) return;
  _frozenChartList = _mnaRows.map(x => x.target_id);
  _frozenChartIdx = _frozenChartList.indexOf(r.target_id);
  if (r.target_name) _chartNames[r.target_id] = r.target_name;
  _chartSource = '收購併購'; _chartOhlcvUrl = null; _resetChartPeriod();
  openChart(r.target_id);
}

async function mnaAddWl(id) {
  const r = _mnaRows.find(x => x.id === id);
  if (!r) return;
  try {
    await api('POST', '/api/watchlist', { stock_id: r.target_id, name: r.target_name || '', note: '收購併購' });
    if (!_wlData.find(x => x.stock_id === r.target_id)) _wlData.push({ stock_id: r.target_id, name: r.target_name || '', memo: '', note: '收購併購', has_data: false });
    const ls = lsLoadWatchlist();
    if (!ls.find(x => x.stock_id === r.target_id)) { ls.push({ stock_id: r.target_id, name: r.target_name || '', memo: '', note: '收購併購' }); lsSaveWatchlist(ls); }
    renderWatchlist();
    toast(`已加入觀察清單：${r.target_id} ${r.target_name || ''}`);
    mnaRender();
  } catch (e) { toast(e.message, true); }
}

function mnaEdit(id) {
  const r = id ? (_mnaRows.find(x => x.id === id) || {}) : { deal_type: '公開收購' };
  const f = (k, label, type = 'text', ph = '') => `<label style="display:flex;flex-direction:column;gap:2px;font-size:.76rem;color:var(--muted)">${label}
    <input data-k="${k}" type="${type}" value="${_mnaE(r[k] ?? '')}" placeholder="${ph}" style="font-size:16px"></label>`;
  const sel = (k, label, opts) => `<label style="display:flex;flex-direction:column;gap:2px;font-size:.76rem;color:var(--muted)">${label}
    <select data-k="${k}">${opts.map(o => `<option ${String(r[k] || '') === o ? 'selected' : ''}>${o}</option>`).join('')}</select></label>`;
  const m = document.createElement('div');
  m.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:10001;display:flex;align-items:center;justify-content:center;padding:16px';
  m.innerHTML = `<div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px;max-width:560px;width:100%;max-height:90vh;overflow:auto">
    <b>${id ? '編輯' : '新增'}收購／併購</b>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin-top:10px">
      ${f('target_id', '標的代號 *')}${f('target_name', '標的名稱')}${f('acquirer', '收購方')}
      ${sel('deal_type', '類型', ['公開收購', '合併', '股份轉換', '收購股權', '減資', '現金增資', '其他'])}
      ${f('announce_date', '公告日', 'date')}${f('offer_price', '每股收購價', 'number')}
      ${f('min_shares', '最低收購數量（股）', 'number')}${f('max_shares', '收購數量上限（股）', 'number')}${f('offer_pct', '收購比例 %', 'number')}
      ${sel('scope', '範圍', ['', '完全收購', '部分收購'])}${f('period_start', '收購期間起', 'date')}${f('period_end', '收購期間迄', 'date')}
      ${sel('consideration', '對價', ['', '現金', '換股', '現金＋換股'])}${sel('status_override', '手動狀態（空白＝自動）', ['', '已完成', '已取消', '延長期間'])}
      ${f('notes', '備註')}
    </div>
    <div style="display:flex;gap:8px;justify-content:space-between;margin-top:12px">
      ${id ? `<button class="btn sm danger" data-act="del">刪除</button>` : '<span></span>'}
      <span style="display:flex;gap:8px"><button class="btn sm ghost" data-act="cancel">取消</button><button class="btn sm" data-act="save">儲存</button></span>
    </div></div>`;
  document.body.appendChild(m);
  m.querySelector('[data-act=cancel]').onclick = () => m.remove();
  const del = m.querySelector('[data-act=del]');
  if (del) del.onclick = async () => { if (!confirm('確定刪除這筆？')) return; try { await api('DELETE', `/api/mna/deal/${id}`); m.remove(); mnaLoad(); } catch (e) { toast(e.message, true); } };
  m.querySelector('[data-act=save]').onclick = async () => {
    const body = {};
    m.querySelectorAll('[data-k]').forEach(el => {
      const v = el.value.trim();
      body[el.dataset.k] = el.type === 'number' ? (v === '' ? null : Number(v)) : (v || null);
    });
    if (!body.target_id) { toast('請填標的代號', true); return; }
    try { await api(id ? 'PUT' : 'POST', id ? `/api/mna/deal/${id}` : '/api/mna/deal', body); m.remove(); toast('已儲存'); mnaLoad(); }
    catch (e) { toast(e.message, true); }
  };
}

async function mnaRefresh() {
  try { const r = await api('POST', '/api/mna/refresh?days=20'); toast(r.message, !r.ok); _mnaWatch(); } catch (e) { toast(e.message, true); }
}

function _mnaWatch() {
  clearTimeout(_mnaPoll);
  const el = document.getElementById('mna-progress');
  const tick = async () => {
    try {
      const s = await api('GET', '/api/mna/status');
      if (s.refresh?.running) {
        el.style.display = ''; el.textContent = `更新中… ${s.refresh.total ? `${s.refresh.progress}/${s.refresh.total} 天` : '準備中'}`;
        _mnaPoll = setTimeout(tick, 3000);
      } else { el.style.display = 'none'; mnaLoad(); }
    } catch (e) { el.style.display = 'none'; }
  };
  tick();
}

function mnaImport(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  const rd = new FileReader();
  rd.onload = async () => {
    try {
      const r = await fetch(API_BASE + '/api/mna/import', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: rd.result });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      toast(`匯入 ${d.imported} 筆`); mnaLoad();
    } catch (e) { toast('匯入失敗：' + e.message, true); }
    input.value = '';
  };
  rd.readAsArrayBuffer(file);
}
