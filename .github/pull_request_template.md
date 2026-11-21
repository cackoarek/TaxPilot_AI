## Opis zmian

<!-- Krótki opis co i dlaczego zostało zmienione -->

## Typ zmiany

<!-- Zaznacz odpowiedni typ (ma wpływ na wersjonowanie SemVer oraz automatyczny CHANGELOG): -->

| Typ commita | Przykład | Bump wersji |
|:---|:---|:---|
| `fix:` | `fix(ksef): napraw parsowanie daty w FA(3)` | PATCH (0.1.x) |
| `feat:` | `feat(zus): dodaj nowy próg składki zdrowotnej` | MINOR (0.x.0) |
| `feat!:` lub `BREAKING CHANGE:` | `feat!: zmiana struktury profil.json` | MAJOR (x.0.0) |
| `docs:` | `docs: zaktualizuj instrukcję onboardingu` | — |
| `chore:` | `chore: aktualizacja bibliotek requirements.txt` | — |
| `ci:` | `ci: dodaj workflow release` | — |
| `refactor:` | `refactor(settlement): uprość SettlementService` | — |
| `test:` | `test: dodaj testy dla zbiorczej kwalifikacji` | — |

## Checklist

- [ ] Commit messages są zgodne z **Conventional Commits** (`type(scope): description`)
- [ ] Testy przechodzą lokalnie (`python -m unittest discover tests`)
- [ ] Zero-Hallucination Policy: obliczenia podatkowo-składkowe wykonane deterministycznie w Pythonie (`Decimal`)
- [ ] Dokumentacja zaktualizowana (jeśli dotyczy)
- [ ] Żadne tokeny KSeF ani poufne dane firm (`profil.json`, `.env`) **nie trafiają** do gita

## Powiązane zgłoszenia / Issues

<!-- Closes #123 -->
