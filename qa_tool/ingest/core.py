"""DuckDB ingestion and summary-refresh operations."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

NUMERIC_TYPE_PREFIXES = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "REAL",
)

INTEGER_TYPE_PREFIXES = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
)

FLOAT_TYPE_PREFIXES = ("FLOAT", "DOUBLE", "DECIMAL", "REAL")

TAR_ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz")


def quote_identifier(name: str) -> str:
    """Quote a DuckDB identifier from a configured or JSON-derived name."""
    escaped_name = name.replace('"', '""')
    return f'"{escaped_name}"'


def normalise_json_value(value: object) -> object:
    """Keep scalar values native and serialize structured JSON for DuckDB."""
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return value


def is_tar_archive(path: Path) -> bool:
    """Return whether a path has a supported tar archive name."""
    return path.name.lower().endswith(TAR_ARCHIVE_SUFFIXES)


def archive_metadata_member(tar: tarfile.TarFile, metadata_path: str | Path | None) -> tarfile.TarInfo:
    """Select one metadata JSON file from an open artifact archive."""
    json_members = [member for member in tar.getmembers() if member.isfile() and member.name.lower().endswith(".json")]
    if metadata_path is not None:
        requested_name = Path(metadata_path).as_posix().removeprefix("./")
        matches = [member for member in json_members if member.name.removeprefix("./") == requested_name]
        if not matches:
            raise ValueError(f"Metadata JSON was not found in archive: {requested_name}")
        if len(matches) > 1:
            raise ValueError(f"Archive contains duplicate metadata member: {requested_name}")
        return matches[0]

    metadata_members = [member for member in json_members if Path(member.name).name.lower() == "metadata.json"]
    candidates = metadata_members or json_members
    if not candidates:
        raise ValueError("Archive does not contain a metadata JSON file")
    if len(candidates) > 1:
        names = ", ".join(member.name for member in candidates)
        raise ValueError(
            f"Archive contains multiple possible metadata JSON files; use --metadata to choose one: {names}"
        )
    return candidates[0]


def read_archive_metadata(archive_path: Path, metadata_path: str | Path | None) -> dict[str, Any]:
    """Read a metadata object directly from a tar archive without extracting it."""
    try:
        with tarfile.open(archive_path) as tar:
            member = archive_metadata_member(tar, metadata_path)
            metadata_file = tar.extractfile(member)
            if metadata_file is None:
                raise ValueError(f"Could not read metadata JSON from archive: {member.name}")
            metadata = json.load(metadata_file)
    except tarfile.TarError as error:
        raise ValueError(f"Could not read tar archive: {archive_path}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid metadata JSON in archive: {archive_path}") from error

    if not isinstance(metadata, dict):
        raise ValueError("Metadata JSON must contain an object at its top level")
    return metadata


def read_directory_metadata(artifact_path: Path, metadata_path: str | Path | None) -> dict[str, Any]:
    """Read a metadata object associated with an artifact directory."""
    json_path = Path(metadata_path) if metadata_path is not None else artifact_path / "metadata.json"
    if not json_path.is_file():
        raise ValueError(f"Metadata JSON does not exist: {json_path}")
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid metadata JSON: {json_path}") from error
    if not isinstance(metadata, dict):
        raise ValueError("Metadata JSON must contain an object at its top level")
    return metadata


def metadata_row(
    artifact_dir: Path,
    metadata: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Select, rename, and normalize metadata into one runs-table row."""
    input_settings = settings["input"]
    include = list(input_settings.get("include", []))
    exclude = set(input_settings.get("exclude", []))
    rename = input_settings.get("rename", {})

    selected_keys = include or list(metadata)
    row = {
        key: normalise_json_value(metadata[key])
        for key in selected_keys
        if key in metadata and key not in exclude and metadata[key] is not None
    }
    for output_column, source_key in rename.items():
        if source_key not in metadata:
            raise ValueError(f"Configured JSON key `{source_key}` was not found")
        if metadata[source_key] is not None:
            row[output_column] = normalise_json_value(metadata[source_key])
        if output_column != source_key:
            row.pop(source_key, None)

    row[str(input_settings.get("artifact_column", "artifact"))] = str(artifact_dir)
    return row


def table_exists(connection: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    """Return whether a table exists in the current DuckDB database."""
    return bool(
        connection.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1",
            [table_name],
        ).fetchone()
    )


def table_columns(connection: duckdb.DuckDBPyConnection, table_name: str) -> dict[str, str]:
    """Return a table's columns and DuckDB types."""
    return {
        str(name): str(type_name)
        for name, type_name, *_ in connection.execute(f"DESCRIBE {quote_identifier(table_name)}").fetchall()
    }


def type_starts_with(type_name: str, prefixes: tuple[str, ...]) -> bool:
    """Return whether a DuckDB type belongs to a family of type prefixes."""
    return type_name.upper().startswith(prefixes)


def reconcile_column_type(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    column: str,
    existing_type: str,
    incoming_type: str,
) -> None:
    """Widen compatible numeric columns and reject incompatible type changes."""
    existing = existing_type.upper()
    incoming = incoming_type.upper()
    if existing == incoming:
        return

    existing_is_integer = type_starts_with(existing, INTEGER_TYPE_PREFIXES)
    incoming_is_integer = type_starts_with(incoming, INTEGER_TYPE_PREFIXES)
    existing_is_float = type_starts_with(existing, FLOAT_TYPE_PREFIXES)
    incoming_is_float = type_starts_with(incoming, FLOAT_TYPE_PREFIXES)

    if existing_is_integer and incoming_is_float:
        connection.execute(
            f"ALTER TABLE {quote_identifier(table_name)} ALTER COLUMN {quote_identifier(column)} TYPE DOUBLE"
        )
        return
    if (existing_is_integer or existing_is_float) and (incoming_is_integer or incoming_is_float):
        return

    raise ValueError(f"Column `{column}` has incompatible types: existing {existing_type}, incoming {incoming_type}")


def append_row(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    row: dict[str, Any],
) -> None:
    """Append a row, extending the runs table for newly discovered keys."""
    incoming = pd.DataFrame([row])
    connection.register("incoming_run", incoming)
    try:
        if not table_exists(connection, table_name):
            connection.execute(f"CREATE TABLE {quote_identifier(table_name)} AS SELECT * FROM incoming_run")
            return

        existing_columns = table_columns(connection, table_name)
        incoming_columns = table_columns(connection, "incoming_run")
        for column, type_name in incoming_columns.items():
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {quote_identifier(column)} {type_name}"
                )
            else:
                reconcile_column_type(
                    connection,
                    table_name,
                    column,
                    existing_columns[column],
                    type_name,
                )

        columns = ", ".join(quote_identifier(column) for column in row)
        connection.execute(f"INSERT INTO {quote_identifier(table_name)} ({columns}) SELECT {columns} FROM incoming_run")
    finally:
        connection.unregister("incoming_run")


def refresh_summary(
    connection: duckdb.DuckDBPyConnection,
    settings: dict[str, Any],
) -> None:
    """Rebuild the one-row summary table from the current runs table."""
    database_settings = settings["database"]
    summary_settings = settings["summary"]
    runs_table = str(database_settings["runs_table"])
    summary_table = str(database_settings["summary_table"])
    columns = table_columns(connection, runs_table)

    expressions = ["CURRENT_TIMESTAMP AS refreshed_at", "COUNT(*) AS run_count"]
    for column in summary_settings.get("distinct_columns", []):
        if column in columns:
            expressions.append(f"COUNT(DISTINCT {quote_identifier(column)}) AS {quote_identifier(f'{column}_count')}")
    for column in summary_settings.get("mean_columns", []):
        type_name = columns.get(column, "").upper()
        if not type_name.startswith(NUMERIC_TYPE_PREFIXES):
            continue
        expressions.append(f"AVG({quote_identifier(column)}) AS {quote_identifier(f'mean_{column}')}")

    connection.execute(
        f"CREATE OR REPLACE TABLE {quote_identifier(summary_table)} AS "
        f"SELECT {', '.join(expressions)} FROM {quote_identifier(runs_table)}"
    )


def ingest_run(
    artifact_dir: str | Path,
    metadata_path: str | Path | None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Append metadata from an artifact directory or tar archive and refresh summaries."""
    artifact_path = Path(artifact_dir)
    if artifact_path.is_dir():
        metadata = read_directory_metadata(artifact_path, metadata_path)
    elif artifact_path.is_file() and is_tar_archive(artifact_path):
        metadata = read_archive_metadata(artifact_path, metadata_path)
    elif artifact_path.is_file():
        raise ValueError(f"Artifact file must be a .tar, .tar.gz, or .tgz archive: {artifact_path}")
    else:
        raise ValueError(f"Artifact path does not exist: {artifact_path}")

    row = metadata_row(artifact_path, metadata, settings)
    database_settings = settings["database"]
    database_path = Path(database_settings["path"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        append_row(connection, str(database_settings["runs_table"]), row)
        refresh_summary(connection, settings)

    return {
        "database": str(database_path),
        "runs_table": database_settings["runs_table"],
        "summary_table": database_settings["summary_table"],
        "columns": list(row),
    }
