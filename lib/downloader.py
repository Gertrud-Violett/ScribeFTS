"""URL-based PDF downloader — stdlib only (urllib + shutil)."""

import shutil
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

# Same rationale as arxiv_client: avoid CA-bundle issues on local installs.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def download_pdf(url: str, dest_dir: Path, filename: str | None = None) -> Path:
    """Download a PDF from url into dest_dir.

    Raises ValueError if the response is not a PDF.
    Raises RuntimeError on network failures.
    Returns the path of the saved file.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "ScribeFTS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
            first_bytes = resp.read(5)
            if not first_bytes.startswith(b"%PDF-"):
                raise ValueError(
                    f"URL did not return a PDF (first bytes: {first_bytes!r})"
                )
            if filename is None:
                filename = _derive_filename(url, resp)
            dest = _unique_path(dest_dir / filename)
            dest_dir.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(first_bytes)
                shutil.copyfileobj(resp, f)
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Download failed: {exc}") from exc
    return dest


def _derive_filename(url: str, resp) -> str:
    """Derive a safe filename from Content-Disposition or URL path."""
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        raw = cd.split("filename=")[-1].strip('"; ')
        if raw:
            return raw
    name = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    if not name:
        return "download.pdf"
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def _unique_path(dest: Path) -> Path:
    """Return dest unchanged if it doesn't exist; otherwise append _1, _2, …"""
    if not dest.exists():
        return dest
    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    for i in range(1, 1000):
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(f"Could not find a unique filename for {dest.name}")
