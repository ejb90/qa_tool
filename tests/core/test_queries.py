"""Tests for shared query and ordering helpers."""

from __future__ import annotations

import pandas as pd
import pytest
from packaging.version import InvalidVersion

from qa_tool.core.queries import (
    aggregate_runs,
    metric_columns,
    model_mean_cdf_data,
    normalize_run_columns,
    select_collection,
)


def test_aggregate_uses_packaging_version_order() -> None:
    """Aggregate tables use Packaging rather than lexical version ordering."""
    runs = pd.DataFrame(
        {
            "uid": list("abcdef"),
            "version": ["v2.0", "v1.10", "v2.0rc1", "v1.9", "v2.0.post1", "v2.0.dev1"],
            "date": pd.date_range("2026-01-01", periods=6),
            "density": range(6),
        }
    )

    aggregate = aggregate_runs(runs, ["version"], ["density"])

    assert aggregate["version"].tolist() == [
        "v1.9",
        "v1.10",
        "v2.0.dev1",
        "v2.0rc1",
        "v2.0",
        "v2.0.post1",
    ]


def test_aggregate_raises_packaging_error_for_invalid_version() -> None:
    """Invalid labels retain Packaging's native validation behavior."""
    runs = pd.DataFrame(
        {
            "uid": ["a"],
            "version": ["release/main"],
            "date": pd.to_datetime(["2026-01-01"]),
            "density": [1.0],
        }
    )

    with pytest.raises(InvalidVersion):
        aggregate_runs(runs, ["version"], ["density"])


def test_normalize_columns_adds_name_and_rejects_invalid_schemas() -> None:
    """Configured aliases normalize cleanly and ambiguous or missing columns fail clearly."""
    source = pd.DataFrame({"uid": [1], "device": ["h2"], "release": ["v1"], "date": ["2026-01-01"], "density": [1.0]})

    normalized = normalize_run_columns(source, "device", "release")

    assert normalized.loc[0, ["uid", "name", "model", "version"]].tolist() == [1, "1", "h2", "v1"]
    assert pd.api.types.is_datetime64_any_dtype(normalized["date"])
    with pytest.raises(ValueError, match="Missing configured"):
        normalize_run_columns(source.drop(columns="device"), "device", "release")
    with pytest.raises(ValueError, match="canonical column already exists"):
        normalize_run_columns(source.assign(model="collision"), "device", "release")
    with pytest.raises(ValueError, match="required database column `uid`"):
        normalize_run_columns(source.drop(columns="uid"), "device", "release")


def test_metric_and_cdf_helpers_select_numeric_values() -> None:
    """Only result columns become metrics and CDF rows use one mean per model."""
    runs = pd.DataFrame(
        {
            "uid": [1, 2, 3],
            "model": ["a", "a", "b"],
            "version": ["v1", "v1", "v1"],
            "date": pd.date_range("2026-01-01", periods=3),
            "density": [1.0, 3.0, 6.0],
            "label": ["x", "y", "z"],
        }
    )

    assert metric_columns(runs) == ["density"]
    cdf = model_mean_cdf_data(runs, "density", "selected")
    assert cdf["value"].tolist() == [2.0, 6.0]
    assert cdf["cdf"].tolist() == [0.5, 1.0]
    assert cdf["curve"].tolist() == ["selected", "selected"]


def test_select_collection_supports_all_match_modes_and_types() -> None:
    """Collection selection covers exact, text, regex, boolean, and inclusive date filters."""
    runs = pd.DataFrame(
        {
            "branch": ["main", "release/one", None],
            "modified": pd.Series([True, False, True], dtype=bool),
            "date": pd.to_datetime(["2026-01-01 12:00", "2026-01-02 23:00", "2026-01-03"], format="mixed"),
        }
    )

    assert select_collection(runs, "branch", ["main"])["branch"].tolist() == ["main"]
    assert select_collection(runs, "branch", ["rel"], "starts-with")["branch"].tolist() == ["release/one"]
    assert select_collection(runs, "branch", ["LEASE"], "contains")["branch"].tolist() == ["release/one"]
    assert select_collection(runs, "branch", [r"^release/"], "regex")["branch"].tolist() == ["release/one"]
    assert len(select_collection(runs, "branch", [], "non-empty")) == 2
    assert len(select_collection(runs, "modified", ["yes"])) == 2
    assert len(select_collection(runs, "date", ["2026-01-01", "2026-01-02"])) == 2
    with pytest.raises(ValueError, match="Unknown collection field"):
        select_collection(runs, "missing", ["value"])
    with pytest.raises(ValueError, match="exactly two"):
        select_collection(runs, "date", ["2026-01-01"])
    with pytest.raises(ValueError, match="Invalid regular expression"):
        select_collection(runs, "branch", ["["], "regex")
