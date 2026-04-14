"""SQLite database operations for the NHI Librarian catalog."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from lib.scanner import FileInfo


def open_db(db_path: str) -> sqlite3.Connection:
    """Open (or create) the SQLite database. Creates tables if they don't exist."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            file_hash     TEXT PRIMARY KEY,
            filename      TEXT NOT NULL,
            rel_path      TEXT NOT NULL,
            file_size     INTEGER NOT NULL,
            date_added    TEXT NOT NULL,
            date_modified TEXT NOT NULL,
            missing       INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS metadata (
            file_hash   TEXT NOT NULL,
            field_name  TEXT NOT NULL,
            field_value TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (file_hash, field_name),
            FOREIGN KEY (file_hash) REFERENCES files(file_hash) ON DELETE CASCADE
        );
    """)
    conn.commit()
    return conn


def add_entry(conn: sqlite3.Connection, file_info: FileInfo, metadata: dict) -> None:
    """Insert a new file entry and its metadata rows."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO files (file_hash, filename, rel_path, file_size, date_added, date_modified, missing) "
        "VALUES (?, ?, ?, ?, ?, ?, 0)",
        (file_info.file_hash, file_info.filename, file_info.rel_path, file_info.file_size, now, now),
    )
    for field_name, value in metadata.items():
        stored = json.dumps(value) if isinstance(value, list) else str(value)
        conn.execute(
            "INSERT INTO metadata (file_hash, field_name, field_value) VALUES (?, ?, ?)",
            (file_info.file_hash, field_name, stored),
        )
    conn.commit()


def update_path(conn: sqlite3.Connection, file_hash: str, new_rel_path: str) -> None:
    """Update the stored path when a file has moved."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE files SET rel_path = ?, date_modified = ?, missing = 0 WHERE file_hash = ?",
        (new_rel_path, now, file_hash),
    )
    conn.commit()


def mark_missing(conn: sqlite3.Connection, file_hash: str) -> None:
    """Flag a file as missing (not found on last scan)."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE files SET missing = 1, date_modified = ? WHERE file_hash = ?",
        (now, file_hash),
    )
    conn.commit()


def update_metadata(conn: sqlite3.Connection, file_hash: str, field: str, value) -> None:
    """Insert or update a single metadata field."""
    stored = json.dumps(value) if isinstance(value, list) else str(value)
    conn.execute(
        "INSERT INTO metadata (file_hash, field_name, field_value) VALUES (?, ?, ?) "
        "ON CONFLICT(file_hash, field_name) DO UPDATE SET field_value = excluded.field_value",
        (file_hash, field, stored),
    )
    conn.commit()


def delete_entry(conn: sqlite3.Connection, file_hash: str) -> None:
    """Remove an entry and its metadata from the database."""
    conn.execute("DELETE FROM files WHERE file_hash = ?", (file_hash,))
    conn.commit()


def delete_missing_entries(conn: sqlite3.Connection) -> int:
    """Remove all entries flagged as missing. Returns the number of entries deleted."""
    cursor = conn.execute("DELETE FROM files WHERE missing = 1")
    conn.commit()
    return cursor.rowcount


def get_entry(conn: sqlite3.Connection, file_hash: str) -> dict | None:
    """Get a single entry with all its metadata. Returns None if not found."""
    row = conn.execute("SELECT * FROM files WHERE file_hash = ?", (file_hash,)).fetchone()
    if row is None:
        return None

    entry = dict(row)
    meta_rows = conn.execute(
        "SELECT field_name, field_value FROM metadata WHERE file_hash = ?",
        (file_hash,),
    ).fetchall()
    entry["metadata"] = {r["field_name"]: r["field_value"] for r in meta_rows}
    return entry


def resolve_hash_prefix(conn: sqlite3.Connection, prefix: str) -> str | None:
    """Resolve a partial hash prefix to a full hash. Returns None if no match or ambiguous."""
    rows = conn.execute(
        "SELECT file_hash FROM files WHERE file_hash LIKE ?",
        (prefix + "%",),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]["file_hash"]
    return None


def find_entries(conn: sqlite3.Connection, query: str) -> list[dict]:
    """Search entries by filename, title, or any metadata value."""
    pattern = f"%{query}%"
    # Search in files table
    file_hashes = set()
    rows = conn.execute(
        "SELECT file_hash FROM files WHERE filename LIKE ?",
        (pattern,),
    ).fetchall()
    file_hashes.update(r["file_hash"] for r in rows)

    # Search in metadata values
    rows = conn.execute(
        "SELECT DISTINCT file_hash FROM metadata WHERE field_value LIKE ?",
        (pattern,),
    ).fetchall()
    file_hashes.update(r["file_hash"] for r in rows)

    results = []
    for fh in file_hashes:
        entry = get_entry(conn, fh)
        if entry:
            results.append(entry)
    return results


def list_entries(conn: sqlite3.Connection, sort_by: str = "filename",
                 filters: dict | None = None) -> list[dict]:
    """List/filter/sort all entries."""
    allowed_sort = {"filename", "date_added", "date_modified", "file_size", "rel_path"}
    if sort_by not in allowed_sort:
        sort_by = "filename"

    rows = conn.execute(f"SELECT file_hash FROM files ORDER BY {sort_by}").fetchall()

    results = []
    for row in rows:
        entry = get_entry(conn, row["file_hash"])
        if entry is None:
            continue

        # Apply metadata filters
        if filters:
            match = True
            for key, val in filters.items():
                meta_val = entry["metadata"].get(key, "")
                if val.lower() not in meta_val.lower():
                    match = False
                    break
            if not match:
                continue

        results.append(entry)
    return results


def get_all_paths(conn: sqlite3.Connection) -> dict[str, str]:
    """Return dict of file_hash -> rel_path for all non-missing entries."""
    rows = conn.execute(
        "SELECT file_hash, rel_path FROM files WHERE missing = 0"
    ).fetchall()
    return {r["file_hash"]: r["rel_path"] for r in rows}


def export_json(conn: sqlite3.Connection, out_path: str) -> None:
    """Export the entire database to a JSON file."""
    entries = list_entries(conn)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
