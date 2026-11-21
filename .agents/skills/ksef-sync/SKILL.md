---
name: ksef-sync
description: >-
  Użyj tego skilla, gdy użytkownik prosi o pobranie, import lub synchronizację faktur z Krajowego Systemu
  e-Faktur (KSeF 2.0) dla wybranego miesiąca lub roku (np. "Ściągnij faktury z KSeF za październik", "Synchronizuj KSeF").
  Obsługuje środowiska PROD i TEST, szyfrowanie RSA-OAEP SHA-256 oraz zapis w archiwum firmy.
---

# Procedura Synchronizacji Faktur z KSeF 2.0

Ten skill instruuje agenta, jak bezpiecznie połączyć się z bramką produkcyjną lub testową Krajowego Systemu e-Faktur (KSeF 2.0) i pobrać komplet faktur sprzedaży oraz kosztów.

## Wymagania Wstępne i Konfiguracja Tokena KSeF

1. Token autoryzacyjny oraz środowisko KSeF przechowywane są bezpośrednio w pliku profilu firmy:
   `firmy/{NIP-Nazwa}/profil.json`:
   ```json
   {
     "ksef": {
       "srodowisko": "PROD",
       "token": "0261108-EC-..."
     }
   }
   ```
2. Zapis lub aktualizacja tokena KSeF może odbyć się:
   * Bezpośrednio w pliku `profil.json`,
   * Lub za pomocą polecenia CLI:
     ```bash
     python -m src.cli set-token --nip {NIP} --token "{TOKEN}" --srodowisko PROD
     ```

## Kroki Wykonania

### 1. Uruchomienie Synchronizacji

W zależności od potrzeb użytkownika agent wybiera odpowiedni tryb:

**A. Synchronizacja pojedynczego miesiąca:**
```bash
python -m src.cli sync --nip {NIP} --rok {ROK} --miesiac {MIESIAC}
```

**B. Synchronizacja całego roku lub zakresu miesięcy:**
Gdy użytkownik prosi o pobranie faktur za cały rok lub wiele miesięcy (np. "Ściągnij wszystkie faktury za 2026", "Zsynchronizuj I półrocze"):
```bash
python -m src.cli sync-zakres --nip {NIP} --od 2026-01-01 --do 2026-12-31
```
*Uwaga:* Tryb `sync-zakres` jest wysoce zoptymalizowany pod kątem limitów API KSeF (Rate Limiting) – pobiera cały zakres w zaledwie 2 zapytaniach (sprzedaż i zakupy), a następnie automatycznie porządkuje i zapisuje faktury w strukturze katalogów dla właściwych miesięcy (`faktury/{ROK}/{MIESIAC}/...`).

Alternatywnie agent może również wykonać pętlę sekwencyjną miesiąc po miesiącu wywołując `python -m src.cli sync ...`.

### 2. Działanie pod maską (KSeF 2.0 Protocol):
Klient `KSeFClient` automatycznie:
1. Pobiera wyzwanie (`POST /auth/challenge`).
2. Pobiera aktualny certyfikat szyfrujący MF (`GET /security/public-key-certificates`).
3. Szyfruje ciąg `token|timestampMs` algorytmem RSA-OAEP z SHA-256.
4. Inicjalizuje sesję (`POST /auth/ksef-token`) i odbiera `accessToken` JWT (`POST /auth/token/redeem`).
5. Odpytuje listę faktur sprzedaży (`Subject1`) oraz zakupów (`Subject2`) dla zadanego miesiąca.
6. Pobiera pliki XML (`GET /invoices/ksef/{ksefNumber}`) i parsuje schemat `FA (3)`.
7. Zapisuje nienaruszone pliki XML oraz ustrukturyzowane JSON-y w:
   `firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/sprzedaz/ksef/`
   `firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/koszty/ksef/`

### 3. Rejestr Historii Synchronizacji i Audyt
Każda próba synchronizacji (zarówno zakończona sukcesem, jak i błędem) jest automatycznie rejestrowana w trwałym pliku audytowym firmy:
`firmy/{NIP-Nazwa}/ksef_sync_history.json`

Struktura pojedynczego wpisu:
* `timestamp`: dokładna data i godzina próby (np. `2026-11-14 08:30:15`),
* `rok`, `miesiac`: badany okres rozliczeniowy,
* `status`: `SUKCES` lub `BLAD`,
* `srodowisko`: `PROD` lub `TEST`,
* `nowe_sprzedaz`, `nowe_kosztow`: liczba nowo pobranych dokumentów z KSeF,
* `lacznie_sprzedaz`, `lacznie_kosztow`: łączna liczba dokumentów w archiwum po synchronizacji,
* `komunikat`: podsumowanie lub szczegóły błędu (np. kod błędu HTTP / brak połączenia sieciowego).

W panelu WWW (`/faktury`) status ostatniej synchronizacji oraz przycisk pełnej historii są prezentowane w kafelku *Krajowy System e-Faktur (KSeF 2.0)*.

### 4. Komunikat dla Użytkownika
Po zakończeniu poinformuj użytkownika o:
* Liczbie pobranych faktur sprzedaży oraz łącznej kwocie netto i VAT,
* Liczbie pobranych faktur kosztowych oraz kontrahentach,
* Odnotowaniu wpisu w historii synchronizacji (`ksef_sync_history.json`),
* Zapytaj, czy chce od razu przeprowadzić rozliczenie miesiąca za pomocą skilla `rozlicz-miesiac`.

