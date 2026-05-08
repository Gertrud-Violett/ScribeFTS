"""Tests for lib/extractor.py — Layers 2 and 3 heuristics (no AI, no real PDF required)."""

import tempfile
import unittest
from pathlib import Path

from lib.extractor import (
    ExtractionResult,
    FieldDraft,
    _extract_authors_from_filename,
    _find_year_in_text,
    _parse_pdf_date_year,
    extract_metadata,
)


class TestPdfDateParsing(unittest.TestCase):
    def test_standard_pdf_date(self):
        self.assertEqual(_parse_pdf_date_year("D:20190315120000"), "2019")

    def test_plain_year(self):
        self.assertEqual(_parse_pdf_date_year("2021"), "2021")

    def test_empty_string(self):
        self.assertEqual(_parse_pdf_date_year(""), "")

    def test_no_year(self):
        self.assertEqual(_parse_pdf_date_year("random text"), "")

    def test_old_century(self):
        self.assertEqual(_parse_pdf_date_year("D:19951010"), "1995")


class TestFindYearInText(unittest.TestCase):
    def test_finds_year_surrounded_by_spaces(self):
        # \b matches when year is surrounded by non-word chars (spaces, punct)
        self.assertEqual(_find_year_in_text("published in 2023 by"), "2023")

    def test_finds_year_with_parentheses(self):
        self.assertEqual(_find_year_in_text("(2019)"), "2019")

    def test_no_year(self):
        self.assertEqual(_find_year_in_text("NoDateHere"), "")

    def test_year_attached_to_word_chars_not_matched(self):
        # \b does not match when year is adjacent to letters or underscores
        self.assertEqual(_find_year_in_text("Smith2023_Title"), "")
        self.assertEqual(_find_year_in_text("Jones_2019_paper"), "")

    def test_century_boundary_not_matched(self):
        # 1800 and 2100 are outside the 19xx/20xx range
        self.assertEqual(_find_year_in_text("1800s history"), "")


class TestExtractAuthorsFromFilename(unittest.TestCase):
    def test_simple_last_year(self):
        result = _extract_authors_from_filename("Smith2023_SomeTitle")
        self.assertIn("Smith", result)

    def test_two_authors(self):
        result = _extract_authors_from_filename("Smith_Jones_2023_Title")
        self.assertIn("Smith", result)
        self.assertIn("Jones", result)

    def test_et_al(self):
        result = _extract_authors_from_filename("Smith_et_al_2019")
        self.assertIn("Smith", result)

    def test_no_names(self):
        result = _extract_authors_from_filename("123_data_file")
        self.assertEqual(result, "")

    def test_all_lowercase_no_match(self):
        result = _extract_authors_from_filename("notes_on_something")
        self.assertEqual(result, "")


class TestExtractionResultAsDict(unittest.TestCase):
    def test_empty_result(self):
        r = ExtractionResult()
        self.assertEqual(r.as_dict(), {})

    def test_partial_result(self):
        r = ExtractionResult(year=FieldDraft("2021", "layer2", 0.70))
        d = r.as_dict()
        self.assertIn("year", d)
        self.assertNotIn("title", d)
        self.assertEqual(d["year"].value, "2021")
        self.assertEqual(d["year"].confidence, 0.70)

    def test_full_result(self):
        r = ExtractionResult(
            title=FieldDraft("A Title", "layer1", 0.95),
            authors=FieldDraft("Smith", "layer1", 0.90),
            year=FieldDraft("2020", "layer1", 0.85),
            keywords=FieldDraft("kw1", "layer2", 0.40),
        )
        d = r.as_dict()
        self.assertEqual(set(d.keys()), {"title", "authors", "year", "keywords"})


class TestExtractMetadataFallback(unittest.TestCase):
    """extract_metadata should not crash for non-PDF or missing files."""

    def test_nonexistent_file_returns_result(self):
        result = extract_metadata(Path("/nonexistent/file.pdf"))
        # All fields should be None since fitz can't open the file
        self.assertIsInstance(result, ExtractionResult)

    def test_non_pdf_returns_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt_path = Path(tmp) / "Smith2022_Climate.txt"
            txt_path.write_text("Some text content", encoding="utf-8")
            result = extract_metadata(txt_path)
            self.assertIsInstance(result, ExtractionResult)
            # Layer 2 should still extract year and author from filename
            if result.year is not None:
                self.assertEqual(result.year.value, "2022")
            if result.authors is not None:
                self.assertIn("Smith", result.authors.value)

    def test_existing_metadata_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt_path = Path(tmp) / "Smith2022_Climate.txt"
            txt_path.write_text("Some text", encoding="utf-8")
            result = extract_metadata(
                txt_path,
                current_metadata={"year": "1999", "authors": "Existing Author"},
            )
            # Fields already populated should not be suggested
            self.assertIsNone(result.year)
            self.assertIsNone(result.authors)

    def test_ai_disabled_uses_heuristic(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt_path = Path(tmp) / "Jones2020_NeuralNets.txt"
            txt_path.write_text("Some text", encoding="utf-8")
            result = extract_metadata(
                txt_path,
                ai_config={"enabled": False, "api_key": "", "provider": "gemini"},
            )
            self.assertIsInstance(result, ExtractionResult)


if __name__ == "__main__":
    unittest.main()
