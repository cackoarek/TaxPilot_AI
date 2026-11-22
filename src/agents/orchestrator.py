"""
Główny Agent Koordynator (Tax Orchestrator Agent).
Integruje deterministyczne narzędzia z modelami AI (Claude, GPT, Gemini) za pomocą uniwersalnych deklaracji Function Calling / Tool Use.
"""

from decimal import Decimal
from typing import Any, Dict, List

from src.core.company import CompanyProfile
from src.level_1_ingestion.ksef_client import KSeFClient
from src.level_3_tax_settlement.settlement_service import SettlementService
from src.skills.pre_settlement_review import PreSettlementReview
from src.skills.tax_advisor_tools import audit_expense_leaks, simulate_tax_regimes

# Uniwersalne definicje narzędzi (kompatybilne ze standardem JSON Schema / OpenAPI)
AGENT_TOOL_DECLARATIONS = [
    {
        "name": "sync_ksef_invoices",
        "description": "Pobiera i synchronizuje faktury sprzedaży i zakupu z Krajowego Systemu e-Faktur (KSeF 2.0) za wskazany miesiąc i rok.",
        "parameters": {
            "type": "object",
            "properties": {
                "nip": {"type": "string", "description": "NIP rozliczanej firmy (np. '7770001122')"},
                "rok": {"type": "string", "description": "Rok podatkowy (np. '2026')"},
                "miesiac": {"type": "string", "description": "Miesiąc w formacie dwucyfrowym (np. '10')"},
            },
            "required": ["rok", "miesiac"],
        },
    },
    {
        "name": "review_month_invoices",
        "description": "Generuje wstępny przegląd dokumentów przed rozliczeniem: tabelę sprzedaży (przychody), tabelę kosztów (do akceptacji) oraz tabelę pozycji do wyjaśnienia.",
        "parameters": {
            "type": "object",
            "properties": {
                "nip": {"type": "string", "description": "NIP rozliczanej firmy"},
                "rok": {"type": "string", "description": "Rok podatkowy"},
                "miesiac": {"type": "string", "description": "Miesiąc (01-12)"},
            },
            "required": ["rok", "miesiac"],
        },
    },
    {
        "name": "settle_month",
        "description": "Przeprowadza pełne, deterministyczne rozliczenie podatkowo-składkowe za dany miesiąc: oblicza ZUS, PIT-28, VAT-7 i generuje Paczkę Przelewów Podatnika.",
        "parameters": {
            "type": "object",
            "properties": {
                "nip": {"type": "string", "description": "NIP rozliczanej firmy"},
                "rok": {"type": "string", "description": "Rok podatkowy"},
                "miesiac": {"type": "string", "description": "Miesiąc (01-12)"},
                "nadwyzka_vat": {
                    "type": "number",
                    "description": "Opcjonalna nadwyżka VAT z poprzedniego miesiąca",
                    "default": 0.0,
                },
            },
            "required": ["rok", "miesiac"],
        },
    },
    {
        "name": "simulate_tax_regimes",
        "description": "Porównuje łączne obciążenia (ZUS + PIT) i dochód netto na rękę dla: Ryczałtu, Podatku Liniowego 19% oraz Skali Podatkowej 12%/32%.",
        "parameters": {
            "type": "object",
            "properties": {
                "przychody_roczne": {"type": "number", "description": "Szacowany roczny przychód netto w PLN"},
                "koszty_roczne": {"type": "number", "description": "Szacowane roczne koszty netto w PLN"},
                "stawka_ryczaltu": {
                    "type": "number",
                    "description": "Stawka ryczałtu dla działalności (np. 0.12 dla IT)",
                    "default": 0.12,
                },
                "rok": {"type": "string", "description": "Rok podatkowy (np. '2026')", "default": "2026"},
            },
            "required": ["przychody_roczne", "koszty_roczne"],
        },
    },
    {
        "name": "audit_expense_leaks",
        "description": "Audytuje koszty z ostatnich miesięcy w poszukiwaniu brakujących comiesięcznych faktur (np. leasing, serwery, telefon).",
        "parameters": {
            "type": "object",
            "properties": {
                "nip": {"type": "string", "description": "NIP firmy"},
                "rok": {"type": "string", "description": "Rok podatkowy"},
                "miesiac": {"type": "string", "description": "Miesiąc"},
            },
            "required": ["rok", "miesiac"],
        },
    },
    {
        "name": "learn_cost_rule",
        "description": "Zapisuje trwałą regułę kwalifikacji kosztów dla kontrahenta na podstawie decyzji przedsiębiorcy.",
        "parameters": {
            "type": "object",
            "properties": {
                "nip": {"type": "string", "description": "NIP rozliczanej firmy"},
                "kontrahent_nip": {"type": "string", "description": "Opcjonalny NIP kontrahenta (np. '9512120077')"},
                "wzorzec": {"type": "string", "description": "Wzorzec tekstu pozycji (np. 'usługi inne', 'tv')"},
                "kwalifikacja": {"type": "string", "enum": ["FIRMOWY_100", "SAMOCHOD_50", "PRYWATNY_0"]},
                "uzasadnienie": {"type": "string", "description": "Uzasadnienie podatkowe decyzji"},
            },
            "required": ["wzorzec", "kwalifikacja"],
        },
    },
    {
        "name": "extract_non_ksef_invoices",
        "description": "Ekstrahuje dokumenty kosztowe z folderu koszty/non-ksef-raw/ (PDF, JSON, TXT) do znormalizowanych encji w koszty/non-ksef-extracted/.",
        "parameters": {
            "type": "object",
            "properties": {
                "nip": {"type": "string", "description": "NIP rozliczanej firmy"},
                "rok": {"type": "string", "description": "Rok podatkowy"},
                "miesiac": {"type": "string", "description": "Miesiąc (01-12)"},
                "force": {"type": "boolean", "description": "Wymuszenie ponownej ekstrakcji", "default": False},
            },
            "required": ["rok", "miesiac"],
        },
    },
    {
        "name": "init_company",
        "description": "Inicjalizuje nowy profil firmy dla użytkownika (onboarding), pobiera dane rejestrowe z Białej Listy MF i CEIDG oraz zakłada strukturę katalogów.",
        "parameters": {
            "type": "object",
            "properties": {
                "nip": {"type": "string", "description": "10-cyfrowy NIP firmy"},
                "nazwa": {
                    "type": "string",
                    "description": "Opcjonalna nazwa firmy (jeśli nie podano, pobrana z rejestru)",
                },
                "forma_opodatkowania": {
                    "type": "string",
                    "enum": ["RYCZALT", "LINIOWY", "SKALA"],
                    "default": "RYCZALT",
                },
                "stawka_ryczaltu": {
                    "type": "number",
                    "description": "Domyślna stawka ryczałtu (np. 0.12 dla IT)",
                    "default": 0.12,
                },
                "platnik_vat": {"type": "boolean", "default": True},
                "zus_typ": {
                    "type": "string",
                    "enum": ["PELNY_ZUS", "MALY_ZUS_PLUS", "ULGA_NA_START", "TYLKO_ZDROWOTNA"],
                    "default": "PELNY_ZUS",
                },
                "chorobowe_dobrowolne": {"type": "boolean", "default": True},
                "kody_pkd": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista kodów PKD (np. ['62.01.Z', '62.02.Z'])",
                },
                "token_ksef": {"type": "string", "description": "Opcjonalny token KSeF podany przez użytkownika"},
                "srodowisko_ksef": {"type": "string", "enum": ["TEST", "PROD"], "default": "PROD"},
            },
            "required": ["nip"],
        },
    },
]

# Wsteczna kompatybilność oraz adaptery dla dostawców LLM
GEMINI_TOOL_DECLARATIONS = AGENT_TOOL_DECLARATIONS


def get_openai_tools() -> List[Dict[str, Any]]:
    """Zwraca deklaracje narzędzi w standardowym formacie OpenAI / ChatGPT."""
    return [{"type": "function", "function": tool} for tool in AGENT_TOOL_DECLARATIONS]


def get_anthropic_tools() -> List[Dict[str, Any]]:
    """Zwraca deklaracje narzędzi w formacie Anthropic / Claude."""
    return [
        {"name": tool["name"], "description": tool["description"], "input_schema": tool["parameters"]}
        for tool in AGENT_TOOL_DECLARATIONS
    ]


class TaxOrchestrator:
    """
    Dyspozytor narzędzi dla agenta orkiestrującego.
    """

    DEFAULT_NIP = "7770001122"

    @classmethod
    def execute_tool(cls, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wykonuje narzędzie wybrane przez model LLM.
        """
        nip = args.get("nip") or cls.DEFAULT_NIP

        if name == "init_company":
            import re
            from datetime import datetime

            from src.core.company import FormaOpodatkowania, KSeFConfig, TypZUS, ZUSConfig
            from src.level_1_ingestion.company_fetcher import CompanyFetcher
            from src.level_2_bookkeeping.ledger import RegulySprzedazyFirmy
            from src.skills.cost_classifier import KwalifikacjaKosztu, RegulaPozycji, RegulyKosztoweFirmy

            clean_nip = re.sub(r"[^0-9]", "", nip)
            nazwa = args.get("nazwa")
            kody_pkd = args.get("kody_pkd") or []
            platnik_vat = args.get("platnik_vat", True)
            adres = None
            regon = None

            # Auto-fetch jeśli brak nazwy lub PKD
            pub_data = CompanyFetcher.fetch_company_info(clean_nip)
            if pub_data.get("nazwa") and not nazwa:
                nazwa = pub_data["nazwa"]
            if pub_data.get("adres"):
                adres = pub_data["adres"]
            if pub_data.get("regon"):
                regon = pub_data["regon"]
            if "platnik_vat" in pub_data and "platnik_vat" not in args:
                platnik_vat = pub_data["platnik_vat"]
            if pub_data.get("kody_pkd") and not kody_pkd:
                kody_pkd = pub_data["kody_pkd"]

            if not nazwa:
                nazwa = f"Firma {clean_nip}"

            forma = FormaOpodatkowania(args.get("forma_opodatkowania", "RYCZALT"))
            zus_typ = TypZUS(args.get("zus_typ", "PELNY_ZUS"))
            chorobowe = args.get("chorobowe_dobrowolne", True)

            new_profile = CompanyProfile(
                nip=clean_nip,
                nazwa=nazwa,
                forma_opodatkowania=forma,
                domyslna_stawka_ryczaltu=float(args.get("stawka_ryczaltu", 0.12)),
                platnik_vat=platnik_vat,
                zus=ZUSConfig(typ=zus_typ, chorobowe_dobrowolne=chorobowe),
                ksef=KSeFConfig(srodowisko=args.get("srodowisko_ksef", "PROD"), token=args.get("token_ksef")),
                kody_pkd=kody_pkd,
                regon=regon,
                adres=adres,
            )
            new_profile.save()

            # Utwórz reguły kosztowe
            reguly = RegulyKosztoweFirmy(nip_firmy=clean_nip)
            reguly.reguly_globalne.append(
                RegulaPozycji(
                    wzorzec="paliwo",
                    kwalifikacja=KwalifikacjaKosztu.SAMOCHOD_50,
                    uzasadnienie="Paliwo do pojazdu osobowego (art. 86a ustawy o VAT)",
                )
            )
            reguly.save(new_profile)

            # Utwórz reguły sprzedaży
            reguly_sprz = RegulySprzedazyFirmy(nip_firmy=clean_nip)
            reguly_sprz.save(new_profile)

            # Struktura folderów
            rok_akt = str(datetime.now().year)
            for m in range(1, 13):
                m_str = f"{m:02d}"
                for kierunek in ["sprzedaz", "koszty"]:
                    for sub in ["ksef", "non-ksef-raw", "non-ksef-extracted"]:
                        (new_profile.katalog_firmy / "faktury" / rok_akt / m_str / kierunek / sub).mkdir(
                            parents=True, exist_ok=True
                        )
            (new_profile.katalog_firmy / "rozliczenia").mkdir(parents=True, exist_ok=True)

            return {
                "success": True,
                "message": f"Pomyślnie zainicjowano firmę {new_profile.nazwa} (NIP: {new_profile.nip})!",
                "profil": new_profile.to_dict(),
                "katalog": str(new_profile.katalog_firmy),
            }

        profile = CompanyProfile.load_by_nip(nip)
        if not profile:
            return {"error": True, "message": f"Nie znaleziono profilu firmy dla NIP: {nip}"}

        if name == "sync_ksef_invoices":
            client = KSeFClient(profile)
            return client.sync_month_invoices(args["rok"], args["miesiac"])

        elif name == "review_month_invoices":
            review = PreSettlementReview.build(profile, args["rok"], args["miesiac"])
            return {"dane": review.to_dict(), "raport_markdown": review.generate_markdown()}

        elif name == "settle_month":
            nadwyzka = Decimal(str(args.get("nadwyzka_vat", 0.0)))
            result = SettlementService.settle_month(
                profile=profile,
                rok=args["rok"],
                miesiac=args["miesiac"],
                nadwyzka_vat_poprzedni=nadwyzka,
                zapisz_raporty=True,
            )
            return {"podsumowanie": result.to_dict(), "raport_markdown": result.generate_markdown_report()}

        elif name == "simulate_tax_regimes":
            przych = Decimal(str(args["przychody_roczne"]))
            kosz = Decimal(str(args["koszty_roczne"]))
            stawka = Decimal(str(args.get("stawka_ryczaltu", profile.domyslna_stawka_ryczaltu)))
            rok = str(args.get("rok", "2026"))
            comp = simulate_tax_regimes(przych, kosz, stawka, rok)
            return {"wynik": comp.to_dict(), "raport_markdown": comp.generate_markdown()}

        elif name == "audit_expense_leaks":
            audit = audit_expense_leaks(profile, args["rok"], args["miesiac"])
            return audit.to_dict()

        elif name == "learn_cost_rule":
            from src.skills.cost_classifier import KwalifikacjaKosztu, RegulyKosztoweFirmy

            reguly = RegulyKosztoweFirmy.load(profile)
            kwal = KwalifikacjaKosztu(args["kwalifikacja"])
            reguly.dodaj_regule(
                profile=profile,
                wzorzec=args["wzorzec"],
                kwalifikacja=kwal,
                uzasadnienie=args.get("uzasadnienie", ""),
                nip_kontrahenta=args.get("kontrahent_nip"),
            )
            return {
                "success": True,
                "message": f"Zapisano trwałą regułę kosztową: '{args['wzorzec']}' -> {kwal.value} dla NIP: {args.get('kontrahent_nip', 'GLOBALNA')}",
            }

        elif name == "extract_non_ksef_invoices":
            from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor

            extracted = NonKSeFExtractor.extract_all(
                profile, rok=str(args["rok"]), miesiac=str(args["miesiac"]).zfill(2), force=args.get("force", False)
            )
            return {"success": True, "liczba_wyekstrahowanych": len(extracted), "pliki": [p.name for p in extracted]}

        else:
            return {"error": True, "message": f"Nieznane narzędzie: {name}"}
