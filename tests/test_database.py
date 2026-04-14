"""Tests for lib/database.py"""

import tempfile
import unittest
from pathlib import Path

from lib.database import (
    add_entry,
    delete_entry,
    delete_missing_entries,
    export_json,
    find_entries,
    get_all_paths,
    get_entry,
    list_entries,
    mark_missing,
    open_db,
    resolve_hash_prefix,
    update_metadata,
    update_path,
)
from lib.scanner import FileInfo


class DatabaseTestBase(unittest.TestCase):
    """Base class providing a fresh temp database for each test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.db")
        self.conn = open_db(self.db_path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _sample_file(self, hash_val="abc123def456", name="test.pdf", path="docs/test.pdf"):
        return FileInfo(file_hash=hash_val, filename=name, rel_path=path, file_size=1024)


class TestOpenDb(DatabaseTestBase):
    def test_creates_tables(self):
        tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r["name"] for r in tables}
        self.assertIn("files", names)
        self.assertIn("metadata", names)


class TestAddAndGetEntry(DatabaseTestBase):
    def test_add_and_retrieve(self):
        fi = self._sample_file()
        meta = {"title": "Test Doc", "genre": "Bearings"}
        add_entry(self.conn, fi, meta)

        entry = get_entry(self.conn, fi.file_hash)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["filename"], "test.pdf")
        self.assertEqual(entry["metadata"]["title"], "Test Doc")
        self.assertEqual(entry["metadata"]["genre"], "Bearings")


class TestUpdatePath(DatabaseTestBase):
    def test_path_update(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {})
        update_path(self.conn, fi.file_hash, "new/path/test.pdf")
        entry = get_entry(self.conn, fi.file_hash)
        self.assertEqual(entry["rel_path"], "new/path/test.pdf")
        self.assertEqual(entry["missing"], 0)


class TestMarkMissing(DatabaseTestBase):
    def test_mark_and_check(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {})
        mark_missing(self.conn, fi.file_hash)
        entry = get_entry(self.conn, fi.file_hash)
        self.assertEqual(entry["missing"], 1)


class TestUpdateMetadata(DatabaseTestBase):
    def test_insert_and_update(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {"title": "old"})
        update_metadata(self.conn, fi.file_hash, "title", "new")
        entry = get_entry(self.conn, fi.file_hash)
        self.assertEqual(entry["metadata"]["title"], "new")

    def test_new_field(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {})
        update_metadata(self.conn, fi.file_hash, "notes", "some notes")
        entry = get_entry(self.conn, fi.file_hash)
        self.assertEqual(entry["metadata"]["notes"], "some notes")


class TestDeleteEntry(DatabaseTestBase):
    def test_delete(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {"title": "x"})
        delete_entry(self.conn, fi.file_hash)
        self.assertIsNone(get_entry(self.conn, fi.file_hash))


class TestResolveHashPrefix(DatabaseTestBase):
    def test_unique_prefix(self):
        fi = self._sample_file(hash_val="abcdef1234567890")
        add_entry(self.conn, fi, {})
        self.assertEqual(resolve_hash_prefix(self.conn, "abcdef1"), "abcdef1234567890")

    def test_ambiguous_prefix(self):
        add_entry(self.conn, self._sample_file(hash_val="abc111"), {})
        add_entry(self.conn, self._sample_file(hash_val="abc222", name="b.pdf", path="b.pdf"), {})
        self.assertIsNone(resolve_hash_prefix(self.conn, "abc"))

    def test_no_match(self):
        self.assertIsNone(resolve_hash_prefix(self.conn, "zzz"))


class TestFindEntries(DatabaseTestBase):
    def test_search_by_filename(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {})
        results = find_entries(self.conn, "test")
        self.assertEqual(len(results), 1)

    def test_search_by_metadata(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {"title": "Bearing Analysis"})
        results = find_entries(self.conn, "Bearing")
        self.assertEqual(len(results), 1)


class TestListEntries(DatabaseTestBase):
    def test_list_all(self):
        add_entry(self.conn, self._sample_file(hash_val="h1", name="a.pdf", path="a.pdf"), {})
        add_entry(self.conn, self._sample_file(hash_val="h2", name="b.pdf", path="b.pdf"), {})
        results = list_entries(self.conn)
        self.assertEqual(len(results), 2)

    def test_filter_by_genre(self):
        add_entry(self.conn, self._sample_file(hash_val="h1", name="a.pdf", path="a.pdf"),
                  {"genre": "Bearings"})
        add_entry(self.conn, self._sample_file(hash_val="h2", name="b.pdf", path="b.pdf"),
                  {"genre": "Turbine"})
        results = list_entries(self.conn, filters={"genre": "Bearings"})
        self.assertEqual(len(results), 1)


class TestGetAllPaths(DatabaseTestBase):
    def test_excludes_missing(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {})
        mark_missing(self.conn, fi.file_hash)
        paths = get_all_paths(self.conn)
        self.assertEqual(len(paths), 0)


class TestExportJson(DatabaseTestBase):
    def test_export(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {"title": "Export Test"})
        out_path = str(Path(self.tmp.name) / "export.json")
        export_json(self.conn, out_path)
        self.assertTrue(Path(out_path).exists())
        import json
        with open(out_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["filename"], "test.pdf")


class TestDeleteMissingEntries(DatabaseTestBase):
    def test_deletes_missing(self):
        fi1 = self._sample_file(hash_val="h1", name="a.pdf", path="a.pdf")
        fi2 = self._sample_file(hash_val="h2", name="b.pdf", path="b.pdf")
        add_entry(self.conn, fi1, {"title": "A"})
        add_entry(self.conn, fi2, {"title": "B"})
        mark_missing(self.conn, "h1")
        count = delete_missing_entries(self.conn)
        self.assertEqual(count, 1)
        self.assertIsNone(get_entry(self.conn, "h1"))
        self.assertIsNotNone(get_entry(self.conn, "h2"))

    def test_no_missing(self):
        fi = self._sample_file()
        add_entry(self.conn, fi, {})
        count = delete_missing_entries(self.conn)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
