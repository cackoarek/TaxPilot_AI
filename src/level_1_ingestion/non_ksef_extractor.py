"""
Moduł ekstrakcji encji faktur (kosztowych oraz sprzedaży) spoza Krajowego Systemu e-Faktur (Non-KSeF).
Przetwarza surowe pliki wrzucone przez użytkownika:
  faktury/{ROK}/{MIESIĄC}/koszty/non-ksef-raw/        ->  koszty/non-ksef-extracted/{stem}.json
  faktury/{ROK}/{MIESIĄC}/sprzedaz/non-ksef-raw/      ->  sprzedaz/non-ksef-extracted/{stem}.json
"""

import json
import os
import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceType, InvoiceParty, InvoiceItem
from src.level_1_ingestion.invoice_storage import InvoiceStorage


def _clean_amount(text: str) -> Decimal:
    """Konwertuje ciąg znaków kwoty (np. '1 234,56 zł') na Decimal."""
    cleaned = re.sub(r"[^\d,\.]", "", text)
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(" ", "").replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


class NonKSeFExtractor:
    """
    Ekstraktor dokumentów (kosztowych i sprzedaży) spoza KSeF (PDF, JSON, TXT/MD, skany).
    """

    @classmethod
    def extract_file(
        cls,
        raw_path: Path,
        profile: CompanyProfile,
        target_dir: Path,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Optional[Path]:
        """
        Przetwarza pojedynczy plik z non-ksef-raw i zapisuje go w non-ksef-extracted/{stem}.json.
        """
        suffix = raw_path.suffix.lower()
        extracted_invoice: Optional[Invoice] = None

        if suffix == ".json":
            extracted_invoice = cls._extract_from_json(raw_path, profile, rok, miesiac, invoice_type=invoice_type)
        elif suffix in [".txt", ".md"]:
            extracted_invoice = cls._extract_from_text(
                raw_path.read_text(encoding="utf-8", errors="ignore"),
                profile,
                raw_path.name,
                rok,
                miesiac,
                invoice_type=invoice_type,
            )
        elif suffix == ".pdf":
            extracted_invoice = cls._extract_from_pdf(raw_path, profile, rok, miesiac, invoice_type=invoice_type)
        else:
            # Dla innych formatów (np. obrazki bez OCR) tworzymy szablon wstępny
            extracted_invoice = cls._create_fallback_invoice(raw_path, profile, rok, miesiac, invoice_type=invoice_type)

        if not extracted_invoice:
            return None

        # Upewniamy się, że typ, źródło i plik źródłowy są właściwie ustawione
        extracted_invoice.typ = invoice_type
        extracted_invoice.zrodlo = "NON_KSEF"
        extracted_invoice.plik_zrodlowy = raw_path.name

        out_path = target_dir / f"{raw_path.stem}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(extracted_invoice.to_dict(), f, indent=2, ensure_ascii=False)

        return out_path

    @classmethod
    def _extract_from_json(
        cls,
        json_path: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Optional[Invoice]:
        """Ekstrahuje dane z pliku JSON (zarówno formatu Invoice jak i zewnętrznych formatów)."""
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        # Przypadek 1: Plik posiada standardowe klucze Invoice
        if "numer" in data and "sprzedawca" in data and "suma_netto" in data:
            try:
                inv = Invoice.from_dict(data)
                inv.typ = invoice_type
                inv.zrodlo = "NON_KSEF"
                inv.plik_zrodlowy = json_path.name
                if invoice_type == InvoiceType.SPRZEDAZ:
                    inv.sprzedawca = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
                elif invoice_type == InvoiceType.KOSZT:
                    inv.nabywca = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
                return inv
            except Exception:
                pass

        # Przypadek 2: Zewnętrzny JSON z powszechnymi aliasami kluczy
        numer = data.get("invoice_number") or data.get("numer_faktury") or data.get("number") or json_path.stem
        data_wyst = data.get("issue_date") or data.get("data_wystawienia") or f"{rok}-{miesiac.zfill(2)}-01"
        data_sprz = data.get("sale_date") or data.get("data_sprzedazy") or data_wyst

        if invoice_type == InvoiceType.SPRZEDAZ:
            seller = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            buyer_data = data.get("buyer") or data.get("nabywca") or data.get("customer") or data.get("client") or {}
            buyer_nip = str(buyer_data.get("nip") or buyer_data.get("vat_id") or "0000000000")
            buyer_name = str(buyer_data.get("name") or buyer_data.get("nazwa") or "Nieznany Klient")
            buyer_country = str(buyer_data.get("country") or buyer_data.get("kraj") or "PL")
            buyer = InvoiceParty(nip=buyer_nip, nazwa=buyer_name, kraj=buyer_country)
        else:
            seller_data = data.get("seller") or data.get("sprzedawca") or {}
            seller_nip = str(seller_data.get("nip") or seller_data.get("vat_id") or "0000000000")
            seller_name = str(seller_data.get("name") or seller_data.get("nazwa") or "Nieznany Sprzedawca")
            seller_country = str(seller_data.get("country") or seller_data.get("kraj") or "PL")
            seller = InvoiceParty(nip=seller_nip, nazwa=seller_name, kraj=seller_country)
            buyer = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")

        netto = _clean_amount(str(data.get("net_amount") or data.get("suma_netto") or data.get("netto") or "0.00"))
        vat = _clean_amount(str(data.get("vat_amount") or data.get("suma_vat") or data.get("vat") or "0.00"))
        brutto = _clean_amount(str(data.get("gross_amount") or data.get("suma_brutto") or data.get("brutto") or "0.00"))

        if brutto == Decimal("0.00") and netto > Decimal("0.00"):
            brutto = netto + vat
        elif netto == Decimal("0.00") and brutto > Decimal("0.00"):
            netto = brutto - vat

        items = []
        raw_items = data.get("items") or data.get("pozycje") or []
        for it in raw_items:
            opis = it.get("description") or it.get("opis") or ("Usługa IT" if invoice_type == InvoiceType.SPRZEDAZ else "Pozycja kosztowa")
            it_netto = _clean_amount(str(it.get("net") or it.get("wartosc_netto") or netto))
            it_vat = _clean_amount(str(it.get("vat") or it.get("kwota_vat") or vat))
            it_brutto = _clean_amount(str(it.get("gross") or it.get("wartosc_brutto") or brutto))
            it_rate = str(it.get("vat_rate") or it.get("stawka_vat") or "23")
            items.append(
                InvoiceItem(
                    opis=opis,
                    ilosc=Decimal("1"),
                    jednostka="szt",
                    cena_jednostkowa_netto=it_netto,
                    wartosc_netto=it_netto,
                    stawka_vat=it_rate,
                    kwota_vat=it_vat,
                    wartosc_brutto=it_brutto,
                )
            )

        if not items:
            domyslny_opis = "Usługa informatyczna" if invoice_type == InvoiceType.SPRZEDAZ else "Wydatek kosztowy"
            items.append(
                InvoiceItem(
                    opis=domyslny_opis,
                    wartosc_netto=netto,
                    stawka_vat="23" if vat > 0 else "0",
                    kwota_vat=vat,
                    wartosc_brutto=brutto,
                )
            )

        return Invoice(
            numer=numer,
            data_wystawienia=data_wyst,
            data_sprzedazy=data_sprz,
            sprzedawca=seller,
            nabywca=buyer,
            typ=invoice_type,
            suma_netto=netto,
            suma_vat=vat,
            suma_brutto=brutto,
            waluta=data.get("currency") or data.get("waluta") or "PLN",
            pozycje=items,
            zrodlo="NON_KSEF",
            plik_zrodlowy=json_path.name,
        )

    @classmethod
    def _extract_from_text(
        cls,
        text: str,
        profile: CompanyProfile,
        filename: str,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Invoice:
        """Ekstrahuje dane z czystego tekstu (np. po OCR lub pdftotext) przy użyciu heurystyk."""
        # 1. Numer faktury
        num_m = re.search(
            r"(?:faktura(?:\s+vat|\s+proforma)?|fv|invoice|rachunek)\s*(?:nr|numer|no\.?|#)?[\s:]+([A-Za-z0-9][A-Za-z0-9\/\-_]+)|(?:nr|numer|invoice\s*#)[\s:]+([A-Za-z0-9][A-Za-z0-9\/\-_]+)",
            text,
            re.IGNORECASE,
        )
        if num_m:
            numer = (num_m.group(1) or num_m.group(2)).strip()
        else:
            numer = Path(filename).stem

        # 2. Daty
        dates = re.findall(r"\b(\d{4}[-/]\d{2}[-/]\d{2})\b", text)
        if not dates:
            dot_dates = re.findall(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", text)
            dates = [f"{d[2]}-{d[1]}-{d[0]}" for d in dot_dates]

        data_wyst = dates[0] if dates else f"{rok}-{miesiac.zfill(2)}-01"
        data_sprz = dates[1] if len(dates) > 1 else data_wyst

        # 3. Kontrahent NIP (10 cyfr różniących się od NIP podatnika)
        nipy = re.findall(r"\b(\d{10})\b", text)
        other_nip = "0000000000"
        for n in nipy:
            if n != profile.nip:
                other_nip = n
                break

        # 4. Nazwa kontrahenta
        if invoice_type == InvoiceType.SPRZEDAZ:
            seller = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            buyer_name = "Klient Zewnętrzny"
            buyer_m = re.search(r"(?:nabywca|buyer|klient|odbiorca)[\s:]*([^\n\r]+)", text, re.IGNORECASE)
            if buyer_m:
                candidate = buyer_m.group(1).strip()
                if len(candidate) > 2:
                    buyer_name = candidate[:60]
            buyer = InvoiceParty(nip=other_nip, nazwa=buyer_name, kraj="PL")
        else:
            seller_name = "Kontrahent Zewnętrzny"
            sprz_m = re.search(r"(?:sprzedawca|seller|wystawca)[\s:]*([^\n\r]+)", text, re.IGNORECASE)
            if sprz_m:
                candidate = sprz_m.group(1).strip()
                if len(candidate) > 2:
                    seller_name = candidate[:60]
            seller = InvoiceParty(nip=other_nip, nazwa=seller_name, kraj="PL")
            buyer = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")

        # 5. Kwoty
        brutto_m = re.search(r"(?:brutto|do zapłaty|razem brutto|total)[\s:]*([0-9\s,\.]+\s*(?:zł|pln|eur|usd)?)", text, re.IGNORECASE)
        netto_m = re.search(r"(?:netto|razem netto)[\s:]*([0-9\s,\.]+\s*(?:zł|pln|eur|usd)?)", text, re.IGNORECASE)
        vat_m = re.search(r"(?:vat|podatek vat)[\s:]*([0-9\s,\.]+\s*(?:zł|pln|eur|usd)?)", text, re.IGNORECASE)

        brutto = _clean_amount(brutto_m.group(1)) if brutto_m else Decimal("0.00")
        netto = _clean_amount(netto_m.group(1)) if netto_m else Decimal("0.00")
        vat = _clean_amount(vat_m.group(1)) if vat_m else Decimal("0.00")

        if brutto > 0 and netto == 0:
            if vat > 0:
                netto = brutto - vat
            else:
                netto = (brutto / Decimal("1.23")).quantize(Decimal("0.01"))
                vat = brutto - netto
        elif netto > 0 and brutto == 0:
            if vat > 0:
                brutto = netto + vat
            else:
                vat = (netto * Decimal("0.23")).quantize(Decimal("0.01"))
                brutto = netto + vat

        item_desc = f"Sprzedaż z pliku {filename}" if invoice_type == InvoiceType.SPRZEDAZ else f"Zakup z pliku {filename}"
        pozycje = [
            InvoiceItem(
                opis=item_desc,
                wartosc_netto=netto,
                stawka_vat="23" if vat > 0 else "0",
                kwota_vat=vat,
                wartosc_brutto=brutto,
            )
        ]

        return Invoice(
            numer=numer,
            data_wystawienia=data_wyst,
            data_sprzedazy=data_sprz,
            sprzedawca=seller,
            nabywca=buyer,
            typ=invoice_type,
            suma_netto=netto,
            suma_vat=vat,
            suma_brutto=brutto,
            waluta="PLN",
            pozycje=pozycje,
            zrodlo="NON_KSEF",
            plik_zrodlowy=filename,
        )

    @classmethod
    def _extract_from_pdf(
        cls,
        pdf_path: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Invoice:
        """Konwertuje PDF na tekst za pomocą pdftotext i dokonuje ekstrakcji."""
        text = ""
        try:
            res = subprocess.run(
                ["/usr/bin/pdftotext", "-layout", str(pdf_path), "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            if res.returncode == 0:
                text = res.stdout
        except Exception:
            text = ""

        if text.strip():
            return cls._extract_from_text(text, profile, pdf_path.name, rok, miesiac, invoice_type=invoice_type)

        return cls._create_fallback_invoice(pdf_path, profile, rok, miesiac, invoice_type=invoice_type)

    @classmethod
    def _create_fallback_invoice(
        cls,
        file_path: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Invoice:
        """Tworzy szkic faktury, gdy automatyczne rozpoznanie zawartości nie powiodło się."""
        if invoice_type == InvoiceType.SPRZEDAZ:
            seller = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            buyer = InvoiceParty(nip="0000000000", nazwa=f"Klient ({file_path.name})", kraj="PL")
            item_desc = f"Sprzedaż z pliku {file_path.name} (do weryfikacji kwot)"
        else:
            seller = InvoiceParty(nip="0000000000", nazwa=f"Sprzedawca ({file_path.name})", kraj="PL")
            buyer = InvoiceParty(nip=profile.nip, nazwa=profile.nazwa, kraj="PL")
            item_desc = f"Dokument z pliku {file_path.name} (do weryfikacji kwot)"

        return Invoice(
            numer=file_path.stem,
            data_wystawienia=f"{rok}-{miesiac.zfill(2)}-01",
            data_sprzedazy=f"{rok}-{miesiac.zfill(2)}-01",
            sprzedawca=seller,
            nabywca=buyer,
            typ=invoice_type,
            suma_netto=Decimal("0.00"),
            suma_vat=Decimal("0.00"),
            suma_brutto=Decimal("0.00"),
            pozycje=[
                InvoiceItem(
                    opis=item_desc,
                    wartosc_netto=Decimal("0.00"),
                    stawka_vat="23",
                    kwota_vat=Decimal("0.00"),
                    wartosc_brutto=Decimal("0.00"),
                )
            ],
            zrodlo="NON_KSEF",
            plik_zrodlowy=file_path.name,
        )

    @classmethod
    def extract_all(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        typ: Optional[InvoiceType] = None,
        force: bool = False
    ) -> List[Path]:
        """
        Skanuje foldery non-ksef-raw dla danego miesiąca, ekstrahuje nowe/zmienione pliki
        i zapisuje je w non-ksef-extracted/{stem}.json.
        Obsługuje zarówno sprzedaż, jak i koszty (lub wybrany typ, gdy typ is not None).
        """
        types_to_process = [typ] if typ else [InvoiceType.KOSZT, InvoiceType.SPRZEDAZ]
        extracted_paths: List[Path] = []

        for curr_type in types_to_process:
            raw_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=curr_type)
            extracted_dir = InvoiceStorage.get_non_ksef_extracted_dir(profile, rok, miesiac, typ=curr_type)

            if not raw_dir.exists():
                continue

            raw_files = [f for f in raw_dir.iterdir() if f.is_file() and not f.name.startswith(".")]

            for raw_file in raw_files:
                target_json = extracted_dir / f"{raw_file.stem}.json"
                # Sprawdź cache / czas modyfikacji
                if not force and target_json.exists():
                    if target_json.stat().st_mtime >= raw_file.stat().st_mtime:
                        extracted_paths.append(target_json)
                        continue

                out = cls.extract_file(
                    raw_path=raw_file,
                    profile=profile,
                    target_dir=extracted_dir,
                    rok=str(rok),
                    miesiac=str(miesiac).zfill(2),
                    invoice_type=curr_type,
                )
                if out:
                    extracted_paths.append(out)

        return extracted_paths
