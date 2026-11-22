# Zbiorczy Raport Weryfikacji Kontrahentów (AML / Sankcje / Biała Lista)
**Okres rozliczeniowy:** 2026-10
**Firma audytująca:** CloudTech Test Jan Kowalski (NIP: `7770001122`)
**Data audytu:** 20.11.2026, 19:31 (UTC: `2026-11-20T18:31:00.734225+00:00`)

---
## 1. Podsumowanie Procedury Należytej Staranności

W okresie **2026-10** zweryfikowano łącznie **9** unikalnych kontrahentów występujących na fakturach sprzedaży oraz kosztów.

| Kategoria ryzyka | Liczba podmiotów | Status i zalecenia operacyjne |
| :--- | :---: | :--- |
| 🟢 **Niskie (Czysty)** | **8** | Brak zagrożeń – pełna akceptacja do księgowania i płatności |
| 🟡 **Średnie (Uwaga)** | **0** | Wymaga weryfikacji konta bankowego (Biała Lista) lub statusu PEP |
| 🟠 **Wysokie (Wyjaśnij)** | **1** | Podmiot nieaktywny w KRS/CEIDG lub brak rejestracji VAT |
| 🔴 **KRYTYCZNE (STOP)** | **0** | **BEZWZGLĘDNY ZAKAZ WSPÓŁPRACY I PŁATNOŚCI (Wpis na liście sankcyjnej)** |

---
## 2. Rejestr Zweryfikowanych Kontrahentów w Miesiącu

| Lp. | Kontrahent | NIP | Rejestr | Status VAT | Rachunek bankowy | Sankcje MSWiA/UE | Ryzyko | Decyzja |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | **VIKINGCO POLAND SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ** | `8971793639` | AKTYWNY | Czynny | Brak | ✅ Czysty | 🟢 Niskie | **Zaksięguj** |
| 2 | **Google Ireland Limited** | `IE6388047V` | AKTYWNY | Czynny | Brak | ✅ Czysty | 🟢 Niskie | **Zaksięguj** |
| 3 | **"EURO NET" SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ** | `5270005984` | AKTYWNY | Czynny | ✅ Biała Lista | ✅ Czysty | 🟢 Niskie | **Zaksięguj** |
| 4 | **ALLEGRO SP. Z O.O.** | `5252674797` | AKTYWNY | Czynny | ✅ Biała Lista | ✅ Czysty | 🟢 Niskie | **Zaksięguj** |
| 5 | **'P4 SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ'** | `9512120077` | AKTYWNY | Czynny | ✅ Biała Lista | ✅ Czysty | 🟢 Niskie | **Zaksięguj** |
| 6 | **ORLEN SPÓŁKA AKCYJNA** | `7740001454` | AKTYWNY | Czynny | ✅ Biała Lista | ✅ Czysty | 🟢 Niskie | **Zaksięguj** |
| 7 | **Amazon Web Services EMEA SARL** | `LU26375245` | AKTYWNY | Czynny | Brak | ✅ Czysty | 🟢 Niskie | **Zaksięguj** |
| 8 | **FAST-NET CLOUD SP. Z O.O.** | `9990001122` | NIEZNALEZIONY | Niezarejestrowany | ⚠️ Poza listą | ✅ Czysty | 🟠 Wysokie | **Wyjaśnij** |
| 9 | **MICHAŁ SZYMUSIK** | `5341531304` | AKTYWNY | Czynny | ✅ Biała Lista | ✅ Czysty | 🟢 Niskie | **Zaksięguj** |

---
## 3. Instrukcja dla Kontroli Skarbowej i GIIF
Wszystkie powyższe weryfikacje zostały wygenerowane deterministycznie na podstawie publicznych rejestrów państwowych (Biała Lista MF, CEIDG, KRS, CRBR) oraz oficjalnych list sankcyjnych RP i UE.
Indywidualne karty każdego kontrahenta wraz ze śladem audytowym i sumami kontrolnymi SHA-256 znajdują się w podfolderze `karty/`.

**Ścieżka do archiwum:** `firmy/7770001122-CloudTech_Test_Jan_Kowalski/weryfikacje/2026/10/`
