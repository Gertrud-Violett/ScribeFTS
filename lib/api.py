"""Public API facade for NHI Librarian."""

import json
from pathlib import Path, PurePath

from lib import database, metadata, scanner
from lib.scanner import ScanReport


class NHILibrarian:
    """Single entry point wrapping all NHI Librarian operations.

    External code (CLI, Jupyter, web apps) should use this class exclusively.
    """

    def __init__(self, data_dir: str, scan_dirs: list[str] | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.db_path = self.data_dir / "library.db"
        self.config_path = self.data_dir / "meta_config.json"

        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Create default config if it doesn't exist
        if not self.config_path.exists():
            metadata.create_default_config(str(self.config_path))

        self._config = metadata.load_config(str(self.config_path))
        self._conn = database.open_db(str(self.db_path))

        # scan_dirs override takes precedence over config
        if scan_dirs is not None:
            self._scan_dirs = [str(Path(d).resolve()) for d in scan_dirs]
        else:
            self._scan_dirs = [
                str(Path(d).resolve())
                for d in self._config.get("scan_directories", ["."])
            ]

    # -- Scanning --

    def refresh(self) -> ScanReport:
        """Scan configured directories and reconcile with the database."""
        extensions = self._config.get("file_extensions", [".pdf"])

        # Scan all configured directories and merge results
        all_files = []
        for scan_dir in self._scan_dirs:
            all_files.extend(scanner.scan_directory(scan_dir, extensions))

        # Deduplicate by hash (first occurrence wins)
        seen = set()
        unique_files = []
        for fi in all_files:
            if fi.file_hash not in seen:
                seen.add(fi.file_hash)
                unique_files.append(fi)

        db_paths = database.get_all_paths(self._conn)
        report = scanner.detect_changes(unique_files, db_paths)

        # Apply changes
        empty_meta = metadata.build_empty_metadata(self._config)

        # Find the genre field definition (if any) for auto-genre logic
        genre_field = None
        for f in self._config.get("fields", []):
            if f["name"] == "genre":
                genre_field = f
                break

        new_genres_added = False
        for fi in report.new:
            file_meta = dict(empty_meta)  # shallow copy per file

            # Auto-set genre from parent folder name when default is empty
            if genre_field is not None:
                parent = PurePath(fi.rel_path).parent.name
                if parent and parent != ".":
                    file_meta["genre"] = parent
                    # If genre is a choice field, ensure the folder name is in choices
                    if genre_field["type"] == "choice":
                        choices = genre_field.setdefault("choices", [])
                        if parent not in choices:
                            choices.append(parent)
                            new_genres_added = True

            database.add_entry(self._conn, fi, file_meta)

        # Persist any new genre choices to meta_config.json
        if new_genres_added:
            with open(str(self.config_path), "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)

        for fi, _old_path in report.moved:
            database.update_path(self._conn, fi.file_hash, fi.rel_path)

        for file_hash in report.missing:
            database.mark_missing(self._conn, file_hash)

        return report

    def delete_missing(self) -> int:
        """Remove all entries flagged as missing. Returns the count deleted."""
        return database.delete_missing_entries(self._conn)

    # -- Entries --

    def get_entry(self, file_hash: str) -> dict | None:
        """Get a single entry by full or partial hash."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            return None
        return database.get_entry(self._conn, full_hash)

    def update_metadata(self, file_hash: str, updates: dict) -> None:
        """Update metadata fields for an entry."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            raise ValueError(f"No unique entry found for hash prefix '{file_hash}'")

        errors = metadata.validate_metadata(self._config, updates)
        if errors:
            raise ValueError(f"Validation errors: {'; '.join(errors)}")

        for field, value in updates.items():
            database.update_metadata(self._conn, full_hash, field, value)

    def delete_entry(self, file_hash: str) -> None:
        """Remove an entry from the database (does not delete the file)."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            raise ValueError(f"No unique entry found for hash prefix '{file_hash}'")
        database.delete_entry(self._conn, full_hash)

    def search(self, query: str) -> list[dict]:
        """Search entries by filename, title, or any metadata value."""
        return database.find_entries(self._conn, query)

    def list_all(self, sort_by: str = "filename", category: str | None = None) -> list[dict]:
        """List all entries, optionally filtered by genre/category."""
        filters = None
        if category:
            filters = {"genre": category}
        return database.list_entries(self._conn, sort_by=sort_by, filters=filters)

    # -- Export --

    def export_json(self, out_path: str) -> None:
        """Export the entire database to a JSON file."""
        database.export_json(self._conn, out_path)

    # -- Config --

    def get_meta_config(self) -> dict:
        """Return the current metadata configuration."""
        return self._config

    def save_meta_config(self, config: dict) -> None:
        """Validate and write meta_config.json. Reloads config on success."""
        # Validate structure by running through load_config's validation logic
        if "fields" not in config:
            raise ValueError("Config missing required key: 'fields'")
        if not isinstance(config["fields"], list):
            raise ValueError("'fields' must be a list")
        for field in config["fields"]:
            if "name" not in field or "type" not in field:
                raise ValueError(f"Field missing 'name' or 'type': {field}")
            if field["type"] not in metadata.VALID_FIELD_TYPES:
                raise ValueError(
                    f"Field '{field['name']}' has invalid type '{field['type']}'. "
                    f"Must be one of: {metadata.VALID_FIELD_TYPES}"
                )
            if field["type"] == "choice" and "choices" not in field:
                raise ValueError(
                    f"Field '{field['name']}' is type 'choice' but has no 'choices' list"
                )

        config.setdefault("scan_directories", ["."])
        config.setdefault("file_extensions", [".pdf"])

        import json
        with open(str(self.config_path), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        self._config = metadata.load_config(str(self.config_path))

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
