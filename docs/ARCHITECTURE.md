# NHI Librarian — Architecture Document

## 1. Overview

NHI Librarian is a lightweight document cataloging tool that scans a designated directory tree for files matching configurable extensions (default: `.pdf`), assigns configurable metadata, and stores everything in a local SQLite database. Metadata field definitions are kept in an editable JSON file. The core logic is exposed as a Python API consumed by two interfaces: an interactive **CLI** (built-in `cmd` module) and a **browser-based GUI** (Flask on localhost). The user selects the interface mode at launch.

---

## 2. Directory Layout

```
NHI_Librarian/
├── __main__.py                # Launcher: python __main__.py [--cli | --gui]
├── bin/
│   └── NHI_Librarian.py      # CLI entry point
├── data/
│   ├── library.db             # SQLite database (auto-generated)
│   └── meta_config.json       # Metadata field definitions (user-editable)
├── docs/
│   └── ARCHITECTURE.md        # This file
├── gui/
│   ├── __init__.py
│   ├── app.py                 # Flask application & route definitions
│   ├── templates/
│   │   ├── base.html          # Shared layout (nav bar, CSS, flash messages)
│   │   ├── library.html       # Main table view (list, search, sort, filter)
│   │   ├── detail.html        # Single-entry view & metadata edit form
│   │   ├── stats.html         # Summary statistics page
│   │   └── config.html        # Metadata schema editor (meta_config.json)
│   └── static/
│       └── style.css          # Custom styles
├── lib/
│   ├── __init__.py
│   ├── scanner.py             # File system scanning & move detection
│   ├── database.py            # SQLite database operations
│   ├── metadata.py            # Metadata schema loading & validation
│   └── api.py                 # Public API (importable by all interfaces)
└── tests/
    ├── __init__.py
    ├── test_scanner.py
    ├── test_database.py
    ├── test_metadata.py
    ├── test_api.py
    ├── test_gui.py            # Flask route tests
    └── sample_docs_directory/ # Test fixture files (PDFs, etc.)
```

---

## 3. Core Concepts

### 3.1 File Identity

Each file is identified by a **content hash** (SHA-256 of the first 64 KB + file size). This allows NHI Librarian to detect when a file has been **moved** to a different sub-directory without treating it as a new file.

**Hash algorithm (pseudocode):**
```python
digest = hashlib.sha256(file.read(65536))   # first 64 KB
digest.update(str(file_size).encode())       # append file size as string
file_hash = digest.hexdigest()[:20]               # 20-char hex string = first 64 KB + file size
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
        "Rotordynamics", "Bearings", "Compressor", "Turbine",
        "Manufacturing", "Fluid Dynamics", "Materials", "NVH", "Other"
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

The two-table design keeps the fixed file-tracking columns separate from the user-configurable metadata, so adding or removing metadata fields never requires a schema migration.

**Why SQLite?** Single portable file, built into Python (`sqlite3`), crash-safe (ACID), fast incremental updates, readable by any SQLite-compatible tool (DB Browser, DBeaver, Jupyter, etc.). Format guaranteed stable until 2050+.

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
| `open_db(db_path) -> Connection` | Open (or create) the SQLite database. Creates tables if they don't exist. |
| `add_entry(conn, file_info, metadata)` | Insert a new file entry + metadata rows. |
| `update_path(conn, file_hash, new_rel_path)` | Update the stored path when a file has moved. |
| `update_metadata(conn, file_hash, field, value)` | Insert or update a single metadata field. |
| `delete_entry(conn, file_hash)` | Remove an entry and its metadata from the database. |
| `find_entries(conn, query) -> list[dict]` | Search entries by filename, title, or any metadata value. |
| `list_entries(conn, sort_by, filters) -> list[dict]` | List/filter/sort all entries. |
| `export_json(conn, out_path)` | Export the entire database to a JSON file. |

### 4.3 `metadata.py` — Metadata Schema

| Function | Description |
|---|---|
| `load_config(config_path) -> MetaConfig` | Load and validate the metadata field definitions. |
| `create_default_config(config_path)` | Generate the default `meta_config.json` if none exists. |
| `validate_metadata(meta_config, metadata) -> list[str]` | Validate metadata values against the schema. Returns a list of error messages (empty = valid). |
| `build_empty_metadata(meta_config) -> dict` | Create a metadata dict with all default values. |

### 4.4 `api.py` — Public API Facade

A single class `NHILibrarian` that wraps all operations. This is the **only interface** that external code should call (CLI, Jupyter, web apps).

```python
class NHILibrarian:
    def __init__(self, data_dir: str, scan_dirs: list[str] = None)

    # Scanning
    def refresh(self) -> ScanReport
    def delete_missing(self) -> int          # remove all entries flagged missing; returns count

    # Entries
    def get_entry(self, file_hash: str) -> dict
    def resolve_file_path(self, file_hash: str) -> Path | None
    def update_metadata(self, file_hash: str, updates: dict) -> None
    def delete_entry(self, file_hash: str) -> None
    def search(self, query: str) -> list[dict]
    def list_all(self, sort_by: str = "filename", category: str = None) -> list[dict]

    # Export
    def export_json(self, out_path: str) -> None

    # Config
    def get_meta_config(self) -> dict
    def save_meta_config(self, config: dict) -> None  # validate & write meta_config.json

    # Cleanup
    def close(self) -> None
```

---

## 5. CLI Commands (`NHI_Librarian.py`)

The CLI uses Python's built-in `cmd` module for an interactive REPL-style interface.

| Command | Description |
|---|---|
| `refresh` | Scan the root directory for new, moved, or missing files. Report changes. |
| `list [--sort FIELD] [--category CAT]` | Display all cataloged files in a table. |
| `search <query>` | Search entries by filename, title, or keywords. |
| `show <hash_prefix>` | Show full details for an entry (accepts partial hash). |
| `update <hash_prefix> <field> <value>` | Update a single metadata field for an entry. |
| `edit <hash_prefix>` | Interactively edit all metadata fields for an entry. |
| `delete <hash_prefix>` | Remove an entry from the database (does not delete the file). |
| `delete-old` | Permanently remove all entries flagged as MISSING from the database. |
| `export [path]` | Export the entire database to a JSON file. Default: `data/library_export.json`. |
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
3. No meta_config.json exists → generate defaults (scan_directories: ["."])
4. Auto-trigger `refresh` → scan all matching files, add to database with empty metadata
5. Enter interactive CLI loop  (or open browser to http://localhost:5000)
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
   - Hash in database but file gone → flag as MISSING (do not auto-delete)
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
4. Validate → save
```

---

## 7. Design Decisions

| Decision | Rationale |
|---|---|
| **SQLite for library data** | Single file, built into Python, crash-safe (ACID), fast incremental updates. Readable by external tools. |
| **JSON for metadata config** | Small, human-edited file. Easy to read and modify in any text editor. |
| **Separate metadata table** | EAV-style storage means adding/removing metadata fields requires zero schema changes. |
| **Content hash for identity** | Survives file renames and moves. Avoids duplicate entries. |
| **Auto-genre from folder name** | New files get their parent folder name as the default genre. If the folder name is not in the genre choices list, it is added automatically and `meta_config.json` is updated. Files at the scan root keep an empty genre. |
| **No auto-delete on missing** | Files on network drives may be temporarily unavailable. Flagging is safer. Explicit `delete-old` command for intentional cleanup. |
| **JSON export command** | Provides human-readable snapshots and interop with tools that need JSON input. |
| **`cmd` module for CLI** | Built-in, no dependencies, supports tab completion and history. |
| **Flask for GUI** | Lightweight, single dependency, renders in any browser. Localhost-only (not hosted). |
| **CLI / GUI parity** | Both interfaces call the same `NHILibrarian` API. No feature is exclusive to either mode. |

---

## 8. Dependencies

- **Python 3.14+** (standard library: `sqlite3`, `json`, `hashlib`, `pathlib`, `cmd`, `webbrowser`)
- **Flask** (`pip install flask`) — required for GUI mode only; CLI mode has zero external dependencies

---

## 9. GUI Architecture (Flask)

### 9.1 Overview

The GUI runs a local Flask development server (`localhost:5000`) and opens the default browser automatically. It is **not** a hosted web application — it serves only the local user. All operations go through the same `NHILibrarian` API used by the CLI.

### 9.2 Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Main library table — lists all entries with columns for filename, path, genre, status. Supports sorting and search via query params. |
| `/refresh` | POST | Trigger a directory scan. Redirect back to `/` with a flash summary (N new, N moved, N missing). |
| `/entry/<hash_prefix>` | GET | Detail view for a single entry — all file info and metadata fields displayed. |
| `/entry/<hash_prefix>/edit` | GET/POST | Edit form for a single entry's metadata. GET shows pre-filled form; POST validates and saves. |
| `/entry/<hash_prefix>/delete` | POST | Delete a single entry from the database. Redirect to `/`. |
| `/entry/<hash_prefix>/open` | GET | Open the file in the user's OS-default application and redirect back to the current list/detail page. |
| `/delete-old` | POST | Remove all MISSING entries from the database. Redirect to `/` with count. |
| `/search` | GET | Search results page. Query param `q` passed to `NHILibrarian.search()`. |
| `/export` | POST | Trigger JSON export. Flash the output path. |
| `/stats` | GET | Summary statistics page (total, by genre, missing count). |
| `/config` | GET/POST | View and edit `meta_config.json`. GET shows current config in an editable form; POST validates and saves via `NHILibrarian.save_meta_config()`. |

### 9.3 Templates

| Template | Purpose |
|---|---|
| `base.html` | Shared layout: nav bar (Library, Stats, Config, Refresh button), flash message area, CSS link. |
| `library.html` | Main table with sortable column headers, search bar, per-row Edit/Delete links, and a Delete Old button. |
| `detail.html` | Read-only entry view + Edit button. Edit mode renders appropriate input widgets per field type (text input, dropdown for `choice`, tag input for `list`). |
| `stats.html` | Summary counts, genre breakdown. |
| `config.html` | JSON editor for `meta_config.json` — displays current fields, allows adding/removing/reordering fields, and editing `scan_directories` and `file_extensions`. |

In the default list view (`library.html`), each **Path** cell is clickable and calls `/entry/<hash_prefix>/open`, which opens the file with the system default app for its file type.

### 9.4 Design Principles

- **No JavaScript frameworks** — plain HTML forms with minimal vanilla JS where needed (e.g., confirm dialogs).
- **Flask flash messages** for operation feedback (success/error).
- **UTF-8 throughout** — browser natively handles Japanese filenames.
- **No authentication** — localhost-only, single-user tool.

---
