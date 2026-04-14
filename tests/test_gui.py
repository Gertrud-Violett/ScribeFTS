"""Tests for Flask GUI routes."""

import json
import tempfile
import unittest
from pathlib import Path

from gui.app import create_app


class GUITestBase(unittest.TestCase):
    """Base class providing a Flask test client with temp data."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = str(Path(self.tmp.name) / "data")
        self.scan_dir = Path(self.tmp.name) / "docs"
        self.scan_dir.mkdir()

        # Create test files
        (self.scan_dir / "paper1.pdf").write_bytes(b"PDF content 1")
        (self.scan_dir / "paper2.pdf").write_bytes(b"PDF content 2")

        # Write config pointing to our scan dir
        data_path = Path(self.data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        config = {
            "scan_directories": [str(self.scan_dir)],
            "file_extensions": [".pdf"],
            "fields": [
                {"name": "title", "type": "text", "required": False, "default": ""},
                {"name": "genre", "type": "choice", "required": False, "default": "",
                 "choices": ["A", "B"]},
                {"name": "keywords", "type": "list", "required": False, "default": []},
            ],
        }
        (data_path / "meta_config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )

        self.app = create_app(data_dir=self.data_dir)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Trigger initial refresh
        self.client.post("/refresh")

    def tearDown(self):
        self.tmp.cleanup()


class TestIndex(GUITestBase):
    def test_index_returns_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_index_lists_files(self):
        resp = self.client.get("/")
        self.assertIn(b"paper1.pdf", resp.data)
        self.assertIn(b"paper2.pdf", resp.data)

    def test_sort_param(self):
        resp = self.client.get("/?sort=file_size")
        self.assertEqual(resp.status_code, 200)


class TestRefresh(GUITestBase):
    def test_refresh_redirects(self):
        resp = self.client.post("/refresh")
        self.assertEqual(resp.status_code, 302)


class TestDetail(GUITestBase):
    def _get_hash(self):
        resp = self.client.get("/")
        # Extract a file hash from the response
        data = resp.data.decode()
        # Find href="/entry/<hash>"
        import re
        match = re.search(r'/entry/([a-f0-9]{20})', data)
        return match.group(1) if match else None

    def test_detail_returns_200(self):
        fh = self._get_hash()
        self.assertIsNotNone(fh)
        resp = self.client.get(f"/entry/{fh}")
        self.assertEqual(resp.status_code, 200)

    def test_detail_not_found(self):
        resp = self.client.get("/entry/00000000000000000000")
        self.assertEqual(resp.status_code, 302)  # redirect with flash


class TestEditEntry(GUITestBase):
    def _get_hash(self):
        resp = self.client.get("/")
        import re
        match = re.search(r'/entry/([a-f0-9]{20})', resp.data.decode())
        return match.group(1) if match else None

    def test_edit_get(self):
        fh = self._get_hash()
        resp = self.client.get(f"/entry/{fh}/edit")
        self.assertEqual(resp.status_code, 200)

    def test_edit_post(self):
        fh = self._get_hash()
        resp = self.client.post(f"/entry/{fh}/edit", data={
            "title": "New Title",
            "genre": "A",
            "keywords": "kw1, kw2",
        })
        self.assertEqual(resp.status_code, 302)


class TestDeleteEntry(GUITestBase):
    def _get_hash(self):
        resp = self.client.get("/")
        import re
        match = re.search(r'/entry/([a-f0-9]{20})', resp.data.decode())
        return match.group(1) if match else None

    def test_delete_entry(self):
        fh = self._get_hash()
        resp = self.client.post(f"/entry/{fh}/delete")
        self.assertEqual(resp.status_code, 302)


class TestDeleteOld(GUITestBase):
    def test_delete_old_no_missing(self):
        resp = self.client.post("/delete-old")
        self.assertEqual(resp.status_code, 302)


class TestSearch(GUITestBase):
    def test_search_returns_results(self):
        resp = self.client.get("/search?q=paper1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"paper1.pdf", resp.data)

    def test_search_empty_redirects(self):
        resp = self.client.get("/search?q=")
        self.assertEqual(resp.status_code, 302)


class TestExport(GUITestBase):
    def test_export(self):
        resp = self.client.post("/export")
        self.assertEqual(resp.status_code, 302)
        export_path = Path(self.data_dir) / "library_export.json"
        self.assertTrue(export_path.exists())


class TestStats(GUITestBase):
    def test_stats_returns_200(self):
        resp = self.client.get("/stats")
        self.assertEqual(resp.status_code, 200)


class TestConfig(GUITestBase):
    def test_config_get(self):
        resp = self.client.get("/config")
        self.assertEqual(resp.status_code, 200)

    def test_config_post_valid(self):
        config = {
            "scan_directories": [str(self.scan_dir)],
            "file_extensions": [".pdf"],
            "fields": [
                {"name": "title", "type": "text", "required": False, "default": ""},
            ],
        }
        resp = self.client.post("/config", data={"config_json": json.dumps(config)})
        self.assertEqual(resp.status_code, 302)

    def test_config_post_invalid_json(self):
        resp = self.client.post("/config", data={"config_json": "not json"})
        self.assertEqual(resp.status_code, 200)  # stays on page with error


if __name__ == "__main__":
    unittest.main()
