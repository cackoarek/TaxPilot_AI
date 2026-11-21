# Sprawozdanie z Czynności Księgowych i Audytu Podatkowego – 2026-10
**Firma:** CloudTech Test Jan Kowalski (NIP: `7770001122`)
**Kody PKD:** Brak
**Forma opodatkowania:** Ryczałt od przychodów ewidencjonowanych (PIT-28) | Płatnik VAT: TAK
**Okres audytowany:** 2026-10

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
W okresie **2026-10** zarejestrowano **2** faktur sprzedaży o łącznej wartości netto **54500.00 zł**.

### 1.1. Faktura sprzedaży nr `1/10/2026` – VIKINGCO POLAND SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ
* **Kontrahent (Nabywca):** VIKINGCO POLAND SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ (NIP: `8971793639`)
* **Data wykonania usługi / sprzedaży:** `2026-10-30`
* **Data wystawienia dokumentu:** `2026-10-30`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/10/sprzedaz/ksef/2026-10-30_1_10_2026.json`)
* **Wartości faktury:** Netto: **36500.00 zł** | VAT: **8395.00 zł** | Brutto: **44895.00 zł**

**Wykaz pozycji i kwalifikacja ryczałtu:**
* **Usługi architektury chmurowej i DevOps (Kubernetes/AWS) - kontrakt 10/2026** – Netto: 32000.00 zł | VAT 23% (7360.00 zł) $\rightarrow$ Stawka ryczałtu: **12%** (podatek: **3840.00 zł**)
* **Konsultacje wdrożeniowe CI/CD i automatyzacja testów** – Netto: 4500.00 zł | VAT 23% (1035.00 zł) $\rightarrow$ Stawka ryczałtu: **12%** (podatek: **540.00 zł**)

**Uzasadnienie sposobu rozliczenia:**
* **Kwalifikacja PIT:** Przychód zaksięgowany w Ewidencji Przychodów ze stawką ryczałtu właściwą dla przedmiotu usług IT (zgodnie z art. 12 ust. 1 pkt 2b ustawy o zryczałtowanym podatku dochodowym).
* **Rozliczenie VAT:** Podatek VAT w stawce 23% ujęty w Rejestrze Sprzedaży VAT. Obowiązek podatkowy powstał z dniem wykonania usługi (art. 19a ust. 1 ustawy o VAT).

### 1.2. Faktura sprzedaży nr `EXP/2026/10/01` – Google Ireland Limited
* **Kontrahent (Nabywca):** Google Ireland Limited (NIP: `IE6388047V`)
* **Data wykonania usługi / sprzedaży:** `2026-10-28`
* **Data wystawienia dokumentu:** `2026-10-28`
* **Źródło dokumentu:** 📁 Non-KSeF (`EXP_2026_10_01.txt`)
* **Wartości faktury:** Netto: **18000.00 zł** | VAT: **0.00 zł** | Brutto: **18000.00 zł**

**Wykaz pozycji i kwalifikacja ryczałtu:**
* **Senior Cloud Architecture Consulting & GCP Platform Optimization** – Netto: 18000.00 zł | VAT np% (0.00 zł) $\rightarrow$ Stawka ryczałtu: **12%** (podatek: **2160.00 zł**)

**Uzasadnienie sposobu rozliczenia:**
* **Kwalifikacja PIT:** Przychód zaksięgowany w Ewidencji Przychodów ze stawką ryczałtu właściwą dla przedmiotu usług IT (zgodnie z art. 12 ust. 1 pkt 2b ustawy o zryczałtowanym podatku dochodowym).
* **Rozliczenie VAT:** Podatek VAT w stawce 23% ujęty w Rejestrze Sprzedaży VAT. Obowiązek podatkowy powstał z dniem wykonania usługi (art. 19a ust. 1 ustawy o VAT).

---
## 🧾 Część II: Faktury Kosztowe (Zakupy) – Szczegółowy Audyt Podatkowy
W okresie **2026-10** poddano audytowi **7** faktur zakupowych wystawionych na NIP firmy.

### 2.1. Faktura kosztowa nr `CE/FAV/2026/0005129` – EURO-NET SP. Z O.O.
* **Sprzedawca:** EURO-NET SP. Z O.O. (NIP: `5270005984`)
* **Data wystawienia:** `2026-10-10` | **Data zakupu:** `2026-10-10`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/10/koszty/ksef/2026-10-10_CE_FAV_2026_0005129.json`)
* **Wartości z dokumentu:** Netto: **1299.18 zł** | VAT: **298.82 zł** | Brutto: **1598.00 zł**
* **Rachunek bankowy do zapłaty:** `42191010482209772674840001` – ✅ **Zgodny z Białą Listą MF** (bezpieczny do płatności pow. 15 tys. zł)

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Dysk SSD Samsung 990 Pro 2TB NVMe PCIe 4.0 do... | 730.89 zł | 168.11 zł (23%) | ✅ 100% Firmowy | **168.11 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |
| Klawiatura mechaniczna bezprzewodowa Logitech... | 568.29 zł | 130.71 zł (23%) | ✅ 100% Firmowy | **130.71 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **298.82 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **0.00 zł**

### 2.2. Faktura kosztowa nr `FV/ALG/2026/10/9128` – ALLEGRO SP. Z O.O.
* **Sprzedawca:** ALLEGRO SP. Z O.O. (NIP: `5252674797`)
* **Data wystawienia:** `2026-10-14` | **Data zakupu:** `2026-10-14`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/10/koszty/ksef/2026-10-14_FV_ALG_2026_10_9128.json`)
* **Wartości z dokumentu:** Netto: **470.00 zł** | VAT: **108.10 zł** | Brutto: **578.10 zł**
* **Rachunek bankowy do zapłaty:** `92109013620000000130009988` – ⚠️ **Brak na Białej Liście MF** (wymaga zawiadomienia ZAW-NR przy kwocie pow. 15 tys. zł)

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Kable sieciowe patchcord RJ45 Cat 6a 10m - 5 ... | 120.00 zł | 27.60 zł (23%) | ✅ 100% Firmowy | **27.60 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |
| Zestaw klocków LEGO Star Wars dla dzieci (wyd... | 350.00 zł | 80.50 zł (23%) | ⛔ Odrzucony (0% VAT) | **0.00 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **27.60 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **80.50 zł**

### 2.3. Faktura kosztowa nr `F/71029415/10/26` – P4 SP. Z O.O.
* **Sprzedawca:** P4 SP. Z O.O. (NIP: `9512120077`)
* **Data wystawienia:** `2026-10-15` | **Data zakupu:** `2026-10-15`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/10/koszty/ksef/2026-10-15_F_71029415_10_26.json`)
* **Wartości z dokumentu:** Netto: **210.00 zł** | VAT: **48.30 zł** | Brutto: **258.30 zł**
* **Rachunek bankowy do zapłaty:** `93109000047777010097655657` – ✅ **Zgodny z Białą Listą MF** (bezpieczny do płatności pow. 15 tys. zł)

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Abonament Biznes Rozszerzony - Internet Świat... | 180.00 zł | 41.40 zł (23%) | ✅ 100% Firmowy | **41.40 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |
| Opłata za publiczny stały adres IPv4 dla serw... | 30.00 zł | 6.90 zł (23%) | ✅ 100% Firmowy | **6.90 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **48.30 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **0.00 zł**

### 2.4. Faktura kosztowa nr `F 41209/1561/26` – ORLEN S.A.
* **Sprzedawca:** ORLEN S.A. (NIP: `7740001454`)
* **Data wystawienia:** `2026-10-19` | **Data zakupu:** `2026-10-19`
* **Źródło dokumentu:** 🏛️ KSeF (`firmy/7770001122-CloudTech_Test_Jan_Kowalski/faktury/2026/10/koszty/ksef/2026-10-19_F_41209_1561_26.json`)
* **Wartości z dokumentu:** Netto: **298.54 zł** | VAT: **68.66 zł** | Brutto: **367.20 zł**
* **Rachunek bankowy do zapłaty:** `30102010260000140203550589` – ✅ **Zgodny z Białą Listą MF** (bezpieczny do płatności pow. 15 tys. zł)

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| EFECTA 95 CN27101245 paliwo benzyna | 298.54 zł | 68.66 zł (23%) | 🚗 Pojazd 50% (art. 86a) | **34.33 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **34.33 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **34.33 zł**

### 2.5. Faktura kosztowa nr `AWS-INV-2026-10-7419` – Amazon Web Services EMEA SARL
* **Sprzedawca:** Amazon Web Services EMEA SARL (NIP: `LU26375245`)
* **Data wystawienia:** `2026-10-24` | **Data zakupu:** `2026-10-24`
* **Źródło dokumentu:** 📁 Non-KSeF (`AWS-INV-2026-10-7419.pdf`)
* **Wartości z dokumentu:** Netto: **1450.00 zł** | VAT: **0.00 zł** | Brutto: **1450.00 zł**
* **Rachunek bankowy do zapłaty:** Nie wskazano

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Amazon Web Services Cloud Infrastructure Serv... | 1450.00 zł | 0.00 zł (np%) | ✅ 100% Firmowy | **0.00 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **0.00 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **0.00 zł**

### 2.6. Faktura kosztowa nr `FV/2026/10/FAST-891` – FAST-NET CLOUD SP. Z O.O.
* **Sprzedawca:** FAST-NET CLOUD SP. Z O.O. (NIP: `9990001122`)
* **Data wystawienia:** `2026-10-22` | **Data zakupu:** `2026-10-22`
* **Źródło dokumentu:** 📁 Non-KSeF (`INV-2026-10-FASTNET.pdf`)
* **Wartości z dokumentu:** Netto: **1850.00 zł** | VAT: **425.50 zł** | Brutto: **2275.50 zł**
* **Rachunek bankowy do zapłaty:** `99109010140000000199998888` – ⚠️ **Brak na Białej Liście MF** (wymaga zawiadomienia ZAW-NR przy kwocie pow. 15 tys. zł)

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Serwer dedykowany NVMe Pro 64GB RAM oraz back... | 1850.00 zł | 425.50 zł (23%) | ✅ 100% Firmowy | **425.50 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **425.50 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **0.00 zł**

### 2.7. Faktura kosztowa nr `PAR-2026-10-55912` – M&M Michał Szymusik (Circle K nr 75090)
* **Sprzedawca:** M&M Michał Szymusik (Circle K nr 75090) (NIP: `5341531304`)
* **Data wystawienia:** `2026-10-27` | **Data zakupu:** `2026-10-27`
* **Źródło dokumentu:** 📁 Non-KSeF (`PAR-2026-10-55912.jpg`)
* **Wartości z dokumentu:** Netto: **235.77 zł** | VAT: **54.23 zł** | Brutto: **290.00 zł**
* **Rachunek bankowy do zapłaty:** Nie wskazano

**Przebieg audytu poszczególnych pozycji:**

| Pozycja na fakturze | Netto | VAT | Kwalifikacja podatkowa | Odliczenie VAT | Uzasadnienie decyzji audytora |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Paliwo benzyna milesPLUS 98 | 235.77 zł | 54.23 zł (23%) | 🚗 Pojazd 50% (art. 86a) | **27.12 zł** | Ręczna decyzja przedsiębiorcy w bieżącym okresie |

* **Podsumowanie rozliczenia dokumentu:**
  * VAT zaliczony do odliczenia (rejestr zakupów JPK_V7): **27.12 zł**
  * VAT nieodliczony (wyłączenia prywatne / limit 50% na auto): **27.11 zł**

---
## 🛡️ Część III: Podsumowanie Audytu i Bilans Bezpieczeństwa Podatkowego

### 1. Zestawienie Zbiorcze Podatku VAT
* **Łączny VAT należny ze sprzedaży:** **8395.00 zł**
* **Łączny VAT naliczony podlegający odliczeniu:** **861.67 zł**
* **Łączny VAT odrzucony jako prywatny / nieodliczony:** **80.50 zł**
* **Finalny wynik VAT-7 za ten miesiąc:** **7533 zł** (do zapłaty)

### 2. Eliminacja Ryzyk Podatkowych (Ochrona Podatkowa)
* Wszystkie pozycje o charakterze osobistym (np. opieka medyczna, telewizja, zakupy prywatne) zostały zidentyfikowane i trwale wykluczone z odliczenia podatku VAT.
* Zapobiega to zakwestionowaniu rozliczenia przez organy Krajowej Administracji Skarbowej (KAS) oraz eliminuje ryzyko nałożenia dodatkowego zobowiązania podatkowego (sankcji VAT do 30% z art. 112b ustawy o VAT) wraz z odsetkami za zwłokę.
* Zastosowano ustawowy limit 50% odliczenia VAT na wydatki eksploatacyjne pojazdów osobowych użytkowanych w trybie mieszanym (art. 86a ustawy o VAT).

### 3. Weryfikacja Rachunków Bankowych na Białej Liście Podatników VAT (art. 22p PIT)
* Zgodnie z procedurą należytej staranności, numery rachunków bankowych z faktur zakupowych poddano weryfikacji w oficjalnym wykazie Ministerstwa Finansów.
* Płatności powyżej 15 000 zł brutto na rachunki figurujące na Białej Liście MF gwarantują pełne bezpieczeństwo podatkowe, zachowanie prawa do KUP oraz brak solidarnej odpowiedzialności za VAT (art. 117ba Ordynacji podatkowej).

---
## 🔍 Część IV: Rejestr Wykrytych Duplikatów i Kolizji Źródłowych (Deduplikacja)
W procesie księgowania wykryto zdublowane dokumenty. Zgodnie z nadrzędnymi regułami bezpieczeństwa podatkowego:
1. **KSeF First:** Faktury pobrane bezpośrednio z Krajowego Systemu e-Faktur stanowią urzędowe źródło prawdy. Pliki wgrane do katalogów non-ksef dublujące KSeF zostały odrzucone.
2. **Cross-Month Protection:** Dokumenty uprzednio zaksięgowane w innych miesiącach zostały zablokowane przed ponownym ujęciem.

| Lp. | Odrzucony dokument | Pierwotny dokument | Typ kolizji | Wartość brutto | Uzasadnienie i ochrona |
| :---: | :--- | :--- | :---: | :---: | :--- |
| 1 | `INV-2026-10-FASTNET.txt` (nr: `FV/2026/10/FAST-891`) | `INV-2026-10-FASTNET.pdf` (2026-10) | 📄 Zdublowany plik | 2275.50 zł | Faktura 'FV/2026/10/FAST-891' od FAST-NET CLOUD SP. Z O.O., NIP 9990001122 (2275.50 zł brutto) została wgrana wielokrotnie w tym samym miesiącu (plik 'INV-2026-10-FASTNET.txt' duplikuje plik 'INV-2026-10-FASTNET.pdf'). Zdublowany plik został pominięty. Dokument zostanie ujęty w księgowaniu tylko raz. |

*Łącznie wykluczono:* **1** prób podwójnego ujęcia dokumentów.
