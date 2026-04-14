"""Metadata schema loading, validation, and default config generation."""

import json
from pathlib import Path


DEFAULT_CONFIG = {
    "scan_directories": ["."],
    "file_extensions": [".pdf"],
    "fields": [
        {"name": "title",    "type": "text",   "required": True,  "default": ""},
        {"name": "authors",  "type": "text",   "required": False, "default": ""},
        {"name": "genre",    "type": "choice", "required": False, "default": "", "choices": [
            "Rotordynamics", "Bearings", "Compressor", "Turbine",
            "Manufacturing", "Fluid Dynamics", "Materials", "NVH", "Other",
        ]},
        {"name": "year",     "type": "text",   "required": False, "default": ""},
        {"name": "keywords", "type": "list",   "required": False, "default": []},
        {"name": "notes",    "type": "text",   "required": False, "default": ""},
    ],
}

VALID_FIELD_TYPES = {"text", "choice", "list"}


def load_config(config_path: str) -> dict:
    """Load and validate the metadata field definitions from a JSON file."""
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    # Validate top-level keys
    if "fields" not in config:
        raise ValueError("meta_config.json missing required key: 'fields'")
    if not isinstance(config["fields"], list):
        raise ValueError("'fields' must be a list")

    # Validate each field definition
    for field in config["fields"]:
        if "name" not in field or "type" not in field:
            raise ValueError(f"Field missing 'name' or 'type': {field}")
        if field["type"] not in VALID_FIELD_TYPES:
            raise ValueError(
                f"Field '{field['name']}' has invalid type '{field['type']}'. "
                f"Must be one of: {VALID_FIELD_TYPES}"
            )
        if field["type"] == "choice" and "choices" not in field:
            raise ValueError(
                f"Field '{field['name']}' is type 'choice' but has no 'choices' list"
            )

    # Defaults for optional top-level keys
    config.setdefault("scan_directories", ["."])
    config.setdefault("file_extensions", [".pdf"])

    return config


def create_default_config(config_path: str) -> None:
    """Generate the default meta_config.json if none exists."""
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)


def validate_metadata(meta_config: dict, metadata: dict) -> list[str]:
    """Validate metadata values against the schema.

    Returns a list of error messages (empty = valid).
    """
    errors = []
    fields_by_name = {f["name"]: f for f in meta_config["fields"]}

    for field_def in meta_config["fields"]:
        name = field_def["name"]
        value = metadata.get(name)

        # Check required fields
        if field_def.get("required") and (value is None or value == "" or value == []):
            errors.append(f"Required field '{name}' is empty")
            continue

        if value is None:
            continue

        # Type-specific validation
        if field_def["type"] == "text":
            if not isinstance(value, str):
                errors.append(f"Field '{name}' must be a string")

        elif field_def["type"] == "choice":
            choices = field_def.get("choices", [])
            if value != "" and value not in choices:
                errors.append(
                    f"Field '{name}' value '{value}' not in choices: {choices}"
                )

        elif field_def["type"] == "list":
            if not isinstance(value, list):
                errors.append(f"Field '{name}' must be a list")
            elif not all(isinstance(item, str) for item in value):
                errors.append(f"Field '{name}' list items must be strings")

    return errors


def build_empty_metadata(meta_config: dict) -> dict:
    """Create a metadata dict with all default values."""
    result = {}
    for field in meta_config["fields"]:
        default = field.get("default")
        # Deep copy list defaults to avoid shared references
        if isinstance(default, list):
            result[field["name"]] = list(default)
        else:
            result[field["name"]] = default if default is not None else ""
    return result
