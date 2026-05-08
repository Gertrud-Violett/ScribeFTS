"""3-layer metadata extraction pipeline for ScribeFTS.

Layer 1 — PDF internal metadata (highest confidence)
Layer 2 — Filename/path nomenclature heuristics
Layer 3 — First-page structural heuristics or AI assist (lowest confidence)

Each layer only fills fields that earlier layers left empty (waterfall model).
"""

import json
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path


@dataclass
class FieldDraft:
    value: str
    source: str       # 'layer1' | 'layer2' | 'layer3' | 'layer3_ai'
    confidence: float  # 0.0–1.0


@dataclass
class ExtractionResult:
    title: FieldDraft | None = None
    authors: FieldDraft | None = None
    year: FieldDraft | None = None
    keywords: FieldDraft | None = None

    def as_dict(self) -> dict[str, FieldDraft]:
        result = {}
        for name in ("title", "authors", "year", "keywords"):
            val = getattr(self, name)
            if val is not None:
                result[name] = val
        return result


# ---------------------------------------------------------------------------
# Layer 1 — PDF internal metadata
# ---------------------------------------------------------------------------

def _layer1(file_path: Path) -> ExtractionResult:
    result = ExtractionResult()
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return result

    try:
        doc = fitz.open(str(file_path))
        meta = doc.metadata or {}
        doc.close()
    except Exception:
        return result

    raw_title = (meta.get("title") or "").strip()
    if raw_title:
        result.title = FieldDraft(value=raw_title, source="layer1", confidence=0.95)

    raw_author = (meta.get("author") or "").strip()
    if raw_author:
        result.authors = FieldDraft(value=raw_author, source="layer1", confidence=0.90)

    # Parse PDF date string: "D:YYYYMMDDHHmmSS..." or plain "YYYY"
    raw_date = (meta.get("creationDate") or meta.get("modDate") or "").strip()
    year = _parse_pdf_date_year(raw_date)
    if year:
        result.year = FieldDraft(value=year, source="layer1", confidence=0.85)

    return result


def _parse_pdf_date_year(date_str: str) -> str:
    """Extract a 4-digit year from a PDF date string (e.g. 'D:20190315...')."""
    if not date_str:
        return ""
    # PDF date format: D:YYYYMMDDHHmmSS
    m = re.search(r"D:(\d{4})", date_str)
    if m:
        return m.group(1)
    # Plain 4-digit year anywhere
    m = re.search(r"\b(19|20)\d{2}\b", date_str)
    if m:
        return m.group(0)
    return ""


# ---------------------------------------------------------------------------
# Layer 2 — Nomenclature (filename + parent folder)
# ---------------------------------------------------------------------------

def _layer2(file_path: Path, existing: ExtractionResult) -> ExtractionResult:
    stem = file_path.stem  # filename without extension
    parent = file_path.parent.name

    # Year: first 4-digit year in stem (and parent if needed)
    if existing.year is None:
        year = _find_year_in_text(stem) or _find_year_in_text(parent)
        if year:
            existing.year = FieldDraft(value=year, source="layer2", confidence=0.70)

    # Authors: extract before the year token or before underscores
    if existing.authors is None:
        authors = _extract_authors_from_filename(stem)
        if authors:
            existing.authors = FieldDraft(value=authors, source="layer2", confidence=0.50)

    # Keywords: parent folder name (if distinct from "." or root markers)
    if existing.keywords is None and parent and parent not in {".", "", "data", "docs"}:
        existing.keywords = FieldDraft(
            value=parent, source="layer2", confidence=0.40
        )

    return existing


def _find_year_in_text(text: str) -> str:
    m = re.search(r"\b(19|20)\d{2}\b", text)
    return m.group(0) if m else ""


def _extract_authors_from_filename(stem: str) -> str:
    """Attempt to extract an author token from filename stem.

    Handles patterns like:
      Smith2023_Title, Smith_Jones_2023_Title, Smith_et_al_2019
    Returns a best-guess author string or empty string.
    """
    # Remove year tokens and common separators to isolate name parts
    cleaned = re.sub(r"\b(19|20)\d{2}\b", " ", stem)
    cleaned = re.sub(r"[_\-]+", " ", cleaned).strip()

    # Split on spaces, keep tokens that look like Capitalized words (names)
    tokens = cleaned.split()
    name_tokens = [t for t in tokens if re.match(r"^[A-Z][a-z]{1,}", t)]

    if not name_tokens:
        return ""

    # Heuristic: take first 1–3 name tokens before a likely title word
    # A "title word" tends to be longer or lowercase-starting
    authors = []
    for tok in name_tokens[:3]:
        if len(tok) > 12:
            break  # probably a title word, stop
        authors.append(tok)

    return ", ".join(authors) if authors else ""


# ---------------------------------------------------------------------------
# Layer 3 — Structural heuristics (first-page text)
# ---------------------------------------------------------------------------

def _layer3_heuristic(file_path: Path, existing: ExtractionResult) -> ExtractionResult:
    text = _get_first_page_text(file_path)
    if not text:
        return existing

    # Year
    if existing.year is None:
        year = _find_year_in_text(text[:500])
        if year:
            existing.year = FieldDraft(value=year, source="layer3", confidence=0.50)

    # Authors: lines that look like "Lastname, F." or "F. Lastname" in first 400 chars
    if existing.authors is None:
        authors = _extract_authors_from_text(text[:400])
        if authors:
            existing.authors = FieldDraft(value=authors, source="layer3", confidence=0.45)

    # Title: first short non-empty line in the page (heuristic only)
    if existing.title is None:
        title = _extract_title_from_text(text[:600])
        if title:
            existing.title = FieldDraft(value=title, source="layer3", confidence=0.40)

    return existing


def _layer3_ai(
    file_path: Path, existing: ExtractionResult, ai_config: dict
) -> ExtractionResult:
    """Use AI to fill remaining empty fields from first-page text."""
    from lib.ai_client import call_ai

    text = _get_first_page_text(file_path)
    if not text:
        return existing

    prompt = (
        "Extract the Title, Authors, and Publication Year from this text in JSON format.\n"
        'Return ONLY a JSON object like: {"title": "...", "authors": "...", "year": "YYYY"}\n\n'
        + text[:3000]
    )

    raw_response = call_ai(prompt, ai_config)
    if not raw_response:
        return _layer3_heuristic(file_path, existing)

    parsed = _parse_ai_json(raw_response)
    if not parsed:
        return _layer3_heuristic(file_path, existing)

    if existing.title is None:
        title = str(parsed.get("title") or "").strip()
        if title:
            existing.title = FieldDraft(value=title, source="layer3_ai", confidence=0.75)

    if existing.authors is None:
        authors = str(parsed.get("authors") or "").strip()
        if authors:
            existing.authors = FieldDraft(value=authors, source="layer3_ai", confidence=0.75)

    if existing.year is None:
        year = str(parsed.get("year") or "").strip()
        year_clean = _find_year_in_text(year) if year else ""
        if year_clean:
            existing.year = FieldDraft(value=year_clean, source="layer3_ai", confidence=0.75)

    return existing


def _get_first_page_text(file_path: Path) -> str:
    try:
        import fitz
        doc = fitz.open(str(file_path))
        text = doc[0].get_text() if len(doc) > 0 else ""
        doc.close()
        return text
    except Exception:
        return ""


def _extract_authors_from_text(text: str) -> str:
    """Heuristic: find lines that look like author names."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidates = []
    for line in lines[:20]:
        # Matches "Lastname, F." / "F. Lastname" / "Lastname and Lastname"
        if re.search(r"\b[A-Z][a-z]+,\s+[A-Z]\.?|\b[A-Z]\.\s+[A-Z][a-z]+", line):
            if len(line) < 120:
                candidates.append(line)
        if len(candidates) >= 2:
            break
    return "; ".join(candidates) if candidates else ""


def _extract_title_from_text(text: str) -> str:
    """Heuristic: first short, non-trivial line is likely the title."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines[:10]:
        if 10 < len(line) < 120 and not line.startswith(("http", "www", "©", "doi")):
            return line
    return ""


def _parse_ai_json(raw: str) -> dict | None:
    """Strip markdown fences and parse JSON from AI response."""
    # Remove ```json ... ``` fences
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    # Try to find a {...} block in the response
    m = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_metadata(
    file_path: str | Path,
    current_metadata: dict | None = None,
    ai_config: dict | None = None,
) -> ExtractionResult:
    """Run the 3-layer extraction pipeline.

    Only fills fields that are absent or empty in current_metadata.
    Returns an ExtractionResult; any field may be None if no layer found a value.
    """
    file_path = Path(file_path)
    current = current_metadata or {}

    # Determine which fields are already populated in the database.
    # We use a sentinel FieldDraft to mark them as "occupied" so that
    # layers 2 and 3 won't overwrite them.
    _SKIP = FieldDraft(value="", source="skip", confidence=0.0)

    def _kw_populated(kw) -> bool:
        if not kw:
            return False
        if isinstance(kw, str):
            try:
                kw = json.loads(kw)
            except (json.JSONDecodeError, ValueError):
                pass
        return bool(kw) and kw not in ([], "[]")

    # Start with Layer 1
    result = _layer1(file_path)

    # Mark fields already populated in the database so no layer overwrites them.
    if current.get("title", "").strip():
        result.title = _SKIP
    if current.get("authors", "").strip():
        result.authors = _SKIP
    if current.get("year", "").strip():
        result.year = _SKIP
    if _kw_populated(current.get("keywords")):
        result.keywords = _SKIP

    # Layer 2 — fills whatever Layer 1 left empty
    result = _layer2(file_path, result)

    # Layer 3 — AI or heuristic
    if ai_config and ai_config.get("enabled") and ai_config.get("api_key", "").strip():
        result = _layer3_ai(file_path, result, ai_config)
    else:
        result = _layer3_heuristic(file_path, result)

    # Remove sentinels so callers only see genuinely extracted fields.
    for attr in ("title", "authors", "year", "keywords"):
        fd = getattr(result, attr)
        if fd is not None and fd.source == "skip":
            setattr(result, attr, None)

    return result
