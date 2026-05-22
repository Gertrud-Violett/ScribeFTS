"""Persistent workspace preference management for ScribeFTS.

Stores and retrieves the last-used meta_config.json path so the app
can reopen the same workspace across launches without user intervention.
"""

import json
import shutil
from pathlib import Path

_PREFS_DIR = Path.home() / ".scribefts"
_PREFS_FILE = _PREFS_DIR / "prefs.json"
_WORKSPACE_FILES = ("meta_config.json", "library.db", "fts.db", "ai_config.json")


def load_last_settings_path() -> Path | None:
    """Return the saved meta_config.json path, or None if absent or file missing."""
    if not _PREFS_FILE.is_file():
        return None
    try:
        data = json.loads(_PREFS_FILE.read_text(encoding="utf-8"))
        raw = data.get("last_settings_file")
        if raw:
            p = Path(raw)
            return p if p.is_file() else None
    except (json.JSONDecodeError, OSError):
        return None
    return None


def save_last_settings_path(settings_path: Path) -> None:
    """Persist settings_path as the last-used workspace pointer."""
    _PREFS_DIR.mkdir(parents=True, exist_ok=True)
    _PREFS_FILE.write_text(
        json.dumps({"last_settings_file": str(settings_path.resolve())}, indent=2),
        encoding="utf-8",
    )


def move_workspace(old_data_dir: Path, new_data_dir: Path) -> None:
    """Copy all workspace files from old_data_dir to new_data_dir, then remove originals.

    Only files that exist are copied. The destination directory is created if needed.
    Originals are removed only after all copies succeed.
    """
    new_data_dir.mkdir(parents=True, exist_ok=True)
    to_remove = []
    for name in _WORKSPACE_FILES:
        src = old_data_dir / name
        if src.is_file():
            shutil.copy2(src, new_data_dir / name)
            to_remove.append(src)
    for src in to_remove:
        src.unlink()
