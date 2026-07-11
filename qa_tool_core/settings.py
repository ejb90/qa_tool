"""Framework-independent TOML settings helpers shared by QA Tool front ends."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

SETTINGS_ENV_VAR = "QA_TOOL_SETTINGS"


def deep_merge_settings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge user settings over a default settings dictionary."""
    merged = {key: value.copy() if isinstance(value, dict) else value for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_toml_file(path: Path) -> dict[str, Any]:
    """Load a TOML file into a settings dictionary."""
    with path.open("rb") as settings_file:
        return tomllib.load(settings_file)


def override_settings_path(settings_path: str | Path | None = None) -> Path | None:
    """Resolve an explicit settings path or the ``QA_TOOL_SETTINGS`` environment override."""
    if settings_path:
        return Path(settings_path)
    if environment_path := os.environ.get(SETTINGS_ENV_VAR):
        return Path(environment_path)
    return None


def load_settings(default_settings: dict[str, Any], settings_path: str | Path | None = None) -> dict[str, Any]:
    """Merge optional TOML overrides onto an already-loaded default settings dictionary."""
    override_path = override_settings_path(settings_path)
    if override_path is None:
        return default_settings
    if not override_path.exists():
        raise FileNotFoundError(f"Could not find settings file: {override_path}")
    return deep_merge_settings(default_settings, load_toml_file(override_path))
