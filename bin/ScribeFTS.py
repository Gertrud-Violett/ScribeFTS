#!/usr/bin/env python3
"""ScribeFTS — Interactive CLI for document cataloging."""

import cmd
import json
import sys
from pathlib import Path

# Handle encoding for terminals that default to non-UTF-8 (e.g. cp932 on Windows)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is on sys.path so `lib` is importable
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from lib.api import ScribeFTS
from lib import settings_locator


_DEFAULT_DATA_DIR = str(_project_root / "data")


def _resolve_data_dir(settings_path: str | None) -> str:
    """Resolve the workspace data directory for CLI startup.

    Priority: explicit --settings arg > last-used prefs > interactive prompt.
    Returns the data_dir string (parent of meta_config.json).
    """
    if settings_path is not None:
        p = Path(settings_path).resolve()
        if p.suffix.lower() == ".json":
            data_dir = p.parent
            settings_locator.save_last_settings_path(p)
        else:
            # Treat as a data directory directly
            data_dir = p
            settings_locator.save_last_settings_path(p / "meta_config.json")
        print(f"  Using settings: {data_dir / 'meta_config.json'}")
        return str(data_dir)

    last = settings_locator.load_last_settings_path()
    if last:
        print(f"  Using settings: {last}")
        return str(last.parent)

    return _prompt_first_run()


def _prompt_first_run() -> str:
    """Interactively ask the user where to put or find the workspace on first run."""
    print("\n  No settings file found. How would you like to start?")
    print("  1. Open an existing settings file (meta_config.json)")
    print("  2. Create a new workspace in a directory")
    print("  [Enter] Use the default location (./data/)")

    choice = input("\n  Select [1/2 or Enter]: ").strip()

    if choice == "1":
        while True:
            path_str = input("  Path to meta_config.json: ").strip()
            if not path_str:
                break
            p = Path(path_str).resolve()
            if p.is_file():
                settings_locator.save_last_settings_path(p)
                print(f"  Workspace: {p.parent}")
                return str(p.parent)
            print(f"  File not found: {p}")

    elif choice == "2":
        dir_str = input("  Directory for new workspace: ").strip()
        if dir_str:
            d = Path(dir_str).resolve()
            d.mkdir(parents=True, exist_ok=True)
            settings_locator.save_last_settings_path(d / "meta_config.json")
            print(f"  New workspace: {d}")
            return str(d)

    print(f"  Using default: {_DEFAULT_DATA_DIR}")
    return _DEFAULT_DATA_DIR


class ScribeFTSCLI(cmd.Cmd):
    """Interactive REPL for ScribeFTS."""

    intro = "ScribeFTS - type 'help' for available commands.\n"
    prompt = "scribe> "

    def __init__(self, librarian: ScribeFTS):
        super().__init__()
        self.lib = librarian

    # -- Commands --

    def do_refresh(self, _arg):
        """Scan configured directories for new, moved, or missing files."""
        report = self.lib.refresh()
        print(f"  New:     {len(report.new)}")
        print(f"  Moved:   {len(report.moved)}")
        print(f"  Missing: {len(report.missing)}")
        if report.new:
            for fi in report.new:
                print(f"    + {fi.rel_path}")
        if report.moved:
            for fi, old in report.moved:
                print(f"    ~ {old} -> {fi.rel_path}")
        if report.missing:
            for fh in report.missing:
                print(f"    - {fh[:7]}...")

    def do_list(self, arg):
        """List all cataloged files. Usage: list [--sort FIELD] [--category CAT]"""
        parts = arg.split()
        sort_by = "filename"
        category = None

        i = 0
        while i < len(parts):
            if parts[i] == "--sort" and i + 1 < len(parts):
                sort_by = parts[i + 1]
                i += 2
            elif parts[i] == "--category" and i + 1 < len(parts):
                category = parts[i + 1]
                i += 2
            else:
                i += 1

        entries = self.lib.list_all(sort_by=sort_by, category=category)
        if not entries:
            print("  No entries found.")
            return

        for entry in entries:
            status = " [MISSING]" if entry.get("missing") else ""
            genre = entry.get("metadata", {}).get("genre", "")
            genre_str = f"  [{genre}]" if genre else ""
            print(f"  {entry['file_hash'][:7]}  {entry['filename']}{genre_str}{status}")
        print(f"\n  Total: {len(entries)}")

    def do_search(self, arg):
        """Search entries by filename or metadata values (LIKE-based). Usage: search <query>"""
        if not arg.strip():
            print("  Usage: search <query>")
            return

        results = self.lib.search(arg.strip())
        if not results:
            print("  No matches found.")
            return

        for entry in results:
            print(f"  {entry['file_hash'][:7]}  {entry['filename']}")
        print(f"\n  {len(results)} match(es)")

    def do_fts_search(self, arg):
        """Full-text search using the FTS5 index. Usage: fts_search <query>"""
        if not arg.strip():
            print("  Usage: fts_search <query>")
            return

        try:
            results = self.lib.fts_search(arg.strip())
        except Exception as e:
            print(f"  FTS search error: {e}")
            return

        if not results:
            print("  No matches found.")
            return

        for entry in results:
            print(f"  {entry['file_hash'][:7]}  {entry['filename']}")
        print(f"\n  {len(results)} match(es)")

    def do_reindex(self, _arg):
        """Rebuild the FTS index from scratch (re-extracts text from all cataloged files)."""
        print("  Rebuilding FTS index...")

        def progress(current, total):
            pct = (current / total * 100) if total > 0 else 0
            bar_len = 30
            filled = int(bar_len * current / total) if total > 0 else 0
            bar = '█' * filled + '░' * (bar_len - filled)
            print(f"\r  [{bar}] {current}/{total} ({pct:.0f}%)", end='', flush=True)

        count = self.lib.reindex_fts(progress_callback=progress)
        print(f"\n  Indexed {count} document(s).")

    def do_show(self, arg):
        """Show full details for an entry. Usage: show <hash_prefix>"""
        if not arg.strip():
            print("  Usage: show <hash_prefix>")
            return

        entry = self.lib.get_entry(arg.strip())
        if entry is None:
            print("  Entry not found (hash prefix may be ambiguous or invalid).")
            return

        print(f"  Hash:     {entry['file_hash']}")
        print(f"  File:     {entry['filename']}")
        print(f"  Path:     {entry['rel_path']}")
        print(f"  Size:     {entry['file_size']:,} bytes")
        print(f"  Added:    {entry['date_added']}")
        print(f"  Modified: {entry['date_modified']}")
        print(f"  Missing:  {'Yes' if entry['missing'] else 'No'}")
        meta = entry.get("metadata", {})
        if meta:
            print("  Metadata:")
            for k, v in meta.items():
                print(f"    {k}: {v}")

    def do_update(self, arg):
        """Update a single metadata field. Usage: update <hash_prefix> <field> <value>"""
        parts = arg.split(maxsplit=2)
        if len(parts) < 3:
            print("  Usage: update <hash_prefix> <field> <value>")
            return

        hash_prefix, field, value = parts
        # Try to parse as JSON for list fields
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                value = parsed
        except (json.JSONDecodeError, ValueError):
            pass

        try:
            self.lib.update_metadata(hash_prefix, {field: value})
            print(f"  Updated '{field}' for {hash_prefix}.")
        except ValueError as e:
            print(f"  Error: {e}")

    def do_edit(self, arg):
        """Interactively edit all metadata fields. Usage: edit <hash_prefix>"""
        if not arg.strip():
            print("  Usage: edit <hash_prefix>")
            return

        entry = self.lib.get_entry(arg.strip())
        if entry is None:
            print("  Entry not found.")
            return

        print(f"  Editing: {entry['filename']}")
        config = self.lib.get_meta_config()
        current_meta = entry.get("metadata", {})
        updates = {}

        for field_def in config["fields"]:
            name = field_def["name"]
            current = current_meta.get(name, field_def.get("default", ""))

            if field_def["type"] == "choice":
                choices = field_def.get("choices", [])
                print(f"\n  {name} (current: {current})")
                for idx, ch in enumerate(choices, 1):
                    print(f"    {idx}. {ch}")
                answer = input(f"  Select [1-{len(choices)}] or Enter to keep: ").strip()
                if answer:
                    try:
                        choice_idx = int(answer) - 1
                        if 0 <= choice_idx < len(choices):
                            updates[name] = choices[choice_idx]
                        else:
                            print("  Invalid selection, keeping current value.")
                    except ValueError:
                        print("  Invalid input, keeping current value.")
            elif field_def["type"] == "list":
                print(f"\n  {name} (current: {current})")
                answer = input("  Enter comma-separated values or Enter to keep: ").strip()
                if answer:
                    updates[name] = [item.strip() for item in answer.split(",")]
            else:
                answer = input(f"  {name} [{current}]: ").strip()
                if answer:
                    updates[name] = answer

        if updates:
            try:
                self.lib.update_metadata(arg.strip(), updates)
                print("  Metadata updated.")
            except ValueError as e:
                print(f"  Error: {e}")
        else:
            print("  No changes made.")

    def do_delete(self, arg):
        """Remove an entry from the database (file is not deleted). Usage: delete <hash_prefix>"""
        if not arg.strip():
            print("  Usage: delete <hash_prefix>")
            return

        entry = self.lib.get_entry(arg.strip())
        if entry is None:
            print("  Entry not found.")
            return

        confirm = input(f"  Delete '{entry['filename']}' from catalog? [y/N]: ").strip().lower()
        if confirm == "y":
            try:
                self.lib.delete_entry(arg.strip())
                print("  Entry deleted.")
            except ValueError as e:
                print(f"  Error: {e}")
        else:
            print("  Cancelled.")

    def do_delete_old(self, _arg):
        """Permanently remove all entries flagged as MISSING from the database."""
        count = self.lib.delete_missing()
        if count:
            print(f"  Removed {count} missing entry/entries.")
        else:
            print("  No missing entries to remove.")

    def do_export(self, arg):
        """Export the database to JSON. Usage: export [path]"""
        out_path = arg.strip() if arg.strip() else str(self.lib.data_dir / "library_export.json")
        self.lib.export_json(out_path)
        print(f"  Exported to {out_path}")

    def do_stats(self, _arg):
        """Show summary statistics."""
        entries = self.lib.list_all()
        total = len(entries)
        missing = sum(1 for e in entries if e.get("missing"))
        present = total - missing

        # Count by genre
        genre_counts: dict[str, int] = {}
        for e in entries:
            genre = e.get("metadata", {}).get("genre", "")
            if genre:
                genre_counts[genre] = genre_counts.get(genre, 0) + 1

        print(f"  Total entries: {total}")
        print(f"  Present:       {present}")
        print(f"  Missing:       {missing}")
        if genre_counts:
            print("  By genre:")
            for genre, count in sorted(genre_counts.items()):
                print(f"    {genre}: {count}")

    def do_suggest(self, arg):
        """Run the extraction pipeline for one entry and show draft suggestions. Usage: suggest <hash_prefix>"""
        if not arg.strip():
            print("  Usage: suggest <hash_prefix>")
            return

        try:
            result = self.lib.suggest_metadata(arg.strip())
        except ValueError as e:
            print(f"  Error: {e}")
            return

        entry = self.lib.get_entry(arg.strip())
        filename = entry["filename"] if entry else arg.strip()
        print(f"  Suggested for {filename}:")
        for field_name, info in result.items():
            status = "AUTO-COMMITTED" if info.get("auto_committed") else "DRAFT - run 'commit' to apply"
            print(
                f"    {field_name:<12} \"{info['value']}\""
                f"  [{info['source']}, confidence={info['confidence']:.0%}]"
                f"  <- {status}"
            )

    def do_suggest_all(self, _arg):
        """Run extraction for all entries with missing author/year/keywords."""
        print("  Running extraction for qualifying entries...")

        def progress(current, total):
            pct = (current / total * 100) if total > 0 else 0
            bar_len = 30
            filled = int(bar_len * current / total) if total > 0 else 0
            bar = '█' * filled + '░' * (bar_len - filled)
            print(f"\r  [{bar}] {current}/{total} ({pct:.0f}%)", end='', flush=True)

        counts = self.lib.suggest_all(progress_callback=progress)
        print(f"\n  Processed: {counts['suggested']} entry/entries")
        print(f"  Auto-committed: {counts['auto_committed']} field(s)")

    def do_commit(self, arg):
        """Commit pending draft for one entry to the metadata table. Usage: commit <hash_prefix>"""
        if not arg.strip():
            print("  Usage: commit <hash_prefix>")
            return

        draft = self.lib.get_draft(arg.strip())
        if not draft:
            print("  No pending draft for that entry.")
            return

        try:
            self.lib.commit_draft(arg.strip())
            print(f"  Draft committed ({len(draft)} field(s) updated).")
        except ValueError as e:
            print(f"  Error: {e}")

    def do_commit_all(self, _arg):
        """Commit all pending drafts across all entries."""
        count = self.lib.commit_all_drafts()
        if count:
            print(f"  Committed drafts for {count} entry/entries.")
        else:
            print("  No pending drafts to commit.")

    def do_location(self, _arg):
        """Manage the workspace location. Usage: location"""
        print(f"  Current workspace : {self.lib.data_dir}")
        print(f"  Settings file     : {self.lib.config_path}")
        print()
        print("  1. Open different settings file")
        print("  2. Create new workspace in a directory")
        print("  3. Move workspace to a new directory")
        choice = input("  Select [1-3] or Enter to cancel: ").strip()
        if choice == "1":
            self._location_open()
        elif choice == "2":
            self._location_create()
        elif choice == "3":
            self._location_move()
        else:
            print("  Cancelled.")

    def _location_open(self) -> None:
        path_str = input("  Path to meta_config.json: ").strip()
        if not path_str:
            print("  Cancelled.")
            return
        p = Path(path_str).resolve()
        if not p.is_file():
            print(f"  File not found: {p}")
            return
        self.lib.close()
        settings_locator.save_last_settings_path(p)
        self.lib = ScribeFTS(data_dir=str(p.parent))
        print(f"  Workspace opened: {p.parent}")

    def _location_create(self) -> None:
        dir_str = input("  Directory for new workspace: ").strip()
        if not dir_str:
            print("  Cancelled.")
            return
        d = Path(dir_str).resolve()
        d.mkdir(parents=True, exist_ok=True)
        self.lib.close()
        settings_locator.save_last_settings_path(d / "meta_config.json")
        self.lib = ScribeFTS(data_dir=str(d))
        print(f"  New workspace created: {d}")

    def _location_move(self) -> None:
        dir_str = input("  Destination directory: ").strip()
        if not dir_str:
            print("  Cancelled.")
            return
        new_dir = Path(dir_str).resolve()
        old_dir = self.lib.data_dir
        self.lib.close()
        try:
            settings_locator.move_workspace(old_dir, new_dir)
        except OSError as e:
            print(f"  Move failed: {e}")
            self.lib = ScribeFTS(data_dir=str(old_dir))
            return
        settings_locator.save_last_settings_path(new_dir / "meta_config.json")
        self.lib = ScribeFTS(data_dir=str(new_dir))
        print(f"  Workspace moved to: {new_dir}")

    def do_quit(self, _arg):
        """Exit ScribeFTS."""
        print("  Goodbye.")
        return True

    # Aliases
    do_exit = do_quit
    do_EOF = do_quit


def main(settings_path: str | None = None):
    data_dir = _resolve_data_dir(settings_path)
    librarian = ScribeFTS(data_dir=data_dir)

    # Auto-refresh on first run
    print("Scanning configured directories...")
    report = librarian.refresh()
    print(f"  Found {len(report.new)} new file(s).\n")

    cli = ScribeFTSCLI(librarian)
    cli.cmdloop()


if __name__ == "__main__":
    main()
