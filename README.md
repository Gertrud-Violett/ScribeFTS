# NHI Librarian

A lightweight CLI tool to catalog and organize documents using customizable metadata. Scans directory trees for files (default: PDFs), tracks them by content hash, and stores everything in a local SQLite database.

## Features

- **Configurable file scanning** — scan any directories for any file types, set via `meta_config.json`
- **Customizable metadata** — define your own fields (text, choice lists, keyword lists) without touching code
- **Move detection** — files are tracked by content hash, so renames and moves are handled automatically
- **Missing file tracking** — files that disappear are flagged, never silently deleted
- **Search & filter** — find entries by filename, title, keywords, or any metadata field
- **JSON export** — export the full catalog for use in other tools
- **Zero external dependencies** — Python standard library only
- **Importable API** — use `NHILibrarian` directly from Jupyter notebooks or web frameworks

## Requirements

- Python 3.14 or above

## Quick Start

```bash
# Clone the repository
git clone https://github.com/Gertrud-Violett/NHI_Librarian.git
cd NHI_Librarian

# Run the CLI
python bin/NHI_Librarian.py
```

On first run, NHI Librarian will create `data/library.db` and `data/meta_config.json` with sensible defaults, then scan the configured directories.

## CLI Commands

| Command | Description |
|---|---|
| `refresh` | Scan configured directories for new, moved, or missing files |
| `list [--sort FIELD] [--category CAT]` | Display all cataloged files in a table |
| `search <query>` | Search entries by filename, title, or keywords |
| `show <hash_prefix>` | Show full details for an entry (partial hash OK) |
| `update <hash_prefix> <field> <value>` | Update a single metadata field |
| `edit <hash_prefix>` | Interactively edit all metadata fields |
| `delete <hash_prefix>` | Remove an entry from the database (file is not deleted) |
| `export [path]` | Export the database to JSON |
| `stats` | Show summary statistics |
| `help` | Show available commands |
| `quit` | Exit |

## Configuration

Edit `data/meta_config.json` to customize:

- **`scan_directories`** — list of directories to scan (absolute or relative paths)
- **`file_extensions`** — file types to include (e.g. `[".pdf"]`, or `[".*"]` for all)
- **`fields`** — metadata fields with types (`text`, `choice`, `list`), defaults, and validation

## Project Structure

```
NHI_Librarian/
├── bin/NHI_Librarian.py       # CLI entry point
├── data/                      # Database & config (auto-generated)
├── lib/                       # Core library modules
│   ├── scanner.py             # File system scanning & move detection
│   ├── database.py            # SQLite operations
│   ├── metadata.py            # Metadata schema loading & validation
│   └── api.py                 # Public API facade
├── tests/                     # Unit tests & sample documents
└── docs/ARCHITECTURE.md       # Detailed architecture document
```

## Documentation

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed design decisions, database schema, module responsibilities, and workflows.

## License

This project is licensed under the BSD 2-Clause License. See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome. Please open an issue to discuss proposed changes before submitting a pull request.
