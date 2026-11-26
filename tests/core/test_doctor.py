"""Tests for read-only database inspection."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from qa_tool.core.doctor import inspect_database
from qa_tool.ingest.core import ingest_run
from qa_tool.ingest.settings import load_settings


def dashboard_settings(model: str = "model", version: str = "version") -> dict[str, object]:
    """Return the dashboard settings relevant to database inspection."""
    return {"database": {"columns": {"model": model, "version": version}}}


def healthy_database(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    """Create a database entirely through the supported ingestion path."""
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "metadata.json").write_text(
        json.dumps(
            {
                "uid": "run-1",
                "model": "device-a",
                "version": "v1",
                "date": "2026-11-26T12:00:00Z",
                "score": 1.5,
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings()
    settings["database"]["path"] = str(tmp_path / "runs.duckdb")
    settings["input"]["types"]["score"] = "DOUBLE"
    settings["summary"]["mean_columns"] = ["score"]
    ingest_run(artifact, None, settings)
    return Path(settings["database"]["path"]), settings


def test_inspection_accepts_ingested_database_without_modifying_it(tmp_path: Path) -> None:
    """A valid database passes and its bytes and timestamp remain unchanged."""
    database, ingestion_settings = healthy_database(tmp_path)
    before_bytes = database.read_bytes()
    before_mtime = database.stat().st_mtime_ns

    report = inspect_database(database, dashboard_settings(), ingestion_settings)

    assert report.passed
    assert report.run_count == 1
    assert report.findings == ()
    assert report.to_dict()["status"] == "passed"
    assert database.read_bytes() == before_bytes
    assert database.stat().st_mtime_ns == before_mtime


def test_inspection_reports_contract_and_data_failures(tmp_path: Path) -> None:
    """One inspection reports mappings, types, rows, dates, and stale summaries together."""
    database = tmp_path / "runs.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE runs (uid VARCHAR, model VARCHAR, version VARCHAR, date VARCHAR, score VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
            [
                ("duplicate", "a", "v1", "not-a-date", "1.5"),
                ("duplicate", "b", "v1", "2026-11-26", "2.5"),
                ("", "c", "v1", "2026-11-26", "3.5"),
            ],
        )
        connection.execute("CREATE TABLE run_summary (run_count BIGINT)")
        connection.execute("INSERT INTO run_summary VALUES (99)")

    ingestion_settings = load_settings()
    ingestion_settings["input"]["types"]["score"] = "DOUBLE"
    report = inspect_database(database, dashboard_settings(model="device"), ingestion_settings)
    codes = {finding.code for finding in report.findings}

    assert not report.passed
    assert report.run_count == 3
    assert {
        "missing_required_values",
        "unresolved_dashboard_mapping",
        "incompatible_declared_type",
        "duplicate_uids",
        "invalid_dates",
        "missing_summary_column",
        "stale_summary",
    } <= codes


def test_inspection_reports_missing_database_and_runs_table(tmp_path: Path) -> None:
    """Missing files and missing configured tables produce structured findings."""
    ingestion_settings = load_settings()
    missing = inspect_database(tmp_path / "missing.duckdb", dashboard_settings(), ingestion_settings)
    assert [finding.code for finding in missing.findings] == ["missing_database"]

    database = tmp_path / "empty.duckdb"
    with duckdb.connect(str(database)):
        pass
    empty = inspect_database(database, dashboard_settings(), ingestion_settings)
    assert [finding.code for finding in empty.findings] == ["missing_runs_table"]
