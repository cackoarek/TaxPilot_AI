#!/usr/bin/env python3
"""
scripts/export_demo_pages.py
Skrypt generujący pakiet statycznych stron HTML panelu webowego TaxPilot AI
w folderze examples/pages na podstawie zanonimizowanych danych referencyjnych
CloudTech Solutions Jan Kowalski (examples/firmy/7770001122-CloudTech_Solutions_Jan_Kowalski).
"""

import argparse
import sys
from pathlib import Path

# Upewnienie się że główny katalog repozytorium znajduje się w sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.web.export import (
    DEFAULT_DEMO_MONTH,
    DEFAULT_DEMO_NIP,
    DEFAULT_DEMO_YEAR,
    DEFAULT_OUTPUT_DIR,
    export_demo_pages,
)


def main():
    parser = argparse.ArgumentParser(
        description="Generuje pakiet statycznych stron HTML do prezentacji na GitHub Pages lub przeglądania offline."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Ścieżka do katalogu wyjściowego (domyślnie: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--nip",
        type=str,
        default=DEFAULT_DEMO_NIP,
        help=f"NIP firmy demonstracyjnej (domyślnie: {DEFAULT_DEMO_NIP})",
    )
    parser.add_argument(
        "--rok",
        type=str,
        default=DEFAULT_DEMO_YEAR,
        help=f"Aktywny rok rozliczeniowy (domyślnie: {DEFAULT_DEMO_YEAR})",
    )
    parser.add_argument(
        "--miesiac",
        type=str,
        default=DEFAULT_DEMO_MONTH,
        help=f"Aktywny miesiąc rozliczeniowy (domyślnie: {DEFAULT_DEMO_MONTH})",
    )

    args = parser.parse_args()
    output_dir = Path(args.output).resolve()

    print(f"🚀 [TaxPilot AI] Rozpoczynanie generowania stron demo w: {output_dir}")
    print(f"🏢 Podmiot demonstracyjny: NIP {args.nip} (okres: {args.rok}-{args.miesiac})")

    try:
        generated = export_demo_pages(
            output_dir=output_dir,
            nip=args.nip,
            rok=args.rok,
            miesiac=args.miesiac,
        )
    except Exception as exc:
        print(f"❌ Wystąpił błąd podczas generowania stron demo: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    print("\n✅ Pomyślnie wygenerowano pakiet stron HTML:")
    for fname, path in sorted(generated.items()):
        size_kb = path.stat().st_size / 1024.0
        print(f"   📄 {fname:<30} ({size_kb:6.1f} KB) -> {path}")

    print(f"\n✨ Kompletny pakiet stron gotowy w: {output_dir}")
    print(f"🌐 Główny plik wejściowy (GitHub Pages): {output_dir / 'index.html'}")


if __name__ == "__main__":
    main()
