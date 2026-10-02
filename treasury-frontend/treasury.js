// 🏦 庫藏股分頁（dashboard 內嵌，非 iframe：才能直接開 K 線、加觀察清單）
// 資料：/api/treasury/*（MOPS t35sc09 庫藏股買回資訊彙總）
'use strict';

let _tbRows = [];
let _tbStatusFilter = '進行中';
let _tbSort = { col: 'board_date', dir: -1 };
let _tbActive = {};          // {stock_id: {...}} 進行中/未開始 → 觀察清單、策略篩選打標記
let _tbLoaded = false;
let _tbPollTimer = null;
let _tbExpanded = null;

const _tbEsc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const _tbNum = (v, dp = 0) => v == null ? '—' : Number(v).toLocaleString('zh-TW', { maximumFractionDigits: dp, minimumFractionDigits: dp });
const _tbPct = (v, dp = 1) => v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(dp)}%`;
const _tbColor = v => v == null ? 'var(--muted)' : (v >= 0 ? '#ef4444' : '#22c55e');   // 台股慣例：紅漲綠跌
const _tbDate = d => d ? d.slice(2).replace(/-/g, '/') : '—';   // 2024-05-10 → 24/05/10
const _TB_STATUS_COLOR = { '進行中': '#f59e0b', '未開始': '#58a6ff', '期滿待申報': '#a78bfa', '已結束': '#64748b' };

function _tbPurposeShort(p) {
  p = p || '';
  if (/員工/.test(p)) return '轉讓員工';
  if (/股東權益|信用/.test(p)) return '維護股東權益';
  if (/轉換|認股|附認股/.test(p)) return '轉換／認股';
  return p || '—';
}

// 其他分頁用：股票名稱旁的 🏦 標記
function tbBadge(sid) {
  const a = _tbActive[sid];
  if (!a) return '';
  const tip = `庫藏股${a.status}：${a.period_start || ''}～${a.period_end || ''}，預定 ${a.plan_lots ?? '—'} 張，價格區間 ${a.price_low ?? '—'}～${a.price_high ?? '—'}`;
  return `<span title="${_tbEsc(tip)}" style="margin-left:4px;font-size:.66rem;background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55;border-radius:3px;padding:0 4px;white-space:nowrap">🏦庫藏</span>`;
}

async function tbLoadActive() {
  try {
    _tbActive = await api('GET', '/api/treasury/active') || {};
    // _wlData / _viewingStrategy 是 dashboard 的頂層 let，不在 window 上，用 typeof 判斷
    if (typeof _wlData !== 'undefined' && _wlData.length) renderWatchlist();
    if (typeof _viewingStrategy !== 'undefined' && _viewingStrategy && typeof _screenAllResults !== 'undefined')
      renderScreenTable(_viewingStrategy, _screenAllResults[_viewingStrategy] || []);
  } catch (e) { /* 沒資料就不打標記 */ }
}

function tbOnShow() {
  if (!_tbLoaded) { _tbLoaded = true; tbLoad(); }
}

async function tbLoad() {
  const body = document.getElementById('tb-body');
  const days = document.getElementById('tb-days').value;
  const market = document.getElementById('tb-market').value;
  body.innerHTML = '<div style="color:var(--muted);text-align:center;padding:30px">載入中...</div>';
  try {
    const r = await api('GET', `/api/treasury/list?days=${days}&market=${market}`);
    _tbRows = r.rows || [];
    _tbRenderStatus(r.status);
    _tbRenderChips();
    tbRender();
    if (r.status?.refresh?.running) _tbPoll();
  } catch (e) {
    body.innerHTML = `<div style="color:var(--red)">載入失敗：${_tbEsc(e.message)}</div>`;
  }
}

function _tbRenderStatus(s) {
  const el = document.getElementById('tb-status');
  if (!s) { el.textContent = ''; return; }
  const parts = [];
  if (s.rows) parts.push(`共 ${s.rows} 筆（決議日 ${_tbDate(s.earliest)}～${_tbDate(s.latest)}）`);
  if (s.last_refresh) parts.push(`上次更新 ${s.last_refresh}：${s.last_message || ''}`);
  if (s.last_import) parts.push(`上次匯入 ${s.last_import}`);
  el.innerHTML = _tbEsc(parts.join(' · ') || '尚無資料，按「從公開資訊觀測站更新」或匯入檔案');
  const err = document.getElementById('tb-error');
  if (s.last_errors && !s.rows) {
    err.style.display = '';
    err.innerHTML = `⚠️ 伺服器抓不到公開資訊觀測站：${_tbEsc(s.last_errors.split('\n')[0])}${s.last_snippet ? `<br><span style="color:var(--muted)">回應：${_tbEsc(s.last_snippet.slice(0, 160))}</span>` : ''}<br>
      可以改用「匯入」：到公開資訊觀測站「庫藏股買回資訊彙總」查詢後另存 CSV（或整頁存成 HTML）匯入這裡；或在自己電腦執行 <code>python treasury_sync.py</code> 自動抓好推上來。`;
  } else if (s.last_errors) {
    err.style.display = '';
    err.innerHTML = `⚠️ 部分區段更新失敗：${_tbEsc(s.last_errors.split('\n')[0])}`;
  } else {
    err.style.display = 'none';
  }
}

function _tbRenderChips() {
  const counts = {};
  _tbRows.forEach(r => { counts[r.status] = (counts[r.status] || 0) + 1; });
  const all = ['進行中', '未開始', '期滿待申報', '已結束', '全部'];
  document.getElementById('tb-chips').innerHTML = all.map(k => {
    const n = k === '全部' ? _tbRows.length : (counts[k] || 0);
    const on = _tbStatusFilter === k;
    const c = _TB_STATUS_COLOR[k] || 'var(--accent)';
    return `<button onclick="_tbStatusFilter='${k}';_tbRenderChips();tbRender()" style="cursor:pointer;border-radius:14px;padding:3px 12px;font-size:.8rem;border:1px solid ${on ? c : '#30363d'};background:${on ? c + '22' : 'transparent'};color:${on ? c : 'var(--muted)'}">${k} <b>${n}</b></button>`;
  }).join('');
}

function _tbFiltered() {
  const q = document.getElementById('tb-search').value.trim();
  const purpose = document.getElementById('tb-purpose').value;
  const inRange = document.getElementById('tb-inrange').checked;
  return _tbRows.filter(r =>
    (_tbStatusFilter === '全部' || r.status === _tbStatusFilter) &&
    (!q || r.stock_id.includes(q) || (r.name || '').includes(q)) &&
    (!purpose || _tbPurposeShort(r.purpose) === purpose) &&
    (!inRange || r.range_pos === '區間內' || r.range_pos === '低於下限'));
}

function tbSortBy(col) {
  _tbSort = _tbSort.col === col ? { col, dir: -_tbSort.dir } : { col, dir: -1 };
  tbRender();
}

const _TB_COLS = [
  ['stock_id', '代號'], ['name', '名稱'], ['status', '狀態'], ['board_date', '決議日'],
  ['period_end', '買回期間'], ['purpose', '目的'], ['plan_lots', '預定(張)'], ['price_high', '價格區間'],
  ['price', '現價'], ['to_high_pct', '離上限'], ['chg_since_board', '決議後漲跌'],
  ['bought_lots', '已買回(張)'], ['exec_ratio', '執行率'], ['avg_price', '均價'], ['pct_of_capital', '佔股本'],
];
const _TB_HINT = {
  to_high_pct: '現價漲到買回價格上限還差多少；負的代表股價已高於上限，公司不能再買',
  chg_since_board: '董事會決議日收盤 → 最新收盤',
  exec_ratio: '已買回 ÷ 預定買回；通常買回期間結束後公司申報才會更新',
  pct_of_capital: '已買回股數佔已發行股份比例',
  price: '最新收盤（股價快取）',
};

function tbRender() {
  const rows = _tbFiltered();
  const { col, dir } = _tbSort;
  rows.sort((a, b) => {
    const x = a[col], y = b[col];
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return (x > y ? 1 : x < y ? -1 : 0) * dir;
  });
  window._tbVisibleIds = rows.map(r => r.stock_id);
  const body = document.getElementById('tb-body');
  if (!rows.length) {
    body.innerHTML = `<div style="color:var(--muted);text-align:center;padding:30px">${_tbRows.length ? '沒有符合條件的資料' : '尚無資料'}</div>`;
    _tbRenderSummary([]);
    return;
  }
  _tbRenderSummary(rows);
  const th = ([k, label]) => `<th onclick="tbSortBy('${k}')" title="${_TB_HINT[k] || ''}" style="cursor:pointer;white-space:nowrap;padding:6px 8px;text-align:${['stock_id', 'name', 'purpose'].includes(k) ? 'left' : 'right'}">${label}${_tbSort.col === k ? (dir > 0 ? ' ▲' : ' ▼') : ''}</th>`;
  body.innerHTML = `<div class="tbl-wrap" style="overflow-x:auto"><table style="width:100%;font-size:.8rem;border-collapse:collapse">
    <thead><tr style="background:#1c2128;color:var(--muted)">${_TB_COLS.map(th).join('')}</tr></thead>
    <tbody>${rows.map(_tbRow).join('')}</tbody></table></div>`;
}

function _tbRow(r) {
  const c = _TB_STATUS_COLOR[r.status] || '#64748b';
  const posColor = { '區間內': '#f59e0b', '低於下限': '#ef4444', '高於上限': '#64748b' }[r.range_pos] || 'var(--muted)';
  const td = (v, extra = '') => `<td style="padding:5px 8px;text-align:right;white-space:nowrap;${extra}">${v}</td>`;
  const key = `${r.stock_id}_${r.board_date}`;
  return `<tr data-key="${key}" style="border-top:1px solid #21262d;cursor:pointer" onclick="tbToggle('${r.stock_id}','${key}')">
    <td style="padding:5px 8px;color:var(--muted)">${_tbEsc(r.stock_id)}</td>
    <td style="padding:5px 8px;white-space:nowrap">${_tbEsc(r.name)}${r.market === 'tpex' ? '<span style="color:var(--muted);font-size:.68rem"> 櫃</span>' : ''}</td>
    ${td(`<span style="font-size:.72rem;padding:1px 7px;border-radius:10px;background:${c}22;color:${c};border:1px solid ${c}55">${r.status}</span>`)}
    ${td(_tbDate(r.board_date))}
    ${td(`${_tbDate(r.period_start)}～${_tbDate(r.period_end)}${r.days_left != null ? `<br><span style="font-size:.7rem;color:#f59e0b">剩 ${r.days_left} 天</span>` : ''}`)}
    <td style="padding:5px 8px;white-space:nowrap" title="${_tbEsc(r.purpose)}">${_tbEsc(_tbPurposeShort(r.purpose))}</td>
    ${td(_tbNum(r.plan_lots))}
    ${td(r.price_high != null ? `${_tbNum(r.price_low, 1)}～${_tbNum(r.price_high, 1)}` : '—')}
    ${td(r.price != null ? `${_tbNum(r.price, 2)}${r.range_pos ? `<br><span style="font-size:.68rem;color:${posColor}">${r.range_pos}</span>` : ''}` : '—')}
    ${td(_tbPct(r.to_high_pct), `color:${r.to_high_pct == null ? 'var(--muted)' : r.to_high_pct >= 0 ? '#f59e0b' : 'var(--muted)'}`)}
    ${td(_tbPct(r.chg_since_board), `color:${_tbColor(r.chg_since_board)};font-weight:600`)}
    ${td(_tbNum(r.bought_lots))}
    ${td(r.exec_ratio != null ? `${Number(r.exec_ratio).toFixed(0)}%` : '—')}
    ${td(r.avg_price != null ? _tbNum(r.avg_price, 2) : '—')}
    ${td(r.pct_of_capital != null ? `${Number(r.pct_of_capital).toFixed(2)}%` : '—')}
  </tr>`;
}

function _tbRenderSummary(rows) {
  const el = document.getElementById('tb-summary');
  const live = rows.filter(r => r.status === '進行中');
  const amount = live.reduce((s, r) => s + (r.amount_cap || 0), 0);
  const inRange = live.filter(r => r.range_pos === '區間內' || r.range_pos === '低於下限').length;
  const done = rows.filter(r => r.status === '已結束' && r.exec_ratio != null);
  const avgExec = done.length ? done.reduce((s, r) => s + r.exec_ratio, 0) / done.length : null;
  const box = (label, val, hint = '') => `<div title="${hint}" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 10px;text-align:center">
    <div style="font-size:.7rem;color:var(--muted)">${label}</div><div style="font-size:1.15rem;font-weight:700">${val}</div></div>`;
  el.innerHTML = box('列表筆數', rows.length) +
    box('進行中', live.length) +
    box('進行中且現價在區間內', inRange, '公司還能在這個價位買，等於有買盤支撐') +
    box('進行中預定金額上限', amount ? `${(amount / 1e8).toFixed(1)} 億` : '—') +
    box('已結束平均執行率', avgExec != null ? `${avgExec.toFixed(0)}%` : '—', '說到做到的程度；執行率低的公司公告效果要打折');
}

async function tbToggle(sid, key) {
  const old = document.getElementById('tb-detail');
  if (old) old.remove();
  if (_tbExpanded === key) { _tbExpanded = null; return; }
  _tbExpanded = key;
  const tr = document.querySelector(`#tb-body tr[data-key="${key}"]`);
  if (!tr) return;
  const det = document.createElement('tr');
  det.id = 'tb-detail';
  det.innerHTML = `<td colspan="${_TB_COLS.length}" style="background:#0d1117;padding:10px 14px">載入中...</td>`;
  tr.after(det);
  try {
    const h = await api('GET', `/api/treasury/stock/${encodeURIComponent(sid)}`);
    const name = h.name || '';
    const rows = h.rows || [];
    const cur = rows.find(r => `${r.stock_id}_${r.board_date}` === key) || rows[0] || {};
    det.firstElementChild.innerHTML = `
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
        <b>${_tbEsc(sid)} ${_tbEsc(name)}</b>
        <span style="color:var(--muted);font-size:.78rem">歷次買回 ${h.count} 次${h.avg_exec_ratio != null ? ` · 已結束平均執行率 ${h.avg_exec_ratio}%` : ''}${h.total_bought_amount ? ` · 累計買回 ${(h.total_bought_amount / 1e8).toFixed(2)} 億` : ''}</span>
        <span style="margin-left:auto;display:flex;gap:6px">
          <button class="btn sm ghost" onclick="event.stopPropagation();tbOpenChart('${_tbEsc(sid)}','${_tbEsc(name).replace(/'/g, '')}')">📈 K 線</button>
          <button class="btn sm ghost" style="color:#22c55e" onclick="event.stopPropagation();tbAddWl('${_tbEsc(sid)}','${_tbEsc(name).replace(/'/g, '')}')">+ 觀察清單</button>
        </span>
      </div>
      <div style="font-size:.78rem;color:var(--muted);margin-bottom:8px;line-height:1.6">
        本次：${_tbEsc(cur.purpose || '—')} · 金額上限 ${cur.amount_cap ? (cur.amount_cap / 1e8).toFixed(2) + ' 億' : '—'}
        ${cur.price_at_board ? ` · 決議日收盤 ${_tbNum(cur.price_at_board, 2)}` : ''}${cur.vs_avg_price != null ? ` · 現價相對買回均價 ${_tbPct(cur.vs_avg_price)}` : ''}
        ${cur.not_done_reason ? `<br>未執行完畢原因：${_tbEsc(cur.not_done_reason)}` : ''}
      </div>
      <div style="overflow-x:auto"><table style="width:100%;font-size:.76rem;border-collapse:collapse;white-space:nowrap">
        <thead><tr style="color:var(--muted)"><th style="text-align:left;padding:3px 6px">決議日</th><th style="padding:3px 6px">期間</th>
          <th style="padding:3px 6px">目的</th><th style="padding:3px 6px;text-align:right">預定(張)</th><th style="padding:3px 6px;text-align:right">價格區間</th>
          <th style="padding:3px 6px;text-align:right">已買回(張)</th><th style="padding:3px 6px;text-align:right">執行率</th>
          <th style="padding:3px 6px;text-align:right">均價</th><th style="padding:3px 6px;text-align:right">決議後漲跌</th><th style="padding:3px 6px">狀態</th></tr></thead>
        <tbody>${rows.map(r => `<tr style="border-top:1px solid #21262d${`${r.stock_id}_${r.board_date}` === key ? ';background:#f59e0b11' : ''}">
          <td style="padding:3px 6px">${_tbDate(r.board_date)}</td>
          <td style="padding:3px 6px">${_tbDate(r.period_start)}～${_tbDate(r.period_end)}</td>
          <td style="padding:3px 6px">${_tbEsc(_tbPurposeShort(r.purpose))}</td>
          <td style="padding:3px 6px;text-align:right">${_tbNum(r.plan_lots)}</td>
          <td style="padding:3px 6px;text-align:right">${r.price_high != null ? `${_tbNum(r.price_low, 1)}～${_tbNum(r.price_high, 1)}` : '—'}</td>
          <td style="padding:3px 6px;text-align:right">${_tbNum(r.bought_lots)}</td>
          <td style="padding:3px 6px;text-align:right">${r.exec_ratio != null ? Number(r.exec_ratio).toFixed(0) + '%' : '—'}</td>
          <td style="padding:3px 6px;text-align:right">${r.avg_price != null ? _tbNum(r.avg_price, 2) : '—'}</td>
          <td style="padding:3px 6px;text-align:right;color:${_tbColor(r.chg_since_board)}">${_tbPct(r.chg_since_board)}</td>
          <td style="padding:3px 6px;color:${_TB_STATUS_COLOR[r.status]}">${r.status}</td>
        </tr>`).join('')}</tbody></table></div>`;
  } catch (e) {
    det.firstElementChild.innerHTML = `<span style="color:var(--red)">載入失敗：${_tbEsc(e.message)}</span>`;
  }
}

function tbOpenChart(sid, name) {
  _frozenChartList = [...new Set(window._tbVisibleIds || [sid])];
  _frozenChartIdx = _frozenChartList.indexOf(sid);
  if (name) _chartNames[sid] = name;
  _chartSource = '庫藏股';
  _chartOhlcvUrl = null;
  _resetChartPeriod();
  openChart(sid);
}

async function tbAddWl(sid, name) {
  const note = '庫藏股';
  const ls = lsLoadWatchlist();
  if (!ls.find(x => x.stock_id === sid)) { ls.push({ stock_id: sid, name, memo: '', note }); lsSaveWatchlist(ls); }
  try {
    await api('POST', '/api/watchlist', { stock_id: sid, name, note });
    if (!_wlData.find(x => x.stock_id === sid)) {
      _wlData.push({ stock_id: sid, name, memo: '', note, has_data: false });
      toast(`已加入觀察清單：${sid} ${name}（庫藏股）`);
    } else {
      toast(`${sid} 已在觀察清單`);
    }
    renderWatchlist();
  } catch (e) { toast(e.message, true); }
}

async function tbRefresh() {
  const days = Math.max(180, parseInt(document.getElementById('tb-days').value) || 365);
  try {
    const r = await api('POST', `/api/treasury/refresh?days=${days}`);
    toast(r.message, !r.ok);
    _tbPoll();
  } catch (e) { toast(e.message, true); }
}

function _tbPoll() {
  clearTimeout(_tbPollTimer);
  const el = document.getElementById('tb-progress');
  const tick = async () => {
    try {
      const s = await api('GET', '/api/treasury/status');
      const p = s.refresh || {};
      if (p.running) {
        el.style.display = '';
        el.textContent = `更新中… ${p.total ? `${p.progress}/${p.total} 段` : '準備中'}（公開資訊觀測站會擋太快的查詢，每段間隔幾秒）`;
        _tbPollTimer = setTimeout(tick, 3000);
      } else {
        el.style.display = 'none';
        tbLoad();
        tbLoadActive();
      }
    } catch (e) { el.style.display = 'none'; }
  };
  tick();
}

function tbImport(input) {
  const f = input.files && input.files[0];
  if (!f) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const r = await fetch(API_BASE + '/api/treasury/import', {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: reader.result });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      toast(`匯入 ${d.parsed} 筆（新增 ${d.inserted}、更新 ${d.updated}）`);
      tbLoad();
      tbLoadActive();
    } catch (e) { toast('匯入失敗：' + e.message, true); }
    input.value = '';
  };
  reader.readAsArrayBuffer(f);
}

document.addEventListener('DOMContentLoaded', () => setTimeout(tbLoadActive, 1500));
