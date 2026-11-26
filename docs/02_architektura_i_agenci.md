# 🏗️ Rozdział 2: Architektura Systemu & Zespół Agentów

Architektura **TaxPilot AI** została zaprojektowana według restrykcyjnych standardów inżynierii oprogramowania FinTech, w których nie ma miejsca na błędy numeryczne ani halucynacje modeli sztucznej inteligencji.

---

## 1. Naczelne Zasady Architektoniczne

### 1.1. Zero-Hallucination Policy (Separacja Rozumowania od Arytmetyki)
W systemach podatkowo-księgowych halucynacja kwoty podatku lub składki ZUS niesie za sobą bezpośrednie konsekwencje prawno-skarbowe. Dlatego w TaxPilot AI obowiązuje ścisły podział odpowiedzialności:

```mermaid
graph LR
    subgraph "🤖 Warstwa Poznawcza (LLM / Agent AI)"
        A1["Zrozumienie intencji języka naturalnego"]
        A2["Orkiestracja etapów procesu"]
        A3["Dialog z przedsiębiorcą (Human-in-the-Loop)"]
        A4["Generowanie czytelnych raportów Markdown"]
    end

    subgraph "⚙️ Warstwa Deterministyczna (Python Decimal Engine)"
        B1["Kalkulator składek ZUS (społeczne + zdrowotna)"]
        B2["Zaliczka na podatek dochodowy PIT-28"]
        B3["Bilans i proporcje podatku VAT-7"]
        B4["Weryfikacja sum kontrolnych (Modulo 11, Modulo 97-10)"]
    end

    A2 -->|Zlecenie kalkulacji| B1
    A2 -->|Zlecenie kalkulacji| B2
    A2 -->|Zlecenie kalkulacji| B3
    B1 -->|Zwrot dokładnych kwot Decimal| A4
    B2 -->|Zwrot dokładnych kwot Decimal| A4
    B3 -->|Zwrot dokładnych kwot Decimal| A4
```

> [!CAUTION]
> **Zasada nienaruszalna:** Agentowi AI **bezwzględnie zabrania się liczenia podatków w pamięci roboczej LLM**. Każda liczba pojawiająca się w zestawieniach finansowych, Paczce Przelewów czy ewidencji przychodów pochodzi wprost z kodu Pythona operującego na typie `Decimal`.

---

### 1.2. Architektura Multi-Tenant w Strukturze Dyskowej
Wszystkie dane firmowe, faktury, reguły kwalifikacji oraz wygenerowane rozliczenia podlegają izolacji dyskowej w dedykowanych podkatalogach:

```text
firmy/{NIP-Nazwa_Firmy}/
├── profil.json                       # Profil podatnika (NIP, forma opodatkowania, schemat ZUS, KSeF)
├── reguly_kosztowe.json              # Trwale wyuczone reguły kwalifikacji pozycji kosztowych
├── reguly_sprzedazy.json             # Reguły przypisywania stawek ryczałtu dla kontrahentów
├── faktury/                          # Archiwum dokumentów finansowych
│   └── {ROK}/{MIESIAC}/
│       ├── sprzedaz/                 # Przychody (ksef/, non-ksef-raw/, non-ksef-extracted/)
│       └── koszty/                   # Wydatki (ksef/, non-ksef-raw/, non-ksef-extracted/)
├── rozliczenia/                      # Wygenerowane oficjalne raporty
│   └── {ROK}/{MIESIAC}/
│       ├── rozliczenie.json          # Maszynowy stan rozliczenia
│       ├── rozliczenie.md            # Oficjalny raport z Paczką Przelewów
│       ├── ewidencja-przychodow.md   # Ewidencja przychodów za dany miesiąc
│       ├── ewidencja-przychodow-sumy.md # Zestawienie YTD (od początku roku)
│       └── sprawozdanie.md           # Sprawozdanie audytowe z weryfikacji dokumentów
└── weryfikacje/                      # Archiwum procedury należytej staranności (AML / Sankcje / VAT)
    └── {ROK}/{MIESIAC}/
        ├── raport-weryfikacji.md     # Zbiorczy raport compliance za dany miesiąc
        ├── raport-weryfikacji.json   # Maszynowy stan z sumami SHA-256
        └── karty/                    # Indywidualne Karty Weryfikacji Kontrahenta (dowód na 5 lat)
```

---

## 2. Diagram Współpracy Zespołu Agentów

Proces comiesięcznego rozliczenia podatkowego i generowania przelewów opiera się na orkiestracji wyspecjalizowanych agentów:

```mermaid
sequenceDiagram
    autonumber
    actor U as Przedsiębiorca
    participant O as Tax Director (Orchestrator Agent)
    participant DA as Document Ingestion Agent
    participant BA as Bookkeeping Agent
    participant TA as Tax Settlement Agent
    participant OA as Tax Advisor Agent

    U->>O: "Rozlicz październik 2026"
    O->>DA: Synchronizuj faktury (KSeF 2.0 + Non-KSeF)
    Note over DA: ksef-sync / non-ksef-extract
    DA-->>O: Zaimportowano i zdeduplikowano dokumenty
    
    O->>O: Pre-settlement Review (Wstępny przegląd)
    O->>U: Przedstawienie 3 tabel i pozycji do wyjaśnienia
    U-->>O: Akceptacja wydatków i decyzje (np. 100% firmowy)

    O->>BA: Zaksięguj dokumenty i utrwal reguły
    Note over BA: cost_classifier / ryczalt_classifier
    BA-->>O: Ewidencja przychodów (12%) i rejestr VAT

    O->>TA: Oblicz ZUS i podatki
    Note over TA: zus_calculator / pit28 / vat_tools
    TA-->>O: Wyliczono: ZUS, PIT-28, VAT-7 i Paczkę Przelewów z kodami QR

    O->>OA: Analiza optymalizacyjna
    Note over OA: simulate_tax_regimes / audit_leaks
    OA-->>O: Symulacja form opodatkowania i alert brakujących kosztów

    O->>U: Prezentacja Paczki Przelewów Podatnika i raportów
```

---

## 3. Role i Odpowiedzialności Agentów

### 1. Tax Director / Orchestrator Agent (Główny Koordynator)
* **Zadanie:** Pierwsza linia kontaktu z przedsiębiorcą. Kieruje przepływem informacji, zarządza stanem okresu rozliczeniowego i syntetyzuje raporty.
* **Zakres wiedzy:** Profil podatnika, kalendarz podatkowy (terminy: 20. dzień miesiąca dla PIT/ZUS, 25. dzień dla VAT).
* **Zasada:** Nie wykonuje kalkulacji w pamięci LLM – deleguje zadania narzędziom Python i pod-agentom.

### 2. Document Ingestion Agent (Agent Dokumentów)
* **Zadanie:** Pozyskiwanie, walidacja i bezpieczna archiwizacja dokumentów.
* **Kluczowe moduły:**
  * `KSeFClient` & `KSeFParser`: Szyfrowanie sesji RSA-OAEP SHA-256 certyfikatem MF, pobieranie faktur XML FA(2)/FA(3).
  * `NonKSeFExtractor`: Natywna ekstrakcja PDF, obrazów oraz JSON (faktury zagraniczne, Google Cloud, AWS, GitHub).
  * `InvoiceDeduplicator`: Wykrywanie kolizji według reguły **KSeF First** (faktura z KSeF ma nadrzędną moc nad plikiem PDF/papierowym).
  * `Auto-Routing`: Automatyczne rozpoznawanie NIP i relokacja omyłkowo upuszczonych faktur (np. sprzedaż wrzucona do folderu kosztów).

### 3. Bookkeeping Agent (Agent Księgowy)
* **Zadanie:** Prawidłowa kwalifikacja podatkowa zdarzeń gospodarczych.
* **Kluczowe moduły:**
  * `CostClassifier`: Klasyfikacja pozycji kosztowych:
    * `FIRMOWY_100`: 100% odliczenia VAT, 100% koszt uzyskania przychodu,
    * `SAMOCHOD_50`: 50% odliczenia VAT (art. 86a ustawy o VAT), 75% kosztu KUP,
    * `PRYWATNY_0`: 0% odliczenia VAT, wydatek prywatny (np. pakiet TV, streaming),
    * `DO_WYJASNIENIA`: Pytanie do przedsiębiorcy w procedurze *Human-in-the-Loop*.
  * `ReczneKwalifikacjeService`: Atomowy zapis decyzji z blokadą plikową (`lock=True`).

### 4. Tax Settlement Agent (Agent Podatkowy & ZUS)
* **Zadanie:** Deterministyczne wyliczenie zobowiązań podatkowych i składek ZUS.
* **Kluczowe moduły:**
  * `calculate_zus`: Składki społeczne (emerytalna, rentowa, wypadkowa, chorobowa, FP) oraz składka zdrowotna ryczałtu (progi: do 60k, do 300k, powyżej 300k zł narastająco YTD).
  * `calculate_pit28_advance`: Zaliczka PIT-28 po odliczeniu składek społecznych i 50% zapłaconej składki zdrowotnej (zaokrąglenie do pełnych złotych).
  * `calculate_vat_settlement`: Bilans VAT-7 z bezpiecznym przeniesieniem nadwyżki z poprzedniego miesiąca (`max(0, nadwyzka)`).
  * `SettlementService`: Generowanie Paczki Przelewów z kodami QR w standardzie ZBP / Elixir.

### 5. Tax Optimization Advisor Agent (Agent Doradca)
* **Zadanie:** Proaktywne wsparcie doradcze i audyt wydatków.
* **Kluczowe moduły:**
  * `simulate_tax_regimes`: Porównanie opłacalności Ryczałtu vs Podatku Liniowego 19% vs Skali Podatkowej 12%/32% w ujęciu rocznym.
  * `audit_expense_leaks`: Wykrywanie brakujących powtarzalnych faktur (księgowość, hosting, telefony, leasing).
  * Analiza ulg podatkowych: IP-Box (5% dla branży IT) oraz ulga B+R.

---

## ⏭️ Kolejny Rozdział

Dowiedz się, jak działa bezpośrednia integracja z Krajowym Systemem e-Faktur:  
👉 [**Przejdź do: 03. KSeF 2.0 & Kryptografia**](03_ksef_i_kryptografia.md)
