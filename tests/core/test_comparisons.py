"""Tests for shared comparison-table calculations."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from qa_tool.core.comparisons import build_collection_comparison, build_model_comparison


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
