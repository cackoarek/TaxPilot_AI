---
name: rozlicz-miesiac
description: >-
  Użyj tego skilla, gdy użytkownik prosi o rozliczenie podatkowo-księgowe wybranego miesiąca
  (np. "Rozlicz październik 2026", "Zaksięguj styczeń", "Oblicz podatki za zeszły miesiąc").
  Prowadzi proces krok po kroku: KSeF sync, wstępny przegląd dokumentów (przychody, koszty do akceptacji,
  pozycje do wyjaśnienia), ewidencja przychodów, rejestry VAT, kalkulacja ZUS, PIT-28 i VAT-7
  oraz generowanie gotowej Paczki Przelewów Podatnika.
---

# Procedura Rozliczenia Miesięcznego (Tax Settlement)

Ten skill prowadzi agenta przez kompletny, bezpieczny i deterministyczny proces rozliczenia miesiąca dla Jednoosobowej Działalności Gospodarczej.

## Wytyczne Operacyjne

1. **Zero-Hallucination Policy:**
   Nigdy nie wyliczaj podatków ani składek ZUS za pomocą arytmetyki LLM. Zawsze uruchamiaj deterministyczny kod Pythona.

2. **Domyślna Firma:**
   Jeśli użytkownik nie podał NIP-u, załaduj domyślny profil:
   `NIP: 7770001122` (*CloudTech Solutions Jan Kowalski*).

3. **Obowiązkowy Krok Weryfikacji (Human-in-the-Loop):**
   Przed ostatecznym obliczeniem podatków agent **MUSI** przedstawić przedsiębiorcy wstępny przegląd:
   * Faktury przychodowe (czy nie brakuje żadnej faktury sprzedaży),
   * Faktury kosztowe (czy faktycznie należą do działalności),
   * Pozycje do wyjaśnienia i wykluczenia prywatne.

---

## Krok 1: Weryfikacja Dokumentów i Ekstrakcja (KSeF + Non-KSeF)

Sprawdź stan dokumentów w katalogu firmy za wskazany miesiąc:
`firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/`

1. **Faktury z KSeF (przychody w `sprzedaz/ksef/` oraz zakupy w `koszty/ksef/`):**
   * Jeśli brak faktur lub użytkownik prosi o pobranie z KSeF, wykonaj synchronizację:
     ```bash
     python -m src.cli sync --nip {NIP} --rok {ROK} --miesiac {MIESIAC}
     ```

2. **Faktury spoza KSeF (Non-KSeF – sprzedaż zagraniczna, usługi chmurowe, PDF, rachunki):**
   * Sprawdź obecność plików w folderach:
     - Sprzedaż: `firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/sprzedaz/non-ksef-raw/`
     - Koszty: `firmy/{NIP-Nazwa}/faktury/{ROK}/{MIESIAC}/koszty/non-ksef-raw/`
   * Jeśli użytkownik wrzucił nowe dokumenty, uruchom ekstrakcję encji:
     ```bash
     python -m src.cli extract-non-ksef --nip {NIP} --rok {ROK} --miesiac {MIESIAC}
     ```
     *(Narzędzia `przeglad` oraz `rozlicz` uruchamiają ten krok również automatycznie, zapewniając pełną spójność danych).*

---

## Krok 2: Wstępny Przegląd i Akceptacja Dokumentów (Pre-settlement Review)

Przed faktycznym rozliczeniem kosztów i podatków wygeneruj zestawienie weryfikacyjne:

```bash
python -m src.cli przeglad --nip {NIP} --rok {ROK} --miesiac {MIESIAC}
```
*(lub wywołaj narzędzie `review_month_invoices`).*

Agent prezentuje użytkownikowi trzy przejrzyste tabele:

### 1. Tabela Faktur Przychodowych (Sprzedaż)
* Prezentuje listę faktur sprzedaży zakwalifikowanych do przychodów danego miesiąca (numer, data, nabywca, NIP, kwota netto, ryczałt, VAT, brutto, przedmiot sprzedaży).
* **Zadanie dla przedsiębiorcy:** Sprawdzenie, czy to wszystkie faktury sprzedaży z tego miesiąca i czy nie brakuje jakiegoś zlecenia/faktury wystawionej poza KSeF.

### 2. Tabela Faktur Kosztowych (Zakupy) – Do Akceptacji
* Prezentuje zestawienie wszystkich faktur zakupowych pobranych z KSeF (numer, data, sprzedawca, NIP, kwota netto, VAT, brutto, przedmiot, wstępna kwalifikacja).
* **Zadanie dla przedsiębiorcy:** Potwierdzenie, czy wszystkie faktury faktycznie należą do jego firmy i dotyczą działalności gospodarczej.

### 3. Tabela Faktur i Pozycji do Wyjaśnienia
* Prezentuje wyodrębnione pozycje niejednoznaczne (`DO_WYJASNIENIA`) oraz pozycje wykluczone jako prywatne (`PRYWATNY_0`).
* **Zadanie dla przedsiębiorcy:** Rozstrzygnięcie wątpliwości (np. opłaty za usługi inne w Play – czy to firmowe stałe IP serwera, czy wydatek prywatny; potwierdzenie wykluczenia pakietu medycznego/TV).

### Utrwalenie Reguł Firmy:
Po uzyskaniu odpowiedzi od przedsiębiorcy, agent zapisuje decyzję do bazy wiedzy firmy:
```bash
python -m src.cli regula --nip {NIP} --kontrahent-nip {KONTRAHENT_NIP} --wzorzec "{WZORZEC}" --kwalifikacja {FIRMOWY_100|SAMOCHOD_50|PRYWATNY_0} --uzasadnienie "{UZASADNIENIE}"
```
Dzięki temu w kolejnych miesiącach ta pozycja będzie klasyfikowana automatycznie!

---

## Krok 3: Deterministyczne Przeliczenie Zobowiązań

Po uzyskaniu akceptacji przedsiębiorcy uruchom silnik rozliczeniowy:

```bash
python -m src.cli rozlicz --nip {NIP} --rok {ROK} --miesiac {MIESIAC}
```

Silnik automatycznie:
1. Księguje faktury sprzedaży w Ewidencji Przychodów (Ryczałt 12% dla IT).
2. Uwzględnia nauczone i potwierdzone reguły kosztowe z `reguly_kosztowe.json`.
3. Stosuje 50% VAT dla samochodów osobowych i 100% dla wydatków firmowych.
4. Wylicza przychód roczny narastająco i właściwy próg składki zdrowotnej ZUS.
5. Wylicza składki społeczne ZUS oraz składkę zdrowotną.
6. Wylicza zaliczkę PIT-28 z odliczeniami.
7. Oblicza bilans VAT-7.
8. Zapisuje oficjalny raport w `firmy/{NIP-Nazwa}/rozliczenia/{ROK}/{MIESIAC}/rozliczenie.md`.

---

## Krok 4: Prezentacja Paczki Przelewów Podatnikowi

Zwróć użytkownikowi zwięzłą, czytelną tabelę podsumowującą 3 przelewy:

```markdown
### 💸 Paczka Przelewów Podatkowych za {ROK}-{MIESIAC}

| Odbiorca / Zobowiązanie | Kwota do zapłaty | Termin płatności | Rachunek docelowy | Tytuł przelewu |
| :--- | :---: | :---: | :--- | :--- |
| **ZUS (Społeczne + Zdrowotna)** | **{KWOTA_ZUS} zł** | `{TERMIN_ZUS}` | Indywidualny Rachunek Składkowy ZUS (NRS) | `Składki ZUS za {M}/{ROK}` |
| **Urząd Skarbowy – Ryczałt PIT-28** | **{KWOTA_PIT} zł** | `{TERMIN_PIT}` | Indywidualny Mikrorachunek Podatkowy | `Zaliczka PIT-28 za {M}/{ROK}` |
| **Urząd Skarbowy – Podatek VAT-7** | **{KWOTA_VAT} zł** | `{TERMIN_VAT}` | Indywidualny Mikrorachunek Podatkowy | `Podatek VAT-7 za {M}/{ROK}` |

**Łączna kwota do zapłaty:** **{SUMA} zł**
```

Podaj również link do wygenerowanego raportu szczegółowego:
`firmy/{NIP-Nazwa}/rozliczenia/{ROK}/{MIESIAC}/rozliczenie.md`
