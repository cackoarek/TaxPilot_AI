"""
tests/test_xss_prevention.py
Testy bezpieczeństwa weryfikujące odporność na ataki Cross-Site Scripting (XSS / CWE-79)
w konwerterze markdown_to_html (Copilot chat) oraz render_markdown (panele raportowe).
"""

import unittest

from src.web.routers.copilot import is_safe_url, markdown_to_html
from src.web.utils.markdown import render_markdown


class TestXSSPrevention(unittest.TestCase):
    """Zestaw testów bezpieczeństwa przeciwko wstrzykiwaniu kodu HTML i JavaScript."""

    def test_script_tag_in_text_is_neutralized(self):
        """Weryfikuje neutralizację bezpośredniego taga <script> w akapicie."""
        payload = "<script>alert('xss')</script>"
        html = markdown_to_html(payload)
        self.assertNotIn("<script>", html)
        self.assertNotIn("</script>", html)
        self.assertIn("&lt;script&gt;alert('xss')&lt;/script&gt;", html)

    def test_img_onerror_tag_is_neutralized(self):
        """Weryfikuje neutralizację taga <img> z handlerem onerror."""
        payload = "<img src=x onerror=alert(1)>"
        html = markdown_to_html(payload)
        self.assertNotIn("<img", html)
        self.assertNotIn("onerror", html.lower().replace("&lt;", "<").replace("&gt;", ">") if "<img" in html else "")
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)

    def test_svg_onload_tag_is_neutralized(self):
        """Weryfikuje neutralizację wektora SVG z handlerem onload."""
        payload = "<svg/onload=alert(document.cookie)>"
        html = markdown_to_html(payload)
        self.assertNotIn("<svg", html)
        self.assertIn("&lt;svg/onload=alert(document.cookie)&gt;", html)

    def test_javascript_pseudo_protocol_in_markdown_link(self):
        """Weryfikuje odrzucenie linków z pseudo-protokołem javascript: w Markdown."""
        payloads = [
            "[kliknij](javascript:alert('xss'))",
            "[kliknij](JAVASCRIPT:alert(1))",
            "[kliknij](javascript:alert(document.domain))",
            "[kliknij](vbscript:msgbox(1))",
            "[kliknij](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
        ]
        for p in payloads:
            html = markdown_to_html(p)
            self.assertNotIn('href="javascript:', html.lower())
            self.assertNotIn('href="vbscript:', html.lower())
            self.assertNotIn('href="data:', html.lower())
            # Niebezpieczny link nie może tworzyć taga <a>
            self.assertNotIn("<a ", html)

    def test_safe_markdown_link_is_preserved(self):
        """Weryfikuje, czy prawidłowe i bezpieczne linki http, https oraz relatywne są dozwolone."""
        safe_links = [
            ("[TaxPilot](https://taxpilot.local/dashboard)", "https://taxpilot.local/dashboard"),
            ("[Dokumentacja](http://docs.local/info)", "http://docs.local/info"),
            ("[Panel](/dashboard)", "/dashboard"),
            ("[Kontakt](mailto:pomoc@taxpilot.pl)", "mailto:pomoc@taxpilot.pl"),
        ]
        for md, expected_url in safe_links:
            html = markdown_to_html(md)
            self.assertIn(f'href="{expected_url}"', html)
            self.assertIn('target="_blank"', html)
            self.assertIn('rel="noopener noreferrer"', html)

    def test_link_attribute_injection_prevention(self):
        """Weryfikuje zabezpieczenie przed ucieczką z atrybutu href (attribute breakout)."""
        payload = '[evil](https://example.com" onmouseover="alert(1))'
        html = markdown_to_html(payload)
        self.assertNotIn('onmouseover="alert(1)"', html)
        self.assertNotIn("onmouseover=alert(1)", html)

    def test_xss_in_markdown_table(self):
        """Weryfikuje neutralizację payloadów XSS w komórkach i nagłówkach tabeli."""
        md = (
            "| Kolumna 1 | <script>alert('th')</script> |\n"
            "|---|---|\n"
            "| <img src=x onerror=alert(1)> | **Bezpieczny tekst** |\n"
        )
        html = markdown_to_html(md)
        self.assertIn("<table", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;alert('th')&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertIn("<strong>Bezpieczny tekst</strong>", html)

    def test_xss_in_headers_and_quotes(self):
        """Weryfikuje neutralizację XSS w nagłówkach i cytatach."""
        md = "### Nagłówek <script>alert(1)</script>\n\n> Cytat <img src=x onerror=alert(1)>"
        html = markdown_to_html(md)
        self.assertIn("<h4", html)
        self.assertIn("<blockquote", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)

    def test_xss_in_code_blocks_and_inline_code(self):
        """Weryfikuje, że w blokach kodu i inline code tagi są escapowane, a nie wykonywane."""
        md = "Oto kod:\n```html\n<script>alert('code')</script>\n```\nOraz inline `<img src=x onerror=alert(1)>`."
        html = markdown_to_html(md)
        self.assertIn("<pre", html)
        self.assertIn("<code", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;alert('code')&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)

    def test_xss_in_render_markdown_utility(self):
        """Weryfikuje, że pomocnik render_markdown z utils/markdown.py jest również zabezpieczony."""
        md = "# Tytuł <script>alert(1)</script>\n\n[klik](javascript:alert(1))"
        html = str(render_markdown(md))
        self.assertNotIn("<script>", html)
        self.assertNotIn('href="javascript:', html.lower())
        self.assertNotIn("<a ", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_render_markdown_contract_strict_html_neutralization(self):
        """Formalny kontrakt bezpieczeństwa render_markdown (SEC-12 / CWE-79)."""
        malicious_samples = [
            '<iframe src="https://evil.com"></iframe>',
            '<object data="exploit.swf"></object>',
            '<embed src="exploit.pdf">',
            '<div onmouseover="alert(1)">Treść</div>',
            "<style>body { display: none; }</style>",
            '<base href="https://evil.com">',
            '<form action="https://evil.com"><input type="submit"></form>',
        ]
        for payload in malicious_samples:
            rendered = str(render_markdown(payload))
            # Żaden z tych surowych tagów nie może pojawić się w wynikowym kodzie HTML jako element DOM
            self.assertNotIn("<iframe", rendered)
            self.assertNotIn("<object", rendered)
            self.assertNotIn("<embed", rendered)
            self.assertNotIn("<div", rendered)
            self.assertNotIn("<style", rendered)
            self.assertNotIn("<base", rendered)
            self.assertNotIn("<form", rendered)
            # Tagi muszą być bezpiecznie zneutralizowane do encji &lt; i &gt;
            self.assertIn("&lt;", rendered)

    def test_render_markdown_contract_tables_and_formatting(self):
        """Weryfikuje poprawne formatowanie tabeli z neutralizacją wstrzyknięć w komórkach."""
        md_table = (
            "| Kontrahent | NIP | Kwota | Zdarzenie |\n"
            "|:---|:---:|---:|:---|\n"
            "| Google Cloud <script>steal()</script> | 1234567890 | 100.00 zł | `<img src=x onerror=alert(1)>` |\n"
            "| **SUMA** | - | **100.00 zł** | [Panel](https://safe.local) |\n"
        )
        rendered = str(render_markdown(md_table))
        self.assertIn("<table", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)
        self.assertIn("&lt;script&gt;steal()&lt;/script&gt;", rendered)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", rendered)
        self.assertIn('<a href="https://safe.local"', rendered)

    def test_is_safe_url_helper(self):
        """Sprawdza reguły walidacji URL pod kątem bezpieczeństwa."""
        self.assertTrue(is_safe_url("https://gov.pl"))
        self.assertTrue(is_safe_url("http://localhost:8000"))
        self.assertTrue(is_safe_url("/faktury/2026/01"))
        self.assertTrue(is_safe_url("#sekcja"))
        self.assertTrue(is_safe_url("mailto:kontakt@firma.pl"))

        self.assertFalse(is_safe_url(""))
        self.assertFalse(is_safe_url("javascript:alert(1)"))
        self.assertFalse(is_safe_url("JavaScript:alert(1)"))
        self.assertFalse(is_safe_url("jav\tascript:alert(1)"))
        self.assertFalse(is_safe_url("data:text/html;base64,123"))
        self.assertFalse(is_safe_url("vbscript:msgbox(1)"))
        self.assertFalse(is_safe_url("file:///etc/passwd"))
        self.assertFalse(is_safe_url("//evil.com/phishing"))


if __name__ == "__main__":
    unittest.main()
