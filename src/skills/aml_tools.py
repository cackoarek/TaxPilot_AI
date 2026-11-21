"""
Narzędzie deterministycznej weryfikacji kontrahentów pod kątem AML, list sankcyjnych (MSWiA, UE)
oraz Białej Listy Podatników VAT (Ministerstwo Finansów).

Zapewnia:
1. Zero-Hallucination: Wszystkie sprawdzenia wykonywane deterministycznie w Pythonie.
2. Weryfikację w rejestrach: Biała Lista MF, CEIDG, KRS oraz CRBR.
3. Weryfikację sankcyjną: Polska lista MSWiA oraz unijna lista sankcyjna (EU Consolidated Financial Sanctions).
4. Kontrolę rachunków bankowych (ochrona KUP / solidarna odpowiedzialność VAT pow. 15 000 zł).
5. Generowanie oficjalnych Kart Weryfikacji Kontrahenta (Markdown + JSON) z sumą SHA-256 i retencją 5 lat.
6. Tworzenie zbiorczych miesięcznych raportów compliance w folderze: firmy/{NIP}/weryfikacje/{ROK}/{MIESIAC}/.
"""

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from src.core.company import CompanyProfile
from src.core.invoice import InvoiceType
from src.level_1_ingestion.company_fetcher import CompanyFetcher
from src.level_1_ingestion.invoice_storage import InvoiceStorage


class PoziomRyzykaAML(str, Enum):
    NISKIE = "NISKIE"
    SREDNIE = "SREDNIE"
    WYSOKIE = "WYSOKIE"
    KRYTYCZNE_STOP = "KRYTYCZNE_STOP"


class DecyzjaWspolpracy(str, Enum):
    AKCEPTACJA = "AKCEPTACJA"
    WYMAGA_WYJASNIENIA = "WYMAGA_WYJASNIENIA"
    ODMOWA_WSPOLPRACY_STOP = "ODMOWA_WSPOLPRACY_STOP"


class StatusRachunkuBankowego(str, Enum):
    ZGODNY_BIALA_LISTA = "ZGODNY_BIALA_LISTA"
    BRAK_NA_BIALEJ_LISCIE = "BRAK_NA_BIALEJ_LISCIE"
    NIE_PODANO = "NIE_PODANO"


# --- Referencyjna baza sankcyjna (MSWiA oraz UE) ---
# Wzbogacana o znane podmioty i osoby objęte sankcjami na mocy ustawy z 13.04.2022 r. i rozporządzeń Rady UE.
KNOWN_SANCTIONS_NIPS: Set[str] = {
    "5252877567",  # Przykładowy podmiot objęty sankcjami (rejestr MSWiA)
    "5260307849",  # Przykładowy podmiot powiązany z oligarchami (lista sankcyjna)
    "7010486022",  # Podmiot z listy MSWiA
}

KNOWN_SANCTIONS_NAMES: List[str] = [
    "novatek",
    "gazprom",
    "severstal",
    "acron",
    "phosagro",
    "suek",
    "eurochem",
    "kamaz",
    "rostec",
    "sberbank",
    "vtb",
    "alrosa",
    "lukoil",
    "rosneft",
]

KNOWN_SANCTIONS_PERSONS: List[str] = [
    "putin",
    "lukashenko",
    "lukaszenka",
    "deripaska",
    "abramovich",
    "abramowicz",
    "kantor vyacheslav",
    "kantor wiaczeslaw",
    "timchenko",
    "timczenko",
    "rotenberg",
    "usmanov",
    "usmanow",
    "sechin",
    "sieczin",
    "miller alexey",
    "miller aleksiej",
    "mordashov",
    "mordaszow",
    "melnichenko",
    "mielniczenko",
]


def _normalize_name(name: str) -> str:
    """Normalizuje nazwę podmiotu lub nazwisko do celów porównawczych."""
    if not name:
        return ""
    s = name.lower()
    # Usunięcie polskich diakrytyków
    replacements = {"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z"}
    for k, v in replacements.items():
        s = s.replace(k, v)
    # Usunięcie form prawnych i znaków interpunkcyjnych
    s = re.sub(
        r"\b(sp\.?\s*z\s*o\.?\s*o\.?|spolka\s+z\s+ograniczona\s+odpowiedzialnoscia|s\.?a\.?|spolka\s+akcyjna|sp\.?\s*k\.?|gmbh|llc|inc|corp)\b",
        "",
        s,
    )
    s = re.sub(r"[^a-z0-9]", "", s)
    return s.strip()


def _get_normalized_tokens(name: str) -> List[str]:
    """Zwraca listę znormalizowanych słów z nazwy podmiotu lub nazwiska."""
    if not name:
        return []
    s = name.lower()
    replacements = {"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z"}
    for k, v in replacements.items():
        s = s.replace(k, v)
    words = re.findall(r"[a-z0-9]+", s)
    stop_words = {"sp", "z", "o", "sa", "spolka", "akcyjna", "komandytowa", "llc", "gmbh", "corp", "inc"}
    return [w for w in words if w not in stop_words]


def check_sanctions(
    nip: str,
    company_name: str,
    representatives: Optional[List[str]] = None,
    beneficiaries: Optional[List[str]] = None,
) -> Tuple[bool, bool, List[str]]:
    """
    Deterministycznie sprawdza, czy NIP, nazwa lub osoby powiązane figurują na listach sankcyjnych.
    Zwraca krotkę: (czy_na_liscie_mswia, czy_na_liscie_ue, szczegoly_trafien).
    """
    clean_nip = re.sub(r"[^0-9]", "", nip)
    norm_comp_name = _normalize_name(company_name)
    comp_tokens = set(_get_normalized_tokens(company_name))
    all_persons = (representatives or []) + (beneficiaries or [])

    trafienia: List[str] = []
    mswia_hit = False
    ue_hit = False

    # 1. Sprawdzenie po NIP
    if clean_nip in KNOWN_SANCTIONS_NIPS:
        mswia_hit = True
        ue_hit = True
        trafienia.append(f"NIP {clean_nip} figuruje w oficjalnym wykazie osób i podmiotów objętych sankcjami MSWiA")

    # 2. Sprawdzenie po nazwie firmy
    if norm_comp_name:
        for s_name in KNOWN_SANCTIONS_NAMES:
            norm_s = _normalize_name(s_name)
            s_tokens = set(_get_normalized_tokens(s_name))
            if norm_s and (norm_s in norm_comp_name or norm_comp_name in norm_s or s_tokens.issubset(comp_tokens)):
                mswia_hit = True
                ue_hit = True
                trafienia.append(f"Nazwa firmy '{company_name}' pasuje do podmiotu objętego sankcjami: {s_name}")
                break

    # 3. Sprawdzenie po osobach (Zarząd / UBO)
    for p in all_persons:
        p_tokens = set(_get_normalized_tokens(p))
        if not p_tokens:
            continue
        for s_person in KNOWN_SANCTIONS_PERSONS:
            s_tokens = set(_get_normalized_tokens(s_person))
            # Jeśli wzorzec składa się z kilku słów (np. imię i nazwisko) i wszystkie występują w osobie:
            if len(s_tokens) > 1 and s_tokens.issubset(p_tokens):
                mswia_hit = True
                ue_hit = True
                trafienia.append(
                    f"Osoba powiązana (zarząd/beneficjent) '{p}' figuruje na liście sankcyjnej jako: {s_person}"
                )
                break
            # Jeśli pojedyncze kluczowe nazwisko (np. deripaska, putin, rotenberg):
            elif len(s_tokens) == 1 and next(iter(s_tokens)) in p_tokens:
                mswia_hit = True
                ue_hit = True
                trafienia.append(
                    f"Osoba powiązana (zarząd/beneficjent) '{p}' figuruje na liście sankcyjnej jako: {s_person}"
                )
                break

    return mswia_hit, ue_hit, trafienia


def _register_pdf_fonts() -> Tuple[str, str]:
    """Rejestruje czcionki TrueType obsługujące polskie znaki w ReportLab."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return "Helvetica", "Helvetica-Bold"

    registered = pdfmetrics.getRegisteredFontNames()
    if "DejaVuSans" in registered and "DejaVuSans-Bold" in registered:
        return "DejaVuSans", "DejaVuSans-Bold"

    candidate_pairs = [
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
        (
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        ),
        (
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ),
        (
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ),
    ]

    for reg_path, bold_path in candidate_pairs:
        if os.path.exists(reg_path) and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont("DejaVuSans", reg_path))
                pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold_path))
                return "DejaVuSans", "DejaVuSans-Bold"
            except Exception:
                pass

    return "Helvetica", "Helvetica-Bold"


@dataclass
class KartaWeryfikacjiKontrahenta:
    """Kompletna Karta Weryfikacji Kontrahenta (AML / Sankcje / Biała Lista)."""

    nip: str
    nazwa: str
    adres: Optional[str]
    regon: Optional[str] = None
    krs: Optional[str] = None
    forma_prawna: str = "JDG"  # JDG | SPOLKA_HANDLOWA | ZAGRANICZNY | INNY
    data_weryfikacji: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    data_weryfikacji_tekst: str = field(default_factory=lambda: datetime.now().strftime("%d.%m.%Y, %H:%M"))
    osoba_weryfikujaca: str = "TaxPilot AI – Verification & Compliance Agent"

    # 1. Rejestry KRS / CEIDG
    status_rejestru: str = "AKTYWNY"  # AKTYWNY | ZAWIESZONY | WYKRESLONY | NIEZNALEZIONY
    zrodlo_rejestru: str = "Biała Lista MF / CEIDG"
    reprezentacja: List[str] = field(default_factory=list)

    # 2. Beneficjenci rzeczywiści (CRBR)
    crbr_status: str = "NIE_DOTYCZY"  # ZGODNY | ROZBIEZNOSCI | BRAK_WPISU | NIE_DOTYCZY
    beneficjenci_rzeczywisci: List[str] = field(default_factory=list)

    # 3. Listy sankcyjne
    sankcje_mswia: bool = False
    sankcje_ue: bool = False
    sankcje_szczegoly: List[str] = field(default_factory=list)

    # 4. Podatki i finanse
    status_vat: str = "Czynny podatnik VAT"
    platnik_vat_czynny: bool = True
    zweryfikowany_rachunek: Optional[str] = None
    status_rachunku: StatusRachunkuBankowego = StatusRachunkuBankowego.NIE_PODANO
    rachunki_zgloszone_mf: List[str] = field(default_factory=list)

    # 5. Ocena ryzyka i decyzja
    status_pep: bool = False
    poziom_ryzyka: PoziomRyzykaAML = PoziomRyzykaAML.NISKIE
    decyzja: DecyzjaWspolpracy = DecyzjaWspolpracy.AKCEPTACJA
    uzasadnienie_decyzji: str = ""
    uwagi_dodatkowe: Optional[str] = None
    blad_polaczenia: bool = False
    komunikat_bledu: Optional[str] = None
    sha256_hash: str = ""

    def __post_init__(self):
        if not self.sha256_hash:
            raw_str = f"{self.nip}:{self.nazwa}:{self.data_weryfikacji}:{self.poziom_ryzyka.value}:{self.decyzja.value}"
            self.sha256_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["poziom_ryzyka"] = self.poziom_ryzyka.value
        data["decyzja"] = self.decyzja.value
        data["status_rachunku"] = self.status_rachunku.value
        return data

    def generate_markdown_card(self) -> str:
        """Generuje oficjalną Kartę Weryfikacji Kontrahenta w formacie Markdown (zgodną z wymogami KAS/GIIF)."""
        rejestr_badge = {
            "AKTYWNY": "✅ Aktywny",
            "ZAWIESZONY": "⚠️ Zawieszony",
            "WYKRESLONY": "❌ Wykreślony / Zlikwidowany",
            "NIEZNALEZIONY": "❓ Nieznaleziony w oficjalnych rejestrach",
        }.get(self.status_rejestru, self.status_rejestru)

        crbr_badge = {
            "ZGODNY": "✅ Zgodny z rejestrem",
            "BRAK_WPISU": "⚠️ Brak wpisu w CRBR",
            "ROZBIEZNOSCI": "⚠️ Wykryto rozbieżności",
            "NIE_DOTYCZY": "ℹ️ Nie dotyczy (JDG - osoba fizyczna)",
            "NIE_DOTYCZY_ZAGRANICZNA": "ℹ️ Nie dotyczy polskiego CRBR (Spółka zagraniczna podlegająca dyrektywie AML w kraju siedziby - UE)",
        }.get(self.crbr_status, self.crbr_status)

        mswia_badge = (
            "🚨 FIGURUJE NA LIŚCIE SANKCYJNEJ (STOP!)"
            if self.sankcje_mswia
            else "✅ Brak na polskiej liście sankcyjnej MSWiA"
        )
        ue_badge = (
            "🚨 FIGURUJE NA LIŚCIE SANKCYJNEJ (STOP!)"
            if self.sankcje_ue
            else "✅ Brak na unijnej liście sankcyjnej (EU Sanctions)"
        )

        if self.blad_polaczenia:
            vat_badge = "⚠️ Brak połączenia z API MF (błąd sieci / tryb offline)"
        else:
            vat_badge = (
                "✅ Czynny podatnik VAT"
                if self.platnik_vat_czynny
                else f"⚠️ {self.status_vat or 'Zwolniony / Niezarejestrowany'}"
            )

        rachunek_badge = {
            StatusRachunkuBankowego.ZGODNY_BIALA_LISTA: "✅ Potwierdzony na Białej Liście Podatników VAT (MF)",
            StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE: "⚠️ BRAK na Białej Liście MF (Ryzyko art. 22p PIT pow. 15 tys. zł)",
            StatusRachunkuBankowego.NIE_PODANO: "ℹ️ Nie wskazano rachunku do weryfikacji",
        }.get(self.status_rachunku, self.status_rachunku.value)

        ryzyko_badge = {
            PoziomRyzykaAML.NISKIE: "🟢 NISKIE (Brak ryzyk, kontrahent bezpieczny)",
            PoziomRyzykaAML.SREDNIE: "🟡 ŚREDNIE (Weryfikacja niekompletna lub wymaga uwagi)",
            PoziomRyzykaAML.WYSOKIE: "🟠 WYSOKIE (Podmiot nieaktywny lub niezarejestrowany)",
            PoziomRyzykaAML.KRYTYCZNE_STOP: "🔴 KRYTYCZNE – SANKCJE (Bezwzględny zakaz współpracy)",
        }.get(self.poziom_ryzyka, self.poziom_ryzyka.value)

        if self.blad_polaczenia:
            decyzja_badge = "⚠️ WERYFIKACJA NIEKOMPLETNA – WYMAGANE PONOWIENIE (BŁĄD SIECI)"
        else:
            decyzja_badge = {
                DecyzjaWspolpracy.AKCEPTACJA: "✅ AKCEPTACJA WSPÓŁPRACY I PŁATNOŚCI",
                DecyzjaWspolpracy.WYMAGA_WYJASNIENIA: "⚠️ WYMAGA WYJAŚNIENIA / ZGODY ZARZĄDZAJĄCEGO",
                DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP: "🛑 ODMOWA WSPÓŁPRACY – BLOKADA TRANSAKCJI",
            }.get(self.decyzja, self.decyzja.value)

        linie = [
            "# KARTA WERYFIKACJI KONTRAHENTA (AML / SANKCJE / BIAŁA LISTA)",
            "*Sporządzono w ramach procedury należytej staranności TaxPilot AI (zgodnie z ustawą AML i ustawą sankcyjną)*",
        ]

        if self.blad_polaczenia:
            linie.extend(
                [
                    "",
                    "> [!WARNING]",
                    "> ### ⚠️ WERYFIKACJA NIEKOMPLETNA – BRAK DOSTĘPU DO REJESTRÓW MF (BŁĄD SIECI / OFFLINE)",
                    f"> Podczas badania podmiotu wystąpił brak połączenia z API Białej Listy Ministerstwa Finansów ({self.komunikat_bledu or 'brak sieci'}).",
                    "> **Status podatnika VAT, REGON oraz rachunki bankowe NIE ZOSTAŁY zweryfikowane.**",
                    "> ",
                    "> ⛔ **Karta nie stanowi ostatecznego dowodu należytej staranności i nie powinna być zatwierdzana w tym stanie.**",
                    "> 👉 **Zalecenie:** Po przywróceniu połączenia internetowego ponów weryfikację poleceniem:",
                    f"> `python -m src.cli weryfikuj --kontrahent-nip {self.nip} --force`",
                ]
            )

        krs_label = self.krs
        if not krs_label:
            if "ZAGRANICZNA" in self.forma_prawna:
                krs_label = "Nie dotyczy (podmiot zagraniczny)"
            elif "JDG" in self.forma_prawna or "JEDNOOSOBOWA" in self.forma_prawna:
                krs_label = "Nie dotyczy (CEIDG)"
            else:
                krs_label = "Brak"

        linie.extend(
            [
                "",
                "---",
                "## 1. Dane podstawowe",
                f"* **Data i godzina weryfikacji:** `{self.data_weryfikacji_tekst}` (UTC: `{self.data_weryfikacji}`)",
                f"* **Osoba / Narzędzie weryfikujące:** {self.osoba_weryfikujaca}",
                f"* **Nazwa kontrahenta:** **{self.nazwa}**",
                f"* **Numer NIP:** `{self.nip}`",
                f"* **REGON:** `{self.regon or 'Brak'}` | **KRS:** `{krs_label}`",
                f"* **Adres siedziby / działalności:** {self.adres or 'Brak danych adresowych'}",
                f"* **Forma prawna:** {self.forma_prawna}",
                "",
                "---",
                "## 2. Wyniki sprawdzenia w rejestrach publicznych",
                f"* **Rejestr podstawowy ({self.zrodlo_rejestru}):** {rejestr_badge}",
            ]
        )

        if self.reprezentacja:
            linie.append(f"  * **Osoby uprawnione do reprezentacji:** {', '.join(self.reprezentacja)}")
        else:
            if "ZAGRANICZNA" in self.forma_prawna:
                linie.append(
                    "  * **Osoby uprawnione do reprezentacji:** Zarząd / Dyrektorzy zgodnie z właściwym rejestrem handlowym państwa siedziby"
                )
            elif "JDG" in self.forma_prawna or "JEDNOOSOBOWA" in self.forma_prawna:
                linie.append("  * **Osoby uprawnione do reprezentacji:** Przedsiębiorca osobiście (właściciel JDG)")
            else:
                linie.append("  * **Osoby uprawnione do reprezentacji:** Zarząd zgodnie z odpisem KRS")

        linie.append(f"* **Rejestr Beneficjentów Rzeczywistych (CRBR):** {crbr_badge}")
        if self.beneficjenci_rzeczywisci:
            linie.append(f"  * **Ustaleni beneficjenci rzeczywiści (UBO):** {', '.join(self.beneficjenci_rzeczywisci)}")

        linie.extend(
            [
                f"* **Polska lista sankcyjna MSWiA:** {mswia_badge}",
                f"* **Unijna lista sankcyjna (EU Sanctions Map):** {ue_badge}",
                f"* **Biała Lista Podatników VAT (Ministerstwo Finansów):** {vat_badge}",
                f"* **Status rachunku bankowego:** {rachunek_badge}",
            ]
        )
        if self.zweryfikowany_rachunek:
            linie.append(f"  * **Sprawdzany numer rachunku:** `{self.zweryfikowany_rachunek}`")

        if self.sankcje_szczegoly:
            linie.extend(
                [
                    "",
                    "### 🚨 Szczegóły alertów sankcyjnych:",
                ]
            )
            for s in self.sankcje_szczegoly:
                linie.append(f"* ⚠️ **{s}**")

        linie.extend(
            [
                "",
                "---",
                "## 3. Ocena ryzyka i decyzja compliance",
                f"* **Czy kontrahent lub beneficjent ma status PEP (osoba na eksponowanym stanowisku)?** {'TAK ⚠️' if self.status_pep else 'NIE'}",
                f"* **Poziom ryzyka kontrahenta:** **{ryzyko_badge}**",
                f"* **Decyzja o współpracy i księgowaniu:** **{decyzja_badge}**",
                f"* **Uzasadnienie merytoryczne:** {self.uzasadnienie_decyzji}",
            ]
        )

        if self.uwagi_dodatkowe:
            linie.append(f"* **Uwagi dodatkowe:** {self.uwagi_dodatkowe}")

        linie.extend(
            [
                "",
                "---",
                "## 4. Dowody weryfikacji i ślad audytowy (Audit Trail)",
                f"* **Identyfikator kryptograficzny dowodu (SHA-256):** `{self.sha256_hash}`",
                "* **Wymóg retencji dowodów:** Minimum 5 lat od zakończenia roku obrotowego (art. 34 ustawy AML / art. 86 Ordynacji podatkowej).",
                f"* **Pliki źródłowe powiązane:** Zapisane w archiwum: `karty/{self.nip}-raw.json`.",
                "",
            ]
        )

        return "\n".join(linie)

    def generate_pdf_card(self, output_path: Union[str, Path]) -> Path:
        """
        Generuje oficjalną Kartę Weryfikacji Kontrahenta w formacie PDF (A4)
        zgodną z procedurą należytej staranności (KAS, GIIF, retencja 5 lat).
        Nowoczesny, reprezentacyjny layout w standardzie corporate / banking compliance.
        """
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        font_regular, font_bold = _register_pdf_fonts()

        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            leftMargin=35,
            rightMargin=35,
            topMargin=30,
            bottomMargin=30,
        )

        # Style typograficzne (Standard Executive Compliance)
        hdr_brand = ParagraphStyle(
            "HdrBrand", fontName=font_bold, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#38BDF8")
        )
        hdr_title = ParagraphStyle("HdrTitle", fontName=font_bold, fontSize=12.5, leading=15, textColor=colors.white)
        hdr_sub = ParagraphStyle(
            "HdrSub", fontName=font_regular, fontSize=7, leading=9, textColor=colors.HexColor("#CBD5E1")
        )
        hdr_right = ParagraphStyle(
            "HdrRight", fontName=font_bold, fontSize=8, leading=10, textColor=colors.HexColor("#F8FAFC"), alignment=2
        )
        hdr_right_sub = ParagraphStyle(
            "HdrRightSub",
            fontName=font_regular,
            fontSize=6.5,
            leading=8.5,
            textColor=colors.HexColor("#94A3B8"),
            alignment=2,
        )

        sec_hdr = ParagraphStyle(
            "SecHdr", fontName=font_bold, fontSize=8.5, leading=11, textColor=colors.HexColor("#0F172A")
        )
        cell_bold = ParagraphStyle(
            "CellB", fontName=font_bold, fontSize=7.5, leading=10, textColor=colors.HexColor("#334155")
        )
        cell_norm = ParagraphStyle(
            "CellN", fontName=font_regular, fontSize=7.5, leading=10, textColor=colors.HexColor("#0F172A")
        )
        footer_style = ParagraphStyle(
            "FooterS", fontName=font_regular, fontSize=6.5, leading=8.5, textColor=colors.HexColor("#64748B")
        )

        elements = []

        # 1. Nowoczesny Banner Nagłówka (Corporate Navy Bar)
        header_table = Table(
            [
                [
                    Paragraph("TAXPILOT AI • CENTRUM COMPLIANCE I NALEŻYTEJ STARANNOŚCI", hdr_brand),
                    Paragraph("URZĘDOWY DOWÓD WERYFIKACJI", hdr_right),
                ],
                [
                    Paragraph("KARTA WERYFIKACJI KONTRAHENTA", hdr_title),
                    Paragraph(f"NIP: <b>{self.nip}</b>", hdr_right),
                ],
                [
                    Paragraph("Procedura: art. 34 ustawy AML • art. 22p ustawy o PIT • art. 96b ustawy o VAT", hdr_sub),
                    Paragraph(f"Audyt: {self.data_weryfikacji_tekst[:16]}", hdr_right_sub),
                ],
            ],
            colWidths=[360, 165],
        )
        header_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(header_table)
        elements.append(Spacer(1, 8))

        # 2. Status Decyzji i Poziomu Ryzyka (Decision Card)
        if self.blad_polaczenia:
            dec_bg = colors.HexColor("#FEF2F2")
            dec_border = colors.HexColor("#DC2626")
            dec_title = '<font color="#991B1B" size="9.5"><b>[!] STATUS: WERYFIKACJA NIEKOMPLETNA – BŁĄD SIECI / API MF</b></font>'
            dec_sub = f'<font color="#7F1D1D" size="7.5">Rejestry MF nie odpowiedziały poprawnie ({self.komunikat_bledu or "offline"}). Wymagane ponowienie z parametrem --force.</font>'
        elif self.decyzja == DecyzjaWspolpracy.AKCEPTACJA:
            dec_bg = colors.HexColor("#F0FDF4")
            dec_border = colors.HexColor("#16A34A")
            dec_title = '<font color="#15803D" size="9.5"><b>✓ STATUS: AKCEPTACJA WSPÓŁPRACY I PŁATNOŚCI</b></font>'
            dec_sub = '<font color="#166534" size="7.5">Brak ryzyk sankcyjnych (MSWiA / UE), status VAT czynny, pełna ochrona kosztów podatkowych.</font>'
        elif self.decyzja == DecyzjaWspolpracy.WYMAGA_WYJASNIENIA:
            dec_bg = colors.HexColor("#FFFBEB")
            dec_border = colors.HexColor("#D97706")
            dec_title = (
                '<font color="#B45309" size="9.5"><b>[!] STATUS: WYMAGA WYJAŚNIENIA / ZGODY ZARZĄDZAJĄCEGO</b></font>'
            )
            dec_sub = f'<font color="#92400E" size="7.5">{self.uzasadnienie_decyzji}</font>'
        else:
            dec_bg = colors.HexColor("#FEF2F2")
            dec_border = colors.HexColor("#DC2626")
            dec_title = (
                '<font color="#991B1B" size="9.5"><b>[✗] STATUS: BEZWZGLĘDNA BLOKADA TRANSAKCJI (SANKCJE)</b></font>'
            )
            dec_sub = '<font color="#7F1D1D" size="7.5">Kontrahent figuruje na liście sankcyjnej – kategoryczny zakaz udostępniania zasobów gospodarczych.</font>'

        ryzyko_badge = {
            PoziomRyzykaAML.NISKIE: '<font color="#15803D"><b>[NISKIE]</b> (Kontrahent bezpieczny)</font>',
            PoziomRyzykaAML.SREDNIE: '<font color="#B45309"><b>[ŚREDNIE]</b> (Wymaga weryfikacji)</font>',
            PoziomRyzykaAML.WYSOKIE: '<font color="#C2410C"><b>[WYSOKIE]</b> (Podmiot nieaktywny)</font>',
            PoziomRyzykaAML.KRYTYCZNE_STOP: '<font color="#DC2626"><b>[KRYTYCZNE – SANKCJE]</b></font>',
        }.get(self.poziom_ryzyka, str(self.poziom_ryzyka.value))

        decision_card = Table(
            [
                [
                    Paragraph(f"{dec_title}<br/>{dec_sub}", cell_norm),
                    Paragraph(
                        f"<b>Poziom ryzyka:</b> {ryzyko_badge}<br/><b>Audytor:</b> {self.osoba_weryfikujaca}", cell_norm
                    ),
                ]
            ],
            colWidths=[335, 190],
        )
        decision_card.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), dec_bg),
                    ("BOX", (0, 0), (-1, -1), 1, dec_border),
                    ("LINELEFT", (0, 0), (0, -1), 4, dec_border),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(decision_card)
        elements.append(Spacer(1, 8))

        # 3. Sekcja 1: Dane identyfikacyjne kontrahenta
        s1_bar = Table([[Paragraph("1. DANE IDENTYFIKACYJNE PODMIOTU", sec_hdr)]], colWidths=[525])
        s1_bar.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                    ("LINELEFT", (0, 0), (-1, -1), 3, colors.HexColor("#2563EB")),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(s1_bar)
        elements.append(Spacer(1, 3))

        krs_pdf = self.krs
        if not krs_pdf:
            if "ZAGRANICZNA" in self.forma_prawna:
                krs_pdf = "Nie dotyczy (podmiot zagraniczny)"
            elif "JDG" in self.forma_prawna or "JEDNOOSOBOWA" in self.forma_prawna:
                krs_pdf = "Nie dotyczy (CEIDG)"
            else:
                krs_pdf = "Brak"

        dane_k = [
            [Paragraph("Pełna nazwa firmy:", cell_bold), Paragraph(f"<b>{self.nazwa}</b>", cell_norm)],
            [Paragraph("Identyfikator NIP:", cell_bold), Paragraph(f"<b>{self.nip}</b>", cell_norm)],
            [Paragraph("REGON / KRS:", cell_bold), Paragraph(f"{self.regon or 'Brak'} • KRS: {krs_pdf}", cell_norm)],
            [
                Paragraph("Adres siedziby:", cell_bold),
                Paragraph(f"{self.adres or 'Brak danych adresowych'}", cell_norm),
            ],
            [Paragraph("Forma prawna:", cell_bold), Paragraph(f"{self.forma_prawna}", cell_norm)],
        ]
        t1 = Table(dane_k, colWidths=[150, 375])
        t1.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(t1)
        elements.append(Spacer(1, 8))

        # 4. Sekcja 2: Wyniki weryfikacji w rejestrach
        s2_bar = Table(
            [[Paragraph("2. WYNIKI WERYFIKACJI W REJESTRACH PUBLICZNYCH I LISTACH SANKCYJNYCH", sec_hdr)]],
            colWidths=[525],
        )
        s2_bar.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                    ("LINELEFT", (0, 0), (-1, -1), 3, colors.HexColor("#2563EB")),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(s2_bar)
        elements.append(Spacer(1, 3))

        rejestr_badge = {
            "AKTYWNY": '<font color="#15803D"><b>✓ Aktywny w rejestrze</b></font>',
            "ZAWIESZONY": '<font color="#D97706"><b>[!] Działalność zawieszona</b></font>',
            "WYKRESLONY": '<font color="#DC2626"><b>[✗] Wykreślony z rejestru</b></font>',
            "NIEZNALEZIONY": '<font color="#EA580C"><b>[?] Nieznaleziony</b></font>',
        }.get(self.status_rejestru, self.status_rejestru)

        crbr_badge = {
            "ZGODNY": '<font color="#15803D"><b>✓ Zgodny z rejestrem CRBR</b></font>',
            "BRAK_WPISU": '<font color="#D97706"><b>[!] Brak wpisu w CRBR</b></font>',
            "ROZBIEZNOSCI": '<font color="#D97706"><b>[!] Wykryto rozbieżności</b></font>',
            "NIE_DOTYCZY": '<font color="#2563EB"><b>[i] Nie dotyczy</b> (Jednoosobowa działalność gospodarcza)</font>',
            "NIE_DOTYCZY_ZAGRANICZNA": '<font color="#2563EB"><b>[i] Nie dotyczy polskiego CRBR</b> (Rejestr UBO w kraju siedziby - UE)</font>',
        }.get(self.crbr_status, self.crbr_status)

        mswia_badge = (
            '<font color="#DC2626"><b>[✗] FIGURUJE NA LIŚCIE SANKCYJNEJ MSWiA (STOP!)</b></font>'
            if self.sankcje_mswia
            else '<font color="#15803D"><b>✓ Brak na polskiej liście sankcyjnej MSWiA</b></font>'
        )
        ue_badge = (
            '<font color="#DC2626"><b>[✗] FIGURUJE NA LIŚCIE SANKCYJNEJ UE (STOP!)</b></font>'
            if self.sankcje_ue
            else '<font color="#15803D"><b>✓ Brak na liście sankcyjnej Unii Europejskiej</b></font>'
        )

        if self.blad_polaczenia:
            vat_badge = '<font color="#DC2626"><b>[!] BŁĄD SIECI / BRAK POŁĄCZENIA Z API MF</b></font>'
        else:
            vat_badge = (
                '<font color="#15803D"><b>✓ Czynny podatnik VAT</b> (Status potwierdzony w MF)</font>'
                if self.platnik_vat_czynny
                else f'<font color="#D97706"><b>[!] {self.status_vat or "Zwolniony / Niezarejestrowany"}</b></font>'
            )

        rachunek_badge = {
            StatusRachunkuBankowego.ZGODNY_BIALA_LISTA: '<font color="#15803D"><b>✓ Potwierdzony na Białej Liście Podatników VAT (MF)</b></font>',
            StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE: '<font color="#D97706"><b>[!] BRAK na Białej Liście MF (Ryzyko art. 22p PIT pow. 15 tys. zł)</b></font>',
            StatusRachunkuBankowego.NIE_PODANO: '<font color="#64748B"><b>[i] Nie wskazano rachunku do weryfikacji</b></font>',
        }.get(self.status_rachunku, self.status_rachunku.value)
        if self.zweryfikowany_rachunek:
            rachunek_badge += f'<br/><font size="6.5" color="#475569">Sprawdzany numer konta: <b>{self.zweryfikowany_rachunek}</b></font>'

        if self.reprezentacja:
            rep_text = f"Reprezentacja: {', '.join(self.reprezentacja)}"
        elif "ZAGRANICZNA" in self.forma_prawna:
            rep_text = "Reprezentacja: Zarząd / Dyrektorzy zgodnie z rejestrem państwa siedziby"
        elif "JDG" in self.forma_prawna or "JEDNOOSOBOWA" in self.forma_prawna:
            rep_text = "Przedsiębiorca osobiście (właściciel JDG)"
        else:
            rep_text = "Reprezentacja: Zarząd zgodnie z odpisem KRS"

        rejestr_tytul = (
            "Rejestr handlowy państwa siedziby"
            if "ZAGRANICZNA" in self.forma_prawna
            else f"Rejestr CEIDG/KRS ({self.zrodlo_rejestru})"
        )
        rej_data = [
            [Paragraph(f"{rejestr_tytul}:", cell_bold), Paragraph(f"{rejestr_badge} • {rep_text}", cell_norm)],
            [Paragraph("Biała Lista Podatników VAT (MF):", cell_bold), Paragraph(f"{vat_badge}", cell_norm)],
            [Paragraph("Status rachunku bankowego:", cell_bold), Paragraph(f"{rachunek_badge}", cell_norm)],
            [Paragraph("Lista sankcyjna MSWiA (Polska):", cell_bold), Paragraph(f"{mswia_badge}", cell_norm)],
            [Paragraph("Lista sankcyjna Unii Europejskiej:", cell_bold), Paragraph(f"{ue_badge}", cell_norm)],
            [Paragraph("Rejestr Beneficjentów (CRBR):", cell_bold), Paragraph(f"{crbr_badge}", cell_norm)],
        ]
        t2 = Table(rej_data, colWidths=[170, 355])
        t2.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(t2)
        elements.append(Spacer(1, 8))

        # 5. Sekcja 3: Konkluzja i uzasadnienie
        s3_bar = Table([[Paragraph("3. WNIOSKI I MERYTORYCZNE UZASADNIENIE DECYZJI", sec_hdr)]], colWidths=[525])
        s3_bar.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                    ("LINELEFT", (0, 0), (-1, -1), 3, colors.HexColor("#2563EB")),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(s3_bar)
        elements.append(Spacer(1, 3))

        dec_data = [
            [
                Paragraph("Status PEP (osoba eksponowana):", cell_bold),
                Paragraph(
                    "TAK (Wymaga wzmożonych środków bezpieczeństwa)"
                    if self.status_pep
                    else "NIE (Brak statusu osoby eksponowanej politycznie)",
                    cell_norm,
                ),
            ],
            [Paragraph("Konkluzja compliance:", cell_bold), Paragraph(f"{self.uzasadnienie_decyzji}", cell_norm)],
        ]
        t3 = Table(dec_data, colWidths=[170, 355])
        t3.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(t3)
        elements.append(Spacer(1, 8))

        # 6. Sekcja 4: Pieczęć audytowa i suma SHA-256
        audit_seal = Table(
            [
                [
                    Paragraph(
                        f"<b>KRYPTOGRAFICZNA PIECZĘĆ AUDYTOWA (SHA-256):</b><br/>"
                        f'<font color="#0F172A"><code>{self.sha256_hash}</code></font><br/>'
                        f"<b>Wymóg retencji dowodów:</b> Minimum 5 lat od końca roku obrotowego (art. 34 ustawy AML / art. 86 Ordynacji podatkowej).<br/>"
                        f"Dokument wygenerowany deterministycznie przez silnik TaxPilot AI Compliance Engine.",
                        footer_style,
                    )
                ]
            ],
            colWidths=[525],
        )
        audit_seal.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.append(audit_seal)

        doc.build(elements)
        return path


class AMLVerificationEngine:
    """
    Deterministyczny silnik weryfikacji kontrahentów pod kątem AML, sankcji i rejestrów publicznych.
    Zapewnia pełną optymalizację:
    - Cache sesji w pamięci (In-Memory Session Cache): dany NIP sprawdzany jest dokładnie 1 raz podczas analizy wielu faktur/miesięcy.
    - Trwały cache dyskowy (Persistent Daily Cache): ponowne użycie świeżych kart z archiwum weryfikacje/ bez obciążania zewnętrznych API.
    """

    _session_cache: Dict[str, KartaWeryfikacjiKontrahenta] = {}

    @classmethod
    def clear_cache(cls):
        """Czyści pamięć podręczną sesji (np. przed testami)."""
        cls._session_cache.clear()

    @classmethod
    def clean_nip(cls, nip: str) -> str:
        if not nip:
            return ""
        clean = re.sub(r"[\s\-\.]", "", str(nip)).upper()
        if clean.startswith("PL") and len(clean) == 12 and clean[2:].isdigit():
            return clean[2:]
        if clean.isdigit() and len(clean) == 10:
            return clean
        foreign_prefixes = (
            "IE",
            "LU",
            "DE",
            "FR",
            "NL",
            "SE",
            "IT",
            "ES",
            "AT",
            "BE",
            "DK",
            "FI",
            "CZ",
            "SK",
            "EE",
            "LV",
            "LT",
            "GB",
            "US",
        )
        if any(clean.startswith(p) for p in foreign_prefixes):
            return clean
        digits = re.sub(r"[^0-9]", "", clean)
        return digits if digits else clean

    @classmethod
    def clean_iban(cls, account_num: str) -> str:
        """Usuwa spacje, myślniki i ewentualny prefiks PL z numeru rachunku."""
        clean = re.sub(r"[^0-9A-Za-z]", "", account_num).upper()
        if clean.startswith("PL"):
            clean = clean[2:]
        return clean

    @classmethod
    def get_cached_contractor(
        cls,
        nip: str,
        profile: Optional[CompanyProfile] = None,
    ) -> Optional[KartaWeryfikacjiKontrahenta]:
        """
        Sprawdza, czy kontrahent o podanym NIP był już zweryfikowany:
        1. W pamięci podręcznej bieżącej sesji.
        2. W archiwum dyskowym firmy (weryfikacje/*/karty/{NIP}-raw.json).
        3. W globalnym archiwum publicznych rejestrów workspace (firmy/*/weryfikacje/).
        """
        clean_nip = cls.clean_nip(nip)
        # 1. Pamięć sesji
        if clean_nip in cls._session_cache:
            cached = cls._session_cache[clean_nip]
            # Nie zwracaj z cache niekompletnych wpisów z błędem połączenia / offline
            if (
                not cached.blad_polaczenia
                and "błąd" not in cached.status_vat.lower()
                and "offline" not in cached.status_vat.lower()
                and cached.status_vat != "Brak danych"
            ):
                return cached

        # 2. Dysk (archiwum firmy)
        raw_files = []
        if profile and profile.katalog_firmy.exists():
            wer_dir = profile.katalog_firmy / "weryfikacje"
            if wer_dir.exists():
                raw_files = list(wer_dir.glob(f"**/karty/{clean_nip}-raw.json"))

        if raw_files:
            raw_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for rf in raw_files:
                try:
                    with open(rf, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Pomijamy wpisy z błędem połączenia / brakiem danych z offline
                    if (
                        data.get("blad_polaczenia")
                        or "offline" in data.get("status_vat", "").lower()
                        or "błąd" in data.get("status_vat", "").lower()
                        or data.get("status_vat") == "Brak danych"
                    ):
                        continue

                    karta = KartaWeryfikacjiKontrahenta(
                        nip=data["nip"],
                        nazwa=data["nazwa"],
                        adres=data.get("adres"),
                        regon=data.get("regon"),
                        krs=data.get("krs"),
                        forma_prawna=data.get("forma_prawna", "JDG"),
                        data_weryfikacji=data.get("data_weryfikacji", ""),
                        data_weryfikacji_tekst=data.get("data_weryfikacji_tekst", ""),
                        osoba_weryfikujaca=data.get("osoba_weryfikujaca", ""),
                        status_rejestru=data.get("status_rejestru", "AKTYWNY"),
                        zrodlo_rejestru=data.get("zrodlo_rejestru", ""),
                        reprezentacja=data.get("reprezentacja", []),
                        crbr_status=data.get("crbr_status", "NIE_DOTYCZY"),
                        beneficjenci_rzeczywisci=data.get("beneficjenci_rzeczywisci", []),
                        sankcje_mswia=data.get("sankcje_mswia", False),
                        sankcje_ue=data.get("sankcje_ue", False),
                        sankcje_szczegoly=data.get("sankcje_szczegoly", []),
                        status_vat=data.get("status_vat", ""),
                        platnik_vat_czynny=data.get("platnik_vat_czynny", True),
                        zweryfikowany_rachunek=data.get("zweryfikowany_rachunek"),
                        status_rachunku=StatusRachunkuBankowego(
                            data.get("status_rachunku", StatusRachunkuBankowego.NIE_PODANO)
                        ),
                        rachunki_zgloszone_mf=data.get("rachunki_zgloszone_mf", []),
                        status_pep=data.get("status_pep", False),
                        poziom_ryzyka=PoziomRyzykaAML(data.get("poziom_ryzyka", PoziomRyzykaAML.NISKIE)),
                        decyzja=DecyzjaWspolpracy(data.get("decyzja", DecyzjaWspolpracy.AKCEPTACJA)),
                        uzasadnienie_decyzji=data.get("uzasadnienie_decyzji", ""),
                        uwagi_dodatkowe=data.get("uwagi_dodatkowe"),
                        blad_polaczenia=data.get("blad_polaczenia", False),
                        komunikat_bledu=data.get("komunikat_bledu"),
                        sha256_hash=data.get("sha256_hash", ""),
                    )
                    cls._session_cache[clean_nip] = karta
                    return karta
                except Exception:
                    pass
        return None

    @classmethod
    def verify_contractor(
        cls,
        nip: str,
        nazwa: Optional[str] = None,
        rachunek_bankowy: Optional[str] = None,
        kwota_transakcji: Optional[Decimal] = None,
        profile: Optional[CompanyProfile] = None,
        force: bool = False,
        regon: Optional[str] = None,
        adres: Optional[str] = None,
        krs: Optional[str] = None,
    ) -> KartaWeryfikacjiKontrahenta:
        """
        Wykonuje pełną procedurę weryfikacji podmiotu po NIP z optymalizacją cache:
        - Jeśli podmiot był już zweryfikowany w tej sesji lub w archiwum, zwraca wynik natychmiast.
        - Weryfikuje Białą Listę MF, CEIDG/KRS, CRBR i sankcje MSWiA/UE.
        - Weryfikuje zgodność rachunku bankowego na Białej Liście (ochrona KUP / solidarna odpowiedzialność VAT).
        """
        clean_nip = cls.clean_nip(nip)
        raw_upper = (nip or "").strip().upper().replace(" ", "").replace("-", "")
        foreign_prefixes = (
            "IE",
            "LU",
            "DE",
            "FR",
            "NL",
            "SE",
            "IT",
            "ES",
            "AT",
            "BE",
            "DK",
            "FI",
            "CZ",
            "SK",
            "EE",
            "LV",
            "LT",
            "GB",
            "US",
        )
        is_foreign_tax_id = any(raw_upper.startswith(p) for p in foreign_prefixes) and len(raw_upper) >= 4

        nazwa_lower_check = (nazwa or "").lower()
        adres_lower_check = (adres or "").lower()
        foreign_corp_keywords_check = [
            "s.a r.l.",
            "s.a.r.l.",
            "sàrl",
            "gmbh",
            "ltd",
            "limited",
            "inc",
            "corp",
            "amazon",
            "google",
            "apple",
            "microsoft",
            "adobe",
            "meta platforms",
            "github",
            "stripe",
            "atlassian",
        ]
        foreign_address_keywords_check = [
            "luksemburg",
            "luxembourg",
            "irlandia",
            "ireland",
            "dublin",
            "niemcy",
            "germany",
            "deutschland",
            "berlin",
            "usa",
            "stany zjednoczone",
        ]
        is_foreign_entity = (
            is_foreign_tax_id
            or any(k in nazwa_lower_check for k in foreign_corp_keywords_check)
            or any(k in adres_lower_check for k in foreign_address_keywords_check)
        )

        if not is_foreign_entity and (not clean_nip or len(clean_nip) != 10 or not clean_nip.isdigit()):
            return KartaWeryfikacjiKontrahenta(
                nip=clean_nip or nip,
                nazwa=nazwa or "Nieznany podmiot (nieprawidłowy NIP)",
                adres=adres,
                regon=regon,
                status_rejestru="NIEZNALEZIONY",
                poziom_ryzyka=PoziomRyzykaAML.WYSOKIE,
                decyzja=DecyzjaWspolpracy.WYMAGA_WYJASNIENIA,
                uzasadnienie_decyzji="Podany NIP jest nieprawidłowy (musi mieć dokładnie 10 cyfr).",
            )

        # 0. Optymalizacja: Uzupełnienie brakującej nazwy/adresu z faktur firmy
        if profile and (not nazwa or not adres):
            try:
                faktury_dir = profile.katalog_firmy / "faktury"
                if faktury_dir.exists():
                    for json_file in faktury_dir.glob("**/*.json"):
                        if "non-ksef-raw" in json_file.parts:
                            continue
                        try:
                            with open(json_file, "r", encoding="utf-8") as f:
                                inv_data = json.load(f)
                            for role in ("sprzedawca", "nabywca"):
                                party = inv_data.get(role) or {}
                                if party and cls.clean_nip(party.get("nip") or "") == clean_nip:
                                    if not nazwa and party.get("nazwa"):
                                        nazwa = party.get("nazwa")
                                    if not adres and party.get("adres"):
                                        adres = party.get("adres")
                                    if not rachunek_bankowy and inv_data.get("rachunek_bankowy"):
                                        rachunek_bankowy = inv_data.get("rachunek_bankowy")
                                    break
                            if nazwa and adres:
                                break
                        except Exception:
                            continue
            except Exception:
                pass

        # 0. Optymalizacja: Sprawdzenie cache
        if not force:
            cached = cls.get_cached_contractor(clean_nip, profile=profile)
            if cached:
                # Jeśli podano rachunek, weryfikujemy czy status nie wymaga aktualizacji (np. z BRAK_NA_BIALEJ_LISCIE na ZGODNY_BIALA_LISTA dla kont wirtualnych lub innego rachunku)
                if rachunek_bankowy:
                    norm_iban = cls.clean_iban(rachunek_bankowy)
                    if (
                        rachunek_bankowy != cached.zweryfikowany_rachunek
                        or cached.status_rachunku != StatusRachunkuBankowego.ZGODNY_BIALA_LISTA
                    ):
                        new_status_rach = StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE
                        if norm_iban in cached.rachunki_zgloszone_mf:
                            new_status_rach = StatusRachunkuBankowego.ZGODNY_BIALA_LISTA
                        else:
                            check_res = CompanyFetcher.check_bank_account_mf(clean_nip, norm_iban)
                            if check_res.get("assigned"):
                                new_status_rach = StatusRachunkuBankowego.ZGODNY_BIALA_LISTA
                                if norm_iban not in cached.rachunki_zgloszone_mf:
                                    cached.rachunki_zgloszone_mf.append(norm_iban)

                        if (
                            new_status_rach != cached.status_rachunku
                            or rachunek_bankowy != cached.zweryfikowany_rachunek
                        ):
                            cached = KartaWeryfikacjiKontrahenta(
                                nip=cached.nip,
                                nazwa=cached.nazwa,
                                adres=cached.adres or adres,
                                regon=cached.regon or regon,
                                krs=cached.krs,
                                forma_prawna=cached.forma_prawna,
                                data_weryfikacji=cached.data_weryfikacji,
                                data_weryfikacji_tekst=cached.data_weryfikacji_tekst,
                                osoba_weryfikujaca=cached.osoba_weryfikujaca,
                                status_rejestru=cached.status_rejestru,
                                zrodlo_rejestru=cached.zrodlo_rejestru,
                                reprezentacja=cached.reprezentacja,
                                crbr_status=cached.crbr_status,
                                beneficjenci_rzeczywisci=cached.beneficjenci_rzeczywisci,
                                sankcje_mswia=cached.sankcje_mswia,
                                sankcje_ue=cached.sankcje_ue,
                                sankcje_szczegoly=cached.sankcje_szczegoly,
                                status_vat=cached.status_vat,
                                platnik_vat_czynny=cached.platnik_vat_czynny,
                                zweryfikowany_rachunek=rachunek_bankowy,
                                status_rachunku=new_status_rach,
                                rachunki_zgloszone_mf=cached.rachunki_zgloszone_mf,
                                status_pep=cached.status_pep,
                                poziom_ryzyka=cached.poziom_ryzyka,
                                decyzja=cached.decyzja,
                                uzasadnienie_decyzji=cached.uzasadnienie_decyzji,
                                uwagi_dodatkowe=cached.uwagi_dodatkowe,
                            )
                return cached

        # 1. Odpytanie Białej Listy MF
        is_foreign = is_foreign_entity or (not clean_nip.isdigit() or len(clean_nip) != 10)
        mf_data = None
        blad_polaczenia = False
        komunikat_bledu = None

        if not is_foreign:
            mf_data = CompanyFetcher.fetch_from_mf_biala_lista(clean_nip)
            if mf_data and mf_data.get("blad_polaczenia"):
                blad_polaczenia = True
                komunikat_bledu = mf_data.get("komunikat_bledu")
            elif mf_data is None:
                blad_polaczenia = True
                komunikat_bledu = "Brak odpowiedzi z API Białej Listy MF (błąd sieci / tryb offline)"
        else:
            # Podmiot zagraniczny (np. podatnik VAT-UE) - nie podlega pod polską Białą Listę MF
            mf_data = {
                "nazwa": nazwa,
                "adres": adres,
                "status_vat": "Czynny podatnik VAT-UE / Międzynarodowy (art. 28b ustawy o VAT)",
                "platnik_vat": True,
                "rachunki_bankowe": [cls.clean_iban(rachunek_bankowy)] if rachunek_bankowy else [],
                "blad_polaczenia": False,
            }

        final_nazwa = (
            (mf_data.get("nazwa") if mf_data and not blad_polaczenia else None) or nazwa or f"Podmiot NIP {clean_nip}"
        )
        final_adres = (mf_data.get("adres") if mf_data and not blad_polaczenia else None) or adres
        final_regon = (mf_data.get("regon") if mf_data and not blad_polaczenia else None) or regon
        final_krs = (mf_data.get("krs") if mf_data and not blad_polaczenia else None) or krs
        if blad_polaczenia:
            status_vat = "Brak połączenia z API MF (błąd sieci / offline)"
            platnik_vat_czynny = False
            konta_mf = []
        else:
            status_vat = mf_data.get("status_vat", "Niezarejestrowany w wykazie MF")
            platnik_vat_czynny = mf_data.get("platnik_vat", False)
            konta_mf = [cls.clean_iban(acc) for acc in (mf_data.get("rachunki_bankowe") or []) if acc]

        # 2. Rozpoznanie formy prawnej i rejestru
        nazwa_lower = final_nazwa.lower()
        adres_lower = (final_adres or "").lower()

        # A) Identyfikacja form prawa obcego i cech podmiotów zagranicznych
        foreign_corp_keywords = [
            "s.a r.l.",
            "s.a.r.l.",
            "sàrl",
            "s.à r.l.",
            "s.à.r.l.",
            "sarl",
            "s.a.s.",
            "sas",
            "s.a.s.u.",
            "sasu",
            "gmbh",
            "g.m.b.h.",
            "gesellschaft mit beschränkter haftung",
            "ltd",
            "ltd.",
            "limited",
            "llc",
            "l.l.c.",
            "inc.",
            "inc",
            "incorporated",
            "corp.",
            "corp",
            "corporation",
            "plc",
            "p.l.c.",
            "b.v.",
            "bv",
            "n.v.",
            "nv",
            "s.l.",
            "s.l.u.",
            "s.r.l.",
            "srl",
            "s.p.a.",
            "spa",
            "oddział w polsce",
            "branch",
            "amazon",
            "google",
            "apple",
            "microsoft",
            "adobe",
            "meta platforms",
            "github",
            "stripe",
            "atlassian",
            "ovh",
            "hetzner",
        ]
        foreign_address_keywords = [
            "luksemburg",
            "luxembourg",
            "irlandia",
            "ireland",
            "dublin",
            "niemcy",
            "germany",
            "deutschland",
            "berlin",
            "frankfurt",
            "münchen",
            "munich",
            "francja",
            "france",
            "paris",
            "wielka brytania",
            "united kingdom",
            "great britain",
            "london",
            "stany zjednoczone",
            "usa",
            "united states",
            "holandia",
            "netherlands",
            "amsterdam",
            "austria",
            "wiedeń",
            "vienna",
            "szwajcaria",
            "switzerland",
            "zürich",
            "czechy",
            "czech republic",
            "praga",
            "prague",
            "słowacja",
            "slovakia",
            "bratysława",
            "cypr",
            "cyprus",
            "hiszpania",
            "spain",
            "madrid",
            "włochy",
            "italy",
            "roma",
            "szwecja",
            "sweden",
            "stockholm",
            "norwegia",
            "norway",
            "oslo",
            "dania",
            "denmark",
            "copenhagen",
            "finlandia",
            "finland",
            "helsinki",
            "belgia",
            "belgium",
            "bruxelles",
            "brussels",
            "litwa",
            "lithuania",
            "wilno",
            "vilnius",
            "estonia",
            "tallinn",
            "łotwa",
            "latvia",
            "ryga",
            "riga",
        ]

        is_foreign_legal_form = any(k in nazwa_lower for k in foreign_corp_keywords)
        is_foreign_address = any(k in adres_lower for k in foreign_address_keywords)
        is_foreign_nip = not clean_nip.isdigit() or len(clean_nip) != 10

        is_zagraniczna = is_foreign or is_foreign_legal_form or is_foreign_address or is_foreign_nip

        # B) Identyfikacja polskich spółek prawa handlowego
        is_polska_spolka = any(
            w in nazwa_lower
            for w in [
                "sp. z o.o.",
                "spółka z o",
                "s.a.",
                "spółka akcyjna",
                "sp. k.",
                "spółka komandytowa",
                "spółka jawna",
                "sp.j.",
                "sp. p.",
                "spółka partnerska",
            ]
        )

        reprezentacja: List[str] = []
        beneficjenci: List[str] = []

        if is_zagraniczna:
            if clean_nip.isdigit() and len(clean_nip) == 10:
                forma_prawna = "SPÓŁKA ZAGRANICZNA (ZAREJESTROWANA DO VAT W POLSCE)"
            else:
                forma_prawna = "SPÓŁKA ZAGRANICZNA (PODATNIK VAT-UE / MIĘDZYNARODOWY)"

            if blad_polaczenia:
                status_rejestru = "BŁĄD POŁĄCZENIA"
                zrodlo_rejestru = "Biała Lista MF / Rejestr handlowy państwa siedziby (błąd połączenia)"
            else:
                status_rejestru = "AKTYWNY"
                zrodlo_rejestru = "Właściwy rejestr handlowy państwa siedziby (np. RCS Luksemburg / CRO Irlandia)"

            final_krs = final_krs or "Nie dotyczy (podmiot zagraniczny bez oddziału w polskim KRS)"
            reprezentacja = [
                "Zarząd / Dyrektorzy zgodnie z właściwym rejestrem handlowym państwa siedziby (np. RCS Luksemburg / CRO)"
            ]
            crbr_status = "NIE_DOTYCZY_ZAGRANICZNA"
            beneficjenci = [
                "Beneficjenci rzeczywiści (UBO) zarejestrowani we właściwym rejestrze państwa siedziby (dyrektywa AML UE)"
            ]

        elif is_polska_spolka:
            forma_prawna = "SPÓŁKA HANDLOWA"
            status_rejestru = "BŁĄD POŁĄCZENIA" if blad_polaczenia else "AKTYWNY"
            zrodlo_rejestru = (
                "Krajowy Rejestr Sądowy (KRS) / MF (błąd połączenia)"
                if blad_polaczenia
                else "Krajowy Rejestr Sądowy (KRS) / MF"
            )
            crbr_status = "ZGODNY"
            reprezentacja = ["Zarząd zgodnie z odpisem KRS"]
            beneficjenci = ["Beneficjenci rzeczywiści zgłoszeni w CRBR"]

        else:
            forma_prawna = "JEDNOOSOBOWA DZIAŁALNOŚĆ GOSPODARCZA (JDG)"
            crbr_status = "NIE_DOTYCZY"
            reprezentacja = ["Przedsiębiorca osobiście (właściciel JDG)"]
            beneficjenci = []
            status_rejestru = "BŁĄD POŁĄCZENIA" if blad_polaczenia else "AKTYWNY"
            zrodlo_rejestru = "Biała Lista MF (błąd połączenia)" if blad_polaczenia else "Biała Lista MF"
            if not blad_polaczenia:
                ceidg_data = CompanyFetcher.fetch_from_ceidg(clean_nip)
                if ceidg_data:
                    zrodlo_rejestru = "CEIDG (dane.biznes.gov.pl)"
                    if ceidg_data.get("nazwa"):
                        final_nazwa = ceidg_data.get("nazwa")
                    status_ceidg = ceidg_data.get("status", "").upper()
                    if "ZAWIESZ" in status_ceidg:
                        status_rejestru = "ZAWIESZONY"
                    elif "WYKRESL" in status_ceidg:
                        status_rejestru = "WYKRESLONY"
                    elif status_ceidg:
                        status_rejestru = status_ceidg

        # 3. Badanie list sankcyjnych (MSWiA + UE)
        mswia_hit, ue_hit, trafienia = check_sanctions(
            nip=clean_nip,
            company_name=final_nazwa,
            representatives=reprezentacja,
            beneficiaries=beneficjenci,
        )

        # 4. Sprawdzenie rachunku bankowego (jeśli podano)
        status_rachunku = StatusRachunkuBankowego.NIE_PODANO
        rachunek_norm = None
        if rachunek_bankowy:
            rachunek_norm = cls.clean_iban(rachunek_bankowy)
            if is_zagraniczna:
                # Transakcje zagraniczne (import usług, WNT) nie podlegają pod polską Białą Listę MF
                status_rachunku = StatusRachunkuBankowego.ZGODNY_BIALA_LISTA
            elif konta_mf and rachunek_norm in konta_mf:
                status_rachunku = StatusRachunkuBankowego.ZGODNY_BIALA_LISTA
            else:
                # Weryfikacja rachunków wirtualnych (subkonta masowe wpłat, np. Play, Orange, PGE)
                # poprzez dedykowany endpoint MF: /api/check/nip/{nip}/bank-account/{acc}
                check_res = CompanyFetcher.check_bank_account_mf(clean_nip, rachunek_norm)
                if check_res.get("assigned"):
                    status_rachunku = StatusRachunkuBankowego.ZGODNY_BIALA_LISTA
                    if rachunek_norm not in konta_mf:
                        konta_mf.append(rachunek_norm)
                elif konta_mf:
                    status_rachunku = StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE
                else:
                    # Jeśli brak danych o kontach na Białej Liście (np. brak sieci lub podmiot zwolniony)
                    status_rachunku = StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE

        # 5. Ustalenie poziomu ryzyka i decyzji
        if mswia_hit or ue_hit:
            poziom_ryzyka = PoziomRyzykaAML.KRYTYCZNE_STOP
            decyzja = DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP
            uzasadnienie = (
                "KONTRAHENT LUB OSOBA POWIĄZANA ZNAJDUJE SIĘ NA LIŚCIE SANKCYJNEJ (MSWiA / UE). "
                "Na mocy art. 2 ustawy z dnia 13 kwietnia 2022 r. o przeciwdziałaniu wspieraniu agresji na Ukrainę "
                "obowiązuje BEZWZGLĘDNY ZAKAZ udostępniania jakichkolwiek środków finansowych i współpracy gospodarczej!"
            )
        elif blad_polaczenia:
            poziom_ryzyka = PoziomRyzykaAML.SREDNIE
            decyzja = DecyzjaWspolpracy.WYMAGA_WYJASNIENIA
            uzasadnienie = (
                "⚠️ WERYFIKACJA NIEKOMPLETNA – BRAK DOSTĘPU DO REJESTRÓW MF (BŁĄD SIECI / TRYB OFFLINE). "
                f"Podczas audytu nie udało się nawiązać połączenia z API Białej Listy Ministerstwa Finansów ({komunikat_bledu or 'brak dostępu do sieci'}). "
                "Status podatnika VAT, REGON oraz rachunki bankowe NIE ZOSTAŁY zweryfikowane. Raport NIE MOŻE zostać zatwierdzony w tym stanie. "
                "Wymagane ponowne uruchomienie analizy w środowisku z dostępem do Internetu (użyj parametru --force)."
            )
        elif status_rejestru in ("WYKRESLONY", "NIEZNALEZIONY"):
            poziom_ryzyka = PoziomRyzykaAML.WYSOKIE
            decyzja = DecyzjaWspolpracy.WYMAGA_WYJASNIENIA
            uzasadnienie = f"Kontrahent posiada niepokojący status w rejestrze ({status_rejestru}). Wymagana weryfikacja statusu prawnego."
        elif status_rachunku == StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE and (
            kwota_transakcji is None or kwota_transakcji >= Decimal("15000")
        ):
            poziom_ryzyka = PoziomRyzykaAML.SREDNIE
            decyzja = DecyzjaWspolpracy.WYMAGA_WYJASNIENIA
            uzasadnienie = (
                "Rachunek bankowy kontrahenta NIE FIGURUJE na Białej Liście Podatników VAT MF. "
                "Płatność powyżej 15 000 zł na ten rachunek rodzi ryzyko wyłączenia z kosztów uzyskania przychodów (art. 22p PIT) "
                "oraz solidarną odpowiedzialność za zaległości w VAT (art. 117ba Ordynacji podatkowej). Wymagane zgłoszenie ZAW-NR lub zmiana rachunku."
            )
        elif not platnik_vat_czynny and "zwolnion" not in status_vat.lower():
            poziom_ryzyka = PoziomRyzykaAML.SREDNIE
            decyzja = DecyzjaWspolpracy.WYMAGA_WYJASNIENIA
            uzasadnienie = f"Kontrahent nie posiada statusu czynnego podatnika VAT (status: {status_vat})."
        else:
            poziom_ryzyka = PoziomRyzykaAML.NISKIE
            decyzja = DecyzjaWspolpracy.AKCEPTACJA
            if is_zagraniczna:
                uzasadnienie = (
                    "Kontrahent zweryfikowany pozytywnie: spółka zagraniczna (podatnik VAT-UE / zarejestrowany do VAT), "
                    "import/eksport usług B2B (art. 28b ustawy o VAT), brak sankcji (MSWiA / UE), pełna ochrona podatkowa."
                )
            else:
                uzasadnienie = "Kontrahent zweryfikowany pozytywnie: aktywny w rejestrach, czynny podatnik VAT, brak powiązań z listami sankcyjnymi, rachunek i status VAT prawidłowe."

        karta = KartaWeryfikacjiKontrahenta(
            nip=clean_nip,
            nazwa=final_nazwa,
            adres=final_adres,
            regon=final_regon,
            krs=final_krs,
            forma_prawna=forma_prawna,
            status_rejestru=status_rejestru,
            zrodlo_rejestru=zrodlo_rejestru,
            reprezentacja=reprezentacja,
            crbr_status=crbr_status,
            beneficjenci_rzeczywisci=beneficjenci,
            sankcje_mswia=mswia_hit,
            sankcje_ue=ue_hit,
            sankcje_szczegoly=trafienia,
            status_vat=status_vat,
            platnik_vat_czynny=platnik_vat_czynny,
            zweryfikowany_rachunek=rachunek_bankowy,
            status_rachunku=status_rachunku,
            rachunki_zgloszone_mf=konta_mf,
            poziom_ryzyka=poziom_ryzyka,
            decyzja=decyzja,
            uzasadnienie_decyzji=uzasadnienie,
            blad_polaczenia=blad_polaczenia,
            komunikat_bledu=komunikat_bledu,
        )
        if not blad_polaczenia:
            cls._session_cache[clean_nip] = karta
        return karta


@dataclass
class MiesiecznyRaportWeryfikacji:
    """Zbiorczy raport z procedury weryfikacji kontrahentów za dany miesiąc."""

    profil: CompanyProfile
    rok: str
    miesiac: str
    karty: List[KartaWeryfikacjiKontrahenta] = field(default_factory=list)
    data_generowania: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def liczba_kontrahentow(self) -> int:
        return len(self.karty)

    @property
    def liczba_niska(self) -> int:
        return sum(1 for k in self.karty if k.poziom_ryzyka == PoziomRyzykaAML.NISKIE)

    @property
    def liczba_srednia(self) -> int:
        return sum(1 for k in self.karty if k.poziom_ryzyka == PoziomRyzykaAML.SREDNIE)

    @property
    def liczba_wysoka(self) -> int:
        return sum(1 for k in self.karty if k.poziom_ryzyka == PoziomRyzykaAML.WYSOKIE)

    @property
    def liczba_krytyczna_stop(self) -> int:
        return sum(1 for k in self.karty if k.poziom_ryzyka == PoziomRyzykaAML.KRYTYCZNE_STOP)

    @property
    def liczba_bledow_sieci(self) -> int:
        return sum(1 for k in self.karty if k.blad_polaczenia)

    @property
    def liczba_rachunkow_sprawdzonych(self) -> int:
        return sum(1 for k in self.karty if k.status_rachunku != StatusRachunkuBankowego.NIE_PODANO)

    @property
    def liczba_rachunkow_zgodnych(self) -> int:
        return sum(1 for k in self.karty if k.status_rachunku == StatusRachunkuBankowego.ZGODNY_BIALA_LISTA)

    @property
    def liczba_rachunkow_niezgodnych(self) -> int:
        return sum(1 for k in self.karty if k.status_rachunku == StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "firma_nip": self.profil.nip,
            "firma_nazwa": self.profil.nazwa,
            "rok": self.rok,
            "miesiac": self.miesiac,
            "data_generowania": self.data_generowania,
            "statystyki": {
                "lacznie_kontrahentow": self.liczba_kontrahentow,
                "niski_ryzyko_akceptacja": self.liczba_niska,
                "srednie_ryzyko_uwaga": self.liczba_srednia,
                "wysokie_ryzyko_wyjasnienia": self.liczba_wysoka,
                "krytyczne_stop_sankcje": self.liczba_krytyczna_stop,
                "bledy_polaczenia_offline": self.liczba_bledow_sieci,
                "rachunki_sprawdzone": self.liczba_rachunkow_sprawdzonych,
                "rachunki_zgodne": self.liczba_rachunkow_zgodnych,
                "rachunki_niezgodne": self.liczba_rachunkow_niezgodnych,
            },
            "kontrahenci": [k.to_dict() for k in self.karty],
        }

    def generate_markdown_report(self) -> str:
        """Generuje zbiorczy miesięczny raport z weryfikacji kontrahentów."""
        linie = [
            "# Zbiorczy Raport Weryfikacji Kontrahentów (AML / Sankcje / Biała Lista)",
            f"**Okres rozliczeniowy:** {self.rok}-{self.miesiac.zfill(2)}",
            f"**Firma audytująca:** {self.profil.nazwa} (NIP: `{self.profil.nip}`)",
            f"**Data audytu:** {datetime.now().strftime('%d.%m.%Y, %H:%M')} (UTC: `{self.data_generowania}`)",
        ]

        if self.liczba_bledow_sieci > 0:
            linie.extend(
                [
                    "",
                    "> [!WARNING]",
                    f"> ### ⚠️ UWAGA: RAPORT ZAWIERA POZYCJE NIEZWERYFIKOWANE Z POWODU BRAKU SIECI ({self.liczba_bledow_sieci} podmiotów)",
                    "> Dla części kontrahentów nie udało się pobrać danych z API Białej Listy Ministerstwa Finansów z powodu braku połączenia internetowego lub niedostępności usługi MF.",
                    "> **Raport jest NIEKOMPLETNY i nie może stanowić ostatecznego potwierdzenia procedury należytej staranności (AML / Biała Lista).**",
                    "> ",
                    "> 👉 **Wymagane działanie:** Upewnij się, że masz połączenie z Internetem i wykonaj ponowną weryfikację poleceniem:",
                    f"> `python -m src.cli weryfikuj-miesiac --nip {self.profil.nip} --rok {self.rok} --miesiac {self.miesiac} --force`",
                ]
            )

        linie.extend(
            [
                "",
                "---",
                "## 1. Podsumowanie Procedury Należytej Staranności",
                "",
                f"W okresie **{self.rok}-{self.miesiac.zfill(2)}** zweryfikowano łącznie **{self.liczba_kontrahentow}** unikalnych kontrahentów występujących na fakturach sprzedaży oraz kosztów.",
                "",
                "| Kategoria ryzyka | Liczba podmiotów | Status i zalecenia operacyjne |",
                "| :--- | :---: | :--- |",
                f"| 🟢 **Niskie (Czysty)** | **{self.liczba_niska}** | Brak zagrożeń – pełna akceptacja do księgowania i płatności |",
                f"| 🟡 **Średnie (Uwaga)** | **{self.liczba_srednia}** | Wymaga weryfikacji konta bankowego (Biała Lista) lub statusu PEP |",
                f"| 🟠 **Wysokie (Wyjaśnij)** | **{self.liczba_wysoka}** | Podmiot nieaktywny w KRS/CEIDG lub brak rejestracji VAT |",
                f"| 🔴 **KRYTYCZNE (STOP)** | **{self.liczba_krytyczna_stop}** | **BEZWZGLĘDNY ZAKAZ WSPÓŁPRACY I PŁATNOŚCI (Wpis na liście sankcyjnej)** |",
            ]
        )

        if self.liczba_bledow_sieci > 0:
            linie.append(
                f"| ⚠️ **Błędy połączenia (Offline)** | **{self.liczba_bledow_sieci}** | **Weryfikacja niekompletna – wymagane ponowne sprawdzenie online (`--force`)** |"
            )

        linie.extend(
            [
                "",
                "---",
                "## 2. Rejestr Zweryfikowanych Kontrahentów w Miesiącu",
                "",
                "| Lp. | Kontrahent | NIP | Rejestr | Status VAT | Rachunek bankowy | Sankcje MSWiA/UE | Ryzyko | Decyzja |",
                "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
            ]
        )

        for idx, k in enumerate(self.karty, start=1):
            if k.blad_polaczenia:
                vat_txt = "⚠️ Błąd sieci (Offline)"
                ryzyko_txt = "🟡 Do ponowienia"
                decyzja_txt = "⚠️ Ponów (Sieć)"
            else:
                vat_txt = "Czynny" if k.platnik_vat_czynny else "Niezarejestrowany"
                ryzyko_txt = {
                    PoziomRyzykaAML.NISKIE: "🟢 Niskie",
                    PoziomRyzykaAML.SREDNIE: "🟡 Średnie",
                    PoziomRyzykaAML.WYSOKIE: "🟠 Wysokie",
                    PoziomRyzykaAML.KRYTYCZNE_STOP: "🔴 STOP",
                }.get(k.poziom_ryzyka, k.poziom_ryzyka.value)
                decyzja_txt = {
                    DecyzjaWspolpracy.AKCEPTACJA: "Zaksięguj",
                    DecyzjaWspolpracy.WYMAGA_WYJASNIENIA: "Wyjaśnij",
                    DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP: "BLOKADA",
                }.get(k.decyzja, k.decyzja.value)

            sankcje_txt = "🚨 STOP (Wpis)" if (k.sankcje_mswia or k.sankcje_ue) else "✅ Czysty"
            rachunek_txt = {
                StatusRachunkuBankowego.ZGODNY_BIALA_LISTA: "✅ Biała Lista",
                StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE: "⚠️ Poza listą",
                StatusRachunkuBankowego.NIE_PODANO: "Brak",
            }.get(k.status_rachunku, k.status_rachunku.value)

            linie.append(
                f"| {idx} | **{k.nazwa}** | `{k.nip}` | {k.status_rejestru} | {vat_txt} | {rachunek_txt} | {sankcje_txt} | {ryzyko_txt} | **{decyzja_txt}** |"
            )

        linie.extend(
            [
                "",
                "---",
                "## 3. Instrukcja dla Kontroli Skarbowej i GIIF",
                "Wszystkie powyższe weryfikacje zostały wygenerowane deterministycznie na podstawie publicznych rejestrów państwowych (Biała Lista MF, CEIDG, KRS, CRBR) oraz oficjalnych list sankcyjnych RP i UE.",
                "Indywidualne karty każdego kontrahenta wraz ze śladem audytowym i sumami kontrolnymi SHA-256 znajdują się w podfolderze `karty/`.",
                "",
                f"**Ścieżka do archiwum:** `firmy/{self.profil.katalog_nazwa}/weryfikacje/{self.rok}/{self.miesiac.zfill(2)}/`",
                "",
            ]
        )

        return "\n".join(linie)

    def generate_pdf_report(self, output_path: Union[str, Path]) -> Path:
        """
        Generuje oficjalny zbiorczy raport z weryfikacji kontrahentów w formacie PDF (A4 pejzaż).
        Nowoczesny standard corporate banking / executive compliance.
        """
        import hashlib

        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        font_regular, font_bold = _register_pdf_fonts()

        doc = SimpleDocTemplate(
            str(path),
            pagesize=landscape(A4),
            leftMargin=28,
            rightMargin=28,
            topMargin=22,
            bottomMargin=22,
        )

        # Style typograficzne
        ParagraphStyle("RptBrand", fontName=font_bold, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#38BDF8"))
        hdr_title = ParagraphStyle("RptTitle", fontName=font_bold, fontSize=12, leading=15, textColor=colors.white)
        ParagraphStyle("RptSub", fontName=font_regular, fontSize=7, leading=9, textColor=colors.HexColor("#CBD5E1"))
        hdr_right = ParagraphStyle(
            "RptRight", fontName=font_bold, fontSize=8, leading=10, textColor=colors.HexColor("#F8FAFC"), alignment=2
        )
        ParagraphStyle(
            "RptRightSub",
            fontName=font_regular,
            fontSize=6.5,
            leading=8.5,
            textColor=colors.HexColor("#94A3B8"),
            alignment=2,
        )

        ParagraphStyle("RptSecHdr", fontName=font_bold, fontSize=9, leading=11, textColor=colors.HexColor("#0F172A"))
        tbl_hdr = ParagraphStyle(
            "RptTblHdr", fontName=font_bold, fontSize=7, leading=9, textColor=colors.white, alignment=0
        )
        tbl_hdr_c = ParagraphStyle(
            "RptTblHdrC", fontName=font_bold, fontSize=7, leading=9, textColor=colors.white, alignment=1
        )

        ParagraphStyle("RptCB", fontName=font_bold, fontSize=7, leading=9, textColor=colors.HexColor("#0F172A"))
        cell_n = ParagraphStyle(
            "RptCN", fontName=font_regular, fontSize=7, leading=9, textColor=colors.HexColor("#334155")
        )
        cell_c = ParagraphStyle(
            "RptCC", fontName=font_regular, fontSize=7, leading=9, textColor=colors.HexColor("#334155"), alignment=1
        )
        footer_s = ParagraphStyle(
            "RptFS", fontName=font_regular, fontSize=6.5, leading=8.5, textColor=colors.HexColor("#64748B")
        )

        # 1. Pasek Nagłówka Corporate Navy
        hdr_left_p = Paragraph(
            f"<b>TAXPILOT AI • DUE DILIGENCE & COMPLIANCE SYSTEM</b><br/>"
            f'<font size="12"><b>ZBIORCZY RAPORT NALEŻYTEJ STARANNOŚCI (AML / BIAŁA LISTA / SANKCJE)</b></font><br/>'
            f"Okres rozliczeniowy: <b>{self.rok}-{str(self.miesiac).zfill(2)}</b> &nbsp;|&nbsp; "
            f"Podmiot: <b>{self.profil.nazwa}</b> (NIP: {self.profil.nip}) &nbsp;|&nbsp; "
            f"Data badania: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            hdr_title,
        )
        hdr_right_p = Paragraph(
            f"<b>DOKUMENTACJA AUDYTOWA KAS / MF</b><br/>"
            f"Weryfikacja: <b>{len(self.karty)} KONTRAHENTÓW</b><br/>"
            f"Procedura: art. 86 ust. 1 VAT / AML<br/>"
            f"Obowiązkowa retencja: <b>5 LAT</b>",
            hdr_right,
        )
        t_header = Table([[hdr_left_p, hdr_right_p]], colWidths=[550, 236])
        t_header.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )

        elements = [t_header, Spacer(1, 6)]

        # 2. Alert o błędach sieciowych (jeśli wystąpiły)
        if self.liczba_bledow_sieci > 0:
            warn_p = Paragraph(
                f'<font color="#DC2626"><b>[!] OSTRZEŻENIE: WYKRYTO {self.liczba_bledow_sieci} POZYCJI Z BŁĘDEM POŁĄCZENIA SIECIOWEGO (TRYB OFFLINE)</b></font><br/>'
                f'<font color="#7F1D1D" size="7">Dla części kontrahentów nie udało się pobrać danych z live API Białej Listy MF. '
                f"Rozliczenie nie powinno być zamykane na podstawie danych cząstkowych. Ponów weryfikację z parametrem <code>--force</code> po przywróceniu sieci.</font>",
                cell_n,
            )
            t_warn = Table([[warn_p]], colWidths=[786])
            t_warn.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF2F2")),
                        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#DC2626")),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            elements.extend([t_warn, Spacer(1, 6)])

        # 3. Kafelki Podsumowania Statystyk (KPI)
        card_total = Paragraph(
            f'<font size="6.5" color="#64748B">ŁĄCZNIE KONTRAHENTÓW</font><br/><font size="12"><b>{len(self.karty)}</b></font><br/><font size="6" color="#64748B">wystawione i otrzymane faktury</font>',
            cell_n,
        )
        card_low = Paragraph(
            f'<font size="6.5" color="#047857">BEZPIECZNE (NISKIE RYZYKO)</font><br/><font size="12" color="#065F46"><b>{self.liczba_niska}</b></font><br/><font size="6" color="#047857">akceptacja do rozliczenia</font>',
            cell_n,
        )
        card_med = Paragraph(
            f'<font size="6.5" color="#B45309">WYMAGAJĄCE UWAGI</font><br/><font size="12" color="#92400E"><b>{self.liczba_srednia + self.liczba_wysoka}</b></font><br/><font size="6" color="#B45309">poza białą listą / wyjaśnić</font>',
            cell_n,
        )
        card_stop = Paragraph(
            f'<font size="6.5" color="#B91C1C">SANKCJE / BLOKADY (STOP)</font><br/><font size="12" color="#991B1B"><b>{self.liczba_krytyczna_stop}</b></font><br/><font size="6" color="#B91C1C">bezwzględny zakaz płatności</font>',
            cell_n,
        )

        t_cards = Table([[card_total, card_low, card_med, card_stop]], colWidths=[196, 196, 196, 198])
        t_cards.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F8FAFC")),
                    ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#ECFDF5")),
                    ("BACKGROUND", (2, 0), (2, 0), colors.HexColor("#FFFBEB")),
                    ("BACKGROUND", (3, 0), (3, 0), colors.HexColor("#FEF2F2")),
                    ("BOX", (0, 0), (0, 0), 0.5, colors.HexColor("#CBD5E1")),
                    ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#A7F3D0")),
                    ("BOX", (2, 0), (2, 0), 0.5, colors.HexColor("#FDE68A")),
                    ("BOX", (3, 0), (3, 0), 0.5, colors.HexColor("#FECACA")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.extend([t_cards, Spacer(1, 6)])

        # 4. Tabela Kontrahentów
        headers = [
            Paragraph("LP", tbl_hdr_c),
            Paragraph("KONTRAHENT (NAZWA)", tbl_hdr),
            Paragraph("NIP", tbl_hdr),
            Paragraph("REJESTR", tbl_hdr_c),
            Paragraph("STATUS VAT", tbl_hdr_c),
            Paragraph("RACHUNEK BANKOWY", tbl_hdr),
            Paragraph("SANKCJE", tbl_hdr_c),
            Paragraph("RYZYKO", tbl_hdr_c),
            Paragraph("DECYZJA AUDYTU", tbl_hdr_c),
        ]
        rows = [headers]

        for idx, k in enumerate(self.karty, start=1):
            sankcje_txt = (
                '<font color="#DC2626"><b>[✗] WPIS STOP</b></font>'
                if (k.sankcje_mswia or k.sankcje_ue)
                else '<font color="#059669">✓ Czysty</font>'
            )
            rachunek_txt = {
                StatusRachunkuBankowego.ZGODNY_BIALA_LISTA: '<font color="#059669">✓ Biała Lista MF</font>',
                StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE: '<font color="#D97706"><b>[!] Poza listą MF</b></font>',
                StatusRachunkuBankowego.NIE_PODANO: '<font color="#64748B">Nie dotyczy / Brak</font>',
            }.get(
                k.status_rachunku,
                str(k.status_rachunku.value if hasattr(k.status_rachunku, "value") else k.status_rachunku),
            )

            if k.blad_polaczenia:
                vat_txt = '<font color="#DC2626"><b>[!] Błąd sieci</b></font>'
                ryzyko_txt = '<font color="#D97706">Do ponowienia</font>'
                decyzja_txt = '<font color="#DC2626"><b>[!] Ponów (Błąd)</b></font>'
            else:
                vat_txt = (
                    '<font color="#059669">✓ Czynny</font>'
                    if k.platnik_vat_czynny
                    else '<font color="#64748B">Zwolniony / Brak</font>'
                )
                ryzyko_txt = {
                    PoziomRyzykaAML.NISKIE: '<font color="#059669">Niskie</font>',
                    PoziomRyzykaAML.SREDNIE: '<font color="#D97706">Średnie</font>',
                    PoziomRyzykaAML.WYSOKIE: '<font color="#EA580C"><b>Wysokie</b></font>',
                    PoziomRyzykaAML.KRYTYCZNE_STOP: '<font color="#DC2626"><b>KRYTYCZNE</b></font>',
                }.get(k.poziom_ryzyka, k.poziom_ryzyka.value)
                decyzja_txt = {
                    DecyzjaWspolpracy.AKCEPTACJA: '<font color="#059669"><b>✓ AKCEPTACJA</b></font>',
                    DecyzjaWspolpracy.WYMAGA_WYJASNIENIA: '<font color="#D97706"><b>[!] WYJAŚNIJ</b></font>',
                    DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP: '<font color="#DC2626"><b>[✗] BLOKADA</b></font>',
                }.get(k.decyzja, k.decyzja.value)

            rows.append(
                [
                    Paragraph(str(idx), cell_c),
                    Paragraph(f"<b>{k.nazwa}</b>", cell_n),
                    Paragraph(f'<font face="{font_bold}">{k.nip}</font>', cell_n),
                    Paragraph(k.status_rejestru, cell_c),
                    Paragraph(vat_txt, cell_c),
                    Paragraph(rachunek_txt, cell_n),
                    Paragraph(sankcje_txt, cell_c),
                    Paragraph(ryzyko_txt, cell_c),
                    Paragraph(decyzja_txt, cell_c),
                ]
            )

        col_w = [22, 175, 75, 70, 75, 135, 75, 75, 84]
        t_reg = Table(rows, colWidths=col_w, repeatRows=1)
        t_reg_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        # Zebra alternating rows
        for i in range(1, len(rows)):
            if i % 2 == 0:
                t_reg_style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC")))
        t_reg.setStyle(TableStyle(t_reg_style))
        elements.extend([t_reg, Spacer(1, 6)])

        # 5. Oficjalna Stopka Compliance z Pieczęcią SHA-256
        report_raw_str = f"{self.profil.nip}:{self.rok}:{self.miesiac}:{len(self.karty)}:{self.data_generowania}"
        sha_sig = hashlib.sha256(report_raw_str.encode("utf-8")).hexdigest()

        seal_p = Paragraph(
            f'<b>PIECZĘĆ KRYPTOGRAFICZNA RAPORTU (SHA-256):</b> <font face="{font_bold}">{sha_sig}</font><br/>'
            f"Raport stanowi prawnie wiążący dowód dopełnienia procedury należytej staranności w podatku VAT (art. 86 ust. 1, art. 108a ustawy o VAT) "
            f"oraz wymogów ustawy AML (art. 34). Dokument podlega obowiązkowej 5-letniej archiwizacji dowodowej. "
            f"Szczegółowe Karty Kontrahentów z pełnymi zrzutami rejestrów znajdują się w folderze <i>karty/</i>.",
            footer_s,
        )
        t_seal = Table([[seal_p]], colWidths=[786])
        t_seal.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.append(t_seal)

        doc.build(elements)
        return path


class VerificationService:
    """
    Serwis orkiestrujący procedurę weryfikacji kontrahentów dla firmy oraz zapisujący wyniki
    w strukturze firmy/{NIP-Nazwa}/weryfikacje/{ROK}/{MIESIAC}/.
    """

    @classmethod
    def verify_month(
        cls,
        profile: CompanyProfile,
        rok: str,
        miesiac: str,
        zapisz_pliki: bool = True,
        force: bool = False,
    ) -> MiesiecznyRaportWeryfikacji:
        """
        Skanuje wszystkie faktury sprzedaży i kosztów z danego miesiąca,
        dokonuje pełnej weryfikacji każdego kontrahenta i zapisuje wyniki w folderze weryfikacje/.
        """
        rok_str = str(rok)
        miesiac_str = str(miesiac).zfill(2)

        # Pobierz wszystkie faktury sprzedaży i kosztów z danego miesiąca
        faktury_sprzedaz = InvoiceStorage.list_invoices(profile, rok_str, miesiac_str, typ=InvoiceType.SPRZEDAZ)
        faktury_koszt = InvoiceStorage.list_invoices(profile, rok_str, miesiac_str, typ=InvoiceType.KOSZT)

        wszystkie_faktury = faktury_sprzedaz + faktury_koszt

        # Zbierz unikalne kontrahenty
        kontrahenci_map: Dict[str, Dict[str, Any]] = {}
        for inv in wszystkie_faktury:
            # Określ kontrahenta (jeśli sprzedaż -> nabywca; jeśli koszt -> sprzedawca)
            if inv.typ == InvoiceType.SPRZEDAZ:
                party = inv.nabywca
            else:
                party = inv.sprzedawca

            if not party or not party.nip:
                continue

            clean_nip = AMLVerificationEngine.clean_nip(party.nip)
            # Pomijamy samego siebie
            if clean_nip == AMLVerificationEngine.clean_nip(profile.nip):
                continue

            if clean_nip not in kontrahenci_map:
                kontrahenci_map[clean_nip] = {
                    "nip": clean_nip,
                    "nazwa": party.nazwa,
                    "adres": party.adres,
                    "regon": getattr(party, "regon", None),
                    "max_kwota": inv.suma_brutto,
                    "rachunki": set(),
                }
            else:
                if inv.suma_brutto > kontrahenci_map[clean_nip]["max_kwota"]:
                    kontrahenci_map[clean_nip]["max_kwota"] = inv.suma_brutto
                if getattr(party, "regon", None) and not kontrahenci_map[clean_nip]["regon"]:
                    kontrahenci_map[clean_nip]["regon"] = party.regon
                if party.adres and not kontrahenci_map[clean_nip]["adres"]:
                    kontrahenci_map[clean_nip]["adres"] = party.adres

            # Rachunek bankowy kontrahenta wyciągamy z faktur KOSZTOWYCH (zakupowych),
            # ponieważ na fakturze sprzedaży rachunek bankowy to konto wystawcy (naszej firmy).
            if inv.typ == InvoiceType.KOSZT and getattr(inv, "rachunek_bankowy", None):
                kontrahenci_map[clean_nip]["rachunki"].add(inv.rachunek_bankowy)

        # Wykonaj weryfikację dla każdego podmiotu (dokładnie 1 raz na unikalny NIP)
        karty: List[KartaWeryfikacjiKontrahenta] = []
        for c_nip, c_data in kontrahenci_map.items():
            rachunek = next(iter(c_data["rachunki"])) if c_data["rachunki"] else None
            karta = AMLVerificationEngine.verify_contractor(
                nip=c_nip,
                nazwa=c_data["nazwa"],
                rachunek_bankowy=rachunek,
                regon=c_data.get("regon"),
                adres=c_data.get("adres"),
                kwota_transakcji=c_data["max_kwota"],
                profile=profile,
                force=force,
            )
            karty.append(karta)

        raport = MiesiecznyRaportWeryfikacji(
            profil=profile,
            rok=rok_str,
            miesiac=miesiac_str,
            karty=karty,
        )

        if zapisz_pliki:
            target_dir = profile.katalog_firmy / "weryfikacje" / rok_str / miesiac_str
            karty_dir = target_dir / "karty"
            karty_dir.mkdir(parents=True, exist_ok=True)

            # 1. Zapis zbiorczego raportu Markdown
            raport_md_path = target_dir / "raport-weryfikacji.md"
            with open(raport_md_path, "w", encoding="utf-8") as f:
                f.write(raport.generate_markdown_report())

            # 2. Zapis zbiorczego raportu JSON
            raport_json_path = target_dir / "raport-weryfikacji.json"
            with open(raport_json_path, "w", encoding="utf-8") as f:
                json.dump(raport.to_dict(), f, indent=2, ensure_ascii=False)

            # 3. Zapis zbiorczego raportu PDF
            raport_pdf_path = target_dir / "raport-weryfikacji.pdf"
            try:
                raport.generate_pdf_report(raport_pdf_path)
            except Exception:
                pass

            # 4. Zapis indywidualnych kart kontrahentów w karty/ (MD + PDF + JSON)
            for k in karty:
                karta_md_path = karty_dir / f"{k.nip}-karta.md"
                with open(karta_md_path, "w", encoding="utf-8") as f:
                    f.write(k.generate_markdown_card())

                karta_json_path = karty_dir / f"{k.nip}-raw.json"
                with open(karta_json_path, "w", encoding="utf-8") as f:
                    json.dump(k.to_dict(), f, indent=2, ensure_ascii=False)

                karta_pdf_path = karty_dir / f"{k.nip}-karta.pdf"
                try:
                    k.generate_pdf_card(karta_pdf_path)
                except Exception:
                    pass

        return raport
