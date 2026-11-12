# TaxPilot AI 🚀

> **Autonomiczny asystent podatkowo-księgowy dla jednoosobowej działalności gospodarczej (JDG) w Polsce, w 100% niezależny od dostawcy AI (kompatybilny z Claude, ChatGPT, Gemini, Cursor, Claude Code) oraz oparty na deterministycznym silniku numerycznym Pythona.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![LLM-Agnostic](https://img.shields.io/badge/LLM-Agnostic%20(Claude%20%7C%20GPT%20%7C%20Gemini)-blueviolet.svg)](#1-naczelna-zasada-zero-hallucination-policy)
[![Zero-Hallucination](https://img.shields.io/badge/Policy-Zero--Hallucination-orange.svg)](#1-naczelna-zasada-zero-hallucination-policy)
[![KSeF 2.0 Ready](https://img.shields.io/badge/KSeF-2.0%20(FA%202%20%2F%20FA%203)-red.svg)](#ksef-20-i-faktury-elektroniczne)

---

## Spis Treści
1. [Naczelna Zasada: Zero-Hallucination Policy](#1-naczelna-zasada-zero-hallucination-policy)
2. [Szybki Start (Krok po Kroku)](#2-szybki-start-krok-po-kroku)
   - [Wymagania wstępne](#wymagania-wstępne)
   - [Krok 1: Klonowanie i wirtualne środowisko (venv)](#krok-1-klonowanie-i-wirtualne-środowisko-venv)
   - [Krok 2: Uruchomienie agenta w wybranym środowisku](#krok-2-uruchomienie-agenta-w-wybranym-środowisku)
   - [Krok 3: Kompleksowy Onboarding Firmy & KSeF (skill `inicjalizacja-firmy`)](#krok-3-kompleksowy-onboarding-firmy--ksef-skill-inicjalizacja-firmy)
3. [Praca z Agentem AI (Przykładowe Scenariusze i Komendy)](#3-praca-z-agentem-ai-przykładowe-scenariusze-i-komendy)
4. [Interfejs CLI (Wiersz Poleceń)](#4-interfejs-cli-wiersz-poleceń)
5. [Architektura 4 Poziomów](#5-architektura-4-poziomów)
6. [Struktura Danych i Multi-Tenancy](#6-struktura-danych-i-multi-tenancy)
7. [Testy Jednostkowe](#7-testy-jednostkowe)
8. [Bezpieczeństwo i Ochrona Danych](#8-bezpieczeństwo-i-ochrona-danych)

---

## 1. Naczelna Zasada: Zero-Hallucination Policy

W księgowości i podatkach nie ma miejsca na błędy statystyczne modeli językowych:

* 🧠 **LLM (Claude / ChatGPT / Gemini / Cursor / Claude Code):** Odpowiada wyłącznie za zrozumienie intencji użytkownika w języku naturalnym, orkiestrację procesu, zadawanie pytań weryfikacyjnych (Human-in-the-Loop) oraz czytelną prezentację raportów.
* ⚙️ **Deterministyczny Silnik Pythona (`Decimal`):** Wszystkie obliczenia arytmetyczne (podatki PIT-28, bilans VAT-7, progi i składki ZUS, odliczenia proporcjonalne, zaokrąglenia ordynacji podatkowej) wykonywane są w 100% deterministycznie przez kod Pythona.
* 🚫 **Rygorystyczny Zakaz:** Agentowi zabrania się liczenia podatków "w pamięci" LLM. Każda liczba w raporcie pochodzi ze zweryfikowanego wykonania funkcji matematycznej.

---

## 2. Szybki Start (Krok po Kroku)

### Wymagania wstępne
* System operacyjny: **Linux**, **macOS** lub **Windows (WSL2)**.
* **Python 3.10+** (oraz narzędzie `git`).
* Dowolne środowisko agentowe: **Claude Code**, **Cursor / Windsurf**, **Antigravity IDE** lub sam terminal.

---

### Krok 1: Klonowanie i wirtualne środowisko (venv)

Zainicjuj dedykowane wirtualne środowisko Pythona (`venv`), aby mieć pewność, że wszystkie zależności systemowe i kryptograficzne zostaną zainstalowane w izolacji:

```bash
# 1. Klonowanie repozytorium
git clone https://github.com/acacko/TaxPilot_AI.git
cd TaxPilot_AI

# 2. Utworzenie wirtualnego środowiska venv
python3 -m venv .venv

# 3. Aktywacja środowiska
# Na Linux / macOS:
source .venv/bin/activate
# Na Windows (PowerShell):
# .venv\Scripts\Activate.ps1

# 4. Aktualizacja pip i instalacja zależności
pip install --upgrade pip
pip install -r requirements.txt
```

---

### Krok 2: Uruchomienie agenta w wybranym środowisku

Wystarczy będąc w katalogu głównym projektu w terminalu odpalić odpowiednią komendę w zależności od posiadanego agenta:

* **Claude Code (Anthropic):**
  Uruchom w katalogu projektu:
  ```bash
  claude
  ```
  *(Claude automatycznie wczyta instrukcje z [AGENTS.md](AGENTS.md) i narzędzia projektu).*

* **Cursor / Windsurf / VS Code:**
  Otwórz folder projektu w edytorze. Agent AI w panelu czatu odczyta instrukcje z [AGENTS.md](AGENTS.md) i poprowadzi proces rozliczenia.

* **Antigravity IDE:**
  Otwórz katalog poleceniem `agy` – system załaduje procedury workspace z `.agents/skills/`.

* **Terminal CLI:**
  Możesz też używać TaxPilota bez żadnego modelu AI, bezpośrednio przez komendy:
  ```bash
  python -m src.cli --help
  ```

---

### Krok 3: Kompleksowy Onboarding Firmy & KSeF (skill `inicjalizacja-firmy`)

Wystarczy, że w panelu czatu napiszesz do Agenta:
> *"Cześć! Chcę skonfigurować nową firmę. Mój NIP to 7770001122."*

Dedykowany skill [inicjalizacja-firmy](.agents/skills/inicjalizacja-firmy/SKILL.md) poprowadzi Cię kompleksowo przez cały proces:
1. 🏛️ **Pobranie danych rejestrowych:** Agent automatycznie odpyta oficjalne rejestry publiczne (Biała Lista MF oraz CEIDG) po pełną nazwę firmy, REGON, siedzibę i status podatnika VAT.
2. 📋 **Profil podatkowy:** Ustali z Tobą kody PKD, formę opodatkowania (np. Ryczałt 12%) oraz schemat ZUS (Duży ZUS, Mały ZUS Plus, Ulga na Start).
3. 🔑 **Asystent Tokena KSeF 2.0:** Agent przedstawi prosty przewodnik krok po kroku do Aplikacji Podatnika KSeF 2.0 (zakładka *Tokeny* ➔ *Generuj token*), wyjaśni jak wygenerować token z uprawnieniem do odczytu faktur, poprosi Cię o jego wklejenie w czacie i **automatycznie zapisze go we właściwym miejscu** w pliku `firmy/{NIP-Nazwa}/profil.json`.
4. 📁 **Struktura katalogów:** Utworzy strukturę folderów firmy na cały rok podatkowy oraz bazowe reguły kosztowe i sprzedażowe.

*(W przypadku pracy czysto terminalowej bez Agenta AI, ten sam proces zrealizujesz przez CLI: `python -m src.cli init --nip 7770001122 ...` oraz `python -m src.cli set-token ...`).*

---

## 3. Praca z Agentem AI (Przykładowe Scenariusze i Komendy)

Możesz komunikować się z TaxPilotem w naturalnym języku polskim. Oto zestaw gotowych komend operacyjnych:

### 📥 1. Pobieranie faktur z KSeF i Non-KSeF
* *"Pobierz faktury z KSeF za czerwiec 2026"*
* *"Zaksięguj miesiąc czerwiec 2026"*
* *"Zsynchronizuj zakres od 2026-01-01 do 2026-06-30 z KSeF"*
* *"Dodałem fakturę za paliwo w PDF do folderu non-ksef-raw. Wyekstrahuj ją"*
* *"Wygeneruj mi raport o fakturach za paliwo za 2025"*

### 🔍 2. Wstępny Przegląd Przed Rozliczeniem (Pre-settlement Review)
Zanim podatki zostaną zaksięgowane, asystent generuje zestawienie weryfikacyjne w 3 tabelach:
* *"Zrób wstępny przegląd dokumentów za czerwiec 2026"*

> Asystent wyświetli:
> 1. **Tabelę przychodów** (weryfikacja kompletności sprzedaży).
> 2. **Tabelę kosztów** (czy wszystkie faktury należą do firmy).
> 3. **Pozycje do wyjaśnienia (Human-in-the-Loop)** (np. niejednoznaczne pozycje Play, pakiety medyczne).

### 🧠 3. Edukacja asystenta i trwałe reguły
Gdy asystent zapyta o pozycję sporną, wystarczy odpowiedzieć:
* *"W fakturze od operatora telekomunikacyjnego kwota 76,26 zł to internet biurowy (koszt firmy), a pozycja TV to wydatek prywatny – wyklucz go"*
* *"Kontrahent Szkolenia IT Sp. z o.o. (NIP: 5210001122) to usługi szkoleniowo-dydaktyczne. Stosuj zawsze stawkę ryczałtu 8,5%"*

> Asystent natychmiast zapisze trwałą regułę w `reguly_kosztowe.json` lub `reguly_sprzedazy.json`. W kolejnych miesiącach te pozycje sklasyfikują się automatycznie!

### 💰 4. Rozliczenie miesiąca i Paczka Przelewów
* *"Wszystko zatwierdzone. Rozlicz czerwiec 2026 i wygeneruj paczkę przelewów"*

> Asystent przeliczy zobowiązania kodem Pythona i zwróci czytelną tabelę 3 przelewów:
> * **ZUS (NRS):** kwota ze składką zdrowotną (II próg GUS) do 20. dnia miesiąca.
> * **PIT-28 (PPE):** zaliczka na podatek ryczałtowy z odliczeniem ZUS do 20. dnia miesiąca.
> * **VAT-7 (JPK_V7):** podatek VAT do wpłaty do 25. dnia miesiąca.

### 📊 5. Doradztwo i optymalizacja podatkowa
* *"Czy w przyszłym roku bardziej opłaca mi się pozostać na ryczałcie 12%, czy przejść na podatek liniowy 19%?"*
* *"Przeprowadź audyt moich kosztów – czy nie zapomniałem o jakiejś powtarzalnej fakturze (leasing, telefon, hosting)?"*

### 🛡️ 6. Weryfikacja Kontrahentów (AML, Sankcje MSWiA/UE, Biała Lista VAT)
* *"Sprawdź nowego kontrahenta NIP 5250001090 pod kątem sankcji i AML przed podpisaniem umowy"*
* *"Zweryfikuj kontrahenta i potwierdź czy rachunek bankowy PL 12 1020... jest na Białej Liście"*
* *"Przeprowadź weryfikację compliance wszystkich kontrahentów za luty 2024"*

---

## 4. Interfejs CLI (Wiersz Poleceń)

TaxPilot AI posiada pełne, skryptowalne CLI do integracji w potokach CI/CD lub dla entuzjastów terminala:

```bash
# Pomoc i spis dostępnych komend
python -m src.cli --help

# 1. Synchronizacja faktur z KSeF (miesiąc)
python -m src.cli sync --nip 7770001122 --rok 2026 --miesiac 06

# 2. Synchronizacja zakresu dat KSeF (wielomiesięczna)
python -m src.cli sync-zakres --nip 7770001122 --od 2026-01-01 --do 2026-06-30

# 3. Ekstrakcja dokumentów spoza KSeF (PDF, JPG, TXT)
python -m src.cli extract-non-ksef --nip 7770001122 --rok 2026 --miesiac 06

# 4. Wstępny przegląd dokumentów przed rozliczeniem
python -m src.cli przeglad --nip 7770001122 --rok 2026 --miesiac 06

# 5. Pełne rozliczenie miesiąca i wygenerowanie przelewów
python -m src.cli rozlicz --nip 7770001122 --rok 2026 --miesiac 06

# 6. Sekwencyjne rozliczenie wielu miesięcy (z przenoszeniem nadwyżek VAT)
python -m src.cli rozlicz-rok --nip 7770001122 --rok 2026 --od 01 --do 06

# 7. Symulacja form opodatkowania (Ryczałt vs Liniowy vs Skala)
python -m src.cli symulacja --nip 7770001122 --dochod 250000 --koszty 30000

# 8. Audyt brakujących faktur kosztowych
python -m src.cli audyt --nip 7770001122 --rok 2026 --miesiac 06

# 9. Weryfikacja kontrahenta ad-hoc (AML / Sankcje MSWiA i UE / Biała Lista VAT)
python -m src.cli weryfikuj --kontrahent-nip 5250001090 --konto "12102010260000123456789012"

# 10. Miesięczny audyt należytej staranności wszystkich kontrahentów z faktur
python -m src.cli weryfikuj-miesiac --nip 7770001122 --rok 2026 --miesiac 06
```

---

## 5. Architektura 4 Poziomów

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Poziom 4: Tax Optimization Advisor (Doradca i Optymalizacja)             │
│ • Porównanie form opodatkowania (Ryczałt vs Liniowy vs Skala)            │
│ • Audyt wycieków kosztowych i brakujących faktur cyklicznych             │
└────────────────────────────────────▲─────────────────────────────────────┘
                                     │
┌────────────────────────────────────┴─────────────────────────────────────┐
│ Poziom 3: Tax Settlement Engine (Silnik Rozliczeń i ZUS)                 │
│ • Kalkulator ZUS (baza GUS, 3 progi ryczałtu zdrowotnej: 60k/300k)       │
│ • Deterministyczny PIT-28 (zaokrąglenia ordynacji, odliczenia ZUS)       │
│ • Rejestr JPK_V7 (bilans VAT, proporcje 50% art. 86a, przeniesienia)     │
│ • Generowanie Paczki Przelewów Podatnika                                 │
└────────────────────────────────────▲─────────────────────────────────────┘
                                     │
┌────────────────────────────────────┴─────────────────────────────────────┐
│ Poziom 2: Bookkeeping & Rules Engine (Księgowanie i Kwalifikacja)        │
│ • Pre-settlement Review (Human-in-the-Loop)                              │
│ • Kwalifikacja kosztów (100% firmowe, 50% auto, 0% osobiste/medyczne)    │
│ • Obsługa stawek ryczałtu (12% IT, 8,5% edukacja PKWiU 85.x)             │
│ • Separacja korekt KSeF in-minus (art. 29a ust. 13 VAT vs art. 14 PIT)   │
└────────────────────────────────────▲─────────────────────────────────────┘
                                     │
┌────────────────────────────────────┴─────────────────────────────────────┐
│ Poziom 1: Ingestion & Storage (KSeF 2.0 & Non-KSeF)                      │
│ • Klient KSeF 2.0 (szyfrowanie RSA-OAEP SHA-256 certyfikatami MF)        │
│ • Parser XML FA (2) i FA (3), faktury w cenach netto i brutto            │
│ • Ekstraktor Non-KSeF (paragony paliwowe BFK, rachunki zagraniczne PDF)  │
│ • Symetryczna wielonajemna struktura dyskowa firmy                       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Struktura Danych i Multi-Tenancy

System opiera się na przejrzystej strukturze katalogów – dane każdej firmy są w 100% odseparowane:

```text
firmy/
└── {NIP-NazwaFirmy}/
    ├── profil.json                     # Profil podatnika (NIP, ZUS, forma opodatkowania, token KSeF)
    ├── reguly_kosztowe.json            # Nauczone reguły kwalifikacji kosztów
    ├── reguly_sprzedazy.json           # Reguły stawek ryczałtu dla kontrahentów (np. 8,5% usługi szkoleniowe)
    ├── faktury/
    │   └── {ROK}/
    │       └── {MIESIAC}/
    │           ├── sprzedaz/
    │           │   ├── ksef/               # Faktury sprzedaży z KSeF (.xml i .json)
    │           │   ├── non-ksef-raw/       # Oryginalne pliki (PDF, TXT, JSON)
    │           │   └── non-ksef-extracted/ # Znormalizowane encje sprzedaży
    │           └── koszty/
    │               ├── ksef/               # Faktury kosztowe z KSeF (.xml i .json)
    │               ├── non-ksef-raw/       # Skany, paragony, faktury zagraniczne
    │               └── non-ksef-extracted/ # Znormalizowane encje kosztów
    └── rozliczenia/
        └── {ROK}/
            └── {MIESIAC}/
                ├── rozliczenie.json    # Maszynowy stan rozliczenia
                └── rozliczenie.md      # Oficjalny raport z Paczką Przelewów Podatnika
```

---

## 7. Testy Jednostkowe

Repozytorium posiada bogaty zestaw deterministycznych testów jednostkowych weryfikujących poprawność algorytmów numerycznych, szyfrowania, wskaźników GUS oraz logiki podatkowej:

```bash
# Uruchomienie wszystkich testów
python -m unittest discover tests
```

Zakres testów obejmuje m.in.:
* Deterministyczne wyliczanie składek ZUS i wskaźników GUS ([test_zus_indicators.py](tests/test_zus_indicators.py)).
* Parsowanie faktur KSeF w cenach netto, brutto i korekt in-minus ([test_ksef_parser.py](tests/test_ksef_parser.py)).
* Obsługę terminów otrzymania faktur kosztowych i prawa do odliczenia VAT art. 86 ust. 10b ([test_invoice_timing.py](tests/test_invoice_timing.py)).
* Ekstrakcję dokumentów spoza KSeF ([test_non_ksef_extractor.py](tests/test_non_ksef_extractor.py)).
* Kompletne rozliczenie podatkowo-składkowe ([test_settlement_service.py](tests/test_settlement_service.py)).

---

## 8. Bezpieczeństwo i Ochrona Danych

* 🔒 **Prywatność:** Dane firm, kontrahentów i faktury przechowywane są wyłącznie lokalnie w katalogu `firmy/`. Plik `.gitignore` chroni przed ich przypadkowym wypchnięciem do zdalnego repozytorium.
* 🔑 **Bezpieczeństwo KSeF:** Klucze i tokeny autoryzacyjne szyfrowane są algorytmem RSA-OAEP z dopełnieniem MGF1 i hashem SHA-256 zgodnie z oficjalną specyfikacją Ministerstwa Finansów.
* 🌐 **Dynamiczny Cache Danych Publicznych:** Wskaźniki GUS pobierane są dynamicznie z sieci, a katalog `data/` jest ignorowany w gicie ([data/.gitignore](data/.gitignore)), uniemożliwiając commitowanie nieaktualnych danych statystycznych.

---

<p align="center">
  Stworzone z myślą o polskich przedsiębiorcach JDG 🇵🇱<br/>
  <b>TaxPilot AI – Twoja księgowość pod pełną kontrolą.</b>
</p>
