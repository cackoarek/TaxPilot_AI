/**
 * TaxPilot AI – Static Showcase Helper (GitHub Pages / Offline Mode)
 * Zapewnia obsługę interaktywnych komponentów demo (Kody QR, modale faktur)
 * oraz przyjazną informację przy próbie modyfikacji danych w trybie statycznym.
 */
(function() {
  'use strict';

  function showDemoToast(message, type) {
    type = type || 'info';
    var existingToast = document.getElementById('taxpilot-demo-toast');
    if (existingToast) existingToast.remove();

    var toast = document.createElement('div');
    toast.id = 'taxpilot-demo-toast';
    toast.className = 'fixed bottom-5 right-5 z-[9999] max-w-md p-4 rounded-xl shadow-2xl border transition-all duration-300 transform translate-y-0 opacity-100 flex items-start space-x-3 text-xs bg-slate-900 text-white border-blue-500/50';

    var icon = type === 'warning' ? '⚠️' : '✨';
    toast.innerHTML =
      '<span class="text-xl shrink-0">' + icon + '</span>' +
      '<div class="flex-1">' +
        '<strong class="block font-bold text-blue-400 text-sm mb-1">Tryb Pokazowy (GitHub Pages)</strong>' +
        '<p class="text-slate-300 leading-relaxed">' + message + '</p>' +
      '</div>' +
      '<button onclick="this.parentElement.remove()" class="text-slate-400 hover:text-white font-bold text-sm ml-2">&times;</button>';

    document.body.appendChild(toast);

    setTimeout(function() {
      if (toast && toast.parentElement) {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(function() { if (toast.parentElement) toast.remove(); }, 300);
      }
    }, 4500);
  }

  window.showTaxPilotDemoToast = showDemoToast;

  // Przechwytywanie zapytań HTMX
  document.addEventListener('htmx:beforeRequest', function(evt) {
    var detail = evt.detail;
    var path = (detail.pathInfo && detail.pathInfo.requestPath) || '';
    var fullUrl = detail.url || path;
    var data = window.TAX_PILOT_DEMO_DATA || {};

    // 1. Obsługa kodów QR przelewów (/api/settlement/qr/{typ})
    if (path.indexOf('/api/settlement/qr/') !== -1 || path.indexOf('api/settlement/qr/') !== -1) {
      evt.preventDefault();
      var cleanPath = path.startsWith('/') ? path : '/' + path;
      var modalHtml = data.qrModals && (data.qrModals[cleanPath] || data.qrModals[path]);
      if (modalHtml) {
        var target = document.querySelector(detail.target || '#qr-modal-content');
        if (target) {
          target.innerHTML = modalHtml;
        }
      }
      return;
    }

    // 2. Obsługa podglądu faktury (/api/invoices/preview)
    if (path.indexOf('/api/invoices/preview') !== -1 || path.indexOf('api/invoices/preview') !== -1) {
      evt.preventDefault();
      var numer = '';
      var typ = 'koszt';
      try {
        var urlObj = new URL(fullUrl, window.location.origin);
        numer = urlObj.searchParams.get('numer') || '';
        typ = urlObj.searchParams.get('typ') || 'koszt';
      } catch(e) {
        var match = fullUrl.match(/numer=([^&]+)/);
        if (match) numer = decodeURIComponent(match[1]);
      }

      var key = numer + '::' + typ;
      var previewHtml = data.invoiceModals && (data.invoiceModals[key] || data.invoiceModals[numer]);
      var container = document.getElementById('invoice-modal-container');
      if (container && previewHtml) {
        container.innerHTML = previewHtml;
        if (window.openInvoiceModal) {
          window.openInvoiceModal();
        }
        if (window.Alpine) {
          try { window.Alpine.initTree(container); } catch(err) {}
        }
      } else {
        showDemoToast('Podgląd tej faktury w wersji statycznej nie jest dostępny. Wybierz inną fakturę z listy.', 'warning');
      }
      return;
    }

    // 3. Obsługa listy reguł (/api/rules/list)
    if (path.indexOf('/api/rules/list') !== -1) {
      evt.preventDefault();
      if (data.rulesList) {
        var rulesContainer = document.getElementById('rules-list-container');
        if (rulesContainer) rulesContainer.innerHTML = data.rulesList;
      }
      return;
    }

    // 4. Pozostałe zapytania modyfikujące (POST / PUT / DELETE lub nieobsługiwane GET)
    evt.preventDefault();
    showDemoToast('Ta akcja wymaga połączenia z lokalnym silnikiem TaxPilot AI oraz KSeF 2.0. W statycznym demo dane są tylko do odczytu.', 'info');
  });

  // Przechwytywanie wysyłania formularzy
  document.addEventListener('submit', function(evt) {
    var form = evt.target;
    var action = form.getAttribute('action') || '';
    if (action.indexOf('/firmy/switch') !== -1 || action.indexOf('/firmy/period') !== -1) {
      evt.preventDefault();
      showDemoToast('Wersja demonstracyjna prezentuje pełne dane testowe dla firmy CloudTech Solutions (2026-10).', 'info');
    }
  });

})();
