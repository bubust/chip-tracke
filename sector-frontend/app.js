/**
 * app.js — 台股產業輪動引擎 V1 前端
 */

const BASE = "";  // 同源

// ── 狀態 ────────────────────────────────────────────────────────────────────
let _sectors = [];       // 當前表格資料
let _sortKey = "relative_rank_5d";
let _sortAsc = true;
let _currentTab = "rank";  // rank | change | event | events-list
let _statusTimer = null;

// ── localStorage 快取 ───────────────────────────────────────────────────────

const _LS_KEY = "sector_cache_v1";

function _saveCache(sectors, date) {
  try {
    localStorage.setItem(_LS_KEY, JSON.stringify({ sectors, date, saved: Date.now() }));
  } catch (e) {}
}

function _loadCache() {
  try {
    const raw = localStorage.getItem(_LS_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    // 快取超過 24 小時視為過期
    if (Date.now() - (obj.saved || 0) > 86400000) return null;
    return obj;
  } catch (e) { return null; }
}

// ── 初始化 ──────────────────────────────────────────────────────────────────

async function init() {
  // 先顯示 localStorage 快取（讓頁面重整後立刻有資料）
  const cache = _loadCache();
  if (cache && cache.sectors && cache.sectors.length > 0) {
    _sectors = cache.sectors;
    renderTable(_sectors);
    showLoading(false);
    // 在 header 顯示快取說明
    const dateBadge = document.getElementById("stat-date");
    if (dateBadge && cache.date) dateBadge.textContent = cache.date + "（快取）";
  }
  await loadStatus();
  await loadSectors(_currentTab);
  // 每 30s 自動刷狀態
  _statusTimer = setInterval(loadStatus, 30000);
}

// ── 狀態列 ──────────────────────────────────────────────────────────────────

async function loadStatus() {
  try {
    const r = await fetch(`${BASE}/sector/api/status`);
    const d = await r.json();

    document.getElementById("stat-sectors").textContent = d.sector_count ?? "—";
    document.getElementById("stat-stocks").textContent = d.stock_count ?? "—";
    document.getElementById("stat-date").textContent = formatDate(d.latest_date) || "尚無資料";

    const dot = document.getElementById("status-dot");
    const runTxt = document.getElementById("engine-running-txt");
    if (d.engine_running) {
      dot.className = "status-dot running";
      runTxt.style.display = "";
    } else {
      dot.className = d.initialized ? "status-dot ok" : "status-dot";
      runTxt.style.display = "none";
    }

    // 若未初始化，顯示提示
    if (!d.initialized) {
      showEmpty("尚未初始化", "請點擊右上角「初始化」按鈕，從 FinMind 建立產業對照表");
    }
  } catch (e) {
    console.error("loadStatus:", e);
  }
}

// ── 排序 Tab ────────────────────────────────────────────────────────────────

function switchSortTab(tab, el) {
  _currentTab = tab;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  el.classList.add("active");

  if (tab === "events-list") {
    document.getElementById("sectors-panel").style.display = "none";
    document.getElementById("detail-panel").style.display = "none";
    document.getElementById("events-panel").style.display = "";
    document.getElementById("bubble-panel").style.display = "none";
    loadEvents();
  } else if (tab === "bubble") {
    document.getElementById("sectors-panel").style.display = "none";
    document.getElementById("detail-panel").style.display = "none";
    document.getElementById("events-panel").style.display = "none";
    document.getElementById("bubble-panel").style.display = "";
    renderBubbleChart(_sectors.length > 0 ? _sectors : null);
  } else {
    document.getElementById("events-panel").style.display = "none";
    document.getElementById("detail-panel").style.display = "none";
    document.getElementById("sectors-panel").style.display = "";
    document.getElementById("bubble-panel").style.display = "none";
    loadSectors(tab);
  }
}

// ── 載入產業列表 ─────────────────────────────────────────────────────────────

async function loadSectors(tab) {
  const sortByMap = {
    rank: "rank5d",
    change: "rank_change",
    event: "event",
  };
  const sortBy = sortByMap[tab] || "rank5d";

  showLoading(true);
  try {
    const r = await fetch(`${BASE}/sector/api/sectors?sort_by=${sortBy}`);
    const d = await r.json();
    const fresh = d.sectors || [];
    if (fresh.length > 0) {
      _sectors = fresh;
      renderTable(_sectors);
      _saveCache(fresh, d.date);  // 成功時存快取
    } else if (_sectors.length === 0) {
      // API 空且沒有快取 → 顯示「無資料」
      renderTable([]);
    }
    // 若 API 空但有快取，保留快取畫面不清除
  } catch (e) {
    showToast("載入失敗：" + e.message, "err");
    if (_sectors.length === 0) showEmpty("載入失敗", "請重新整理頁面或點擊「初始化/更新」");
  } finally {
    showLoading(false);
  }
}

// ── 表格渲染 ─────────────────────────────────────────────────────────────────

function renderTable(sectors) {
  if (!sectors || sectors.length === 0) {
    showEmpty("尚無資料", "請先初始化並執行計算");
    return;
  }

  document.getElementById("sectors-panel").style.display = "";
  document.getElementById("loading-indicator").style.display = "none";

  const tbody = document.getElementById("sectors-tbody");
  tbody.innerHTML = "";

  sectors.forEach((s, i) => {
    const tr = document.createElement("tr");
    tr.id = `row-${i}`;
    tr.innerHTML = buildSectorRow(s, i);
    tbody.appendChild(tr);

    // 展開列（預設隱藏）
    const expandTr = document.createElement("tr");
    expandTr.id = `expand-${i}`;
    expandTr.className = "expand-row";
    expandTr.style.display = "none";
    expandTr.innerHTML = `<td colspan="12"><div class="expand-inner" id="expand-inner-${i}"></div></td>`;
    tbody.appendChild(expandTr);
  });
}

function buildSectorRow(s, i) {
  const name = s.sector_name || s.sector_id;
  const trend = s.trend_state || "—";
  const trendBadge = trendBadgeHtml(trend);

  const rank5 = rankHtml(s.relative_rank_5d, _sectors.length);
  const rank20 = rankHtml(s.relative_rank_20d, _sectors.length);
  const rank60 = rankHtml(s.relative_rank_60d, _sectors.length);

  const rankTrend = rankTrendHtml(s.rank_trend, s.rank_change_5d);
  const ret5 = retHtml(s.return_ew_5d);
  const ret20 = retHtml(s.return_ew_20d);

  const evBadge = s.structure_event ? eventBadgeHtml(s.structure_event) : '<span style="color:var(--muted)">—</span>';
  const healthBadge = healthBadgeHtml(s.internal_health);
  const regimeBadge = s.sector_regime
    ? `<span class="regime-chip regime-${s.sector_regime}">${s.sector_regime}</span>`
    : '<span style="color:var(--muted)">—</span>';

  return `
    <td style="font-weight:600;cursor:pointer" onclick="toggleDetail(${i}, '${escHtml(s.sector_id)}')">${name}</td>
    <td>${regimeBadge}</td>
    <td>${trendBadge}</td>
    <td>${rank5}</td>
    <td>${rank20}</td>
    <td>${rank60}</td>
    <td>${rankTrend}</td>
    <td>${ret5}</td>
    <td>${ret20}</td>
    <td>${evBadge}</td>
    <td>${healthBadge}</td>
    <td><button class="btn" style="padding:3px 8px;font-size:.75rem" onclick="openDetail('${escHtml(s.sector_id)}')">詳細</button></td>
  `;
}

// ── 行內展開 ────────────────────────────────────────────────────────────────

async function toggleDetail(i, sectorId) {
  const expandTr = document.getElementById(`expand-${i}`);
  const mainTr = document.getElementById(`row-${i}`);
  if (expandTr.style.display === "none") {
    expandTr.style.display = "";
    mainTr.classList.add("expanded");
    const inner = document.getElementById(`expand-inner-${i}`);
    inner.innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';
    try {
      const r = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}?days=30`);
      const d = await r.json();
      inner.innerHTML = buildExpandContent(d.latest, d.stocks);
      // 非同步載入個股明細
      loadExpandStocks(sectorId, d.latest?.sector_id || sectorId);
    } catch (e) {
      inner.innerHTML = '<span style="color:var(--red)">載入失敗</span>';
    }
  } else {
    expandTr.style.display = "none";
    mainTr.classList.remove("expanded");
  }
}

function buildExpandContent(latest, stocks) {
  if (!latest) return "無資料";

  const items = [
    ["指數水位", latest.index_level?.toFixed(2)],
    ["MA20", latest.ma20?.toFixed(2)],
    ["MA60", latest.ma60?.toFixed(2)],
    ["MA120", latest.ma120?.toFixed(2)],
    ["MA60 斜率", latest.ma60_slope !== null ? (latest.ma60_slope * 100).toFixed(3) + "%" : "—"],
    ["1D 報酬", pctFmt(latest.return_ew_1d)],
    ["5D 報酬", pctFmt(latest.return_ew_5d)],
    ["20D 報酬", pctFmt(latest.return_ew_20d)],
    ["60D 報酬", pctFmt(latest.return_ew_60d)],
    ["中位數 1D", pctFmt(latest.return_median_1d)],
    ["漲跌比", latest.breadth_up_ratio !== null ? (latest.breadth_up_ratio * 100).toFixed(1) + "%" : "—"],
    ["站上MA20", latest.above_ma20_ratio !== null ? (latest.above_ma20_ratio * 100).toFixed(1) + "%" : "—"],
    ["站上MA60", latest.above_ma60_ratio !== null ? (latest.above_ma60_ratio * 100).toFixed(1) + "%" : "—"],
    ["量能偏多比", latest.up_volume_ratio !== null ? (latest.up_volume_ratio * 100).toFixed(1) + "%" : "—"],
    ["Top3 貢獻", latest.top3_contribution !== null ? (latest.top3_contribution * 100).toFixed(1) + "%" : "—"],
    ["Swing High", latest.swing_high?.toFixed(2) + (latest.swing_high_date ? ` (${formatDate(latest.swing_high_date)})` : "") || "—"],
    ["Swing Low",  latest.swing_low?.toFixed(2)  + (latest.swing_low_date  ? ` (${formatDate(latest.swing_low_date)})` : "")  || "—"],
    ["市場相對 5D", latest.market_relative_5d !== null ? pctFmt(latest.market_relative_5d) : "—"],
    ["轉換狀態", latest.transition_state || "None"],
    ["股票數", latest.stock_count],
  ];

  const gridItems = items.map(([label, val]) =>
    `<div class="detail-item"><span class="detail-label">${label}</span><span class="detail-value">${val ?? "—"}</span></div>`
  ).join("");

  return `
    <div class="expand-section">
      <h4>詳細指標</h4>
      <div class="detail-grid">${gridItems}</div>
    </div>
    <div class="expand-section" style="flex:1;min-width:240px">
      <h4>成份股（${(stocks || []).length} 支）</h4>
      <div id="expand-stocks-${latest.sector_id || 'x'}" class="expand-stocks-wrap">
        <div style="color:var(--muted);font-size:.78rem">載入中…</div>
      </div>
    </div>
  `;
}

// ── 個股明細表格 ────────────────────────────────────────────────────────────────

async function loadExpandStocks(sectorId, domId) {
  const el = document.getElementById(`expand-stocks-${domId}`);
  if (!el) return;
  try {
    const r = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}/stocks`);
    const d = await r.json();
    el.innerHTML = renderStocksTable(d.stocks || []);
  } catch (e) {
    if (el) el.innerHTML = '<span style="color:var(--red)">載入失敗</span>';
  }
}

function renderStocksTable(stocks) {
  if (!stocks || stocks.length === 0) return '<div style="color:var(--muted);font-size:.8rem">無資料</div>';
  const rows = stocks.map(s => {
    const ret = s.return_20d;
    const retCls = ret === null ? '' : ret > 0 ? 'ret-pos' : ret < 0 ? 'ret-neg' : '';
    const retStr = ret === null ? '—' : (ret > 0 ? '+' : '') + ret.toFixed(2) + '%';
    const vol = s.volume ? (s.volume >= 10000 ? (s.volume/10000).toFixed(1)+'萬' : s.volume.toLocaleString()) : '—';
    return `<tr>
      <td style="font-weight:600;color:var(--accent)">${s.stock_id}</td>
      <td style="color:var(--text-dim)">${escHtml(s.name || '—')}</td>
      <td style="text-align:right">${s.close != null ? s.close.toFixed(2) : '—'}</td>
      <td style="text-align:right;color:var(--muted)">${vol}</td>
      <td class="${retCls}" style="text-align:right;font-weight:600">${retStr}</td>
    </tr>`;
  }).join('');
  return `<div style="overflow-x:auto;max-height:300px;overflow-y:auto">
    <table style="width:100%;border-collapse:collapse;font-size:.78rem">
      <thead><tr style="color:var(--muted);border-bottom:1px solid var(--border)">
        <th style="padding:4px 6px;text-align:left">股號</th>
        <th style="padding:4px 6px;text-align:left">股名</th>
        <th style="padding:4px 6px;text-align:right">股價</th>
        <th style="padding:4px 6px;text-align:right">成交量(張)</th>
        <th style="padding:4px 6px;text-align:right">20日漲幅</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ── 產業詳細頁 ────────────────────────────────────────────────────────────────

async function openDetail(sectorId) {
  document.getElementById("sectors-panel").style.display = "none";
  document.getElementById("events-panel").style.display = "none";
  const detailPanel = document.getElementById("detail-panel");
  detailPanel.style.display = "";
  document.getElementById("detail-content").innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';

  try {
    const r = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}?days=60`);
    const d = await r.json();
    renderDetailPage(d);
    // 非同步載入個股明細
    const sr = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}/stocks`);
    const sd = await sr.json();
    const el = document.getElementById("detail-stocks-wrap");
    if (el) el.innerHTML = renderStocksTable(sd.stocks || []);
  } catch (e) {
    document.getElementById("detail-content").innerHTML = `<div style="color:var(--red)">載入失敗：${e.message}</div>`;
  }
}

function renderDetailPage(d) {
  const s = d.latest || {};
  const name = s.sector_name || s.sector_id || d.sector_id || '';

  const metrics = [
    { label: "趨勢狀態", value: trendBadgeHtml(s.trend_state) },
    { label: "5D 排名", value: rankHtml(s.relative_rank_5d, null) },
    { label: "20D 排名", value: rankHtml(s.relative_rank_20d, null) },
    { label: "排名趨勢", value: rankTrendHtml(s.rank_trend, s.rank_change_5d) },
    { label: "5D 報酬", value: `<span class="${retClass(s.return_ew_5d)}">${pctFmt(s.return_ew_5d)}</span>` },
    { label: "20D 報酬", value: `<span class="${retClass(s.return_ew_20d)}">${pctFmt(s.return_ew_20d)}</span>` },
    { label: "60D 報酬", value: `<span class="${retClass(s.return_ew_60d)}">${pctFmt(s.return_ew_60d)}</span>` },
    { label: "指數水位", value: s.index_level?.toFixed(2) ?? "—" },
    { label: "健康度", value: healthBadgeHtml(s.internal_health) },
    { label: "漲跌比", value: s.breadth_up_ratio !== null && s.breadth_up_ratio !== undefined ? `<div class="health-bar-wrap"><div class="health-bar"><div class="health-bar-fill" style="width:${(s.breadth_up_ratio*100).toFixed(0)}%;background:${s.breadth_up_ratio>=0.5?'var(--green)':'var(--red)'}"></div></div>${(s.breadth_up_ratio*100).toFixed(1)}%</div>` : "—" },
    { label: "站上MA20", value: s.above_ma20_ratio !== null && s.above_ma20_ratio !== undefined ? `${(s.above_ma20_ratio*100).toFixed(1)}%` : "—" },
    { label: "結構事件", value: s.structure_event ? eventBadgeHtml(s.structure_event) : "—" },
  ];

  const metricCards = metrics.map(m =>
    `<div class="metric-card"><div class="metric-label">${m.label}</div><div class="metric-value">${m.value}</div></div>`
  ).join("");

  // 歷史事件
  const events = (d.events || []).map(ev =>
    `<div class="event-card">
      <span class="event-date">${formatDate(ev.observation_date)}</span>
      ${eventBadgeHtml(ev.event_type)}
      <span class="event-detail">參考價 ${ev.reference_price?.toFixed(2) ?? "—"} | 事件價 ${ev.event_price?.toFixed(2) ?? "—"}</span>
      <span style="color:var(--muted);font-size:.75rem">${ev.confirmation_status}</span>
    </div>`
  ).join("") || '<div style="color:var(--muted);font-size:.85rem">無近期事件</div>';

  // 歷史資料表格
  const historyRows = (d.history || []).slice(-20).reverse().map(h =>
    `<tr>
      <td>${formatDate(h.observation_date)}</td>
      <td>${h.index_level?.toFixed(2) ?? "—"}</td>
      <td class="${retClass(h.return_ew_1d)}">${pctFmt(h.return_ew_1d)}</td>
      <td class="${retClass(h.return_ew_5d)}">${pctFmt(h.return_ew_5d)}</td>
      <td>${h.ma20?.toFixed(2) ?? "—"}</td>
      <td>${h.ma60?.toFixed(2) ?? "—"}</td>
      <td>${trendBadgeHtml(h.trend_state)}</td>
      <td>${h.relative_rank_5d ?? "—"}</td>
    </tr>`
  ).join("");

  document.getElementById("detail-content").innerHTML = `
    <div class="detail-header">
      <h2>${name}</h2>
      <div class="meta">觀察日：${formatDate(s.observation_date)} | 股票數：${s.stock_count ?? "—"} | ${s.sector_regime ? `<span class="regime-chip regime-${s.sector_regime}">${s.sector_regime}</span>` : ""}</div>
    </div>

    <div class="metrics-grid">${metricCards}</div>

    <div style="margin-bottom:20px">
      <h4 style="color:var(--muted);margin-bottom:10px;font-size:.85rem">近期結構事件</h4>
      <div class="event-list">${events}</div>
    </div>

    <div>
      <h4 style="color:var(--muted);margin-bottom:10px;font-size:.85rem">歷史資料（最近 20 天）</h4>
      <div class="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>日期</th><th>指數</th><th>1D%</th><th>5D%</th>
              <th>MA20</th><th>MA60</th><th>趨勢</th><th>5D#</th>
            </tr>
          </thead>
          <tbody>${historyRows}</tbody>
        </table>
      </div>
    </div>

    <div style="margin-top:20px">
      <h4 style="color:var(--muted);margin-bottom:10px;font-size:.85rem">成份股（${(d.stocks||[]).length} 支）</h4>
      <div id="detail-stocks-wrap"><div style="color:var(--muted);font-size:.8rem">載入中…</div></div>
    </div>
  `;
}

function backToList() {
  document.getElementById("detail-panel").style.display = "none";
  if (_currentTab === "events-list") {
    document.getElementById("events-panel").style.display = "";
  } else {
    document.getElementById("sectors-panel").style.display = "";
  }
}

// ── 事件記錄 ────────────────────────────────────────────────────────────────

async function loadEvents() {
  const container = document.getElementById("events-list-container");
  container.innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';
  try {
    const r = await fetch(`${BASE}/sector/api/events?limit=50`);
    const d = await r.json();
    const events = d.events || [];
    if (events.length === 0) {
      container.innerHTML = '<div class="empty-state"><h3>尚無事件記錄</h3><p>請先執行計算</p></div>';
      return;
    }
    container.innerHTML = events.map(ev =>
      `<div class="event-card">
        <span class="event-date">${formatDate(ev.observation_date)}</span>
        <span class="event-sector">${ev.sector_name || ev.sector_id}</span>
        ${eventBadgeHtml(ev.event_type)}
        <span class="event-detail">參考價 <b>${ev.reference_price?.toFixed(2) ?? "—"}</b> | 事件價 <b>${ev.event_price?.toFixed(2) ?? "—"}</b></span>
        <span style="color:var(--muted);font-size:.75rem">${ev.confirmation_status}</span>
      </div>`
    ).join("");
  } catch (e) {
    container.innerHTML = `<div style="color:var(--red)">載入失敗：${e.message}</div>`;
  }
}

// ── 排序 ────────────────────────────────────────────────────────────────────

let _lastSortKey = null;
let _lastSortAsc = true;

function sortTable(key) {
  if (_lastSortKey === key) {
    _lastSortAsc = !_lastSortAsc;
  } else {
    _lastSortKey = key;
    _lastSortAsc = key.startsWith("return") ? false : true;
  }

  const sorted = [..._sectors].sort((a, b) => {
    let va = a[key], vb = b[key];
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    if (typeof va === "number") return _lastSortAsc ? va - vb : vb - va;
    return _lastSortAsc
      ? String(va).localeCompare(String(vb))
      : String(vb).localeCompare(String(va));
  });

  // 更新表頭箭頭
  document.querySelectorAll("th").forEach(th => th.classList.remove("sorted"));
  renderTable(sorted);
}

// ── Actions ──────────────────────────────────────────────────────────────────

async function triggerSmartRefresh() {
  const btn = document.getElementById("btn-smart-refresh");
  btn.disabled = true;

  try {
    // 先查狀態
    const st = await fetch(`${BASE}/sector/api/status`).then(r => r.json()).catch(() => null);

    if (!st || !st.initialized) {
      // 未初始化：先 init 再等待，然後 refresh
      btn.textContent = "初始化中...";
      showToast("尚未初始化，開始從 FinMind 建立產業對照表...", "ok");
      await fetch(`${BASE}/sector/api/init`, { method: "POST" });

      // 輪詢等待初始化完成（最多 5 分鐘）
      let waited = 0;
      await new Promise(resolve => {
        const poll = setInterval(async () => {
          waited += 10;
          const s = await fetch(`${BASE}/sector/api/status`).then(r => r.json()).catch(() => null);
          if ((s && s.initialized) || waited > 300) {
            clearInterval(poll);
            resolve();
          }
        }, 10000);
      });
    }

    // 執行更新計算
    btn.textContent = "計算中...";
    const r = await fetch(`${BASE}/sector/api/refresh?days_back=120`, { method: "POST" });
    const d = await r.json();
    if (d.ok) {
      showToast("引擎已開始計算（約需 3~10 分鐘）", "ok");
      const poll = setInterval(async () => {
        const s = await fetch(`${BASE}/sector/api/status`).then(r => r.json()).catch(() => null);
        if (s && !s.engine_running) {
          clearInterval(poll);
          btn.disabled = false;
          btn.textContent = "🔄 初始化/更新";
          await loadStatus();
          await loadSectors(_currentTab);
          showToast("更新完成！", "ok");
        }
      }, 10000);
    } else {
      showToast(d.message || "啟動失敗", "err");
      btn.disabled = false;
      btn.textContent = "🔄 初始化/更新";
    }
  } catch (e) {
    showToast("請求失敗：" + e.message, "err");
    btn.disabled = false;
    btn.textContent = "🔄 初始化/更新";
  }
}

// 保留舊名稱相容
async function triggerRefresh() { return triggerSmartRefresh(); }
async function triggerInit()    { return triggerSmartRefresh(); }

// ── UI helpers ────────────────────────────────────────────────────────────────

function trendBadgeHtml(trend) {
  const map = { BULL: ["badge-bull", "多頭"], BEAR: ["badge-bear", "空頭"], RANGE: ["badge-range", "盤整"] };
  const [cls, label] = map[trend] || ["badge-stable", trend || "—"];
  return `<span class="badge ${cls}">${label}</span>`;
}

function rankHtml(rank, total) {
  if (rank === null || rank === undefined) return '<span style="color:var(--muted)">—</span>';
  let cls = "rank-num";
  if (total && rank <= Math.ceil(total * 0.15)) cls += " rank-top3";
  else if (total && rank >= Math.ceil(total * 0.85)) cls += " rank-bot3";
  return `<span class="${cls}">${rank}</span>`;
}

function rankTrendHtml(trend, change) {
  const changeStr = change !== null && change !== undefined
    ? ` (${change > 0 ? "+" : ""}${change})`
    : "";
  if (trend === "STRENGTHENING") return `<span class="badge badge-strong arrow-up">↑↑ 強化${changeStr}</span>`;
  if (trend === "WEAKENING")     return `<span class="badge badge-weak arrow-down">↓↓ 弱化${changeStr}</span>`;
  return `<span class="badge badge-stable">→ 穩定${changeStr}</span>`;
}

function eventBadgeHtml(event) {
  const labels = {
    BREAKOUT:        "突破",
    BREAKDOWN:       "跌破",
    FALSE_BREAKDOWN: "假跌破",
    FALSE_BREAKOUT:  "假突破",
    RECLAIM:         "收復",
  };
  const label = labels[event] || event;
  return `<span class="badge-event badge-event-${event}">${label}</span>`;
}

function healthBadgeHtml(health) {
  const map = {
    HEALTHY:      ["badge-strong", "健康"],
    CONCENTRATED: ["badge-range",  "集中"],
    WEAK:         ["badge-weak",   "弱勢"],
    IMPROVING:    ["badge-strong", "改善"],
    DETERIORATING:["badge-weak",  "惡化"],
    STABLE:       ["badge-stable", "穩定"],
  };
  const [cls, label] = map[health] || ["badge-stable", health || "—"];
  return `<span class="badge ${cls}">${label}</span>`;
}

function retClass(val) {
  if (val === null || val === undefined) return "ret-neu";
  return val > 0 ? "ret-pos" : val < 0 ? "ret-neg" : "ret-neu";
}

function retHtml(val) {
  if (val === null || val === undefined) return '<span class="ret-neu">—</span>';
  const pct = (val * 100).toFixed(2);
  const sign = val > 0 ? "+" : "";
  return `<span class="${retClass(val)}">${sign}${pct}%</span>`;
}

function pctFmt(val) {
  if (val === null || val === undefined) return "—";
  const pct = (val * 100).toFixed(2);
  const sign = val > 0 ? "+" : "";
  return `${sign}${pct}%`;
}

function formatDate(d) {
  if (!d) return "—";
  const s = String(d);
  if (s.length === 8) return `${s.slice(0, 4)}/${s.slice(4, 6)}/${s.slice(6, 8)}`;
  if (s.includes("T")) return s.slice(0, 10);
  return s;
}

function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[c]));
}

function showLoading(show) {
  const el = document.getElementById("loading-indicator");
  if (show) {
    el.style.display = "";
    document.getElementById("sectors-panel").style.display = "none";
  } else {
    el.style.display = "none";
    document.getElementById("sectors-panel").style.display = "";
  }
}

function showEmpty(title, msg) {
  document.getElementById("loading-indicator").style.display = "none";
  document.getElementById("sectors-panel").style.display = "";
  document.getElementById("sectors-tbody").innerHTML =
    `<tr><td colspan="12">
      <div class="empty-state">
        <h3>${title}</h3>
        <p style="margin-top:6px;font-size:.85rem">${msg}</p>
      </div>
    </td></tr>`;
}

function showToast(msg, type = "ok") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => { t.className = "toast"; }, 3000);
}

// ── 樹狀熱力圖 ─────────────────────────────────────────────────────────────

function heatBg(ret5d) {
  const p = (ret5d || 0) * 100;
  if (p >= 5)    return '#155d27';
  if (p >= 3)    return '#1a7f37';
  if (p >= 1.5)  return '#238c45';
  if (p >= 0.5)  return '#2da44e';
  if (p > 0)     return '#3db868';
  if (p <= -5)   return '#7a1f1a';
  if (p <= -3)   return '#943028';
  if (p <= -1.5) return '#ad3a30';
  if (p <= -0.5) return '#c94a3f';
  if (p < 0)     return '#d9605a';
  return '#3d444d';
}

// Squarified treemap 算法
function squarifyLayout(items, x0, y0, w, h, rects) {
  if (!items.length) return;
  if (items.length === 1) { rects.push({...items[0], x:x0, y:y0, w, h}); return; }

  const short = Math.min(w, h);
  let bestN = 1, bestWorst = Infinity, rowArea = 0;

  for (let n = 1; n <= items.length; n++) {
    rowArea += items[n-1].area;
    const rowLen = rowArea / short;
    let worst = 0, acc = 0;
    for (let k = 0; k < n; k++) {
      const side = items[k].area / rowLen;
      worst = Math.max(worst, Math.max(rowLen / side, side / rowLen));
    }
    if (worst < bestWorst) { bestWorst = worst; bestN = n; }
    else break;
  }

  const row = items.slice(0, bestN);
  const rest = items.slice(bestN);
  const rowArea2 = row.reduce((s, i) => s + i.area, 0);
  const rowLen = rowArea2 / short;

  if (w >= h) {
    let cy = y0;
    for (const item of row) {
      const ih = item.area / rowLen;
      rects.push({...item, x:x0, y:cy, w:rowLen, h:ih});
      cy += ih;
    }
    squarifyLayout(rest, x0 + rowLen, y0, w - rowLen, h, rects);
  } else {
    let cx = x0;
    for (const item of row) {
      const iw = item.area / rowLen;
      rects.push({...item, x:cx, y:y0, w:iw, h:rowLen});
      cx += iw;
    }
    squarifyLayout(rest, x0, y0 + rowLen, w, h - rowLen, rects);
  }
}

async function renderBubbleChart(sectors) {
  const leftEl = document.getElementById("bubble-left");
  const container = document.getElementById("bubbleSection");

  if (!sectors || sectors.length === 0) {
    if (leftEl) leftEl.innerHTML = '<div class="loading"><div class="spinner"></div> 載入中...</div>';
    try {
      const r = await fetch(`${BASE}/sector/api/sectors?sort_by=rank5d`);
      const d = await r.json();
      sectors = d.sectors || [];
    } catch (e) {
      if (leftEl) leftEl.innerHTML = `<div style="color:var(--red);padding:20px">載入失敗：${e.message}</div>`;
      return;
    }
  }

  if (!sectors || sectors.length === 0) {
    if (leftEl) leftEl.innerHTML = '<div class="empty-state"><h3>尚無資料</h3><p>請先初始化並執行計算</p></div>';
    return;
  }

  // 依 5D 排名排序（強到弱）
  const sorted = [...sectors].sort((a, b) => (a.relative_rank_5d || 99) - (b.relative_rank_5d || 99));

  // 計算樹狀圖佈局（使用左欄寬度，面板已顯示時 clientWidth 正確）
  const W = Math.max(280, (leftEl ? leftEl.clientWidth : 0) || Math.round((container.clientWidth || 900) * 0.46));
  const H = Math.max(260, Math.round(W * 0.56));
  const GAP = 3;
  const totalStocks = sorted.reduce((s, sec) => s + (sec.stock_count || 1), 0);
  const items = sorted.map(s => ({...s, area: ((s.stock_count || 1) / totalStocks) * W * H}));

  const rects = [];
  squarifyLayout(items, 0, 0, W, H, rects);

  const tiles = rects.map(r => {
    const r5raw  = (r.return_ew_5d  || 0) * 100;
    const r20raw = (r.return_ew_20d || 0) * 100;
    const sign5  = r5raw  >= 0 ? '+' : '';
    const sign20 = r20raw >= 0 ? '+' : '';
    const bg = heatBg(r.return_ew_5d);
    const name = escHtml(r.sector_name || r.sector_id);
    const sid  = escHtml(r.sector_id);
    const tw = r.w - GAP, th = r.h - GAP;
    const fBase = Math.max(9, Math.min(13, tw / 9));
    const showName = tw > 55 && th > 36;
    const showR20  = tw > 70 && th > 56;

    const inner = showName
      ? `<div class="tm-name"  style="font-size:${Math.min(fBase, 11)}px">${name}</div>
         <div class="tm-r5"   style="font-size:${Math.min(fBase*1.3,14)}px">${sign5}${r5raw.toFixed(1)}%</div>
         ${showR20 ? `<div class="tm-r20" style="font-size:${Math.max(9,fBase*.85)}px">${sign20}${r20raw.toFixed(1)}% <span style="opacity:.55;font-size:8px">20日</span></div>` : ''}`
      : `<div style="font-size:9px;opacity:.7">${sign5}${r5raw.toFixed(1)}%</div>`;

    return `<div class="tm-cell" style="left:${r.x}px;top:${r.y}px;width:${Math.max(1,tw)}px;height:${Math.max(1,th)}px;background:${bg}"
      onclick="onBubbleClick('${sid}','${name}')" title="${name} | 5日:${sign5}${r5raw.toFixed(1)}% 20日:${sign20}${r20raw.toFixed(1)}%">
      ${inner}
    </div>`;
  }).join('');

  if (leftEl) leftEl.innerHTML = `
    <div class="tm-wrap" style="height:${H}px">${tiles}</div>
    <div class="heat-legend">
      <span>弱</span>
      <div class="heat-legend-grad"></div>
      <span>強</span>
      <span style="margin-left:8px">顏色=5日漲跌 ｜ 大小=成份股數量 ｜ 點擊左側查看詳情</span>
    </div>`;
}

async function onBubbleClick(sectorId, name) {
  const placeholder = document.getElementById("sdp-placeholder");
  const main = document.getElementById("sdp-main");
  if (!main) return;
  if (placeholder) placeholder.style.display = 'none';
  main.style.display = '';

  document.getElementById("sdp-title").textContent = name;
  document.getElementById("sdp-metrics").innerHTML =
    '<div style="color:var(--muted);font-size:.8rem;grid-column:1/-1">載入中...</div>';
  document.getElementById("sdp-stocks").innerHTML = '';

  try {
    const r = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}?days=60`);
    const d = await r.json();
    const s = d.latest || {};
    const metrics = [
      { lbl: '5日%',   val: pctFmt(s.return_ew_5d)  },
      { lbl: '20日%',  val: pctFmt(s.return_ew_20d) },
      { lbl: '60日%',  val: pctFmt(s.return_ew_60d) },
      { lbl: '趨勢',   val: s.trend_state || '—'    },
      { lbl: '健康',   val: s.internal_health || '—'},
      { lbl: '成份股', val: s.stock_count ?? '—'    },
    ];
    document.getElementById("sdp-metrics").innerHTML = metrics.map(m => {
      const v = m.val;
      const cls = typeof v === 'number' ? retClass(v) : '';
      return `<div class="sdp-metric-card"><div class="lbl">${m.lbl}</div><div class="val ${cls}">${v}</div></div>`;
    }).join('');

    const sr = await fetch(`${BASE}/sector/api/sector/${encodeURIComponent(sectorId)}/stocks`);
    const sd = await sr.json();
    const stks = sd.stocks || [];
    document.getElementById("sdp-stocks").innerHTML =
      `<div class="sdp-stocks-title">成份股（${stks.length}支）</div>` +
      renderStocksTablePanel(stks);
  } catch (e) {
    document.getElementById("sdp-metrics").innerHTML =
      `<div style="color:var(--red);grid-column:1/-1">載入失敗</div>`;
  }
}

function renderStocksTablePanel(stocks) {
  if (!stocks || stocks.length === 0)
    return '<div style="color:var(--muted);font-size:.8rem">無資料</div>';
  const rows = stocks.map(s => {
    const ret = s.return_20d;
    const retStyle = ret == null ? '' : ret > 0 ? 'color:var(--green)' : ret < 0 ? 'color:var(--red)' : '';
    const retStr = ret == null ? '—' : (ret > 0 ? '+' : '') + ret.toFixed(2) + '%';
    const vol = s.volume ? (s.volume >= 10000 ? (s.volume/10000).toFixed(1)+'萬' : s.volume.toLocaleString()) : '—';
    const sname = escHtml(s.name || '');
    return `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:6px 8px"><a class="stock-link" onclick="openKline('${s.stock_id}','${sname}')">${s.stock_id}</a></td>
      <td style="padding:6px 8px;color:var(--text-dim)">${sname}</td>
      <td style="padding:6px 8px;text-align:right">${s.close != null ? s.close.toFixed(2) : '—'}</td>
      <td style="padding:6px 8px;text-align:right;color:var(--muted)">${vol}</td>
      <td style="padding:6px 8px;text-align:right;${retStyle};font-weight:600">${retStr}</td>
      <td style="padding:6px 8px;text-align:right">
        <button class="btn sm ghost" onclick="addToWatchlist('${s.stock_id}','${sname}')">+清單</button>
      </td>
    </tr>`;
  }).join('');
  return `<div style="overflow-x:auto;max-height:320px;overflow-y:auto">
    <table style="width:100%;border-collapse:collapse;font-size:.82rem">
      <thead><tr style="color:var(--muted)">
        <th style="padding:5px 8px;text-align:left">股號</th>
        <th style="padding:5px 8px;text-align:left">股名</th>
        <th style="padding:5px 8px;text-align:right">股價</th>
        <th style="padding:5px 8px;text-align:right">成交量</th>
        <th style="padding:5px 8px;text-align:right">20日漲幅</th>
        <th style="padding:5px 8px;text-align:right">操作</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ── K線 Modal ────────────────────────────────────────────────────────────────

let _klineModalStock = null;

async function openKline(stockId, name) {
  _klineModalStock = {id: stockId, name};
  const modal = document.getElementById('kline-modal');
  document.getElementById('kline-title').textContent = `${stockId}　${name}`;
  modal.style.display = 'flex';
  const chartEl = document.getElementById('kline-chart');
  chartEl.innerHTML = '<div style="color:var(--muted);padding:20px;text-align:center">K線載入中...</div>';
  ['ki-close','ki-change','ki-ma5','ki-ma10','ki-ma20','ki-bb','ki-vol','ki-r20']
    .forEach(id => { const el = document.getElementById(id); if (el) el.textContent = '—'; });

  if (window._klineChart) { try { window._klineChart.remove(); } catch(_){} window._klineChart = null; }

  try {
    const res = await fetch(`${BASE}/api/stock/${encodeURIComponent(stockId)}/ohlcv`);
    const d = await res.json();
    const rawBars = (d.ohlcv || []).filter(b => b.date && b.close);
    const bars = rawBars.map(b => ({time: b.date, open: +b.open, high: +b.high, low: +b.low, close: +b.close}));

    chartEl.innerHTML = '';
    const chart = LightweightCharts.createChart(chartEl, {
      width: chartEl.clientWidth || 500,
      height: chartEl.clientHeight || 300,
      layout: { background: {color:'#0d1117'}, textColor:'#c9d1d9' },
      grid: { vertLines:{color:'#21262d'}, horzLines:{color:'#21262d'} },
      timeScale: { borderColor:'#30363d', timeVisible:true },
      rightPriceScale: { borderColor:'#30363d' },
    });
    const cs = chart.addCandlestickSeries({
      upColor:'#f85149', downColor:'#3fb950',
      borderUpColor:'#f85149', borderDownColor:'#3fb950',
      wickUpColor:'#f85149', wickDownColor:'#3fb950',
    });
    cs.setData(bars);
    chart.timeScale().fitContent();
    window._klineChart = chart;

    // ── 右側資訊面板 ──────────────────────────────────────────────
    if (rawBars.length >= 2) {
      const closes = rawBars.map(b => +b.close);
      const last = rawBars[rawBars.length - 1];
      const prev = rawBars[rawBars.length - 2];
      const close = +last.close;
      const changePct = prev.close ? ((close - +prev.close) / +prev.close * 100) : 0;
      const changeStyle = changePct >= 0 ? 'color:var(--red)' : 'color:var(--green)';

      const ma = (n) => {
        if (closes.length < n) return null;
        return (closes.slice(-n).reduce((s, v) => s + v, 0) / n).toFixed(2);
      };
      const ma5v  = ma(5);
      const ma10v = ma(10);
      const ma20v = ma(20);

      // BB 分數
      let bbScore = 0;
      if (closes.length >= 20) {
        const sl = closes.slice(-20);
        const mean = sl.reduce((s,v)=>s+v,0)/20;
        const std = Math.sqrt(sl.reduce((s,v)=>s+(v-mean)**2,0)/20);
        if (std > 0) bbScore = Math.max(-10, Math.min(10, ((close - mean) / (2 * std) * 10)));
      }

      const vol = +last.volume || 0;
      const volStr = vol >= 10000 ? (vol/10000).toFixed(1)+'萬' : vol.toLocaleString();

      // 20日漲幅
      let r20 = null;
      if (rawBars.length >= 20) {
        const base = +rawBars[rawBars.length - 20].close;
        if (base > 0) r20 = ((close - base) / base * 100);
      }

      document.getElementById('ki-close').textContent = close.toFixed(2);
      document.getElementById('ki-change').innerHTML =
        `<span style="${changeStyle}">${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%</span> 今日`;
      document.getElementById('ki-ma5').textContent  = ma5v  || '—';
      document.getElementById('ki-ma10').textContent = ma10v || '—';
      document.getElementById('ki-ma20').textContent = ma20v || '—';
      document.getElementById('ki-bb').textContent   = bbScore.toFixed(1);
      document.getElementById('ki-vol').textContent  = volStr;
      document.getElementById('ki-r20').innerHTML    = r20 != null
        ? `<span style="${r20>=0?'color:var(--red)':'color:var(--green)'}">${r20>=0?'+':''}${r20.toFixed(1)}%</span>`
        : '—';
    }
  } catch (e) {
    chartEl.innerHTML = `<div style="color:var(--red);padding:20px">載入失敗：${e.message}</div>`;
  }
}

function closeKlineModal() {
  document.getElementById('kline-modal').style.display = 'none';
  if (window._klineChart) { try { window._klineChart.remove(); } catch(_){} window._klineChart = null; }
}

async function addToWatchlistFromModal() {
  if (_klineModalStock) await addToWatchlist(_klineModalStock.id, _klineModalStock.name);
}

async function addToWatchlist(stockId, name) {
  try {
    const r = await fetch(`${BASE}/api/watchlist`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({stock_id: stockId, name: name || '', note: '産業輪動'})
    });
    const d = await r.json();
    showToast(d.message || `已加入觀察清單：${stockId}`, 'ok');
  } catch (e) {
    showToast('加入失敗：' + e.message, 'error');
  }
}

// ── 啟動 ────────────────────────────────────────────────────────────────────
init();
