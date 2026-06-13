/* Phase 3 — render_performance.js
 * Mở rộng giao diện bảng #top-products thành Ma trận hiệu suất sản phẩm
 * (Product Performance Grid) kiểu Sellerboard. JavaScript THUẦN, không framework.
 *
 * Cách hoạt động (KHÔNG sửa app.js gốc):
 *   - Nạp SAU app.js (patch_frontend.py chèn <script src="/static/render_performance.js">).
 *   - Ghi đè App.loadDashboard: gọi cùng API GET /api/analytics/dashboard?days=N,
 *     vẫn vẽ chart + thẻ kỳ như cũ, nhưng render bảng theo layout mới.
 *   - Nếu payload KHÔNG có khoá mới (backend chưa vá) hoặc có lỗi bất kỳ
 *     -> tự động fallback về hàm loadDashboard gốc, UI cũ không bị ảnh hưởng.
 */
(function () {
  'use strict';

  // ---------- Helper định dạng ----------
  var fmtMoney = function (v) {
    return '$' + (Number(v) || 0).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  var fmtNum = function (v) { return (Number(v) || 0).toLocaleString('en-US'); };

  // Escape HTML — tránh title/SKU chứa ký tự đặc biệt phá vỡ template string
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };

  // Logic màu sắc động kiểu Sellerboard:
  //   > 0 -> xanh lá đậm + dấu '+'   |   < 0 -> đỏ rực + dấu '-'
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
    return '<button type="button" onclick="navigator.clipboard&&navigator.clipboard.writeText(\'' +
      esc(text) + '\');this.classList.add(\'ring-1\',\'ring-green-400\');' +
      'var b=this;setTimeout(function(){b.classList.remove(\'ring-1\',\'ring-green-400\')},800)" ' +
      'title="Click để copy ' + esc(label) + '" ' +
      'class="text-[10px] font-mono bg-slate-100 hover:bg-slate-200 text-slate-500 ' +
      'rounded px-1.5 py-0.5 mr-1 cursor-pointer select-all">' + esc(text) + '</button>';
  }

  // Ảnh thumb 50x50 từ ASIN (widget Amazon); lỗi ảnh -> hiện ô chữ cái đầu
  // của title (render sẵn ở trạng thái ẩn, onerror chỉ bật/tắt class).
  function thumb(p) {
    var initial = esc((p.title || '?').charAt(0).toUpperCase());
    var fallback = '<div class="w-10 h-10 rounded-lg bg-slate-200 hidden ' +
      'items-center justify-center text-slate-500 text-xs font-bold">' + initial + '</div>';
    if (!p.asin) {
      return fallback.replace('hidden', 'flex');
    }
    return '<img loading="lazy" src="https://ws-na.amazon-adsystem.com/widgets/q?_encoding=UTF8&ASIN=' +
      esc(p.asin) + '&Format=_SL64_&ID=AsinImage&MarketPlace=US&ServiceVersion=20070822&WS=1" ' +
      'class="w-10 h-10 rounded-lg object-contain bg-slate-100 border border-slate-200" ' +
      'onerror="this.style.display=\'none\';this.nextElementSibling.classList.remove(\'hidden\');' +
      'this.nextElementSibling.classList.add(\'flex\')">' + fallback;
  }

  var NEW_HEAD =
    '<tr class="text-left">' +
    '<th class="py-2 px-2">Sản phẩm</th>' +
    '<th class="text-right px-2">Số lượng</th>' +
    '<th class="text-right px-2">Doanh thu</th>' +
    '<th class="text-right px-2">Chi phí gốc (COGS)</th>' +
    '<th class="text-right px-2">Phí sàn (Comm/FBA)</th>' +
    '<th class="text-right px-2">Quảng cáo</th>' +
    '<th class="text-right px-2">Lợi nhuận ròng</th>' +
    '<th class="text-right px-2">Biên LN</th></tr>';

  // ---------- Render ma trận hiệu suất ----------
  function renderGrid(d) {
    var tbody = document.getElementById('top-products');
    if (!tbody) return false;
    var table = tbody.closest('table');
    var rows = Array.isArray(d.top_products) ? d.top_products : [];

    // Đổi thead sang layout mới (8 cột chuẩn Sellerboard)
    try {
      var thead = table && table.querySelector('thead');
      if (thead) thead.innerHTML = NEW_HEAD;
    } catch (e) { /* thead lỗi không chặn render tbody */ }

    // Trường hợp biên: mảng rỗng -> thông báo sạch, không vỡ bố cục
    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-slate-400">' +
        'Không có dữ liệu hiệu suất cho khoảng thời gian này</td></tr>';
      removeTfoot(table);
      return true;
    }

    var html = rows.map(function (p) {
      var fees = (Number(p.commission) || 0) + (Number(p.fba_fee) || 0);
      return '<tr class="border-b last:border-0 hover:bg-gray-50 transition-colors">' +
        '<td class="py-2 px-2"><div class="flex items-center gap-2.5">' + thumb(p) +
          '<div class="min-w-0">' +
            '<div class="font-medium max-w-[260px] truncate" title="' + esc(p.title) + '">' +
              (esc(p.title) || '(không có tên)') + '</div>' +
            '<div class="mt-0.5">' + badge(p.asin, 'ASIN') + badge(p.sku, 'SKU') + '</div>' +
          '</div></div></td>' +
        '<td class="text-right px-2">' + fmtNum(p.quantity != null ? p.quantity : p.units) + '</td>' +
        '<td class="text-right px-2"><div>' + fmtMoney(p.sales) + '</div>' +
          '<div class="text-[10px] text-slate-400">' + fmtMoney(p.price != null ? p.price : p.avg_selling_price) + '/sp</div></td>' +
        '<td class="text-right px-2 text-slate-600">' + fmtMoney(p.product_cost != null ? p.product_cost : p.cogs) + '</td>' +
        '<td class="text-right px-2"><div class="text-slate-600">' + fmtMoney(fees) + '</div>' +
          '<div class="text-[10px] text-slate-400">Comm ' + fmtMoney(p.commission) +
          ' · FBA ' + fmtMoney(p.fba_fee) + ' · Promo ' + fmtMoney(p.promo) + '</div></td>' +
        '<td class="text-right px-2 text-slate-600">' + fmtMoney(p.ad_spend != null ? p.ad_spend : p.ppc) + '</td>' +
        '<td class="text-right px-2">' + pnl(p.net_profit) + '</td>' +
        '<td class="text-right px-2">' + pnl(p.margin != null ? p.margin : p.margin_pct, true) + '</td></tr>';
    }).join('');
    tbody.innerHTML = html;

    // Dòng tổng (tfoot) — tạo nếu chưa có
    try {
      var t = d.totals || {};
      if (table && t.sales != null) {
        var tfoot = table.querySelector('tfoot');
        if (!tfoot) { tfoot = document.createElement('tfoot'); table.appendChild(tfoot); }
        tfoot.className = 'border-t-2 bg-slate-50 font-semibold';
        tfoot.innerHTML = '<tr>' +
          '<td class="py-2 px-2">Tổng (' + rows.length + ' SKU · ' + fmtNum(t.orders) + ' đơn)</td>' +
          '<td class="text-right px-2">' + fmtNum(t.quantity) + '</td>' +
          '<td class="text-right px-2">' + fmtMoney(t.sales) + '</td>' +
          '<td class="text-right px-2">' + fmtMoney(t.product_cost) + '</td>' +
          '<td class="text-right px-2">' + fmtMoney((t.commission || 0) + (t.fba_fee || 0)) + '</td>' +
          '<td class="text-right px-2">' + fmtMoney(t.ad_spend) + '</td>' +
          '<td class="text-right px-2">' + pnl(t.net_profit) + '</td>' +
          '<td class="text-right px-2">' + pnl(t.margin, true) + '</td></tr>';
      } else {
        removeTfoot(table);
      }
    } catch (e) { /* tfoot lỗi không chặn UI */ }
    return true;
  }

  function removeTfoot(table) {
    try {
      var tfoot = table && table.querySelector('tfoot');
      if (tfoot) tfoot.innerHTML = '';
    } catch (e) { /* bỏ qua */ }
  }

  // ---------- Ghi đè App.loadDashboard (giữ bản gốc để fallback) ----------
  function install() {
    if (!window.App || typeof window.App.loadDashboard !== 'function') {
      return false; // app.js chưa nạp xong
    }
    var origLoad = window.App.loadDashboard.bind(window.App);

    window.App.loadDashboard = async function () {
      var sel = document.getElementById('range-select');
      var days = sel ? sel.value : 30;
      var tbody = document.getElementById('top-products');
      try {
        if (tbody) {
          tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-slate-400">' +
            'Đang tổng hợp dữ liệu hiệu suất từ Supabase...</td></tr>';
        }
        // 1 lần fetch duy nhất — dùng chung cho chart + bảng
        var results = await Promise.all([
          window.api('/api/analytics/dashboard?days=' + days),
          // Thẻ kỳ so sánh (Today/Yesterday/MTD...) như bản gốc
          typeof this.loadPeriods === 'function' ? this.loadPeriods() : null,
        ]);
        var d = results[0] || {};

        // Vẽ chart như bản gốc — lỗi chart không được chặn bảng
        try { if (typeof this.drawSales === 'function') this.drawSales(d.timeseries || []); } catch (e) { console.warn('[Phase3] drawSales:', e); }
        try { if (typeof this.drawMarket === 'function') this.drawMarket(d.marketplace_breakdown || {}); } catch (e) { console.warn('[Phase3] drawMarket:', e); }

        // Payload có khoá mới (backend đã vá)? -> render grid mới.
        var hasNew = Array.isArray(d.top_products) &&
          (d.top_products.length === 0 || (d.top_products[0] && 'margin' in d.top_products[0] && 'sku' in d.top_products[0]));
        if (hasNew && d.status) {
          renderGrid(d);
        } else {
          // Backend chưa vá -> render kiểu cũ bằng hàm gốc (fetch lại, an toàn)
          console.info('[Phase3] Payload chưa có khoá mới — dùng renderer gốc.');
          await origLoad();
        }
      } catch (err) {
        // Lỗi bất kỳ -> quay về hành vi gốc, KHÔNG đóng băng giao diện
        console.error('[Phase3] render_performance lỗi, fallback bản gốc:', err);
        try { await origLoad(); } catch (e2) {
          if (tbody) {
            tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-red-500">' +
              'Lỗi tải dữ liệu: ' + esc(err && err.message) + '</td></tr>';
          }
        }
      }
    };
    console.info('[Phase3] render_performance.js đã kích hoạt (ghi đè App.loadDashboard).');
    return true;
  }

  // app.js nạp trước (script tag đứng trước) nên thường install được ngay;
  // phòng hờ thì thử lại sau DOMContentLoaded.
  if (!install()) {
    document.addEventListener('DOMContentLoaded', install);
  }
})();
