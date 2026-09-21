/* ── 金流追蹤模組 ── */

let _flowDir    = 'all';
let _flowSort   = 'net';
let _flowDate   = null;
let _flowInited = false;
let _flowPolling = null;

/* ── 初始化（切到金流分頁時呼叫一次） ── */
async function initFlow() {
  if (!_flowInited) {
    await loadFlowDates();
    _flowInited = true;
  }
  refreshFlowStatus();
}

/* ── 載入可用日期 ── */
async function loadFlowDates() {
  try {
    const dates = await fetch('/warrant/api/flow/dates').then(r => r.json());
    const sel   = document.getElementById('flowDateSel');
    sel.innerHTML = '';

    // 加入今天（可能還沒有資料）
    const today = new Date().toISOString().slice(0, 10);
    const allDates = dates.includes(today) ? dates : [today, ...dates];

    allDates.forEach(d => {
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d;
      sel.appendChild(opt);
    });

    _flowDate = allDates[0] || today;
    sel.value = _flowDate;
    loadFlowTable();
  } catch(e) {
    console.error('[flow] loadFlowDates', e);
  }
}

/* ── 日期切換 ── */
function onFlowDateChange() {
  _flowDate = document.getElementById('flowDateSel').value;
  loadFlowTable();
}

/* ── 方向切換 ── */
function setFlowDir(dir) {
  _flowDir = dir;
  ['flowBtnAll','flowBtnCall','flowBtnPut'].forEach(id => {
    document.getElementById(id).classList.remove('active');
  });
  const map = { all:'flowBtnAll', CALL:'flowBtnCall', PUT:'flowBtnPut' };
  document.getElementById(map[dir] || 'flowBtnAll').classList.add('active');
  loadFlowTable();
}

/* ── 排序切換 ── */
function setFlowSort(s) {
  _flowSort = s;
  ['flowSortNet','flowSortTotal','flowSortCp'].forEach(id =>
    document.getElementById(id).classList.remove('active'));
  const map = { net:'flowSortNet', total:'flowSortTotal', cp:'flowSortCp' };
  document.getElementById(map[s]).classList.add('active');
  loadFlowTable();
}

/* ── 載入金流表格 ── */
async function loadFlowTable() {
  const wrap = document.getElementById('flowTableWrap');
  wrap.innerHTML = '<div class="flow-placeholder">載入中…</div>';

  const dir = _flowDir === 'all' ? '' : _flowDir;
  const url = `/warrant/api/flow/daily?date=${_flowDate}&sort_by=${_flowSort}&min_total=10000`
            + (dir ? `&direction=${dir}` : '');
  try {
    const data = await fetch(url).then(r => r.json());
    if (!data.rows || data.rows.length === 0) {
      wrap.innerHTML = `<div class="flow-placeholder">
        ${_flowDate} 尚無金流資料<br>
        <small>盤後 14:10 自動更新，或點「立刻計算」手動觸發</small>
      </div>`;
      return;
    }
    wrap.innerHTML = renderFlowTable(data.rows);
  } catch(e) {
    wrap.innerHTML = `<div class="flow-placeholder" style="color:var(--red)">載入失敗：${e.message}</div>`;
  }
}

/* ── 渲染表格 ── */
function renderFlowTable(rows) {
  const fmtMoney = v => {
    if (Math.abs(v) >= 10000) return (v/10000).toFixed(1) + '億';
    return v.toFixed(0) + '萬';
  };
  const fmtVol = v => v >= 10000 ? (v/10000).toFixed(1)+'萬張' : v.toLocaleString()+'張';
  const dirTag = dir => dir === 'CALL'
    ? '<span class="flow-dir-call">▲認購</span>'
    : dir === 'PUT'
      ? '<span class="flow-dir-put">▼認售</span>'
      : '<span class="flow-dir-flat">－持平</span>';
  const cpTag = cp => cp == null ? '—'
    : cp >= 3 ? `<span style="color:var(--green);font-weight:700">${cp.toFixed(2)}</span>`
    : cp <= 0.33 ? `<span style="color:var(--red);font-weight:700">${cp.toFixed(2)}</span>`
    : cp.toFixed(2);

  let html = `
  <table class="flow-table">
    <thead>
      <tr>
        <th>#</th><th>股號</th><th>股名</th>
        <th>認購金額(萬)</th><th>認購量</th>
        <th>認售金額(萬)</th><th>認售量</th>
        <th>淨流量(萬)</th><th>C/P比</th><th>方向</th>
      </tr>
    </thead><tbody>`;

  rows.forEach((r, i) => {
    const isCall = r.direction === 'CALL';
    const isPut  = r.direction === 'PUT';
    const rowCls = isCall ? 'flow-row-call' : isPut ? 'flow-row-put' : '';
    const netAbs = Math.abs(r.net_turnover);
    // 淨流量 bar 寬度（最大 rows 中最大值）
    html += `
    <tr class="flow-row ${rowCls}" onclick="showFlowDetail('${r.underlying_code}','${escHtml(r.underlying_name || r.underlying_code)}')">
      <td class="flow-rank">${i+1}</td>
      <td class="flow-code">${r.underlying_code}</td>
      <td class="flow-name">${r.underlying_name || '—'}</td>
      <td class="flow-call-amt">${fmtMoney(r.call_turnover)}</td>
      <td class="flow-vol">${fmtVol(r.call_volume)}</td>
      <td class="flow-put-amt">${fmtMoney(r.put_turnover)}</td>
      <td class="flow-vol">${fmtVol(r.put_volume)}</td>
      <td class="flow-net ${isCall?'flow-net-pos':isPut?'flow-net-neg':''}">${isCall?'+':''}${fmtMoney(r.net_turnover)}</td>
      <td class="flow-cp">${cpTag(r.cp_ratio)}</td>
      <td>${dirTag(r.direction)}</td>
    </tr>`;
  });

  html += '</tbody></table>';
  return html;
}

/* ── 個股歷史 ── */
async function showFlowDetail(code, name) {
  const panel = document.getElementById('flowDetail');
  document.getElementById('flowDetailTitle').textContent = `${name}（${code}）近期金流`;
  panel.classList.remove('hidden');

  const chartDiv = document.getElementById('flowDetailChart');
  chartDiv.innerHTML = '載入中…';

  try {
    const data = await fetch(`/warrant/api/flow/stock/${code}?days=20`).then(r => r.json());
    if (!data.rows || !data.rows.length) {
      chartDiv.innerHTML = '<div style="padding:20px;color:var(--text-dim)">尚無歷史資料</div>';
      return;
    }
    chartDiv.innerHTML = renderFlowHistory(data.rows);
  } catch(e) {
    chartDiv.innerHTML = `<div style="color:var(--red)">載入失敗</div>`;
  }
}

function closeFlowDetail() {
  document.getElementById('flowDetail').classList.add('hidden');
}

function renderFlowHistory(rows) {
  const fmtM = v => v >= 10000 ? (v/10000).toFixed(1)+'億' : v.toFixed(0)+'萬';
  let html = `<table class="flow-table flow-history-table">
    <thead><tr>
      <th>日期</th><th>認購(萬)</th><th>認售(萬)</th><th>淨流量(萬)</th><th>C/P比</th>
    </tr></thead><tbody>`;
  rows.forEach(r => {
    const isCall = r.net_turnover > 0;
    const isPut  = r.net_turnover < 0;
    html += `<tr>
      <td>${r.trade_date}</td>
      <td style="color:var(--green)">${fmtM(r.call_turnover)}</td>
      <td style="color:var(--red)">${fmtM(r.put_turnover)}</td>
      <td class="${isCall?'flow-net-pos':isPut?'flow-net-neg':''}">${isCall?'+':''}${fmtM(r.net_turnover)}</td>
      <td>${r.cp_ratio != null ? r.cp_ratio.toFixed(2) : '—'}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  return html;
}

/* ── 手動觸發計算 ── */
async function triggerFlowRun() {
  const d = _flowDate || new Date().toISOString().slice(0,10);
  try {
    await fetch(`/warrant/api/flow/run?date=${d}`, {method:'POST'});
    setFlowStatusText('計算中…', false);
    startFlowPolling();
  } catch(e) {
    setFlowStatusText('觸發失敗：' + e.message, true);
  }
}

/* ── 輪詢計算狀態 ── */
function startFlowPolling() {
  if (_flowPolling) clearInterval(_flowPolling);
  _flowPolling = setInterval(refreshFlowStatus, 2000);
}

async function refreshFlowStatus() {
  try {
    const s = await fetch('/warrant/api/flow/status').then(r => r.json());
    if (s.error) {
      setFlowStatusText('計算失敗：' + s.error, true);
      clearInterval(_flowPolling); _flowPolling = null;
    } else if (!s.running && s.ran_at) {
      setFlowStatusText(`最後計算：${s.ran_at}　共 ${s.last_count} 筆`, false);
      clearInterval(_flowPolling); _flowPolling = null;
      loadFlowTable();
    } else if (s.running) {
      setFlowStatusText('計算中…', false);
    }
  } catch(e) {}
}

function setFlowStatusText(txt, isErr) {
  const el = document.getElementById('flowStatus');
  el.innerHTML = `<span style="color:${isErr?'var(--red)':'var(--text-dim)'}">${txt}</span>`;
}

/* ── escHtml 在 app.js 已定義，若未載入則補一個 ── */
if (typeof escHtml === 'undefined') {
  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
}
