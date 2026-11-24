"""App-level database compatibility tests."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from qa_tool.core.archive import create_comparison_archive
from qa_tool.webapp.app import resolve_database_path
from qa_tool.webapp.data import (
    RunFilters,
    clear_database_caches,
    count_runs,
    database_revision,
    load_run_schema,
    load_run_statistics,
    load_run_summary,
    load_runs,
)
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


def test_default_database_falls_back_to_repository_example(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repository demos work without changing the installed default database setting."""
    example_database = tmp_path / "examples" / "runs.duckdb"
    example_database.parent.mkdir()
    example_database.touch()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("qa_tool.webapp.app.EXAMPLE_DATABASE", example_database)

    assert resolve_database_path("runs.duckdb") == example_database
    live_database = tmp_path / "runs.duckdb"
    live_database.touch()
    assert resolve_database_path("runs.duckdb") == Path("runs.duckdb")
    assert resolve_database_path("custom.duckdb") == Path("custom.duckdb")


def test_manual_refresh_clears_only_stale_database_results(tmp_path: Path) -> None:
    """A manual database refresh reloads data even when the cache key is unchanged."""
    database_path = tmp_path / "runs.duckdb"
    create_runs_database(database_path)
    revision = database_revision(database_path)
    clear_database_caches()

    before = load_runs(str(database_path), "device", "release", revision, 0)
    with duckdb.connect(str(database_path)) as database:
        database.execute("UPDATE runs SET score = 9.0")
    still_cached = load_runs(str(database_path), "device", "release", revision, 0)
    clear_database_caches()
    refreshed = load_runs(str(database_path), "device", "release", revision, 0)

    assert before.loc[0, "score"] == 1.5
    assert still_cached.loc[0, "score"] == 1.5
    assert refreshed.loc[0, "score"] == 9.0


def test_promoted_database_revision_bypasses_cached_runs(tmp_path: Path) -> None:
    """An atomic current-pointer promotion loads the new immutable database."""
    first_database = tmp_path / "releases" / "first" / "runs.duckdb"
    second_database = tmp_path / "releases" / "second" / "runs.duckdb"
    first_database.parent.mkdir(parents=True)
    second_database.parent.mkdir(parents=True)
    create_runs_database(first_database)
    create_runs_database(second_database)
    with duckdb.connect(str(second_database)) as database:
        database.execute("UPDATE runs SET score = 7.5")

    current_database = tmp_path / "current.duckdb"
    current_database.symlink_to(first_database)
    first_revision = database_revision(current_database)
    first_runs = load_runs(str(current_database), "device", "release", first_revision, 0)

    next_link = tmp_path / "next.duckdb"
    next_link.symlink_to(second_database)
    next_link.replace(current_database)
    second_revision = database_revision(current_database)
    second_runs = load_runs(str(current_database), "device", "release", second_revision, 0)

    assert first_runs.loc[0, "score"] == 1.5
    assert second_runs.loc[0, "score"] == 7.5


def test_million_row_database_queries_are_projected_filtered_and_bounded(tmp_path: Path) -> None:
    """The representative large database never becomes one complete dashboard DataFrame."""
    database_path = tmp_path / "large.duckdb"
    with duckdb.connect(str(database_path)) as database:
        database.execute(
            """
            CREATE TABLE runs AS
            SELECT
                'run-' || i AS uid,
                'model-' || (i % 10) AS device,
                'v' || (i % 4) AS release,
                TIMESTAMP '2026-01-01' + i * INTERVAL 1 SECOND AS date,
                CAST(i AS DOUBLE) AS score,
                repeat('payload-', 8) AS artifact_payload
            FROM range(1000000) AS generated(i)
            """
        )
    revision = database_revision(database_path)
    filters = RunFilters(models=("model-1",), versions=("v1", "v3"))

    schema = load_run_schema(str(database_path), "device", "release", revision, 0)
    matching_rows = count_runs(str(database_path), "device", "release", revision, 0, filters)
    page = load_runs(
        str(database_path),
        "device",
        "release",
        revision,
        0,
        ("uid", "model", "version", "date", "score"),
        filters,
        250,
    )
    statistics = load_run_statistics(
        str(database_path),
        "device",
        "release",
        revision,
        0,
        filters,
        ("score",),
    )

    assert schema.metrics == ("score",)
    assert matching_rows == 100_000
    assert len(page) == 250
    assert page.columns.tolist() == ["uid", "model", "version", "date", "score"]
    assert "artifact_payload" not in page
    assert statistics["runs"] == 100_000
    assert statistics["models"] == 1


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
    assert any(button.label == "Refresh database" for button in app.button)
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
