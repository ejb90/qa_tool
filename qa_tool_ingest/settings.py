"""Settings loading for the ingestion package."""

from __future__ import annotations

import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge nested ingestion settings without losing default sections."""
    merged = {key: value.copy() if isinstance(value, dict) else value for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(path: str | Path | None = None) -> dict[str, Any]:
    """Load packaged defaults with an optional TOML override."""
    defaults = tomllib.loads(files("qa_tool_ingest").joinpath("default_settings.toml").read_text(encoding="utf-8"))
    if path is None:
        return defaults

    settings_path = Path(path)
    with settings_path.open("rb") as settings_file:
        return deep_merge(defaults, tomllib.load(settings_file))
