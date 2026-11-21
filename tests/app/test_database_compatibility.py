"""App-level database compatibility tests."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from qa_tool.core.archive import create_comparison_archive
from qa_tool.webapp.data import load_run_summary, load_runs
from qa_tool.webapp.settings import load_settings

APP_PATH = Path(__file__).resolve().parents[2] / "qa_tool" / "webapp" / "app.py"


def write_settings(tmp_path: Path, database_path: Path) -> Path:
    """Create settings that map alternative source names to app names."""
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        "\n".join(
            [
                "[database]",
                f'path = "{database_path}"',
                "",
                "[database.columns]",
                'model = "device"',
                'version = "release"',
            ]
        ),
        encoding="utf-8",
    )
    return settings_path


def create_runs_database(database_path: Path) -> None:
    """Create a minimal compatible database without optional app columns."""
    columns = "uid VARCHAR, device VARCHAR, release VARCHAR, date TIMESTAMP, score DOUBLE"
    row = ("run-1", "device-a", "v1", "2026-07-10 12:00:00", 1.5)
    with duckdb.connect(str(database_path)) as database:
        database.execute(f"CREATE TABLE runs ({columns})")
        database.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?)", row)


def create_analysis_database(database_path: Path) -> None:
    """Create enough runs to exercise each interactive analysis view."""
    columns = (
        "uid VARCHAR, name VARCHAR, device VARCHAR, release VARCHAR, date TIMESTAMP, "
        "density DOUBLE, error DOUBLE, git_branch VARCHAR, modified BOOLEAN"
    )
    rows = [
        ("a", "run-a", "h2", "v1.0", "2026-07-10", 1.0, 0.10, "main", False),
        ("b", "run-b", "co2", "v1.0", "2026-07-11", 2.0, 0.20, "main", False),
        ("c", "run-c", "h2", "v2.0", "2026-07-12", 1.5, 0.15, "release", True),
        ("d", "run-d", "co2", "v2.0", "2026-07-13", 2.5, 0.25, "release", True),
    ]
    with duckdb.connect(str(database_path)) as database:
        database.execute(f"CREATE TABLE runs ({columns})")
        database.executemany("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def run_app(monkeypatch: pytest.MonkeyPatch, settings_path: Path) -> AppTest:
    """Run the Streamlit app with isolated settings and cleared data caches."""
    load_settings.clear()
    load_runs.clear()
    load_run_summary.clear()
    monkeypatch.setenv("QA_TOOL_SETTINGS", str(settings_path))
    return AppTest.from_file(APP_PATH).run(timeout=10)


def test_app_loads_alias_columns_from_duckdb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DuckDB works with configured model/version column aliases."""
    database_path = tmp_path / "runs.duckdb"
    create_runs_database(database_path)

    app = run_app(monkeypatch, write_settings(tmp_path, database_path))
    assert not app.exception

    app.session_state["main_tabs"] = "All Runs"
    app.run(timeout=10)

    assert not app.exception
    assert len(app.dataframe) == 1
    assert app.dataframe[0].value.loc[0, "model"] == "device-a"
    assert app.dataframe[0].value.loc[0, "version"] == "v1"
    assert app.dataframe[0].value.loc[0, "name"] == "run-1"

    linked_app = AppTest.from_file(APP_PATH)
    linked_app.query_params["view"] = "all_runs"
    linked_app.run(timeout=10)

    assert not linked_app.exception
    assert linked_app.session_state["main_tabs"] == "All Runs"
    assert linked_app.query_params["view"] == ["all_runs"]


def test_app_exits_cleanly_for_a_corrupt_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A corrupt database file is reported in the UI without an app exception."""
    database_path = tmp_path / "invalid.duckdb"
    database_path.write_text("this is not a DuckDB database", encoding="utf-8")

    app = run_app(monkeypatch, write_settings(tmp_path, database_path))
    app.session_state["main_tabs"] = "All Runs"
    app.run(timeout=10)

    assert not app.exception
    assert len(app.error) == 1
    assert "Could not load database" in app.error[0].value


def test_saved_comparison_remains_available_without_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery reads the snapshot even when the original DuckDB file is absent."""
    archive_root = tmp_path / "archives"
    runs = pd.DataFrame([{"uid": "base", "model": "h2", "density": 1.0}])
    archive = create_comparison_archive(
        archive_root,
        comparison_type="runs",
        base_label="base",
        test_label="test",
        base_runs=runs,
        test_runs=runs.assign(uid="test", density=2.0),
        comparison=pd.DataFrame([{"metric": "density", "bottom_minus_top": 1.0}]),
        metrics=["density"],
    )
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        f'[database]\npath = "{tmp_path / "missing.duckdb"}"\n'
        f'[archive]\nsave_path = "{tmp_path / "saved"}"\nsearch_paths = ["{archive_root}"]\n',
        encoding="utf-8",
    )

    app = run_app(monkeypatch, settings_path)
    app.session_state["main_tabs"] = "Saved Comparisons"
    app.run(timeout=10)

    assert not app.exception
    comparison_tables = [table.value for table in app.dataframe if "bottom_minus_top" in table.value.columns]
    assert len(comparison_tables) == 1
    assert comparison_tables[0].loc[0, "bottom_minus_top"] == 1.0

    linked_app = AppTest.from_file(APP_PATH)
    linked_app.query_params["comparison"] = archive.snapshot_id
    linked_app.run(timeout=10)

    assert not linked_app.exception
    assert linked_app.session_state["main_tabs"] == "Saved Comparisons"
    assert linked_app.session_state["saved_comparison_selector"] == archive.snapshot_id
    assert linked_app.query_params["view"] == ["saved_comparisons"]
    assert linked_app.query_params["comparison"] == [archive.snapshot_id]


@pytest.mark.parametrize(
    "view",
    [
        "versions",
        "models",
        "compare_versions",
        "compare_collection",
        "compare_run",
        "pie_charts",
        "run_detail",
    ],
)
def test_analysis_views_render_without_exceptions(
    view: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every database-backed tab renders against a representative run set."""
    database_path = tmp_path / "runs.duckdb"
    create_analysis_database(database_path)
    settings_path = write_settings(tmp_path, database_path)
    load_settings.clear()
    load_runs.clear()
    load_run_summary.clear()
    monkeypatch.setenv("QA_TOOL_SETTINGS", str(settings_path))
    app = AppTest.from_file(APP_PATH)
    app.query_params["view"] = view

    app.run(timeout=15)

    assert not app.exception
    assert app.query_params["view"] == [view]
