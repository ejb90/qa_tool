"""Tests for CLI plot, raw-data, and table artifact writing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from plotly.graph_objects import Figure
from pytest import MonkeyPatch

from qa_tool.cli.rendering import require_png_support, write_plot


def test_require_png_support_rejects_missing_optional_dependency(monkeypatch: MonkeyPatch) -> None:
    """An explicit PNG request explains how to install the optional dependencies."""
    monkeypatch.setattr("qa_tool.cli.rendering.find_spec", lambda _name: None)

    with pytest.raises(ValueError, match=r"qa-tool\[png\]"):
        require_png_support(["png"])


def test_require_png_support_ignores_non_png_formats(monkeypatch: MonkeyPatch) -> None:
    """Standard formats do not inspect or require the optional PNG backend."""
    monkeypatch.setattr(
        "qa_tool.cli.rendering.find_spec",
        lambda _name: pytest.fail("Kaleido should not be inspected"),
    )

    require_png_support(["html", "csv", "parquet"])


def test_write_plot_writes_png_raw_data_and_table(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """PNG, CSV, and Parquet selections write plot and both adjacent dataframe artifacts."""

    def fake_write_image(_figure: Figure, path: Path) -> None:
        """Create a placeholder PNG without requiring the external image backend in this unit test."""
        path.write_bytes(b"png")

    monkeypatch.setattr(Figure, "write_image", fake_write_image)
    raw_data = pd.DataFrame({"model": ["h2"], "density": [1.0]})
    table_data = pd.DataFrame({"model": ["h2"], "mean_density": [1.0]})

    paths = write_plot(Figure(), raw_data, table_data, tmp_path, "model_h2_density", ["png", "csv", "parquet"])

    assert {path.name for path in paths} == {
        "model_h2_density.png",
        "model_h2_density.csv",
        "model_h2_density.parquet",
        "model_h2_density_table.csv",
        "model_h2_density_table.parquet",
    }


def test_write_plot_reports_failed_png_backend(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """A failed browser backend produces actionable guidance after writing tabular artifacts."""

    def failing_write_image(_figure: Figure, _path: Path) -> None:
        """Simulate a missing or failed browser backend."""
        raise RuntimeError("browser unavailable")

    monkeypatch.setattr(Figure, "write_image", failing_write_image)
    dataframe = pd.DataFrame({"model": ["h2"], "density": [1.0]})

    with pytest.raises(ValueError, match="Chrome or Chromium"):
        write_plot(Figure(), dataframe, dataframe, tmp_path, "model_h2_density", ["png", "csv", "parquet"])

    assert (tmp_path / "model_h2_density.csv").exists()
    assert (tmp_path / "model_h2_density_table.parquet").exists()
    assert not (tmp_path / "model_h2_density.png").exists()
