/* Phase 3 — render_performance.js
 * Kiến trúc Progressive Disclosure 8-Level (Mức 4-8) cho Dashboard SellerVision.
 * JavaScript THUẦN, không framework. Mức 1-3 (Login/Sidebar/Account Selector)
 * thuộc index.html/app.js gốc — KHÔNG đụng tới ở đây.
 *
 * Cách hoạt động (KHÔNG sửa app.js gốc):
 *   - Nạp SAU app.js (patch_frontend.py chèn <script src="/static/render_performance.js">).
 *   - Tiêm thêm DOM cho Top Panel (Mức 4), Popover (Mức 6) ngay lần load đầu.
 *   - Ghi đè App.loadDashboard / App.loadPeriods / App.loadProductPerf để dùng
 *     payload lồng nhau (product_info / metrics / detailed_pnl) từ
 *     GET /api/analytics/dashboard/summary (analytics_aggregator.py Phase 3).
 *   - Backend Phase 3 không trả timeseries/marketplace_breakdown -> View
 *     "Chart"/"Map" hiển thị canvas rỗng (không lỗi, chỉ tạm trống).
 *
 * Bản đồ kiến trúc:
 *   Mức 4  Top Panel: ensureTopPanel()      — Search + Date Picker + View Switcher
 *   Mức 5  KPI Tiles: renderTiles()/tileCard() — #period-cards
 *   Mức 6  Drilldown: showPopover()/renderPnlTree() (6A) · selectPeriod() (6B)
 *   Mức 7  Data Grid: ensureGridContainer()/renderGridContainer()/renderTab()
 *   Mức 8  Rows:      renderProductRow()/renderOrderRow()
 */
(function () {
  'use strict';

  // ════════════════════════════════════════════════════════════════════════
  // Helper định dạng
  // ════════════════════════════════════════════════════════════════════════
  var fmtMoney = function (v) {
    var n = Number(v) || 0;
    var sign = n < 0 ? '-' : '';
    return sign + '$' + Math.abs(n).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  var fmtNum = function (v) { return (Number(v) || 0).toLocaleString('en-US'); };

  // Escape HTML — tránh title/SKU chứa ký tự đặc biệt phá vỡ template string
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };

  // Logic màu sắc động kiểu Sellerboard: > 0 -> xanh + '+'  |  < 0 -> đỏ + '-'
  function pnl(v, isPercent) {
    var n = Number(v) || 0;
    var sign = n > 0 ? '+' : (n < 0 ? '-' : '');
    var body = isPercent ? Math.abs(n).toFixed(1) + '%' : fmtMoney(Math.abs(n));
    var cls = n > 0 ? 'text-green-600 font-semibold'
            : n < 0 ? 'text-red-600 font-semibold'
            : 'text-slate-400';
    return '<span class="' + cls + '">' + sign + body + '</span>';
  }

  // Badge ASIN/SKU nhỏ gọn, click để copy nhanh
  function badge(text, label) {
    if (!text) return '';
    return '<button type="button" onclick="event.stopPropagation();navigator.clipboard&&navigator.clipboard.writeText(\'' +
      esc(text) + '\');this.classList.add(\'ring-1\',\'ring-green-400\');' +
      'var b=this;setTimeout(function(){b.classList.remove(\'ring-1\',\'ring-green-400\')},800)" ' +
      'title="Click để copy ' + esc(label) + '" ' +
      'class="text-[10px] font-mono bg-slate-100 hover:bg-slate-200 text-slate-500 ' +
      'rounded px-1.5 py-0.5 mr-1 cursor-pointer select-all">' + esc(text) + '</button>';
  }

  // Ảnh thumb 40x40: ưu tiên product_info.image_url (DB cục bộ); fallback ảnh
  // widget Amazon theo ASIN; lỗi cả 2 -> ô chữ cái đầu của title.
  function thumb(info) {
    var initial = esc((info.title || info.sku || '?').charAt(0).toUpperCase());
    var fallback = '<div class="w-10 h-10 rounded-lg bg-slate-200 hidden ' +
      'items-center justify-center text-slate-500 text-xs font-bold shrink-0">' + initial + '</div>';
    var src = info.image_url ||
      (info.asin ? 'https://ws-na.amazon-adsystem.com/widgets/q?_encoding=UTF8&ASIN=' +
        esc(info.asin) + '&Format=_SL64_&ID=AsinImage&MarketPlace=US&ServiceVersion=20070822&WS=1' : '');
    if (!src) return fallback.replace('hidden', 'flex');
    return '<img loading="lazy" src="' + esc(src) + '" ' +
      'class="w-10 h-10 rounded-lg object-contain bg-slate-100 border border-slate-200 shrink-0" ' +
      'onerror="this.style.display=\'none\';this.nextElementSibling.classList.remove(\'hidden\');' +
      'this.nextElementSibling.classList.add(\'flex\')">' + fallback;
  }

  // ════════════════════════════════════════════════════════════════════════
  // State module — toàn bộ điều khiển luồng 8-Level nằm ở đây
  // ════════════════════════════════════════════════════════════════════════
  var state = {
    activeTab: 'tiles',        // Mức 4: View Switcher — tiles | chart | pnl | trends | map
    search: '',                 // Mức 4: Search Bar (SKU/ASIN/Campaign)
    rangeOverride: null,        // Mức 4: Date Picker tuỳ chỉnh {start,end}
    gridTab: 'products',        // Mức 7: products | orders
    gridPeriodKey: 'today',     // Mức 6B: kỳ đang đổ xuống Bottom Panel
    gridTitle: 'Hôm nay',
    periods: [],
    productsRaw: [],
    ordersRaw: [],
    _rowSeq: 0,
  };

  // ════════════════════════════════════════════════════════════════════════
  // Mức 4 — Top Panel: Search Bar + Date Picker + View Switcher
  // ════════════════════════════════════════════════════════════════════════
  var VIEWS = [
    { key: 'tiles', label: '🗂 Tiles' },
    { key: 'chart', label: '📈 Chart' },
    { key: 'pnl', label: '🧾 P&L' },
    { key: 'trends', label: '📊 Trends' },
    { key: 'map', label: '🗺 Map' },
  ];

  function ensureTopPanel() {
    if (document.getElementById('sv8-top-panel')) return;
    var anchor = document.getElementById('period-cards');
    if (!anchor) return;
    var panel = document.createElement('div');
    panel.id = 'sv8-top-panel';
    panel.className = 'bg-white rounded-xl p-3 shadow-sm mb-4 flex flex-wrap items-center gap-3';
    panel.innerHTML =
      '<input id="sv8-search" type="text" placeholder="🔎 Tìm SKU / ASIN / Campaign..." ' +
        'class="text-sm border border-slate-200 rounded-lg px-3 py-1.5 flex-1 min-w-[180px]" />' +
      '<div class="flex items-center gap-1.5 text-sm">' +
        '<input id="sv8-date-start" type="date" class="border border-slate-200 rounded-lg px-2 py-1.5 text-xs" />' +
        '<span class="text-slate-400">→</span>' +
        '<input id="sv8-date-end" type="date" class="border border-slate-200 rounded-lg px-2 py-1.5 text-xs" />' +
      '</div>' +
      '<div id="sv8-view-switcher" class="flex gap-1 bg-slate-100 rounded-lg p-1"></div>';
    anchor.parentNode.insertBefore(panel, anchor);

    document.getElementById('sv8-search').addEventListener('input', function (e) {
      state.search = e.target.value.trim().toLowerCase();
      renderGridBody();
    });
    var onDateChange = function () {
      var s = document.getElementById('sv8-date-start').value;
      var e = document.getElementById('sv8-date-end').value;
      if (!s || !e) return;
      state.rangeOverride = { start: s, end: e };
      state.gridTitle = s + ' → ' + e;
      loadGrid();
    };
    document.getElementById('sv8-date-start').addEventListener('change', onDateChange);
    document.getElementById('sv8-date-end').addEventListener('change', onDateChange);

    var switcher = document.getElementById('sv8-view-switcher');
    switcher.innerHTML = VIEWS.map(function (v) {
      return '<button type="button" data-view="' + v.key + '" ' +
        'class="dash-tab text-xs px-3 py-1.5 rounded-md' + (v.key === state.activeTab ? ' active' : '') + '" ' +
        'onclick="SV8.switchView(\'' + v.key + '\')">' + v.label + '</button>';
    }).join('');
  }

  function applyActiveView() {
    var charts = document.querySelector('#sales-chart') ? document.querySelector('#sales-chart').closest('.grid') : null;
    var tiles = document.getElementById('period-cards');
    var grid = document.getElementById('sv8-grid-card');
    var pnlView = document.getElementById('sv8-pnl-view');

    var show = function (el, on) { if (el) el.classList.toggle('hidden', !on); };
    show(tiles, state.activeTab === 'tiles');
    show(charts, state.activeTab === 'tiles' || state.activeTab === 'chart' || state.activeTab === 'map');
    // Grid (Mức 7) chỉ hiển thị ở view Tiles — các view khác (chart/pnl/trends/map) có view riêng.
    show(grid, state.activeTab === 'tiles');
    show(pnlView, state.activeTab === 'pnl');

    if (state.activeTab === 'pnl') renderPnlView();
    if (state.activeTab === 'trends' || state.activeTab === 'map') ensurePlaceholderView();
    else removePlaceholderView();

    document.querySelectorAll('#sv8-view-switcher .dash-tab').forEach(function (b) {
      b.classList.toggle('active', b.dataset.view === state.activeTab);
    });
  }

  function ensurePlaceholderView() {
    var ph = document.getElementById('sv8-placeholder-view');
    var anchor = document.getElementById('period-cards');
    var msg = state.activeTab === 'trends'
      ? '📊 Trends (Timeseries) — Backend Phase 3 chưa trả dữ liệu theo ngày, sẽ bổ sung ở Phase 4.'
      : '🗺 Map (Marketplace Breakdown) — Backend Phase 3 chưa trả dữ liệu theo sàn, sẽ bổ sung ở Phase 4.';
    if (!ph) {
      ph = document.createElement('div');
      ph.id = 'sv8-placeholder-view';
      ph.className = 'bg-white rounded-xl p-8 shadow-sm text-center text-slate-400 text-sm mb-4';
      anchor.parentNode.insertBefore(ph, anchor.nextSibling);
    }
    ph.textContent = msg;
    ph.classList.remove('hidden');
  }
  function removePlaceholderView() {
    var ph = document.getElementById('sv8-placeholder-view');
    if (ph) ph.classList.add('hidden');
  }

  // ════════════════════════════════════════════════════════════════════════
  // Mức 5 — KPI Tiles Container (Mid Panel)
  // ════════════════════════════════════════════════════════════════════════
  var PERIOD_COLORS = ['from-sky-500 to-sky-600', 'from-cyan-500 to-cyan-600', 'from-teal-500 to-teal-600',
    'from-emerald-500 to-emerald-600', 'from-slate-500 to-slate-600'];

  function renderTiles(periods) {
    var el = document.getElementById('period-cards');
    if (!el) return;
    if (!periods.length) {
      el.innerHTML = '<div class="col-span-full text-center text-slate-400 py-6">Chưa có dữ liệu kỳ nào</div>';
      return;
    }
    el.innerHTML = periods.map(function (p, i) {
      return tileCard(p, PERIOD_COLORS[i % PERIOD_COLORS.length]);
    }).join('');
  }

  function tileCard(p, gradient) {
    var delta = function (v) {
      if (v === null || v === undefined) return '';
      return '<span class="text-xs font-semibold ' + (v >= 0 ? 'text-emerald-600' : 'text-red-500') + ' ml-1.5">' +
        (v >= 0 ? '▲' : '▼') + ' ' + Math.abs(v) + '%</span>';
    };
    var active = state.gridPeriodKey === p.key && !state.rangeOverride;
    return '<div class="bg-white rounded-xl shadow-sm overflow-hidden flex flex-col period-tile' +
        (active ? ' ring-2 ring-indigo-400' : '') + '">' +
      '<div class="bg-gradient-to-r ' + gradient + ' text-white px-4 py-3 flex items-start justify-between gap-2">' +
        '<div class="cursor-pointer" onclick="SV8.selectPeriod(\'' + p.key + '\',\'' + esc(p.label) + '\')" title="Xem chi tiết kỳ này ở bảng dưới">' +
          '<div class="text-sm font-semibold hover:underline">' + esc(p.label) + '</div>' +
          '<div class="text-xs text-white/80">' + esc(p.range_label) + '</div>' +
        '</div>' +
        '<button type="button" onclick="SV8.showTileMore(event,\'' + p.key + '\')" ' +
          'class="text-white/80 hover:text-white text-xs bg-white/10 hover:bg-white/20 rounded px-1.5 py-0.5" title="Chi tiết P&L">More</button>' +
      '</div>' +
      '<div class="p-4 flex-1 flex flex-col gap-3 text-sm">' +
        '<div><div class="text-xs text-slate-400">Sales</div>' +
          '<div class="text-xl font-bold">' + fmtMoney(p.sales) + delta(p.sales_delta_pct) + '</div></div>' +
        '<div class="grid grid-cols-2 gap-y-2 gap-x-3">' +
          '<div><div class="text-xs text-slate-400">Orders / Units</div><div class="font-medium">' + fmtNum(p.orders) + ' / ' + fmtNum(p.units) + '</div></div>' +
          '<div><div class="text-xs text-slate-400">Refunds</div><div class="font-medium">' + fmtNum(p.refunds) + '</div></div>' +
          '<div><div class="text-xs text-slate-400">Adv. cost</div><div class="font-medium text-red-500">-' + fmtMoney(Math.abs(p.adv_cost)) + '</div></div>' +
          '<div><div class="text-xs text-slate-400">Est. payout</div><div class="font-medium">' + fmtMoney(p.est_payout) + '</div></div>' +
        '</div>' +
        '<div class="mt-auto pt-3 border-t border-slate-100">' +
          '<div class="text-xs text-slate-400">Net profit</div>' +
          '<div class="text-lg font-bold ' + (p.net_profit >= 0 ? 'text-emerald-600' : 'text-red-500') + '">' +
            fmtMoney(p.net_profit) + delta(p.net_profit_delta_pct) + '</div>' +
        '</div>' +
      '</div></div>';
  }

  // ════════════════════════════════════════════════════════════════════════
  // Mức 6 — Drill-down / Detail View
  //   6A: TileMorePopover (More / "...")  — cây P&L đệ quy, toggle {>}
  //   6B: Click tiêu đề Tile -> đổ dữ liệu kỳ đó xuống Bottom Panel (Mức 7)
  // ════════════════════════════════════════════════════════════════════════
  var PNL_LABELS = {
    sales: 'Doanh thu', cogs: 'COGS (Chi phí gốc)', amazon_fees: 'Phí Amazon',
    referral_fee: 'Referral fee', fba_fee: 'FBA fee', ads: 'Quảng cáo',
    promo: 'Khuyến mãi', refund_cost: 'Hoàn tiền', shipping: 'Vận chuyển',
    net_profit: 'Lợi nhuận ròng', gross_profit: 'Lợi nhuận gộp',
    expenses: 'Chi phí khác', est_payout: 'Tiền về dự kiến',
    sponsored_products: 'Sponsored Products', sponsored_brands: 'Sponsored Brands',
    sponsored_brands_video: 'Sponsored Brands Video', sponsored_display: 'Sponsored Display',
    google_ads: 'Google Ads', facebook_ads: 'Facebook Ads',
  };

  function ensurePopover() {
    if (document.getElementById('drilldown-popover')) return;
    var pop = document.createElement('div');
    pop.id = 'drilldown-popover';
    pop.className = 'hidden absolute bg-white shadow-xl border border-slate-200 rounded-lg z-50 text-sm min-w-[260px]';
    document.body.appendChild(pop);
    // Click ra ngoài -> đóng popover
    document.addEventListener('click', function (e) {
      if (pop.classList.contains('hidden')) return;
      if (pop.contains(e.target)) return;
      pop.classList.add('hidden');
    });
  }

  // Thuật toán đệ quy DOM: lặp qua detailed_pnl tạo <tr data-parent="X">.
  function renderPnlTree(tree, parentId) {
    var html = '';
    Object.keys(tree).forEach(function (key) {
      var node = tree[key] || {};
      var id = 'pnl-' + (++state._rowSeq);
      var hasChildren = node.children && Object.keys(node.children).length;
      var label = PNL_LABELS[key] || key;
      var hiddenAttr = parentId ? ' data-parent="' + parentId + '" style="display:none"' : '';
      html += '<tr' + hiddenAttr + ' class="border-b last:border-0">' +
        '<td class="py-1.5 px-3">' +
          (hasChildren
            ? '<button type="button" class="mr-1 w-4 inline-block text-slate-400" onclick="SV8.togglePnlRow(\'' + id + '\')" id="toggle-' + id + '">▸</button>'
            : '<span class="mr-1 w-4 inline-block"></span>') +
          esc(label) +
        '</td>' +
        '<td class="py-1.5 px-3 text-right">' + pnl(node.total) + '</td></tr>';
      if (hasChildren) {
        html += renderPnlTree(node.children, id);
      }
    });
    return html;
  }

  window.SV8 = window.SV8 || {};

  SV8.togglePnlRow = function (id) {
    var rows = document.querySelectorAll('tr[data-parent="' + id + '"]');
    var btn = document.getElementById('toggle-' + id);
    var willShow = rows.length && rows[0].style.display === 'none';
    rows.forEach(function (r) { r.style.display = willShow ? '' : 'none'; });
    if (btn) btn.textContent = willShow ? '▾' : '▸';
  };

  // Mức 6A: mở popover tại vị trí chuột với cây detailed_pnl
  // extraRows: [{label, value, isPercent}] -> render thêm các chỉ số tỉ lệ
  // (Margin, ROI, Real ACOS, % Refunds...) bên dưới cây P&L.
  // footerNote: dòng chú thích nhỏ ở cuối (vd: chỉ số chưa có nguồn dữ liệu).
  function showPopover(evt, tree, titleText, extraRows, footerNote) {
    ensurePopover();
    var pop = document.getElementById('drilldown-popover');
    var extraHtml = '';
    if (extraRows && extraRows.length) {
      extraHtml = '<tr><td colspan="2" class="pt-2 pb-1 px-3 text-[11px] font-semibold text-slate-400 border-t">Tỉ lệ</td></tr>' +
        extraRows.map(function (r) {
          var val = (r.value === null || r.value === undefined)
            ? '<span class="text-slate-400">—</span>'
            : pnl(r.value, r.isPercent);
          return '<tr class="border-b last:border-0"><td class="py-1.5 px-3">' + esc(r.label) + '</td>' +
            '<td class="py-1.5 px-3 text-right">' + val + '</td></tr>';
        }).join('');
    }
    var footerHtml = footerNote
      ? '<div class="px-3 py-2 border-t text-[11px] text-slate-400">' + esc(footerNote) + '</div>'
      : '';
    pop.innerHTML =
      '<div class="px-3 py-2 border-b font-semibold flex items-center justify-between">' +
        '<span>' + esc(titleText) + '</span>' +
        '<button type="button" class="text-slate-400 hover:text-slate-700" onclick="document.getElementById(\'drilldown-popover\').classList.add(\'hidden\')">✕</button>' +
      '</div>' +
      '<table class="w-full"><tbody>' + renderPnlTree(tree, null) + extraHtml + '</tbody></table>' +
      footerHtml;
    var x = evt.clientX, y = evt.clientY;
    var maxX = window.innerWidth - 280, maxY = window.innerHeight - 40;
    pop.style.left = Math.min(x, maxX) + window.scrollX + 'px';
    pop.style.top = Math.min(y, maxY) + window.scrollY + 'px';
    pop.classList.remove('hidden');
    evt.stopPropagation();
  }

  // Mức 6A — tile "More": xây cây P&L đầy đủ kiểu Sellerboard từ dữ liệu
  // thẻ kỳ (period card) — backend/app/services/profit.py period_overview().
  SV8.showTileMore = function (evt, key) {
    var p = state.periods.find(function (x) { return x.key === key; });
    if (!p) return;
    var ab = p.ads_breakdown || {};
    var adsChildren = {
      sponsored_products: { total: ab.sponsored_products || 0 },
      sponsored_brands: { total: ab.sponsored_brands || 0 },
      sponsored_brands_video: { total: ab.sponsored_brands_video || 0 },
      sponsored_display: { total: ab.sponsored_display || 0 },
    };
    if (ab.google_ads) adsChildren.google_ads = { total: ab.google_ads };
    if (ab.facebook_ads) adsChildren.facebook_ads = { total: ab.facebook_ads };

    var tree = {
      sales: { total: p.sales },
      promo: { total: p.promo },
      amazon_fees: { total: p.amazon_fees, children: splitAmazonFees(p.sales, p.amazon_fees) },
      cogs: { total: p.cost_of_goods },
      shipping: { total: p.shipping },
      gross_profit: { total: p.gross_profit },
      ads: { total: p.ads, children: adsChildren },
      refund_cost: { total: p.refund_cost },
      expenses: { total: p.expenses },
      net_profit: { total: p.net_profit },
      est_payout: { total: p.est_payout },
    };
    var extraRows = [
      { label: 'Margin', value: p.margin, isPercent: true },
      { label: 'ROI', value: p.roi, isPercent: true },
      { label: 'Real ACOS', value: p.real_acos, isPercent: true },
      { label: '% Refunds', value: p.refunds_pct, isPercent: true },
    ];
    var footerNote = 'Sessions, % Unit session, Active subscriptions (SnS), BSR, ' +
      'Sellable returns: chưa có nguồn dữ liệu từ Amazon API.';
    showPopover(evt, tree, p.label + ' — P&L', extraRows, footerNote);
  };

  // Mức 6A — row "...": cây P&L chi tiết từ detailed_pnl backend (Mức 8)
  SV8.showRowMore = function (evt, identifier, kind) {
    var list = kind === 'orders' ? state.ordersRaw : state.productsRaw;
    var row;
    if (kind === 'orders') {
      row = list.find(function (o) { return (o.order_number + '|' + o.sku) === identifier; });
      if (!row) return;
      var tree = {
        sales: { total: row.sales },
        cogs: { total: row.cost_of_goods },
        amazon_fees: { total: row.amazon_fees, children: splitAmazonFees(row.sales, row.amazon_fees) },
        promo: { total: row.promo },
        refund_cost: { total: row.refund_cost },
        shipping: { total: row.shipping },
        net_profit: { total: row.net_profit },
      };
      showPopover(evt, tree, row.sku + ' — P&L');
      return;
    }
    row = list.find(function (p) { return p.identifier === identifier; });
    if (!row) return;
    showPopover(evt, row.detailed_pnl, row.identifier + ' — P&L');
  };

  function splitAmazonFees(sales, amazonFees) {
    var referral = -round2(Math.abs(sales) * 0.165);
    if (Math.abs(referral) > Math.abs(amazonFees)) referral = amazonFees;
    return { referral_fee: referral, fba_fee: round2(amazonFees - referral) };
  }
  function round2(n) { return Math.round((Number(n) || 0) * 100) / 100; }

  // Mức 6B: click tiêu đề tile -> đổ dữ liệu kỳ đó xuống Bottom Panel (Mức 7)
  SV8.selectPeriod = function (key, label) {
    state.gridPeriodKey = key;
    state.gridTitle = label;
    state.rangeOverride = null;
    document.getElementById('sv8-date-start').value = '';
    document.getElementById('sv8-date-end').value = '';
    renderTiles(state.periods); // cập nhật highlight tile đang chọn
    loadGrid();
  };

  // ════════════════════════════════════════════════════════════════════════
  // Mức 7 — Data Grid Container (Bottom Panel): TabSwitcher Products/Orders
  // ════════════════════════════════════════════════════════════════════════
  var PRODUCTS_HEAD =
    '<tr class="text-left">' +
    '<th class="py-2 px-2">Sản phẩm</th>' +
    '<th class="text-right px-2">Số lượng</th>' +
    '<th class="text-right px-2">Doanh thu</th>' +
    '<th class="text-right px-2">COGS</th>' +
    '<th class="text-right px-2">Phí Amazon</th>' +
    '<th class="text-right px-2">Quảng cáo</th>' +
    '<th class="text-right px-2">Lợi nhuận ròng</th>' +
    '<th class="text-right px-2">ROI</th></tr>';

  var ORDERS_HEAD =
    '<tr class="text-left">' +
    '<th class="py-2 px-2">Order</th>' +
    '<th class="text-right px-2">SKU</th>' +
    '<th class="text-right px-2">Doanh thu</th>' +
    '<th class="text-right px-2">Lợi nhuận ròng</th>' +
    '<th class="text-right px-2"></th></tr>';

  // Mức 7: khung TabSwitcher + tiêu đề động — chuyển đổi từ card "Hiệu suất
  // sản phẩm chi tiết" cũ trong index.html sang Data Grid Container 8-Level.
  function ensureGridContainer() {
    var tbody = document.getElementById('top-products');
    if (!tbody) return null;
    var card = tbody.closest('.bg-white.rounded-xl.p-5.shadow-sm') || tbody.closest('.bg-white');
    if (!card) return null;
    card.id = 'sv8-grid-card';
    if (card.dataset.sv8Ready) return card;
    card.dataset.sv8Ready = '1';
    card.innerHTML =
      '<div class="flex justify-between items-center border-b pb-3 mb-3">' +
        '<h3 id="grid-dynamic-title" class="font-bold text-lg"></h3>' +
        '<div class="flex space-x-2">' +
          '<button type="button" class="tab-btn dash-tab text-xs px-4 py-1.5 rounded-lg" data-tab="products" onclick="SV8.renderTab(\'products\')">Products</button>' +
          '<button type="button" class="tab-btn dash-tab text-xs px-4 py-1.5 rounded-lg" data-tab="orders" onclick="SV8.renderTab(\'orders\')">Order Items</button>' +
        '</div>' +
      '</div>' +
      '<div class="overflow-x-auto">' +
        '<table id="datagrid-table" class="w-full text-sm whitespace-nowrap">' +
          '<thead id="datagrid-head" class="text-slate-500 border-b"></thead>' +
          '<tbody id="datagrid-body"></tbody>' +
          '<tfoot id="datagrid-foot"></tfoot>' +
        '</table>' +
      '</div>';
    return card;
  }

  // Mức 7: chuyển tab Products <-> Order Items, nạp dữ liệu nếu chưa có
  SV8.renderTab = function (which) {
    state.gridTab = which;
    document.querySelectorAll('#sv8-grid-card .tab-btn').forEach(function (b) {
      b.classList.toggle('active', b.dataset.tab === which);
    });
    var head = document.getElementById('datagrid-head');
    head.innerHTML = which === 'orders' ? ORDERS_HEAD : PRODUCTS_HEAD;
    var needData = which === 'orders' ? !state._ordersLoaded : !state._productsLoaded;
    if (needData) { loadGrid(); return; }
    renderGridBody();
  };

  function renderGridContainer() {
    var card = ensureGridContainer();
    if (!card) return;
    document.getElementById('grid-dynamic-title').textContent = state.gridTitle;
    document.querySelectorAll('#sv8-grid-card .tab-btn').forEach(function (b) {
      b.classList.toggle('active', b.dataset.tab === state.gridTab);
    });
    document.getElementById('datagrid-head').innerHTML = state.gridTab === 'orders' ? ORDERS_HEAD : PRODUCTS_HEAD;
  }

  // ════════════════════════════════════════════════════════════════════════
  // Mức 8 — Row Level & SKU Drill-down
  // ════════════════════════════════════════════════════════════════════════
  function renderGridBody() {
    var body = document.getElementById('datagrid-body');
    var foot = document.getElementById('datagrid-foot');
    if (!body) return;
    var q = state.search;

    if (state.gridTab === 'orders') {
      var orders = state.ordersRaw.filter(function (o) {
        if (!q) return true;
        return (o.order_number_raw + ' ' + o.sku + ' ' + o.asin).toLowerCase().indexOf(q) !== -1;
      });
      if (!orders.length) {
        body.innerHTML = '<tr><td colspan="5" class="py-8 text-center text-slate-400">Không có Order Items cho khoảng thời gian này</td></tr>';
        foot.innerHTML = '';
        return;
      }
      body.innerHTML = orders.map(renderOrderRow).join('');
      foot.innerHTML = '';
      return;
    }

    var rows = state.productsRaw.filter(function (p) {
      if (!q) return true;
      var info = p.product_info || {};
      return (info.asin + ' ' + info.sku + ' ' + info.title).toLowerCase().indexOf(q) !== -1;
    });
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-slate-400">Không có dữ liệu hiệu suất cho khoảng thời gian này</td></tr>';
      foot.innerHTML = '';
      return;
    }
    body.innerHTML = rows.map(renderProductRow).join('');

    // Dòng tổng (tfoot)
    var t = { units: 0, sales: 0, cogs: 0, amazon_fees: 0, ads: 0, net_profit: 0 };
    rows.forEach(function (p) {
      var m = p.metrics || {};
      t.units += Number(m.units) || 0;
      t.sales += Number(m.sales) || 0;
      t.cogs += Number(m.cogs) || 0;
      t.amazon_fees += Number(m.amazon_fees) || 0;
      t.ads += Number(m.ads) || 0;
      t.net_profit += Number(m.net_profit) || 0;
    });
    var roi = t.cogs ? (t.net_profit / Math.abs(t.cogs) * 100) : 0;
    foot.innerHTML = '<tr class="border-t-2 bg-slate-50 font-semibold">' +
      '<td class="py-2 px-2">Tổng (' + rows.length + ' SKU)</td>' +
      '<td class="text-right px-2">' + fmtNum(t.units) + '</td>' +
      '<td class="text-right px-2">' + fmtMoney(t.sales) + '</td>' +
      '<td class="text-right px-2">' + fmtMoney(t.cogs) + '</td>' +
      '<td class="text-right px-2">' + fmtMoney(t.amazon_fees) + '</td>' +
      '<td class="text-right px-2">' + fmtMoney(t.ads) + '</td>' +
      '<td class="text-right px-2">' + pnl(t.net_profit) + '</td>' +
      '<td class="text-right px-2">' + pnl(roi, true) + '</td></tr>';
  }

  // Mức 8 — Products row: Thumbnail + Title + ASIN/SKU/Label, {>} subrow phí
  // Amazon, "..." mở TileMorePopover riêng cho SKU.
  function renderProductRow(p) {
    var info = p.product_info || {};
    var m = p.metrics || {};
    var rowId = 'row-' + (++state._rowSeq);
    var isFBA = info.fulfillment_channel === 'FBA'
      ? '<span class="bg-blue-100 text-blue-800 text-[10px] px-1 rounded ml-1">FBA</span>'
      : (info.fulfillment_channel ? '<span class="bg-slate-100 text-slate-600 text-[10px] px-1 rounded ml-1">' + esc(info.fulfillment_channel) + '</span>' : '');
    var stock = (info.fba_stock !== undefined && info.fba_stock !== null)
      ? '<span class="text-[10px] text-slate-400 ml-1">Tồn: ' + fmtNum(info.fba_stock) + '</span>' : '';

    var main = '<tr class="border-b hover:bg-gray-50 transition-colors">' +
      '<td class="py-2 px-2"><div class="flex items-center gap-2.5">' +
        '<button type="button" class="text-gray-400 hover:text-gray-800 w-4" onclick="SV8.toggleSubRow(\'' + rowId + '\')" id="toggle-' + rowId + '">▸</button>' +
        thumb(info) +
        '<div class="min-w-0">' +
          '<div class="font-medium max-w-[260px] truncate" title="' + esc(info.title) + '">' + (esc(info.title) || '(không có tên)') + isFBA + '</div>' +
          '<div class="mt-0.5 flex items-center">' + badge(info.asin, 'ASIN') + badge(info.sku, 'SKU') + stock + '</div>' +
        '</div>' +
        '<button type="button" class="ml-auto text-gray-400 hover:text-gray-800 px-1" onclick="SV8.showRowMore(event,\'' + esc(p.identifier) + '\',\'products\')" title="Chi tiết P&L">...</button>' +
      '</div></td>' +
      '<td class="text-right px-2">' + fmtNum(m.units) + '</td>' +
      '<td class="text-right px-2"><div>' + fmtMoney(m.sales) + '</div>' +
        '<div class="text-[10px] text-slate-400">' + fmtMoney(m.average_sales_price) + '/sp</div></td>' +
      '<td class="text-right px-2 text-slate-600">' + fmtMoney(m.cogs) + '</td>' +
      '<td class="text-right px-2 text-slate-600">' + fmtMoney(m.amazon_fees) + '</td>' +
      '<td class="text-right px-2 text-slate-600">' + fmtMoney(m.ads) + '</td>' +
      '<td class="text-right px-2">' + pnl(m.net_profit) + '</td>' +
      '<td class="text-right px-2">' + pnl(m.roi_pct, true) + '</td></tr>';

    // Sub-row {>}: breakdown Phí Amazon (referral_fee / fba_fee)
    var feeNode = (p.detailed_pnl && p.detailed_pnl.amazon_fees) || { total: m.amazon_fees, children: {} };
    var children = feeNode.children || {};
    var sub = '<tr data-parent="' + rowId + '" style="display:none" class="bg-slate-50 border-b">' +
      '<td class="py-1.5 px-2 pl-10 text-xs text-slate-500" colspan="8">' +
        '<span class="font-semibold">Phí Amazon: ' + fmtMoney(feeNode.total) + '</span>' +
        Object.keys(children).map(function (k) {
          return '<span class="ml-4">' + esc(PNL_LABELS[k] || k) + ': ' + fmtMoney(children[k]) + '</span>';
        }).join('') +
      '</td></tr>';

    return main + sub;
  }

  SV8.toggleSubRow = function (rowId) {
    var rows = document.querySelectorAll('tr[data-parent="' + rowId + '"]');
    var btn = document.getElementById('toggle-' + rowId);
    var willShow = rows.length && rows[0].style.display === 'none';
    rows.forEach(function (r) { r.style.display = willShow ? '' : 'none'; });
    if (btn) btn.textContent = willShow ? '▾' : '▸';
  };

  // Mức 8 — Order Items row: parse order_number_raw "ID / Status / COG / FBA"
  function renderOrderRow(order) {
    var rowId = 'row-' + (++state._rowSeq);
    var parts = (order.order_number_raw || '').split(' / ');
    var orderId = parts[0] || order.order_number;
    var status = parts[1] || order.order_status || 'Pending';

    var badgeClass = /shipped/i.test(status) ? 'bg-green-100 text-green-700'
      : /return|refund/i.test(status) ? 'bg-red-100 text-red-700'
      : /cancel/i.test(status) ? 'bg-slate-100 text-slate-500'
      : 'bg-yellow-100 text-yellow-700';

    var identifier = order.order_number + '|' + order.sku;
    var main = '<tr class="border-b hover:bg-slate-50">' +
      '<td class="py-2 px-2">' +
        '<button type="button" class="text-gray-400 hover:text-gray-800 w-4 mr-1" onclick="SV8.toggleSubRow(\'' + rowId + '\')" id="toggle-' + rowId + '">▸</button>' +
        '<span class="font-mono text-blue-600">' + esc(orderId) + '</span>' +
        '<div class="text-xs text-gray-500 ml-5">' + esc(order.order_date) + '</div>' +
        '<span class="px-2 py-0.5 rounded text-[10px] font-bold ml-5 ' + badgeClass + '">' + esc(status) + '</span>' +
      '</td>' +
      '<td class="text-right px-2">' + badge(order.sku, 'SKU') + '<div class="text-[10px] text-slate-400 mt-0.5">' + esc(order.asin) + '</div></td>' +
      '<td class="text-right px-2">' + fmtMoney(order.sales) + '</td>' +
      '<td class="text-right px-2">' + pnl(order.net_profit) + '</td>' +
      '<td class="text-right px-2"><button type="button" class="text-gray-400 hover:text-gray-800 px-1" onclick="SV8.showRowMore(event,\'' + esc(identifier).replace(/'/g, "\\'") + '\',\'orders\')" title="Chi tiết P&L">...</button></td>' +
      '</tr>';

    var sub = '<tr data-parent="' + rowId + '" style="display:none" class="bg-slate-50 border-b">' +
      '<td class="py-1.5 px-2 pl-10 text-xs text-slate-500" colspan="5">' +
        '<span class="font-semibold">Phí Amazon: ' + fmtMoney(order.amazon_fees) + '</span>' +
        '<span class="ml-4">COGS: ' + fmtMoney(order.cost_of_goods) + '</span>' +
        '<span class="ml-4">Hoàn tiền: ' + fmtMoney(order.refund_cost) + '</span>' +
        '<span class="ml-4">Vận chuyển: ' + fmtMoney(order.shipping) + '</span>' +
      '</td></tr>';

    return main + sub;
  }

  // ════════════════════════════════════════════════════════════════════════
  // Mức "P&L" View (View Switcher) — tổng hợp detailed_pnl của các SKU
  // đang hiển thị trong Bottom Panel thành 1 cây P&L tổng.
  // ════════════════════════════════════════════════════════════════════════
  function ensurePnlViewContainer() {
    var el = document.getElementById('sv8-pnl-view');
    if (el) return el;
    var anchor = document.getElementById('period-cards');
    el = document.createElement('div');
    el.id = 'sv8-pnl-view';
    el.className = 'bg-white rounded-xl p-5 shadow-sm mb-4 hidden';
    anchor.parentNode.insertBefore(el, anchor.nextSibling);
    return el;
  }

  function renderPnlView() {
    var el = ensurePnlViewContainer();
    var sum = { sales: 0, cogs: 0, amazon_fees: 0, ads: 0, promo: 0, refund_cost: 0, shipping: 0, net_profit: 0 };
    state.productsRaw.forEach(function (p) {
      var dp = p.detailed_pnl || {};
      Object.keys(sum).forEach(function (k) {
        sum[k] += Number((dp[k] && dp[k].total) || 0);
      });
    });
    var tree = {
      sales: { total: round2(sum.sales) },
      cogs: { total: round2(sum.cogs) },
      amazon_fees: { total: round2(sum.amazon_fees), children: splitAmazonFees(sum.sales, sum.amazon_fees) },
      ads: { total: round2(sum.ads) },
      promo: { total: round2(sum.promo) },
      refund_cost: { total: round2(sum.refund_cost) },
      shipping: { total: round2(sum.shipping) },
      net_profit: { total: round2(sum.net_profit) },
    };
    el.innerHTML = '<h3 class="font-bold text-lg mb-3">Tổng hợp P&L — ' + esc(state.gridTitle) + '</h3>' +
      '<table class="w-full text-sm"><tbody>' + renderPnlTree(tree, null) + '</tbody></table>';
  }

  // ════════════════════════════════════════════════════════════════════════
  // View Switcher (Mức 4) — chuyển activeTab
  // ════════════════════════════════════════════════════════════════════════
  SV8.switchView = function (key) {
    state.activeTab = key;
    applyActiveView();
  };

  // ════════════════════════════════════════════════════════════════════════
  // Data loading — fetch + render
  // ════════════════════════════════════════════════════════════════════════
  function rangeForKey(key) {
    if (state.rangeOverride) return state.rangeOverride;
    var k = key === 'forecast' ? 'mtd' : key;
    if (typeof App._periodRange === 'function') return App._periodRange(k);
    var now = new Date();
    var fmt = function (d) { return d.toISOString().slice(0, 10); };
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return { start: fmt(today), end: fmt(today) };
  }

  async function loadGrid() {
    renderGridContainer();
    var range = rangeForKey(state.gridPeriodKey);
    var tab = state.gridTab;
    var body = document.getElementById('datagrid-body');
    if (body) {
      body.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-slate-400">Đang tải dữ liệu...</td></tr>';
    }
    try {
      var d = await window.api('/api/analytics/dashboard/summary?tab=' + tab +
        '&start=' + range.start + '&end=' + range.end);
      if (tab === 'orders') {
        state.ordersRaw = Array.isArray(d.orders) ? d.orders : [];
        state._ordersLoaded = true;
      } else {
        state.productsRaw = Array.isArray(d.products) ? d.products : [];
        state._productsLoaded = true;
      }
      renderGridBody();
      if (state.activeTab === 'pnl') renderPnlView();
    } catch (err) {
      console.error('[Phase3] render_performance: lỗi tải grid:', err);
      if (body) body.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-red-500">Lỗi tải dữ liệu: ' + esc(err && err.message) + '</td></tr>';
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  // Ghi đè App.loadDashboard / loadPeriods / loadProductPerf
  // ════════════════════════════════════════════════════════════════════════
  function install() {
    if (!window.App || typeof window.App.loadDashboard !== 'function') {
      return false; // app.js chưa nạp xong
    }

    App.loadPeriods = async function () {
      var d = await window.api('/api/analytics/periods');
      state.periods = d.periods || [];
      renderTiles(state.periods);
    };

    // Vô hiệu hoá range-select cũ (đã được thay bằng Date Picker ở Top Panel)
    App.loadProductPerf = async function () { return loadGrid(); };

    App.loadDashboard = async function () {
      ensureTopPanel();
      ensureGridContainer();
      try {
        await this.loadPeriods();
        state._productsLoaded = false;
        state._ordersLoaded = false;
        await loadGrid();
      } catch (err) {
        console.error('[Phase3] render_performance: lỗi tải dashboard:', err);
      }
      try { if (typeof this.drawSales === 'function') this.drawSales([]); } catch (e) { console.warn('[Phase3] drawSales:', e); }
      try { if (typeof this.drawMarket === 'function') this.drawMarket({}); } catch (e) { console.warn('[Phase3] drawMarket:', e); }
      applyActiveView();
    };

    // Ẩn dropdown "Kỳ" cũ (range-select) — Date Picker mới ở Top Panel thay thế
    var oldSelect = document.getElementById('range-select');
    if (oldSelect) {
      var oldLabel = oldSelect.closest('label');
      if (oldLabel) oldLabel.style.display = 'none';
    }

    console.info('[Phase3] render_performance.js đã kích hoạt (8-Level Progressive Disclosure).');
    return true;
  }

  // app.js nạp trước (script tag đứng trước) nên thường install được ngay;
  // phòng hờ thì thử lại sau DOMContentLoaded.
  if (!install()) {
    document.addEventListener('DOMContentLoaded', install);
  }
})();
