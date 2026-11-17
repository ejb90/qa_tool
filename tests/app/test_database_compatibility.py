"""App-level database compatibility tests."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

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
