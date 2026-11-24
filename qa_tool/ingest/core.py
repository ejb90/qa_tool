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

CONFIGURED_TYPE_ALIASES = {
    "BIGINT": "BIGINT",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "DOUBLE": "DOUBLE",
    "JSON": "JSON",
    "TIMESTAMP": "TIMESTAMP",
    "TIMESTAMPTZ": "TIMESTAMP WITH TIME ZONE",
    "VARCHAR": "VARCHAR",
}

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


def configured_column_types(settings: dict[str, Any]) -> dict[str, str]:
    """Return validated, canonical configured DuckDB column types."""
    configured = settings["input"].get("types", {})
    if not isinstance(configured, dict):
        raise ValueError("Ingestion setting `input.types` must be a table")

    validated: dict[str, str] = {}
    for column, type_name in configured.items():
        configured_name = str(type_name).upper()
        if configured_name not in CONFIGURED_TYPE_ALIASES:
            supported = ", ".join(sorted(CONFIGURED_TYPE_ALIASES))
            raise ValueError(f"Unsupported configured type for `{column}`: {type_name}. Supported types: {supported}")
        validated[str(column)] = CONFIGURED_TYPE_ALIASES[configured_name]
    return validated


def reconciled_column_type(
    column: str,
    existing_type: str,
    incoming_type: str,
    configured_type: str | None = None,
) -> str:
    """Return a compatible target type or reject an incompatible change."""
    existing = existing_type.upper()
    incoming = incoming_type.upper()
    target = configured_type or incoming

    if configured_type is not None and existing != configured_type:
        if type_starts_with(existing, INTEGER_TYPE_PREFIXES) and configured_type == "DOUBLE":
            existing = "DOUBLE"
        else:
            raise ValueError(
                f"Column `{column}` has type {existing_type}, but ingestion settings require {configured_type}"
            )

    existing_is_integer = type_starts_with(existing, INTEGER_TYPE_PREFIXES)
    target_is_integer = type_starts_with(target, INTEGER_TYPE_PREFIXES)
    existing_is_float = type_starts_with(existing, FLOAT_TYPE_PREFIXES)
    target_is_float = type_starts_with(target, FLOAT_TYPE_PREFIXES)

    if existing == target:
        return existing
    if existing_is_integer and target_is_float:
        return "DOUBLE"
    if (existing_is_integer or existing_is_float) and (target_is_integer or target_is_float):
        return existing

    raise ValueError(f"Column `{column}` has incompatible types: existing {existing_type}, incoming {incoming_type}")


def validate_incoming_type(
    connection: duckdb.DuckDBPyConnection,
    column: str,
    incoming_type: str,
    target_type: str,
) -> None:
    """Ensure an incoming non-null value can be stored without lossy coercion."""
    incoming = incoming_type.upper()
    target = target_type.upper()
    incoming_is_integer = type_starts_with(incoming, INTEGER_TYPE_PREFIXES)
    incoming_is_float = type_starts_with(incoming, FLOAT_TYPE_PREFIXES)
    target_is_integer = type_starts_with(target, INTEGER_TYPE_PREFIXES)
    target_is_float = type_starts_with(target, FLOAT_TYPE_PREFIXES)

    compatible = incoming == target
    compatible |= target_is_float and (incoming_is_integer or incoming_is_float)
    compatible |= target_is_integer and incoming_is_integer
    compatible |= target in {"DATE", "JSON", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE"} and incoming == "VARCHAR"
    if not compatible:
        raise ValueError(f"Column `{column}` cannot be stored as {target_type}; incoming type is {incoming_type}")

    cast_is_valid = connection.execute(
        f"SELECT TRY_CAST({quote_identifier(column)} AS {target}) IS NOT NULL FROM incoming_run"
    ).fetchone()
    if not cast_is_valid or not cast_is_valid[0]:
        raise ValueError(f"Column `{column}` contains a value that cannot be stored as {target_type}")


def append_row(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    row: dict[str, Any],
    configured_types: dict[str, str] | None = None,
) -> None:
    """Validate and append a row, extending the runs table when needed."""
    configured_types = configured_types or {}
    incoming = pd.DataFrame([row])
    connection.register("incoming_run", incoming)
    try:
        incoming_columns = table_columns(connection, "incoming_run")
        existing_columns = table_columns(connection, table_name) if table_exists(connection, table_name) else {}
        target_columns = {
            column: configured_types.get(column, incoming_type) for column, incoming_type in incoming_columns.items()
        }
        for column, configured_type in configured_types.items():
            target_columns.setdefault(column, configured_type)

        type_changes: dict[str, str] = {}
        for column, existing_type in existing_columns.items():
            if column in configured_types:
                target_type = reconciled_column_type(
                    column,
                    existing_type,
                    configured_types[column],
                    configured_types[column],
                )
                if target_type != existing_type.upper():
                    type_changes[column] = target_type

        for column, incoming_type in incoming_columns.items():
            target_type = target_columns[column]
            if column in existing_columns:
                target_type = reconciled_column_type(
                    column,
                    existing_columns[column],
                    incoming_type,
                    configured_types.get(column),
                )
                if target_type != existing_columns[column].upper():
                    type_changes[column] = target_type
            else:
                target_type = configured_types.get(column, incoming_type)
            target_columns[column] = target_type
            validate_incoming_type(connection, column, incoming_type, target_type)

        if not existing_columns:
            definitions = ", ".join(
                f"{quote_identifier(column)} {type_name}" for column, type_name in target_columns.items()
            )
            connection.execute(f"CREATE TABLE {quote_identifier(table_name)} ({definitions})")
        else:
            for column, type_name in target_columns.items():
                if column not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {quote_identifier(column)} {type_name}"
                    )
            for column, type_name in type_changes.items():
                connection.execute(
                    f"ALTER TABLE {quote_identifier(table_name)} "
                    f"ALTER COLUMN {quote_identifier(column)} TYPE {type_name}"
                )

        columns = ", ".join(quote_identifier(column) for column in row)
        values = ", ".join(f"CAST({quote_identifier(column)} AS {target_columns[column]})" for column in row)
        connection.execute(f"INSERT INTO {quote_identifier(table_name)} ({columns}) SELECT {values} FROM incoming_run")
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
    column_types = configured_column_types(settings)
    database_settings = settings["database"]
    database_path = Path(database_settings["path"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        connection.execute("BEGIN TRANSACTION")
        try:
            append_row(connection, str(database_settings["runs_table"]), row, column_types)
            refresh_summary(connection, settings)
        except Exception:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")

    return {
        "database": str(database_path),
        "runs_table": database_settings["runs_table"],
        "summary_table": database_settings["summary_table"],
        "columns": list(row),
    }
