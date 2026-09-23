# Environment: scribefts

Read by every loop iteration and by the owner. Keep it current. If you (the
agent) change how the project is built or tested, update this file in the
same commit.

## Where it runs
- Host: lightsail (pure Python + SQLite FTS5 + Flask; all tests run headless via the Flask test client, no GUI or Windows needed)
- Repo path on host: `/home/ubuntu/work/ScribeFTS`
- Loop branch: `loop/scribefts` → PRs into `main`

## Toolchain
| Tool | Version | Check |
|---|---|---|
| python | 3.10+ required by the code (README targets 3.14; proven with 3.13.13). init.sh picks the newest of python3.14 down to python3.10, then python3; override with `PYTHON=` | `.venv/bin/python -V` |
| SQLite FTS5 | bundled with CPython's sqlite3 | init.sh smoke check creates an fts5 table |
| flask | latest from PyPI (3.x) | `.venv/bin/python -c "import flask"` |
| pymupdf | latest from PyPI (1.2x) | `.venv/bin/python -c "import pymupdf"` |
| pytest | latest from PyPI (8.x) | `.venv/bin/python -m pytest --version` |
| git, jq | system | `git --version` |

## Setup
`bash .loop/init.sh`: idempotent. What it does:
- Checks `git` and a Python >= 3.10 interpreter (exit 10 if missing).
- Creates `.venv` if absent and installs `flask pymupdf pytest` (the repo has no requirements file yet; see prd T1). Reinstalls only when the dependency list or init.sh changes (stamp `.venv/.installed`).
- Creates `.loop/artifacts/`.
- Smoke check: pytest runs, flask and pymupdf import, SQLite supports FTS5.
- First run about 40 s (network install), second run about 1 s.

## Verify (what "working" means mechanically)
Same as `prd.json → verify.commands`:
- `.venv/bin/python -m pytest -q -p no:cacheprovider tests`: 124 unittest-style tests (scanner, database, metadata, FTS, extractor, API facade, Flask routes). Offline, temp dirs only. About 20 s.
- `.venv/bin/python __main__.py --help >/dev/null`: entry point and argument parsing import cleanly. Under 1 s.

## Secrets and accounts
Names only, never values. Values go in
`~/.config/loop-engineering/projects/scribefts.env` on the host (chmod 600).
| Name | Used for | Who provides |
|---|---|---|
| – | None. Optional AI extraction keys (Gemini / OpenAI) are stored by the app in `data/ai_config.json` for interactive use only; the loop never needs or sets them. | – |

## Owner-only steps (the agent can't do these)
- [ ] Ensure `python3.12` (or newer) with the `venv` module is installed on the host (`apt install python3 python3-venv`).
- [ ] `gh auth login` on the host so the loop can open draft PRs.

## Off-limits for the loop
- `data/` and `~/.scribefts/` (the owner's real catalog, config and AI API key; never read, write or commit).
- Real network calls to AI providers (Gemini/OpenAI), arXiv or URL downloads in tests or verify; mock `urllib.request.urlopen` instead.
- `LICENSE` (BSD 2-Clause), version number and release tagging (escalate tier).
- The Japanese section of README.md: keep it in sync only when the English text it mirrors changes.

## Known quirks
- `CLAUDE.md` mentions a `genv` command to activate the venv; that is the owner's Windows alias. In the loop use `.venv/bin/python` directly.
- PyMuPDF prints "The `fitz` API is deprecated" when `lib/fts.py` / `lib/extractor.py` import `fitz` (prd T3).
- `gui/app.py` opens files with `os.startfile` / `open` / `xdg-open` by platform; tests mock `_open_with_default_app`, never call it for real on the server.
- Code must stay cross-platform: the owner runs it on Windows with Windows drive-letter paths such as `C:/Users/<name>/Papers` in `data/meta_config.json`.
