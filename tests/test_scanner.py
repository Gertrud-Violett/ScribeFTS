"""Tests for lib/scanner.py"""

import tempfile
import unittest
from pathlib import Path

from lib.scanner import FileInfo, compute_hash, detect_changes, scan_directory


class TestComputeHash(unittest.TestCase):
    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "test.pdf"
            f.write_bytes(b"hello world")
            h1 = compute_hash(f)
            h2 = compute_hash(f)
            self.assertEqual(h1, h2)

    def test_different_content_different_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            f1 = Path(tmp) / "a.pdf"
            f2 = Path(tmp) / "b.pdf"
            f1.write_bytes(b"content A")
            f2.write_bytes(b"content B")
            self.assertNotEqual(compute_hash(f1), compute_hash(f2))


class TestScanDirectory(unittest.TestCase):
    def test_finds_matching_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.pdf").write_bytes(b"pdf1")
            (Path(tmp) / "b.txt").write_bytes(b"txt1")
            sub = Path(tmp) / "sub"
            sub.mkdir()
            (sub / "c.pdf").write_bytes(b"pdf2")

            results = scan_directory(tmp, [".pdf"])
            names = {fi.filename for fi in results}
            self.assertEqual(names, {"a.pdf", "c.pdf"})

    def test_wildcard_matches_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.pdf").write_bytes(b"pdf")
            (Path(tmp) / "b.txt").write_bytes(b"txt")
            results = scan_directory(tmp, [".*"])
            self.assertEqual(len(results), 2)

    def test_multiple_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.pdf").write_bytes(b"pdf")
            (Path(tmp) / "b.doc").write_bytes(b"doc")
            (Path(tmp) / "c.txt").write_bytes(b"txt")
            results = scan_directory(tmp, [".pdf", ".doc"])
            names = {fi.filename for fi in results}
            self.assertEqual(names, {"a.pdf", "b.doc"})


class TestDetectChanges(unittest.TestCase):
    def test_new_files(self):
        files = [FileInfo("hash1", "a.pdf", "a.pdf", 100)]
        report = detect_changes(files, {})
        self.assertEqual(len(report.new), 1)
        self.assertEqual(len(report.moved), 0)
        self.assertEqual(len(report.missing), 0)

    def test_moved_file(self):
        files = [FileInfo("hash1", "a.pdf", "new/a.pdf", 100)]
        db = {"hash1": "old/a.pdf"}
        report = detect_changes(files, db)
        self.assertEqual(len(report.new), 0)
        self.assertEqual(len(report.moved), 1)
        self.assertEqual(report.moved[0][1], "old/a.pdf")

    def test_missing_file(self):
        files = []
        db = {"hash1": "a.pdf"}
        report = detect_changes(files, db)
        self.assertEqual(len(report.missing), 1)
        self.assertEqual(report.missing[0], "hash1")

    def test_unchanged_file(self):
        files = [FileInfo("hash1", "a.pdf", "a.pdf", 100)]
        db = {"hash1": "a.pdf"}
        report = detect_changes(files, db)
        self.assertEqual(len(report.new), 0)
        self.assertEqual(len(report.moved), 0)
        self.assertEqual(len(report.missing), 0)


if __name__ == "__main__":
    unittest.main()
