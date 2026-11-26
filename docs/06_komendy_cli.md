# 💻 Rozdział 6: Podręcznik Poleceń CLI

Interfejs wiersza poleceń (**CLI**) w TaxPilot AI umożliwia pełną automatyzację rozliczeń podatkowych, integrację ze skryptami CI/CD oraz działanie w środowiskach bez środowiska graficznego (np. na serwerach headless lub w kontenerach).

Podstawowa składnia wywołania:
```bash
python -m src.cli <POLECENIE> [OPCJE]
```

---

## 1. Zarządzanie Systemem & Web UI

### `version`
Wyświetla aktualną wersję aplikacji TaxPilot AI:
```bash
python -m src.cli version
```

### `web` (aliasy: `serve`, `gui`)
Uruchamia lokalny serwer interfejsu graficznego (FastAPI + Uvicorn):
```bash
python -m src.cli web --host 127.0.0.1 --port 8000
```
* Opcje:
  * `--host`: adres nasłuchiwania (domyślnie `127.0.0.1`),
  * `--port`: port serwera (domyślnie `8000`),
  * `--no-reload`: wyłącza mechanizm auto-reload (przydatne na produkcji).

---

## 2. Onboarding i Konfiguracja Podatnika

### `init-firma` (alias: `init`)
Inicjalizuje nowy profil firmy, tworząc strukturę katalogów i automatycznie odpytując rejestry publiczne (Biała Lista VAT MF, CEIDG):
```bash
python -m src.cli init-firma \
  --nip 7770001122 \
  --forma RYCZALT \
  --stawka-ryczaltu 0.12 \
  --zus PELNY_ZUS \
  --srodowisko TEST
```
* Opcje:
  * `--nip`: 10-cyfrowy NIP firmy (wymagany),
  * `--forma`: forma opodatkowania (`RYCZALT`, `LINIOWY`, `SKALA`),
  * `--stawka-ryczaltu`: domyślna stawka ryczałtu (np. `0.12` dla IT/Software),
  * `--zus`: schemat składek (`PELNY_ZUS`, `MALY_ZUS_PLUS`, `ULGA_NA_START`, `TYLKO_ZDROWOTNA`),
  * `--bez-chorobowego`: wyłącza dobrowolną składkę chorobową,
  * `--token`: token autoryzacyjny KSeF,
  * `--srodowisko`: środowisko KSeF (`TEST` lub `PROD`),
  * `--no-fetch`: pomija pobieranie danych online z rejestrów.

### `set-token`
Zapisuje token autoryzacyjny KSeF w profilu podatnika (`firmy/{nazwa}/profil.json`):
```bash
python -m src.cli set-token --nip 7770001122 --token "<TWOJ_TOKEN_KSEF>" --srodowisko TEST
```

### `set-certs`
Wgrywa parę certyfikatów i kluczy prywatnych do autoryzacji lub trybu offline KSeF:
```bash
python -m src.cli set-certs \
  --nip 7770001122 \
  --auth-cert "/sciezka/do/auth.crt" \
  --auth-key "/sciezka/do/auth.key" \
  --auth-password "opcjonalne_haslo" \
  --srodowisko TEST
```

---

## 3. Ingestia i Ekstrakcja Dokumentów

### `sync`
Pobiera paczkę faktur ustrukturyzowanych XML z KSeF 2.0 za wskazany miesiąc:
```bash
python -m src.cli sync --nip 7770001122 --rok 2026 --miesiac 10
```

### `sync-zakres`
Pobiera faktury z KSeF dla ciągłego zakresu dat ISO (np. wiele miesięcy w pojedynczej sesji):
```bash
python -m src.cli sync-zakres \
  --nip 7770001122 \
  --od 2026-01-01 \
  --do 2026-10-31
```

### `extract-non-ksef`
Przetwarza dokumenty z katalogów surowych (`non-ksef-raw/`) do postaci znormalizowanej (`non-ksef-extracted/`):
```bash
python -m src.cli extract-non-ksef --nip 7770001122 --rok 2026 --miesiac 10
```
* Opcje:
  * `--typ`: zakres ekstrakcji (`sprzedaz`, `koszty`, `all`),
  * `--force`: wymusza ponowną ekstrakcję,
  * `--ai`: włącza zaawansowaną analizę multimodalną Vision/OCR przez agenta AI.

---

## 4. Wstępny Przegląd & Uczenie Reguł

### `przeglad` (alias: `review`)
Generuje zestawienie weryfikacyjne przed księgowaniem (3 tabele: przychody, koszty, pozycje do wyjaśnienia):
```bash
python -m src.cli przeglad --nip 7770001122 --rok 2026 --miesiac 10
```

### `regula`
Zapisuje trwałą regułę kwalifikacji kosztowej dla powtarzających się opisów pozycji faktury:
```bash
python -m src.cli regula \
  --nip 7770001122 \
  --wzorzec "usługi inne" \
  --kwalifikacja FIRMOWY_100 \
  --uzasadnienie "Usługi doradztwa technicznego na rzecz klienta"
```

---

## 5. Księgowanie i Rozliczenia Podatkowe

### `rozlicz`
Wykonuje deterministyczne kalkulacje ZUS, PIT-28 i VAT-7 oraz generuje oficjalne raporty:
```bash
python -m src.cli rozlicz --nip 7770001122 --rok 2026 --miesiac 10 --nadwyzka-vat 0.00
```
Wygenerowane raporty:
* `firmy/{nazwa}/rozliczenia/2026/10/rozliczenie.md` (Paczka Przelewów z rachunkami)
* `firmy/{nazwa}/rozliczenia/2026/10/ewidencja-przychodow.md` (Ewidencja ryczałtu)
* `firmy/{nazwa}/rozliczenia/2026/10/ewidencja-przychodow-sumy.md` (Zestawienie narastające YTD)
* `firmy/{nazwa}/rozliczenia/2026/10/sprawozdanie.md` (Audyt dokumentów)

### `rozlicz-rok`
Sekwencyjnie rozlicza wiele miesięcy z automatycznym przenoszeniem nadwyżek podatku VAT:
```bash
python -m src.cli rozlicz-rok --nip 7770001122 --rok 2026 --od 1 --do 12
```

### `agregat-vat` (aliasy: `vat-kategorie`, `vat-sumy`)
Agreguje odliczenia podatku VAT według branż i kategorii zakupowych:
```bash
python -m src.cli agregat-vat --nip 7770001122 --rok 2026 --zapisz
```

---

## 6. Compliance AML & Weryfikacja Należytej Staranności

### `weryfikuj`
Weryfikuje pojedynczego kontrahenta pod kątem list sankcyjnych MSWiA/UE oraz statusu na Białej Liście VAT MF:
```bash
python -m src.cli weryfikuj \
  --kontrahent-nip 5213242793 \
  --konto 84101010230000261395100000 \
  --kwota 12300.00 \
  --firma 7770001122 \
  --rok 2026 \
  --miesiac 10
```

### `weryfikuj-miesiac`
Przeprowadza zbiorczą weryfikację compliance dla wszystkich kontrahentów, z którymi przeprowadzono transakcje w danym miesiącu:
```bash
python -m src.cli weryfikuj-miesiac --nip 7770001122 --rok 2026 --miesiac 10
```

---

## 7. Optymalizacja i Narzędzia Doradcy

### `symulacja`
Porównuje roczne obciążenia fiskalne dla różnych form opodatkowania:
```bash
python -m src.cli symulacja \
  --nip 7770001122 \
  --przychod 300000 \
  --koszty 40000 \
  --stawka-ryczaltu 0.12
```

### `audyt`
Wykrywa anomalie i brakujące powtarzalne faktury kosztowe (np. brak faktury za telefon lub biuro):
```bash
python -m src.cli audyt --nip 7770001122 --rok 2026 --miesiac 10
```

---

## 8. Kopie Zapasowe & Disaster Recovery

### `backup`
Tworzy bezpieczne archiwum `.tar.gz` z plikiem sumy kontrolnej `.sha256`:
```bash
python -m src.cli backup --nip 7770001122
```

### `restore`
Bezpiecznie przywraca firmę z kopii zapasowej (z ochroną przed TarSlip CWE-22):
```bash
python -m src.cli restore /sciezka/do/backup_7770001122_20261126_204500.tar.gz
```

---

## 🏁 Podsumowanie

Wszystkie komendy wspierają parametr `--help`, który wyświetla szczegółowy opis argumentów i flag:
```bash
python -m src.cli <KOMENDA> --help
```
