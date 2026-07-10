"""DuckDB ingestion and summary-refresh operations."""

from __future__ import annotations

import json
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


def quote_identifier(name: str) -> str:
    """Quote a DuckDB identifier from a configured or JSON-derived name."""
    escaped_name = name.replace('"', '""')
    return f'"{escaped_name}"'


def normalise_json_value(value: object) -> object:
    """Keep scalar values native and serialize structured JSON for DuckDB."""
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return value


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
    row = {key: normalise_json_value(metadata[key]) for key in selected_keys if key in metadata and key not in exclude}
    for output_column, source_key in rename.items():
        if source_key not in metadata:
            raise ValueError(f"Configured JSON key `{source_key}` was not found")
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
    metadata_path: str | Path,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Append one metadata JSON document and refresh DuckDB summaries."""
    artifact_path = Path(artifact_dir)
    json_path = Path(metadata_path)
    if not artifact_path.is_dir():
        raise ValueError(f"Artifact directory does not exist: {artifact_path}")
    if not json_path.is_file():
        raise ValueError(f"Metadata JSON does not exist: {json_path}")

    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("Metadata JSON must contain an object at its top level")

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
