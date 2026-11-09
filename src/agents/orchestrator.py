"""
Główny Agent Koordynator (Tax Orchestrator Agent).
Integruje deterministyczne narzędzia z modelami Gemini za pomocą deklaracji Function Calling.
"""

from decimal import Decimal
from typing import Dict, Any, List, Optional
import json

from src.core.company import CompanyProfile
from src.level_1_ingestion.ksef_client import KSeFClient
from src.level_3_tax_settlement.settlement_service import SettlementService
from src.skills.tax_advisor_tools import simulate_tax_regimes, audit_expense_leaks
from src.skills.pre_settlement_review import PreSettlementReview


# Definicje narzędzi (Function Declarations dla Gemini API)
GEMINI_TOOL_DECLARATIONS = [
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
            "required": ["rok", "miesiac"]
        }
    },
    {
        "name": "review_month_invoices",
        "description": "Generuje wstępny przegląd dokumentów przed rozliczeniem: tabelę sprzedaży (przychody), tabelę kosztów (do akceptacji) oraz tabelę pozycji do wyjaśnienia.",
        "parameters": {
            "type": "object",
            "properties": {
                "nip": {"type": "string", "description": "NIP rozliczanej firmy"},
                "rok": {"type": "string", "description": "Rok podatkowy"},
                "miesiac": {"type": "string", "description": "Miesiąc (01-12)"}
            },
            "required": ["rok", "miesiac"]
        }
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
                "nadwyzka_vat": {"type": "number", "description": "Opcjonalna nadwyżka VAT z poprzedniego miesiąca", "default": 0.0}
            },
            "required": ["rok", "miesiac"]
        }
    },
    {
        "name": "simulate_tax_regimes",
        "description": "Porównuje łączne obciążenia (ZUS + PIT) i dochód netto na rękę dla: Ryczałtu, Podatku Liniowego 19% oraz Skali Podatkowej 12%/32%.",
        "parameters": {
            "type": "object",
            "properties": {
                "przychody_roczne": {"type": "number", "description": "Szacowany roczny przychód netto w PLN"},
                "koszty_roczne": {"type": "number", "description": "Szacowane roczne koszty netto w PLN"},
                "stawka_ryczaltu": {"type": "number", "description": "Stawka ryczałtu dla działalności (np. 0.12 dla IT)", "default": 0.12},
                "rok": {"type": "string", "description": "Rok podatkowy (np. '2026')", "default": "2026"}
            },
            "required": ["przychody_roczne", "koszty_roczne"]
        }
    },
    {
        "name": "audit_expense_leaks",
        "description": "Audytuje koszty z ostatnich miesięcy w poszukiwaniu brakujących comiesięcznych faktur (np. leasing, serwery, telefon).",
        "parameters": {
            "type": "object",
            "properties": {
                "nip": {"type": "string", "description": "NIP firmy"},
                "rok": {"type": "string", "description": "Rok podatkowy"},
                "miesiac": {"type": "string", "description": "Miesiąc"}
            },
            "required": ["rok", "miesiac"]
        }
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
                "uzasadnienie": {"type": "string", "description": "Uzasadnienie podatkowe decyzji"}
            },
            "required": ["wzorzec", "kwalifikacja"]
        }
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
                "force": {"type": "boolean", "description": "Wymuszenie ponownej ekstrakcji", "default": False}
            },
            "required": ["rok", "miesiac"]
        }
    }
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
        profile = CompanyProfile.load_by_nip(nip)
        if not profile:
            return {"error": True, "message": f"Nie znaleziono profilu firmy dla NIP: {nip}"}

        if name == "sync_ksef_invoices":
            client = KSeFClient(profile)
            return client.sync_month_invoices(args["rok"], args["miesiac"])

        elif name == "review_month_invoices":
            review = PreSettlementReview.build(profile, args["rok"], args["miesiac"])
            return {
                "dane": review.to_dict(),
                "raport_markdown": review.generate_markdown()
            }

        elif name == "settle_month":
            nadwyzka = Decimal(str(args.get("nadwyzka_vat", 0.0)))
            result = SettlementService.settle_month(
                profile=profile,
                rok=args["rok"],
                miesiac=args["miesiac"],
                nadwyzka_vat_poprzedni=nadwyzka,
                zapisz_raporty=True
            )
            return {
                "podsumowanie": result.to_dict(),
                "raport_markdown": result.generate_markdown_report()
            }

        elif name == "simulate_tax_regimes":
            przych = Decimal(str(args["przychody_roczne"]))
            kosz = Decimal(str(args["koszty_roczne"]))
            stawka = Decimal(str(args.get("stawka_ryczaltu", profile.domyslna_stawka_ryczaltu)))
            rok = str(args.get("rok", "2026"))
            comp = simulate_tax_regimes(przych, kosz, stawka, rok)
            return {
                "wynik": comp.to_dict(),
                "raport_markdown": comp.generate_markdown()
            }

        elif name == "audit_expense_leaks":
            audit = audit_expense_leaks(profile, args["rok"], args["miesiac"])
            return audit.to_dict()

        elif name == "learn_cost_rule":
            from src.skills.cost_classifier import RegulyKosztoweFirmy, KwalifikacjaKosztu
            reguly = RegulyKosztoweFirmy.load(profile)
            kwal = KwalifikacjaKosztu(args["kwalifikacja"])
            reguly.dodaj_regule(
                profile=profile,
                wzorzec=args["wzorzec"],
                kwalifikacja=kwal,
                uzasadnienie=args.get("uzasadnienie", ""),
                nip_kontrahenta=args.get("kontrahent_nip")
            )
            return {
                "success": True,
                "message": f"Zapisano trwałą regułę kosztową: '{args['wzorzec']}' -> {kwal.value} dla NIP: {args.get('kontrahent_nip', 'GLOBALNA')}"
            }

        elif name == "extract_non_ksef_invoices":
            from src.level_1_ingestion.non_ksef_extractor import NonKSeFExtractor
            extracted = NonKSeFExtractor.extract_all(
                profile,
                rok=str(args["rok"]),
                miesiac=str(args["miesiac"]).zfill(2),
                force=args.get("force", False)
            )
            return {
                "success": True,
                "liczba_wyekstrahowanych": len(extracted),
                "pliki": [p.name for p in extracted]
            }

        else:
            return {"error": True, "message": f"Nieznane narzędzie: {name}"}

