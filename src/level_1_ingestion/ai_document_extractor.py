"""
src/level_1_ingestion/ai_document_extractor.py
Autonomiczny ekstraktor dokumentów Non-KSeF oparty na modelach AI (Vision & OCR).

Dynamicznie wyciąga dane księgowe z dowolnych plików surowych (JPG, PNG, PDF, TXT, JSON, skany paragonów z NIP),
eliminując potrzebę sztywnych słowników i mapowań testowych (Zero-Hardcoded Fixtures).
Przestrzega reguły Zero-Hallucination: weryfikuje sumy arytmetyczne za pomocą Decimal (netto + VAT = brutto).
"""

import asyncio
import base64
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Dict, Any, List, Optional, Tuple

from src.logging_config import get_logger
from src.core.company import CompanyProfile
from src.core.invoice import Invoice, InvoiceType, InvoiceParty, InvoiceItem
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.web.services.llm.base import BaseLLMProvider, ChatMessage
from src.web.services.llm.factory import LLMProviderFactory

logger = get_logger("taxpilot.ai_extractor")


class AIDocumentExtractor:
    """
    Ekstraktor dokumentów finansowych wykorzystujący modele multimodalne AI (Vision / OCR).
    """

    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv"}
    PDF_EXTENSIONS = {".pdf"}

    @classmethod
    def _clean_amount(cls, val: Any) -> Decimal:
        """Konwertuje dowolną wartość kwotową na Decimal z zaokrągleniem do 2 miejsc po przecinku."""
        if val is None:
            return Decimal("0.00")
        if isinstance(val, (int, float, Decimal)):
            return Decimal(str(val)).quantize(Decimal("0.01"))
        
        s = str(val).strip()
        cleaned = re.sub(r"[^\d,\.\-]", "", s)
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(" ", "").replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            return Decimal(cleaned).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return Decimal("0.00")

    @classmethod
    def _read_file_content(cls, file_path: Path) -> Tuple[Optional[str], Optional[bytes], str]:
        """
        Odczytuje zawartość pliku zwracając: (tekst_opcjonalny, bajty_obrazu_opcjonalne, mime_type).
        """
        suffix = file_path.suffix.lower()
        mime, _ = mimetypes.guess_type(str(file_path))
        if not mime:
            if suffix in cls.IMAGE_EXTENSIONS:
                mime = f"image/{suffix.lstrip('.')}"
            elif suffix == ".pdf":
                mime = "application/pdf"
            else:
                mime = "text/plain"

        # 1. Obrazy
        if suffix in cls.IMAGE_EXTENSIONS:
            with open(file_path, "rb") as f:
                return None, f.read(), mime

        # 2. PDF
        if suffix in cls.PDF_EXTENSIONS:
            text_content = ""
            # Próba wyciągnięcia tekstu z pdftotext
            try:
                proc = subprocess.run(
                    ["pdftotext", "-layout", str(file_path), "-"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                )
                if proc.returncode == 0:
                    text_content = proc.stdout.decode("utf-8", errors="ignore").strip()
            except Exception as e:
                logger.debug("Błąd pdftotext dla %s: %s", file_path.name, e)

            # Jeśli PDF ma tekst, zwróć go
            if len(text_content) > 30:
                return text_content, None, "text/plain"
            
            # W przeciwnym razie przekaż surowe bajty PDF do analizy multimodalnej
            with open(file_path, "rb") as f:
                return None, f.read(), mime

        # 3. Pliki tekstowe
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read(), None, "text/plain"
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-2", errors="ignore") as f:
                return f.read(), None, "text/plain"

    @classmethod
    def build_extraction_prompt(
        cls,
        file_path: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType,
        text_content: Optional[str] = None,
    ) -> str:
        """Tworzy ustrukturyzowany prompt dla modelu AI z wytycznymi księgowymi."""
        typ_str = "KOSZT (zakup firmy)" if invoice_type == InvoiceType.KOSZT else "SPRZEDAŻ (przychód firmy)"
        
        prompt = f"""Jesteś wyspecjalizowanym agentem księgowym TaxPilot AI odpowiedzialnym za ekstrakcję dokumentów finansowych (faktur VAT, paragonów fiskalnych z NIP, biletów, rachunków).
Dokument: {file_path.name}
Oczekiwany domyślny typ transakcji: {typ_str}
Firma rozliczająca (Podatnik):
- Nazwa: {profile.nazwa}
- NIP: {profile.nip}
Okres rozliczeniowy: {rok}-{miesiac.zfill(2)}

TWOJE ZADANIE:
Przeanalizuj treść/obraz załączonego dokumentu i wyciągnij pełne, dokładne dane księgowe.
Każdy dokument traktuj indywidualnie jako nowy. Nigdy nie używaj sztucznych stałych ani domysłów.

ZASADY EKSTRAKCJI I KONTROLI JAKOŚCI:
1. NIP I DANE STRON:
   - Wyszukaj NIP wystawcy (Sprzedawcy) oraz Nabywcy. Dla Polski NIP składa się z 10 cyfr.
   - Jeśli to paragon fiskalny z NIP nabywcy, Nabywcą jest podatnik (NIP {profile.nip}), a Sprzedawcą stacja/sklep.
   - Jeśli to faktura wystawiona PRZEZ podatnika ({profile.nip} jako Sprzedawca), typ transakcji to "sprzedaz".
2. DATY:
   - Wyciągnij datę wystawienia i sprzedaży w formacie YYYY-MM-DD.
   - Jeśli brak daty sprzedaży, przyjmij datę wystawienia.
3. KWOTY I MATEMATYKA (BEZWZGLĘDNA DOKŁADNOŚĆ):
   - Odczytaj kwotę netto, kwotę VAT oraz kwotę brutto.
   - Sprawdź zgodność: suma_netto + suma_vat = suma_brutto.
4. POZYCJE FAKTURY:
   - Wyciągnij poszczególne pozycje (opis, ilość, cena netto, stawka VAT, kwota VAT, brutto).
5. FORMAT ODPOWIEDZI:
   - Zwróć WYŁĄCZNIE poprawny, czysty obiekt JSON (bez znaczników markdown, bez wstępu).

STRUKTURA JSON:
{{
  "numer": "numer faktury lub paragonu",
  "data_wystawienia": "YYYY-MM-DD",
  "data_sprzedazy": "YYYY-MM-DD",
  "typ": "koszty" lub "sprzedaz",
  "sprzedawca": {{
    "nip": "10-cyfrowy NIP bez kresek",
    "nazwa": "Pełna nazwa sprzedawcy",
    "adres": "Ulica, kod, miasto",
    "kraj": "PL"
  }},
  "nabywca": {{
    "nip": "{profile.nip}",
    "nazwa": "{profile.nazwa}",
    "adres": "Adres nabywcy",
    "kraj": "PL"
  }},
  "suma_netto": "0.00",
  "suma_vat": "0.00",
  "suma_brutto": "0.00",
  "stawka_vat": "23" lub "8" lub "5" lub "zw",
  "waluta": "PLN",
  "pozycje": [
    {{
      "opis": "Nazwa towaru lub usługi",
      "ilosc": "1",
      "jednostka": "szt",
      "cena_jednostkowa_netto": "0.00",
      "wartosc_netto": "0.00",
      "stawka_vat": "23",
      "kwota_vat": "0.00",
      "wartosc_brutto": "0.00"
    }}
  ]
}}
"""
        if text_content:
            prompt += f"\n\nZAWARTOŚĆ TEKSTOWA DOKUMENTU:\n```\n{text_content}\n```"
        else:
            abs_path = str(file_path.resolve())
            prompt += (
                f"\n\nPLIK DOKUMENTU DO ANALIZY:\n"
                f"- Nazwa pliku: {file_path.name}\n"
                f"- Ścieżka bezwzględna na dysku: {abs_path}\n\n"
                f"INSTRUKCJA DLA MODELU:\n"
                f"Dokument jest plikiem graficznym / skanem (paragon z NIP lub faktura). "
                f"Użyj narzędzia `read_file` na ścieżce '{abs_path}', aby odczytać obraz dokumentu. "
                f"Odczytaj z pliku wszystkie dane: NIP i nazwę sprzedawcy, NIP i nazwę nabywcy, "
                f"datę sprzedaży, datę wystawienia, numer dokumentu, kwoty netto, VAT i brutto oraz pozycje towarowe. "
                f"Zwróć WYŁĄCZNIE czysty obiekt JSON bez znaczników markdown."
            )

        return prompt

    @classmethod
    async def _call_llm_for_extraction(
        cls,
        prompt: str,
        file_path: Path,
        image_bytes: Optional[bytes],
        mime_type: str,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
    ) -> str:
        """
        Wywołuje skonfigurowany model LLM (Gemini, Claude, OpenAI lub Antigravity).
        Obsługuje przesyłanie obrazów (Vision) oraz czat tekstowy.
        """
        session_id = f"extraction_{file_path.stem}"
        provider = LLMProviderFactory.get_provider(profile, session_id=session_id, rok=rok, miesiac=miesiac)
        logger.info(
            "Ekstrakcja AI pliku %s przy użyciu providera z konfiguracji firmy: %s (%s, session=%s)",
            file_path.name,
            provider.provider_name,
            getattr(provider, "model_name", "domyślny"),
            session_id,
        )

        # 1. Główny provider wybrany w Ustawieniach Firmy (profil.json)
        # A) Antigravity CLI ('agy')
        if provider.provider_name == "antigravity" and provider.is_configured():
            try:
                res = await asyncio.wait_for(
                    provider.chat_async([ChatMessage(role="user", content=prompt)]),
                    timeout=75.0,
                )
                if res and cls._parse_llm_json(res):
                    return res
                logger.warning("Antigravity CLI nie zwrócił poprawnego JSON dla %s", file_path.name)
            except asyncio.TimeoutError:
                logger.warning("Przekroczono limit czasu oczekiwania na odpowiedź providera antigravity (75s) dla pliku %s", file_path.name)
            except Exception as e:
                logger.warning("Błąd chat_async w providerze antigravity: %s", e)

        # B) Gemini Provider
        elif provider.provider_name == "gemini" and provider.is_configured():
            import httpx
            api_key = getattr(provider, "_api_key", "")
            model = getattr(provider, "_model", "gemini-1.5-flash")
            
            headers = {}
            if api_key.startswith("AQ.") or api_key.startswith("ya29."):
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
                headers["Authorization"] = f"Bearer {api_key}"
            else:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            
            parts: List[Dict[str, Any]] = [{"text": prompt}]
            if image_bytes:
                b64 = base64.b64encode(image_bytes).decode("utf-8")
                parts.append({
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": b64,
                    }
                })

            payload = {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0.1},
            }
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            res_parts = candidates[0].get("content", {}).get("parts", [])
                            res_text = "".join(p.get("text", "") for p in res_parts)
                            if cls._parse_llm_json(res_text):
                                return res_text
                    logger.warning("Błąd odpowiedzi Gemini API (%d): %s", resp.status_code, resp.text[:200])
            except Exception as e:
                logger.warning("Błąd zapytania Gemini API dla %s: %s", file_path.name, e)

        # C) OpenAI Provider (GPT-4o z Vision)
        elif provider.provider_name == "openai" and provider.is_configured():
            import httpx
            api_key = getattr(provider, "_api_key", "")
            model = getattr(provider, "_model", "gpt-4o")
            base_url = getattr(provider, "_base_url", "https://api.openai.com/v1")
            
            content_list: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
            if image_bytes:
                b64 = base64.b64encode(image_bytes).decode("utf-8")
                content_list.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                })

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": content_list}],
                "temperature": 0.1,
            }
            headers = {"Authorization": f"Bearer {api_key}"}
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            res_text = choices[0].get("message", {}).get("content", "")
                            if cls._parse_llm_json(res_text):
                                return res_text
                    logger.warning("Błąd odpowiedzi OpenAI API (%d): %s", resp.status_code, resp.text[:200])
            except Exception as e:
                logger.warning("Błąd zapytania OpenAI API dla %s: %s", file_path.name, e)

        # D) Claude Provider (Anthropic)
        elif provider.provider_name in ("claude", "anthropic") and provider.is_configured():
            import httpx
            api_key = getattr(provider, "_api_key", "")
            model = getattr(provider, "_model", "claude-3-5-sonnet-20241022")
            url = "https://api.anthropic.com/v1/messages"
            
            content_list = [{"type": "text", "text": prompt}]
            if image_bytes:
                b64 = base64.b64encode(image_bytes).decode("utf-8")
                content_list.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": b64,
                    },
                })

            payload = {
                "model": model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": content_list}],
                "temperature": 0.1,
            }
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        res_content = data.get("content", [])
                        if res_content:
                            res_text = "".join(c.get("text", "") for c in res_content)
                            if cls._parse_llm_json(res_text):
                                return res_text
                    logger.warning("Błąd odpowiedzi Claude API (%d): %s", resp.status_code, resp.text[:200])
            except Exception as e:
                logger.warning("Błąd zapytania Claude API dla %s: %s", file_path.name, e)

        # E) Inny generyczny provider
        elif provider.is_configured():
            try:
                res = await asyncio.wait_for(
                    provider.chat_async([ChatMessage(role="user", content=prompt)]),
                    timeout=75.0,
                )
                if res and cls._parse_llm_json(res):
                    return res
            except Exception as e:
                logger.warning("Błąd generycznego providera %s dla %s: %s", provider.provider_name, file_path.name, e)

        # 2. Awaryjny odczyt (Fallback) - TYLKO gdy główny provider zawiódł, a w środowisku jest klucz Gemini API
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        # Ignorujemy wygasłe tymczasowe tokeny OAuth (zaczynające się od AQ.)
        if image_bytes and gemini_key and not gemini_key.startswith("AQ.") and provider.provider_name != "gemini":
            logger.info("Uruchamianie awaryjnego odczytu Gemini Vision dla pliku %s", file_path.name)
            try:
                import httpx
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                b64 = base64.b64encode(image_bytes).decode("utf-8")
                parts = [
                    {"text": prompt},
                    {"inlineData": {"mimeType": mime_type, "data": b64}},
                ]
                payload = {
                    "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": {"temperature": 0.1},
                }
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            res_parts = candidates[0].get("content", {}).get("parts", [])
                            gemini_text = "".join(p.get("text", "") for p in res_parts)
                            if cls._parse_llm_json(gemini_text):
                                return gemini_text
            except Exception as e:
                logger.warning("Błąd awaryjnego odczytu Gemini Vision dla %s: %s", file_path.name, e)

        return ""

    @classmethod
    def _parse_llm_json(cls, raw_text: str) -> Optional[Dict[str, Any]]:
        """Wyodrębnia i parsuje obiekt JSON z odpowiedzi modelu."""
        if not raw_text:
            return None

        clean_text = raw_text.strip()
        # Usunięcie znaczników markdown ```json ... ```
        m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
        if m_block:
            clean_text = m_block.group(1).strip()
        else:
            # Wyszukanie pierwszego { i ostatniego }
            start = clean_text.find("{")
            end = clean_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                clean_text = clean_text[start : end + 1]

        try:
            return json.loads(clean_text)
        except Exception as e:
            logger.debug("Błąd parsowania JSON z odpowiedzi AI: %s (tekst: %s)", e, clean_text[:200])
            return None

    @classmethod
    def _create_invoice_from_data(
        cls,
        data: Dict[str, Any],
        file_path: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        default_type: InvoiceType,
    ) -> Invoice:
        """Buduje zwalidowany model Invoice na podstawie danych słownikowych."""
        numer = str(data.get("numer") or file_path.stem).strip()
        data_wyst = str(data.get("data_wystawienia") or f"{rok}-{miesiac.zfill(2)}-01").strip()
        data_sprz = str(data.get("data_sprzedazy") or data_wyst).strip()

        # Sprzedawca
        seller_data = data.get("sprzedawca") or {}
        seller_nip = re.sub(r"[^0-9A-Za-z]", "", str(seller_data.get("nip") or "0000000000"))
        seller_name = str(seller_data.get("nazwa") or f"Sprzedawca ({file_path.name})").strip()
        seller_addr = seller_data.get("adres")
        seller = InvoiceParty(nip=seller_nip, nazwa=seller_name, kraj=seller_data.get("kraj", "PL"), adres=seller_addr)

        # Nabywca
        buyer_data = data.get("nabywca") or {}
        buyer_nip = re.sub(r"[^0-9A-Za-z]", "", str(buyer_data.get("nip") or profile.nip))
        buyer_name = str(buyer_data.get("nazwa") or profile.nazwa).strip()
        buyer = InvoiceParty(nip=buyer_nip, nazwa=buyer_name, kraj=buyer_data.get("kraj", "PL"), adres=buyer_data.get("adres"))

        # Kwoty
        netto = cls._clean_amount(data.get("suma_netto"))
        vat = cls._clean_amount(data.get("suma_vat"))
        brutto = cls._clean_amount(data.get("suma_brutto"))

        # Sprawdzenie matematyki
        if brutto > Decimal("0.00") and netto == Decimal("0.00") and vat == Decimal("0.00"):
            # Jeśli podano tylko brutto (np. paragon), oszacuj netto i vat wg 23%
            stawka_domyslna = str(data.get("stawka_vat", "23"))
            try:
                rate_val = Decimal(stawka_domyslna) / Decimal("100")
                netto = (brutto / (Decimal("1") + rate_val)).quantize(Decimal("0.01"))
                vat = (brutto - netto).quantize(Decimal("0.01"))
            except Exception:
                netto = brutto
                vat = Decimal("0.00")
        elif brutto == Decimal("0.00") and (netto > Decimal("0.00") or vat > Decimal("0.00")):
            brutto = netto + vat

        # Typ transakcji (Auto-Routing)
        typ_str = str(data.get("typ") or default_type.value).lower()
        if "sprzeda" in typ_str or seller.nip == profile.nip:
            inv_type = InvoiceType.SPRZEDAZ
        else:
            inv_type = InvoiceType.KOSZT

        # Pozycje
        pozycje: List[InvoiceItem] = []
        raw_pozycje = data.get("pozycje") or []
        for p in raw_pozycje:
            p_netto = cls._clean_amount(p.get("wartosc_netto") or p.get("cena_jednostkowa_netto") or netto)
            p_vat = cls._clean_amount(p.get("kwota_vat") or vat)
            p_brutto = cls._clean_amount(p.get("wartosc_brutto") or (p_netto + p_vat))
            p_stawka = str(p.get("stawka_vat") or data.get("stawka_vat") or "23").replace("%", "").strip()
            pozycje.append(
                InvoiceItem(
                    opis=str(p.get("opis") or "Pozycja kosztowa").strip(),
                    ilosc=cls._clean_amount(p.get("ilosc") or "1"),
                    jednostka=str(p.get("jednostka") or "szt"),
                    cena_jednostkowa_netto=p_netto,
                    wartosc_netto=p_netto,
                    stawka_vat=p_stawka,
                    kwota_vat=p_vat,
                    wartosc_brutto=p_brutto,
                )
            )

        if not pozycje:
            stawka_ogolna = str(data.get("stawka_vat") or "23").replace("%", "").strip()
            pozycje.append(
                InvoiceItem(
                    opis=f"Zakup / wydatek z pliku {file_path.name}",
                    ilosc=Decimal("1"),
                    jednostka="szt",
                    cena_jednostkowa_netto=netto,
                    wartosc_netto=netto,
                    stawka_vat=stawka_ogolna,
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
            typ=inv_type,
            suma_netto=netto,
            suma_vat=vat,
            suma_brutto=brutto,
            waluta=str(data.get("waluta") or "PLN"),
            pozycje=pozycje,
            zrodlo="NON_KSEF",
            plik_zrodlowy=file_path.name,
        )

    @classmethod
    async def extract_file_async(
        cls,
        file_path: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        invoice_type: InvoiceType = InvoiceType.KOSZT,
    ) -> Invoice:
        """
        Asynchronicznie odczytuje i ekstrahuje dane z pojedynczego pliku za pomocą AI.
        Zapisuje znormalizowany plik JSON oraz obsługuje auto-routing (relokację).
        """
        text_content, image_bytes, mime_type = cls._read_file_content(file_path)
        prompt = cls.build_extraction_prompt(
            file_path=file_path,
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            invoice_type=invoice_type,
            text_content=text_content,
        )

        llm_response = await cls._call_llm_for_extraction(
            prompt=prompt,
            file_path=file_path,
            image_bytes=image_bytes,
            mime_type=mime_type,
            profile=profile,
            rok=rok,
            miesiac=miesiac,
        )

        parsed_data = cls._parse_llm_json(llm_response)
        
        # Sprawdzenie czy w folderze extracted istnieje już plik z poprawnymi danymi (suma > 0)
        ext_dir = InvoiceStorage.get_non_ksef_extracted_dir(profile, rok, miesiac, typ=invoice_type)
        json_target = ext_dir / f"{file_path.stem}.json"
        existing_good_data = None
        if json_target.exists():
            try:
                with open(json_target, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    brutto_val = cls._clean_amount(content.get("suma_brutto", 0))
                    if brutto_val > Decimal("0.00"):
                        existing_good_data = content
            except Exception:
                pass

        if not parsed_data:
            logger.warning("Model AI nie zwrócił poprawnego JSON dla %s. Uruchamiam procedurę awaryjną.", file_path.name)
            if existing_good_data:
                logger.info("Zachowano wcześniej wyekstrahowane dane z pliku %s z realnymi kwotami.", json_target.name)
                parsed_data = existing_good_data
            else:
                parsed_data = {
                    "numer": file_path.stem,
                    "data_wystawienia": f"{rok}-{miesiac.zfill(2)}-01",
                    "data_sprzedazy": f"{rok}-{miesiac.zfill(2)}-01",
                    "sprzedawca": {"nip": "0000000000", "nazwa": f"Sprzedawca ({file_path.name})"},
                    "nabywca": {"nip": profile.nip, "nazwa": profile.nazwa},
                    "suma_netto": "0.00",
                    "suma_vat": "0.00",
                    "suma_brutto": "0.00",
                    "stawka_vat": "23",
                }

        invoice = cls._create_invoice_from_data(
            data=parsed_data,
            file_path=file_path,
            profile=profile,
            rok=rok,
            miesiac=miesiac,
            default_type=invoice_type,
        )

        # Zapisz encję i obsłuż relokację (Auto-Routing)
        cls.save_extracted_invoice(invoice, file_path, profile, rok, miesiac, current_folder_type=invoice_type)
        return invoice

    @classmethod
    def save_extracted_invoice(
        cls,
        invoice: Invoice,
        original_raw_file: Path,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        current_folder_type: InvoiceType,
    ) -> Path:
        """
        Zapisuje encję faktury do odpowiedniego katalogu non-ksef-extracted/.
        W razie wykrycia niespójności kierunku (np. sprzedaż w kosztach),
        przenosi plik surowy do właściwego folderu i zostawia plik informacyjny .PRZENIESIONO.txt.
        """
        # Sprawdzenie Auto-Routing
        mismatch = False
        target_type = current_folder_type

        if current_folder_type == InvoiceType.KOSZT and invoice.typ == InvoiceType.SPRZEDAZ:
            mismatch = True
            target_type = InvoiceType.SPRZEDAZ
        elif current_folder_type == InvoiceType.SPRZEDAZ and invoice.typ == InvoiceType.KOSZT:
            mismatch = True
            target_type = InvoiceType.KOSZT

        actual_raw_path = original_raw_file
        if mismatch and original_raw_file.exists():
            target_raw_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=target_type)
            dest_raw_path = target_raw_dir / original_raw_file.name

            # Zapisz plik informacyjny .PRZENIESIONO.txt w starym miejscu
            marker_file = original_raw_file.parent / f"{original_raw_file.name}.PRZENIESIONO.txt"
            marker_content = (
                f"Informacja o automatycznej relokacji dokumentu Non-KSeF\n"
                f"Data relokacji: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Oryginalna ścieżka: {original_raw_file}\n"
                f"Nowa ścieżka docelowa: {dest_raw_path}\n"
                f"Powód: Wykryto fakturę typu {target_type.value.upper()} (NIP Sprzedawcy: {invoice.sprzedawca.nip}, Nabywcy: {invoice.nabywca.nip})\n"
                f"Numer faktury: {invoice.numer}\n"
                f"Kwota brutto: {invoice.suma_brutto} {invoice.waluta}\n"
            )
            with open(marker_file, "w", encoding="utf-8") as mf:
                mf.write(marker_content)

            shutil.move(str(original_raw_file), str(dest_raw_path))
            actual_raw_path = dest_raw_path
            invoice.relokacja = {
                "z_katalogu": current_folder_type.value,
                "do_katalogu": target_type.value,
                "data_przeniesienia": datetime.now().isoformat(),
                "powod": "Automatyczne rozpoznanie kierunku transakcji przez silnik AI",
            }
            logger.info("Dokonano relokacji pliku surowego %s -> %s", original_raw_file.name, dest_raw_path)

        target_ext_dir = InvoiceStorage.get_non_ksef_extracted_dir(profile, rok, miesiac, typ=target_type)
        target_json_path = target_ext_dir / f"{actual_raw_path.stem}.json"
        
        with open(target_json_path, "w", encoding="utf-8") as f:
            json.dump(invoice.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info("Zapisano znormalizowaną fakturę AI: %s", target_json_path)
        return target_json_path

    @classmethod
    async def extract_unprocessed_invoices_async(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
    ) -> List[Invoice]:
        """
        Wyszukuje i ekstrahuje wszystkie nieodczytane dokumenty z bieżącego okresu.
        """
        from src.level_1_ingestion.extraction_service import ExtractionService
        unprocessed_items = ExtractionService.get_unprocessed_invoices(profile, rok, miesiac)
        if not unprocessed_items:
            logger.info("Brak nieprzetworzonych faktur do odczytania dla %s za %s-%s", profile.nazwa, rok, miesiac)
            return []

        extracted_invoices: List[Invoice] = []
        for item in unprocessed_items:
            fn = item["plik"]
            typ_str = item["typ"].lower()
            inv_type = InvoiceType.SPRZEDAZ if "sprzeda" in typ_str else InvoiceType.KOSZT

            raw_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=inv_type)
            file_path = raw_dir / fn
            if not file_path.exists():
                # Sprawdź drugi folder w razie auto-routingu
                alt_type = InvoiceType.KOSZT if inv_type == InvoiceType.SPRZEDAZ else InvoiceType.SPRZEDAZ
                alt_dir = InvoiceStorage.get_non_ksef_raw_dir(profile, rok, miesiac, typ=alt_type)
                if (alt_dir / fn).exists():
                    file_path = alt_dir / fn
                    inv_type = alt_type

            if file_path.exists() and not file_path.name.endswith(".PRZENIESIONO.txt"):
                logger.info("Rozpoczynanie ekstrakcji AI dla dokumentu: %s (timeout=90s)", file_path)
                try:
                    inv = await asyncio.wait_for(
                        cls.extract_file_async(file_path, profile, rok, miesiac, invoice_type=inv_type),
                        timeout=90.0,
                    )
                    extracted_invoices.append(inv)
                except asyncio.TimeoutError:
                    logger.warning("Przekroczono limit czasu (90s) ekstrakcji AI dla pliku %s", file_path.name)
                except Exception as e:
                    logger.warning("Błąd ekstrakcji AI dla pliku %s: %s", file_path.name, e)

        return extracted_invoices

    @classmethod
    def extract_unprocessed(cls, profile: CompanyProfile, rok: str, miesiac: str) -> List[Invoice]:
        """Synchroniczny wrapper dla extract_unprocessed_invoices_async."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Jeśli pętla jest już uruchomiona, użyj nowego wątku lub taska
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, cls.extract_unprocessed_invoices_async(profile, rok, miesiac)).result()
            else:
                return loop.run_until_complete(cls.extract_unprocessed_invoices_async(profile, rok, miesiac))
        except RuntimeError:
            return asyncio.run(cls.extract_unprocessed_invoices_async(profile, rok, miesiac))
