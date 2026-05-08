"""Tests for lib/fts.py"""

import tempfile
import unittest
from pathlib import Path

from lib.fts import (
    extract_text,
    fts_search,
    index_document,
    open_fts_db,
    rebuild_index,
    remove_document,
)
from lib.database import open_db, add_entry
from lib.scanner import FileInfo


class TestOpenFtsDb(unittest.TestCase):
    def test_creates_db_and_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            fts_path = str(Path(tmp) / "fts.db")
            conn = open_fts_db(fts_path)
            self.assertTrue(Path(fts_path).exists())
            # Table should be queryable
            rows = conn.execute(
                "SELECT * FROM documents_fts WHERE documents_fts MATCH 'test'"
            ).fetchall()
            self.assertEqual(rows, [])
            conn.close()

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            fts_path = str(Path(tmp) / "fts.db")
            conn1 = open_fts_db(fts_path)
            conn1.close()
            conn2 = open_fts_db(fts_path)
            conn2.close()


class TestExtractText(unittest.TestCase):
    def test_nonexistent_file_returns_empty(self):
        result = extract_text("/nonexistent/path/file.pdf")
        self.assertEqual(result, "")

    def test_non_pdf_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt_file = Path(tmp) / "doc.txt"
            txt_file.write_text("hello world", encoding="utf-8")
            result = extract_text(txt_file)
            # Either empty (PyMuPDF not installed) or extracted text
            self.assertIsInstance(result, str)


class TestIndexAndSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        fts_path = str(Path(self.tmp.name) / "fts.db")
        self.conn = open_fts_db(fts_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_index_and_find(self):
        index_document(self.conn, "abc123", "paper.pdf", "rotordynamics bearings", "")
        results = fts_search(self.conn, "rotordynamics")
        self.assertIn("abc123", results)

    def test_index_replaces_existing(self):
        index_document(self.conn, "abc123", "paper.pdf", "old content", "")
        index_document(self.conn, "abc123", "paper.pdf", "new content", "")
        results = fts_search(self.conn, "old")
        self.assertNotIn("abc123", results)
        results = fts_search(self.conn, "new")
        self.assertIn("abc123", results)

    def test_remove_document(self):
        index_document(self.conn, "abc123", "paper.pdf", "rotordynamics", "")
        remove_document(self.conn, "abc123")
        results = fts_search(self.conn, "rotordynamics")
        self.assertNotIn("abc123", results)

    def test_search_body(self):
        index_document(self.conn, "xyz789", "report.pdf", "", "thrust load calculation")
        results = fts_search(self.conn, "thrust")
        self.assertIn("xyz789", results)

    def test_search_no_results(self):
        results = fts_search(self.conn, "nonexistent_term_xyz")
        self.assertEqual(results, [])

    def test_multiple_documents(self):
        index_document(self.conn, "h1", "a.pdf", "bearings fatigue", "")
        index_document(self.conn, "h2", "b.pdf", "compressor vibration", "")
        r1 = fts_search(self.conn, "bearings")
        r2 = fts_search(self.conn, "compressor")
        self.assertIn("h1", r1)
        self.assertNotIn("h2", r1)
        self.assertIn("h2", r2)


class TestRebuildIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)

        self.lib_path = str(tmp_path / "library.db")
        self.fts_path = str(tmp_path / "fts.db")
        self.scan_dir = tmp_path / "docs"
        self.scan_dir.mkdir()

        # Create dummy files
        (self.scan_dir / "doc1.pdf").write_bytes(b"dummy")
        (self.scan_dir / "doc2.pdf").write_bytes(b"dummy2")

        self.lib_conn = open_db(self.lib_path)
        self.fts_conn = open_fts_db(self.fts_path)

        # Add entries to library.db
        fi1 = FileInfo(file_hash="a" * 20, filename="doc1.pdf",
                       rel_path="doc1.pdf", file_size=5)
        fi2 = FileInfo(file_hash="b" * 20, filename="doc2.pdf",
                       rel_path="doc2.pdf", file_size=6)
        add_entry(self.lib_conn, fi1, {"title": "Doc One", "genre": ""})
        add_entry(self.lib_conn, fi2, {"title": "Doc Two", "genre": ""})

    def tearDown(self):
        self.lib_conn.close()
        self.fts_conn.close()
        self.tmp.cleanup()

    def test_rebuild_indexes_all_entries(self):
        count = rebuild_index(self.fts_conn, self.lib_conn, [str(self.scan_dir)])
        self.assertEqual(count, 2)

    def test_rebuild_clears_old_entries(self):
        # Pre-populate with stale entry
        index_document(self.fts_conn, "stale000000000000000", "old.pdf", "stale", "")
        rebuild_index(self.fts_conn, self.lib_conn, [str(self.scan_dir)])
        results = fts_search(self.fts_conn, "stale")
        self.assertNotIn("stale000000000000000", results)

    def test_rebuild_entries_searchable(self):
        rebuild_index(self.fts_conn, self.lib_conn, [str(self.scan_dir)])
        results = fts_search(self.fts_conn, "One")
        self.assertIn("a" * 20, results)


if __name__ == "__main__":
    unittest.main()
