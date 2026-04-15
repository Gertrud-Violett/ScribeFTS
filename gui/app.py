"""Flask-based GUI for NHI Librarian."""

import json
import os
import subprocess
import sys
import traceback
import webbrowser
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from lib.api import NHILibrarian


def _open_with_default_app(file_path: Path) -> None:
    """Open a file with the user's OS-default application."""
    if sys.platform.startswith("win"):
        os.startfile(str(file_path))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(file_path)], check=True)
        return
    subprocess.run(["xdg-open", str(file_path)], check=True)


def create_app(data_dir: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    if data_dir is None:
        data_dir = str(Path(__file__).resolve().parent.parent / "data")

    app = Flask(__name__)
    app.secret_key = "nhi-librarian-local-only"

    def get_lib() -> NHILibrarian:
        """Return a request-scoped librarian instance.

        Flask may serve requests in different threads, so the SQLite connection
        must be created and used within the same request thread.
        """
        if "lib" not in g:
            g.lib = NHILibrarian(data_dir=data_dir)
        return g.lib

    @app.teardown_appcontext
    def close_lib(exc):
        lib = g.pop("lib", None)
        if lib is not None:
            lib.close()

    @app.errorhandler(Exception)
    def log_unhandled_error(exc):
        """Log unexpected GUI errors to a file for diagnosis."""
        if isinstance(exc, HTTPException):
            return exc

        log_path = Path(data_dir) / "gui_error.log"
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
        sort_by = request.args.get("sort", "filename")
        entries = lib.list_all(sort_by=sort_by)
        return render_template("library.html", entries=entries, view_name="index", query="")

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
        return render_template("detail.html", entry=entry, fields=fields, edit_mode=False)

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
        sort_by = request.args.get("sort", "filename")
        if not query:
            return redirect(url_for("index"))
        entries = lib.search(query)
        return render_template("library.html", entries=entries, query=query, view_name="search")

    @app.route("/export", methods=["POST"])
    def do_export():
        lib = get_lib()
        out_path = str(Path(data_dir) / "library_export.json")
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

    return app


def run_gui(data_dir: str | None = None):
    """Create and start the Flask GUI, opening the browser automatically."""
    app = create_app(data_dir)

    # Auto-refresh on startup
    with app.app_context():
        lib_instance = NHILibrarian(
            data_dir=data_dir or str(Path(__file__).resolve().parent.parent / "data")
        )
        report = lib_instance.refresh()
        lib_instance.close()
        print(f"Initial scan: {len(report.new)} new file(s) found.")

    webbrowser.open("http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
