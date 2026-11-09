---
name: non-ksef-extract
description: >-
  Użyj tego skilla, gdy użytkownik dodaje faktury kosztowe lub sprzedaży spoza KSeF (PDF, skany, pliki JSON lub tekstowe,
  np. Google Cloud, AWS, GitHub, zagraniczna sprzedaż B2B, paragony z NIP) lub prosi o przetworzenie i ekstrakcję
  dokumentów z folderów non-ksef-raw do non-ksef-extracted przed rozliczeniem.
---

# Procedura Ekstrakcji Dokumentów Non-KSeF (Sprzedaż i Koszty)

Ten skill opisuje procedurę przyjmowania, ekstrakcji i włączania do księgowania faktur i rachunków, które nie przechodzą przez Krajowy System e-Faktur (KSeF), takich jak:
* **Koszty:** Zagraniczne faktury za usługi chmurowe i oprogramowanie (Google Cloud, AWS, GitHub, JetBrains, Microsoft, Adobe), bilety kolejowe, rachunki i paragony z NIP,
* **Sprzedaż:** Faktury wystawione dla kontrahentów zagranicznych (np. USA, UE poza KSeF), samofakturowanie na platformach międzynarodowych,
* Dokumenty papierowe lub skany w formatach PDF / TXT / JSON.

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
    ├── non-ksef-raw/                    # Oryginalne pliki kosztowe wrzucone przez użytkownika (PDF, JSON, TXT, skany)
    └── non-ksef-extracted/              # Znormalizowane pliki JSON kosztów podlegające księgowaniu ({stem}.json)
```

---

## 2. Instrukcja Postępowania Krok po Kroku

### Krok 1: Wrzucenie dokumentów do `non-ksef-raw/`
Użytkownik umieszcza pliki źródłowe w odpowiednim folderze:
* Dla kosztów: `firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/koszty/non-ksef-raw/`
* Dla sprzedaży: `firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/sprzedaz/non-ksef-raw/`

### Krok 2: Uruchomienie Ekstrakcji
Agent uruchamia deterministyczny moduł ekstrakcji:

```bash
python -m src.cli extract-non-ksef --nip {NIP} --rok {ROK} --miesiac {MIESIAC}
```
*(opcjonalnie z parametrem `--typ {sprzedaz,koszty,all}` oraz `--force` w celu wymuszenia ponownej ekstrakcji).*

Moduł automatycznie:
1. Rozpoznaje format pliku:
   * **Pliki JSON:** mapuje strukturę zewnętrzną na znormalizowany model `Invoice` (`typ=InvoiceType.KOSZT` lub `InvoiceType.SPRZEDAZ`, `zrodlo="NON_KSEF"`).
   * **Pliki PDF:** wyciąga tekst za pomocą `pdftotext` i parsuje kluczowe encje (NIP, numer, daty, kwoty netto/VAT/brutto, pozycje).
   * **Pliki TXT / MD:** analizuje treść za pomocą reguł i wyrażeń regularnych.
2. Zapisuje znormalizowany plik do:
   * `faktury/{ROK}/{MIESIAC}/koszty/non-ksef-extracted/{stem}.json`
   * `faktury/{ROK}/{MIESIAC}/sprzedaz/non-ksef-extracted/{stem}.json`

### Krok 3: Weryfikacja Wyekstrahowanych Danych (Human-in-the-Loop)
Jeśli dokument zawierał nietypowy układ graficzny lub brakowało niektórych danych:
* Agent weryfikuje poprawność kwot netto, VAT i brutto oraz dane nabywcy/sprzedawcy.
* W razie wątpliwości dopytuje użytkownika o poprawność odczytanych wartości.

### Krok 4: Automatyczne Uwzględnienie w Księgowaniu
Narzędzia księgowe (`InvoiceStorage.list_invoices`, `PreSettlementReview`, `BookkeepingService`) **automatycznie** łączą faktury z KSeF oraz faktury z `non-ksef-extracted/`:
* W zestawieniu wstępnym `przeglad` faktury spoza KSeF są oznaczone symbolem `📁 Non-KSeF` (zarówno w tabeli sprzedaży, jak i zakupów).
* Faktury kosztowe zostają poddane audytowi kwalifikacji podatkowej (odliczenie 100% / 50% dla samochodów / wykluczenie prywatne).
* Faktury przychodowe wchodzą do ewidencji przychodów i bilansu VAT-7.

