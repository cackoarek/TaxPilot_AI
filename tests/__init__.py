"""
tests/__init__.py
Konfiguracja środowiska testowego TaxPilot AI.
Wyciszenie przestarzałych ostrzeżeń bibliotek zewnętrznych (Starlette / FastAPI TestClient) (QA-7).
"""

import warnings

# Wyciszenie ostrzeżeń deprecation bibliotek zewnętrznych w środowisku testowym (QA-7)
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"starlette(\..*)?")
warnings.filterwarnings("ignore", message=r".*Using `httpx` with `starlette\.testclient` is deprecated.*")
