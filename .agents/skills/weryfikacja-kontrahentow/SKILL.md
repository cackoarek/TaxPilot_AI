---
name: weryfikacja-kontrahentow
description: >-
  Użyj tego skilla, gdy użytkownik pyta o weryfikację kontrahenta pod kątem AML, sankcji (MSWiA, UE),
  sprawdzenie statusu VAT na Białej Liście MF, weryfikację numeru konta bankowego lub wygenerowanie
  Karty Weryfikacji Kontrahenta / miesięcznego raportu compliance w procedurze należytej staranności.
---

# Procedura Weryfikacji Kontrahentów – AML, Sankcje i Należyta Staranność

Ten skill instruuje agenta, jak przeprowadzić deterministyczną, zgodną z polskim i unijnym prawem procedurę weryfikacji kontrahentów (KYC/AML, listy sankcyjne, Biała Lista VAT) w ramach miesięcznego procesu księgowego lub na doraźne żądanie (ad-hoc).

---

## 1. Ramy Prawne i Cel Biznesowy

Procedura weryfikacji zabezpiecza przedsiębiorcę przed dwoma niezależnymi kategoriami ryzyka:
1. **Ustawa sankcyjna z dnia 13 kwietnia 2022 r. (art. 2) oraz sankcje Unii Europejskiej:**
   * Obowiązuje **bezwzględnie każdego przedsiębiorcę** (w tym 1-osobowe działalności gospodarcze, spółki B2B).
   * Zakazuje udostępniania jakichkolwiek środków finansowych lub zasobów gospodarczych podmiotom i osobom powiązanym z agresją na Ukrainę (lista MSWiA oraz EU Consolidated Sanctions).
   * **Kary:** do 20 000 000 PLN kary administracyjnej oraz odpowiedzialność karna (pozbawienie wolności do lat 3).
2. **Ustawa o VAT (Biała Lista Podatników VAT, art. 96b) oraz PIT (art. 22p):**
   * Płatność na rachunek bankowy spoza Białej Listy dla transakcji $\ge$ 15 000 zł brutto pozbawia prawa do zaliczenia wydatku w koszty uzyskania przychodów (KUP) i rodzi solidarną odpowiedzialność za zaległości VAT wystawcy faktury.
3. **Ustawa AML z dnia 1 marca 2018 r. (art. 34-37):**
   * Wymóg ustalenia beneficjenta rzeczywistego (UBO) w CRBR oraz oceny ryzyka przed nawiązaniem relacji gospodarczych.

---

## 2. Zasada Zero-Hallucination & Optymalizacja Cache

1. **Brak halucynacji LLM:**
   Agentowi zabrania się zgadywania, czy podmiot jest na liście sankcyjnej lub czy rachunek jest na Białej Liście. Wszelkie sprawdzenia wykonuje deterministyczny moduł Python: `src/skills/aml_tools.py`.
2. **Optymalizacja (Jednorazowe Sprawdzanie Podmiotu):**
   System wykorzystuje dwupoziomowy cache (`_session_cache` w pamięci oraz trwały cache dyskowy w `weryfikacje/`):
   * Niezależnie od liczby faktur od danego dostawcy w miesiącu (np. 10 faktur za paliwo czy hosting) kontrahent sprawdzany jest **dokładnie jeden raz**.
   * Podczas sekwencyjnego badania wielu miesięcy (np. cały rok) raz sprawdzony podmiot jest natychmiast serwowany z pamięci podręcznej, co eliminuje opóźnienia i chroni przed limitami zapytań publicznych API (np. API MF).
3. **Automatyczne Pobieranie Rachunku Bankowego i Danych z Faktury:**
   * **Separacja Sprzedaż vs Zakup:** Numer rachunku bankowego kontrahenta (do weryfikacji na Białej Liście) jest odczytywany **z faktur kosztowych/zakupowych** (węzeł KSeF `Fa/Platnosc/RachunekBankowy/NrRB` oraz faktury Non-KSeF), na których wystawca podaje swoje konto do zapłaty. Na fakturach sprzedaży rachunek bankowy należy do firmy użytkownika, więc nie jest błędnie przypisywany kontrahentowi-nabywcy.
   * **Weryfikacja z Białą Listą:** Odczytany rachunek kontrahenta jest natychmiast porównywany z oficjalnym wykazem zgłoszonych rachunków bankowych na Białej Liście Podatników VAT MF.
   * **Automatyczne uzupełnianie REGON i adresu:** REGON i dane adresowe kontrahenta są automatycznie integrowane z Białej Listy MF oraz sekcji rejestrowej faktury KSeF (`Stopka/Rejestry/REGON`, `DaneIdentyfikacyjne/REGON`).

---

## 3. Struktura Katalogów i Archiwizacja Dowodów (Retencja 5 lat)

Wyniki procedury zapisywane są symetrycznie w katalogu głównym firmy obok folderów `faktury` oraz `rozliczenia`. Każda weryfikacja generuje komplet plików: Markdown (`.md`), maszynowy JSON (`.json`) oraz oficjalny, gotowy do druku i kontroli dokument PDF (`.pdf`):

```text
firmy/{NIP-Nazwa}/
├── faktury/{ROK}/{MIESIAC}/
├── rozliczenia/{ROK}/{MIESIAC}/
└── weryfikacje/
    └── {ROK}/{MIESIAC}/
        ├── raport-weryfikacji.md       # Zbiorczy miesięczny raport compliance dla urzędu
        ├── raport-weryfikacji.pdf      # Zbiorczy raport w formacie PDF (A4 pejzaż)
        ├── raport-weryfikacji.json     # Stan maszynowy z hashami kryptograficznymi
        └── karty/                      # Indywidualne Karty Weryfikacji (dowód należytej staranności)
            ├── {NIP1}-karta.md         # Karta weryfikacji w Markdown
            ├── {NIP1}-karta.pdf        # Oficjalna 1-stronicowa Karta Weryfikacji w formacie PDF (A4)
            ├── {NIP1}-raw.json         # Surowe dane z rejestrów publicznych
            ├── {NIP2}-karta.md
            ├── {NIP2}-karta.pdf
            ├── {NIP2}-raw.json
            └── ...
```

Każda karta PDF oraz Markdown zawiera unikalny hash `SHA-256` oraz znacznik czasu UTC, spełniając wymóg formalnego dowodu należytej staranności dla organów KAS, GIIF oraz audytu bankowego. Format `.pdf` gwarantuje integralność wizualną i stanowi niezmienny dowód do teczki kontrahenta (retencja min. 5 lat).

---

## 4. Tryby Działania Skilla

### A. Tryb Automatyczny (Część Procesu Księgowania Miesiąca)
Podczas procedury `rozlicz-miesiac` (lub polecenia `python -m src.cli rozlicz`):
1. Silnik automatycznie audytuje wszystkich kontrahentów z faktur danego okresu.
2. W tabelach wstępnego przeglądu (`przeglad`) wyświetla kolumnę `Status AML / Sankcje`.
3. Przy zamykaniu miesiąca automatycznie tworzy kompletny pakiet w `firmy/{NIP}/weryfikacje/{ROK}/{MIESIAC}/`.

Ręczne wywołanie weryfikacji dla całego miesiąca:
```bash
python -m src.cli weryfikuj-miesiac --nip {NIP_FIRMY} --rok {ROK} --miesiac {MIESIAC}
```

### B. Tryb Doraźny / Ad-hoc (Sprawdzenie Nowego Kontrahenta Przed Podpisaniem Umowy)
Gdy przedsiębiorca pyta: *"Sprawdź kontrahenta NIP 5250001090"*, *"Zweryfikuj firmę X przed przelewem na konto PL..."*:
```bash
python -m src.cli weryfikuj --kontrahent-nip {NIP} [--nazwa "{NAZWA}"] [--konto "{NR_KONTA}"] [--kwota {BRUTTO}]
```

Jeśli użytkownik chce od razu przypisać weryfikację do profilu firmy:
```bash
python -m src.cli weryfikuj --kontrahent-nip {NIP} --firma {NIP_FIRMY} --rok {ROK} --miesiac {MIESIAC}
```

---

## 5. Interpretacja Wyników i Poziomów Ryzyka

Agent analizuje wygenerowaną kartę i komunikuje przedsiębiorcy:

| Poziom ryzyka | Decyzja compliance | Znaczenie i zalecenia operacyjne |
| :--- | :--- | :--- |
| 🟢 **NISKIE** | `AKCEPTACJA` | Kontrahent w 100% bezpieczny. Aktywny w KRS/CEIDG, czynny VAT, rachunek na Białej Liście, brak sankcji. |
| 🟡 **ŚREDNIE** | `WYMAGA WYJAŚNIENIA` | Podmiot aktywny, ale rachunek bankowy nie figuruje na Białej Liście MF (ryzyko podatkowe dla kwot pow. 15 tys. zł) LUB podmiot ma status PEP. |
| 🟠 **WYSOKIE** | `WYMAGA WYJAŚNIENIA` | Podmiot wykreślony / zawieszony w rejestrze lub brak rejestracji VAT. |
| 🔴 **KRYTYCZNE (STOP)** | `ODMOWA WSPÓŁPRACY` | **BEZWZGLĘDNY ZAKAZ TRANSAKCJI.** Wykryto wpis na liście sankcyjnej MSWiA lub UE. Zablokuj płatność i zrezygnuj ze współpracy. |

