"""FTS5 search index operations and PDF text extraction for ScribeFTS."""

import sqlite3
from pathlib import Path


def open_fts_db(fts_db_path: str) -> sqlite3.Connection:
    """Open (or create) the FTS database and ensure the virtual table exists."""
    path = Path(fts_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            file_hash UNINDEXED,
            filename,
            metadata_text,
            body,
            tokenize = 'unicode61'
        )
    """)
    conn.commit()
    return conn


def extract_text(file_path: str | Path) -> str:
    """Extract plain text from a document file.

    Uses PyMuPDF for PDFs. Returns empty string on any failure (missing
    library, encrypted file, corrupt file, non-PDF type, etc.).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""

    try:
        doc = fitz.open(str(file_path))
        parts = []
        for page in doc:
            text = page.get_text()
            if text:
                parts.append(text)
        doc.close()
        return "\n".join(parts)
    except Exception:
        return ""


def index_document(
    fts_conn: sqlite3.Connection,
    file_hash: str,
    filename: str,
    metadata_text: str,
    body: str,
) -> None:
    """Add or replace one document in the FTS index.

    FTS5 virtual tables do not support reliable UPDATE, so we use DELETE + INSERT.
    """
    fts_conn.execute(
        "DELETE FROM documents_fts WHERE file_hash = ?",
        (file_hash,),
    )
    fts_conn.execute(
        "INSERT INTO documents_fts (file_hash, filename, metadata_text, body) "
        "VALUES (?, ?, ?, ?)",
        (file_hash, filename, metadata_text, body),
    )
    fts_conn.commit()


def remove_document(fts_conn: sqlite3.Connection, file_hash: str) -> None:
    """Remove a document from the FTS index."""
    fts_conn.execute(
        "DELETE FROM documents_fts WHERE file_hash = ?",
        (file_hash,),
    )
    fts_conn.commit()


def fts_search(fts_conn: sqlite3.Connection, query: str) -> list[str]:
    """Run an FTS5 query and return a list of matching file_hash values.

    The query string is passed directly to FTS5 MATCH, so callers may use
    FTS5 query syntax: phrases ("exact phrase"), column filters (body:term),
    and boolean operators (term1 AND term2).  Invalid queries raise sqlite3.OperationalError.
    """
    rows = fts_conn.execute(
        "SELECT file_hash FROM documents_fts WHERE documents_fts MATCH ?",
        (query,),
    ).fetchall()
    return [row["file_hash"] for row in rows]


def rebuild_index(
    fts_conn: sqlite3.Connection,
    lib_conn: sqlite3.Connection,
    scan_dirs: list[str],
    progress_callback=None,
) -> int:
    """Truncate and rebuild the entire FTS index from library.db.

    progress_callback(current, total) is called at each document (optional).
    Returns the number of documents indexed.
    """
    fts_conn.execute("DELETE FROM documents_fts")
    fts_conn.commit()

    rows = lib_conn.execute(
        "SELECT file_hash, filename, rel_path FROM files WHERE missing = 0"
    ).fetchall()

    total = len(rows)
    count = 0
    for i, row in enumerate(rows):
        file_hash = row["file_hash"]
        filename = row["filename"]
        rel_path = Path(row["rel_path"])

        # Fetch all metadata for this entry
        meta_rows = lib_conn.execute(
            "SELECT field_name, field_value FROM metadata WHERE file_hash = ?",
            (file_hash,),
        ).fetchall()
        meta = {r["field_name"]: r["field_value"] for r in meta_rows}
        metadata_text = " ".join(v for v in meta.values() if v)

        # Resolve file on disk
        body = ""
        for scan_dir in scan_dirs:
            candidate = (Path(scan_dir) / rel_path).resolve()
            if candidate.is_file():
                body = extract_text(candidate)
                break

        fts_conn.execute(
            "INSERT INTO documents_fts (file_hash, filename, metadata_text, body) "
            "VALUES (?, ?, ?, ?)",
            (file_hash, filename, metadata_text, body),
        )
        count += 1
        if progress_callback:
            progress_callback(count, total)

    fts_conn.commit()
    return count
