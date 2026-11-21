"""Tests for shared comparison-table calculations."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from qa_tool.core.comparisons import (
    build_collection_comparison,
    build_collection_metric_deltas,
    build_model_comparison,
    build_run_scalar_comparison,
    build_version_comparison,
    percentage_difference,
    percentage_uncertainty,
)


def test_collection_comparison_includes_standard_deviations_and_percent_difference() -> None:
    """Wide comparison tables include means, standard deviations, and percentage-point uncertainty."""
    base_runs = pd.DataFrame({"model": ["h2", "h2"], "density": [10.0, 14.0]})
    test_runs = pd.DataFrame({"model": ["h2", "h2"], "density": [15.0, 21.0]})

    comparison = build_collection_comparison(base_runs, "base", test_runs, "test", ["density"])

    row = comparison.iloc[0]
    assert row["base_mean_density"] == pytest.approx(12.0)
    assert row["base_std_density"] == pytest.approx(math.sqrt(8.0))
    assert row["test_mean_density"] == pytest.approx(18.0)
    assert row["test_std_density"] == pytest.approx(math.sqrt(18.0))
    assert row["percent_difference_density"] == pytest.approx(50.0)
    assert row["percent_uncertainty_density"] == pytest.approx(100 * math.sqrt(13.0) / 12.0)


def test_model_collection_comparison_reports_percent_difference() -> None:
    """Aggregate model collection comparisons report percentage differences rather than fractions."""
    runs = pd.DataFrame(
        {
            "model": ["h2", "h2", "co2", "co2"],
            "density": [10.0, 14.0, 15.0, 21.0],
        }
    )

    comparison = build_model_comparison(runs, ["h2"], ["co2"], ["density"])

    row = comparison.iloc[0]
    assert row["base_std"] == pytest.approx(math.sqrt(8.0))
    assert row["test_std"] == pytest.approx(math.sqrt(18.0))
    assert row["percent_difference"] == pytest.approx(50.0)


@pytest.mark.parametrize("value", [0.0, float("nan")])
def test_percentage_helpers_reject_undefined_base_values(value: float) -> None:
    """Percentage calculations return no value when their denominator is undefined."""
    assert percentage_difference(value, 2.0) is None
    assert percentage_uncertainty(value, 1.0) is None


def test_long_form_and_version_comparisons_only_include_shared_models() -> None:
    """Collection deltas retain labels and omit models absent from one side."""
    runs = pd.DataFrame(
        {
            "model": ["shared", "base-only", "shared", "test-only"],
            "version": ["v1", "v1", "v2", "v2"],
            "density": [10.0, 1.0, 15.0, 2.0],
        }
    )

    wide = build_version_comparison(runs, "v1", "v2", ["density"])
    long = build_collection_metric_deltas(
        runs[runs["version"] == "v1"],
        "old",
        runs[runs["version"] == "v2"],
        "new",
        ["density"],
    )

    assert wide["model"].tolist() == ["shared"]
    assert long.loc[0, ["base_label", "test_label", "model"]].tolist() == ["old", "new", "shared"]
    assert long.loc[0, "percent_difference"] == pytest.approx(50.0)


def test_run_scalar_comparison_handles_missing_and_zero_values() -> None:
    """Run comparisons preserve values while avoiding invalid ratios and deltas."""
    comparison = build_run_scalar_comparison(
        pd.Series({"zero": 0.0, "missing": float("nan"), "normal": 2.0}),
        pd.Series({"zero": 1.0, "missing": 3.0, "normal": 6.0}),
        ["zero", "missing", "normal"],
    ).set_index("metric")

    assert pd.isna(comparison.loc["zero", "bottom_over_top"])
    assert pd.isna(comparison.loc["missing", "bottom_minus_top"])
    assert comparison.loc["normal", "bottom_minus_top"] == 4.0
    assert comparison.loc["normal", "bottom_over_top"] == 3.0
