import json
import os
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.core.io import atomic_write_json, atomic_write_text, file_lock


class TestAtomicIO(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="taxpilot_test_io_"))

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_atomic_write_text_creates_directories_and_file(self):
        target_file = self.test_dir / "nested" / "sub" / "output.txt"
        content = "Zażółć gęślą jaźń – test polskich znaków\nLinia 2"
        result_path = atomic_write_text(target_file, content)

        self.assertEqual(result_path, target_file)
        self.assertTrue(target_file.exists())
        self.assertEqual(target_file.read_text(encoding="utf-8"), content)

        # No temp files left behind
        temp_files = list(target_file.parent.glob("*.tmp.*"))
        self.assertEqual(temp_files, [])

    def test_atomic_write_text_overwrites_existing_file(self):
        target_file = self.test_dir / "doc.md"
        target_file.write_text("Old content", encoding="utf-8")

        new_content = "New improved content"
        atomic_write_text(target_file, new_content)

        self.assertEqual(target_file.read_text(encoding="utf-8"), new_content)

    def test_atomic_write_json_with_unicode_and_indent(self):
        target_file = self.test_dir / "data" / "profil.json"
        data = {
            "nazwa": "Firma Usługowa Jan Kowalski",
            "nip": "1234567890",
            "stawki": [0.12, 0.085],
            "opis": "Kwalifikacja kosztów: Zażółć gęślą jaźń",
        }

        result_path = atomic_write_json(target_file, data, indent=2, ensure_ascii=False)
        self.assertEqual(result_path, target_file)
        self.assertTrue(target_file.exists())

        with open(target_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        self.assertEqual(loaded, data)
        # Verify unicode is preserved unescaped
        raw_text = target_file.read_text(encoding="utf-8")
        self.assertIn("Zażółć gęślą jaźń", raw_text)

    def test_atomic_write_json_custom_serializer(self):
        target_file = self.test_dir / "decimal_data.json"
        data = {
            "stawka": Decimal("0.12"),
            "vat": Decimal("123.45"),
        }

        atomic_write_json(target_file, data, default=str)
        with open(target_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        self.assertEqual(loaded["stawka"], "0.12")
        self.assertEqual(loaded["vat"], "123.45")

    def test_atomic_write_json_failure_cleans_up_temp_file(self):
        target_file = self.test_dir / "failed.json"
        target_file.write_text('{"initial": true}', encoding="utf-8")

        # Object that cannot be serialized without default
        class Unserializable:
            pass

        bad_data = {"key": Unserializable()}

        with self.assertRaises(TypeError):
            atomic_write_json(target_file, bad_data)

        # Existing file remains untouched
        self.assertEqual(target_file.read_text(encoding="utf-8"), '{"initial": true}')

        # Temp files are removed
        temp_files = list(self.test_dir.glob("*.tmp.*"))
        self.assertEqual(temp_files, [])

    @unittest.skipIf(os.name == "nt", "fcntl file locking is only available on POSIX systems")
    def test_file_lock_mutual_exclusion(self):
        target_file = self.test_dir / "concurrent.json"
        with file_lock(target_file, timeout=1.0):
            # Attempting to acquire another exclusive lock with zero timeout should raise TimeoutError
            with self.assertRaises(TimeoutError):
                with file_lock(target_file, timeout=0.05):
                    pass

        # After releasing, lock can be acquired again
        acquired = False
        with file_lock(target_file, timeout=1.0):
            acquired = True
        self.assertTrue(acquired)

    def test_atomic_write_with_lock_flag(self):
        target_file = self.test_dir / "locked_output.json"
        data = {"concurrent": True, "value": 42}
        atomic_write_json(target_file, data, lock=True)
        self.assertTrue(target_file.exists())
        with open(target_file, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), data)

        txt_file = self.test_dir / "locked_output.txt"
        atomic_write_text(txt_file, "locked text content", lock=True)
        self.assertEqual(txt_file.read_text(encoding="utf-8"), "locked text content")


if __name__ == "__main__":
    unittest.main()
