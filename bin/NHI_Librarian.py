#!/usr/bin/env python3
"""NHI Librarian — Interactive CLI for document cataloging."""

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

from lib.api import NHILibrarian


class NHILibrarianCLI(cmd.Cmd):
    """Interactive REPL for NHI Librarian."""

    intro = "NHI Librarian - type 'help' for available commands.\n"
    prompt = "nhi> "

    def __init__(self, librarian: NHILibrarian):
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
        """Search entries by filename, title, or keywords. Usage: search <query>"""
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

    def do_quit(self, _arg):
        """Exit NHI Librarian."""
        print("  Goodbye.")
        return True

    # Aliases
    do_exit = do_quit
    do_EOF = do_quit


def main():
    data_dir = str(Path(__file__).resolve().parent.parent / "data")
    librarian = NHILibrarian(data_dir=data_dir)

    # Auto-refresh on first run
    print("Scanning configured directories...")
    report = librarian.refresh()
    print(f"  Found {len(report.new)} new file(s).\n")

    cli = NHILibrarianCLI(librarian)
    cli.cmdloop()


if __name__ == "__main__":
    main()
