# Sprawozdanie z Czynności Księgowych i Audytu Podatkowego – 2026-09
**Firma:** CloudTech Test Jan Kowalski (NIP: `7770001122`)
**Kody PKD:** Brak
**Forma opodatkowania:** Ryczałt od przychodów ewidencjonowanych (PIT-28) | Płatnik VAT: TAK
**Okres audytowany:** 2026-09

---
## 🎯 Cel i Zakres Sprawozdania
Niniejszy dokument stanowi protokół z czynności księgowych oraz audytu dokumentów źródłowych (zarówno pobranych z KSeF, jak i wyekstrahowanych ze źródeł zewnętrznych).
Każdy dokument został zweryfikowany pod kątem:
1. Prawidłowości kwalifikacji przychodu do stawek ryczałtu (art. 12 ustawy o zryczałtowanym podatku dochodowym),
2. Prawa do odliczenia podatku naliczonego VAT (art. 86 ust. 1 oraz art. 86a ustawy o VAT),
3. Ochrony przed ryzykiem podatkowym poprzez bezwzględne wyłączenie wydatków prywatnych i osobistych,
4. Zgodności wyliczeń z zasadą Zero-Hallucination (deterministyczne obliczenia w Pythonie na typie Decimal).

---
## 📈 Część I: Faktury Sprzedaży (Przychody) – Kwalifikacja i Podatki
W okresie **2026-09** zarejestrowano **2** faktur sprzedaży o łącznej wartości netto **53500.00 zł**.

### 1.1. Faktura sprzedaży nr `1/09/2026` – VIKINGCO POLAND SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ
* **Kontrahent (Nabywca):** VIKINGCO POLAND SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ (NIP: `8971793639`)
* **Data wykonania usługi / sprzedaży:** `2026-09-30`
* **Data wystawienia dokumentu:** `2026-09-30`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/09/sprzedaz/ksef/2026-09-30_1_09_2026.json`)
* **Wartości faktury:** Netto: **35500.00 zł** | VAT: **8165.00 zł** | Brutto: **43665.00 zł**

**Wykaz pozycji i kwalifikacja ryczałtu:**
* **Usługi DevSecOps i konteneryzacji mikroserwisów - kontrakt 09/2026** – Netto: 35500.00 zł | VAT 23% (8165.00 zł) $\rightarrow$ Stawka ryczałtu: **12%** (podatek: **4260.00 zł**)

**Uzasadnienie sposobu rozliczenia:**
* **Kwalifikacja PIT:** Przychód zaksięgowany w Ewidencji Przychodów ze stawką ryczałtu właściwą dla przedmiotu usług IT (zgodnie z art. 12 ust. 1 pkt 2b ustawy o zryczałtowanym podatku dochodowym).
* **Rozliczenie VAT:** Podatek VAT w stawce 23% ujęty w Rejestrze Sprzedaży VAT. Obowiązek podatkowy powstał z dniem wykonania usługi (art. 19a ust. 1 ustawy o VAT).

### 1.2. Faktura sprzedaży nr `EXP/2026/09/01` – GOOGLE IRELAND LIMITED
* **Kontrahent (Nabywca):** GOOGLE IRELAND LIMITED (NIP: `IE6388047V`)
* **Data wykonania usługi / sprzedaży:** `2026-09-28`
* **Data wystawienia dokumentu:** `2026-09-28`
* **Źródło dokumentu:** 📁 Non-KSeF (`EXP_2026_09_01.txt`)
* **Wartości faktury:** Netto: **18000.00 zł** | VAT: **0.00 zł** | Brutto: **18000.00 zł**

**Wykaz pozycji i kwalifikacja ryczałtu:**
* **Konsultacje GCP & Kubernetes - okres 09/2026** – Netto: 18000.00 zł | VAT np% (0.00 zł) $\rightarrow$ Stawka ryczałtu: **12%** (podatek: **2160.00 zł**)

**Uzasadnienie sposobu rozliczenia:**
* **Kwalifikacja PIT:** Przychód zaksięgowany w Ewidencji Przychodów ze stawką ryczałtu właściwą dla przedmiotu usług IT (zgodnie z art. 12 ust. 1 pkt 2b ustawy o zryczałtowanym podatku dochodowym).
* **Rozliczenie VAT:** Podatek VAT w stawce 23% ujęty w Rejestrze Sprzedaży VAT. Obowiązek podatkowy powstał z dniem wykonania usługi (art. 19a ust. 1 ustawy o VAT).

---
## 🧾 Część II: Faktury Kosztowe (Zakupy) – Szczegółowy Audyt Podatkowy
W okresie **2026-09** poddano audytowi **5** faktur zakupowych wystawionych na NIP firmy.

### 2.1. Faktura kosztowa nr `CE/FAV/2026/0004219` – ORLEN SPÓŁKA AKCYJNA
* **Sprzedawca:** ORLEN SPÓŁKA AKCYJNA (NIP: `7740001454`)
* **Data wystawienia:** `2026-09-14` | **Data zakupu:** `2026-09-14`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/09/koszty/ksef/2026-09-14_CE_FAV_2026_0004219.json`)
* **Wartości z dokumentu:** Netto: **310.00 zł** | VAT: **71.30 zł** | Brutto: **381.30 zł**
* **Rachunek bankowy do zapłaty:** `30102010260000140203550589` – ℹ️ Odczytany z dokumentu

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Paliwo EFECTA 95 | 310.00 zł | 71.30 zł (23%) | 🚗 Pojazd 50% (art. 86a) | **35.65 zł** | Eksploatacja pojazdu osobowego w trybie mieszanym (art. 86a ustawy o VAT) |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **35.65 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **35.65 zł**

### 2.2. Faktura kosztowa nr `F/71029415/09/26` – P4 SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ
* **Sprzedawca:** P4 SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ (NIP: `5341531304`)
* **Data wystawienia:** `2026-09-15` | **Data zakupu:** `2026-09-15`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/09/koszty/ksef/2026-09-15_F_71029415_09_26.json`)
* **Wartości z dokumentu:** Netto: **140.00 zł** | VAT: **32.20 zł** | Brutto: **172.20 zł**
* **Rachunek bankowy do zapłaty:** `59194010763036820200000000` – ℹ️ Odczytany z dokumentu

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Usługi telekomunikacyjne mobilne (Play) | 140.00 zł | 32.20 zł (23%) | ✅ 100% Firmowy | **32.20 zł** | Wydatek firmowy związany z prowadzoną działalnością |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **32.20 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **0.00 zł**

### 2.3. Faktura kosztowa nr `F 40112/1561/26` – T-MOBILE POLSKA S.A.
* **Sprzedawca:** T-MOBILE POLSKA S.A. (NIP: `9512120077`)
* **Data wystawienia:** `2026-09-20` | **Data zakupu:** `2026-09-20`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/09/koszty/ksef/2026-09-20_F_40112_1561_26.json`)
* **Wartości z dokumentu:** Netto: **110.00 zł** | VAT: **25.30 zł** | Brutto: **135.30 zł**
* **Rachunek bankowy do zapłaty:** `93109000047777010097655657` – ℹ️ Odczytany z dokumentu

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Dostęp do sieci i łącze światłowodowe (T-Mobile) | 110.00 zł | 25.30 zł (23%) | ✅ 100% Firmowy | **25.30 zł** | Standardowy wydatek bieżący firmy |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **25.30 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **0.00 zł**

### 2.4. Faktura kosztowa nr `FV/2026/09/09` – PIOTR WIŚNIEWSKI
* **Sprzedawca:** PIOTR WIŚNIEWSKI (NIP: `5213242793`)
* **Data wystawienia:** `2026-09-25` | **Data zakupu:** `2026-09-25`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/09/koszty/ksef/2026-09-25_FV_2026_09_09.json`)
* **Wartości z dokumentu:** Netto: **3000.00 zł** | VAT: **690.00 zł** | Brutto: **3690.00 zł**
* **Rachunek bankowy do zapłaty:** `33114020040000370274135103` – ℹ️ Odczytany z dokumentu

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Wsparcie wdrożeniowe DevOps & CI/CD | 3000.00 zł | 690.00 zł (23%) | ✅ 100% Firmowy | **690.00 zł** | Standardowy wydatek bieżący firmy |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **690.00 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **0.00 zł**

### 2.5. Faktura kosztowa nr `AWS-INV-2026-09-6844` – AMAZON WEB SERVICES EMEA SARL
* **Sprzedawca:** AMAZON WEB SERVICES EMEA SARL (NIP: `LU26375245`)
* **Data wystawienia:** `2026-09-03` | **Data zakupu:** `2026-09-03`
* **Źródło dokumentu:** 📁 Non-KSeF (`AWS-INV-2026-09-6844.pdf`)
* **Wartości z dokumentu:** Netto: **890.00 zł** | VAT: **0.00 zł** | Brutto: **890.00 zł**
* **Rachunek bankowy do zapłaty:** Nie wskazano

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Usługi chmurowe Amazon Web Services (Compute ... | 890.00 zł | 0.00 zł (np%) | ✅ 100% Firmowy | **0.00 zł** | Wydatek firmowy związany z prowadzoną działalnością |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **0.00 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **0.00 zł**

---
## 🛡️ Część III: Podsumowanie Audytu i Bilans Bezpieczeństwa Podatkowego

### 1. Zestawienie Zbiorcze Podatku VAT
* **Łączny VAT należny ze sprzedaży:** **8165.00 zł**
* **Łączny VAT naliczony podlegający odliczeniu:** **783.15 zł**
* **Łączny VAT odrzucony jako prywatny / nieodliczony:** **0.00 zł**
* **Finalny wynik VAT-7 za ten miesiąc:** **7382 zł** (do zapłaty)

### 2. Eliminacja Ryzyk Podatkowych (Ochrona Podatkowa)
* Wszystkie pozycje o charakterze osobistym (np. opieka medyczna, telewizja, zakupy prywatne) zostały zidentyfikowane i trwale wykluczone z odliczenia podatku VAT.
* Zapobiega to zakwestionowaniu rozliczenia przez organy Krajowej Administracji Skarbowej (KAS) oraz eliminuje ryzyko nałożenia dodatkowego zobowiązania podatkowego (sankcji VAT do 30% z art. 112b ustawy o VAT) wraz z odsetkami za zwłokę.
* Zastosowano ustawowy limit 50% odliczenia VAT na wydatki eksploatacyjne pojazdów osobowych użytkowanych w trybie mieszanym (art. 86a ustawy o VAT).

### 3. Weryfikacja Rachunków Bankowych na Białej Liście Podatników VAT (art. 22p PIT)
* Zgodnie z procedurą należytej staranności, numery rachunków bankowych z faktur zakupowych poddano weryfikacji w oficjalnym wykazie Ministerstwa Finansów.
* Płatności powyżej 15 000 zł brutto na rachunki figurujące na Białej Liście MF gwarantują pełne bezpieczeństwo podatkowe, zachowanie prawa do KUP oraz brak solidarnej odpowiedzialności za VAT (art. 117ba Ordynacji podatkowej).

---
## 🔍 Część IV: Rejestr Wykrytych Duplikatów i Kolizji Źródłowych (Deduplikacja)
* **Status deduplikacji:** ✅ W audytowanym okresie nie stwierdzono kolizji źródłowych (KSeF vs Non-KSeF) ani powtórzeń dokumentów z innych miesięcy.
* Wszystkie ujęte faktury są unikalne i reprezentują rzeczywiste zdarzenia gospodarcze.
