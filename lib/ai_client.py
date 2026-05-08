"""HTTP-based AI API client for ScribeFTS metadata extraction.

Supports Google Gemini and OpenAI-compatible providers.
Uses only urllib.request — no additional dependencies.
All errors are caught and logged; callers receive None on any failure.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

_DEFAULT_AI_CONFIG = {
    "enabled": False,
    "provider": "gemini",
    "api_key": "",
    "model": "gemini-1.5-flash",
    "auto_commit_threshold": 0.8,
    "openai_endpoint": "https://api.openai.com/v1/chat/completions",
}


def load_ai_config(config_path: str | Path) -> dict:
    """Load ai_config.json, creating it with defaults if absent."""
    path = Path(config_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(_DEFAULT_AI_CONFIG, f, indent=2, ensure_ascii=False)
        return dict(_DEFAULT_AI_CONFIG)

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        # Fill in any missing keys from defaults
        for key, val in _DEFAULT_AI_CONFIG.items():
            data.setdefault(key, val)
        return data
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_AI_CONFIG)


def save_ai_config(config_path: str | Path, config: dict) -> None:
    """Write ai_config.json."""
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def call_ai(prompt: str, ai_config: dict) -> str | None:
    """Send prompt to the configured AI provider.

    Returns the raw text response, or None on any error.
    Callers should handle None gracefully (fall back to heuristics).
    """
    provider = ai_config.get("provider", "gemini")
    api_key = ai_config.get("api_key", "").strip()
    model = ai_config.get("model", "gemini-1.5-flash").strip()

    if not api_key:
        return None

    try:
        if provider == "gemini":
            return _call_gemini(prompt, api_key, model)
        else:
            endpoint = ai_config.get(
                "openai_endpoint", "https://api.openai.com/v1/chat/completions"
            )
            return _call_openai(prompt, api_key, model, endpoint)
    except Exception:
        return None


def _call_gemini(prompt: str, api_key: str, model: str) -> str | None:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError,
            json.JSONDecodeError, OSError):
        return None


def _call_openai(prompt: str, api_key: str, model: str, endpoint: str) -> str | None:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 256,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError,
            json.JSONDecodeError, OSError):
        return None
