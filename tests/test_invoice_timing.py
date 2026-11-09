"""
Testy jednostkowe kwalifikacji okresu rozliczeniowego faktur sprzedaży i kosztów.
Weryfikuje zgodność z art. 19a VAT / art. 14 PIT (sprzedaż) oraz art. 86 ust. 10b VAT (zakupy).
"""

import unittest
from decimal import Decimal
from src.core.invoice import Invoice, InvoiceType, InvoiceParty


class TestInvoiceTiming(unittest.TestCase):
    def setUp(self):
        self.seller = InvoiceParty(nip="7770001122", nazwa="Sprzedawca")
        self.buyer = InvoiceParty(nip="5322030067", nazwa="Nabywca")

    def test_sales_invoice_month_transition(self):
        # Sprzedaż wykonana 31.08, faktura wystawiona 02.09
        # Powinna wejść do przychodów sierpnia (art. 19a VAT / art. 14 PIT)
        inv = Invoice(
            numer="1/09/2026",
            data_wystawienia="2026-09-02",
            data_sprzedazy="2026-08-31",
            sprzedawca=self.seller,
            nabywca=self.buyer,
            typ=InvoiceType.SPRZEDAZ,
            suma_netto=Decimal("1000.00"),
            suma_vat=Decimal("230.00"),
            suma_brutto=Decimal("1230.00"),
        )
        self.assertEqual(inv.rok, "2026")
        self.assertEqual(inv.miesiac, "08")
        self.assertEqual(inv.okres_rozliczeniowy, ("2026", "08"))

    def test_purchase_invoice_month_transition_vikingco(self):
        # Usługa telekomunikacyjna za lipiec (31.07), faktura wystawiona i otrzymana w KSeF 06.08
        # Prawo do odliczenia VAT powstaje w dacie otrzymania dokumentu (sierpień) - art. 86 ust. 10b VAT
        inv = Invoice(
            numer="2026-08-0107919-Z",
            data_wystawienia="2026-08-06",
            data_sprzedazy="2026-07-31",
            sprzedawca=self.seller,
            nabywca=self.buyer,
            typ=InvoiceType.KOSZT,
            suma_netto=Decimal("44.72"),
            suma_vat=Decimal("10.28"),
            suma_brutto=Decimal("55.00"),
        )
        self.assertEqual(inv.rok, "2026")
        self.assertEqual(inv.miesiac, "08")
        self.assertEqual(inv.okres_rozliczeniowy, ("2026", "08"))

    def test_purchase_invoice_september_transition(self):
        # Usługa za sierpień (31.08), faktura wystawiona 07.09
        # Wchodzi do rozliczenia września (nie sierpnia!)
        inv = Invoice(
            numer="2026-09-0107425-Z",
            data_wystawienia="2026-09-07",
            data_sprzedazy="2026-08-31",
            sprzedawca=self.seller,
            nabywca=self.buyer,
            typ=InvoiceType.KOSZT,
            suma_netto=Decimal("56.91"),
            suma_vat=Decimal("13.09"),
            suma_brutto=Decimal("70.00"),
        )
        self.assertEqual(inv.rok, "2026")
        self.assertEqual(inv.miesiac, "09")
        self.assertEqual(inv.okres_rozliczeniowy, ("2026", "09"))

    def test_invoice_without_sales_date(self):
        inv = Invoice(
            numer="FV/123",
            data_wystawienia="2026-05-15",
            data_sprzedazy=None,
            sprzedawca=self.seller,
            nabywca=self.buyer,
            typ=InvoiceType.KOSZT,
            suma_netto=Decimal("100.00"),
            suma_vat=Decimal("23.00"),
            suma_brutto=Decimal("123.00"),
        )
        self.assertEqual(inv.rok, "2026")
        self.assertEqual(inv.miesiac, "05")


if __name__ == "__main__":
    unittest.main()

