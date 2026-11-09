# TaxPilot AI 🚀

Autonomiczny asystent podatkowo-księgowy dla jednoosobowej działalności gospodarczej (JDG) w Polsce.

## Architektura 4 Poziomów

1. **Poziom 1 (Zbieranie dokumentów / Ingestion):**
   - Integracja z Krajowym Systemem e-Faktur (KSeF API & parser XML `FA (2)`).
   - Zapis faktur do ustrukturyzowanych katalogów per firma/rok/miesiąc.
   - Planowane: Importer z Dysku Google, skrzynki e-mail oraz OCR skanów (VLM).

2. **Poziom 2 (Księgowanie / Bookkeeping):**
   - Ewidencja przychodów (Ryczałt) oraz KPiR (Liniowy/Skala).
   - Klasyfikacja kosztów podatkowych (KUP) i odliczeń VAT.

3. **Poziom 3 (Rozliczenia podatkowe / Tax Settlement):**
   - Deterministyczny kalkulator zaliczek na podatek dochodowy (PIT-28 / PIT-5).
   - Obliczanie składek ZUS (społeczne + zdrowotna wg formy opodatkowania).
   - Rozliczenie podatku VAT (rejestr VAT sprzedaży i zakupów, JPK_V7).

4. **Poziom 4 (Optymalizacja podatków / Optimization):**
   - Symulacje porównawcze form opodatkowania (Ryczałt vs Liniowy vs Skala).
   - Wykrywanie brakujących kosztów i rekomendacje ulg podatkowych (np. IP-BOX, B+R).

## Struktura katalogów

```text
TaxPilot_AI/
├── firmy/
│   └── 7770001122-CloudTech_Solutions_Jan_Kowalski/
│       ├── profil.json
│       └── faktury/
│           └── 2026/
│               └── 01/
│                   ├── sprzedaz/
│                   └── koszty/
├── src/
│   ├── config.py
│   ├── core/
│   │   ├── company.py
│   │   └── invoice.py
│   ├── level_1_ingestion/
│   │   ├── ksef_client.py
│   │   ├── ksef_parser.py
│   │   └── invoice_storage.py
│   ├── level_2_bookkeeping/
│   ├── level_3_tax_settlement/
│   └── level_4_optimization/
├── tests/
└── AGENTS.md
```

## Konfiguracja KSeF

Token autoryzacyjny oraz środowisko (PROD / TEST) są konfigurowane bezpośrednio w profilu firmy:
`firmy/{NIP-Nazwa}/profil.json`:

```json
{
  "ksef": {
    "srodowisko": "PROD",
    "token": "0261108-EC-..."
  }
}
```

Możesz go również zapisać lub zaktualizować za pomocą wbudowanego CLI:
```bash
python -m src.cli set-token --nip 7770001122 --token "TWOJ_TOKEN_KSEF" --srodowisko PROD
```
