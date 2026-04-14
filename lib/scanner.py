"""File system scanning and move detection."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileInfo:
    """Information about a single scanned file."""
    file_hash: str
    filename: str
    rel_path: str
    file_size: int


@dataclass
class ScanReport:
    """Results of comparing a scan against the database."""
    new: list[FileInfo] = field(default_factory=list)
    moved: list[tuple[FileInfo, str]] = field(default_factory=list)  # (file_info, old_rel_path)
    missing: list[str] = field(default_factory=list)  # file_hashes no longer on disk


def compute_hash(file_path: Path) -> str:
    """Compute SHA-256 content hash of first 64 KB + file size."""
    file_size = file_path.stat().st_size
    digest = hashlib.sha256()
    with file_path.open("rb") as f:
        digest.update(f.read(65536))
    digest.update(str(file_size).encode())
    return digest.hexdigest()[:20]


def scan_directory(root_dir: str, extensions: list[str]) -> list[FileInfo]:
    """Recursively find all files matching extensions under root_dir.

    Args:
        root_dir: Directory path to scan.
        extensions: List of file extensions to match (e.g. [".pdf"]).
                    Use [".*"] to match all files.

    Returns:
        List of FileInfo for each matching file found.
    """
    root = Path(root_dir).resolve()
    results = []
    match_all = ".*" in extensions
    ext_set = {e.lower() for e in extensions}

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if not match_all and path.suffix.lower() not in ext_set:
            continue

        file_hash = compute_hash(path)
        rel_path = str(path.relative_to(root))
        results.append(FileInfo(
            file_hash=file_hash,
            filename=path.name,
            rel_path=rel_path,
            file_size=path.stat().st_size,
        ))

    return results


def detect_changes(current_scan: list[FileInfo], db_entries: dict[str, str]) -> ScanReport:
    """Compare scan results against the database.

    Args:
        current_scan: List of FileInfo from scanning.
        db_entries: Dict mapping file_hash -> rel_path from the database.

    Returns:
        ScanReport with new, moved, and missing file lists.
    """
    report = ScanReport()

    scanned_hashes = set()
    for fi in current_scan:
        scanned_hashes.add(fi.file_hash)

        if fi.file_hash not in db_entries:
            report.new.append(fi)
        elif db_entries[fi.file_hash] != fi.rel_path:
            report.moved.append((fi, db_entries[fi.file_hash]))

    for db_hash in db_entries:
        if db_hash not in scanned_hashes:
            report.missing.append(db_hash)

    return report
