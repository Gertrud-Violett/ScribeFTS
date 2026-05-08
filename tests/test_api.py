"""Tests for lib/api.py"""

import tempfile
import unittest
from pathlib import Path

from lib.api import ScribeFTS


class TestScribeFTS(unittest.TestCase):
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

        self.lib = ScribeFTS(
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

    def test_fts_db_created(self):
        """fts.db is created alongside library.db on init."""
        self.assertTrue(self.lib.fts_db_path.exists())

    def test_fts_search_after_refresh(self):
        """fts_search returns results after refresh indexes files."""
        self.lib.refresh()
        results = self.lib.fts_search("paper1")
        filenames = [e["filename"] for e in results]
        self.assertIn("paper1.pdf", filenames)

    def test_reindex_fts(self):
        self.lib.refresh()
        count = self.lib.reindex_fts()
        self.assertEqual(count, 3)

    def test_fts_search_removed_after_delete(self):
        self.lib.refresh()
        entries = self.lib.list_all()
        fh = entries[0]["file_hash"]
        filename = entries[0]["filename"]
        self.lib.delete_entry(fh[:7])
        results = self.lib.fts_search(Path(filename).stem)
        result_filenames = [e["filename"] for e in results]
        self.assertNotIn(filename, result_filenames)

    # -- Draft staging tests --

    def _get_first_hash(self):
        self.lib.refresh()
        return self.lib.list_all()[0]["file_hash"]

    def test_get_draft_empty_initially(self):
        fh = self._get_first_hash()
        draft = self.lib.get_draft(fh)
        self.assertEqual(draft, {})

    def test_get_pending_draft_hashes_empty(self):
        self._get_first_hash()
        pending = self.lib.get_pending_draft_hashes()
        self.assertEqual(pending, set())

    def test_discard_draft_noop_when_empty(self):
        fh = self._get_first_hash()
        self.lib.discard_draft(fh)  # should not raise
        self.assertEqual(self.lib.get_draft(fh), {})

    def test_commit_all_drafts_empty(self):
        self._get_first_hash()
        count = self.lib.commit_all_drafts()
        self.assertEqual(count, 0)

    def test_suggest_all_skips_missing(self):
        """suggest_all should not crash when entries are missing from disk."""
        self.lib.refresh()
        # Remove a file so one entry becomes missing
        (self.scan_dir / "paper1.pdf").unlink()
        self.lib.refresh()
        counts = self.lib.suggest_all()
        # Should return a dict with 'suggested' and 'auto_committed' keys
        self.assertIn("suggested", counts)
        self.assertIn("auto_committed", counts)

    def test_get_ai_config_creates_default(self):
        cfg = self.lib.get_ai_config()
        self.assertIn("enabled", cfg)
        self.assertIn("provider", cfg)
        self.assertIn("api_key", cfg)
        self.assertIn("model", cfg)
        self.assertIn("auto_commit_threshold", cfg)
        self.assertFalse(cfg["enabled"])

    def test_save_ai_config_valid(self):
        self.lib.save_ai_config({
            "enabled": True,
            "provider": "gemini",
            "api_key": "test-key",
            "model": "gemini-1.5-flash",
            "auto_commit_threshold": 0.9,
            "openai_endpoint": "https://api.openai.com/v1/chat/completions",
        })
        cfg = self.lib.get_ai_config()
        self.assertEqual(cfg["api_key"], "test-key")
        self.assertAlmostEqual(cfg["auto_commit_threshold"], 0.9)

    def test_save_ai_config_invalid_provider(self):
        with self.assertRaises(ValueError):
            self.lib.save_ai_config({
                "enabled": False,
                "provider": "unknown_provider",
                "api_key": "",
                "model": "x",
                "auto_commit_threshold": 0.8,
            })

    def test_save_ai_config_invalid_threshold(self):
        with self.assertRaises(ValueError):
            self.lib.save_ai_config({
                "enabled": False,
                "provider": "gemini",
                "api_key": "",
                "model": "x",
                "auto_commit_threshold": 1.5,
            })


if __name__ == "__main__":
    unittest.main()
