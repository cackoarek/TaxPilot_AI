# Jak wydawać wersje (Releasing)

Ten dokument opisuje proces wydawania nowych wersji projektu **TaxPilot AI** z użyciem Git tagów i GitHub Actions.

---

## Strategia wersjonowania

Projekt stosuje **Semantic Versioning (SemVer)**:

```
MAJOR.MINOR.PATCH  →  np. 0.2.0 lub 1.0.0
```

| Typ zmiany | Bump | Przykład |
|:---|:---|:---|
| Poprawka błędu | PATCH: `0.1.0 → 0.1.1` | naprawa parsowania daty w fakturze FA(3) |
| Nowa funkcja (kompatybilna wstecz) | MINOR: `0.1.0 → 0.2.0` | nowy moduł generowania przelewów lub ulga podatkowa |
| Złamanie kompatybilności | MAJOR: `0.x.x → 1.0.0` | zmiana schematu `profil.json` lub nadrzędnej architektury |

---

## Standard commit messages: Conventional Commits

Każdy commit powinien zaczynać się od **type(scope): description**:

```
feat(ksef): dodaj obsługę środowiska produkcyjnego KSeF 2.0
fix(zus): napraw wyliczenie składki zdrowotnej w II progu
docs: zaktualizuj instrukcję onboardingu firmy
chore: aktualizacja zależności w requirements.txt
ci: dodaj workflow testów jednostkowych
refactor(settlement): uprość SettlementService
test: dodaj testy zbiorczej kwalifikacji pozycji
```

Typy commit messages i ich znaczenie:

| Prefix | Opis |
|:---|:---|
| `feat:` | Nowa funkcja (trafia do sekcji *Nowe funkcje* w changelogu) |
| `fix:` | Poprawka błędu (trafia do sekcji *Poprawki błędów*) |
| `docs:` | Zmiany w dokumentacji (trafia do *Dokumentacja*) |
| `chore:` | Zadania pomocnicze, zależności, konfiguracja |
| `ci:` | Zmiany w GitHub Actions / pipeline |
| `refactor:` | Refaktoryzacja kodu bez zmiany zachowania |
| `test:` | Dodanie lub poprawa testów |
| `perf:` | Optymalizacja wydajności |

> [!TIP]
> Conventional Commits są automatycznie używane przez skrypt `.github/scripts/update_changelog.py` do kategoryzowania zmian w `CHANGELOG.md` oraz generowania GitHub Release Notes.

---

## Pipeline wydania (co robi GitHub Actions)

Po wypchnięciu tagu `v*` uruchamia się automatyczny pipeline:

```
git push origin v0.2.0
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  1. TEST GATE (.github/workflows/release.yml)           │
│     • python -m unittest discover tests                 │
│     • ❌ Błąd → pipeline zatrzymany, brak publikacji    │
└─────────────────────┬───────────────────────────────────┘
                      │ ✅
                      ▼
┌─────────────────────────────────────────────────────────┐
│  2. BUMP VERSION & CHANGELOG                            │
│     • aktualizuje version w pyproject.toml              │
│     • aktualizuje plik VERSION                          │
│     • aktualizuje CHANGELOG.md (z [Unreleased] lub gita)│
│     • commit "chore(release): bump version... [skip ci]"│
│     • push do gałęzi main                               │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  3. GITHUB RELEASE                                      │
│     • tworzy oficjalny Release na stronie GitHub        │
│     • generuje skategoryzowane Release Notes z commitów │
│       (✨ Nowe funkcje, 🐛 Poprawki, 📚 Dokumentacja)   │
│     • oznacza jako pre-release dla tagów z myślnikiem   │
└─────────────────────────────────────────────────────────┘
```

---

## Krok po kroku: jak wydać nową wersję

### 1. Przygotuj kod

```bash
# Upewnij się, że jesteś na main z najnowszymi zmianami
git checkout main
git pull

# Sprawdź czy testy przechodzą lokalnie
python -m unittest discover tests
```

### 2. (Opcjonalnie) Uzupełnij sekcję [Unreleased] w CHANGELOG.md

Proces wydania w GitHub Actions automatycznie aktualizuje plik [`CHANGELOG.md`](CHANGELOG.md):
- Jeśli wpiszesz własne punkty w sekcji `## [Unreleased]`, skrypt przeniesie je do nowej wersji i zaktualizuje linki na dole.
- Jeśli sekcja `## [Unreleased]` pozostanie pusta, skrypt wygeneruje wpisy automatycznie na podstawie historii commitów Git (Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`).

Jeśli chcesz dodać własne notatki przed wydaniem:
```markdown
## [Unreleased]

### Dodane
- Nowa integracja z bankowością internetową
```

Zacommituj ewentualne wpisy:
```bash
git add CHANGELOG.md
git commit -m "docs: przygotuj wpisy w changelog dla nowego wydania"
git push origin main
```

### 3. Utwórz tag Git

```bash
# Format: vMAJOR.MINOR.PATCH
git tag v0.2.0 -m "Wydanie v0.2.0: Zbiorcza kwalifikacja pozycji i onboarding firm"

# Pre-release (opcjonalnie):
git tag v0.2.0-rc1 -m "Release candidate 1"
```

### 4. Wypchnij tag – to wystarcza

```bash
git push origin v0.2.0
```

Od tego momentu GitHub Actions wykona cały proces:
1. Uruchomi zestaw testów jednostkowych.
2. Podbije wersję w `pyproject.toml` oraz `VERSION`.
3. Zaktualizuje `CHANGELOG.md` i zacommituje zmiany do `main`.
4. Opublikuje oficjalny GitHub Release z Release Notes.

### 5. Weryfikacja

- Otwórz zakładkę **Actions** na GitHub → sprawdź czy workflow `Release – Tag & Publish` przeszedł pomyślnie ✅.
- Otwórz zakładkę **Releases** na GitHub → sprawdź nowy Release.
- Uruchom aplikację – w stopce strony oraz w poleceniu `python -m src.cli --version` pojawi się nowo wydana wersja!

---

## Wersje pre-release (RC, Beta, Alpha)

Tag z myślnikiem jest automatycznie oznaczany jako pre-release:

```bash
git tag v1.0.0-rc1 -m "Release candidate – stabilne API KSeF"
git push origin v1.0.0-rc1
# → GitHub Release z flagą "Pre-release" (nie nadpisuje "latest")
```

---

## Cofnięcie tagu (jeśli coś poszło nie tak)

```bash
# Usuń tag lokalnie
git tag -d v0.2.0

# Usuń tag zdalnie (i usuń Release ręcznie na GitHub w zakładce Releases)
git push origin --delete v0.2.0
```

---

## Pliki powiązane z procesem wydań

| Plik | Rola |
|:---|:---|
| [`CHANGELOG.md`](CHANGELOG.md) | Historia wersji i rejestr zmian wg Keep a Changelog |
| [`RELEASING.md`](RELEASING.md) | Niniejsza instrukcja procedury wydawania wersji |
| [`pyproject.toml`](pyproject.toml) | Konfiguracja projektu i deklaracja wersji |
| [`VERSION`](VERSION) | Statyczny plik wersji (aktualizowany automatycznie przez CI) |
| [`src/version.py`](src/version.py) | Moduł dynamicznego wykrywania wersji w aplikacji |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Testy jednostkowe przy commitach i Pull Requestach |
| [`.github/workflows/release.yml`](.github/workflows/release.yml) | Automatyczny pipeline wydania po pushu tagu git |
| [`.github/scripts/update_changelog.py`](.github/scripts/update_changelog.py) | Skrypt aktualizujący `CHANGELOG.md` z commitów i sekcji `[Unreleased]` |
| [`.github/pull_request_template.md`](.github/pull_request_template.md) | Szablon PR z checklistą i Conventional Commits |
