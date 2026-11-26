# 🚀 Rozdział 1: Szybki Start & Wdrożenie

Niniejszy przewodnik poprowadzi Cię krok po kroku przez instalację, konfigurację środowiska oraz pierwsze uruchomienie systemu **TaxPilot AI**.

---

## 1. Wymagania Systemowe

TaxPilot AI działa w modelu **Local-First** i jest w pełni samowystarczalny. Nie wymaga zewnętrznych baz danych SQL (np. PostgreSQL czy MySQL) ani instalacji narzędzi Poppler/pdftotext (dzięki natywnej obsłudze PDF w oparciu o czysty Python).

* **System operacyjny:** Linux (Ubuntu 20.04+, Debian, Fedora, Arch), Windows 10/11, macOS 12+ (Apple Silicon & Intel).
* **Python:** wersja **3.10**, **3.11** lub **3.12** (zalecana: Python 3.11+).
* **Menedżer pakietów:** standardowy `pip` oraz moduł `venv`.
* **Przeglądarka internetowa:** dowolna nowoczesna przeglądarka (Chrome, Firefox, Safari, Edge, Brave).
* *(Opcjonalnie)* **Docker & Docker Compose** (jeśli preferujesz uruchamianie w izolowanym kontenerze).

---

## 2. Klonowanie Repozytorium i Przygotowanie Środowiska

### Krok 2.1: Sklonuj repozytorium
```bash
git clone https://github.com/cackoarek/TaxPilot_AI.git
cd TaxPilot_AI
```

### Krok 2.2: Utwórz i aktywuj wirtualne środowisko (venv)

* **Linux / macOS:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```

* **Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  ```

* **Windows (Wiersz poleceń CMD):**
  ```cmd
  python -m venv .venv
  .venv\Scripts\activate.bat
  ```

### Krok 2.3: Zainstaluj zależności projektu
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> [!TIP]
> Jeśli planujesz współtworzenie projektu lub uruchamianie pełnego pakietu testów i linterna, doinstaluj narzędzia deweloperskie:
> ```bash
> pip install ruff mypy coverage
> ```

---

## 3. Konfiguracja Środowiska (`.env`)

Skopiuj przykładowy plik konfiguracyjny `.env.example` lub utwórz plik `.env` w katalogu głównym projektu:

```bash
cp .env.example .env
```

### Dostępne Zmienne Środowiskowe

```ini
# ==============================================================================
# KONFIGURACJA TAXPILOT AI
# ==============================================================================

# Adres i port serwera interfejsu Web UI
TAXPILOT_HOST=127.0.0.1
TAXPILOT_PORT=8000

# Opcjonalny token zabezpieczający dostęp do Web UI (SEC-3, SEC-6)
# Jeśli ustawiony, wejście do aplikacji wymaga autoryzacji w formularzu /login
# TAXPILOT_ACCESS_TOKEN=twoj-tajny-bezpieczny-token-dostepu-min-32-znaki

# Opcjonalne symetryczne szyfrowanie wrażliwych tokenów w profil.json (SEC-13)
# TAXPILOT_ENCRYPTION_KEY=twoj-klucz-szyfrowania-at-rest

# Dostawca modeli AI (opcjonalnie do zaawansowanej analizy dokumentów Vision/OCR)
# GEMINI_API_KEY=AIzaSy...
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...

# Token API CEIDG (dane.biznes.gov.pl) - opcjonalny, pozwala pobierać dane firm
# CEIDG_API_TOKEN=twoj_token_ceidg
```

> [!IMPORTANT]
> Aplikacja działa w pełni deterministycznie nawet **bez skonfigurowanego klucza API do modelu LLM**! Wszystkie kalkulacje podatkowe, ZUS, VAT oraz weryfikacje AML i KSeF wykonywane są w 100% lokalnie przez kod Pythona.

---

## 4. Uruchomienie Aplikacji

### Metoda A: Uruchomienie Interfejsu Webowego (Zalecane)

Użyj wygodnego skryptu startowego dostosowanego do Twojego systemu:

* **Linux / macOS:**
  ```bash
  chmod +x run_web.sh
  ./run_web.sh
  ```

* **Windows (PowerShell):**
  ```powershell
  .\run_web.ps1
  ```

* **Windows (CMD):**
  ```cmd
  run_web.bat
  ```

* **Bezpośrednio przez moduł CLI:**
  ```bash
  python -m src.cli web --host 127.0.0.1 --port 8000
  ```

Po uruchomieniu otwórz przeglądarkę pod adresem:  
👉 **`http://127.0.0.1:8000`**

---

### Metoda B: Uruchomienie w Kontenerze Docker

Dla użytkowników preferujących konteneryzację przygotowano gotowy stos Docker Compose:

```bash
docker compose up -d
```

Aplikacja zbindowana jest wyłącznie do pętli zwrotnej `127.0.0.1:8000`, a dane firmowe montowane są trwale z katalogu `./firmy`.

---

## 5. Onboarding Pierwszej Firmy

System TaxPilot AI obsługuje wiele firm jednocześnie (*Multi-Tenant*). Aby rozpocząć pracę, zainicjalizuj profil swojego podmiotu gospodarczego:

### Opcja 1: Z poziomu wiersza poleceń (CLI)

Wystarczy podać NIP – system automatycznie odpyta rejestr państwowy (Biała Lista VAT MF oraz CEIDG) i pobierze oficjalną nazwę, adres oraz REGON:

```bash
python -m src.cli init-firma \
  --nip 7770001122 \
  --forma RYCZALT \
  --stawka-ryczaltu 0.12 \
  --zus PELNY_ZUS \
  --srodowisko TEST
```

### Opcja 2: Z poziomu interfejsu Web UI

1. W prawym górnym rogu paska nawigacyjnego kliknij selektor firm i wybierz **"+ Dodaj nową firmę"** (lub przejdź do `/firmy`).
2. Wpisz 10-cyfrowy NIP i kliknij **"Pobierz dane z rejestru"**.
3. Wybierz formę opodatkowania (np. Ryczałt od przychodów ewidencjonowanych 12%), schemat składek ZUS oraz wprowadź swój token autoryzacyjny KSeF.
4. Kliknij **"Zapisz profil firmy"**.

System natychmiast utworzy dedykowaną, izolowaną strukturę dyskową:
```text
firmy/7770001122-Nazwa_Twojej_Firmy/
├── profil.json
├── reguly_kosztowe.json
├── reguly_sprzedazy.json
├── faktury/
├── rozliczenia/
└── weryfikacje/
```

---

## 6. Szybka Weryfikacja Poprawności Instalacji

Sprawdź, czy bateria testów jednostkowych i integracyjnych przechodzi bez błędów w Twoim środowisku:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Oczekiwany rezultat:
```text
Ran 255 tests in ~30s
OK (skipped=1)
```

---

## ⏭️ Kolejny Rozdział

Poznaj zasady działania zespołu agentów oraz separacji arytmetyki od sztucznej inteligencji:  
👉 [**Przejdź do: 02. Architektura & Zespół Agentów**](02_architektura_i_agenci.md)
