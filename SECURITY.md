# Polityka Bezpieczeństwa (SECURITY.md)

Dokument opisuje model bezpieczeństwa, wektory zagrożeń oraz wytyczne operacyjne dla projektu **TaxPilot AI**.

---

## 1. Model Architektury: Local-First Personal AI Assistant

TaxPilot AI został zaprojektowany jako **lokalny, jednostanowiskowy asystent podatkowo-księgowy (Local-First)** dla jednoosobowej działalności gospodarczej (JDG):
* Aplikacja uruchamiana jest bezpośrednio na stacji roboczej przedsiębiorcy (`127.0.0.1:8000`) lub w prywatnej, zaufanej sieci VPN (np. Tailscale, WireGuard).
* System **nie jest publicznym chmurowym serwisem SaaS (Multi-Tenant)**. Katalogi w `firmy/` służą do organizacji danych per podmiot gospodarczy na lokalnym dysku użytkownika, a nie do separacji uprawnień pomiędzy wieloma różnymi, niezaufanymi użytkownikami w sieci publicznej.

---

## 2. Przechowywanie Sekretów i Danych Wrażliwych (Secrets at Rest)

1. **Tokeny KSeF i Klucze API LLM:**
   * Tokeny autoryzacyjne KSeF 2.0 oraz klucze API modeli językowych (OpenAI, Anthropic Claude, Google Gemini) zapisywane są bezpośrednio w pliku profilu: `firmy/{NIP-Nazwa}/profil.json`.
   * **Uprawnienia do plików i folderów:** Przy każdym zapisie profilu aplikacja automatycznie wymusza uprawnienia systemu plików `chmod 600` (`-rw-------`) dla plików `profil.json` oraz `reguly_*.json`, a także `chmod 700` (`drwx------`) dla katalogów firm.
   * **Automatyczna migracja uprawnień:** Podczas każdego startu serwera uruchamiana jest procedura `migrate_data_permissions()`, która audytuje i naprawia uprawnienia dla istniejących wcześniej folderów i profili.
   * **Opcjonalne szyfrowanie symetryczne at-rest (SEC-13):** Aplikacja posiada wbudowany moduł kryptograficzny `src/core/security.py` oparty o algorytm Fernet (`AES-128-CBC` + `HMAC-SHA256` z biblioteki `cryptography`). Jeśli skonfigurowana jest zmienna środowiskowa `TAXPILOT_ENCRYPTION_KEY`, tokeny autoryzacyjne KSeF 2.0 oraz klucze API LLM są automatycznie zapisywane w `profil.json` w postaci zaszyfrowanej z prefiksem `enc:fernet:...`. Klucz może być zdefiniowany jako losowy 32-bajtowy klucz Fernet w base64 lub dowolne silne hasło (zabezpieczone derywacją klucza PBKDF2-HMAC-SHA256 z solą aplikacyjną i 100 000 iteracji).
   * **Pełne szyfrowanie dyskowe:** Niezależnie od szyfrowania sekretów na poziomie aplikacji, dla maksymalnego bezpieczeństwa zaleca się stosowanie pełnego szyfrowania dysku systemowego (LUKS w Linux, BitLocker w Windows, FileVault w macOS).
2. **Katalogi Firm i Git Safety:**
   * Główny katalog danych `firmy/` jest bezwzględnie objęty regułą w `.gitignore`. Żadne faktury, dane kontrahentów ani pliki `profil.json` nie mogą trafiać do repozytorium gita.

---

## 3. Ochrona Sieciowa, Autoryzacja i Sesja (Network & Session Security)

1. **Bindowanie Kontenera Docker:**
   * Domyślna konfiguracja `docker-compose.yml` mapuje port serwera wyłącznie na pętlę zwrotną `127.0.0.1:8000`. Aplikacja nie nasłuchuje na interfejsach zewnętrznych (`0.0.0.0`).
2. **Opcjonalna Autoryzacja Tokenem (`TAXPILOT_ACCESS_TOKEN`):**
   * W przypadku uruchamiania w sieci lokalnej (LAN) lub wystawienia przez tunel VPN, zalecane jest ustawienie zmiennej środowiskowej `TAXPILOT_ACCESS_TOKEN`.
   * Mechanizm uwierzytelniania stosuje stałoczasowe porównywanie (`secrets.compare_digest`) chroniące przed atakami typu timing attack.
   * Wszelkie przekazania tokena przez parametr adresu `?token=...` powodują natychmiastowe przekierowanie `303 See Other` na czysty adres URL z zapisaniem ciasteczka `HttpOnly` (`taxpilot_auth_token`), co zapobiega wyciekowi sekretu do historii przeglądarki, logów serwera proxy i nagłówków `Referer`.
3. **Dynamiczna flaga Secure w Ciasteczkach:**
   * W środowisku lokalnym HTTP cookie działa bez flagi Secure, natomiast przy wykryciu połączenia szyfrowanego (`HTTPS`, nagłówek `X-Forwarded-Proto: https` lub zmienna `TAXPILOT_COOKIE_SECURE=1`) flaga `Secure=True` jest automatycznie aktywowana.
4. **Ochrona przed Brute-Force na `/login`:**
   * Endpoint logowania wyposażony jest w in-memory rate limiter per IP (maksymalnie 5 prób na minutę).
   * Każda błędna próba logowania generuje opóźnienie ochronne (1.0 s) oraz zwraca nagłówki `Cache-Control: no-store, no-cache, must-revalidate`.
5. **Ochrona przed Open Redirect (CWE-601):**
   * Formularz logowania rygorystycznie waliduje parametr `redirect_url` (`is_safe_redirect_url`). Dozwolone są wyłącznie ścieżki względne zaczynające się od pojedynczego `/`. Wszelkie odwołania do obcych domen, schematów czy protocol-relative URL (`//evil.com`) są redukowane do bezpiecznego `"/"`.

---

## 4. Ochrona przed Atakami Przeglądarkowymi (CSRF & XSS)

1. **Ochrona przed CSRF w architekturze Local-First (SEC-11):**
   * Aplikacje działające na `127.0.0.1` mogą być celem ataków CSRF prowadzonych ze złośliwych stron otwartych przez użytkownika w sąsiednich kartach przeglądarki.
   * TaxPilot AI stosuje weryfikację nagłówków `Origin` oraz `Referer` dla wszystkich żądań mutujących stan (`POST`, `PUT`, `DELETE`, `PATCH`). Żądania pochodzące z obcych domen są natychmiast odrzucane z kodem `403 Forbidden`.
2. **Neutralizacja XSS (CWE-79):**
   * Wszystkie dane prezentowane w panelu (w tym treści raportów i Copilota) przechodzą przez deterministyczny renderer Markdown (`src/web/utils/markdown.py`), który przeprowadza pełną ucieczkę tagów HTML (`html.escape`) oraz rygorystyczną walidację schematów linków (`is_safe_url`), blokując pseudo-protokoły `javascript:`, `data:`, `vbscript:` i `file:`.

---

## 5. Granice Bezpieczeństwa Uploadu i Inspekcji Dokumentów (Defense-in-Depth)

1. **Walidacja Wejścia Dokumentów:**
   * Limity rozmiaru: 15 MB na plik, 50 MB na paczkę.
   * Sanityzacja nazw plików (ochrona przed Path Traversal).
   * Weryfikacja sygnatur binarnych (*Magic Bytes*) dla PDF, PNG, JPEG i JSON.
2. **Heurystyczny Skaner PDF vs Izolacja Procesowa (Ważna Informacja):**
   * Wbudowana inspekcja PDF (`validate_file_content`) sprawdza obecność niebezpiecznych dyrektyw uruchomieniowych (`/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFiles`).
   * **Granica bezpieczeństwa:** Skaner ten stanowi warstwę defensywną (*Defense-in-Depth*), a nie twardy sandbox procesowy. Przy przetwarzaniu dokumentów z nieznanych źródeł w środowiskach wieloużytkownikowych docelowo zaleca się uruchamianie parserów OCR i bibliotek PDF w odizolowanym kontenerze bez dostępu do sieci.

---

## 6. Zgłaszanie Podatności (Responsible Disclosure)

Jeśli zidentyfikujesz potencjalną lukę bezpieczeństwa w repozytorium TaxPilot AI, prosimy o kontakt bezpośredni i nieotwieranie publicznych issue ze szczegółami exploita:
* **Kontakt:** Arkadiusz Cacko (`cackoarek@gmail.com`)
* Zgłoszenie powinno zawierać opis podatności, kroki do jej odtworzenia oraz propozycję remediacji.
