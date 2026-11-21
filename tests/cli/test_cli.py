"""Integration tests for the Rich QA Tool command-line interface."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from qa_tool.cli.cli import main


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
            "--format",
            "html",
            "--format",
            "csv",
            "--format",
            "parquet",
        ]
    )


def test_root_help_lists_unified_commands(capsys: pytest.CaptureFixture[str]) -> None:
    """The generic entry point advertises ingestion, serving, and analysis commands."""
    main(["--help"])

    output = capsys.readouterr().out
    for command in ("ingest", "serve", "report", "compare", "archive"):
        assert command in output


@pytest.mark.parametrize("removed_command", ["webapp", "model", "version", "pie"])
def test_removed_top_level_commands_have_no_legacy_alias(removed_command: str) -> None:
    """The reorganized CLI exposes only the new command vocabulary."""
    with pytest.raises(SystemExit, match="2"):
        main([removed_command, "--help"])


def test_serve_forwards_settings_and_streamlit_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The serve command separates Streamlit and application arguments."""
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text("[page]\ntitle = 'Test'\n", encoding="utf-8")
    captured_arguments: list[str] = []

    def fake_launch(arguments: list[str]) -> int:
        captured_arguments.extend(arguments)
        return 0

    monkeypatch.setattr("qa_tool.cli.cli.launch_webapp", fake_launch)

    main(["serve", "--settings", str(settings_path), "--", "--server.port=8600"])

    assert captured_arguments == ["--server.port=8600", "--", "--settings", str(settings_path)]


def test_default_formats_do_not_require_png_dependencies(database_path: Path, tmp_path: Path) -> None:
    """A standard CLI invocation defaults to formats supported by the base installation."""
    output_dir = tmp_path / "default-formats"
    main(
        [
            "report",
            "models",
            "h2",
            "--database",
            str(database_path),
            "--output-dir",
            str(output_dir),
            "--metric",
            "density",
        ]
    )

    assert (output_dir / "model_h2_density.html").exists()
    assert (output_dir / "model_h2_density.csv").exists()
    assert (output_dir / "model_h2_density.parquet").exists()
    assert not (output_dir / "model_h2_density.png").exists()


def test_png_request_reports_missing_optional_dependencies(
    database_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit PNG request fails early with installation instructions."""
    monkeypatch.setattr("qa_tool.cli.rendering.find_spec", lambda _name: None)

    with pytest.raises(SystemExit, match="1"):
        main(
            [
                "report",
                "models",
                "h2",
                "--database",
                str(database_path),
                "--output-dir",
                str(tmp_path),
                "--format",
                "png",
            ]
        )

    captured = capsys.readouterr()
    assert "qa-tool[png]" in captured.out + captured.err


def test_models_report_prints_table_and_writes_plot(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The models report renders a Rich table and interactive model plots."""
    output_dir = tmp_path / "plots"
    run_cli(database_path, output_dir, ["report", "models", "h2", "co2"])
    assert "h2 (2 runs)" in capsys.readouterr().out
    assert (output_dir / "model_h2_density.html").exists()
    assert (output_dir / "model_co2_density.html").exists()
    assert (output_dir / "model_h2_density.csv").exists()
    assert (output_dir / "model_h2_density_table.parquet").exists()


def test_versions_report_writes_version_and_cdf_plots(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The versions report emits model tables plus both plots from the web view."""
    output_dir = tmp_path / "plots"
    run_cli(
        database_path,
        output_dir,
        ["report", "versions", "v1.0.0", "v2.0.0", "--cdf-version", "v2.0.0"],
    )
    assert "v2.0.0 (2 runs)" in capsys.readouterr().out
    assert (output_dir / "versions_density.html").exists()
    assert (output_dir / "version_cdf_v2.0.0_density.html").exists()
    assert (output_dir / "versions_density.csv").exists()
    assert (output_dir / "versions_density_table.csv").exists()


def test_compare_versions_writes_recoverable_snapshot(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Version comparison records inputs, results, and a standalone report together."""
    archive_dir = tmp_path / "archive"
    main(
        [
            "compare",
            "versions",
            "v1.0.0",
            "v2.0.0",
            "--database",
            str(database_path),
            "--archive-dir",
            str(archive_dir),
            "--metric",
            "density",
        ]
    )
    assert "Saved comparison" in capsys.readouterr().out
    snapshot = next(archive_dir.iterdir())
    assert (snapshot / "manifest.json").exists()
    assert (snapshot / "runs.parquet").exists()
    assert (snapshot / "comparison.parquet").exists()
    assert (snapshot / "report.html").exists()
    assert (snapshot / "checksums.sha256").exists()


def test_compare_models_writes_snapshot(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Model collection comparison reports differences and saves the full inputs."""
    archive_dir = tmp_path / "archive"
    main(
        [
            "compare",
            "models",
            "--base",
            "h2",
            "--test",
            "co2",
            "--database",
            str(database_path),
            "--archive-dir",
            str(archive_dir),
            "--metric",
            "density",
        ]
    )
    assert "Models co2 minus h2" in capsys.readouterr().out
    assert len(list(archive_dir.glob("*/manifest.json"))) == 1


def test_compare_models_rejects_empty_selections(database_path: Path, tmp_path: Path) -> None:
    """Unknown model groups fail without writing a meaningless NaN snapshot."""
    with pytest.raises(SystemExit, match="1"):
        main(
            [
                "compare",
                "models",
                "--base",
                "unknown",
                "--test",
                "co2",
                "--database",
                str(database_path),
                "--archive-dir",
                str(tmp_path / "archive"),
            ]
        )

    assert not (tmp_path / "archive").exists()


def test_compare_collections_supports_keyword_field_selection(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Collection comparison selects exact field values before rendering its outputs."""
    archive_dir = tmp_path / "archive"
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
            "--database",
            str(database_path),
            "--archive-dir",
            str(archive_dir),
            "--metric",
            "density",
        ],
    )
    output = capsys.readouterr().out
    assert "release minus main" in output
    assert "Saved comparison" in output
    assert len(list(archive_dir.glob("*/comparison.csv"))) == 1


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
        ]
    )
    output = capsys.readouterr().out
    assert "Deltas: git_branch exact" in output
    assert "density" in output
    assert "error" in output
    assert "difference (%)" in output
    assert not output_dir.exists()


def test_compare_runs_and_archive_commands(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run snapshots can be listed, verified, shown, and recovered as HTML."""
    archive_dir = tmp_path / "archive"
    main(
        [
            "compare",
            "runs",
            "a",
            "c",
            "--database",
            str(database_path),
            "--archive-dir",
            str(archive_dir),
            "--metric",
            "density",
        ]
    )
    snapshot_dir = next(archive_dir.iterdir())
    snapshot_id = snapshot_dir.name.rsplit("_", 1)[-1]
    assert "Run c minus a" in capsys.readouterr().out

    main(["archive", "list", "--archive-dir", str(archive_dir)])
    assert snapshot_id in capsys.readouterr().out

    settings_path = tmp_path / "analysis.toml"
    settings_path.write_text(
        f'[archive]\nsearch_paths = ["{tmp_path / "missing"}", "{archive_dir}"]\n',
        encoding="utf-8",
    )
    main(["archive", "list", "--settings", str(settings_path)])
    assert snapshot_id in capsys.readouterr().out

    main(["archive", "show", snapshot_id[:6], "--archive-dir", str(archive_dir)])
    assert '"comparison_type": "runs"' in capsys.readouterr().out
    main(["archive", "verify", snapshot_id, "--archive-dir", str(archive_dir)])
    assert "Verified comparison" in capsys.readouterr().out

    report = tmp_path / "recovered.html"
    main(
        [
            "archive",
            "export",
            snapshot_id,
            "--archive-dir",
            str(archive_dir),
            "--output",
            str(report),
        ]
    )
    assert report.exists()


def test_breakdown_command_writes_plot(database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The breakdown command prints source values and writes an interactive donut plot."""
    output_dir = tmp_path / "plots"
    run_cli(database_path, output_dir, ["report", "breakdown", "--by", "model"])
    assert "sum_density by model" in capsys.readouterr().out
    assert (output_dir / "breakdown_model_sum_density.html").exists()


def test_breakdown_command_defaults_to_run_counts(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting the breakdown metric produces run counts and one chart for every numeric metric."""
    output_dir = tmp_path / "plots"
    main(
        [
            "report",
            "breakdown",
            "--by",
            "version",
            "--database",
            str(database_path),
            "--output-dir",
            str(output_dir),
            "--format",
            "html",
            "--format",
            "csv",
        ]
    )
    assert "run_count by version" in capsys.readouterr().out
    assert (output_dir / "breakdown_version_run_count.html").exists()
    assert (output_dir / "breakdown_version_sum_density.html").exists()
    assert (output_dir / "breakdown_version_sum_error.html").exists()


def test_models_report_defaults_to_every_numeric_metric(database_path: Path, tmp_path: Path) -> None:
    """Omitting --metric writes one model plot per available numeric variable."""
    output_dir = tmp_path / "plots"
    main(
        [
            "report",
            "models",
            "h2",
            "--database",
            str(database_path),
            "--output-dir",
            str(output_dir),
            "--format",
            "html",
            "--format",
            "csv",
        ]
    )
    assert (output_dir / "model_h2_density.html").exists()
    assert (output_dir / "model_h2_error.html").exists()


def test_reports_print_destination_and_verbose_paths(
    database_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Normal reports show the destination while verbose mode lists every path."""
    quiet_output_dir = tmp_path / "quiet"
    command = [
        "report",
        "models",
        "h2",
        "--metric",
        "density",
        "--database",
        str(database_path),
        "--output-dir",
        str(quiet_output_dir),
        "--format",
        "html",
    ]
    main(command)
    normal_error = capsys.readouterr().err
    assert f"Wrote {quiet_output_dir / 'model_h2_density.html'}" in normal_error

    main(["--verbose", *command])
    verbose_error = capsys.readouterr().err
    assert "Wrote files:" in verbose_error
    assert str(quiet_output_dir / "model_h2_density.html") in verbose_error
