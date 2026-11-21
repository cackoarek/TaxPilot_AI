# Changelog

Wszystkie istotne zmiany w projekcie TaxPilot AI są dokumentowane w tym pliku.

Format bazuje na [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/).
Projekt stosuje [Semantic Versioning](https://semver.org/lang/pl/).

---

## [Unreleased]

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
