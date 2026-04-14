"""Tests for lib/metadata.py"""

import json
import tempfile
import unittest
from pathlib import Path

from lib.metadata import (
    build_empty_metadata,
    create_default_config,
    load_config,
    validate_metadata,
)


class TestCreateDefaultConfig(unittest.TestCase):
    def test_creates_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "meta_config.json"
            create_default_config(str(config_path))
            self.assertTrue(config_path.exists())
            config = load_config(str(config_path))
            self.assertIn("fields", config)
            self.assertIn("scan_directories", config)
            self.assertIn("file_extensions", config)


class TestLoadConfig(unittest.TestCase):
    def _write(self, tmp, data):
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_valid_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "fields": [{"name": "title", "type": "text"}]
            })
            config = load_config(path)
            self.assertEqual(len(config["fields"]), 1)

    def test_missing_fields_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"stuff": []})
            with self.assertRaises(ValueError):
                load_config(path)

    def test_invalid_field_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "fields": [{"name": "x", "type": "number"}]
            })
            with self.assertRaises(ValueError):
                load_config(path)

    def test_choice_without_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {
                "fields": [{"name": "x", "type": "choice"}]
            })
            with self.assertRaises(ValueError):
                load_config(path)

    def test_defaults_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"fields": []})
            config = load_config(path)
            self.assertEqual(config["scan_directories"], ["."])
            self.assertEqual(config["file_extensions"], [".pdf"])


class TestValidateMetadata(unittest.TestCase):
    CONFIG = {
        "fields": [
            {"name": "title", "type": "text", "required": True, "default": ""},
            {"name": "genre", "type": "choice", "required": False, "default": "",
             "choices": ["A", "B"]},
            {"name": "tags", "type": "list", "required": False, "default": []},
        ]
    }

    def test_valid(self):
        errors = validate_metadata(self.CONFIG, {
            "title": "Test", "genre": "A", "tags": ["x"]
        })
        self.assertEqual(errors, [])

    def test_required_empty(self):
        errors = validate_metadata(self.CONFIG, {"title": ""})
        self.assertTrue(any("Required" in e for e in errors))

    def test_invalid_choice(self):
        errors = validate_metadata(self.CONFIG, {"title": "ok", "genre": "Z"})
        self.assertTrue(any("not in choices" in e for e in errors))

    def test_list_wrong_type(self):
        errors = validate_metadata(self.CONFIG, {"title": "ok", "tags": "bad"})
        self.assertTrue(any("must be a list" in e for e in errors))


class TestBuildEmptyMetadata(unittest.TestCase):
    def test_defaults(self):
        config = {
            "fields": [
                {"name": "title", "type": "text", "default": ""},
                {"name": "tags", "type": "list", "default": ["a"]},
            ]
        }
        meta = build_empty_metadata(config)
        self.assertEqual(meta["title"], "")
        self.assertEqual(meta["tags"], ["a"])
        # Ensure list is a copy
        meta["tags"].append("b")
        meta2 = build_empty_metadata(config)
        self.assertEqual(meta2["tags"], ["a"])


if __name__ == "__main__":
    unittest.main()
