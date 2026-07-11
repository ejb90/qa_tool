"""Tests for CLI plot, raw-data, and table artifact writing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from plotly.graph_objects import Figure
from pytest import MonkeyPatch

from qa_tool_cli.rendering import write_plot


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


def test_write_plot_preserves_tabular_artifacts_when_png_export_fails(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """CSV and Parquet artifacts remain available when the local PNG browser backend is unavailable."""

    def failing_write_image(_figure: Figure, _path: Path) -> None:
        """Simulate a missing or failed browser backend."""
        raise RuntimeError("browser unavailable")

    monkeypatch.setattr(Figure, "write_image", failing_write_image)
    dataframe = pd.DataFrame({"model": ["h2"], "density": [1.0]})

    paths = write_plot(Figure(), dataframe, dataframe, tmp_path, "model_h2_density", ["png", "csv", "parquet"])

    assert (tmp_path / "model_h2_density.csv").exists()
    assert (tmp_path / "model_h2_density_table.parquet").exists()
    assert not (tmp_path / "model_h2_density.png").exists()
    assert "model_h2_density.png" not in {path.name for path in paths}
