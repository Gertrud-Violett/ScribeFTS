"""Flask-based GUI for ScribeFTS."""

import json
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from flask import Flask, flash, g, jsonify, redirect, render_template, request, Response, url_for, stream_with_context
from werkzeug.exceptions import HTTPException

from lib.api import ScribeFTS

_FILES_COLUMNS = {"filename", "date_added", "date_modified", "file_size", "rel_path", "missing"}


def _sort_entries(entries: list, sort_by: str, sort_order: str) -> list:
    """Sort a list of entry dicts by any files-table column or metadata field."""
    reverse = sort_order.lower() == "desc"
    if sort_by in _FILES_COLUMNS:
        return sorted(entries, key=lambda e: (e.get(sort_by) or ""), reverse=reverse)
    return sorted(
        entries,
        key=lambda e: (e.get("metadata", {}).get(sort_by) or "").lower(),
        reverse=reverse,
    )


def _open_with_default_app(file_path: Path) -> None:
    """Open a file with the user's OS-default application."""
    if sys.platform.startswith("win"):
        os.startfile(str(file_path))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(file_path)], check=True)
        return
    subprocess.run(["xdg-open", str(file_path)], check=True)


def _is_within_scan_dirs(dest: Path, scan_dirs: list) -> bool:
    """Return True if dest is a subdirectory of any configured scan directory."""
    resolved = dest.resolve()
    for sd in scan_dirs:
        try:
            resolved.relative_to(Path(sd).resolve())
            return True
        except ValueError:
            continue
    return False


def create_app(data_dir: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.secret_key = "scribefts-local-only"
    app.config["DATA_DIR"] = data_dir  # None means unconfigured → workspace page

    def get_lib() -> ScribeFTS:
        """Return a request-scoped ScribeFTS instance.

        Flask may serve requests in different threads, so the SQLite connection
        must be created and used within the same request thread.
        """
        if "lib" not in g:
            g.lib = ScribeFTS(data_dir=app.config["DATA_DIR"])
        return g.lib

    @app.teardown_appcontext
    def close_lib(exc):
        lib = g.pop("lib", None)
        if lib is not None:
            lib.close()

    @app.before_request
    def require_workspace():
        """Redirect to workspace setup when no data directory is configured."""
        _workspace_endpoints = {
            "workspace", "workspace_open", "workspace_create", "workspace_move",
            "browse_dir", "static",
        }
        if request.endpoint not in _workspace_endpoints and not app.config.get("DATA_DIR"):
            return redirect(url_for("workspace"))

    @app.context_processor
    def inject_scan_dirs():
        """Inject scan_dirs and first_scan_dir into every template context."""
        if not app.config.get("DATA_DIR"):
            return {"scan_dirs": [], "first_scan_dir": ""}
        try:
            lib = get_lib()
            scan_dirs = lib.get_meta_config().get("scan_directories", [])
            first_scan_dir = str(Path(scan_dirs[0]).resolve()) if scan_dirs else ""
        except Exception:
            return {"scan_dirs": [], "first_scan_dir": ""}
        return {"scan_dirs": scan_dirs, "first_scan_dir": first_scan_dir}

    @app.errorhandler(Exception)
    def log_unhandled_error(exc):
        """Log unexpected GUI errors to a file for diagnosis."""
        if isinstance(exc, HTTPException):
            return exc

        current_data_dir = app.config.get("DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
        log_path = Path(current_data_dir) / "gui_error.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
            f.write("\n" + "-" * 80 + "\n")
        app.logger.exception("Unhandled GUI exception")
        return (
            "Internal Server Error. See data/gui_error.log for details.",
            500,
        )

    # --- Routes ---

    @app.route("/")
    def index():
        lib = get_lib()
        sort_by = request.args.get("sort", "genre")
        sort_order = request.args.get("order", "asc")
        entries = lib.list_all(sort_by=sort_by, sort_order=sort_order)
        pending_drafts = lib.get_pending_draft_hashes()
        fields = lib.get_meta_config()["fields"]
        return render_template(
            "library.html", entries=entries, view_name="index", query="",
            pending_drafts=pending_drafts, fields=fields,
            current_sort=sort_by, sort_order=sort_order,
        )

    @app.route("/refresh", methods=["POST"])
    def refresh():
        lib = get_lib()
        report = lib.refresh()
        flash(
            f"Refresh complete: {len(report.new)} new, {len(report.moved)} moved, "
            f"{len(report.missing)} missing.",
            "success",
        )
        return redirect(url_for("index"))

    @app.route("/entry/<hash_prefix>")
    def detail(hash_prefix):
        lib = get_lib()
        entry = lib.get_entry(hash_prefix)
        if entry is None:
            flash("Entry not found.", "error")
            return redirect(url_for("index"))
        fields = lib.get_meta_config()["fields"]
        draft = lib.get_draft(hash_prefix)
        return render_template("detail.html", entry=entry, fields=fields, edit_mode=False, draft=draft)

    @app.route("/entry/<hash_prefix>/open")
    def open_entry_file(hash_prefix):
        lib = get_lib()
        file_path = lib.resolve_file_path(hash_prefix)
        if file_path is None:
            flash("File not found on disk for this entry.", "error")
            return redirect(request.referrer or url_for("index"))

        try:
            _open_with_default_app(file_path)
        except Exception as e:
            flash(f"Failed to open file: {e}", "error")
        return redirect(request.referrer or url_for("index"))

    @app.route("/entry/<hash_prefix>/edit", methods=["GET", "POST"])
    def edit_entry(hash_prefix):
        lib = get_lib()
        entry = lib.get_entry(hash_prefix)
        if entry is None:
            flash("Entry not found.", "error")
            return redirect(url_for("index"))

        fields = lib.get_meta_config()["fields"]

        if request.method == "POST":
            updates = {}
            for field_def in fields:
                name = field_def["name"]
                raw = request.form.get(name, "")
                if field_def["type"] == "list":
                    updates[name] = [v.strip() for v in raw.split(",") if v.strip()]
                else:
                    updates[name] = raw

            try:
                lib.update_metadata(hash_prefix, updates)
                flash("Metadata updated.", "success")
                if request.form.get("_return_to") == "library":
                    return redirect(url_for("index"))
                return redirect(url_for("detail", hash_prefix=entry["file_hash"]))
            except ValueError as e:
                flash(str(e), "error")

        return render_template("detail.html", entry=entry, fields=fields, edit_mode=True)

    @app.route("/entry/<hash_prefix>/delete", methods=["POST"])
    def delete_entry_route(hash_prefix):
        lib = get_lib()
        try:
            lib.delete_entry(hash_prefix)
            flash("Entry deleted.", "success")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("index"))

    @app.route("/delete-old", methods=["POST"])
    def delete_old():
        lib = get_lib()
        count = lib.delete_missing()
        if count:
            flash(f"Removed {count} missing entry/entries.", "success")
        else:
            flash("No missing entries to remove.", "info")
        return redirect(url_for("index"))

    @app.route("/search")
    def search():
        lib = get_lib()
        query = request.args.get("q", "").strip()
        if not query:
            return redirect(url_for("index"))
        sort_by = request.args.get("sort", "genre")
        sort_order = request.args.get("order", "asc")
        entries = _sort_entries(lib.search(query), sort_by, sort_order)
        pending_drafts = lib.get_pending_draft_hashes()
        fields = lib.get_meta_config()["fields"]
        return render_template(
            "library.html", entries=entries, query=query,
            view_name="search", search_mode="metadata", pending_drafts=pending_drafts, fields=fields,
            current_sort=sort_by, sort_order=sort_order,
        )

    @app.route("/fts_search")
    def fts_search():
        lib = get_lib()
        query = request.args.get("q", "").strip()
        if not query:
            return redirect(url_for("index"))
        try:
            entries = lib.fts_search(query)
        except Exception as e:
            flash(f"Full-text search error: {e}", "error")
            entries = []
        sort_by = request.args.get("sort", "genre")
        sort_order = request.args.get("order", "asc")
        entries = _sort_entries(entries, sort_by, sort_order)
        pending_drafts = lib.get_pending_draft_hashes()
        fields = lib.get_meta_config()["fields"]
        return render_template(
            "library.html", entries=entries, query=query,
            view_name="fts_search", search_mode="fulltext", pending_drafts=pending_drafts, fields=fields,
            current_sort=sort_by, sort_order=sort_order,
        )

    @app.route("/reindex", methods=["GET"])
    def reindex_page():
        return render_template("progress.html", operation="reindex", title="Rebuilding FTS Index")

    @app.route("/reindex", methods=["POST"])
    def reindex():
        class Progress:
            def __init__(self):
                self.current = 0
                self.total = 0
                self.count = 0

            def callback(self, current, total):
                self.current = current
                self.total = total

        progress = Progress()

        def generate():
            current_data_dir = app.config["DATA_DIR"]

            def work():
                # Create a new ScribeFTS instance for this thread
                thread_lib = ScribeFTS(data_dir=current_data_dir)
                try:
                    progress.count = thread_lib.reindex_fts(progress_callback=progress.callback)
                finally:
                    thread_lib.close()

            thread = threading.Thread(target=work, daemon=True)
            thread.start()

            while thread.is_alive():
                yield json.dumps({
                    "current": progress.current,
                    "total": progress.total,
                    "complete": False,
                }) + "\n"
                time.sleep(0.1)

            thread.join()
            yield json.dumps({
                "current": progress.total,
                "total": progress.total,
                "complete": True,
                "count": progress.count,
            }) + "\n"

        return Response(stream_with_context(generate()), mimetype="application/x-ndjson")

    @app.route("/export", methods=["POST"])
    def do_export():
        lib = get_lib()
        out_path = str(Path(app.config["DATA_DIR"]) / "library_export.json")
        lib.export_json(out_path)
        flash(f"Exported to {out_path}", "success")
        return redirect(url_for("index"))

    @app.route("/stats")
    def stats():
        lib = get_lib()
        entries = lib.list_all()
        total = len(entries)
        missing = sum(1 for e in entries if e.get("missing"))
        present = total - missing

        genre_counts: dict[str, int] = {}
        author_counts: dict[str, int] = {}
        keyword_counts: dict[str, int] = {}
        year_counts: dict[str, int] = {}
        for e in entries:
            meta = e.get("metadata", {})
            genre = meta.get("genre", "")
            if genre:
                genre_counts[genre] = genre_counts.get(genre, 0) + 1
            authors = meta.get("authors", "")
            if authors:
                author_counts[authors] = author_counts.get(authors, 0) + 1
            keywords = meta.get("keywords", [])
            if isinstance(keywords, list):
                for kw in keywords:
                    if kw:
                        keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
            year = meta.get("year", "")
            if year:
                year_counts[year] = year_counts.get(year, 0) + 1

        sorted_genres = sorted(genre_counts.items())
        sorted_authors = sorted(author_counts.items())
        sorted_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
        sorted_years = sorted(year_counts.items())
        return render_template(
            "stats.html", total=total, present=present, missing=missing,
            genre_counts=sorted_genres, author_counts=sorted_authors,
            keyword_counts=sorted_keywords, year_counts=sorted_years,
        )

    @app.route("/config", methods=["GET", "POST"])
    def config_page():
        lib = get_lib()
        if request.method == "POST":
            raw = request.form.get("config_json", "")
            try:
                config = json.loads(raw)
                lib.save_meta_config(config)
                flash("Configuration saved.", "success")
                return redirect(url_for("config_page"))
            except (json.JSONDecodeError, ValueError) as e:
                flash(f"Invalid config: {e}", "error")

        config = lib.get_meta_config()
        config_json = json.dumps(config, indent=2, ensure_ascii=False)
        return render_template("config.html", config_json=config_json, config=config)

    @app.route("/suggest/<hash_prefix>", methods=["POST"])
    def suggest_entry(hash_prefix):
        lib = get_lib()
        try:
            result = lib.suggest_metadata(hash_prefix)
            auto = sum(1 for v in result.values() if v.get("auto_committed"))
            draft = len(result) - auto
            msg = f"Extraction complete: {auto} field(s) auto-committed, {draft} draft(s) pending."
            flash(msg, "success")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(request.referrer or url_for("detail", hash_prefix=hash_prefix))

    @app.route("/commit/<hash_prefix>", methods=["POST"])
    def commit_entry(hash_prefix):
        lib = get_lib()
        try:
            lib.commit_draft(hash_prefix)
            flash("Draft committed to metadata.", "success")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(request.referrer or url_for("detail", hash_prefix=hash_prefix))

    @app.route("/discard/<hash_prefix>", methods=["POST"])
    def discard_entry_draft(hash_prefix):
        lib = get_lib()
        lib.discard_draft(hash_prefix)
        flash("Draft discarded.", "info")
        return redirect(request.referrer or url_for("detail", hash_prefix=hash_prefix))

    @app.route("/suggest_all", methods=["GET"])
    def suggest_all_page():
        return render_template("progress.html", operation="suggest_all", title="Running Metadata Extraction")

    @app.route("/suggest_all", methods=["POST"])
    def suggest_all():
        class Progress:
            def __init__(self):
                self.current = 0
                self.total = 0
                self.suggested = 0
                self.auto_committed = 0

            def callback(self, current, total):
                self.current = current
                self.total = total

        progress = Progress()

        def generate():
            current_data_dir = app.config["DATA_DIR"]

            def work():
                # Create a new ScribeFTS instance for this thread
                thread_lib = ScribeFTS(data_dir=current_data_dir)
                try:
                    counts = thread_lib.suggest_all(progress_callback=progress.callback)
                    progress.suggested = counts.get("suggested", 0)
                    progress.auto_committed = counts.get("auto_committed", 0)
                finally:
                    thread_lib.close()

            thread = threading.Thread(target=work, daemon=True)
            thread.start()

            while thread.is_alive():
                yield json.dumps({
                    "current": progress.current,
                    "total": progress.total,
                    "complete": False,
                }) + "\n"
                time.sleep(0.1)

            thread.join()
            yield json.dumps({
                "current": progress.total,
                "total": progress.total,
                "complete": True,
                "suggested": progress.suggested,
                "auto_committed": progress.auto_committed,
            }) + "\n"

        return Response(stream_with_context(generate()), mimetype="application/x-ndjson")

    @app.route("/commit_all", methods=["POST"])
    def commit_all():
        lib = get_lib()
        count = lib.commit_all_drafts()
        flash(f"Committed drafts for {count} entry/entries.", "success")
        return redirect(url_for("index"))

    @app.route("/ai_config", methods=["GET", "POST"])
    def ai_config_page():
        lib = get_lib()
        if request.method == "POST":
            config = {
                "enabled": request.form.get("enabled") == "on",
                "provider": request.form.get("provider", "gemini"),
                "api_key": request.form.get("api_key", "").strip(),
                "model": request.form.get("model", "").strip(),
                "auto_commit_threshold": request.form.get("auto_commit_threshold", "0.8"),
                "openai_endpoint": request.form.get(
                    "openai_endpoint", "https://api.openai.com/v1/chat/completions"
                ).strip(),
            }
            try:
                lib.save_ai_config(config)
                flash("AI configuration saved.", "success")
                return redirect(url_for("ai_config_page"))
            except ValueError as e:
                flash(str(e), "error")

        ai_cfg = lib.get_ai_config()
        return render_template("ai_config.html", ai_cfg=ai_cfg)

    # --- Workspace management routes ---

    @app.route("/workspace")
    def workspace():
        current_data_dir = app.config.get("DATA_DIR")
        return render_template("workspace.html", current_data_dir=current_data_dir)

    @app.route("/workspace/open", methods=["POST"])
    def workspace_open():
        from lib.settings_locator import save_last_settings_path
        path_str = request.form.get("settings_path", "").strip()
        if not path_str:
            flash("Please enter a path to meta_config.json.", "error")
            return redirect(url_for("workspace"))
        p = Path(path_str).resolve()
        if not p.is_file():
            flash(f"File not found: {p}", "error")
            return redirect(url_for("workspace"))
        save_last_settings_path(p)
        app.config["DATA_DIR"] = str(p.parent)
        flash(f"Workspace opened: {p.parent}", "success")
        return redirect(url_for("index"))

    @app.route("/workspace/create", methods=["POST"])
    def workspace_create():
        from lib.settings_locator import save_last_settings_path
        dir_str = request.form.get("new_dir", "").strip()
        if not dir_str:
            flash("Please enter a directory path.", "error")
            return redirect(url_for("workspace"))
        d = Path(dir_str).resolve()
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            flash(f"Could not create directory: {e}", "error")
            return redirect(url_for("workspace"))
        save_last_settings_path(d / "meta_config.json")
        app.config["DATA_DIR"] = str(d)
        flash(f"New workspace created: {d}", "success")
        return redirect(url_for("refresh"))

    @app.route("/workspace/move", methods=["POST"])
    def workspace_move():
        from lib.settings_locator import move_workspace, save_last_settings_path
        dir_str = request.form.get("move_dir", "").strip()
        if not dir_str:
            flash("Please enter a destination directory.", "error")
            return redirect(url_for("workspace"))
        current = app.config.get("DATA_DIR")
        if not current:
            flash("No current workspace to move.", "error")
            return redirect(url_for("workspace"))
        new_dir = Path(dir_str).resolve()
        try:
            move_workspace(Path(current), new_dir)
        except OSError as e:
            flash(f"Move failed: {e}", "error")
            return redirect(url_for("workspace"))
        save_last_settings_path(new_dir / "meta_config.json")
        app.config["DATA_DIR"] = str(new_dir)
        flash(f"Workspace moved to: {new_dir}", "success")
        return redirect(url_for("index"))

    # --- Directory browser route ---

    @app.route("/browse")
    def browse_dir():
        """Return immediate subdirectories of a path for the in-browser directory picker.

        Query param `path`: absolute directory path to list. Empty string → OS roots.
        Returns JSON: {"path": str, "parent": str|null, "dirs": [{"name": str, "path": str}]}
        """
        path_str = request.args.get("path", "").strip()

        # Empty path → list drives (Windows) or root (Unix)
        if not path_str:
            if sys.platform.startswith("win"):
                try:
                    drives = [{"name": d, "path": d} for d in os.listdrives()]
                except AttributeError:
                    import string
                    drives = [
                        {"name": f"{d}:\\", "path": f"{d}:\\"}
                        for d in string.ascii_uppercase
                        if Path(f"{d}:\\").exists()
                    ]
                return jsonify({"path": "", "parent": None, "dirs": drives})
            path_str = "/"

        # Walk up until we find an existing directory (handles not-yet-created paths)
        path = Path(path_str)
        while not path.is_dir() and path != path.parent:
            path = path.parent
        if not path.is_dir():
            return jsonify({"path": "", "parent": None, "dirs": []})

        try:
            subdirs = sorted(
                (e for e in path.iterdir() if e.is_dir()),
                key=lambda e: e.name.lower(),
            )
            dirs = [{"name": e.name, "path": str(e)} for e in subdirs]
        except PermissionError:
            dirs = []

        parent_path = str(path.parent) if path != path.parent else None
        return jsonify({"path": str(path), "parent": parent_path, "dirs": dirs})

    # --- Upload route ---

    @app.route("/upload", methods=["POST"])
    def upload():
        from lib import downloader
        from werkzeug.utils import secure_filename

        lib = get_lib()
        dest_dir_str = request.form.get("dest_dir", "").strip()
        confirmed = request.form.get("confirmed", "false") == "true"

        if not dest_dir_str:
            return jsonify({"ok": False, "error": "No destination directory specified."})

        dest_dir = Path(dest_dir_str).resolve()
        scan_dirs = lib.get_meta_config().get("scan_directories", [])
        within_scan = _is_within_scan_dirs(dest_dir, scan_dirs)

        if not within_scan and not confirmed:
            return jsonify({
                "ok": False,
                "outside_scan_dir": True,
                "warning": (
                    "The chosen directory is not within any configured scan directory. "
                    "Files saved here will not be automatically indexed by ScribeFTS. "
                    "Proceed anyway?"
                ),
            })

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return jsonify({"ok": False, "error": f"Cannot create directory: {e}"})

        url = request.form.get("url", "").strip()
        uploaded_file = request.files.get("file")

        if uploaded_file and uploaded_file.filename:
            safe_name = secure_filename(uploaded_file.filename)
            if not safe_name:
                return jsonify({"ok": False, "error": "Invalid filename."})
            dest_path = downloader._unique_path(dest_dir / safe_name)
            try:
                uploaded_file.save(str(dest_path))
            except OSError as e:
                return jsonify({"ok": False, "error": f"Save failed: {e}"})
        elif url:
            try:
                dest_path = downloader.download_pdf(url, dest_dir)
            except (ValueError, RuntimeError) as e:
                return jsonify({"ok": False, "error": str(e)})
        else:
            return jsonify({"ok": False, "error": "No file or URL provided."})

        filename = dest_path.name

        if within_scan:
            report = lib.refresh()
            return jsonify({
                "ok": True,
                "filename": filename,
                "new_count": len(report.new),
                "outside_scan_dir": False,
            })

        return jsonify({
            "ok": True,
            "filename": filename,
            "new_count": 0,
            "outside_scan_dir": True,
            "message": "File saved. Add its directory to scan_directories in Config to index it.",
        })

    # --- Discovery Scout routes ---

    @app.route("/discover")
    def discover():
        from lib import arxiv_client

        lib = get_lib()
        query = request.args.get("q", "").strip()
        results = []
        error = None
        if query:
            try:
                results = arxiv_client.search(query)
            except RuntimeError as e:
                error = str(e)
        return render_template("discover.html", query=query, results=results, error=error)

    @app.route("/discover/download", methods=["POST"])
    def discover_download():
        from lib import downloader

        lib = get_lib()
        pdf_url = request.form.get("pdf_url", "").strip()
        dest_dir_str = request.form.get("dest_dir", "").strip()
        confirmed = request.form.get("confirmed", "false") == "true"

        if not pdf_url or not dest_dir_str:
            return jsonify({"ok": False, "error": "Missing pdf_url or dest_dir."})

        dest_dir = Path(dest_dir_str).resolve()
        scan_dirs = lib.get_meta_config().get("scan_directories", [])
        within_scan = _is_within_scan_dirs(dest_dir, scan_dirs)

        if not within_scan and not confirmed:
            return jsonify({
                "ok": False,
                "outside_scan_dir": True,
                "warning": (
                    "The chosen directory is not within any configured scan directory. "
                    "Files saved here will not be automatically indexed by ScribeFTS. "
                    "Proceed anyway?"
                ),
            })

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = downloader.download_pdf(pdf_url, dest_dir)
        except (ValueError, RuntimeError) as e:
            return jsonify({"ok": False, "error": str(e)})

        filename = dest_path.name

        if within_scan:
            report = lib.refresh()
            return jsonify({
                "ok": True,
                "filename": filename,
                "new_count": len(report.new),
                "outside_scan_dir": False,
            })

        return jsonify({
            "ok": True,
            "filename": filename,
            "new_count": 0,
            "outside_scan_dir": True,
            "message": "File saved. Add its directory to scan_directories in Config to index it.",
        })

    # --- Tutorial route ---

    @app.route("/tutorial")
    def tutorial():
        lib = get_lib()
        scan_dirs = lib.get_meta_config().get("scan_directories", [])
        return render_template("tutorial.html", scan_dirs=scan_dirs)

    return app


def run_gui(data_dir: str | None = None, settings_path: str | None = None):
    """Create and start the Flask GUI, opening the browser automatically.

    Workspace resolution priority:
    1. Explicit settings_path argument (from --settings flag)
    2. Explicit data_dir argument
    3. Last-used path from ~/.scribefts/prefs.json
    4. None → app redirects to /workspace on first visit
    """
    from lib.settings_locator import load_last_settings_path, save_last_settings_path

    if settings_path is not None:
        p = Path(settings_path).resolve()
        resolved_data_dir = str(p.parent if p.suffix.lower() == ".json" else p)
        save_last_settings_path(Path(resolved_data_dir) / "meta_config.json")
    elif data_dir is not None:
        resolved_data_dir = data_dir
    else:
        last = load_last_settings_path()
        resolved_data_dir = str(last.parent) if last else None

    app = create_app(resolved_data_dir)

    # Auto-refresh on startup when a workspace is already configured
    if resolved_data_dir:
        with app.app_context():
            lib_instance = ScribeFTS(data_dir=resolved_data_dir)
            report = lib_instance.refresh()
            lib_instance.close()
            print(f"Initial scan: {len(report.new)} new file(s) found.")
    else:
        print("No workspace configured. Open http://localhost:5000 to set one up.")

    webbrowser.open("http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
