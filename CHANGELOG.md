# Changelog

Wszystkie istotne zmiany w projekcie TaxPilot AI są dokumentowane w tym pliku.

Format bazuje na [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/).
Projekt stosuje [Semantic Versioning](https://semver.org/lang/pl/).

---

## [Unreleased]

### Bezpieczeństwo
- **SEC-1**: Eliminacja podatności XSS (CWE-79) w module Markdown Copilota za pomocą bezpiecznej sanitizacji HTML (`bleach`) z białą listą dozwolonych tagów i ucieczką atrybutów (`tests/test_xss_prevention.py`).
- **SEC-2**: Utwardzenie uploadu dokumentów (`invoices.py`): wprowadzenie limitów rozmiaru (15 MB na plik, 50 MB na paczkę), weryfikacji nagłówków binarnych (*magic bytes* dla PDF, PNG, JPEG, JSON) oraz sanityzacji nazw plików.
- **NET-1**: Zabezpieczenie sieciowe wdrożenia – bindowanie kontenera Docker wyłącznie do pętli zwrotnej `127.0.0.1:8000`, opcjonalna autoryzacja tokenem (`TAXPILOT_ACCESS_TOKEN`) lub Basic Auth oraz doprecyzowanie architektury aplikacji jako Local-First Personal AI Assistant w `README.md`.
- **SEC-3**: Stałoczasowa weryfikacja tokena (`secrets.compare_digest`) chroniąca przed timing attacks, automatyczne stripowanie tokena z adresu URL za pomocą przekierowania 303 (ochrona historii przeglądarki i logów proxy) oraz formularz logowania `POST /login` i wylogowania `GET /logout`.
- **SEC-4**: Wymuszenie restrykcyjnych uprawnień systemu plików `chmod 600` dla plików `profil.json` przy atomowym zapisie oraz utworzenie oficjalnego dokumentu `SECURITY.md`.
- **SEC-5**: Głęboka walidacja plików uploadowanych – inspekcja strumieniowa PDF pod kątem osadzonego kodu wykonywalnego (`/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFiles`) oraz blokada złośliwych znaczników kodu w plikach tekstowych.

### Zmienione
- **TAX-1**: Wdrożenie zasady ostrożności podatkowej w `settlement_service.py` – pozycje faktur bez audytu otrzymują status `⚠️ DO_WYJASNIENIA` i 0.00 zł VAT do odliczenia (zamiast domyślnego 100% firmowego). Usunięcie kategorycznych obietnic ("100% bezpieczny") i dodanie standardowej klauzuli informacyjnej do raportów.
- **IO-1**: Wprowadzenie atomowego zapisu plików dyskowych `src/core/io.py` (`atomic_write_json`, `atomic_write_text` z użyciem unikalnych plików tymczasowych, `fsync` i atomowego `os.replace`) dla profili firm, reguł kosztowych, rejestrów i historii czatu.
- **ARCH-1**: Modularyzacja silnika rozliczeń `SettlementService` – wyodrębnienie generatorów raportów do dedykowanego pakietu `src/level_3_tax_settlement/reports/` (`SettlementMarkdownReporter`, `LedgerMarkdownReporter`, `AuditMarkdownReporter`), redukując `settlement_service.py` o ponad 700 linii.

### Jakość Kodu i Testy (QA)
- **QA-1**: Wdrożenie lintera i formatera `ruff` w konfiguracji projektu `pyproject.toml` oraz w potoku CI `.github/workflows/ci.yml`.
- **QA-1**: Pełna hermetyzacja i izolacja testów jednostkowych – testowe profile firm tworzone w izolowanych katalogach tymczasowych (`tempfile.mkdtemp`), eliminując współdzielony stan i kolizje danych testowych.
- **QA-2**: Rozszerzenie triggerów potoku CI `.github/workflows/ci.yml` o gałąź `fixes` i `feature/**`, dodanie pełnego raportowania wyników testów do GitHub Step Summary oraz aktualizacja badge'a w `README.md` (197 testów).
- **QA-3**: 100% hermetyzacji testów integracyjnych i webowych dzięki dynamicznemu proxy `TAXPILOT_DATA_DIR` w `src/config.py` – żaden test nie modyfikuje ani nie wymaga obecności danych w produkcyjnym folderze `firmy/`.

---

## [0.1.0] – 2026-11-20

### Dodane
- **Deterministyczny Silnik Podatkowo-Księgowy JDG (Zero-Hallucination Policy)**:
  - Wszelkie operacje arytmetyczne realizowane wyłącznie w Pythonie z użyciem typu `Decimal`.
  - Kalkulator składek ZUS (społeczne, wypadkowa, FP oraz składka zdrowotna na ryczałcie w 3 progach przychodowych: do 60k, do 300k, powyżej 300k zł).
  - Deterministyczne wyliczanie zaliczki na podatek zryczałtowany (PIT-28) z odliczeniem składek społecznych i 50% zapłaconej składki zdrowotnej oraz zaokrągleniem do pełnych złotych.
  - Bilans VAT-7 (VAT należny - naliczony z uwzględnieniem nadwyżki z poprzedniego okresu).
  - Automatyczne generowanie Paczki Przelewów Podatnika z rachunkami NRS (ZUS) i mikrorachunkiem Urzędu Skarbowego.
- **Ingestia Dokumentów & Integracja z KSeF 2.0**:
  - Klient KSeF 2.0 z asynchronicznym szyfrowaniem tokena autoryzacyjnego RSA-OAEP SHA-256 certyfikatem produkcyjnym i testowym MF.
  - Pobieranie i walidacja faktur ustrukturyzowanych XML `FA (2)` oraz `FA (3)`.
  - Ekstrakcja dokumentów spoza KSeF (PDF, skany, JSON, TXT) dla kosztów i sprzedaży zagranicznej z auto-routingiem i relokacją dokumentów.
  - Moduł `InvoiceDeduplicator` eliminujący kolizje KSeF vs Non-KSeF i duplikaty międzyokresowe.
- **Weryfikacja Kontrahentów & Należyta Staranność (AML & Biała Lista MF)**:
  - Automatyczna weryfikacja kontrahentów pod kątem sankcji MSWiA i unijnych list sankcyjnych.
  - Sprawdzanie statusu podatnika VAT na Białej Liście MF oraz weryfikacja numeru rachunku bankowego.
  - Generowanie oficjalnych Kart Weryfikacji Kontrahenta oraz raportów zbiorczych w formatach Markdown, PDF (A4 pejzaż) i JSON z sumami kryptograficznymi SHA-256 (archiwizacja dowodowa na 5 lat).
- **Interfejs Użytkownika (FastAPI + Jinja2 + HTMX + TailwindCSS)**:
  - Pulpit główny (Dashboard) z kluczowymi wskaźnikami KPI i kalendarzem podatkowym.
  - Widok Wstępnego Przeglądu i Akceptacji Dokumentów (Pre-settlement Review) z tabelami przychodów, kosztów i pozycji do wyjaśnienia.
  - Kwalifikacja kosztów z rozbiciem na pozycje (`100% Firmowy`, `50% Samochód`, `0% Prywatny`).
  - Zbiorcza kwalifikacja pozycji jednym kliknięciem dla faktur wielopozycyjnych posiadających powyżej 5 pozycji.
  - Dynamiczny onboarding i dodawanie nowej firmy do księgowania (`/firmy/nowa`) z automatycznym pobieraniem danych z rejestrów państwowych.
  - Asystent Copilot AI (szuflada boczna) z izolacją kontekstu firmowego i historią konwersacji.
  - Wersjonowanie aplikacji z dynamiczną detekcją tagu git i prezentacją wersji w stopce interfejsu.

[Unreleased]: https://github.com/cackoarek/TaxPilot_AI/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cackoarek/TaxPilot_AI/releases/tag/v0.1.0
