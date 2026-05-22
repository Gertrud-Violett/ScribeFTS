# ScribeFTS — Architecture Document (v1.1)

## 1. Overview

ScribeFTS is a lightweight document cataloging tool that scans a designated directory tree for files matching configurable extensions (default: `.pdf`), assigns configurable metadata, and stores everything in a local SQLite database. Metadata field definitions are kept in an editable JSON file. The core logic is exposed as a Python API consumed by two interfaces: an interactive **CLI** (built-in `cmd` module) and a **browser-based GUI** (Flask on localhost). The user selects the interface mode at launch.

A second, separate SQLite database provides **full-text search** (SQLite FTS5) over both document metadata and extracted document text (PDF body content). The two databases are kept strictly separate: `library.db` is the authoritative catalog; `fts.db` is a derived, fully re-buildable search index.

---

## 2. Directory Layout

```
ScribeFTS/
├── __main__.py                # Launcher: python __main__.py [--cli | --gui]
├── bin/
│   └── ScribeFTS.py           # CLI entry point
├── data/
│   ├── library.db             # SQLite metadata catalog (auto-generated)
│   ├── fts.db                 # SQLite FTS5 search index (auto-generated, re-buildable)
│   ├── meta_config.json       # Metadata field definitions (user-editable)
│   └── ai_config.json         # AI provider settings (auto-generated, user-editable)
├── docs/
│   └── ARCHITECTURE.md        # This file
├── gui/
│   ├── __init__.py
│   ├── app.py                 # Flask application & route definitions
│   ├── templates/
│   │   ├── base.html          # Shared layout (nav bar, modals, flash messages)
│   │   ├── library.html       # Main table view (list, search, sort, filter)
│   │   ├── detail.html        # Single-entry view, metadata edit, draft review
│   │   ├── stats.html         # Summary statistics page
│   │   ├── config.html        # Metadata schema editor (meta_config.json)
│   │   ├── ai_config.html     # API provider settings page
│   │   ├── discover.html      # arXiv Discovery Scout (search + download)
│   │   └── tutorial.html      # Static setup & usage guide
│   └── static/
│       └── style.css          # Custom styles
├── lib/
│   ├── __init__.py
│   ├── scanner.py             # File system scanning & move detection
│   ├── database.py            # SQLite database operations (incl. draft staging)
│   ├── metadata.py            # Metadata schema loading & validation
│   ├── fts.py                 # FTS5 database operations & PDF text extraction
│   ├── extractor.py           # 3-layer metadata extraction pipeline
│   ├── ai_client.py           # AI API HTTP client (Gemini, OpenAI-compatible)
│   ├── arxiv_client.py        # arXiv Atom XML search client (stdlib only)
│   ├── downloader.py          # URL-based PDF downloader (stdlib only)
│   └── api.py                 # Public API (importable by all interfaces)
└── tests/
    ├── __init__.py
    ├── test_scanner.py
    ├── test_database.py
    ├── test_metadata.py
    ├── test_api.py
    ├── test_extractor.py      # Extractor layer tests
    ├── test_fts.py            # FTS module tests
    ├── test_gui.py            # Flask route tests
    └── sample_docs_directory/ # Test fixture files (PDFs, etc.)
```

---

## 3. Core Concepts

### 3.1 File Identity

Each file is identified by a **content hash** (SHA-256 of the first 64 KB + file size). This allows ScribeFTS to detect when a file has been **moved** to a different sub-directory without treating it as a new file.

**Hash algorithm (pseudocode):**
```python
digest = hashlib.sha256(file.read(65536))   # first 64 KB
digest.update(str(file_size).encode())       # append file size as string
file_hash = digest.hexdigest()[:20]          # 20-char hex string
```

This avoids hashing large files while still differentiating files that share identical headers but differ in length.

### 3.2 Metadata Schema (`meta_config.json`)

Metadata fields are **not hard-coded**. They are defined in a separate JSON configuration file that users can edit to add, remove, or rename fields. A default configuration is generated on first run:

```json
{
  "scan_directories": ["."],
  "file_extensions": [".pdf"],
  "fields": [
    { "name": "title",       "type": "text",   "required": true,  "default": "" },
    { "name": "authors",     "type": "text",   "required": false, "default": "" },
    { "name": "genre",       "type": "choice", "required": false, "default": "", "choices": [
        "Rotordynamics", "Bearings", "Compressor", "Turbine", "Pumps", "Seals", "Gears", "Electrical", "Materials", "General"
    ]},
    { "name": "year",        "type": "text",   "required": false, "default": "" },
    { "name": "keywords",    "type": "list",   "required": false, "default": [] },
    { "name": "notes",       "type": "text",   "required": false, "default": "" }
  ]
}
```

**`scan_directories`**: List of directory paths to scan. Paths can be absolute or relative to the project root. Default: `["."]` (the project root). Multiple directories are scanned in order and merged.

**`file_extensions`**: List of file extensions to scan for (including the dot). Default: `[".pdf"]`. Set to `[".*"]` to match all files.

**Supported field types:** `text`, `choice` (constrained to a list), `list` (array of strings).

### 3.3 Library Database (`library.db`)

A single SQLite file with two tables:

**`files` table** — one row per document (fixed columns):

| Column | Type | Description |
|---|---|---|
| `file_hash` | TEXT PRIMARY KEY | Truncated SHA-256 content hash (20 hex chars) |
| `filename` | TEXT | Original filename |
| `rel_path` | TEXT | Path relative to the root directory |
| `file_size` | INTEGER | Size in bytes |
| `date_added` | TEXT | ISO-8601 timestamp |
| `date_modified` | TEXT | ISO-8601 timestamp |
| `missing` | INTEGER | 0 = present, 1 = not found on last scan |

**`metadata` table** — one row per (file, field) pair:

| Column | Type | Description |
|---|---|---|
| `file_hash` | TEXT | FK → files.file_hash |
| `field_name` | TEXT | Field name from meta_config.json |
| `field_value` | TEXT | Value (lists stored as JSON arrays) |
| | | PRIMARY KEY (file_hash, field_name) |

**`metadata_draft` table** — one row per (file, field) pair, for staged suggestions:

| Column | Type | Description |
|---|---|---|
| `file_hash` | TEXT | FK → files.file_hash (ON DELETE CASCADE) |
| `field_name` | TEXT | Field name being suggested |
| `field_value` | TEXT | Suggested value |
| `source` | TEXT | Extraction source: `layer1`, `layer2`, `layer3`, `layer3_ai` |
| `confidence` | REAL | Confidence score 0.0–1.0 |
| `created_at` | TEXT | ISO-8601 timestamp |
| | | PRIMARY KEY (file_hash, field_name) |

Draft rows are temporary: they are either committed to the `metadata` table (making the suggestion permanent) or discarded. Auto-commit occurs when `confidence >= auto_commit_threshold` (configurable in `ai_config.json`).

The three-table design keeps extracted suggestions isolated from confirmed metadata, preserving the original catalog's integrity until the user (or the auto-commit logic) approves the suggestion.

**WAL mode:** Both `library.db` and `fts.db` are opened with `PRAGMA journal_mode=WAL`. WAL (Write-Ahead Logging) mode improves concurrency by allowing reads while a write is in progress and reduces the chance of `SQLITE_BUSY` errors when the GUI and a background scan access the database simultaneously. WAL mode persists on-disk after the first `PRAGMA` call; setting it on every `open_db()` / `open_fts_db()` call is safe and idempotent.

**Why SQLite?** Single portable file, built into Python (`sqlite3`), crash-safe (ACID), fast incremental updates, readable by any SQLite-compatible tool (DB Browser, DBeaver, Jupyter, etc.). Format guaranteed stable until 2050+.

### 3.4 AI Configuration (`ai_config.json`)

Stored in `data/ai_config.json`. Created with defaults on first access if absent. Users edit it via the GUI's AI Config page or directly.

```json
{
  "enabled": false,
  "provider": "gemini",
  "api_key": "",
  "model": "gemini-3.1-pro",
  "auto_commit_threshold": 0.8,
  "openai_endpoint": "https://api.openai.com/v1/chat/completions"
}
```

| Key | Description |
|---|---|
| `enabled` | Whether AI-assisted extraction (Layer 3b) is active |
| `provider` | `"gemini"` or `"openai"` (OpenAI-compatible) |
| `api_key` | API key for the selected provider |
| `model` | Model name (e.g. `gemini-1.5-flash`, `gpt-4o-mini`) |
| `auto_commit_threshold` | 0.0–1.0; fields extracted with confidence at or above this value are committed automatically |
| `openai_endpoint` | Full URL for OpenAI-compatible API; only used when `provider = "openai"` |

### 3.5 FTS Database (`fts.db`)

A **second, separate** SQLite file holding a single FTS5 virtual table. It is fully derived from `library.db` plus document content; dropping and rebuilding it is always safe and never constitutes data loss.

**`documents_fts` virtual table** (FTS5):

| Column | Indexed? | Content |
|---|---|---|
| `file_hash` | No (UNINDEXED) | Links to `library.db → files.file_hash` |
| `filename` | Yes | Original filename |
| `metadata_text` | Yes | Concatenated title + authors + keywords + notes + year + genre |
| `body` | Yes | Extracted plain text from the document file |

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    file_hash UNINDEXED,
    filename,
    metadata_text,
    body,
    tokenize = 'unicode61'
);
```

The `unicode61` tokenizer is used for correct Unicode segmentation, including Japanese characters.

**Content source for `body`:** Text is extracted from PDFs using PyMuPDF (`fitz`). For non-PDF files the body is left empty. Extraction failures are logged and silently skipped — they never block `refresh()`.

---

## 4. Module Responsibilities

### 4.1 `scanner.py` — File System Scanner

| Function | Description |
|---|---|
| `scan_directory(root_dir, extensions) -> list[FileInfo]` | Recursively find all files matching the configured extensions under `root_dir`. Returns path, size, and content hash for each. |
| `detect_changes(current_scan, database) -> ScanReport` | Compare scan results against the database. Returns lists of **new**, **moved**, and **missing** (deleted/removed) files. |

### 4.2 `database.py` — SQLite Database Manager

| Function | Description |
|---|---|
| `open_db(db_path) -> Connection` | Open (or create) the SQLite database. Creates all three tables if they don't exist. |
| `add_entry(conn, file_info, metadata)` | Insert a new file entry + metadata rows. |
| `update_path(conn, file_hash, new_rel_path)` | Update the stored path when a file has moved. |
| `update_metadata(conn, file_hash, field, value)` | Insert or update a single metadata field. |
| `delete_entry(conn, file_hash)` | Remove an entry and its metadata from the database. |
| `find_entries(conn, query) -> list[dict]` | Search entries by filename or any metadata value (LIKE-based). |
| `list_entries(conn, sort_by, filters) -> list[dict]` | List/filter/sort all entries. |
| `export_json(conn, out_path)` | Export the entire database to a JSON file. |
| `upsert_draft(conn, file_hash, field_name, value, source, confidence)` | Insert or replace one draft suggestion row. |
| `get_draft(conn, file_hash) -> dict` | Return all draft fields for one file as `{field: {value, source, confidence}}`. |
| `get_all_drafts(conn) -> dict` | Return all pending drafts keyed by `file_hash`. |
| `commit_draft(conn, file_hash)` | Copy all draft rows for a file into `metadata`, then delete from draft. |
| `delete_draft(conn, file_hash)` | Discard all pending drafts for a file without committing. |

### 4.3 `metadata.py` — Metadata Schema

| Function | Description |
|---|---|
| `load_config(config_path) -> MetaConfig` | Load and validate the metadata field definitions. |
| `create_default_config(config_path)` | Generate the default `meta_config.json` if none exists. |
| `validate_metadata(meta_config, metadata) -> list[str]` | Validate metadata values against the schema. Returns a list of error messages (empty = valid). |
| `build_empty_metadata(meta_config) -> dict` | Create a metadata dict with all default values. |

### 4.4 `fts.py` — FTS5 Search Index

| Function | Description |
|---|---|
| `open_fts_db(fts_db_path) -> Connection` | Open (or create) the FTS database; creates the `documents_fts` virtual table if absent. |
| `extract_text(file_path) -> str` | Extract plain text from a document file (PDF via PyMuPDF). Returns `""` on failure. |
| `index_document(fts_conn, file_hash, filename, metadata_text, body)` | Add or replace one document in the FTS index (DELETE + INSERT pattern). |
| `remove_document(fts_conn, file_hash)` | Delete one document from the FTS index. |
| `fts_search(fts_conn, query) -> list[str]` | Run an FTS5 query; return a list of matching `file_hash` values. |
| `rebuild_index(fts_conn, lib_conn, scan_dirs)` | Truncate and rebuild the entire FTS index from `library.db`. |

### 4.5 `api.py` — Public API Facade

A single class `ScribeFTS` that wraps all operations. This is the **only interface** that external code should call (CLI, Jupyter, web apps).

```python
class ScribeFTS:
    def __init__(self, data_dir: str, scan_dirs: list[str] = None)

    # Scanning
    def refresh(self) -> ScanReport
    def delete_missing(self) -> int

    # Entries
    def get_entry(self, file_hash: str) -> dict
    def resolve_file_path(self, file_hash: str) -> Path | None
    def update_metadata(self, file_hash: str, updates: dict) -> None
    def delete_entry(self, file_hash: str) -> None
    def search(self, query: str) -> list[dict]
    def fts_search(self, query: str) -> list[dict]
    def list_all(self, sort_by: str = "filename", category: str = None) -> list[dict]

    # Export
    def export_json(self, out_path: str) -> None

    # Config
    def get_meta_config(self) -> dict
    def save_meta_config(self, config: dict) -> None

    # FTS
    def reindex_fts(self) -> int

    # Metadata extraction & draft staging
    def suggest_metadata(self, file_hash: str) -> dict   # run pipeline; auto-commit high-confidence fields
    def get_draft(self, file_hash: str) -> dict          # return pending draft (empty dict if none)
    def commit_draft(self, file_hash: str) -> None       # commit all draft fields to metadata
    def discard_draft(self, file_hash: str) -> None      # delete draft without committing
    def suggest_all(self) -> dict[str, int]              # run pipeline for all entries with empty fields
    def commit_all_drafts(self) -> int                   # commit all pending drafts; returns count
    def get_pending_draft_hashes(self) -> set[str]       # return set of file_hashes with pending drafts

    # AI config
    def get_ai_config(self) -> dict
    def save_ai_config(self, config: dict) -> None

    # Cleanup
    def close(self) -> None
```

### 4.6 `extractor.py` — 3-Layer Metadata Extraction Pipeline

Implements a waterfall extraction strategy. Each layer only fills fields that earlier layers left empty.

**Data structures:**
```python
@dataclass
class FieldDraft:
    value: str
    source: str       # 'layer1' | 'layer2' | 'layer3' | 'layer3_ai'
    confidence: float # 0.0–1.0

@dataclass
class ExtractionResult:
    title: FieldDraft | None = None
    authors: FieldDraft | None = None
    year: FieldDraft | None = None
    keywords: FieldDraft | None = None
```

**Layers and confidence scores:**

| Layer | Source | Title | Authors | Year | Keywords |
|---|---|---|---|---|---|
| 1 — PDF internal metadata (PyMuPDF) | `layer1` | 0.95 | 0.90 | 0.85 | — |
| 2 — Filename/path heuristics (regex) | `layer2` | — | 0.50 | 0.70 | 0.40 |
| 3a — First-page structural heuristics | `layer3` | 0.40 | 0.45 | 0.50 | — |
| 3b — AI extraction (when enabled) | `layer3_ai` | 0.75 | 0.75 | 0.75 | — |

**Public entry point:**
```python
def extract_metadata(file_path, current_metadata=None, ai_config=None) -> ExtractionResult
```

Fields already populated in `current_metadata` are skipped by all layers (a sentinel value prevents layer 2/3 from overwriting them).

### 4.7 `ai_client.py` — AI API HTTP Client

Uses `urllib.request` only — no additional dependencies. Supports Google Gemini and any OpenAI-compatible API endpoint.

| Function | Description |
|---|---|
| `load_ai_config(path) -> dict` | Load `ai_config.json`; create with defaults if absent. |
| `save_ai_config(path, config)` | Write `ai_config.json`. |
| `call_ai(prompt, ai_config) -> str \| None` | Send prompt to configured provider; return raw text response or `None` on any error. |

All network errors, auth failures, and JSON parse errors are caught; callers receive `None` and fall back to heuristic extraction.

### 4.8 `arxiv_client.py` — arXiv Search Client

Stdlib-only (`urllib.request` + `xml.etree.ElementTree`). No additional dependencies.

| Function | Description |
|---|---|
| `search(query, max_results=10) -> list[dict]` | Query the arXiv Atom XML API. Returns a list of paper dicts with keys `title`, `authors`, `year`, `abstract`, `pdf_url`, `arxiv_id`. Raises `RuntimeError` on network or parse failure. |

Uses a shared `ssl.SSLContext` with certificate verification disabled (`CERT_NONE`, `check_hostname=False`). This avoids `CERTIFICATE_VERIFY_FAILED` errors on Windows Python installations that lack a root CA bundle for `arxiv.org`. Appropriate for a local-only tool contacting a well-known public API.

### 4.9 `downloader.py` — URL PDF Downloader

Stdlib-only (`urllib.request` + `shutil`). No additional dependencies.

| Function | Description |
|---|---|
| `download_pdf(url, dest_dir, filename=None) -> Path` | Download a PDF from `url` into `dest_dir`. Validates the first 5 bytes for the `%PDF-` magic number. Derives a filename from `Content-Disposition` or the URL path. Raises `ValueError` if the URL does not return a PDF; raises `RuntimeError` on network failure. |
| `_unique_path(dest) -> Path` | If `dest` exists, appends `_1`, `_2`, … before the extension until a free name is found. |
| `_derive_filename(url, resp) -> str` | Extracts a filename from the `Content-Disposition` header, falling back to the last URL path segment. |

Shares the same SSL context pattern as `arxiv_client.py` to handle PDF downloads from `arxiv.org` and similar hosts.

---

## 5. CLI Commands (`bin/ScribeFTS.py`)

The CLI uses Python's built-in `cmd` module for an interactive REPL-style interface.

| Command | Description |
|---|---|
| `refresh` | Scan the root directory for new, moved, or missing files. Report changes. Also indexes new files in FTS. |
| `list [--sort FIELD] [--category CAT]` | Display all cataloged files in a table. |
| `search <query>` | Search entries by filename or any metadata value (LIKE-based). |
| `fts_search <query>` | Full-text search using the FTS5 index. Supports phrases and boolean operators. |
| `reindex` | Rebuild the FTS index from scratch (re-extracts text from all cataloged files). |
| `show <hash_prefix>` | Show full details for an entry (accepts partial hash). |
| `update <hash_prefix> <field> <value>` | Update a single metadata field for an entry. |
| `edit <hash_prefix>` | Interactively edit all metadata fields for an entry. |
| `delete <hash_prefix>` | Remove an entry from the database (does not delete the file). |
| `delete-old` | Permanently remove all entries flagged as MISSING from the database. |
| `export [path]` | Export the entire database to a JSON file. Default: `data/library_export.json`. |
| `suggest <hash_prefix>` | Run the extraction pipeline for one entry; display draft suggestions with source and confidence. Auto-committed fields are marked. |
| `suggest_all` | Run extraction for all entries where `authors`, `year`, or `keywords` is empty. |
| `commit <hash_prefix>` | Commit the pending draft for one entry to the metadata table. |
| `commit_all` | Commit all pending drafts across all entries. |
| `stats` | Show summary statistics (total files, by genre, missing files, etc.). |
| `help` | Show available commands. |
| `quit` | Exit the program. |

**Hash prefix**: Users don't need to type the full 20-character hash. The first 7+ characters suffice (like Git).

---

## 6. Key Workflows

### 6.1 First Run
```
1. User runs: python __main__.py --cli   (or --gui for browser mode)
2. No library.db exists → create SQLite database with tables
3. No fts.db exists → create FTS5 virtual table
4. No meta_config.json exists → generate defaults (scan_directories: ["."])
5. Auto-trigger `refresh` → scan all matching files, add to database with empty metadata,
   extract text and index in fts.db
6. Enter interactive CLI loop  (or open browser to http://localhost:5000)
```

### 6.2 Refresh (Incremental Scan)
```
1. Scan configured directories → collect all matching file paths + hashes
2. Compare against database:
   - Hash exists, path unchanged → skip (no action)
   - Hash exists, path changed  → auto-update rel_path (file was moved)
   - Hash not in database       → add as new entry:
       a. Set genre to the file's parent folder name (e.g. ./Bearings/file.pdf → "Bearings")
       b. If the folder name is not in meta_config.json genre choices, add it and save config
       c. Files in the scan root (no parent folder) get the default empty genre
       d. Extract document text and index in fts.db
   - Hash in database but file gone → flag as MISSING (do not auto-delete);
       remove from fts.db
3. Print summary: N new, N moved, N missing
```

### 6.3 Metadata Update
```
1. User runs: edit abc1234
2. Resolve partial hash → full entry
3. For each field defined in meta_config.json:
   - Display current value
   - Prompt for new value (Enter to keep current)
   - For "choice" fields: show numbered options
   - For "list" fields: comma-separated input
4. Validate → save to library.db
5. Rebuild FTS entry for this document (DELETE + INSERT in fts.db)
```

### 6.4 FTS Indexing on Refresh
```
1. refresh() scans directories (existing logic, unchanged)
2. For each NEW file added to library.db:
   a. Resolve absolute path via scan_dirs
   b. extract_text(abs_path) → body string (empty string if extraction fails)
   c. Build metadata_text = concatenate all text metadata field values
   d. index_document(fts_conn, file_hash, filename, metadata_text, body)
3. For each MISSING file hash: remove_document(fts_conn, file_hash)
4. Commit fts.db
```

### 6.5 Full Reindex
```
1. User runs: reindex (CLI) or POST /reindex (GUI)
2. rebuild_index() issues DELETE FROM documents_fts (truncate)
3. Iterates all non-missing entries in library.db
4. For each: extract_text + index_document
5. Commits fts.db; returns count of documents indexed
```

### 6.6 Metadata Extraction (Suggest)
```
1. User runs: suggest <hash> (CLI) or clicks "Suggest Metadata" in detail view (GUI)
2. Resolve hash prefix → entry; load current metadata
3. Run extract_metadata(abs_path, current_metadata, ai_config):
   a. Layer 1: fitz.open(path).metadata → title/authors/year at high confidence
   b. Layer 2: filename/folder regex heuristics → fills remaining empty fields
   c. Layer 3a (AI disabled): first-page text structural heuristics
      Layer 3b (AI enabled): POST prompt to Gemini or OpenAI → parse JSON response
4. For each extracted field:
   - Store in metadata_draft table (upsert_draft)
   - If confidence >= auto_commit_threshold: also write to metadata + delete draft
5. Return results dict; flash summary to user
```

### 6.7 Draft Commit / Discard
```
Commit:
1. User runs: commit <hash> (CLI) or clicks "Commit Draft" in detail view (GUI)
2. Copy all metadata_draft rows for that file_hash into the metadata table
3. Delete all metadata_draft rows for that file_hash
4. Rebuild FTS entry (_sync_fts_entry) so search reflects new values

Discard:
1. User runs: (no CLI command needed) or clicks "Discard Draft" in detail view (GUI)
2. DELETE FROM metadata_draft WHERE file_hash = ?
3. metadata table is unchanged
```

---

## 7. Design Decisions

| Decision | Rationale |
|---|---|
| **SQLite for library data** | Single file, built into Python, crash-safe (ACID), fast incremental updates. Readable by external tools. |
| **Separate `fts.db`** | Preserves `library.db` integrity. FTS index is derived and re-buildable; losing it is not data loss. |
| **JSON for metadata config** | Small, human-edited file. Easy to read and modify in any text editor. |
| **Separate metadata table** | EAV-style storage means adding/removing metadata fields requires zero schema changes. |
| **Content hash for identity** | Survives file renames and moves. Avoids duplicate entries. |
| **Auto-genre from folder name** | New files get their parent folder name as the default genre. If the folder name is not in the genre choices list, it is added automatically and `meta_config.json` is updated. Files at the scan root keep an empty genre. |
| **No auto-delete on missing** | Files on network drives may be temporarily unavailable. Flagging is safer. Explicit `delete-old` command for intentional cleanup. |
| **JSON export command** | Provides human-readable snapshots and interop with tools that need JSON input. |
| **`cmd` module for CLI** | Built-in, no dependencies, supports tab completion and history. |
| **Flask for GUI** | Lightweight, single dependency, renders in any browser. Localhost-only (not hosted). |
| **CLI / GUI parity** | Both interfaces call the same `ScribeFTS` API. No feature is exclusive to either mode. |
| **FTS5 `unicode61` tokenizer** | Correct Unicode segmentation; handles Japanese characters without issue. |
| **`fts_search()` alongside `search()`** | LIKE search remains for substring/metadata use. FTS adds document-body search without replacing existing behavior. |
| **DELETE + INSERT for FTS updates** | FTS5 `UPDATE` does not work correctly on virtual tables; delete-then-insert is the canonical pattern. |
| **PyMuPDF for text extraction** | Fast, handles Unicode/Japanese correctly, single wheel dependency. `body` left empty if import fails, so FTS degrades gracefully without the library. |
| **`metadata_draft` table (additive)** | Draft staging uses the same SQLite connection as the main catalog. ON DELETE CASCADE keeps draft rows in sync with entry deletions. Adding the table to `open_db()` means no migration step is needed. |
| **Waterfall extraction with sentinel** | Each layer fills only fields that previous layers left empty. Fields already in the database are marked with a sentinel `FieldDraft(source="skip")` before layer 2 runs, preventing any layer from overwriting confirmed metadata. |
| **Auto-commit threshold** | Allows hands-off operation for high-confidence extractions (Layer 1 PDF metadata) while staging uncertain values (Layer 2/3 heuristics) for human review. Default 0.8 keeps all non-AI suggestions as drafts. |
| **`urllib.request` for AI calls** | Zero new dependencies. All errors are caught; callers receive `None` and fall back to Layer 3a heuristics transparently. |
| **Separate `ai_config.json`** | AI credentials are kept outside `meta_config.json` to avoid accidentally exporting API keys with the document catalog. |
| **WAL mode for both databases** | `PRAGMA journal_mode=WAL` is set on every `sqlite3.connect()` call. WAL persists on-disk after first set, so the call is idempotent. Prevents `SQLITE_BUSY` when GUI requests overlap with a background scan. |
| **SSL verification disabled for external requests** | `arxiv_client.py` and `downloader.py` share an `ssl.SSLContext` with `CERT_NONE`. Some Windows Python installations lack the issuer certificate for `arxiv.org`, causing `CERTIFICATE_VERIFY_FAILED`. Acceptable for a local-only tool contacting well-known public APIs; avoids adding `certifi` as a dependency. |
| **arXiv stdlib-only client** | `arxiv_client.py` uses `urllib.request` + `xml.etree.ElementTree` to parse the arXiv Atom XML feed. Zero new dependencies. |
| **In-browser directory picker** | The "Browse…" button opens a modal backed by the `/browse` JSON endpoint. Single-click highlights; double-click navigates. Avoids limitations of `<input type="file" webkitdirectory>` and works cross-platform. |
| **Config and AI Config under single "API" nav item** | Both `/config` and `/ai_config` share a tab bar, reducing nav clutter. The "API" nav link lands on `/ai_config`; the "Config" tab navigates to the metadata schema editor. |
| **`data-*` attributes for dynamic JS handlers** | Inline `onclick="fn(tojson_value)"` breaks when values contain double quotes (Jinja2 `tojson` uses JSON `"` delimiters inside HTML `"` attributes). All dynamic handlers use `data-*` attributes with `addEventListener` to avoid this conflict. |

---

## 8. Dependencies

- **Python 3.14+** (standard library: `sqlite3`, `json`, `hashlib`, `pathlib`, `cmd`, `webbrowser`, `urllib.request`, `ssl`, `xml.etree.ElementTree`)
- **Flask** (`pip install flask`) — required for GUI mode only; CLI mode has zero external dependencies
- **PyMuPDF** (`pip install pymupdf`) — required for PDF text extraction in FTS and Layer 1/3 extraction; optional (features degrade gracefully if absent)

---

## 9. GUI Architecture (Flask)

### 9.1 Overview

The GUI runs a local Flask development server (`localhost:5000`) and opens the default browser automatically. It is **not** a hosted web application — it serves only the local user. All operations go through the same `ScribeFTS` API used by the CLI.

### 9.2 Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Main library table — lists all entries with columns for filename, path, genre, status. Supports sorting and search via query params. |
| `/refresh` | POST | Trigger a directory scan (also indexes new files in FTS). Redirect back to `/` with a flash summary. |
| `/entry/<hash_prefix>` | GET | Detail view for a single entry — all file info and metadata fields displayed. |
| `/entry/<hash_prefix>/edit` | GET/POST | Edit form for a single entry's metadata. GET shows pre-filled form; POST validates and saves, then refreshes FTS entry. |
| `/entry/<hash_prefix>/delete` | POST | Delete a single entry from the database and FTS index. Redirect to `/`. |
| `/entry/<hash_prefix>/open` | GET | Open the file in the user's OS-default application and redirect back to the current list/detail page. |
| `/delete-old` | POST | Remove all MISSING entries from the database and FTS index. Redirect to `/` with count. |
| `/search` | GET | Metadata search results page (LIKE-based). Query param `q` passed to `ScribeFTS.search()`. |
| `/fts_search` | GET | Full-text search results page (FTS5). Query param `q` passed to `ScribeFTS.fts_search()`. |
| `/reindex` | POST | Trigger a full FTS reindex. Flash the count. Redirect to `/`. |
| `/export` | POST | Trigger JSON export. Flash the output path. |
| `/stats` | GET | Summary statistics page (total, by genre, missing count). |
| `/config` | GET/POST | View and edit `meta_config.json`. GET shows current config in an editable form; POST validates and saves. Shares a "Config / API" tab bar with `/ai_config`. |
| `/suggest/<hash_prefix>` | POST | Run the extraction pipeline for one entry; store results as drafts; auto-commit high-confidence fields. Redirect to detail page with flash summary. |
| `/commit/<hash_prefix>` | POST | Commit the pending draft for one entry to the metadata table. |
| `/discard/<hash_prefix>` | POST | Discard the pending draft for one entry without committing. |
| `/suggest_all` | POST | Run extraction for all entries with empty `authors`/`year`/`keywords`. Flash result summary. |
| `/commit_all` | POST | Commit all pending drafts across all entries. Flash count. |
| `/ai_config` | GET/POST | View and edit `ai_config.json` (provider, API key, model, threshold, endpoint). Accessible from the "API" nav link; shares a tab bar with `/config`. |
| `/upload` | POST | Receive a file upload or PDF URL. Saves to the user-selected directory. If the destination is within a configured scan directory, calls `lib.refresh()` and returns `{ok, filename, new_count}`; otherwise returns `{ok: false, outside_scan_dir: true, warning}`. A second call with `confirmed=true` saves without calling `refresh()`. |
| `/browse` | GET | Directory browser helper. Query param `path`. Returns `{path, parent, dirs: [{name, path}]}` as JSON for the in-browser directory picker modal. Handles Windows drive-letter roots via `os.listdrives()` (Python 3.12+) with A–Z fallback. |
| `/discover` | GET | arXiv Discovery Scout. If query param `q` is present, calls `arxiv_client.search(q)` and renders results; otherwise renders an empty search form. |
| `/discover/download` | POST | Download a PDF from an arXiv (or any direct PDF) URL. Same two-phase scan-dir warning flow as `/upload`. Uses `lib/downloader.py`. Returns JSON. |
| `/tutorial` | GET | Renders the static tutorial page with `scan_dirs` injected for context. |

### 9.3 Templates

| Template | Purpose |
|---|---|
| `base.html` | Shared layout: nav bar (Library, Stats, API, Workspace, Discover, Tutorial, Upload button, Refresh, Reindex FTS); Upload modal (file picker, URL input, destination directory with Browse button, two-phase scan-dir warning); shared in-browser directory browser modal (`/browse`-backed, single-click highlight / double-click navigate). |
| `library.html` | Main table with sortable column headers, search bar with Metadata/Full-text mode toggle, Title/Author/Year columns, per-row `[draft]` badge when a pending draft exists, Suggest All / Commit All buttons, and column filter inputs. |
| `detail.html` | Read-only entry view + Edit button + Suggest Metadata button. When a draft exists, shows a "Suggested (Draft)" card with field values, source, and confidence, plus Commit Draft and Discard Draft buttons. |
| `stats.html` | Summary counts, genre breakdown. |
| `config.html` | Metadata schema editor for `meta_config.json` — visual editor (table of fields with type/required/default/choices) and raw JSON editor tab; shared "Config / API" tab bar at the top for navigation to `ai_config.html`. |
| `ai_config.html` | Form to configure `ai_config.json`: Enable toggle, provider dropdown (Gemini / OpenAI-compatible), API key, model, auto-commit threshold, and OpenAI endpoint (shown only when OpenAI provider selected). Shares the "Config / API" tab bar; accessible from the "API" nav link. |
| `discover.html` | arXiv Discovery Scout: search form (GET), results table (title/authors/year/truncated abstract/Download button), download modal with destination directory picker and two-phase scan-dir warning. |
| `tutorial.html` | Static three-section guide: (1) Basic Usage — adding files via scan or Upload, using Discovery Scout, searching, editing metadata; (2) AI Metadata Extraction — enabling Gemini or OpenAI-compatible providers via the API tab, draft/commit flow; (3) Google Drive Sync & NotebookLM — using Google Drive for Desktop as a zero-OAuth sync bridge, step-by-step NotebookLM integration. |

In the default list view (`library.html`), each **Path** cell is clickable and calls `/entry/<hash_prefix>/open`, which opens the file with the system default app for its file type.

### 9.4 Design Principles

- **No JavaScript frameworks** — plain HTML forms with minimal vanilla JS where needed.
- **Flask flash messages** for operation feedback (success/error).
- **UTF-8 throughout** — browser natively handles Japanese filenames.
- **No authentication** — localhost-only, single-user tool.
- **`data-*` attributes for JS event handlers** — inline `onclick="fn({{ value | tojson }})"` is unsafe when values contain double quotes (Jinja2 `tojson` produces JSON strings wrapped in `"`). All dynamic click handlers use `data-*` HTML attributes with `addEventListener`, avoiding HTML-attribute/JSON-string quote conflicts.
- **Context processor for scan_dirs** — `scan_dirs` and `first_scan_dir` are injected into every template via `@app.context_processor`, so no route needs to pass them explicitly. The Upload button and destination-directory pre-fill both rely on this.
- **Two-phase upload/download flow** — on first submission, the server checks whether the destination is within a configured scan directory. If not, it returns `outside_scan_dir: true` and a warning message; the client shows the warning and offers "Proceed Anyway". On the second submission with `confirmed=true`, the file is saved but `refresh()` is not called (since the file is outside all scan roots).
