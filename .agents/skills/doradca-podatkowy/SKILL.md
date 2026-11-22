---
name: doradca-podatkowy
description: >-
  Użyj tego skilla, gdy użytkownik pyta o optymalizację podatkową, porównanie form opodatkowania
  (Ryczałt vs Podatek Liniowy 19% vs Skala Podatkowa 12%/32%), audyt powtarzalnych kosztów
  lub poszukiwanie oszczędności podatkowych w JDG.
---

# Procedura Doradztwa i Optymalizacji Podatkowej (Tax Advisor)

Ten skill dostarcza przedsiębiorcy proaktywnych analiz finansowych i porównawczych, pozwalających na wybór najbardziej opłacalnej formy opodatkowania oraz wykrywanie brakujących kosztów.

## 1. Symulator Form Opodatkowania

Gdy użytkownik pyta o opłacalność formy opodatkowania lub planowane przychody:

### Wykonanie w Pythonie:
```python
from decimal import Decimal
from src.skills.tax_advisor_tools import simulate_tax_regimes

comp = simulate_tax_regimes(
    przychody_roczne=Decimal("{PRZYCHODY}"),
    koszty_roczne=Decimal("{KOSZTY}"),
    stawka_ryczaltu=Decimal("{STAWKA_RYCZALTU}"),  # np. Decimal("0.12") dla IT
    rok="{ROK}",
)
print(comp.generate_markdown())
```

### Prezentacja Wyników:
Przedstaw czytelną tabelę zestawiającą:
* Roczny przychód i koszty,
* Składki ZUS społeczne i zdrowotne dla każdej formy (uwzględniając progi ryczałtu i 4.9% na liniowym),
* Podatek dochodowy (PIT),
* Łączne obciążenia publicznoprawne,
* **Czysty dochód netto "na rękę"**,
* Wskaż zwycięską formę i kwotę rocznej oszczędności.

## 2. Audyt Brakujących Kosztów (Expense Leak Detector)

Gdy przedsiębiorca zamyka dany miesiąc, warto sprawdzić, czy nie zapomniał o regularnych fakturach:

### Wykonanie w Pythonie:
```python
from src.core.company import CompanyProfile
from src.skills.tax_advisor_tools import audit_expense_leaks

profile = CompanyProfile.load_by_nip("{NIP}")
audit = audit_expense_leaks(profile, "{ROK}", "{MIESIAC}")
```

### Analiza:
* Sprawdza historię z ostatnich 3 miesięcy.
* Wykrywa brak faktury od stałych dostawców (np. leasing, hosting, telefon, biuro, księgowość).
* Zwraca alert z ostrzeżeniem dla użytkownika przed finalnym zamknięciem rozliczenia.

