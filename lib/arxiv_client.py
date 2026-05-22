"""arXiv API client — stdlib only (urllib + ElementTree)."""

import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_ARXIV_API = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Some Windows/Python installations lack the root CA bundle needed to verify
# arxiv.org. Since this app is local-only and contacts well-known public APIs,
# we opt out of certificate verification rather than require certifi.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def search(query: str, max_results: int = 10) -> list[dict]:
    """Query arXiv and return a list of paper dicts.

    Each dict has keys: title, authors, year, abstract, pdf_url, arxiv_id.
    Raises RuntimeError on network or parse failure.
    """
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "max_results": max_results,
        "sortBy": "relevance",
    })
    url = f"{_ARXIV_API}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "ScribeFTS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            xml_bytes = resp.read()
    except Exception as exc:
        raise RuntimeError(f"arXiv request failed: {exc}") from exc

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise RuntimeError(f"arXiv response parse error: {exc}") from exc

    results = []
    for entry in root.findall("atom:entry", _NS):
        pdf_url = None
        for link in entry.findall("atom:link", _NS):
            if link.get("type") == "application/pdf" or link.get("title") == "pdf":
                pdf_url = link.get("href")
                break

        raw_id = entry.findtext("atom:id", "", _NS) or ""
        arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id

        results.append({
            "title":    _clean(entry.findtext("atom:title", "", _NS)),
            "authors":  ", ".join(
                a.findtext("atom:name", "", _NS)
                for a in entry.findall("atom:author", _NS)
            ),
            "year":     (entry.findtext("atom:published", "", _NS) or "")[:4],
            "abstract": _clean(entry.findtext("atom:summary", "", _NS)),
            "pdf_url":  pdf_url,
            "arxiv_id": arxiv_id,
        })
    return results


def _clean(text: str | None) -> str:
    return (text or "").strip().replace("\n", " ")
