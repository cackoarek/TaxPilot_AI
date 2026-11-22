# Changelog

Wszystkie istotne zmiany w projekcie TaxPilot AI są dokumentowane w tym pliku.

Format bazuje na [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/).
Projekt stosuje [Semantic Versioning](https://semver.org/lang/pl/).

---

## [Unreleased]

### Bezpieczeństwo
- **SEC-1**: Eliminacja podatności XSS (CWE-79) w module Markdown Copilota i raportach za pomocą deterministycznego escapowania HTML (`html.escape` + `MarkupSafe`) z walidacją dozwolonych protokołów URI (`tests/test_xss_prevention.py`).
- **SEC-2**: Utwardzenie uploadu dokumentów (`invoices.py`): wprowadzenie limitów rozmiaru (15 MB na plik, 50 MB na paczkę), weryfikacji nagłówków binarnych (*magic bytes* dla PDF, PNG, JPEG, JSON) oraz sanityzacji nazw plików.
- **NET-1**: Zabezpieczenie sieciowe wdrożenia – bindowanie kontenera Docker wyłącznie do pętli zwrotnej `127.0.0.1:8000`, opcjonalna autoryzacja tokenem (`TAXPILOT_ACCESS_TOKEN`) lub Basic Auth oraz doprecyzowanie architektury aplikacji jako Local-First Personal AI Assistant w `README.md`.
- **SEC-3**: Stałoczasowa weryfikacja tokena (`secrets.compare_digest`) chroniąca przed timing attacks, automatyczne stripowanie tokena z adresu URL za pomocą przekierowania 303 (ochrona historii przeglądarki i logów proxy) oraz formularz logowania `POST /login` i wylogowania `GET /logout`.
- **SEC-4**: Wymuszenie restrykcyjnych uprawnień systemu plików `chmod 600` dla plików `profil.json` przy atomowym zapisie oraz utworzenie oficjalnego dokumentu `SECURITY.md`.
- **SEC-5**: Głęboka walidacja plików uploadowanych – inspekcja strumieniowa PDF pod kątem osadzonego kodu wykonywalnego (`/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFiles`) oraz blokada złośliwych znaczników kodu w plikach tekstowych.
- **SEC-6**: Dynamiczna flaga `Secure=True` dla ciasteczek sesyjnych w środowiskach HTTPS (`request.url.scheme == "https"`, nagłówek `X-Forwarded-Proto: https` lub env `TAXPILOT_COOKIE_SECURE=1`).
- **SEC-7**: Ochrona przed atakami brute-force na endpointzie `/login` – in-memory rate limiter per IP (maks. 5 prób/min), stałoczasowe opóźnienie ochronne (1.0 s) przy błędnym tokenie, nagłówki `Cache-Control: no-store, no-cache, must-revalidate` oraz jednolity komunikat błędu.
- **SEC-8**: Walidacja wejściowa długości tokena (max 256 znaków) oraz logowanie ostrzeżenia przy starcie serwera, jeśli skonfigurowany token ma mniej niż 32 znaki.
- **SEC-9**: Ochrona przed podatnością Open Redirect w formularzu logowania (CWE-601) poprzez restrykcyjną walidację ścieżki docelowej (`is_safe_redirect_url`), blokując zewnętrzny host, protocol-relative URL (`//evil.com`) i znaki kontrolne.
- **SEC-10**: Automatyczna migracja uprawnień dyskowych (`migrate_data_permissions`) przy starcie aplikacji FastAPI – wymuszenie `chmod 700` dla folderów firmowych oraz `chmod 600` dla plików `profil.json` i reguł.
- **SEC-11**: Ochrona przed atakami CSRF w architekturze Local-First poprzez weryfikację nagłówków `Origin` i `Referer` dla metod mutujących stan (`POST`, `PUT`, `DELETE`, `PATCH`), odrzucając żądania pochodzące z obcych domen (`403 Forbidden`).
- **SEC-12**: Sformalizowanie kontraktu bezpieczeństwa renderera Markdown (`src/web/utils/markdown.py`) z testami odpornościowymi na wstrzyknięcia DOM i tabel.
- **SEC-13**: Wdrożenie symetrycznego szyfrowania at-rest dla wrażliwych danych (`src/core/security.py`) opartego na algorytmie Fernet (`AES-128-CBC` + `HMAC-SHA256`) z derywacją PBKDF2-HMAC-SHA256. Automatyczne szyfrowanie tokenów KSeF oraz kluczy API w `profil.json` przy obecności zmiennej `TAXPILOT_ENCRYPTION_KEY` z zachowaniem pełnej wstecznej kompatybilności.
- **SEC-14**: Utwardzenie odporności procesu ingestii dokumentów PDF (ochrona przed DoS / zawieszeniem procesu) w `non_ksef_extractor.py` – dodanie limitu czasu `timeout=15.0s`, obsługi `TimeoutExpired` oraz dynamicznego wykrywania ścieżki do `pdftotext` przez `shutil.which`.
- **SEC-15**: Wdrożenie uniwersalnego middleware nagłówków bezpieczeństwa HTTP w `src/web/app.py` dodającego do każdej odpowiedzi: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` oraz restrykcyjny nagłówek `Content-Security-Policy`.
- **SEC-16**: Ochrona przed podatnością Open Redirect w routerze firm (`src/web/routers/companies.py`) dla tras `POST /firmy/switch` i `POST /firmy/period` poprzez walidację ścieżki za pomocą `is_safe_redirect_url` z fallbackiem do `/` oraz zabezpieczenie ciasteczek sesyjnych atrybutami `samesite="lax"` i dynamiczną flagą `secure=is_secure_request(request)`.
- **SEC-17**: Wdrożenie funkcji atomowego zapisu binarnego `atomic_write_bytes` w `src/core/io.py` z domyślnymi uprawnieniami `0600` i opcjonalną blokadą `file_lock`. Wykorzystanie jej w module uploadu faktur (`src/web/routers/invoices.py`), eliminując ryzyko zapisu poufnych dokumentów z domyślnym umask OS.
- **SEC-18**: Ochrona pliku `.env` i sekretów konfiguracyjnych w `src/web/routers/settings.py` – eliminacja podatności CRLF / Env Var Injection poprzez odrzucenie wieloliniowych wartości oraz atomowy zapis pliku `.env` z uprawnieniami `0600` i blokadą `file_lock`.
- **SEC-19**: Pełne i deterministyczne kodowanie encji HTML w dymkach czatu Copilota i tytułach sesji (`copilot.py`) za pomocą `html.escape(..., quote=True)` (eliminacja niepełnego escapowania CWE-116).

### Zmienione
- **INGEST-1**: Wdrożenie natywnej, bezprocesowej ekstrakcji tekstu z dokumentów PDF opartej o czysto pythonową bibliotekę `pypdf` w `non_ksef_extractor.py` oraz `ai_document_extractor.py` z opcjonalnym fallbackiem do systemowego `pdftotext`. Aplikacja nie wymaga instalacji żadnych zewnętrznych binariów (np. Poppler) i działa w pełni samowystarczalnie zarówno na Linuxie, jak i na Windowsie (`tests/test_pdf_extraction_pypdf.py`).
- **VAL-1**: Wdrożenie dedykowanego modułu walidatorów fiskalnych `src/core/validators.py` z formalnymi algorytmami sum kontrolnych:
  - NIP: algorytm wagowy `[6, 5, 7, 2, 3, 4, 5, 6, 7]` i reszta modulo 11,
  - REGON: REGON-9 z wagami `[8, 9, 2, 3, 4, 5, 6, 7]` oraz REGON-14 z kontrolą modulo 11,
  - NRB / IBAN PL: 26-cyfrowy rachunek bankowy z algorytmem ISO 7064 Modulo 97-10.
  Zintegrowano walidację w `CompanyProfile.create`, `initialize_company`, `src/cli.py` oraz `src/web/routers/companies.py`.
- **CONCUR-2**: Zabezpieczenie spójności historii synchronizacji KSeF w `src/level_1_ingestion/ksef_client.py` – zastąpienie bezpośredniego `open(..., "w")` bezpiecznym wywołaniem `atomic_write_json` z uprawnieniami `0600` i blokadą `lock=True`.
- **NUM-1**: Rygorystyczne egzekwowanie Zero-Hallucination Policy i typu `Decimal` w `ksef_client.py:sync_month_invoices` (zamiana `sum(..., 0)` na `sum(..., Decimal("0.00"))`).
- **PERM-1**: Rozszerzenie procedury migracji uprawnień dyskowych `migrate_data_permissions` na wszystkie pliki w katalogach firmowych (nadanie `0600` wszystkim plikom, `0700` folderom – defense-in-depth).
- **PROC-1**: Hermetyzacja podprocesu streamingu `agy` w `antigravity_provider.py` poprzez dodanie `stdin=asyncio.subprocess.DEVNULL`.
- **TAX-2**: Ochrona bilansu podatku VAT-7 przed zniekształceniem w przypadku wprowadzenia ujemnej nadwyżki z poprzedniego okresu (`bezpieczna_nadwyzka = max(Decimal("0.00"), ...)` w `vat_tools.py` i routerze rozliczeń).
- **TAX-1**: Wdrożenie zasady ostrożności podatkowej w `settlement_service.py` – pozycje faktur bez audytu otrzymują status `⚠️ DO_WYJASNIENIA` i 0.00 zł VAT do odliczenia (zamiast domyślnego 100% firmowego). Usunięcie kategorycznych obietnic ("100% bezpieczny") i dodanie standardowej klauzuli informacyjnej do raportów.
- **IO-1**: Wprowadzenie atomowego zapisu plików dyskowych `src/core/io.py` (`atomic_write_json`, `atomic_write_text` z użyciem unikalnych plików tymczasowych, `fsync` i atomowego `os.replace`) dla profili firm, reguł kosztowych, rejestrów i historii czatu.
- **IO-2**: Wprowadzenie menedżera blokad dyskowych `file_lock` opartego o `fcntl.flock` w `src/core/io.py` oraz helpera `InvoiceStorage.get_invoice_dir(profile, rok, miesiac, typ)` eliminującego ryzyko kolizji współbieżnych operacji I/O.
- **CONCUR-1**: Zabezpieczenie spójności procesu finalizacji miesiąca w `SettlementService.settle_month` – objęcie operacji zapisu pakietu 5 raportów rozliczeniowych blokadą `file_lock(target_dir / ".settlement.lock")`.
- **DRY-1**: Deduplikacja renderera Markdown oraz walidatora URL – wyeliminowanie zduplikowanego kodu z `src/web/routers/copilot.py` na rzecz centralnego modułu `src/web/utils/markdown.py` z rozszerzeniem o parametr `header_shift`.
- **LOG-1**: Poprawa jakości logowania – korekta literówki w nazwie pliku logów (`ai_assistant.log`) oraz jawne rejestrowanie ostrzeżeń `logger.warning` przy błędach procedury compliance AML w `settlement_service.py` (eliminacja cichego tłumienia wyjątków).
- **ARCH-1**: Modularyzacja silnika rozliczeń `SettlementService` – wyodrębnienie generatorów raportów do dedykowanego pakietu `src/level_3_tax_settlement/reports/` (`SettlementMarkdownReporter`, `LedgerMarkdownReporter`, `AuditMarkdownReporter`), redukując `settlement_service.py` o ponad 700 linii.

### Jakość Kodu i Testy (QA)
- **DEV-1**: Wprowadzenie deterministycznego pliku blokady zależności `requirements.lock` z zamrożonymi wersjami bibliotek głównych i tranzytywnych.
- **QA-1**: Wdrożenie lintera i formatera `ruff` w konfiguracji projektu `pyproject.toml` oraz w potoku CI `.github/workflows/ci.yml`.
- **QA-1**: Pełna hermetyzacja i izolacja testów jednostkowych – testowe profile firm tworzone w izolowanych katalogach tymczasowych (`tempfile.mkdtemp`), eliminując współdzielony stan i kolizje danych testowych.
- **QA-2**: Rozszerzenie triggerów potoku CI `.github/workflows/ci.yml` o budowanie wszystkich gałęzi (`branches: ['**']`), dodanie concurrency `cancel-in-progress` oraz pełnego raportowania wyników testów do GitHub Step Summary.
- **QA-3**: 100% hermetyzacji testów integracyjnych i webowych dzięki dynamicznemu proxy `TAXPILOT_DATA_DIR` w `src/config.py` – żaden test nie modyfikuje ani nie wymaga obecności danych w produkcyjnym folderze `firmy/`.
- **QA-4**: Dodanie dedykowanego pakietu testów `tests/test_web_security_hardening.py` weryfikującego zabezpieczenia przed atakami Open Redirect, brute-force, CSRF oraz uprawnienia systemu plików (wzrost zestawu do 205 testów).
- **QA-5**: Wdrożenie rygorystycznej statycznej analizy typów `mypy` w potoku CI oraz konfiguracji `[tool.mypy]` w `pyproject.toml` (0 błędów w 69 plikach źródłowych `src/`).
- **QA-6**: Konfiguracja narzędzia pomiaru pokrycia kodu `coverage.py` w `pyproject.toml` oraz weryfikacji raportu pokrycia w workflow GitHub Actions.
- **QA-7**: Eliminacja ostrzeżeń `StarletteDeprecationWarning` w testach integracyjnych oraz dodanie testów szyfrowania sekretów i współbieżności I/O (wzrost zestawu do 216 testów, 100% passed).
- **QA-8**: Dodanie testów weryfikujących obecność nagłówków bezpieczeństwa HTTP (wzrost zestawu do 217 testów, 100% passed).
- **QA-9**: Dodanie dedykowanych pakietów testowych `tests/test_validators.py` oraz `tests/test_audit03_hardening.py` weryfikujących algorytmy sum kontrolnych NIP/REGON/NRB, Open Redirect, atomowy zapis binarny, sanityzację `.env` i odporność podatkową (wzrost zestawu do 232 testów, 100% passed, 72% coverage).

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
