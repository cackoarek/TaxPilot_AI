"""
Testy jednostkowe weryfikujące natywną ekstrakcję tekstu z PDF (pypdf).
Gwarantują pełną niezależność od zewnętrznych binariów systemowych (poppler/pdftotext)
zarówno na systemie Linux, jak i Windows.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from src.core.invoice import InvoiceType
from src.level_1_ingestion.ai_document_extractor import AIDocumentExtractor
from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
from tests.fixtures import setup_test_company


def create_sample_pdf(tmp_path: Path, content_lines: list[str]) -> Path:
    """Tworzy prosty dokument PDF w pamięci i zapisuje do pliku tymczasowego."""
    pdf_file = tmp_path / "test_invoice.pdf"
    c = canvas.Canvas(str(pdf_file), pagesize=letter)
    y = 750
    for line in content_lines:
        c.drawString(50, y, line)
        y -= 25
    c.save()
    return pdf_file


class TestPDFExtractionPyPDF(unittest.TestCase):
    def setUp(self):
        self.profile = setup_test_company()
        self.tmp_dir = Path("tests/.tmp_test_pdf")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil

        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_pypdf_extraction_without_pdftotext_binary(self):
        """Weryfikuje, że pypdf poprawnie wyciąga tekst faktury nawet gdy pdftotext jest niedostępny w OS (np. Windows)."""
        lines = [
            "Faktura VAT nr FV/2026/01/999",
            "Data wystawienia: 15-01-2026",
            "Sprzedawca: Hosting Cloud Sp. z o.o. NIP 5252545285",
            "Nabywca: CloudTech Solutions Jan Kowalski NIP 7770001122",
            "Pozycja: Usługa serwerowa Cloud VPS Netto 1000.00 zł VAT 230.00 zł Brutto 1230.00 zł",
        ]
        pdf_path = create_sample_pdf(self.tmp_dir, lines)

        # Symulujemy brak pdftotext w systemie operacyjnym (shutil.which zwraca None)
        with patch("shutil.which", return_value=None):
            invoice = NonKSeFExtractor._extract_from_pdf(
                pdf_path,
                self.profile,
                rok="2026",
                miesiac="01",
                invoice_type=InvoiceType.KOSZT,
            )

            self.assertIsNotNone(invoice)
            self.assertEqual(invoice.numer, "FV/2026/01/999")
            self.assertEqual(invoice.suma_brutto, 1230.0)
            self.assertEqual(invoice.sprzedawca.nip, "5252545285")

    def test_ai_document_extractor_uses_pypdf(self):
        """Weryfikuje, że AIDocumentExtractor._read_file_content używa pypdf przy braku pdftotext."""
        lines = [
            "FAKTURA ZAKUPU nr F/123/2026",
            "Data: 2026-02-10",
            "Wartość brutto: 500,00 PLN",
        ]
        pdf_path = create_sample_pdf(self.tmp_dir, lines)

        with patch("shutil.which", return_value=None):
            text, binary_data, mime = AIDocumentExtractor._read_file_content(pdf_path)
            self.assertIsNotNone(text)
            self.assertIn("FAKTURA ZAKUPU nr F/123/2026", text)
            self.assertEqual(mime, "text/plain")
            self.assertIsNone(binary_data)


if __name__ == "__main__":
    unittest.main()
