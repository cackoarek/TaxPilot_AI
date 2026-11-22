# Polityka Bezpieczeństwa (SECURITY.md)

Dokument opisuje model bezpieczeństwa, wektory zagrożeń oraz wytyczne operacyjne dla projektu **TaxPilot AI**.

---

## 1. Model Architektury: Local-First Personal AI Assistant

TaxPilot AI został zaprojektowany jako **lokalny, jednostanowiskowy asystent podatkowo-księgowy (Local-First)** dla jednoosobowej działalności gospodarczej (JDG):
* Aplikacja uruchamiana jest bezpośrednio na stacji roboczej przedsiębiorcy (localhost) lub w prywatnej, zaufanej sieci VPN (np. Tailscale, WireGuard).
* System **nie jest publicznym chmurowym serwisem SaaS (Multi-Tenant)**. Katalogi w `firmy/` służą do organizacji danych per podmiot gospodarczy na lokalnym dysku użytkownika, a nie do separacji uprawnień pomiędzy wieloma różnymi, niezaufanymi użytkownikami w sieci publicznej.

---

## 2. Przechowywanie Sekretów i Danych Wrażliwych (Secrets at Rest)

1. **Tokeny KSeF i Klucze API LLM:**
   * Tokeny autoryzacyjne KSeF 2.0 oraz klucze API modeli językowych (OpenAI, Anthropic Claude, Google Gemini) zapisywane są bezpośrednio w pliku profilu: `firmy/{NIP-Nazwa}/profil.json`.
   * **Uprawnienia do plików:** Przy każdym zapisie profilu aplikacja automatycznie wymusza uprawnienia systemu plików `chmod 600` (`-rw-------`), co gwarantuje odczyt i zapis wyłącznie dla procesu i konta systemowego właściciela.
   * **Brak szyfrowania at-rest w aplikacji:** Dane na dysku nie są szyfrowane na poziomie bazy TaxPilot AI. Użytkownikom zaleca się stosowanie pełnego szyfrowania dysku systemowego (LUKS w Linux, BitLocker w Windows, FileVault w macOS).
2. **Katalogi Firm i Git Safety:**
   * Główny katalog danych `firmy/` jest bezwzględnie objęty regułą w `.gitignore`. Żadne faktury, dane kontrahentów ani pliki `profil.json` nie mogą trafiać do repozytorium gita.

---

## 3. Ochrona Sieciowa i Wdrożenie (Network & Deployment)

1. **Bindowanie Kontenera Docker:**
   * Domyślna konfiguracja `docker-compose.yml` mapuje port serwera wyłącznie na pętlę zwrotną `127.0.0.1:8000`. Aplikacja nie nasłuchuje na interfejsach zewnętrznych (`0.0.0.0`).
2. **Opcjonalna Autoryzacja Tokenem (`TAXPILOT_ACCESS_TOKEN`):**
   * W przypadku uruchamiania w sieci lokalnej (LAN) lub wystawienia przez tunel VPN, zalecane jest ustawienie zmiennej środowiskowej `TAXPILOT_ACCESS_TOKEN`.
   * Mechanizm uwierzytelniania stosuje stałoczasowe porównywanie (`secrets.compare_digest`) chroniące przed atakami typu timing attack.
   * Wszelkie przekazania tokena przez parametr adresu `?token=...` powodują natychmiastowe przekierowanie `303 See Other` na czysty adres URL z zapisaniem bezpiecznego ciasteczka `HttpOnly`, co zapobiega wyciekowi sekretu do historii przeglądarki, logów serwera proxy i nagłówków `Referer`.

---

## 4. Ochrona przed Podatnościami Aplikacyjnymi

* **XSS (Cross-Site Scripting, CWE-79):**
  Wszystkie dynamiczne treści generowane przez silnik Markdown oraz Copilota podlegają rygorystycznemu czyszczeniu biblioteką `bleach` z białą listą bezpiecznych tagów HTML i blokadą niebezpiecznych protokołów URI (`javascript:`, `data:`, `vbscript:`, `file:`).
* **Upload Dokumentów:**
  Pliki wgrywane przez formularz faktur podlegają limitom (15 MB na plik, 50 MB na paczkę), sanityzacji ścieżek i nazw (ochrona przed Path Traversal) oraz walidacji nagłówków binarnych (*Magic Bytes*) dla PDF, PNG, JPEG i JSON. Pliki PDF są skanowane pod kątem obecności niebezpiecznych dyrektyw uruchomieniowych (`/JavaScript`, `/JS`, `/Launch`).

---

## 5. Zgłaszanie Podatności (Responsible Disclosure)

Jeśli zidentyfikujesz potencjalną lukę bezpieczeństwa w repozytorium TaxPilot AI, prosimy o kontakt bezpośredni i nieotwieranie publicznych issue ze szczegółami exploita:
* **Kontakt:** Arkadiusz Cacko (`cackoarek@gmail.com`)
* Zgłoszenie powinno zawierać opis podatności, kroki do jej odtworzenia oraz propozycję remediacji.
