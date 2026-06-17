/* ppc_dashboard.js — PPC Dashboard Module  (Mức 1–9, Profit-Driven PPC)
 *
 * Kiến trúc:
 *   - IIFE độc lập, không đụng render_performance.js / app.js gốc.
 *   - Patch App.go() để xử lý route 'ppcdash'.
 *   - Inject toàn bộ UI vào #page-ppcdash (section riêng).
 *   - Lazy-load từng cấp: Portfolio → Campaign → Ad Group → Keyword → Search Term.
 *
 * Cột 19 cột / 5 nhóm Business Logic:
 *   G1 Identity   : Name (indent+toggle+image), Status (badge clickable)
 *   G2 Traffic    : Impressions, Clicks, Orders, Units
 *   G3 Sales      : Ad Spend, CPC, PPC Sales, CPA, Conversion%, Same SKU%
 *   G4 Profit     : ACOS (đỏ khi > BEP), Profit (đỏ/xanh)
 *   G5 Automation : BEP ACOS, BEP Bid, Bid Rec., Current Bid / Budget (input), Auto (toggle)
 */
(function () {
  'use strict';

  /* ══════════════════════════════════════════════════════════════════════
   * 1. GLOBAL STATE  (Master Filter Bar)
   * ══════════════════════════════════════════════════════════════════════ */
  var currentPpcFilters = {
    date_range:      { start: '2026-05-12', end: '2026-06-12' },
    status_filter:   ['ENABLED', 'PAUSED'],
    product_filter:  { type: 'sku', value: '' },
    campaign_filter: { campaign_ids: [], include_no_product_campaigns: true },
    advanced_rules:  [],
    activeTab:       'portfolio',
  };
  window.currentPpcFilters = currentPpcFilters;

  /* Danh sách campaign tạm — sẽ được điền sau khi fetch grid lần đầu */
  var _campaignOptions = [];
  var _chart      = null;
  var _dashInited = false;

  /* ══════════════════════════════════════════════════════════════════════
   * 2. HELPERS
   * ══════════════════════════════════════════════════════════════════════ */
  var $el = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmtMoney(n) {
    var v = Number(n) || 0;
    if (v < 0) return '-$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return '$' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function fmtNum(n) {
    return (Number(n) || 0).toLocaleString('en-US');
  }

  function fmtPct(n) {
    return (Number(n) || 0).toFixed(2) + '%';
  }

  function filterQs() {
    var f = currentPpcFilters;
    var parts = [
      'start='   + encodeURIComponent(f.date_range.start),
      'end='     + encodeURIComponent(f.date_range.end),
      'status='  + encodeURIComponent(f.status_filter.join(',')),
      'sku='     + encodeURIComponent(f.product_filter.value),
      'camps='   + encodeURIComponent(f.campaign_filter.campaign_ids.join(',')),
    ];
    return parts.join('&');
  }

  async function ppcFetch(path) {
    var token = localStorage.getItem('sv_token');
    var base  = (window.SV_API_BASE || location.origin).replace(/\/$/, '');
    var res   = await fetch(base + path, {
      headers: token ? { Authorization: 'Bearer ' + token } : {},
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.json();
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 3. DASHBOARD HTML  (Top + Mid + Bot Panels)
   * ══════════════════════════════════════════════════════════════════════ */
  function buildDashboardHtml() {
    var TAB_DEFS = [
      ['portfolio',   'Portfolios'],
      ['campaign',    'Campaigns'],
      ['ad_group',    'Ad Groups'],
      ['keyword',     'Keywords'],
      ['search_term', 'Search Terms'],
    ];

    var tabsHtml = TAB_DEFS.map(function (t, i) {
      var active = i === 0;
      return '<button onclick="PpcDash.switchTab(\'' + t[0] + '\')" id="ppc-tab-' + t[0] + '"' +
        ' class="ppc-tab-btn text-xs px-3 py-2 rounded-t-lg border-b-2 font-medium transition-colors ' +
        (active ? 'border-indigo-600 text-indigo-600 bg-white' : 'border-transparent text-slate-500 hover:text-indigo-600') + '">' +
        t[1] + '</button>';
    }).join('');

    /* Tiêu đề nhóm cột (row 1 của thead) */
    var groupHead = [
      '<th colspan="2" class="ppc-gh text-slate-600 bg-slate-100">🏷 Identity</th>',
      '<th colspan="4" class="ppc-gh text-blue-700 bg-blue-50">📈 Traffic</th>',
      '<th colspan="6" class="ppc-gh text-green-700 bg-green-50">💰 Sales &amp; Conv.</th>',
      '<th colspan="2" class="ppc-gh text-purple-700 bg-purple-50">📊 Profitability</th>',
      '<th colspan="5" class="ppc-gh text-orange-700 bg-orange-50">⚙ Bidding &amp; Auto</th>',
    ].join('');

    /* Tên từng cột (row 2) */
    var colHead = [
      /* G1 */ '<th class="ppc-ch ppc-name-cell">Name</th>',
               '<th class="ppc-ch w-20">Status</th>',
      /* G2 */ '<th class="ppc-ch text-right">Impr.</th>',
               '<th class="ppc-ch text-right">Clicks</th>',
               '<th class="ppc-ch text-right">Orders</th>',
               '<th class="ppc-ch text-right">Units</th>',
      /* G3 */ '<th class="ppc-ch text-right">Ad Spend</th>',
               '<th class="ppc-ch text-right">CPC</th>',
               '<th class="ppc-ch text-right">PPC Sales</th>',
               '<th class="ppc-ch text-right">CPA</th>',
               '<th class="ppc-ch text-right">Conv.%</th>',
               '<th class="ppc-ch text-right">Same SKU%</th>',
      /* G4 */ '<th class="ppc-ch text-right">ACOS</th>',
               '<th class="ppc-ch text-right">Profit</th>',
      /* G5 */ '<th class="ppc-ch text-right">BEP ACOS</th>',
               '<th class="ppc-ch text-right">BEP Bid</th>',
               '<th class="ppc-ch text-right">Bid Rec.</th>',
               '<th class="ppc-ch text-center">Bid / Budget</th>',
               '<th class="ppc-ch text-center">Auto</th>',
    ].join('');

    return [
      /* ── TOP PANEL: Master Filter Bar ── */
      '<div id="ppc-filter-bar" class="bg-white rounded-xl shadow-sm mb-4 p-4">',
      '  <div class="flex flex-wrap items-center gap-3">',

      '  <span class="font-bold text-sm text-slate-700 mr-1">🎯 PPC Dashboard</span>',
      '  <div class="w-px h-5 bg-slate-200"></div>',

      /* Date range */
      '  <div class="flex items-center gap-1.5">',
      '    <label class="text-xs text-slate-500 font-medium">Từ:</label>',
      '    <input type="date" id="ppc-date-start" value="' + currentPpcFilters.date_range.start + '"',
      '      class="text-xs border border-slate-200 rounded-lg px-2 py-1.5 focus:ring-2 focus:ring-indigo-300 outline-none">',
      '    <label class="text-xs text-slate-500 font-medium">–</label>',
      '    <input type="date" id="ppc-date-end" value="' + currentPpcFilters.date_range.end + '"',
      '      class="text-xs border border-slate-200 rounded-lg px-2 py-1.5 focus:ring-2 focus:ring-indigo-300 outline-none">',
      '  </div>',

      /* Status toggle */
      '  <div class="flex items-center gap-1.5">',
      '    <label class="text-xs text-slate-500 font-medium">Status:</label>',
      '    <label class="text-xs flex items-center gap-1 cursor-pointer select-none">',
      '      <input type="checkbox" id="ppc-s-enabled" checked class="accent-indigo-600"> <span class="text-green-700 font-semibold">ENABLED</span>',
      '    </label>',
      '    <label class="text-xs flex items-center gap-1 cursor-pointer select-none">',
      '      <input type="checkbox" id="ppc-s-paused" checked class="accent-amber-500"> <span class="text-amber-700 font-semibold">PAUSED</span>',
      '    </label>',
      '    <label class="text-xs flex items-center gap-1 cursor-pointer select-none">',
      '      <input type="checkbox" id="ppc-s-archived" class="accent-slate-400"> <span class="text-slate-500">ARCHIVED</span>',
      '    </label>',
      '  </div>',

      /* SKU cascading search */
      '  <div class="flex items-center gap-1.5">',
      '    <label class="text-xs text-slate-500 font-medium">SKU:</label>',
      '    <input type="text" id="ppc-sku-filter" placeholder="Nhập SKU → thu hẹp Campaign..."',
      '      oninput="PpcDash.onSkuInput(this.value)"',
      '      class="text-xs border border-slate-200 rounded-lg px-2 py-1.5 w-48 focus:ring-2 focus:ring-indigo-300 outline-none">',
      '  </div>',

      /* Campaign multi-select */
      '  <div class="flex items-center gap-1.5">',
      '    <label class="text-xs text-slate-500 font-medium">Campaign:</label>',
      '    <div class="relative">',
      '      <button onclick="PpcDash.toggleCampDropdown(event)"',
      '        class="text-xs border border-slate-200 rounded-lg px-2 py-1.5 bg-white hover:bg-slate-50 flex items-center gap-1 min-w-[120px]">',
      '        <span id="ppc-camp-label">Tất cả</span><span class="ml-auto text-slate-400">▾</span>',
      '      </button>',
      '      <div id="ppc-camp-dropdown" class="hidden absolute top-full left-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg z-30 min-w-[220px] max-h-48 overflow-y-auto">',
      '        <div id="ppc-camp-options" class="p-1">',
      '          <div class="text-xs text-slate-400 px-2 py-1">Đang tải campaign...</div>',
      '        </div>',
      '      </div>',
      '    </div>',
      '  </div>',

      /* Action buttons */
      '  <div class="flex items-center gap-2 ml-auto">',
      '    <button onclick="PpcDash.applyFilters()"',
      '      class="bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-4 py-1.5 rounded-lg font-semibold transition-colors">',
      '      ⚡ Áp dụng',
      '    </button>',
      '    <button onclick="PpcDash.refreshAll()"',
      '      class="border border-slate-200 hover:bg-slate-50 text-slate-600 text-xs px-3 py-1.5 rounded-lg transition-colors" title="Làm mới">',
      '      ↻',
      '    </button>',
      '  </div>',

      '  </div>', /* end flex */
      '</div>',  /* end filter bar */

      /* ── MID PANEL: KPI Board + Time Chart ── */
      '<div class="grid grid-cols-1 xl:grid-cols-5 gap-4 mb-4">',

      '  <div class="xl:col-span-2 bg-white rounded-xl p-4 shadow-sm">',
      '    <p class="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-3">Chỉ số PPC tổng hợp</p>',
      '    <div id="ppc-kpi-board" class="grid grid-cols-3 gap-2">',
      '      <div class="col-span-3 text-center text-slate-400 text-xs py-6">⏳ Đang tải...</div>',
      '    </div>',
      '  </div>',

      '  <div class="xl:col-span-3 bg-white rounded-xl p-4 shadow-sm">',
      '    <div class="flex items-center justify-between mb-2">',
      '      <p class="text-[10px] font-bold uppercase tracking-widest text-slate-400">Xu hướng theo ngày</p>',
      '      <span class="text-[10px] text-slate-400">Trái: $ &nbsp;|&nbsp; Phải: %</span>',
      '    </div>',
      '    <canvas id="ppc-time-chart" height="145"></canvas>',
      '  </div>',

      '</div>',

      /* ── BOT PANEL: Tab Switcher + Data Grid ── */
      '<div class="bg-white rounded-xl shadow-sm overflow-hidden">',

      /* Tab bar */
      '  <div class="flex items-end border-b border-slate-200 bg-slate-50 px-4 pt-2 gap-0.5 overflow-x-auto">',
      '    ' + tabsHtml,
      '    <div class="ml-auto flex items-center gap-3 pb-2 pl-4 flex-shrink-0">',
      '      <span id="ppc-grid-status" class="text-[10px] text-slate-400"></span>',
      '    </div>',
      '  </div>',

      /* Grid — scrollable */
      '  <div style="overflow-x:auto;overflow-y:auto;max-height:600px">',
      '    <table class="w-full text-xs border-collapse" id="ppc-grid-table" style="min-width:1400px">',
      '      <thead id="ppc-grid-thead" style="position:sticky;top:0;z-index:3">',
      /* Row 1: Group headers */
      '        <tr class="text-[10px] font-bold uppercase tracking-wider border-b border-slate-300">' + groupHead + '</tr>',
      /* Row 2: Column names */
      '        <tr class="border-b border-slate-200 bg-white">' + colHead + '</tr>',
      '      </thead>',
      '      <tbody id="ppc-grid-body">',
      '        <tr><td colspan="19" class="text-center text-slate-400 py-14 text-sm">⏳ Đang tải dữ liệu...</td></tr>',
      '      </tbody>',
      '    </table>',
      '  </div>',

      '</div>',
    ].join('\n');
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 4. INJECTED STYLES
   * ══════════════════════════════════════════════════════════════════════ */
  function injectStyles() {
    if ($el('ppc-dash-styles')) return;
    var s = document.createElement('style');
    s.id = 'ppc-dash-styles';
    s.textContent = [
      /* Nhóm header chung */
      '.ppc-gh{padding:4px 8px;text-align:center;font-size:10px;border-right:2px solid #e2e8f0}',
      '.ppc-gh:last-child{border-right:none}',
      /* Column header */
      '.ppc-ch{padding:5px 8px;font-weight:600;font-size:10px;color:#64748b;background:#fff;white-space:nowrap;border-right:1px solid #f1f5f9}',
      '.ppc-ch:last-child{border-right:none}',
      /* Data cells */
      '.ppc-td{padding:5px 8px;border-bottom:1px solid #f1f5f9;white-space:nowrap;vertical-align:middle}',
      '.ppc-row:hover td{background:#fafafa}',
      /* Name cell (sticky + đủ chỗ cho badge) */
      '.ppc-name-cell{position:sticky;left:0;background:white;z-index:1;min-width:270px;max-width:340px;box-shadow:2px 0 5px rgba(0,0,0,.06)}',
      '.ppc-row:hover .ppc-name-cell{background:#fafafa}',
      /* Entity badges (SKAG hydration) */
      '.ppc-entity-badge{display:inline-block;font-size:9px;font-weight:700;padding:1px 5px;border-radius:4px;border-width:1px;border-style:solid;line-height:1.5;letter-spacing:.03em;white-space:nowrap}',
      /* Toggle arrow */
      '.ppc-toggle{cursor:pointer;user-select:none;font-size:10px;display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:3px;color:#6366f1;transition:background .1s}',
      '.ppc-toggle:hover{background:#eef2ff}',
      /* Status badge */
      '.ppc-badge{font-size:10px;padding:2px 7px;border-radius:9999px;font-weight:600;cursor:pointer;user-select:none;white-space:nowrap}',
      /* Automation toggle */
      '.auto-toggle{display:inline-flex;align-items:center;gap:4px;cursor:pointer}',
      '.auto-track{width:28px;height:15px;border-radius:8px;transition:background .2s;flex-shrink:0;position:relative}',
      '.auto-thumb{width:11px;height:11px;background:white;border-radius:50%;position:absolute;top:2px;transition:left .2s}',
      '.auto-on .auto-track{background:#6366f1}.auto-on .auto-thumb{left:15px}',
      '.auto-off .auto-track{background:#cbd5e1}.auto-off .auto-thumb{left:2px}',
      /* Tab buttons */
      '.ppc-tab-btn{transition:color .15s,border-color .15s;white-space:nowrap}',
      /* Campaign dropdown */
      '#ppc-camp-dropdown .camp-opt{display:flex;align-items:center;gap:6px;padding:4px 8px;border-radius:4px;cursor:pointer;font-size:11px}',
      '#ppc-camp-dropdown .camp-opt:hover{background:#f8fafc}',
      /* Bid/Budget input */
      '.ppc-bid-input{width:68px;border:1px solid #e2e8f0;border-radius:4px;padding:2px 4px;text-align:right;font-size:11px;outline:none}',
      '.ppc-bid-input:focus{border-color:#6366f1;box-shadow:0 0 0 2px rgba(99,102,241,.15)}',
    ].join('');
    document.head.appendChild(s);
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 5A. NAME CELL RENDERER  (Chống nhầm lẫn SKAG)
   *
   * Hydrate Entity Badges để phân biệt rõ cấp độ khi tên Ad Group và
   * Keyword trùng nhau 100% (chiến lược SKAG 1-KW-per-AdGroup).
   *
   * Badge rules:
   *   ad_group    → [AD GROUP] tím  + thumbnail + sub-text campaign_name
   *   keyword     → match_type: [EXACT] xanh | [PHRASE]/[BROAD] vàng
   *   search_term → [TERM] xám
   *   (portfolio, campaign → không badge, chỉ indent + toggle)
   * ══════════════════════════════════════════════════════════════════════ */
  function renderPpcNameCell(row, level, tabType) {
    var indent = level * 20 + 8;

    /* Nút toggle lazy-load */
    var toggleHtml = row.has_children
      ? '<span class="ppc-toggle" onclick="PpcDash.toggleLazy(\'' + esc(row.id) + '\',\'' + esc(row.entity_type) + '\',' + level + ',\'' + esc(tabType) + '\',event)" title="Mở rộng / Thu gọn">▶</span>'
      : '<span style="display:inline-block;width:16px;flex-shrink:0"></span>';

    var entityBadge    = '';
    var productThumb   = '';
    var subText        = '';

    if (row.entity_type === 'ad_group') {
      /* ── Mức 7: AD GROUP badge ── */
      entityBadge = '<span class="ppc-entity-badge bg-purple-100 text-purple-800 border-purple-200">AD GROUP</span>';

      /* Thumbnail — dùng row.image_url (top-level theo schema) */
      var imgUrl = row.image_url || (row.product_info && row.product_info.image_url) || '';
      if (imgUrl) {
        productThumb = '<img src="' + esc(imgUrl) + '"' +
          ' class="w-8 h-8 object-cover border border-slate-200 rounded mr-2 flex-shrink-0"' +
          ' onerror="this.style.display=\'none\'"' +
          ' title="' + esc(row.name) + '" alt="SKU Img">';
      }

      /* Sub-text: tên campaign cha */
      if (row.campaign_name) {
        subText = '<span class="text-[10px] text-slate-400 leading-tight block mt-0.5">↳ ' + esc(row.campaign_name) + '</span>';
      }

    } else if (row.entity_type === 'keyword') {
      /* ── Mức 8: Match Type badge ── */
      var mt    = (row.match_type || 'EXACT').toUpperCase();
      var mtCls = mt === 'EXACT'
        ? 'bg-green-100 text-green-800 border-green-200'
        : 'bg-yellow-100 text-yellow-800 border-yellow-200';
      entityBadge = '<span class="ppc-entity-badge ' + mtCls + '">' + esc(mt) + '</span>';
      /* Không hiển thị thumbnail ở keyword — thụt lề phân cấp rõ hơn */

    } else if (row.entity_type === 'search_term') {
      /* ── Mức 9: TERM badge ── */
      entityBadge = '<span class="ppc-entity-badge bg-slate-100 text-slate-500 border-slate-200">TERM</span>';
    }

    /* Assemble <td> — giữ class sticky-col-1 để cột dính bên trái */
    return '<td class="ppc-td ppc-name-cell" style="padding-left:' + indent + 'px">' +
      '<div class="flex items-center gap-1">' +
        '<span class="flex-shrink-0">' + toggleHtml + '</span>' +
        productThumb +
        '<div class="flex items-start gap-1 min-w-0">' +
          '<div class="mt-0.5 flex-shrink-0">' + entityBadge + '</div>' +
          '<div class="flex flex-col min-w-0">' +
            '<span class="font-medium text-slate-800 truncate block" style="max-width:210px" title="' + esc(row.name) + '">' + esc(row.name) + '</span>' +
            subText +
          '</div>' +
        '</div>' +
      '</div>' +
    '</td>';
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 5B. ROW RENDERER  (19 cột / 5 nhóm)
   * ══════════════════════════════════════════════════════════════════════ */
  function renderPpcRow(row, level, tabType, parentId) {
    level    = level   || 0;
    tabType  = tabType || currentPpcFilters.activeTab;
    parentId = parentId || '';

    var m  = row.metrics   || {};
    var au = row.automation || {};

    /* Status badge — clickable toggle */
    var sBg = row.status === 'ENABLED' || row.status === 'Active'
      ? 'bg-green-100 text-green-700 hover:bg-green-200'
      : row.status === 'PAUSED' || row.status === 'Paused'
        ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
        : 'bg-slate-100 text-slate-500 hover:bg-slate-200';
    var sLabel = { ENABLED:'● ENABLED', Active:'● Active', PAUSED:'⏸ PAUSED', Paused:'⏸ Paused', ARCHIVED:'🗄 Archived' }[row.status] || esc(row.status);
    var badgeHtml = '<span class="ppc-badge ' + sBg + '" onclick="PpcDash.toggleStatus(\'' + esc(row.id) + '\',\'' + esc(row.entity_type) + '\',\'' + esc(row.status) + '\')" title="Click để chuyển trạng thái">' + sLabel + '</span>';

    /* ── G4: Profit colors ── */
    var acosV  = Number(m.acos)  || 0;
    var bepV   = Number(au.break_even_acos) || 0;
    var profV  = Number(m.profit) || 0;
    var acosCls   = (bepV > 0 && acosV > bepV) ? 'text-red-500 font-bold' : 'text-green-600 font-medium';
    var profitCls = profV < 0 ? 'text-red-500 font-bold' : 'text-green-600 font-semibold';

    /* ── G5: Inline controls ── */
    var bidInput = '';
    if (tabType === 'keyword' || tabType === 'search_term') {
      var bidVal = au.current_bid != null ? Number(au.current_bid).toFixed(2) : '';
      bidInput = '<input type="number" min="0.02" step="0.01" placeholder="Bid"' +
        ' value="' + esc(bidVal) + '"' +
        ' class="ppc-bid-input"' +
        ' onchange="PpcDash.updateBid(\'' + esc(row.id) + '\',this.value)"' +
        ' title="Current Bid ($)">';
    } else if (tabType === 'campaign') {
      var budgetVal = au.daily_budget != null ? Number(au.daily_budget).toFixed(2) : '';
      bidInput = '<input type="number" min="1" step="0.5" placeholder="Budget"' +
        ' value="' + esc(budgetVal) + '"' +
        ' class="ppc-bid-input"' +
        ' onchange="PpcDash.updateBudget(\'' + esc(row.id) + '\',this.value)"' +
        ' title="Daily Budget ($)">';
    } else {
      bidInput = '<span class="text-slate-300 text-xs">—</span>';
    }

    /* ── G5: Automation toggle ── */
    var autoOn  = au.automation_status === 'on' || au.automation_status === 'Active';
    var autoHtml = '<label class="auto-toggle ' + (autoOn ? 'auto-on' : 'auto-off') + '"' +
      ' onclick="PpcDash.toggleAuto(\'' + esc(row.id) + '\',\'' + esc(row.entity_type) + '\',' + (autoOn ? 'true' : 'false') + ',this)" title="' + (autoOn ? 'Auto ON' : 'Auto OFF') + '">' +
      '<div class="auto-track"><div class="auto-thumb"></div></div>' +
      '<span class="text-[10px] ' + (autoOn ? 'text-indigo-600 font-semibold' : 'text-slate-400') + '">' + (autoOn ? 'ON' : 'OFF') + '</span>' +
      '</label>';

    /* ── Assemble <tr> ── */
    var childOfAttr = parentId ? ' data-child-of="' + esc(parentId) + '"' : '';

    var td = function (cls, content) {
      return '<td class="ppc-td ' + cls + '">' + content + '</td>';
    };
    var tdR = function (content, extra) {
      return '<td class="ppc-td text-right ' + (extra || '') + '">' + content + '</td>';
    };

    var html = '<tr class="ppc-row" id="row-' + esc(row.id) + '"' + childOfAttr +
      ' data-level="' + level + '" data-entity="' + esc(row.entity_type) + '">';

    /* G1: Name cell (Hydrated badges — chống nhầm lẫn SKAG) */
    html += renderPpcNameCell(row, level, tabType);
    /* G1: Status */
    html += td('text-center', badgeHtml);

    /* G2 Traffic */
    html += tdR(fmtNum(m.impressions));
    html += tdR(fmtNum(m.clicks));
    html += tdR(fmtNum(m.orders));
    html += tdR(fmtNum(m.units));

    /* G3 Sales */
    html += tdR(fmtMoney(m.ad_spend), 'text-red-500 font-medium');
    html += tdR(fmtMoney(m.cpc));
    html += tdR(fmtMoney(m.ppc_sales), 'text-green-600 font-medium');
    html += tdR(fmtMoney(m.cpa));
    html += tdR(fmtPct(m.conversion));
    html += tdR(m.same_sku_pct != null ? fmtPct(m.same_sku_pct) : '<span class="text-slate-300">—</span>');

    /* G4 Profitability */
    html += tdR(fmtPct(m.acos), acosCls);
    html += tdR(fmtMoney(m.profit), profitCls);

    /* G5 Automation */
    html += tdR(bepV > 0 ? fmtPct(bepV) : '<span class="text-slate-300">—</span>');
    html += tdR(au.break_even_bid != null ? fmtMoney(au.break_even_bid) : '<span class="text-slate-300">—</span>');
    html += tdR(au.bid_recommendation != null ? fmtMoney(au.bid_recommendation) : '<span class="text-slate-300">—</span>');
    html += td('text-center', bidInput);
    html += td('text-center', autoHtml);

    html += '</tr>';
    return html;
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 6. KPI BOARD
   * ══════════════════════════════════════════════════════════════════════ */
  var KPI_DEFS = [
    { key: 'ppc_sales',   label: 'PPC Sales',  fmt: 'money', cls: 'text-green-600'  },
    { key: 'ad_spend',    label: 'Ad Spend',   fmt: 'money', cls: 'text-red-500'    },
    { key: 'profit',      label: 'Profit',     fmt: 'money', cls: 'auto'            },
    { key: 'acos',        label: 'ACOS',       fmt: 'pct',   cls: 'text-amber-600'  },
    { key: 'orders',      label: 'Orders',     fmt: 'int',   cls: 'text-indigo-600' },
    { key: 'clicks',      label: 'Clicks',     fmt: 'int',   cls: 'text-slate-700'  },
    { key: 'impressions', label: 'Impr.',      fmt: 'int',   cls: 'text-slate-700'  },
    { key: 'cpc',         label: 'CPC',        fmt: 'money', cls: 'text-slate-700'  },
    { key: 'cvr',         label: 'CVR',        fmt: 'pct',   cls: 'text-teal-600'   },
  ];

  function renderKpiBoard(kpis) {
    var board = $el('ppc-kpi-board');
    if (!board) return;
    board.innerHTML = KPI_DEFS.map(function (d) {
      var v = kpis[d.key];
      var display = d.fmt === 'money' ? fmtMoney(v) : d.fmt === 'pct' ? fmtPct(v) : fmtNum(v);
      var cls = d.cls === 'auto' ? (Number(v) >= 0 ? 'text-green-600' : 'text-red-500') : d.cls;
      return '<div class="bg-slate-50 hover:bg-indigo-50 rounded-lg p-2 text-center transition-colors">' +
        '<div class="text-[9px] uppercase tracking-widest text-slate-400 font-bold">' + d.label + '</div>' +
        '<div class="text-sm font-bold mt-0.5 ' + cls + '">' + esc(display) + '</div>' +
        '</div>';
    }).join('');
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 7. TIME CHART  (Dual Y-Axis, Chart.js)
   * ══════════════════════════════════════════════════════════════════════ */
  function renderTimeChart(timeseries) {
    var canvas = $el('ppc-time-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (_chart) { _chart.destroy(); _chart = null; }

    _chart = new Chart(canvas, {
      data: {
        labels: timeseries.map(function (d) { return d.date; }),
        datasets: [
          {
            type: 'bar', label: 'PPC Sales',
            data: timeseries.map(function (d) { return d.ppc_sales; }),
            backgroundColor: 'rgba(99,102,241,.25)', borderColor: 'rgba(99,102,241,.7)', borderWidth: 1,
            yAxisID: 'yL',
          },
          {
            type: 'line', label: 'Ad Spend',
            data: timeseries.map(function (d) { return d.ad_spend; }),
            borderColor: 'rgba(239,68,68,.85)', backgroundColor: 'rgba(239,68,68,.06)',
            borderWidth: 2, pointRadius: 2, tension: .35, fill: true, yAxisID: 'yL',
          },
          {
            type: 'line', label: 'ACOS %',
            data: timeseries.map(function (d) { return d.acos; }),
            borderColor: 'rgba(245,158,11,.9)', borderWidth: 2, borderDash: [5, 3],
            pointRadius: 2, tension: .35, fill: false, yAxisID: 'yR',
          },
          {
            type: 'line', label: 'Profit',
            data: timeseries.map(function (d) { return d.profit; }),
            borderColor: 'rgba(16,185,129,.85)', borderWidth: 1.5, borderDash: [2, 2],
            pointRadius: 1.5, tension: .35, fill: false, yAxisID: 'yL',
          },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var v = ctx.parsed.y || 0;
                if (ctx.dataset.yAxisID === 'yR') return ctx.dataset.label + ': ' + v.toFixed(2) + '%';
                return ctx.dataset.label + ': $' + v.toFixed(2);
              },
            },
          },
        },
        scales: {
          yL: { type: 'linear', position: 'left',  grid: { color: 'rgba(0,0,0,.04)' }, ticks: { font: { size: 10 }, callback: function (v) { return '$' + v; } } },
          yR: { type: 'linear', position: 'right', grid: { drawOnChartArea: false },   ticks: { font: { size: 10 }, callback: function (v) { return v + '%'; } } },
          x:  { ticks: { font: { size: 9 }, maxTicksLimit: 12, maxRotation: 0 } },
        },
      },
    });
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 8. DATA LOADERS
   * ══════════════════════════════════════════════════════════════════════ */
  async function loadOverview() {
    try {
      var data = await ppcFetch('/api/ppc/overview?' + filterQs());
      renderKpiBoard(data.kpis || {});
      renderTimeChart(data.timeseries || []);
    } catch (e) {
      console.error('[PpcDash] overview error:', e);
      var b = $el('ppc-kpi-board');
      if (b) b.innerHTML = '<div class="col-span-3 text-center text-red-400 text-xs py-4">Lỗi tải KPI</div>';
    }
  }

  async function loadGrid() {
    var body = $el('ppc-grid-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="19" class="text-center text-slate-400 py-14 text-sm">⏳ Đang tải...</td></tr>';
    var statusEl = $el('ppc-grid-status');
    if (statusEl) statusEl.textContent = '';

    try {
      var url = '/api/ppc/grid?entity_type=' + encodeURIComponent(currentPpcFilters.activeTab) + '&' + filterQs();
      var data = await ppcFetch(url);
      var rows = data.rows || [];

      /* Cập nhật campaign dropdown nếu đang ở tab campaign */
      if (currentPpcFilters.activeTab === 'campaign') {
        _campaignOptions = rows.map(function (r) { return { id: r.id, name: r.name }; });
        renderCampaignOptions();
      }

      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="19" class="text-center text-slate-400 py-14">Không có dữ liệu</td></tr>';
        return;
      }
      body.innerHTML = rows.map(function (r) {
        return renderPpcRow(r, 0, currentPpcFilters.activeTab, '');
      }).join('');
      if (statusEl) statusEl.textContent = rows.length + ' dòng';
    } catch (e) {
      console.error('[PpcDash] grid error:', e);
      body.innerHTML = '<tr><td colspan="19" class="text-center text-red-400 py-10">❌ Lỗi: ' + esc(String(e.message)) + '</td></tr>';
    }
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 9. LAZY LOAD TOGGLE
   * ══════════════════════════════════════════════════════════════════════ */
  async function toggleLazy(rowId, entityType, level, tabType, event) {
    var btn      = event.currentTarget || event.target;
    var parentTr = $el('row-' + rowId);
    if (!parentTr) return;

    /* Xem trạng thái hiện tại */
    var isOpen   = btn.innerText === '▼';
    var existing = document.querySelectorAll('[data-child-of="' + rowId + '"]');

    if (existing.length > 0) {
      if (isOpen) {
        /* Thu gọn — ẩn cả cây con đệ quy */
        collapseSubtree(rowId);
        btn.innerText = '▶';
      } else {
        /* Mở lại (cấp trực tiếp) */
        existing.forEach(function (el) { el.style.display = ''; });
        btn.innerText = '▼';
      }
      return;
    }

    /* Chưa có dữ liệu → gọi API */
    btn.innerText = '…';
    try {
      var childTab = _childTabOf(entityType);
      var url = '/api/ppc/children?parent_id=' + encodeURIComponent(rowId) +
        '&type=' + encodeURIComponent(entityType) + '&' + filterQs();
      var data = await ppcFetch(url);
      var children = data.children || [];

      if (!children.length) { btn.innerText = '—'; return; }

      /* Parse & insert sibling <tr> elements */
      var tempTbody = document.createElement('tbody');
      var insertAfter = parentTr;
      children.forEach(function (child) {
        tempTbody.innerHTML = renderPpcRow(child, level + 1, childTab, rowId);
        var childTr = tempTbody.firstElementChild;
        if (childTr) {
          insertAfter.parentNode.insertBefore(childTr, insertAfter.nextSibling);
          insertAfter = childTr;
        }
      });

      btn.innerText = '▼';
    } catch (e) {
      console.error('[PpcDash] lazy error:', e);
      btn.innerText = '▶';
    }
  }

  function collapseSubtree(rowId) {
    document.querySelectorAll('[data-child-of="' + rowId + '"]').forEach(function (el) {
      el.style.display = 'none';
      var childId = el.id ? el.id.replace(/^row-/, '') : '';
      if (childId) {
        var childBtn = el.querySelector('.ppc-toggle');
        if (childBtn) childBtn.innerText = '▶';
        collapseSubtree(childId);
      }
    });
  }

  /* Mapping entity_type → tab con */
  function _childTabOf(entityType) {
    return { portfolio: 'campaign', campaign: 'ad_group', ad_group: 'keyword', keyword: 'search_term' }[entityType] || 'search_term';
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 10. CAMPAIGN DROPDOWN  (Cascading Filter)
   * ══════════════════════════════════════════════════════════════════════ */
  function renderCampaignOptions() {
    var container = $el('ppc-camp-options');
    if (!container) return;
    var selected = currentPpcFilters.campaign_filter.campaign_ids;

    if (!_campaignOptions.length) {
      container.innerHTML = '<div class="text-xs text-slate-400 px-2 py-2">Không có campaign</div>';
      return;
    }

    var allChecked = selected.length === 0;
    container.innerHTML =
      '<div class="camp-opt" onclick="PpcDash.selectAllCamps()">' +
      '<input type="checkbox" ' + (allChecked ? 'checked' : '') + ' class="accent-indigo-600"> <span>Tất cả</span></div>' +
      _campaignOptions.map(function (c) {
        var chk = selected.indexOf(c.id) >= 0;
        return '<div class="camp-opt" onclick="PpcDash.toggleCamp(\'' + esc(c.id) + '\')">' +
          '<input type="checkbox" ' + (chk ? 'checked' : '') + ' class="accent-indigo-600"> ' +
          '<span class="truncate" title="' + esc(c.name) + '">' + esc(c.name) + '</span></div>';
      }).join('');

    var label = $el('ppc-camp-label');
    if (label) label.textContent = selected.length ? selected.length + ' campaign' : 'Tất cả';
  }

  function closeCampDropdown() {
    var dd = $el('ppc-camp-dropdown');
    if (dd) dd.classList.add('hidden');
    document.removeEventListener('click', closeCampDropdown);
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 11. DOM INJECTION
   * ══════════════════════════════════════════════════════════════════════ */
  function ensureDashboard() {
    if (_dashInited) return;
    _dashInited = true;
    var page = $el('page-ppcdash');
    if (!page) return;
    if (!$el('ppc-dashboard')) {
      var div = document.createElement('div');
      div.id  = 'ppc-dashboard';
      div.innerHTML = buildDashboardHtml();
      page.appendChild(div);
    }
    injectStyles();
  }

  /* ══════════════════════════════════════════════════════════════════════
   * 12. PUBLIC API  window.PpcDash
   * ══════════════════════════════════════════════════════════════════════ */
  window.PpcDash = {

    applyFilters: function () {
      var s = $el('ppc-date-start'); if (s) currentPpcFilters.date_range.start = s.value;
      var e = $el('ppc-date-end');   if (e) currentPpcFilters.date_range.end   = e.value;
      var st = [];
      if ($el('ppc-s-enabled')  && $el('ppc-s-enabled').checked)  st.push('ENABLED');
      if ($el('ppc-s-paused')   && $el('ppc-s-paused').checked)   st.push('PAUSED');
      if ($el('ppc-s-archived') && $el('ppc-s-archived').checked) st.push('ARCHIVED');
      currentPpcFilters.status_filter = st;
      var sku = $el('ppc-sku-filter');
      if (sku) currentPpcFilters.product_filter.value = sku.value.trim();
      this.refreshAll();
    },

    refreshAll: function () { loadOverview(); loadGrid(); },

    switchTab: function (tab) {
      currentPpcFilters.activeTab = tab;
      document.querySelectorAll('.ppc-tab-btn').forEach(function (btn) {
        var active = btn.id === 'ppc-tab-' + tab;
        btn.className = 'ppc-tab-btn text-xs px-3 py-2 rounded-t-lg border-b-2 font-medium transition-colors ' +
          (active ? 'border-indigo-600 text-indigo-600 bg-white' : 'border-transparent text-slate-500 hover:text-indigo-600');
      });
      loadGrid();
    },

    /* Cascading: SKU input → tự lọc campaign */
    onSkuInput: function (val) {
      currentPpcFilters.product_filter.value = val.trim();
      /* Debounce nhẹ */
      clearTimeout(this._skuTimer);
      this._skuTimer = setTimeout(function () { loadGrid(); }, 420);
    },

    /* Campaign dropdown */
    toggleCampDropdown: function (event) {
      event.stopPropagation();
      var dd = $el('ppc-camp-dropdown');
      if (!dd) return;
      var isHidden = dd.classList.contains('hidden');
      dd.classList.toggle('hidden');
      if (isHidden) {
        renderCampaignOptions();
        setTimeout(function () { document.addEventListener('click', closeCampDropdown); }, 10);
      }
    },

    selectAllCamps: function () {
      currentPpcFilters.campaign_filter.campaign_ids = [];
      renderCampaignOptions();
    },

    toggleCamp: function (campId) {
      var ids = currentPpcFilters.campaign_filter.campaign_ids;
      var idx = ids.indexOf(campId);
      if (idx >= 0) ids.splice(idx, 1); else ids.push(campId);
      renderCampaignOptions();
    },

    toggleLazy: toggleLazy,

    /* Status badge toggle */
    toggleStatus: function (id, entityType, currentStatus) {
      var next = (currentStatus === 'ENABLED' || currentStatus === 'Active') ? 'PAUSED' : 'ENABLED';
      console.log('[PpcDash] toggleStatus', id, currentStatus, '→', next);
      /* TODO: PATCH /api/ppc/{entityType}/{id}/status */
    },

    /* Automation toggle */
    toggleAuto: function (id, entityType, isOn, labelEl) {
      var newOn = !isOn;
      var wrapper = labelEl;
      wrapper.classList.toggle('auto-on', newOn);
      wrapper.classList.toggle('auto-off', !newOn);
      var txt = wrapper.querySelector('span:last-child');
      if (txt) { txt.textContent = newOn ? 'ON' : 'OFF'; txt.className = 'text-[10px] ' + (newOn ? 'text-indigo-600 font-semibold' : 'text-slate-400'); }
      console.log('[PpcDash] toggleAuto', id, '→', newOn ? 'on' : 'off');
      /* TODO: PATCH /api/ppc/{entityType}/{id}/automation */
    },

    updateBid: function (id, value) {
      console.log('[PpcDash] updateBid', id, parseFloat(value));
      /* TODO: PATCH /api/ppc/keyword/{id}/bid */
    },

    updateBudget: function (id, value) {
      console.log('[PpcDash] updateBudget', id, parseFloat(value));
      /* TODO: PATCH /api/ppc/campaign/{id}/budget */
    },

    addNegative: function (term) {
      if (confirm('Thêm "' + term + '" vào Negative Keywords?')) {
        console.log('[PpcDash] addNegative:', term);
        /* TODO: POST /api/ppc/negatives */
      }
    },

    addToKw: function (term) {
      if (confirm('Thêm "' + term + '" vào Campaign?')) {
        console.log('[PpcDash] addToKeywords:', term);
        /* TODO: POST /api/ppc/keywords */
      }
    },
  };

  /* ══════════════════════════════════════════════════════════════════════
   * 13. INIT — patch App.go() để xử lý route 'ppcdash'
   * ══════════════════════════════════════════════════════════════════════ */
  function patchApp() {
    var _origGo = window.App.go.bind(window.App);

    window.App.go = function (page) {
      if (page !== 'ppcdash') { _origGo(page); return; }

      document.querySelectorAll('[id^="page-"]').forEach(function (s) { s.classList.add('hidden'); });
      var sec = $el('page-ppcdash');
      if (sec) sec.classList.remove('hidden');
      document.querySelectorAll('.nav-item').forEach(function (n) {
        n.classList.toggle('active', n.dataset.page === 'ppcdash');
      });
      var titleEl = $el('page-title');
      if (titleEl) titleEl.textContent = 'PPC Dashboard';

      ensureDashboard();
      PpcDash.refreshAll();
    };
  }

  function init() {
    if (window.App) {
      patchApp();
    } else {
      var attempts = 0;
      var poll = setInterval(function () {
        if (window.App || ++attempts > 60) { clearInterval(poll); if (window.App) patchApp(); }
      }, 50);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
