"""Integration tests for the Rich QA Tool command-line interface."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from qa_tool_cli.cli import main


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    """Create a small DuckDB database containing two models and two versions."""
    path = tmp_path / "runs.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE runs (
                uid VARCHAR,
                name VARCHAR,
                model VARCHAR,
                version VARCHAR,
                date TIMESTAMP,
                density DOUBLE,
                error DOUBLE,
                git_branch VARCHAR,
                modified BOOLEAN
            )
            """
        )
        connection.executemany(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("a", "a", "h2", "v1.0.0", "2026-01-01", 1.0, 0.1, "main", False),
                ("b", "b", "co2", "v1.0.0", "2026-01-01", 2.0, 0.2, "main", False),
                ("c", "c", "h2", "v2.0.0", "2026-02-01", 1.5, 0.3, "release", True),
                ("d", "d", "co2", "v2.0.0", "2026-02-01", 2.5, 0.4, "release", True),
            ],
        )
    return path


def run_cli(database_path: Path, output_dir: Path, arguments: list[str]) -> None:
    """Invoke one CLI command with the fixture database and deterministic plot directory."""
    main(
        [
            *arguments,
            "--database",
            str(database_path),
            "--output-dir",
            str(output_dir),
            "--metric",
            "density",
            "--formats",
            "html",
            "csv",
            "parquet",
        ]
    )


def test_model_command_prints_table_and_writes_plot(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The model command renders a Rich table and an interactive model plot."""
    output_dir = tmp_path / "plots"
    run_cli(database_path, output_dir, ["model", "--models", "h2", "co2"])
    assert "h2 (2 runs)" in capsys.readouterr().out
    assert (output_dir / "model_h2_density.html").exists()
    assert (output_dir / "model_co2_density.html").exists()
    assert (output_dir / "model_h2_density.csv").exists()
    assert (output_dir / "model_h2_density_table.parquet").exists()


def test_version_command_writes_version_and_cdf_plots(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The version command emits model tables plus both plots from the web view."""
    output_dir = tmp_path / "plots"
    run_cli(database_path, output_dir, ["version", "--versions", "v1.0.0", "v2.0.0", "--cdf-version", "v2.0.0"])
    assert "v2.0.0 (2 runs)" in capsys.readouterr().out
    assert (output_dir / "versions_density.html").exists()
    assert (output_dir / "version_cdf_v2.0.0_density.html").exists()
    assert (output_dir / "versions_density.csv").exists()
    assert (output_dir / "versions_density_table.csv").exists()


def test_compare_versions_writes_delta_and_cdf_plots(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Version comparison produces a shared-model table, delta plot, and CDF plot."""
    output_dir = tmp_path / "plots"
    run_cli(database_path, output_dir, ["compare", "versions", "--base-version", "v1.0.0", "--test-version", "v2.0.0"])
    assert "v2.0.0 minus v1.0.0" in capsys.readouterr().out
    assert (output_dir / "compare_versions_v1.0.0_to_v2.0.0_density.html").exists()
    assert (output_dir / "compare_versions_cdf_density.html").exists()


def test_compare_models_writes_aggregate_delta_plot(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Model collection comparison reports aggregate metric differences and a plot."""
    output_dir = tmp_path / "plots"
    run_cli(database_path, output_dir, ["compare", "models", "--base-models", "h2", "--test-models", "co2"])
    assert "Models co2 minus h2" in capsys.readouterr().out
    assert (output_dir / "compare_models_density.html").exists()


def test_compare_collections_supports_keyword_field_selection(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Collection comparison selects exact field values before rendering its outputs."""
    output_dir = tmp_path / "plots"
    run_cli(
        database_path,
        output_dir,
        ["compare", "collections", "--field", "git_branch", "--base", "main", "--test", "release"],
    )
    output = capsys.readouterr().out
    assert "density: collection git_branch (exact)" in output
    assert "test release - base main" in output
    assert (output_dir / "compare_collections_density.html").exists()
    assert (output_dir / "compare_collections_cdf_density.html").exists()


def test_terse_collection_comparison_combines_all_metrics(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Terse collection comparison prints every metric in one delta-only table without artifacts."""
    output_dir = tmp_path / "plots"
    main(
        [
            "compare",
            "collections",
            "--field",
            "git_branch",
            "--base",
            "main",
            "--test",
            "release",
            "--terse",
            "--database",
            str(database_path),
            "--output-dir",
            str(output_dir),
        ]
    )
    output = capsys.readouterr().out
    assert "Deltas: git_branch exact" in output
    assert "density" in output
    assert "error" in output
    assert "difference (%)" in output
    assert not output_dir.exists()


def test_pie_command_writes_plot(database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The pie command prints the source values and writes an interactive donut plot."""
    output_dir = tmp_path / "plots"
    run_cli(database_path, output_dir, ["pie", "--slice-by", "model"])
    assert "sum_density by model" in capsys.readouterr().out
    assert (output_dir / "pie_model_sum_density.html").exists()


def test_pie_command_defaults_to_run_counts(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting the pie metric produces run counts and one chart for every numeric metric."""
    output_dir = tmp_path / "plots"
    main(
        [
            "pie",
            "--slice-by",
            "version",
            "--database",
            str(database_path),
            "--output-dir",
            str(output_dir),
            "--formats",
            "html",
            "csv",
        ]
    )
    assert "run_count by version" in capsys.readouterr().out
    assert (output_dir / "pie_version_run_count.html").exists()
    assert (output_dir / "pie_version_sum_density.html").exists()
    assert (output_dir / "pie_version_sum_error.html").exists()


def test_model_command_defaults_to_every_numeric_metric(database_path: Path, tmp_path: Path) -> None:
    """Omitting --metric writes one model plot per available numeric variable."""
    output_dir = tmp_path / "plots"
    main(
        [
            "model",
            "--models",
            "h2",
            "--database",
            str(database_path),
            "--output-dir",
            str(output_dir),
            "--formats",
            "html",
            "csv",
        ]
    )
    assert (output_dir / "model_h2_density.html").exists()
    assert (output_dir / "model_h2_error.html").exists()


def test_artifact_paths_require_top_level_verbose(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Normal commands are quiet while top-level --verbose reports generated artifact paths."""
    quiet_output_dir = tmp_path / "quiet"
    command = [
        "model",
        "--models",
        "h2",
        "--metric",
        "density",
        "--database",
        str(database_path),
        "--output-dir",
        str(quiet_output_dir),
        "--formats",
        "html",
    ]
    main(command)
    assert capsys.readouterr().err == ""

    main(["--verbose", *command])
    assert "Wrote artifacts:" in capsys.readouterr().err
