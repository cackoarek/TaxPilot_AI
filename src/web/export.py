"""
src/web/export.py
Generator i eksporter statycznych stron demonstracyjnych HTML panelu webowego TaxPilot AI.
Umożliwia przeglądanie interfejsu offline oraz hosting na GitHub Pages
(na wzór projektu librus2mail).
"""

import json
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from starlette.testclient import TestClient

from src.config import BASE_DIR
from src.core.company import CompanyProfile
from src.logging_config import get_logger
from src.web.app import app
from src.web.config import COOKIE_ACTIVE_MONTH, COOKIE_ACTIVE_NIP, COOKIE_ACTIVE_YEAR

logger = get_logger("taxpilot.web.export")

DEFAULT_DEMO_NIP = "7770001122"
DEFAULT_DEMO_YEAR = "2026"
DEFAULT_DEMO_MONTH = "10"
DEFAULT_OUTPUT_DIR = BASE_DIR / "examples" / "pages"
STATIC_DEMO_CSRF_TOKEN = "static_demo_csrf_token_taxpilot_ai"

# Górny pasek demonstracyjny informujący o środowisku GitHub Pages
DEMO_TOP_BANNER = """
<!-- TaxPilot AI Demo Banner -->
<div class="bg-gradient-to-r from-blue-700 via-indigo-700 to-purple-800 text-white text-xs py-2 px-4 shadow-md sticky top-0 z-50">
  <div class="max-w-7xl mx-auto flex items-center justify-between">
    <div class="flex items-center space-x-2">
      <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-black bg-white/20 text-white uppercase tracking-wider">Demo Showcase</span>
      <span class="font-medium text-slate-100 hidden sm:inline">
        Statyczna wersja demonstracyjna dla GitHub Pages. Dane testowe: <strong class="text-white">CloudTech Solutions Jan Kowalski</strong> (okres: 2026-10).
      </span>
    </div>
    <div class="flex items-center space-x-3 shrink-0">
      <span class="text-xs text-indigo-200 hidden md:inline">100% Deterministyczna Księgowość & KSeF 2.0</span>
      <a href="https://github.com/cackoarek/TaxPilot_AI" target="_blank" class="px-2.5 py-1 bg-white text-slate-900 hover:bg-slate-100 rounded-md font-bold text-[11px] transition-colors flex items-center space-x-1 shadow-xs">
        <span>⭐ GitHub</span>
      </a>
    </div>
  </div>
</div>
<!-- End TaxPilot AI Demo Banner -->
"""


def make_offline_friendly(html: str) -> str:
    """
    Dostosowuje kod HTML do działania statycznego offline / GitHub Pages:
    - Przekształca ścieżki do assetów statycznych (/static/... -> static/...)
    - Zamienia adresy URL tras na pliki .html
    - Wstrzykuje górny pasek demonstracyjny i skrypt obsługi zdarzeń offline demo.js
    - Neutralizuje akcje formularzy wymagających aktywnego backendu.
    """
    # 1. Assety statyczne (/static/... -> static/...)
    html = re.sub(r'([href|src]=["\'])/static/', r"\1static/", html)
    html = re.sub(r'url\(["\']?/static/', "url(static/", html)
    html = html.replace('href="/static/favicon.svg"', 'href="static/favicon.svg"')

    # 2. Zakładki modułu Księgowanie (/ksiegowanie?tab=... -> ksiegowanie_...html)
    tab_replacements = [
        ('href="/ksiegowanie?tab=przychody"', 'href="ksiegowanie.html"'),
        ('href="/ksiegowanie?tab=koszty"', 'href="ksiegowanie_koszty.html"'),
        ('href="/ksiegowanie?tab=vat"', 'href="ksiegowanie_vat.html"'),
        ('href="/ksiegowanie?tab=ytd"', 'href="ksiegowanie_ytd.html"'),
        ('href="/ksiegowanie?tab=przelewy"', 'href="ksiegowanie_przelewy.html"'),
        ('href="/ksiegowanie?tab=audyt"', 'href="ksiegowanie_audyt.html"'),
        ('href="/ksiegowanie?tab=wskazniki"', 'href="ksiegowanie_wskazniki.html"'),
    ]
    for old, new in tab_replacements:
        html = html.replace(old, new)

    # 3. Główne trasy nawigacyjne
    nav_replacements = [
        ('href="/"', 'href="index.html"'),
        ('href="/#"', 'href="index.html#"'),
        ('href="/przeglad"', 'href="przeglad.html"'),
        ('href="/ksiegowanie"', 'href="ksiegowanie.html"'),
        ('href="/faktury"', 'href="faktury.html"'),
        ('href="/aml"', 'href="aml.html"'),
        ('href="/doradca"', 'href="doradca.html"'),
        ('href="/ustawienia"', 'href="ustawienia.html"'),
        ('href="/firmy/nowa"', 'href="firmy_nowa.html"'),
    ]
    for old, new in nav_replacements:
        html = html.replace(old, new)

    # 4. Trasy z dodatkowymi parametrami query
    html = re.sub(r'href="/przeglad\?[^"]*"', 'href="przeglad.html"', html)
    html = re.sub(r'href="/faktury\?[^"]*"', 'href="faktury.html"', html)
    html = re.sub(r'href="/aml\?[^"]*"', 'href="aml.html"', html)
    html = re.sub(r'href="/doradca\?[^"]*"', 'href="doradca.html"', html)
    html = re.sub(r'href="/ustawienia\?[^"]*"', 'href="ustawienia.html"', html)
    html = re.sub(r'href="/ksiegowanie\?[^"]*"', 'href="ksiegowanie.html"', html)

    # 5. Linki do pobierania oficjalnych raportów PDF i MD
    html = re.sub(
        r'href="/aml/raport/pdf(\?[^"]*)?"', 'href="reports/raport-weryfikacji-2026-10.pdf" target="_blank"', html
    )
    html = re.sub(
        r'href="/aml/raport/md(\?[^"]*)?"', 'href="reports/raport-weryfikacji-2026-10.md" target="_blank"', html
    )
    html = re.sub(
        r'href="/aml/karta/pdf/([0-9A-Za-z]+)(\?[^"]*)?"', r'href="reports/\1-karta.pdf" target="_blank"', html
    )

    # 6. JavaScript inline
    html = html.replace("window.location.href='/firmy/nowa'", "window.location.href='firmy_nowa.html'")
    html = html.replace('action="/firmy/switch"', 'action="#" onsubmit="return false;"')
    html = html.replace('action="/firmy/period"', 'action="#" onsubmit="return false;"')

    # 7. Wstrzyknięcie banera demo po znaczniku <body>
    if "<body" in html:
        html = re.sub(r"(<body[^>]*>)", r"\1\n" + DEMO_TOP_BANNER, html, count=1)

    # 8. Wstrzyknięcie skryptu demo przed </body>
    demo_script_tag = """
    <!-- TaxPilot AI Demo Offline Scripts -->
    <script src="static/js/demo-data.js"></script>
    <script src="static/js/demo.js"></script>
    """
    if "</body>" in html:
        html = html.replace("</body>", demo_script_tag + "\n</body>")
    else:
        html += demo_script_tag

    return html


def prepare_demo_data(client: TestClient, output_dir: Path, profile: CompanyProfile, rok: str, miesiac: str) -> None:
    """
    Generuje i zapisuje pre-renderowane dane interaktywnych komponentów demo:
    - Kody QR przelewów ZUS, PIT-28, VAT-7 (/api/settlement/qr/{typ})
    - Dynamiczne podglądy wszystkich faktur sprzedaży i kosztów danego okresu (/api/invoices/preview)
    - Listę nauczonych reguł kosztowych (/api/rules/list)
    Zapisuje je do static/js/demo-data.js.
    """
    js_dir = output_dir / "static" / "js"
    js_dir.mkdir(parents=True, exist_ok=True)

    demo_data = {
        "qrModals": {},
        "invoiceModals": {},
        "rulesList": "",
    }

    # 1. Kody QR przelewów
    for typ in ["pit28", "vat7", "zus"]:
        path = f"/api/settlement/qr/{typ}"
        res = client.get(path)
        if res.status_code == 200:
            demo_data["qrModals"][path] = res.text
            demo_data["qrModals"][f"api/settlement/qr/{typ}"] = res.text

    # 2. Lista reguł
    rules_res = client.get("/api/rules/list")
    if rules_res.status_code == 200:
        demo_data["rulesList"] = rules_res.text

    # 3. Dynamiczne pobranie podglądów wszystkich faktur danego okresu
    from src.level_1_ingestion.invoice_storage import InvoiceStorage

    invoices = InvoiceStorage.list_invoices(profile, rok, miesiac)

    for inv in invoices:
        numer = inv.numer
        typ = "sprzedaz" if inv.typ.value == "sprzedaz" else "koszt"
        enc_numer = urllib.parse.quote(numer)
        url = f"/api/invoices/preview?numer={enc_numer}&typ={typ}"
        res = client.get(url)
        if res.status_code == 200:
            key = f"{numer}::{typ}"
            demo_data["invoiceModals"][key] = res.text
            demo_data["invoiceModals"][numer] = res.text
        else:
            logger.warning("Nie udało się pobrać podglądu dla faktury %s: HTTP %d", numer, res.status_code)

    demo_data_js_path = js_dir / "demo-data.js"
    with open(demo_data_js_path, "w", encoding="utf-8") as f:
        f.write("/* TaxPilot AI Static Demo Data */\n")
        f.write("window.TAX_PILOT_DEMO_DATA = ")
        json.dump(demo_data, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    logger.info(
        "Zapisano dane demonstracyjne (%d faktur, %d kodów QR): %s",
        len(invoices),
        len(demo_data["qrModals"]),
        demo_data_js_path,
    )


def write_demo_js_helper(output_dir: Path) -> None:
    """
    Tworzy skrypt pomocniczy static/js/demo.js odpowiedzialny za:
    - Przechwytywanie zapytań HTMX dla kodów QR i podglądu faktur
    - Wyświetlanie eleganckiego dymka informacyjnego (toast) przy kliknięciu akcji serwerowych
    - Zapewnienie pełnej responsywności i bezbłędnego działania bez backendu.
    """
    js_dir = output_dir / "static" / "js"
    js_dir.mkdir(parents=True, exist_ok=True)
    demo_js_path = js_dir / "demo.js"

    content = """/**
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
"""
    with open(demo_js_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Utworzono skrypt demo: %s", demo_js_path)


def copy_static_assets(output_dir: Path) -> None:
    """Kopiuje pliki ze statycznego katalogu aplikacji do examples/pages/static/."""
    src_static = BASE_DIR / "src" / "web" / "static"
    dest_static = output_dir / "static"
    dest_static.mkdir(parents=True, exist_ok=True)

    if src_static.exists():
        for item in src_static.iterdir():
            target = dest_static / item.name
            if item.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)

    logger.info("Skopiowano assety statyczne z %s do %s", src_static, dest_static)


def copy_official_reports(company_dir: Path, output_dir: Path, rok: str, miesiac: str) -> None:
    """Kopiuje wygenerowane oficjalne raporty PDF i MD do examples/pages/reports/."""
    dest_reports = output_dir / "reports"
    dest_reports.mkdir(parents=True, exist_ok=True)

    # 1. Raporty weryfikacji AML / Biała Lista
    wer_dir = company_dir / "weryfikacje" / rok / miesiac
    if wer_dir.exists():
        for f in wer_dir.glob("raport-weryfikacji.*"):
            shutil.copy2(f, dest_reports / f"{f.stem}-{rok}-{miesiac}{f.suffix}")

        # Karty kontrahentów (PDF, MD)
        karty_dir = wer_dir / "karty"
        if karty_dir.exists():
            for f in karty_dir.glob("*-karta.*"):
                shutil.copy2(f, dest_reports / f.name)

    # 2. Raporty rozliczeniowe
    roz_dir = company_dir / "rozliczenia" / rok / miesiac
    if roz_dir.exists():
        for f in roz_dir.glob("*.md"):
            shutil.copy2(f, dest_reports / f"{f.stem}-{rok}-{miesiac}{f.suffix}")

    logger.info("Skopiowano oficjalne raporty do %s", dest_reports)


def export_demo_pages(
    output_dir: Optional[Path] = None,
    nip: str = DEFAULT_DEMO_NIP,
    rok: str = DEFAULT_DEMO_YEAR,
    miesiac: str = DEFAULT_DEMO_MONTH,
) -> Dict[str, Path]:
    """
    Główna funkcja eksportująca kompletny pakiet stron statycznych HTML do folderu docelowego.
    Zwraca mapę {nazwa_pliku: ścieżka_do_pliku}.
    """
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Rozpoczynanie eksportu stron demo do: %s (NIP: %s, %s-%s)", output_dir, nip, rok, miesiac)

    # 1. Upewnienie się że firma testowa istnieje w katalogu roboczym firmy/
    from tests.fixtures import setup_test_company

    profile = setup_test_company()
    company_dir = profile.katalog_firmy

    # 2. Kopiowanie assetów statycznych i raportów
    copy_static_assets(output_dir)
    copy_official_reports(company_dir, output_dir, rok, miesiac)

    # 3. Inicjalizacja klienta testowego z odpowiednimi ciasteczkami sesji
    client = TestClient(app)
    client.cookies.set(COOKIE_ACTIVE_NIP, nip)
    client.cookies.set(COOKIE_ACTIVE_YEAR, rok)
    client.cookies.set(COOKIE_ACTIVE_MONTH, miesiac)

    # 4. Przygotowanie danych interaktywnych (QR, modale) i skryptu demo
    prepare_demo_data(client, output_dir, profile, rok, miesiac)
    write_demo_js_helper(output_dir)

    # 5. Definicja widoków do wyeksportowania: (ścieżka_url, nazwa_pliku, opis)
    views_to_export: List[Tuple[str, str, str]] = [
        # Główne widoki aplikacji
        ("/", "index.html", "Pulpit Główny & Paczka Przelewów"),
        ("/", "dashboard.html", "Pulpit Główny (alias)"),
        ("/przeglad", "przeglad.html", "Wstępny Przegląd i Kwalifikacja Dokumentów"),
        ("/ksiegowanie", "ksiegowanie.html", "Księgowanie – Ewidencja Przychodów (domyślna)"),
        ("/ksiegowanie?tab=przychody", "ksiegowanie_przychody.html", "Księgowanie – Ewidencja Przychodów"),
        ("/ksiegowanie?tab=koszty", "ksiegowanie_koszty.html", "Księgowanie – Rejestr Kosztów i Zakupów"),
        ("/ksiegowanie?tab=vat", "ksiegowanie_vat.html", "Księgowanie – Rejestr i Rozliczenie VAT-7"),
        ("/ksiegowanie?tab=przelewy", "ksiegowanie_przelewy.html", "Księgowanie – Zestawienie Zobowiązań i Przelewów"),
        ("/ksiegowanie?tab=ytd", "ksiegowanie_ytd.html", "Księgowanie – Zestawienie Narastające Roczne YTD"),
        ("/ksiegowanie?tab=audyt", "ksiegowanie_audyt.html", "Księgowanie – Sprawozdanie i Audyt Podatkowy"),
        (
            "/ksiegowanie?tab=wskazniki",
            "ksiegowanie_wskazniki.html",
            "Księgowanie – Wskaźniki Makroekonomiczne ZUS/GUS",
        ),
        ("/faktury", "faktury.html", "Przeglądarka Faktur KSeF & Non-KSeF"),
        ("/aml", "aml.html", "Compliance AML, Biała Lista VAT i Sankcje"),
        ("/doradca", "doradca.html", "Doradca Podatkowy & Symulacja Form"),
        ("/ustawienia", "ustawienia.html", "Ustawienia Firmy & KSeF 2.0"),
        ("/firmy/nowa", "firmy_nowa.html", "Kreator Dodawania Nowej Firmy"),
    ]

    # Dodatkowe aliasy z prefiksem web_ dla pełnej spójności ze stylem librus2mail
    librus_aliases = [
        ("index.html", "web_dashboard.html"),
        ("przeglad.html", "web_przeglad.html"),
        ("ksiegowanie.html", "web_ksiegowanie.html"),
        ("faktury.html", "web_faktury.html"),
        ("aml.html", "web_aml.html"),
        ("doradca.html", "web_doradca.html"),
        ("ustawienia.html", "web_ustawienia.html"),
        ("firmy_nowa.html", "web_setup.html"),
    ]

    generated_files: Dict[str, Path] = {}

    for route, filename, label in views_to_export:
        res = client.get(route)
        if res.status_code == 200:
            raw_html = res.text
            clean_html = make_offline_friendly(raw_html)
            target_file = output_dir / filename
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(clean_html)
            generated_files[filename] = target_file
            logger.info("Wygenerowano widok [%s]: %s (rozmiar: %d bajtów)", label, target_file.name, len(clean_html))
        else:
            logger.error("Błąd generowania widoku %s: HTTP status %d", route, res.status_code)

    # Zapisanie aliasów web_*
    for source_name, alias_name in librus_aliases:
        source_path = output_dir / source_name
        if source_path.exists():
            alias_path = output_dir / alias_name
            shutil.copy2(source_path, alias_path)
            generated_files[alias_name] = alias_path

    logger.info("Pomyślnie wyeksportowano %d plików HTML do %s", len(generated_files), output_dir)
    return generated_files


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Eksporter statycznych stron demo HTML TaxPilot AI")
    parser.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT_DIR), help="Katalog docelowy")
    parser.add_argument("--nip", default=DEFAULT_DEMO_NIP, help="NIP firmy demonstracyjnej")
    parser.add_argument("--rok", default=DEFAULT_DEMO_YEAR, help="Rok podatkowy")
    parser.add_argument("--miesiac", default=DEFAULT_DEMO_MONTH, help="Miesiąc podatkowy")
    args = parser.parse_args()

    export_demo_pages(
        output_dir=Path(args.output),
        nip=args.nip,
        rok=args.rok,
        miesiac=args.miesiac,
    )
