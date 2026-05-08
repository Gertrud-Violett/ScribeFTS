"""Public API facade for ScribeFTS."""

import json
from pathlib import Path, PurePath

from lib import ai_client, database, extractor, fts, metadata, scanner
from lib.scanner import ScanReport


class ScribeFTS:
    """Single entry point wrapping all ScribeFTS operations.

    External code (CLI, Jupyter, web apps) should use this class exclusively.
    """

    def __init__(self, data_dir: str, scan_dirs: list[str] | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.db_path = self.data_dir / "library.db"
        self.fts_db_path = self.data_dir / "fts.db"
        self.config_path = self.data_dir / "meta_config.json"
        self.ai_config_path = self.data_dir / "ai_config.json"

        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Create default config if it doesn't exist
        if not self.config_path.exists():
            metadata.create_default_config(str(self.config_path))

        self._config = metadata.load_config(str(self.config_path))
        self._conn = database.open_db(str(self.db_path))
        self._fts_conn = fts.open_fts_db(str(self.fts_db_path))

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

            # Index the new document in FTS
            abs_path = self._resolve_abs_path(fi.rel_path)
            body = fts.extract_text(abs_path) if abs_path else ""
            metadata_text = " ".join(
                str(v) for v in file_meta.values() if v
            )
            fts.index_document(
                self._fts_conn, fi.file_hash, fi.filename, metadata_text, body
            )

        # Persist any new genre choices to meta_config.json
        if new_genres_added:
            with open(str(self.config_path), "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)

        for fi, _old_path in report.moved:
            database.update_path(self._conn, fi.file_hash, fi.rel_path)

        for file_hash in report.missing:
            database.mark_missing(self._conn, file_hash)
            fts.remove_document(self._fts_conn, file_hash)

        return report

    def delete_missing(self) -> int:
        """Remove all entries flagged as missing. Returns the count deleted."""
        # Collect hashes before deleting so we can sync the FTS index
        missing_rows = self._conn.execute(
            "SELECT file_hash FROM files WHERE missing = 1"
        ).fetchall()
        for row in missing_rows:
            fts.remove_document(self._fts_conn, row["file_hash"])
        return database.delete_missing_entries(self._conn)

    # -- Entries --

    def get_entry(self, file_hash: str) -> dict | None:
        """Get a single entry by full or partial hash."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            return None
        return database.get_entry(self._conn, full_hash)

    def update_metadata(self, file_hash: str, updates: dict) -> None:
        """Update metadata fields for an entry, then refresh its FTS entry."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            raise ValueError(f"No unique entry found for hash prefix '{file_hash}'")

        errors = metadata.validate_metadata(self._config, updates)
        if errors:
            raise ValueError(f"Validation errors: {'; '.join(errors)}")

        for field, value in updates.items():
            database.update_metadata(self._conn, full_hash, field, value)

        # Rebuild FTS entry with fresh metadata
        self._sync_fts_entry(full_hash)

    def delete_entry(self, file_hash: str) -> None:
        """Remove an entry from the database (does not delete the file)."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            raise ValueError(f"No unique entry found for hash prefix '{file_hash}'")
        fts.remove_document(self._fts_conn, full_hash)
        database.delete_entry(self._conn, full_hash)

    def search(self, query: str) -> list[dict]:
        """Search entries by filename or any metadata value (LIKE-based)."""
        return database.find_entries(self._conn, query)

    def fts_search(self, query: str) -> list[dict]:
        """Full-text search using the FTS5 index. Returns full entry dicts."""
        hashes = fts.fts_search(self._fts_conn, query)
        results = []
        for file_hash in hashes:
            entry = database.get_entry(self._conn, file_hash)
            if entry is not None:
                results.append(entry)
        return results

    def list_all(self, sort_by: str = "genre", sort_order: str = "asc",
                 category: str | None = None) -> list[dict]:
        """List all entries, optionally filtered by genre/category."""
        filters = None
        if category:
            filters = {"genre": category}
        return database.list_entries(self._conn, sort_by=sort_by, sort_order=sort_order, filters=filters)

    def resolve_file_path(self, file_hash: str) -> Path | None:
        """Resolve an entry hash (full or prefix) to an existing absolute file path."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            return None

        entry = database.get_entry(self._conn, full_hash)
        if entry is None:
            return None

        rel_path = Path(entry["rel_path"])

        # Search configured scan roots for the recorded relative path.
        for scan_dir in self._scan_dirs:
            candidate = (Path(scan_dir) / rel_path).resolve()
            if candidate.is_file():
                return candidate

        # Fallback: handle absolute paths stored in legacy/custom databases.
        if rel_path.is_absolute() and rel_path.is_file():
            return rel_path

        return None

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

        with open(str(self.config_path), "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        self._config = metadata.load_config(str(self.config_path))

    # -- FTS --

    def reindex_fts(self, progress_callback=None) -> int:
        """Rebuild the entire FTS index from scratch. Returns the count indexed.

        progress_callback(current, total) is called at each document (optional).
        """
        return fts.rebuild_index(self._fts_conn, self._conn, self._scan_dirs, progress_callback)

    # -- Metadata extraction / draft staging --

    def suggest_metadata(self, file_hash: str) -> dict:
        """Run the 3-layer extraction pipeline for one entry.

        Stores results as drafts. Auto-commits fields whose confidence meets
        the ai_config threshold. Returns a dict of {field: {value, source,
        confidence, auto_committed}} for every field that was suggested.
        """
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            raise ValueError(f"No unique entry found for hash prefix '{file_hash}'")

        entry = database.get_entry(self._conn, full_hash)
        if entry is None:
            raise ValueError(f"Entry not found: {file_hash}")

        abs_path = self._resolve_abs_path(entry["rel_path"])
        if abs_path is None:
            raise ValueError(f"File not found on disk for entry {file_hash[:7]}")

        ai_cfg = self.get_ai_config()
        result = extractor.extract_metadata(
            abs_path,
            current_metadata=entry.get("metadata", {}),
            ai_config=ai_cfg,
        )

        threshold = float(ai_cfg.get("auto_commit_threshold", 0.8))
        drafts = result.as_dict()
        output = {}

        for field_name, field_draft in drafts.items():
            database.upsert_draft(
                self._conn,
                full_hash,
                field_name,
                field_draft.value,
                field_draft.source,
                field_draft.confidence,
            )
            auto_committed = field_draft.confidence >= threshold
            if auto_committed:
                database.update_metadata(
                    self._conn, full_hash, field_name, field_draft.value
                )
                database.delete_draft(self._conn, full_hash)

            output[field_name] = {
                "value": field_draft.value,
                "source": field_draft.source,
                "confidence": field_draft.confidence,
                "auto_committed": auto_committed,
            }

        if any(v["auto_committed"] for v in output.values()):
            self._sync_fts_entry(full_hash)

        return output

    def get_draft(self, file_hash: str) -> dict:
        """Return the current draft for an entry (empty dict if none)."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            return {}
        return database.get_draft(self._conn, full_hash)

    def commit_draft(self, file_hash: str) -> None:
        """Commit all pending drafts for one entry to the main metadata table."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            raise ValueError(f"No unique entry found for hash prefix '{file_hash}'")
        database.commit_draft(self._conn, full_hash)
        self._sync_fts_entry(full_hash)

    def discard_draft(self, file_hash: str) -> None:
        """Discard pending drafts for one entry without committing."""
        full_hash = database.resolve_hash_prefix(self._conn, file_hash)
        if full_hash is None:
            return
        database.delete_draft(self._conn, full_hash)

    def suggest_all(self, progress_callback=None) -> dict[str, int]:
        """Run suggest_metadata for all entries where authors/year/keywords is empty.

        progress_callback(current, total) is called at each entry (optional).
        Returns {'suggested': N, 'auto_committed': N}.
        """
        entries = database.list_entries(self._conn)
        qualifying = []
        for entry in entries:
            if entry.get("missing"):
                continue
            meta = entry.get("metadata", {})
            needs_suggestion = (
                not meta.get("authors", "").strip()
                or not meta.get("year", "").strip()
                or not _has_keywords(meta.get("keywords", ""))
            )
            if needs_suggestion:
                qualifying.append(entry)

        total = len(qualifying)
        suggested = 0
        auto_committed_total = 0

        for i, entry in enumerate(qualifying):
            try:
                result = self.suggest_metadata(entry["file_hash"])
                suggested += 1
                auto_committed_total += sum(
                    1 for v in result.values() if v.get("auto_committed")
                )
            except (ValueError, OSError):
                pass
            if progress_callback:
                progress_callback(i + 1, total)

        return {"suggested": suggested, "auto_committed": auto_committed_total}

    def commit_all_drafts(self) -> int:
        """Commit all pending drafts across all entries. Returns count of entries committed."""
        all_drafts = database.get_all_drafts(self._conn)
        count = 0
        for file_hash in all_drafts:
            database.commit_draft(self._conn, file_hash)
            self._sync_fts_entry(file_hash)
            count += 1
        return count

    def get_pending_draft_hashes(self) -> set[str]:
        """Return the set of file_hashes that have pending drafts."""
        return set(database.get_all_drafts(self._conn).keys())

    # -- AI config --

    def get_ai_config(self) -> dict:
        """Load and return ai_config.json (creates default if absent)."""
        return ai_client.load_ai_config(self.ai_config_path)

    def save_ai_config(self, config: dict) -> None:
        """Validate and save ai_config.json."""
        allowed_providers = {"gemini", "openai"}
        provider = config.get("provider", "gemini")
        if provider not in allowed_providers:
            raise ValueError(
                f"Unknown provider '{provider}'. Must be one of: {allowed_providers}"
            )
        threshold = config.get("auto_commit_threshold", 0.8)
        try:
            threshold = float(threshold)
        except (ValueError, TypeError) as exc:
            raise ValueError("auto_commit_threshold must be a number") from exc
        if not (0.0 <= threshold <= 1.0):
            raise ValueError("auto_commit_threshold must be between 0.0 and 1.0")
        config["auto_commit_threshold"] = threshold
        ai_client.save_ai_config(self.ai_config_path, config)

    # -- Cleanup --

    def close(self) -> None:
        """Close both database connections."""
        self._conn.close()
        self._fts_conn.close()

    # -- Internal helpers --

    def _resolve_abs_path(self, rel_path: str) -> Path | None:
        """Resolve a relative path string to an existing absolute file path."""
        p = Path(rel_path)
        for scan_dir in self._scan_dirs:
            candidate = (Path(scan_dir) / p).resolve()
            if candidate.is_file():
                return candidate
        if p.is_absolute() and p.is_file():
            return p
        return None

    def _sync_fts_entry(self, file_hash: str) -> None:
        """Rebuild the FTS entry for a single document from current library.db state."""
        entry = database.get_entry(self._conn, file_hash)
        if entry is None:
            fts.remove_document(self._fts_conn, file_hash)
            return

        meta = entry.get("metadata", {})
        metadata_text = " ".join(str(v) for v in meta.values() if v)
        abs_path = self._resolve_abs_path(entry["rel_path"])
        body = fts.extract_text(abs_path) if abs_path else ""

        fts.index_document(
            self._fts_conn,
            file_hash,
            entry["filename"],
            metadata_text,
            body,
        )


def _has_keywords(raw: object) -> bool:
    """Return True if raw keywords value represents a non-empty list or string."""
    if not raw:
        return False
    if isinstance(raw, list):
        return any(str(k).strip() for k in raw)
    # Stored as JSON string
    try:
        parsed = json.loads(str(raw))
        if isinstance(parsed, list):
            return any(str(k).strip() for k in parsed)
    except (json.JSONDecodeError, ValueError):
        pass
    return bool(str(raw).strip()) and str(raw).strip() not in ("[]", "")
