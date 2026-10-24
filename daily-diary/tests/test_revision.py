"""Synthetic regression coverage for layout-only content preservation."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/generate_diary_pdf.py"
SPEC = importlib.util.spec_from_file_location("revision_pdf", SCRIPT)
PDF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PDF)


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root / "reference.md"
        self.candidate = self.root / "candidate.md"

    def check(self, reference, candidate):
        self.reference.write_text(reference, encoding="utf8")
        self.candidate.write_text(candidate, encoding="utf8")
        PDF.verify_content_reference(self.candidate, self.reference)

    def test_missing_story_fails_even_if_headings_survive(self):
        with self.assertRaisesRegex(RuntimeError, "Content regression"):
            self.check("# Diary\n\n## Life\n\nA memorable evening.\n",
                       "# Diary\n\n## Life\n\nA short morning.\n")

    def test_formatting_and_additional_people_column_are_allowed(self):
        self.check(
            "# Diary\n\nA memorable evening.\n\n| Time | Event |\n|---|---|\n| 20:00 | Dinner |\n",
            "# Diary\n\n*A memorable evening.*\n\n| Time | People | Event |\n|---|---|---|\n"
            "| 20:00 | Friend | Dinner |\n\nAn extra detail.\n")

    def test_missing_source_table_cell_fails(self):
        with self.assertRaisesRegex(RuntimeError, "Content regression"):
            self.check("| Source | Count |\n|---|---|\n| Demo | 12 |\n",
                       "| Source | Count |\n|---|---|\n| Demo | 0 |\n")

    def test_repeated_paragraph_counts_are_preserved(self):
        with self.assertRaisesRegex(RuntimeError, "Content regression"):
            self.check("Same.\n\nSame.\n", "Same.\n")

    def test_cli_rejects_regression_before_touching_existing_pdf(self):
        self.reference.write_text("# Diary\n\nFull story.\n", encoding="utf8")
        self.candidate.write_text("# Diary\n", encoding="utf8")
        output = self.root / "existing.pdf"
        output.write_bytes(b"last-good-pdf")
        with patch("sys.argv", [str(SCRIPT), str(self.candidate),
                                "--content-reference", str(self.reference),
                                "-o", str(output)]):
            with self.assertRaisesRegex(RuntimeError, "Content regression"):
                PDF.main()
        self.assertEqual(output.read_bytes(), b"last-good-pdf")

    def test_relocated_identical_image_allowed_but_replacement_rejected(self):
        (self.root / "original.png").write_bytes(b"synthetic-image")
        (self.root / "copy.png").write_bytes(b"synthetic-image")
        self.check("![Memory](original.png)\n", "![Memory](copy.png)\n")
        (self.root / "copy.png").write_bytes(b"different-image")
        with self.assertRaisesRegex(RuntimeError, "Content regression"):
            self.check("![Memory](original.png)\n", "![Memory](copy.png)\n")


if __name__ == "__main__":
    unittest.main()
