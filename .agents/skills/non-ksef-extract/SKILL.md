---
name: non-ksef-extract
description: >-
  Użyj tego skilla, gdy użytkownik dodaje faktury kosztowe lub sprzedaży spoza KSeF (PDF, skany, pliki JSON lub tekstowe,
  np. Google Cloud, AWS, GitHub, zagraniczna sprzedaż B2B, paragony z NIP) lub prosi o przetworzenie i ekstrakcję
  dokumentów z folderów non-ksef-raw do non-ksef-extracted przed rozliczeniem.
---

# Procedura Ekstrakcji Dokumentów Non-KSeF (Sprzedaż i Koszty)

Ten skill opisuje procedurę przyjmowania, ekstrakcji i włączania do księgowania faktur i rachunków, które nie przechodzą przez Krajowy System e-Faktur (KSeF), takich jak:
* **Koszty:** Zagraniczne faktury za usługi chmurowe i oprogramowanie (Google Cloud, AWS, GitHub, JetBrains, Microsoft, Adobe), bilety kolejowe, rachunki i paragony fiskalne z NIP,
* **Sprzedaż:** Faktury wystawione dla kontrahentów zagranicznych (np. USA, UE poza KSeF), samofakturowanie na platformach międzynarodowych,
* Dokumenty papierowe, skany lub zdjęcia w formatach JPG / PNG / PDF / TXT / JSON.

---

## 1. Symetryczna Struktura Katalogów Non-KSeF

Każdy miesiąc w archiwum firmy posiada ustrukturyzowany, symetryczny podział dokumentów sprzedaży i kosztów:

```text
firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/
├── sprzedaz/
│   ├── ksef/                            # Faktury sprzedaży pobrane z KSeF ({data}_{numer}.xml / .json)
│   ├── non-ksef-raw/                    # Oryginalne pliki sprzedaży wrzucone przez użytkownika (PDF, JSON, TXT)
│   └── non-ksef-extracted/              # Znormalizowane pliki JSON sprzedaży podlegające księgowaniu ({stem}.json)
└── koszty/
    ├── ksef/                            # Faktury kosztowe pobrane z KSeF ({data}_{numer}.xml / .json)
    ├── non-ksef-raw/                    # Oryginalne pliki kosztowe wrzucone przez użytkownika (PDF, JSON, TXT, skany, JPG/PNG)
    └── non-ksef-extracted/              # Znormalizowane pliki JSON kosztów podlegające księgowaniu ({stem}.json)
```

---

## 2. Dynamiczna Ekstrakcja przez Agenta AI (Zero-Hardcoded Fixtures)

> [!IMPORTANT]
> **Zasada dynamicznej ekstrakcji:** System **NIGDY** nie korzysta ze sztywno zakodowanych map ani słowników (np. `KNOWN_RECEIPTS_MAP`). Każdy dokument trafiający do systemu jest traktowany indywidualnie jako nowy.
> Za odczytanie treści, kwot, stawek VAT oraz danych kontrahentów odpowiada Agent AI (moduł `AIDocumentExtractor` z obsługą Vision i OCR).

### Ścieżki wywołania ekstrakcji:

1. **Interfejs WWW (Przycisk AI w tle i pasek postępu):**
   * Gdy w widoku pojawią się dokumenty wymagające analizy, na ekranach *Faktury*, *Klasyfikacja i Wstępny Przegląd* oraz *Księgowanie* pojawia się ostrzeżenie:
     `⚠️ Nie wszystkie faktury dostarczone przez użytkownika zostały prawidłowo przetworzone!`
   * Kliknięcie przycisku **`🤖 Wyciągnij dane z faktury (AI)`** uruchamia asynchroniczne zadanie w tle (`ExtractionService`).
   * **Niezależny limit czasu per dokument:** Każdy dokument analizowany jest sekwencyjnie z własnym, niezależnym limitem czasu (90s). Ewentualne przekroczenie limitu lub błąd na jednym pliku nie przerywa przetwarzania pozostałych faktur.
   * **Pasek postępu na żywo:** Interfejs na bieżąco prezentuje licznik przetworzonych dokumentów (np. `2 / 5 (40%)`), nazwę aktualnie odczytywanego pliku oraz płynnie animowany pasek postępu.
   * Proces jest niezależny od nawigacji (stan zapisywany w pliku `.extraction_status.json`).
   * Po zakończeniu pojawia się komunikat o sukcesie, a widok tabeli automatycznie się odświeża.

2. **Konsola CLI:**
   * Ekstrakcja nieodczytanych dokumentów przez AI:
     ```bash
     python -m src.cli extract-ai --nip {NIP} --rok {ROK} --miesiac {MIESIAC}
     ```
   * Standardowa ekstrakcja z opcjonalną flagą AI:
     ```bash
     python -m src.cli extract-non-ksef --nip {NIP} --rok {ROK} --miesiac {MIESIAC} --ai
     ```

---

## 3. Instrukcja Postępowania Krok po Kroku

### Krok 1: Wrzucenie dokumentów do `non-ksef-raw/`
Użytkownik umieszcza pliki źródłowe w odpowiednim folderze:
* Dla kosztów: `firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/koszty/non-ksef-raw/`
* Dla sprzedaży: `firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/sprzedaz/non-ksef-raw/`

### Krok 2: Uruchomienie Ekstrakcji AI i Auto-Routing
Moduł `AIDocumentExtractor`:
1. **Analizuje treść i format:**
   * **Zdjęcia i skany (JPG, PNG, WebP):** przesyła obraz do modelu multimodalnego AI (Vision), który odczytuje fizyczny paragon / fakturę.
   * **Pliki PDF:** wyciąga warstwę tekstową (`pdftotext`) lub analizuje strony graficzne.
   * **Pliki tekstowe i JSON:** bezpośrednio parsuje strukturę i mapuje pozycje.
2. **Weryfikuje matematykę (Zero-Hallucination):**
   * Wszystkie kwoty netto, VAT i brutto przeliczane są na typie `Decimal`.
   * Sprawdzana jest tożsamość: $\text{suma netto} + \text{suma VAT} = \text{suma brutto}$.
3. **Auto-Routing i Relokacja Dokumentów (Z Plikiem Informacyjnym):**
   Jeśli użytkownik omyłkowo wrzucił fakturę sprzedaży do `koszty/non-ksef-raw/` (lub odwrotnie):
   * System porównuje NIP sprzedawcy i nabywcy z profilem firmy.
   * **Fizyczna relokacja:** Plik surowy zostaje przeniesiony do właściwego katalogu (`sprzedaz/non-ksef-raw/` lub `koszty/non-ksef-raw/`).
   * **Plik informacyjny `.PRZENIESIONO.txt`:** W pierwotnym miejscu powstaje plik audytowy z informacją o dacie relokacji, kwotach i ścieżce docelowej.
   * **Zapis encji:** Znormalizowany plik JSON trafia do właściwego folderu `non-ksef-extracted/{stem}.json`.

### Krok 3: Weryfikacja Wyekstrahowanych Danych (Pre-Settlement Review)
* W zestawieniu wstępnym `przeglad` faktury spoza KSeF są oznaczone symbolem `📁 Non-KSeF`.
* Przedsiębiorca potwierdza kompletność przychodów i akceptuje koszty.

### Krok 4: Automatyczne Uwzględnienie w Księgowaniu
Narzędzia księgowe (`InvoiceStorage.list_invoices`, `PreSettlementReview`, `BookkeepingService`) łączą faktury KSeF i Non-KSeF w jednolitą ewidencję i rejestr VAT.
