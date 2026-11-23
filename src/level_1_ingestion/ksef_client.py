"""
Klient API Krajowego Systemu e-Faktur (KSeF 2.0).
Obsługuje środowiska PROD i TEST z asynchronicznym uwierzytelnieniem tokenem (RSA-OAEP SHA-256)
oraz automatyczną synchronizacją i zapisem faktur w archiwum firmy.
"""

import base64
import calendar
import json
import os
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from src.config import DEFAULT_KSEF_ENV, KSEF_URLS
from src.core.company import CompanyProfile
from src.core.invoice import Invoice
from src.core.io import atomic_write_json
from src.level_1_ingestion.invoice_storage import InvoiceStorage
from src.level_1_ingestion.ksef_parser import KSeFParser
from src.level_1_ingestion.xades_signer import parse_certificate_info, sign_ksef_auth_token_request


class KSeFClient:
    """
    Oficjalny klient KSeF 2.0 dla profilu podatnika.
    """

    def __init__(self, profile: CompanyProfile, environment: Optional[str] = None):
        self.profile = profile
        self.env = (environment or profile.ksef.srodowisko or DEFAULT_KSEF_ENV).upper()
        self.base_url = KSEF_URLS.get(self.env, KSEF_URLS["PROD"])
        self.access_token: Optional[str] = None
        self.access_token_valid_until: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TaxPilot-AI/1.0)"})

    def get_auth_token(self) -> Optional[str]:
        """
        Pobiera token KSeF bezpośrednio z profilu firmy (firmy/{nazwa}/profil.json).
        W razie potrzeby jako fallback sprawdza zmienne środowiskowe.
        """
        if self.profile.ksef.token:
            return self.profile.ksef.token.strip()

        env_var_name = self.profile.ksef.token_env_var or f"KSEF_TOKEN_{self.profile.nip}"
        return os.getenv(env_var_name) or os.getenv("KSEF_TOKEN")

    def get_auth_token_from_env(self) -> Optional[str]:
        """Metoda pomocnicza dla wstecznej kompatybilności."""
        return self.get_auth_token()

    def is_certificate_configured(self) -> bool:
        """Sprawdza, czy skonfigurowany jest certyfikat i klucz uwierzytelniający KSeF."""
        return self.profile.has_ksef_certificate()

    def is_auth_configured(self) -> bool:
        """Sprawdza czy skonfigurowana jest wybrana lub jakakolwiek metoda uwierzytelnienia (certyfikat / token)."""
        auth_type = (self.profile.ksef.auth_type or "token").lower()
        if auth_type == "certyfikat":
            return self.is_certificate_configured()
        elif auth_type == "token":
            return self.is_token_configured()
        return self.is_certificate_configured() or self.is_token_configured()

    def is_token_configured(self) -> bool:
        """Sprawdza poprawność konfiguracji uwierzytelnienia (obsługuje certyfikat oraz token)."""
        auth_type = (self.profile.ksef.auth_type or "token").lower()
        if auth_type == "certyfikat":
            return self.is_certificate_configured()
        token = self.get_auth_token()
        return bool(token and token != "twoj_tajny_token_ksef_tutaj")

    def set_auth_token(self, token: str, srodowisko: Optional[str] = None) -> None:
        """Zapisuje token KSeF bezpośrednio w pliku profil.json firmy."""
        self.profile.set_ksef_token(token, srodowisko, auth_type="token")

    @classmethod
    def get_sync_history_file(cls, profile: CompanyProfile) -> Path:
        """Zwraca ścieżkę do pliku historii synchronizacji KSeF firmy."""
        return profile.katalog_firmy / "ksef_sync_history.json"

    @classmethod
    def load_sync_history(cls, profile: CompanyProfile) -> List[Dict[str, Any]]:
        """Wczytuje historię synchronizacji KSeF dla firmy."""
        file_path = cls.get_sync_history_file(profile)
        if not file_path.exists():
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    @classmethod
    def record_sync_attempt(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        status: str,
        srodowisko: str,
        nowe_sprzedaz: int = 0,
        nowe_kosztow: int = 0,
        lacznie_sprzedaz: int = 0,
        lacznie_kosztow: int = 0,
        komunikat: str = "",
    ) -> Dict[str, Any]:
        """Zapisuje wynik próby synchronizacji KSeF w historii firmy."""
        file_path = cls.get_sync_history_file(profile)
        history = cls.load_sync_history(profile)
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rok": str(rok),
            "miesiac": str(miesiac).zfill(2),
            "status": status,
            "srodowisko": srodowisko,
            "nowe_sprzedaz": nowe_sprzedaz,
            "nowe_kosztow": nowe_kosztow,
            "lacznie_sprzedaz": lacznie_sprzedaz,
            "lacznie_kosztow": lacznie_kosztow,
            "komunikat": komunikat,
        }
        history.insert(0, entry)
        history = history[:100]  # Ograniczenie do 100 ostatnich zdarzeń
        try:
            atomic_write_json(
                file_path,
                history,
                indent=2,
                ensure_ascii=False,
                mode=0o600,
                lock=True,
            )
        except Exception:
            pass
        return entry

    @classmethod
    def get_last_sync(cls, profile: CompanyProfile, rok: str, miesiac: str) -> Optional[Dict[str, Any]]:
        """Zwraca ostatnią próbę synchronizacji dla zadanego okresu (lub ogólnie ostatnią)."""
        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)
        history = cls.load_sync_history(profile)
        for h in history:
            if h.get("rok") == rok_str and h.get("miesiac") == miesiac_str:
                return h
        return history[0] if history else None

    def authenticate(self) -> str:
        """
        Realizuje uwierzytelnienie w KSeF 2.0:
        - Za pomocą certyfikatu KSeF (.crt + .key, XAdES-BES), jeśli auth_type == 'certyfikat'
          lub jeśli certyfikat jest skonfigurowany a token nie.
        - Za pomocą tokenu KSeF (RSA-OAEP SHA-256) w pozostałych przypadkach.
        """
        auth_type = (self.profile.ksef.auth_type or "token").lower()
        if auth_type == "certyfikat" or (not self.get_auth_token() and self.is_certificate_configured()):
            return self.authenticate_with_certificate()
        return self.authenticate_with_token()

    def authenticate_with_certificate(self) -> str:
        """
        Realizuje uwierzytelnienie w KSeF 2.0 za pomocą podpisu elektronicznego XAdES-BES (certyfikat + klucz):
        1. Wczytanie certyfikatu (auth.crt) i klucza prywatnego (auth.key) firmy
        2. Pobranie AuthorisationChallenge (POST /auth/challenge)
        3. Wygenerowanie i podpisanie XML AuthTokenRequest (XAdES-BES Enveloped)
        4. Rozpoczęcie sesji (POST /auth/xades-signature)
        5. Oczekiwanie na zatwierdzenie (GET /auth/{referenceNumber})
        6. Odebranie docelowego JWT access_token (POST /auth/token/redeem)
        """
        cert_path = self.profile.get_auth_cert_path()
        key_path = self.profile.get_auth_key_path()

        if not cert_path or not key_path:
            raise ValueError(
                f"Brak plików certyfikatu lub klucza dla firmy {self.profile.nazwa} (NIP: {self.profile.nip}). "
                f"Wgraj certyfikat (auth.crt) oraz klucz prywatny (auth.key) w Ustawieniach Firmy."
            )

        with open(cert_path, "rb") as f:
            cert_bytes = f.read()
        with open(key_path, "rb") as f:
            key_bytes = f.read()

        key_password = self.profile.ksef.key_password.encode("utf-8") if self.profile.ksef.key_password else None

        # 1. Challenge
        r_chal = self.session.post(f"{self.base_url}/auth/challenge", json={}, timeout=10)
        r_chal.raise_for_status()
        chal_data = r_chal.json()
        challenge = chal_data["challenge"]

        # 2. Podpisanie XML AuthTokenRequest w formacie XAdES-BES
        signed_xml = sign_ksef_auth_token_request(
            challenge=challenge,
            nip=self.profile.nip,
            cert_bytes=cert_bytes,
            key_bytes=key_bytes,
            key_password=key_password,
        )

        # 3. Wysłanie podpisanego XML do /auth/xades-signature
        headers = {
            "Content-Type": "application/xml",
            "Accept": "application/json",
        }
        r_auth = self.session.post(
            f"{self.base_url}/auth/xades-signature",
            data=signed_xml,
            headers=headers,
            timeout=15,
        )
        r_auth.raise_for_status()
        auth_resp = r_auth.json()
        ref_num = auth_resp["referenceNumber"]
        temp_auth_token = auth_resp["authenticationToken"]["token"]

        # 4. Polling statusu
        auth_headers = {"Authorization": f"Bearer {temp_auth_token}"}
        success = False
        for _ in range(15):
            r_stat = self.session.get(f"{self.base_url}/auth/{ref_num}", headers=auth_headers, timeout=10)
            if r_stat.status_code == 200:
                stat_data = r_stat.json().get("status", {})
                code = stat_data.get("code")
                if code == 200:
                    success = True
                    break
                elif code and code >= 400:
                    raise PermissionError(f"Błąd uwierzytelnienia certyfikatem w KSeF: {stat_data.get('description')}")
            time.sleep(1)

        if not success:
            raise TimeoutError("Przekroczono czas oczekiwania na potwierdzenie uwierzytelnienia certyfikatem w KSeF.")

        # 5. Odebranie Access Tokena
        r_redeem = self.session.post(f"{self.base_url}/auth/token/redeem", headers=auth_headers, timeout=10)
        r_redeem.raise_for_status()
        redeem_data = r_redeem.json()
        self.access_token = redeem_data["accessToken"]["token"]
        self.access_token_valid_until = redeem_data["accessToken"]["validUntil"]

        return self.access_token

    def authenticate_with_token(self) -> str:
        """
        Realizuje pełny proces uwierzytelnienia w KSeF 2.0 za pomocą tokenu podatnika:
        1. Pobranie AuthorisationChallenge (POST /auth/challenge)
        2. Pobranie certyfikatu szyfrującego MF (GET /security/public-key-certificates)
        3. Zaszyfrowanie ciągu token|timestampMs algorytmem RSA-OAEP SHA-256
        4. Rozpoczęcie sesji (POST /auth/ksef-token)
        5. Oczekiwanie na zatwierdzenie (GET /auth/{referenceNumber})
        6. Odebranie docelowego JWT access_token (POST /auth/token/redeem)
        """
        token = self.get_auth_token()
        if not token:
            raise ValueError(
                f"Brak tokena KSeF dla firmy {self.profile.nazwa} (NIP: {self.profile.nip}). "
                f"Uzupełnij token w pliku: firmy/{self.profile.katalog_nazwa}/profil.json "
                f"(w sekcji 'ksef.token') lub użyj polecenia: python -m src.cli set-token --token <TOKEN>"
            )

        # 1. Challenge
        r_chal = self.session.post(f"{self.base_url}/auth/challenge", json={}, timeout=10)
        r_chal.raise_for_status()
        chal_data = r_chal.json()
        challenge = chal_data["challenge"]
        timestamp_ms = chal_data["timestampMs"]

        # 2. Certyfikat klucza publicznego
        r_certs = self.session.get(f"{self.base_url}/security/public-key-certificates", timeout=10)
        r_certs.raise_for_status()
        certs = r_certs.json()
        token_cert_info = next((c for c in certs if "KsefTokenEncryption" in c.get("usage", [])), certs[0])
        cert_bytes = base64.b64decode(token_cert_info["certificate"])
        cert = x509.load_der_x509_certificate(cert_bytes)
        public_key = cert.public_key()

        # 3. Szyfrowanie RSA-OAEP SHA-256
        if not isinstance(public_key, RSAPublicKey):
            raise TypeError("Oczekiwano klucza publicznego RSA z certyfikatu MF.")
        payload_to_encrypt = f"{token}|{timestamp_ms}".encode("utf-8")
        encrypted = public_key.encrypt(
            payload_to_encrypt,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        encrypted_b64 = base64.b64encode(encrypted).decode("ascii")

        # 4. Inicjalizacja uwierzytelnienia
        auth_body = {
            "challenge": challenge,
            "contextIdentifier": {"type": "Nip", "value": self.profile.nip},
            "encryptedToken": encrypted_b64,
        }
        r_auth = self.session.post(f"{self.base_url}/auth/ksef-token", json=auth_body, timeout=10)
        r_auth.raise_for_status()
        auth_resp = r_auth.json()
        ref_num = auth_resp["referenceNumber"]
        temp_auth_token = auth_resp["authenticationToken"]["token"]

        # 5. Polling statusu
        auth_headers = {"Authorization": f"Bearer {temp_auth_token}"}
        success = False
        for _ in range(15):
            r_stat = self.session.get(f"{self.base_url}/auth/{ref_num}", headers=auth_headers, timeout=10)
            if r_stat.status_code == 200:
                stat_data = r_stat.json().get("status", {})
                code = stat_data.get("code")
                if code == 200:
                    success = True
                    break
                elif code and code >= 400:
                    raise PermissionError(f"Błąd uwierzytelnienia w KSeF: {stat_data.get('description')}")
            time.sleep(1)

        if not success:
            raise TimeoutError("Przekroczono czas oczekiwania na potwierdzenie uwierzytelnienia w KSeF.")

        # 6. Odebranie Access Tokena
        r_redeem = self.session.post(f"{self.base_url}/auth/token/redeem", headers=auth_headers, timeout=10)
        r_redeem.raise_for_status()
        redeem_data = r_redeem.json()
        self.access_token = redeem_data["accessToken"]["token"]
        self.access_token_valid_until = redeem_data["accessToken"]["validUntil"]

        return self.access_token

    def test_connection(self) -> Dict[str, Any]:
        """
        Nawiązuje testową sesję z KSeF (poprzez certyfikat lub token) i zwraca status.
        """
        token = self.authenticate()
        return {
            "success": True,
            "auth_type": self.profile.ksef.auth_type,
            "srodowisko": self.env,
            "valid_until": self.access_token_valid_until,
            "token_prefix": token[:15] + "..." if token else "",
        }

    def _ensure_authenticated(self):
        """Upewnia się, że posiadamy aktywny token dostępowy."""
        if not self.access_token:
            self.authenticate()

    def fetch_invoices_metadata_range(
        self, date_from: str, date_to: str, subject_type: str = "Subject1"
    ) -> List[Dict[str, Any]]:
        """
        Pobiera z KSeF listę metadanych faktur dla zadanego zakresu dat (ISO 8601).
        Automatycznie dzieli zakresy > 85 dni na podprzedziały, spełniając wymóg MF (max 100 dni).
        """
        from datetime import timedelta

        self._ensure_authenticated()

        dt_from = datetime.fromisoformat(date_from)
        dt_to = datetime.fromisoformat(date_to)

        # Dzielenie na przedziały <= 85 dni
        chunks = []
        cur = dt_from
        while cur < dt_to:
            nxt = min(cur + timedelta(days=85), dt_to)
            chunks.append((cur.isoformat(), nxt.isoformat()))
            if nxt == dt_to:
                break
            cur = nxt + timedelta(seconds=1)

        api_headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

        all_invoices: List[Dict[str, Any]] = []

        for c_from, c_to in chunks:
            page_offset = 0
            page_size = 100

            while True:
                query_payload: Dict[str, Any] = {
                    "subjectType": subject_type,
                    "dateRange": {"dateType": "Issue", "from": c_from, "to": c_to},
                }
                params: Dict[str, Any] = {"pageOffset": page_offset, "pageSize": page_size, "sortOrder": "Asc"}

                # Pętla z ponawianiem na wypadek rate limitu 429
                max_retries = 6
                for attempt in range(max_retries):
                    resp = self.session.post(
                        f"{self.base_url}/invoices/query/metadata",
                        headers=api_headers,
                        json=query_payload,
                        params=params,
                        timeout=25,
                    )
                    if resp.status_code == 429:
                        try:
                            wait_sec = int(resp.headers.get("Retry-After", 2 * (attempt + 1)))
                        except Exception:
                            wait_sec = 2 * (attempt + 1)
                        if wait_sec > 30:
                            desc = ""
                            try:
                                desc = resp.json().get("status", {}).get("details", [""])[0]
                            except Exception:
                                desc = resp.text
                            raise requests.HTTPError(
                                f"Przekroczono limit zapytań KSeF (MF 429: {desc}). Wymagany czas oczekiwania: {wait_sec} sekund."
                            )
                        time.sleep(wait_sec)
                        continue
                    resp.raise_for_status()
                    break
                else:
                    resp.raise_for_status()

                data = resp.json()
                invoices = data.get("invoices", [])
                all_invoices.extend(invoices)

                if not data.get("hasMore", False) or not invoices:
                    break
                page_offset += 1
                time.sleep(0.3)

        return all_invoices

    def fetch_invoices_metadata(
        self,
        rok: str,
        miesiac: str,
        subject_type: str = "Subject1",  # "Subject1" = Sprzedaż, "Subject2" = Zakup
    ) -> List[Dict[str, Any]]:
        """
        Pobiera z KSeF listę metadanych faktur dla wskazanego pojedynczego miesiąca.
        """
        rok_int = int(rok)
        miesiac_int = int(miesiac)
        _, last_day = calendar.monthrange(rok_int, miesiac_int)

        date_from = f"{rok_int:04d}-{miesiac_int:02d}-01T00:00:00+00:00"
        date_to = f"{rok_int:04d}-{miesiac_int:02d}-{last_day:02d}T23:59:59+00:00"

        return self.fetch_invoices_metadata_range(date_from, date_to, subject_type)

    def fetch_invoice_xml(self, ksef_number: str) -> str:
        """
        Pobiera treść faktury w formacie XML po jej numerze KSeF z obsługą rate limitów (429).
        Endpoint: GET /invoices/ksef/{ksefNumber}
        """
        self._ensure_authenticated()

        api_headers = {"Authorization": f"Bearer {self.access_token}"}
        max_retries = 6
        for attempt in range(max_retries):
            resp = self.session.get(f"{self.base_url}/invoices/ksef/{ksef_number}", headers=api_headers, timeout=20)
            if resp.status_code == 429:
                try:
                    wait_sec = int(resp.headers.get("Retry-After", 2 * (attempt + 1)))
                except Exception:
                    wait_sec = 2 * (attempt + 1)
                if wait_sec > 120:
                    desc = ""
                    try:
                        desc = resp.json().get("status", {}).get("details", [""])[0]
                    except Exception:
                        desc = resp.text
                    raise requests.HTTPError(
                        f"Przekroczono limit pobierania faktur KSeF (MF 429: {desc}). Wymagany czas oczekiwania: {wait_sec}s."
                    )
                print(f"    ⏳ [Limit 16/min KSeF] Czekam {wait_sec + 2}s przed ponowieniem próby...", flush=True)
                time.sleep(wait_sec + 2)
                continue
            resp.raise_for_status()
            return resp.text

        raise requests.HTTPError(f"Przekroczono limit zapytań (429) dla faktury {ksef_number}")

    def sync_month_invoices(self, rok: str, miesiac: str) -> Dict[str, Any]:
        """
        Pobiera wszystkie faktury sprzedaży i zakupu za dany miesiąc,
        parsuje je do obiektów Invoice i zapisuje w strukturze firmy.
        Pomija faktury już obecne w archiwum dyskowym.
        """
        from src.core.invoice import InvoiceType

        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)

        self._ensure_authenticated()

        # Istniejące na dysku faktury (cache hit)
        existing_sprzedaz = {
            i.ksef_numer_referencyjny: i
            for i in InvoiceStorage.list_invoices(self.profile, rok_str, miesiac_str, typ=InvoiceType.SPRZEDAZ)
            if i.ksef_numer_referencyjny
        }
        existing_koszty = {
            i.ksef_numer_referencyjny: i
            for i in InvoiceStorage.list_invoices(self.profile, rok_str, miesiac_str, typ=InvoiceType.KOSZT)
            if i.ksef_numer_referencyjny
        }

        saved_sprzedaz: List[Invoice] = list(existing_sprzedaz.values())
        saved_koszty: List[Invoice] = list(existing_koszty.values())

        # 1. Pobranie i zapis faktur sprzedaży (Subject1)
        meta_sprzedaz = self.fetch_invoices_metadata(rok_str, miesiac_str, subject_type="Subject1")
        for m in meta_sprzedaz:
            ksef_nr = m["ksefNumber"]
            if ksef_nr in existing_sprzedaz:
                continue
            time.sleep(0.3)
            xml = self.fetch_invoice_xml(ksef_nr)
            inv = KSeFParser.parse_xml(xml, target_company_nip=self.profile.nip)
            inv.ksef_numer_referencyjny = ksef_nr
            InvoiceStorage.save_invoice(self.profile, inv)
            saved_sprzedaz.append(inv)
            existing_sprzedaz[ksef_nr] = inv

        # 2. Pobranie i zapis faktur kosztowych (Subject2)
        meta_koszty = self.fetch_invoices_metadata(rok_str, miesiac_str, subject_type="Subject2")
        for m in meta_koszty:
            ksef_nr = m["ksefNumber"]
            if ksef_nr in existing_koszty:
                continue
            time.sleep(0.3)
            xml = self.fetch_invoice_xml(ksef_nr)
            inv = KSeFParser.parse_xml(xml, target_company_nip=self.profile.nip)
            inv.ksef_numer_referencyjny = ksef_nr
            InvoiceStorage.save_invoice(self.profile, inv)
            saved_koszty.append(inv)
            existing_koszty[ksef_nr] = inv

        nowe_s = len(saved_sprzedaz) - len(existing_sprzedaz)
        nowe_k = len(saved_koszty) - len(existing_koszty)

        # Odnotowanie udanej próby synchronizacji w trwałej historii firmy
        self.record_sync_attempt(
            profile=self.profile,
            rok=rok_str,
            miesiac=miesiac_str,
            status="SUKCES",
            srodowisko=self.env,
            nowe_sprzedaz=nowe_s,
            nowe_kosztow=nowe_k,
            lacznie_sprzedaz=len(saved_sprzedaz),
            lacznie_kosztow=len(saved_koszty),
            komunikat=f"Pobrano {nowe_s} nowych faktur sprzedaży i {nowe_k} nowych faktur kosztowych (łącznie: {len(saved_sprzedaz)} sprzedaży, {len(saved_koszty)} kosztów).",
        )

        return {
            "rok": rok_str,
            "miesiac": miesiac_str,
            "nowe_sprzedazy": nowe_s,
            "nowe_kosztow": nowe_k,
            "liczba_sprzedazy": len(saved_sprzedaz),
            "liczba_kosztow": len(saved_koszty),
            "suma_sprzedaz_netto": str(sum((i.suma_netto for i in saved_sprzedaz), Decimal("0.00"))),
            "suma_sprzedaz_vat": str(sum((i.suma_vat for i in saved_sprzedaz), Decimal("0.00"))),
            "suma_koszty_netto": str(sum((i.suma_netto for i in saved_koszty), Decimal("0.00"))),
            "suma_koszty_vat": str(sum((i.suma_vat for i in saved_koszty), Decimal("0.00"))),
            "faktury_sprzedazy": [
                {
                    "numer": i.numer,
                    "ksef_numer": i.ksef_numer_referencyjny,
                    "data": i.data_wystawienia,
                    "nabywca": i.nabywca.nazwa,
                    "netto": str(i.suma_netto),
                    "vat": str(i.suma_vat),
                    "brutto": str(i.suma_brutto),
                }
                for i in saved_sprzedaz
            ],
            "faktury_kosztow": [
                {
                    "numer": i.numer,
                    "ksef_numer": i.ksef_numer_referencyjny,
                    "data": i.data_wystawienia,
                    "sprzedawca": i.sprzedawca.nazwa,
                    "netto": str(i.suma_netto),
                    "vat": str(i.suma_vat),
                    "brutto": str(i.suma_brutto),
                }
                for i in saved_koszty
            ],
        }

    def sync_range_invoices(self, date_from: str, date_to: str) -> Dict[str, Any]:
        """
        Pobiera faktury z dowolnego zakresu dat w zaledwie 2 zapytaniach (Subject1 i Subject2),
        oszczędzając limit 20 zapytań/godz. KSeF API, i zapisuje je w odpowiednich
        folderach miesięcy w archiwum firmy.
        """
        from decimal import Decimal

        self._ensure_authenticated()

        # Znajdź wszystkie już pobrane numery referencyjne KSeF w firmie (cache hit)
        existing_ksef_nrs = set()
        base_faktury = self.profile.katalog_firmy / "faktury"
        if base_faktury.exists():
            for json_path in base_faktury.glob("**/*.json"):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        d = json.load(f)
                        ref = d.get("ksef_numer_referencyjny")
                        if ref:
                            existing_ksef_nrs.add(ref)
                except Exception:
                    pass

        saved_sprzedaz: List[Invoice] = []
        saved_koszty: List[Invoice] = []

        # 1. Sprzedaż
        meta_sprzedaz = self.fetch_invoices_metadata_range(date_from, date_to, subject_type="Subject1")
        print(f"Znaleziono {len(meta_sprzedaz)} faktur sprzedaży w KSeF. Rozpoczynam pobieranie...", flush=True)
        for idx, m in enumerate(meta_sprzedaz, start=1):
            ksef_nr = m["ksefNumber"]
            if ksef_nr in existing_ksef_nrs:
                print(f" [{idx}/{len(meta_sprzedaz)}] Sprzedaż: {ksef_nr} (już w archiwum - pomijam)", flush=True)
                continue
            print(f" [{idx}/{len(meta_sprzedaz)}] Sprzedaż: {ksef_nr}...", flush=True)
            time.sleep(3.8)
            xml = self.fetch_invoice_xml(ksef_nr)
            inv = KSeFParser.parse_xml(xml, target_company_nip=self.profile.nip)
            inv.ksef_numer_referencyjny = ksef_nr
            InvoiceStorage.save_invoice(self.profile, inv)
            saved_sprzedaz.append(inv)
            existing_ksef_nrs.add(ksef_nr)

        # 2. Koszty
        meta_koszty = self.fetch_invoices_metadata_range(date_from, date_to, subject_type="Subject2")
        print(f"\nZnaleziono {len(meta_koszty)} faktur kosztowych w KSeF. Rozpoczynam pobieranie...", flush=True)
        for idx, m in enumerate(meta_koszty, start=1):
            ksef_nr = m["ksefNumber"]
            if ksef_nr in existing_ksef_nrs:
                print(f" [{idx}/{len(meta_koszty)}] Koszt: {ksef_nr} (już w archiwum - pomijam)", flush=True)
                continue
            print(f" [{idx}/{len(meta_koszty)}] Koszt: {ksef_nr}...", flush=True)
            time.sleep(3.8)
            xml = self.fetch_invoice_xml(ksef_nr)
            inv = KSeFParser.parse_xml(xml, target_company_nip=self.profile.nip)
            inv.ksef_numer_referencyjny = ksef_nr
            InvoiceStorage.save_invoice(self.profile, inv)
            saved_koszty.append(inv)
            existing_ksef_nrs.add(ksef_nr)

        return {
            "date_from": date_from,
            "date_to": date_to,
            "liczba_sprzedazy": len(saved_sprzedaz),
            "liczba_kosztow": len(saved_koszty),
            "suma_sprzedaz_netto": str(sum((i.suma_netto for i in saved_sprzedaz), Decimal("0.00"))),
            "suma_sprzedaz_vat": str(sum((i.suma_vat for i in saved_sprzedaz), Decimal("0.00"))),
            "suma_koszty_netto": str(sum((i.suma_netto for i in saved_koszty), Decimal("0.00"))),
            "suma_koszty_vat": str(sum((i.suma_vat for i in saved_koszty), Decimal("0.00"))),
        }
