"""Load generated run metadata into SQLite and DuckDB databases."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import cast

RUN_COLUMNS = (
    "uid",
    "name",
    "model",
    "version",
    "date",
    "modified",
    "density",
    "velocity",
    "error",
    "runtime",
    "memory_hwm",
    "artifact",
    "artifact_path",
)

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model TEXT NOT NULL,
    version TEXT NOT NULL,
    date DATETIME NOT NULL,
    modified BOOLEAN NOT NULL,
    density FLOAT NOT NULL,
    velocity FLOAT NOT NULL,
    error FLOAT NOT NULL,
    runtime FLOAT NOT NULL,
    memory_hwm FLOAT NOT NULL,
    artifact TEXT,
    artifact_path TEXT
)
"""

DUCKDB_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    uid VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    model VARCHAR NOT NULL,
    version VARCHAR NOT NULL,
    date TIMESTAMP NOT NULL,
    modified BOOLEAN NOT NULL,
    density DOUBLE NOT NULL,
    velocity DOUBLE NOT NULL,
    error DOUBLE NOT NULL,
    runtime DOUBLE NOT NULL,
    memory_hwm DOUBLE NOT NULL,
    artifact VARCHAR,
    artifact_path VARCHAR
)
"""

REQUIRED_METADATA_KEYS = frozenset(RUN_COLUMNS) - {"artifact", "artifact_path"}
SQLITE_EXTRA_COLUMNS = {
    "artifact": "TEXT",
    "artifact_path": "TEXT",
}


def metadata_paths(store_dir: Path) -> list[Path]:
    """Return all metadata files under immediate run directories."""
    return sorted(store_dir.glob("*/metadata.json"))


def parse_datetime(value: object, path: Path) -> dt.datetime:
    """Parse an ISO timestamp from a metadata value."""
    if not isinstance(value, str):
        raise TypeError(f"{path}: date must be a string")

    normalized = value.removesuffix("Z").replace("T", " ")
    try:
        return dt.datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{path}: invalid ISO datetime {value!r}") from error


def require_key(metadata: dict[str, object], key: str, path: Path) -> object:
    """Return a required metadata value with a path-aware error."""
    try:
        return metadata[key]
    except KeyError as error:
        raise KeyError(f"{path}: missing required metadata key {key!r}") from error


def row_from_metadata(path: Path) -> dict[str, object]:
    """Convert one metadata JSON file into a database row."""
    loaded_metadata = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded_metadata, dict):
        raise TypeError(f"{path}: expected a JSON object")
    metadata = cast("dict[str, object]", loaded_metadata)

    missing_keys = REQUIRED_METADATA_KEYS.difference(metadata)
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise KeyError(f"{path}: missing required metadata keys: {missing}")

    date = parse_datetime(require_key(metadata, "date", path), path)
    artifact = str(metadata.get("artifact") or path.parent)
    return {
        "uid": str(require_key(metadata, "uid", path)),
        "name": str(require_key(metadata, "name", path)),
        "model": str(require_key(metadata, "model", path)),
        "version": str(require_key(metadata, "version", path)),
        "date": date.replace(tzinfo=None).isoformat(sep=" "),
        "modified": bool(require_key(metadata, "modified", path)),
        "density": float(require_key(metadata, "density", path)),
        "velocity": float(require_key(metadata, "velocity", path)),
        "error": float(require_key(metadata, "error", path)),
        "runtime": float(require_key(metadata, "runtime", path)),
        "memory_hwm": float(require_key(metadata, "memory_hwm", path)),
        "artifact": artifact,
        "artifact_path": artifact,
    }


def load_metadata(store_dir: str | Path = "store") -> list[dict[str, object]]:
    """Load all run metadata rows from a store directory."""
    return [row_from_metadata(path) for path in metadata_paths(Path(store_dir))]


def ensure_sqlite_columns(connection: sqlite3.Connection) -> None:
    """Add artifact columns when loading into an existing SQLite table."""
    existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
    for column, column_type in SQLITE_EXTRA_COLUMNS.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE runs ADD COLUMN {column} {column_type}")


def write_sqlite(rows: Sequence[dict[str, object]], db_path: str | Path = "runs.db") -> int:
    """Upsert run rows into a SQLite database."""
    placeholders = ", ".join(f":{column}" for column in RUN_COLUMNS)
    updates = ", ".join(f"{column} = excluded.{column}" for column in RUN_COLUMNS if column != "uid")
    statement = f"""
        INSERT INTO runs ({", ".join(RUN_COLUMNS)})
        VALUES ({placeholders})
        ON CONFLICT(uid) DO UPDATE SET {updates}
    """

    with sqlite3.connect(db_path) as connection:
        connection.execute(SQLITE_SCHEMA)
        ensure_sqlite_columns(connection)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_model_version ON runs (model, version)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_version ON runs (version)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_date ON runs (date)")
        if rows:
            connection.executemany(statement, rows)
        connection.commit()

    return len(rows)


def write_duckdb(rows: Sequence[dict[str, object]], db_path: str | Path = "runs.duckdb") -> int:
    """Upsert run rows into a DuckDB database."""
    import duckdb

    values = [tuple(row[column] for column in RUN_COLUMNS) for row in rows]
    uid_values = [(row["uid"],) for row in rows]
    placeholders = ", ".join("?" for _ in RUN_COLUMNS)

    with duckdb.connect(str(db_path)) as connection:
        connection.execute(DUCKDB_SCHEMA)
        connection.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS artifact VARCHAR")
        connection.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS artifact_path VARCHAR")
        if rows:
            connection.executemany("DELETE FROM runs WHERE uid = ?", uid_values)
            connection.executemany(
                f"INSERT INTO runs ({', '.join(RUN_COLUMNS)}) VALUES ({placeholders})",
                values,
            )

    return len(rows)


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    argument_parser = argparse.ArgumentParser(
        description="Load store/*/metadata.json into SQLite and DuckDB run databases."
    )
    argument_parser.add_argument("--store-dir", default="store", help="Directory containing */metadata.json files.")
    argument_parser.add_argument("--sqlite-db", default="runs.db", help="SQLite database path to write.")
    argument_parser.add_argument("--duckdb-db", default="runs.duckdb", help="DuckDB database path to write.")
    return argument_parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the metadata loader."""
    args = parser().parse_args(argv)
    rows = load_metadata(args.store_dir)
    sqlite_count = write_sqlite(rows, args.sqlite_db)
    duckdb_count = write_duckdb(rows, args.duckdb_db)
    print(f"Loaded {len(rows)} metadata file(s).")
    print(f"Wrote {sqlite_count} row(s) to {args.sqlite_db}.")
    print(f"Wrote {duckdb_count} row(s) to {args.duckdb_db}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
