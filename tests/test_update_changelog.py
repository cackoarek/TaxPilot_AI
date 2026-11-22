"""
tests/test_update_changelog.py
Testy automatycznej aktualizacji pliku CHANGELOG.md (skrypt .github/scripts/update_changelog.py).
"""

import sys
import unittest
from pathlib import Path

# Dodanie katalogu ze skryptem do sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".github" / "scripts"))
from update_changelog import (
    categorize_commits,
    update_changelog_content,
)


class TestUpdateChangelog(unittest.TestCase):
    def test_categorize_commits_conventional_commits(self):
        """Test poprawnego kategoryzowania commitów wg konwencji Conventional Commits."""
        commits = [
            "feat(ksef): dodaj obsługę środowiska produkcyjnego",
            "fix(zus): napraw wyliczenie składki zdrowotnej w II progu",
            "docs: zaktualizuj instrukcję onboardingu",
            "refactor(settlement): uprość SettlementService",
            "chore: bump dependencies",
        ]
        lines = categorize_commits(commits)
        joined = "\n".join(lines)

        self.assertIn("### Dodane", joined)
        self.assertIn("- dodaj obsługę środowiska produkcyjnego", joined)
        self.assertIn("### Naprawione", joined)
        self.assertIn("- napraw wyliczenie składki zdrowotnej w II progu", joined)
        self.assertIn("### Dokumentacja", joined)
        self.assertIn("- zaktualizuj instrukcję onboardingu", joined)
        self.assertIn("### Zmienione", joined)
        self.assertIn("- uprość SettlementService", joined)

    def test_update_changelog_moves_unreleased_entries(self):
        """Gdy sekcja [Unreleased] zawiera wpisy, przenosi je do nowej wersji."""
        sample_changelog = """# Changelog

Format bazuje na Keep a Changelog.

## [Unreleased]

### Dodane
- Nowa funkcja rozliczeń

---

## [0.1.0] – 2026-11-20

### Dodane
- Inicjalne wydanie

[Unreleased]: https://github.com/cackoarek/TaxPilot_AI/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cackoarek/TaxPilot_AI/releases/tag/v0.1.0
"""
        updated = update_changelog_content(
            content=sample_changelog,
            version="0.2.0",
            tag="v0.2.0",
            prev_tag="v0.1.0",
            repo="cackoarek/TaxPilot_AI",
            release_date="2026-11-21",
        )

        # Sprawdzenie nowej sekcji
        self.assertIn("## [0.2.0] – 2026-11-21", updated)
        self.assertIn("- Nowa funkcja rozliczeń", updated)
        # Sekcja unreleased powinna być teraz pusta
        self.assertTrue("## [Unreleased]\n\n---\n\n## [0.2.0]" in updated)
        # Linki na dole
        self.assertIn("[Unreleased]: https://github.com/cackoarek/TaxPilot_AI/compare/v0.2.0...HEAD", updated)
        self.assertIn("[0.2.0]: https://github.com/cackoarek/TaxPilot_AI/compare/v0.1.0...v0.2.0", updated)

    def test_update_changelog_generates_from_commits_when_unreleased_empty(self):
        """Gdy sekcja [Unreleased] jest pusta, wpisy generowane są z commitów."""
        sample_changelog = """# Changelog

## [Unreleased]

---

## [0.1.0] – 2026-11-20

### Dodane
- Inicjalne wydanie

[Unreleased]: https://github.com/cackoarek/TaxPilot_AI/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cackoarek/TaxPilot_AI/releases/tag/v0.1.0
"""
        commits = [
            "feat(ui): dodaj przełącznik firm",
            "fix(vat): napraw zaokrąglenie groszy",
        ]
        updated = update_changelog_content(
            content=sample_changelog,
            version="0.2.0",
            tag="v0.2.0",
            prev_tag="v0.1.0",
            repo="cackoarek/TaxPilot_AI",
            release_date="2026-11-21",
            commits=commits,
        )

        self.assertIn("## [0.2.0] – 2026-11-21", updated)
        self.assertIn("### Dodane", updated)
        self.assertIn("- dodaj przełącznik firm", updated)
        self.assertIn("### Naprawione", updated)
        self.assertIn("- napraw zaokrąglenie groszy", updated)


if __name__ == "__main__":
    unittest.main()
