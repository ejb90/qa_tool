"""QA dashboard module for settings."""

from __future__ import annotations

import os
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Any

import streamlit as st

SETTINGS_ENV_VAR = "QA_TOOL_SETTINGS"
DEFAULT_SETTINGS_RESOURCE = "default_settings.toml"
PACKAGE_NAME = __package__ or "qa_tool.webapp"


def deep_merge_settings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Handle deep merge settings."""
    merged = {key: value.copy() if isinstance(value, dict) else value for key, value in base.items()}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_toml_file(path: Path) -> dict[str, Any]:
    """Handle load toml file."""
    with path.open("rb") as settings_file:
        return tomllib.load(settings_file)


def load_packaged_defaults() -> dict[str, Any]:
    """Handle load packaged defaults."""
    try:
        settings_resource = files(PACKAGE_NAME).joinpath(DEFAULT_SETTINGS_RESOURCE)
        settings_text = settings_resource.read_text(encoding="utf-8")
    except ModuleNotFoundError:
        settings_text = Path(__file__).with_name(DEFAULT_SETTINGS_RESOURCE).read_text(encoding="utf-8")
    return tomllib.loads(settings_text)


def override_settings_path(settings_path: str | Path | None = None) -> Path | None:
    """Handle override settings path."""
    if settings_path:
        return Path(settings_path)
    if env_path := os.environ.get(SETTINGS_ENV_VAR):
        return Path(env_path)
    return None


@st.cache_data(show_spinner=False)
def load_settings(settings_path: str | Path | None = None) -> dict[str, Any]:
    """Handle load settings."""
    settings = load_packaged_defaults()
    override_path = override_settings_path(settings_path)
    if override_path is None:
        return settings
    if not override_path.exists():
        raise FileNotFoundError(f"Could not find settings file: {override_path}")
    return deep_merge_settings(settings, load_toml_file(override_path))


def configured_metrics(configured: list[str], available: list[str], fallback: list[str]) -> list[str]:
    """Handle configured metrics."""
    selected = [metric for metric in configured if metric in available]
    if selected:
        return selected
    return [metric for metric in fallback if metric in available]
