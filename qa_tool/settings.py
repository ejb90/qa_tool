from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import streamlit as st


DEFAULT_SETTINGS_PATH = Path("qa_tool_settings.toml")
DEFAULT_SETTINGS = {
    "page": {
        "title": "Shock Bubble Interaction Run Database",
        "layout": "wide",
    },
    "database": {
        "path": "runs.db",
        "artifact_root": "",
    },
    "intro": {
        "description": (
            "Interactive run database for shock bubble interaction regression "
            "and quality-assurance analysis."
        ),
        "links": [
            {"label": "Manual", "url": ""},
            {"label": "Source", "url": ""},
        ],
        "show_database_path": True,
        "show_artifact_root": True,
    },
    "defaults": {
        "table_metrics": [],
    },
    "summaries": {
        "default": {
            "top": ["runs", "versions", "models", "total_runtime"],
            "metrics": ["runtime", "memory_hwm"],
            "aggregations": ["mean", "max"],
        },
        "tabs": {
            "all_runs": {},
            "versions": {
                "top": ["versions", "models", "total_runtime"],
                "metrics": ["runtime", "memory_hwm"],
                "aggregations": ["mean"],
            },
            "models": {
                "top": ["models", "versions", "total_runtime"],
                "metrics": ["density", "velocity", "error"],
                "aggregations": ["mean"],
            },
            "compare_versions": {
                "top": [],
                "metrics": [],
                "aggregations": [],
            },
            "pie_charts": {
                "top": [],
                "metrics": [],
                "aggregations": [],
            },
            "run_detail": {
                "top": [],
                "metrics": [],
                "aggregations": [],
            },
        },
    },
    "tabs": {
        "all_runs": True,
        "versions": True,
        "models": True,
        "compare_versions": True,
        "pie_charts": True,
        "run_detail": True,
    },
    "plots": {
        "height": 520,
    },
}


def deep_merge_settings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {
        key: value.copy() if isinstance(value, dict) else value
        for key, value in base.items()
    }
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


@st.cache_data(show_spinner=False)
def load_settings(settings_path: str = str(DEFAULT_SETTINGS_PATH)) -> dict[str, Any]:
    path = Path(settings_path)
    if not path.exists():
        return DEFAULT_SETTINGS
    with path.open("rb") as settings_file:
        return deep_merge_settings(DEFAULT_SETTINGS, tomllib.load(settings_file))


def configured_metrics(configured: list[str], available: list[str], fallback: list[str]) -> list[str]:
    selected = [metric for metric in configured if metric in available]
    if selected:
        return selected
    return [metric for metric in fallback if metric in available]
