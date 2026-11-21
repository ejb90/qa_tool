"""End-to-end tests for JSON artifact ingestion into DuckDB."""

from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path

import duckdb
import pytest

from qa_tool.cli.cli import main as qa_tool_main
from qa_tool.ingest.core import ingest_run
from qa_tool.ingest.settings import load_settings


def write_artifact(tmp_path: Path, name: str, metadata: dict[str, object]) -> Path:
    """Create a temporary artifact directory containing metadata JSON."""
    artifact_dir = tmp_path / "artifacts" / name
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return artifact_dir


def temporary_settings(tmp_path: Path) -> dict[str, object]:
    """Return default ingestion settings targeting a temporary DuckDB file."""
    settings = load_settings()
    settings["database"]["path"] = str(tmp_path / "runs.duckdb")
    settings["summary"]["mean_columns"] = ["score", "new_metric"]
    return settings


def write_archive(tmp_path: Path, name: str, members: dict[str, bytes]) -> Path:
    """Create a compressed tar artifact with the requested member contents."""
    archive_path = tmp_path / name
    with tarfile.open(archive_path, "w:gz") as archive:
        for member_name, contents in members.items():
            member = tarfile.TarInfo(member_name)
            member.size = len(contents)
            archive.addfile(member, BytesIO(contents))
    return archive_path


def test_ingest_creates_runs_and_summary_tables(tmp_path: Path) -> None:
    """One artifact creates a typed runs row and a refreshed summary."""
    artifact_dir = write_artifact(
        tmp_path,
        "run-one",
        {
            "uid": "run-1",
            "model": "device-a",
            "version": "v1",
            "date": "2026-07-09 12:00:00",
            "score": 1.5,
            "passed": True,
            "parameters": {"grid": 128},
        },
    )
    settings = temporary_settings(tmp_path)

    result = ingest_run(artifact_dir, artifact_dir / "metadata.json", settings)
    database_path = Path(result["database"])

    assert database_path.is_file()
    assert database_path.stat().st_size > 0

    with duckdb.connect(str(database_path), read_only=True) as database:
        run_columns = {column[0] for column in database.execute("DESCRIBE runs").fetchall()}
        assert run_columns == {
            "uid",
            "model",
            "version",
            "date",
            "score",
            "passed",
            "parameters",
            "artifact",
        }
        assert database.execute(
            "SELECT uid, model, version, score, passed, parameters, artifact FROM runs"
        ).fetchone() == (
            "run-1",
            "device-a",
            "v1",
            1.5,
            True,
            '{"grid": 128}',
            str(artifact_dir),
        )
        assert database.execute(
            "SELECT run_count, model_count, version_count, mean_score FROM run_summary"
        ).fetchone() == (1, 1, 1, 1.5)


def test_ingest_appends_new_columns_and_refreshes_summary(tmp_path: Path) -> None:
    """Later artifacts extend the schema and refresh aggregate values."""
    settings = temporary_settings(tmp_path)
    first_artifact = write_artifact(
        tmp_path,
        "run-one",
        {"uid": "run-1", "model": "device-a", "version": "v1", "score": 1.5},
    )
    second_artifact = write_artifact(
        tmp_path,
        "run-two",
        {
            "uid": "run-2",
            "model": "device-b",
            "version": "v1",
            "score": 3.5,
            "new_metric": 7.0,
        },
    )

    ingest_run(first_artifact, first_artifact / "metadata.json", settings)
    result = ingest_run(second_artifact, second_artifact / "metadata.json", settings)

    with duckdb.connect(result["database"], read_only=True) as database:
        run_columns = [column[0] for column in database.execute("DESCRIBE runs").fetchall()]
        assert "new_metric" in run_columns
        assert database.execute("SELECT uid, new_metric FROM runs ORDER BY uid").fetchall() == [
            ("run-1", None),
            ("run-2", 7.0),
        ]
        assert database.execute(
            "SELECT run_count, model_count, version_count, mean_score, mean_new_metric FROM run_summary"
        ).fetchone() == (2, 2, 1, 2.5, 7.0)


def test_ingest_discovers_json_and_associates_tar_archive(tmp_path: Path) -> None:
    """A sole JSON file supplies metadata while sibling Parquet needs no JSON pointer."""
    archive_path = write_archive(
        tmp_path,
        "run-archive.tar.gz",
        {
            "results/run.json": json.dumps({"uid": "archive-1", "model": "device-a", "score": 2.5}).encode(),
            "results/history.parquet": b"parquet-placeholder",
        },
    )
    settings = temporary_settings(tmp_path)

    result = ingest_run(archive_path, None, settings)

    with duckdb.connect(result["database"], read_only=True) as database:
        assert database.execute("SELECT uid, model, score, artifact FROM runs").fetchone() == (
            "archive-1",
            "device-a",
            2.5,
            str(archive_path),
        )


def test_archive_metadata_override_resolves_member_path(tmp_path: Path) -> None:
    """An archive-relative --metadata value selects one JSON from several."""
    archive_path = write_archive(
        tmp_path,
        "several-json.tgz",
        {
            "first.json": json.dumps({"uid": "first"}).encode(),
            "nested/selected.json": json.dumps({"uid": "selected"}).encode(),
            "nested/data.parquet": b"parquet-placeholder",
        },
    )
    settings = temporary_settings(tmp_path)

    with pytest.raises(ValueError, match="multiple possible metadata JSON files"):
        ingest_run(archive_path, None, settings)

    result = ingest_run(archive_path, "nested/selected.json", settings)
    with duckdb.connect(result["database"], read_only=True) as database:
        assert database.execute("SELECT uid, artifact FROM runs").fetchone() == ("selected", str(archive_path))


def test_archive_prefers_metadata_json_over_other_json(tmp_path: Path) -> None:
    """A conventionally named metadata file wins over unrelated JSON artifacts."""
    archive_path = write_archive(
        tmp_path,
        "metadata-name.tar.gz",
        {
            "run/metadata.json": json.dumps({"uid": "metadata-run"}).encode(),
            "run/diagnostics.json": b"[]",
            "run/data.parquet": b"parquet-placeholder",
        },
    )
    settings = temporary_settings(tmp_path)

    result = ingest_run(archive_path, None, settings)

    with duckdb.connect(result["database"], read_only=True) as database:
        assert database.execute("SELECT uid FROM runs").fetchone() == ("metadata-run",)


def test_toml_settings_select_and_rename_json_keys(tmp_path: Path) -> None:
    """TOML inclusion and rename rules control the stored runs schema."""
    artifact_dir = write_artifact(
        tmp_path,
        "selected-run",
        {
            "run_identifier": "run-3",
            "device": "device-c",
            "ignored": "not stored",
            "score": 4.0,
        },
    )
    database_path = tmp_path / "selected.duckdb"
    settings_path = tmp_path / "ingest.toml"
    settings_path.write_text(
        "\n".join(
            [
                "[database]",
                f'path = "{database_path}"',
                "",
                "[input]",
                'include = ["run_identifier", "device", "score"]',
                "",
                "[input.rename]",
                'uid = "run_identifier"',
                'model = "device"',
                "",
                "[summary]",
                'distinct_columns = ["model"]',
                'mean_columns = ["score"]',
            ]
        ),
        encoding="utf-8",
    )

    result = ingest_run(artifact_dir, artifact_dir / "metadata.json", load_settings(settings_path))

    with duckdb.connect(result["database"], read_only=True) as database:
        run_columns = {column[0] for column in database.execute("DESCRIBE runs").fetchall()}
        assert run_columns == {"uid", "model", "score", "artifact"}
        assert database.execute("SELECT uid, model, score FROM runs").fetchone() == (
            "run-3",
            "device-c",
            4.0,
        )
        assert database.execute("SELECT run_count, model_count, mean_score FROM run_summary").fetchone() == (
            1,
            1,
            4.0,
        )


def test_exclude_rules_and_invalid_summary_columns(tmp_path: Path) -> None:
    """Excluded keys stay out of runs and invalid aggregates are skipped."""
    artifact_dir = write_artifact(
        tmp_path,
        "excluded-run",
        {
            "uid": "run-4",
            "model": "device-d",
            "score": 5.0,
            "label": "not numeric",
            "secret": "not stored",
        },
    )
    settings = temporary_settings(tmp_path)
    settings["input"]["exclude"] = ["secret"]
    settings["summary"]["mean_columns"] = ["score", "label", "missing"]

    result = ingest_run(artifact_dir, artifact_dir / "metadata.json", settings)

    with duckdb.connect(result["database"], read_only=True) as database:
        run_columns = {column[0] for column in database.execute("DESCRIBE runs").fetchall()}
        summary_columns = {column[0] for column in database.execute("DESCRIBE run_summary").fetchall()}
        assert "secret" not in run_columns
        assert summary_columns == {"refreshed_at", "run_count", "model_count", "mean_score"}


def test_ingest_rejects_invalid_paths_and_metadata(tmp_path: Path) -> None:
    """Input validation reports missing paths and non-object JSON documents."""
    settings = temporary_settings(tmp_path)
    missing_artifact = tmp_path / "missing"
    with pytest.raises(ValueError, match="Artifact path does not exist"):
        ingest_run(missing_artifact, missing_artifact / "metadata.json", settings)

    artifact_dir = tmp_path / "empty-artifact"
    artifact_dir.mkdir()
    with pytest.raises(ValueError, match="Metadata JSON does not exist"):
        ingest_run(artifact_dir, artifact_dir / "metadata.json", settings)

    metadata_path = artifact_dir / "metadata.json"
    metadata_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain an object"):
        ingest_run(artifact_dir, metadata_path, settings)

    archive_path = write_archive(tmp_path, "no-json.tar.gz", {"data.parquet": b"parquet-placeholder"})
    with pytest.raises(ValueError, match="does not contain a metadata JSON"):
        ingest_run(archive_path, None, settings)


def test_ingest_rejects_missing_renamed_json_key(tmp_path: Path) -> None:
    """Configured rename sources must be present in the JSON document."""
    artifact_dir = write_artifact(tmp_path, "rename-error", {"uid": "run-5"})
    settings = temporary_settings(tmp_path)
    settings["input"]["rename"] = {"model": "missing_key"}

    with pytest.raises(ValueError, match="Configured JSON key `missing_key` was not found"):
        ingest_run(artifact_dir, artifact_dir / "metadata.json", settings)


def test_unified_cli_uses_default_metadata_location(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The unified CLI ingests using default metadata.json and TOML settings."""
    artifact_dir = write_artifact(
        tmp_path,
        "cli-run",
        {"uid": "run-6", "model": "device-e", "version": "v2", "score": 6.0},
    )
    database_path = tmp_path / "cli.duckdb"
    settings_path = tmp_path / "cli.toml"
    settings_path.write_text(
        "\n".join(
            [
                "[database]",
                f'path = "{database_path}"',
                "",
                "[summary]",
                'mean_columns = ["score"]',
            ]
        ),
        encoding="utf-8",
    )
    qa_tool_main(["ingest", str(artifact_dir), "--settings", str(settings_path)])

    assert "Ingested" in capsys.readouterr().out
    with duckdb.connect(str(database_path), read_only=True) as database:
        assert database.execute("SELECT uid, score FROM runs").fetchone() == ("run-6", 6.0)


def test_unified_cli_ingests_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The generic qa-tool entry point exposes ingestion as a subcommand."""
    artifact_dir = write_artifact(tmp_path, "unified-run", {"uid": "run-unified", "score": 8.0})
    database_path = tmp_path / "unified.duckdb"

    qa_tool_main(["ingest", str(artifact_dir), "--database", str(database_path)])

    assert "Ingested run" in capsys.readouterr().out
    with duckdb.connect(str(database_path), read_only=True) as database:
        assert database.execute("SELECT uid, score FROM runs").fetchone() == ("run-unified", 8.0)


def test_unified_cli_ingests_tar_gz(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI accepts a tar.gz artifact and discovers nested metadata.json."""
    archive_path = write_archive(
        tmp_path,
        "cli-run.tar.gz",
        {
            "cli-run/metadata.json": json.dumps({"uid": "archive-cli", "score": 9.0}).encode(),
            "cli-run/data.parquet": b"parquet-placeholder",
        },
    )
    database_path = tmp_path / "archive-cli.duckdb"

    qa_tool_main(["ingest", str(archive_path), "--database", str(database_path)])

    assert "Ingested run" in capsys.readouterr().out
    with duckdb.connect(str(database_path), read_only=True) as database:
        assert database.execute("SELECT uid, score, artifact FROM runs").fetchone() == (
            "archive-cli",
            9.0,
            str(archive_path),
        )


def test_cli_database_option_overrides_toml_destination(
    tmp_path: Path,
) -> None:
    """The CLI database option takes precedence over the TOML destination."""
    artifact_dir = write_artifact(tmp_path, "override-run", {"uid": "run-7"})
    configured_database = tmp_path / "configured.duckdb"
    override_database = tmp_path / "override.duckdb"
    settings_path = tmp_path / "override.toml"
    settings_path.write_text(
        "\n".join(["[database]", f'path = "{configured_database}"']),
        encoding="utf-8",
    )
    qa_tool_main(
        [
            "ingest",
            str(artifact_dir),
            "--settings",
            str(settings_path),
            "--database",
            str(override_database),
        ]
    )

    assert override_database.is_file()
    assert not configured_database.exists()
    with duckdb.connect(str(override_database), read_only=True) as database:
        assert database.execute("SELECT uid FROM runs").fetchone() == ("run-7",)
