"""
Fixtures i dane pomocnicze do testów jednostkowych.
Zapewnia pełną hermetyczność testów bez zależności od rzeczywistych danych firmy.
"""

import json
import shutil
from decimal import Decimal
from pathlib import Path

from src.core.company import CompanyProfile, FormaOpodatkowania, ZUSConfig, KSeFConfig, TypZUS
from src.core.invoice import Invoice, InvoiceType, InvoiceParty, InvoiceItem
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.skills.cost_classifier import RegulyKosztoweFirmy, RegulaPozycji, KwalifikacjaKosztu
from src.level_2_bookkeeping.ledger import RegulySprzedazyFirmy


TEST_NIP = "7770001122"
TEST_NAME = "CloudTech Solutions Jan Kowalski"


def setup_test_company() -> CompanyProfile:
    """Tworzy zanonimizowany profil firmy testowej oraz strukturę faktur za kwiecień 2026."""
    profile = CompanyProfile(
        nip=TEST_NIP,
        nazwa=TEST_NAME,
        katalog_nazwa=f"{TEST_NIP}-CloudTech_Solutions_Jan_Kowalski",
        forma_opodatkowania=FormaOpodatkowania.RYCZALT,
        domyslna_stawka_ryczaltu=0.12,
        platnik_vat=True,
        zus=ZUSConfig(typ=TypZUS.PELNY_ZUS, chorobowe_dobrowolne=True),
        ksef=KSeFConfig(srodowisko="TEST", token="0261108-TEST-TOKEN|nip-7770001122|abcdef1234567890"),
    )
    profile.save()

    # Reguły kosztowe firmy
    reguly = RegulyKosztoweFirmy(
        nip_firmy=TEST_NIP,
        reguly_globalne=[
            RegulaPozycji(wzorzec="paliwo", kwalifikacja=KwalifikacjaKosztu.SAMOCHOD_50, uzasadnienie="Paliwo do samochodu osobowego"),
            RegulaPozycji(wzorzec="efecta", kwalifikacja=KwalifikacjaKosztu.SAMOCHOD_50, uzasadnienie="Paliwo Orlen"),
        ]
    )
    reguly.save(profile)

    # Reguły sprzedaży firmy (np. 12% ryczałtu dla odbiorcy)
    reguly_sprzedazy = RegulySprzedazyFirmy(
        nip_firmy=TEST_NIP,
        stawki_nabywcow={"5213242793": Decimal("0.12"), "5252545285": Decimal("0.12")}
    )
    reguly_sprzedazy.save(profile)

    seller_me = InvoiceParty(nip=TEST_NIP, nazwa=TEST_NAME, kraj="PL")

    # 1. Faktury sprzedaży 2026-04
    inv_s1 = Invoice(
        numer="1/04/2026",
        data_wystawienia="2026-04-30",
        data_sprzedazy="2026-04-30",
        sprzedawca=seller_me,
        nabywca=InvoiceParty(nip="5252545285", nazwa="Klient Korporacyjny Sp. z o.o.", kraj="PL"),
        typ=InvoiceType.SPRZEDAZ,
        suma_netto=Decimal("37470.00"),
        suma_vat=Decimal("8618.10"),
        suma_brutto=Decimal("46088.10"),
        pozycje=[InvoiceItem(opis="Usługi programistyczne i architektoniczne IT", wartosc_netto=Decimal("37470.00"), stawka_vat="23", kwota_vat=Decimal("8618.10"), wartosc_brutto=Decimal("46088.10"))]
    )
    inv_s2 = Invoice(
        numer="2/04/2026",
        data_wystawienia="2026-04-30",
        data_sprzedazy="2026-04-30",
        sprzedawca=seller_me,
        nabywca=InvoiceParty(nip="5213242793", nazwa="Piotr Wiśniewski Doradztwo", kraj="PL"),
        typ=InvoiceType.SPRZEDAZ,
        suma_netto=Decimal("1499.00"),
        suma_vat=Decimal("344.77"),
        suma_brutto=Decimal("1843.77"),
        pozycje=[InvoiceItem(opis="Usługa utrzymania i zarządzania infrastrukturą informatyczną", wartosc_netto=Decimal("1499.00"), stawka_vat="23", kwota_vat=Decimal("344.77"), wartosc_brutto=Decimal("1843.77"))]
    )
    InvoiceStorage.save_invoice(profile, inv_s1)
    InvoiceStorage.save_invoice(profile, inv_s2)

    # 2. Faktury kosztowe 2026-04 (8 faktur)
    koszty_dane = [
        ("6468569", "2026-04-02", "5270203968", "Kawa i akcesoria biurowe", Decimal("190.22"), Decimal("43.76"), Decimal("233.98")),
        ("39053/04/2026", "2026-04-05", "5252834567", "Usługi chmurowe hosting", Decimal("59.88"), Decimal("13.77"), Decimal("73.65")),
        ("F 18303/0796/26", "2026-04-09", "7740001454", "EFECTA 95 CN27101245 paliwo", Decimal("330.94"), Decimal("26.47"), Decimal("357.41")),
        ("2026/04/7661", "2026-04-12", "5213123456", "Materiały eksploatacyjne IT", Decimal("40.65"), Decimal("9.35"), Decimal("50.00")),
        ("6474098", "2026-04-16", "5270203968", "Nespresso kawa do biura", Decimal("120.72"), Decimal("27.78"), Decimal("148.50")),
        ("46/04/2026", "2026-04-22", "5213242793", "Usługi księgowe w/g umowy", Decimal("250.00"), Decimal("57.50"), Decimal("307.50")),
        ("F 15146/1561/26", "2026-04-24", "7740001454", "EFECTA 95 CN27101245 paliwo", Decimal("330.02"), Decimal("26.40"), Decimal("356.42")),
        ("2026-05-0105715-Z", "2026-04-28", "8971793639", "usługi inne", Decimal("48.78"), Decimal("11.22"), Decimal("60.00")),
    ]

    for nr, dt, nip_s, opis, n, v, b in koszty_dane:
        inv_k = Invoice(
            numer=nr,
            data_wystawienia=dt,
            data_sprzedazy=dt,
            sprzedawca=InvoiceParty(nip=nip_s, nazwa=f"Sprzedawca {nip_s}", kraj="PL"),
            nabywca=seller_me,
            typ=InvoiceType.KOSZT,
            suma_netto=n,
            suma_vat=v,
            suma_brutto=b,
            pozycje=[InvoiceItem(opis=opis, wartosc_netto=n, stawka_vat="23", kwota_vat=v, wartosc_brutto=b)]
        )
        InvoiceStorage.save_invoice(profile, inv_k)

    return profile


def cleanup_test_company(profile: CompanyProfile):
    """Usuwa tymczasowy katalog firmy testowej."""
    test_dir = profile.katalog_firmy
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)
