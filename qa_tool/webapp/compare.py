"""Web-app adapters and presentation helpers for shared comparison calculations."""

from __future__ import annotations

import pandas as pd

from qa_tool.core.comparisons import (
    build_collection_comparison as core_build_collection_comparison,
)
from qa_tool.core.comparisons import (
    build_collection_metric_deltas as core_build_collection_metric_deltas,
)
from qa_tool.core.comparisons import build_run_scalar_comparison as core_build_run_scalar_comparison
from qa_tool.core.comparisons import (
    build_version_comparison as core_build_version_comparison,
)
from qa_tool.webapp.exports import export_name


def build_version_comparison(
    filtered: pd.DataFrame,
    base_version: str,
    new_version: str,
    metrics: list[str],
) -> pd.DataFrame:
    """Preserve the web-app API while delegating version comparison to the core package."""
    return core_build_version_comparison(filtered, base_version, new_version, metrics)


def build_collection_comparison(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    metrics: list[str],
) -> pd.DataFrame:
    """Delegate collection comparisons to the shared core package."""
    return core_build_collection_comparison(base_runs, base_label, test_runs, test_label, metrics)


def build_collection_metric_deltas(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    metrics: list[str],
) -> pd.DataFrame:
    """Delegate long-form collection metric deltas to the shared core package."""
    return core_build_collection_metric_deltas(base_runs, base_label, test_runs, test_label, metrics)


def comparison_metadata(
    base_label: str,
    test_label: str,
    base_runs: pd.DataFrame,
    test_runs: pd.DataFrame,
) -> pd.DataFrame:
    """Return descriptive counts for a pair of run collections."""
    return pd.DataFrame(
        [
            {"item": "base_label", "value": base_label},
            {"item": "test_label", "value": test_label},
            {"item": "base_run_count", "value": len(base_runs)},
            {"item": "test_run_count", "value": len(test_runs)},
            {"item": "base_model_count", "value": base_runs["model"].nunique()},
            {"item": "test_model_count", "value": test_runs["model"].nunique()},
        ]
    )


def comparison_coverage(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
) -> pd.DataFrame:
    """Report which models occur in each of two compared collections."""
    base_models = set(base_runs["model"].dropna().astype(str))
    test_models = set(test_runs["model"].dropna().astype(str))
    rows = []
    for model in sorted(base_models | test_models):
        in_base = model in base_models
        in_test = model in test_models
        status = "shared" if in_base and in_test else f"only_{export_name(base_label if in_base else test_label)}"
        rows.append({"model": model, "in_base": in_base, "in_test": in_test, "status": status})
    return pd.DataFrame(rows)


def build_run_scalar_comparison(top_run: pd.Series, bottom_run: pd.Series, metrics: list[str]) -> pd.DataFrame:
    """Delegate scalar run comparisons to the shared core package."""
    return core_build_run_scalar_comparison(top_run, bottom_run, metrics)
