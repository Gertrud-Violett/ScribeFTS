"""Tests for lib/api.py"""

import tempfile
import unittest
from pathlib import Path

from lib.api import NHILibrarian


class TestNHILibrarian(unittest.TestCase):
    """Integration tests using real temp directories and sample files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.scan_dir = Path(self.tmp.name) / "docs"
        self.scan_dir.mkdir()

        # Create test files
        (self.scan_dir / "paper1.pdf").write_bytes(b"PDF content 1")
        (self.scan_dir / "paper2.pdf").write_bytes(b"PDF content 2")
        sub = self.scan_dir / "subdir"
        sub.mkdir()
        (sub / "paper3.pdf").write_bytes(b"PDF content 3")

        self.lib = NHILibrarian(
            data_dir=str(self.data_dir),
            scan_dirs=[str(self.scan_dir)],
        )

    def tearDown(self):
        self.lib.close()
        self.tmp.cleanup()

    def test_refresh_finds_files(self):
        report = self.lib.refresh()
        self.assertEqual(len(report.new), 3)

    def test_refresh_idempotent(self):
        self.lib.refresh()
        report = self.lib.refresh()
        self.assertEqual(len(report.new), 0)
        self.assertEqual(len(report.moved), 0)
        self.assertEqual(len(report.missing), 0)

    def test_list_all(self):
        self.lib.refresh()
        entries = self.lib.list_all()
        self.assertEqual(len(entries), 3)

    def test_search(self):
        self.lib.refresh()
        results = self.lib.search("paper1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["filename"], "paper1.pdf")

    def test_get_entry_by_prefix(self):
        self.lib.refresh()
        entries = self.lib.list_all()
        full_hash = entries[0]["file_hash"]
        entry = self.lib.get_entry(full_hash[:7])
        self.assertIsNotNone(entry)
        self.assertEqual(entry["file_hash"], full_hash)

    def test_update_metadata(self):
        self.lib.refresh()
        entries = self.lib.list_all()
        fh = entries[0]["file_hash"]
        self.lib.update_metadata(fh[:7], {"title": "My Paper"})
        entry = self.lib.get_entry(fh)
        self.assertEqual(entry["metadata"]["title"], "My Paper")

    def test_delete_entry(self):
        self.lib.refresh()
        entries = self.lib.list_all()
        fh = entries[0]["file_hash"]
        self.lib.delete_entry(fh[:7])
        self.assertIsNone(self.lib.get_entry(fh))
        self.assertEqual(len(self.lib.list_all()), 2)

    def test_export_json(self):
        self.lib.refresh()
        out = str(self.data_dir / "export.json")
        self.lib.export_json(out)
        self.assertTrue(Path(out).exists())

    def test_default_config_created(self):
        self.assertTrue(self.lib.config_path.exists())
        config = self.lib.get_meta_config()
        self.assertIn("fields", config)

    def test_move_detection(self):
        self.lib.refresh()
        # Move a file
        src = self.scan_dir / "paper1.pdf"
        dest = self.scan_dir / "subdir" / "paper1.pdf"
        src.rename(dest)
        report = self.lib.refresh()
        self.assertEqual(len(report.moved), 1)

    def test_missing_detection(self):
        self.lib.refresh()
        (self.scan_dir / "paper2.pdf").unlink()
        report = self.lib.refresh()
        self.assertEqual(len(report.missing), 1)

    def test_auto_genre_from_folder(self):
        """Files in subfolders get their parent folder name as genre."""
        self.lib.refresh()
        # paper3.pdf is in subdir/
        entries = self.lib.list_all()
        subdir_entry = [e for e in entries if e["filename"] == "paper3.pdf"][0]
        self.assertEqual(subdir_entry["metadata"]["genre"], "subdir")

    def test_auto_genre_root_stays_empty(self):
        """Files at the scan root get empty genre."""
        self.lib.refresh()
        entries = self.lib.list_all()
        root_entry = [e for e in entries if e["filename"] == "paper1.pdf"][0]
        self.assertEqual(root_entry["metadata"]["genre"], "")

    def test_auto_genre_adds_to_choices(self):
        """New folder names are added to genre choices in meta_config.json."""
        self.lib.refresh()
        config = self.lib.get_meta_config()
        genre_field = [f for f in config["fields"] if f["name"] == "genre"][0]
        self.assertIn("subdir", genre_field["choices"])

    def test_delete_missing(self):
        self.lib.refresh()
        (self.scan_dir / "paper2.pdf").unlink()
        self.lib.refresh()  # flags paper2 as missing
        count = self.lib.delete_missing()
        self.assertEqual(count, 1)
        self.assertEqual(len(self.lib.list_all()), 2)

    def test_delete_missing_none(self):
        self.lib.refresh()
        count = self.lib.delete_missing()
        self.assertEqual(count, 0)

    def test_save_meta_config(self):
        config = self.lib.get_meta_config()
        config["fields"].append({"name": "extra", "type": "text", "required": False, "default": ""})
        self.lib.save_meta_config(config)
        reloaded = self.lib.get_meta_config()
        field_names = [f["name"] for f in reloaded["fields"]]
        self.assertIn("extra", field_names)

    def test_save_meta_config_invalid(self):
        with self.assertRaises(ValueError):
            self.lib.save_meta_config({"no_fields_key": True})


if __name__ == "__main__":
    unittest.main()
