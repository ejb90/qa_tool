"""Compare SQLite and DuckDB performance for dashboard-style run queries."""

from __future__ import annotations

import argparse
import csv
import random
import sqlite3
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from qa_tool.load_dummy_data import load_metadata, write_duckdb, write_sqlite

QueryParams = tuple[object, ...]
DEFAULT_SIZES = [10, 100, 1_000, 10_000, 100_000, 1_000_000]
MODEL_NAMES = np.array(
    [
        "He",
        "Ne",
        "Ar",
        "Kr",
        "Xe",
        "Rn",
        "H2",
        "N2",
        "O2",
        "F2",
        "Cl2",
        "CO",
        "CO2",
        "NO",
        "NO2",
        "N2O",
        "SO2",
        "H2S",
        "NH3",
        "CH4",
        "C2H2",
        "C2H4",
        "C2H6",
        "C3H8",
        "C4H10",
        "SF6",
        "CF4",
    ],
    dtype=object,
)
STRING_METADATA_COLUMNS = (
    "git_commit",
    "git_branch",
    "git_tag",
    "code_version",
    "compiler",
    "compiler_version",
    "mpi_version",
    "scheduler",
    "queue",
    "partition",
    "hpc_system",
    "node_type",
    "job_name",
    "job_id",
    "user_name",
    "project",
    "container_image",
    "os_image",
    "input_deck",
    "mesh_id",
)
SCALAR_METADATA_COLUMNS = tuple(f"scalar_{index:02d}" for index in range(1, 31))


@dataclass(frozen=True)
class Query:
    """A benchmark query with equivalent SQLite and DuckDB SQL."""

    name: str
    description: str
    sqlite_sql: str
    duckdb_sql: str
    params: QueryParams = ()


@dataclass(frozen=True)
class QueryResult:
    """Timing result for one query on both engines."""

    name: str
    description: str
    sqlite_ms: float
    duckdb_ms: float
    sqlite_rows: int
    duckdb_rows: int

    @property
    def speedup(self) -> float | None:
        """Return the SQLite/DuckDB timing ratio."""
        if self.duckdb_ms == 0:
            return None
        return self.sqlite_ms / self.duckdb_ms


@dataclass(frozen=True)
class ScaledQueryResult:
    """Timing result for one query at one database size."""

    database_rows: int
    result: QueryResult


@dataclass(frozen=True)
class SampleContext:
    """Representative values selected from the benchmark database."""

    model: str
    versions: tuple[str, ...]
    base_version: str
    new_version: str
    start_date: str
    end_date: str
    uid: str


def scalar_sqlite(connection: sqlite3.Connection, sql: str, params: QueryParams = ()) -> object:
    """Fetch the first column from the first SQLite row."""
    row = connection.execute(sql, params).fetchone()
    if row is None:
        raise RuntimeError(f"Query returned no rows: {sql}")
    return row[0]


def build_sample_context(connection: sqlite3.Connection) -> SampleContext:
    """Choose representative filter values from the SQLite database."""
    row_count = scalar_sqlite(connection, "SELECT count(*) FROM runs")
    if not isinstance(row_count, int) or row_count == 0:
        raise RuntimeError("The runs table is empty.")

    model = str(
        scalar_sqlite(
            connection,
            """
            SELECT model
            FROM runs
            GROUP BY model
            ORDER BY count(*) DESC, model
            LIMIT 1
            """,
        )
    )
    version_rows = connection.execute(
        """
        SELECT version
        FROM runs
        WHERE model = ?
        GROUP BY version
        ORDER BY count(*) DESC, version
        LIMIT 5
        """,
        (model,),
    ).fetchall()
    versions = tuple(str(row[0]) for row in version_rows)
    if not versions:
        raise RuntimeError("Could not find any versions in runs.")

    min_date, max_date = connection.execute("SELECT min(date), max(date) FROM runs").fetchone()
    uid = str(scalar_sqlite(connection, "SELECT uid FROM runs ORDER BY date DESC LIMIT 1"))

    base_version = versions[0]
    new_version = versions[1] if len(versions) > 1 else versions[0]
    return SampleContext(
        model=model,
        versions=versions,
        base_version=base_version,
        new_version=new_version,
        start_date=str(min_date),
        end_date=str(max_date),
        uid=uid,
    )


def placeholders(values: Sequence[object]) -> str:
    """Return positional SQL placeholders for an IN clause."""
    if not values:
        raise ValueError("At least one value is required.")
    return ", ".join("?" for _ in values)


def build_queries(context: SampleContext) -> list[Query]:
    """Build equivalent queries that mirror current Streamlit app workflows."""
    version_placeholders = placeholders(context.versions)
    filtered_params: QueryParams = (
        context.model,
        *context.versions,
        context.start_date,
        context.end_date,
    )

    return [
        Query(
            name="row_count",
            description="Count all runs.",
            sqlite_sql="SELECT count(*) AS run_count FROM runs",
            duckdb_sql="SELECT count(*) AS run_count FROM runs",
        ),
        Query(
            name="filter_options",
            description="Load model/version/date sidebar options.",
            sqlite_sql="""
                SELECT 'model' AS option_type, model AS option_value FROM runs GROUP BY model
                UNION ALL
                SELECT 'version' AS option_type, version AS option_value FROM runs GROUP BY version
                UNION ALL
                SELECT 'min_date' AS option_type, min(date) AS option_value FROM runs
                UNION ALL
                SELECT 'max_date' AS option_type, max(date) AS option_value FROM runs
            """,
            duckdb_sql="""
                SELECT 'model' AS option_type, model AS option_value FROM runs GROUP BY model
                UNION ALL
                SELECT 'version' AS option_type, version AS option_value FROM runs GROUP BY version
                UNION ALL
                SELECT 'min_date' AS option_type, CAST(min(date) AS VARCHAR) AS option_value FROM runs
                UNION ALL
                SELECT 'max_date' AS option_type, CAST(max(date) AS VARCHAR) AS option_value FROM runs
            """,
        ),
        Query(
            name="version_means",
            description="Versions tab: mean metrics by version.",
            sqlite_sql="""
                SELECT
                    version,
                    count(*) AS run_count,
                    avg(runtime) AS mean_runtime,
                    avg(memory_hwm) AS mean_memory_hwm,
                    avg(density) AS mean_density,
                    avg(velocity) AS mean_velocity,
                    avg(error) AS mean_error
                FROM runs
                WHERE modified = 0
                GROUP BY version
                ORDER BY version
            """,
            duckdb_sql="""
                SELECT
                    version,
                    count(*) AS run_count,
                    avg(runtime) AS mean_runtime,
                    avg(memory_hwm) AS mean_memory_hwm,
                    avg(density) AS mean_density,
                    avg(velocity) AS mean_velocity,
                    avg(error) AS mean_error
                FROM runs
                WHERE modified = false
                GROUP BY version
                ORDER BY version
            """,
        ),
        Query(
            name="model_means",
            description="Models tab: mean metrics by model.",
            sqlite_sql="""
                SELECT
                    model,
                    count(*) AS run_count,
                    avg(runtime) AS mean_runtime,
                    avg(memory_hwm) AS mean_memory_hwm,
                    avg(density) AS mean_density,
                    avg(velocity) AS mean_velocity,
                    avg(error) AS mean_error
                FROM runs
                WHERE modified = 0
                GROUP BY model
                ORDER BY model
            """,
            duckdb_sql="""
                SELECT
                    model,
                    count(*) AS run_count,
                    avg(runtime) AS mean_runtime,
                    avg(memory_hwm) AS mean_memory_hwm,
                    avg(density) AS mean_density,
                    avg(velocity) AS mean_velocity,
                    avg(error) AS mean_error
                FROM runs
                WHERE modified = false
                GROUP BY model
                ORDER BY model
            """,
        ),
        Query(
            name="filtered_summary",
            description="Summary cards after sidebar filters.",
            sqlite_sql=f"""
                SELECT
                    count(*) AS runs,
                    count(DISTINCT version) AS versions,
                    count(DISTINCT model) AS models,
                    sum(runtime) AS total_runtime,
                    avg(runtime) AS mean_runtime,
                    max(memory_hwm) AS max_memory_hwm
                FROM runs
                WHERE model = ?
                  AND version IN ({version_placeholders})
                  AND date >= ?
                  AND date <= ?
            """,
            duckdb_sql=f"""
                SELECT
                    count(*) AS runs,
                    count(DISTINCT version) AS versions,
                    count(DISTINCT model) AS models,
                    sum(runtime) AS total_runtime,
                    avg(runtime) AS mean_runtime,
                    max(memory_hwm) AS max_memory_hwm
                FROM runs
                WHERE model = ?
                  AND version IN ({version_placeholders})
                  AND date >= CAST(? AS TIMESTAMP)
                  AND date <= CAST(? AS TIMESTAMP)
            """,
            params=filtered_params,
        ),
        Query(
            name="paged_all_runs",
            description="All Runs tab: first page after filters.",
            sqlite_sql=f"""
                SELECT uid, name, model, version, date, modified, runtime, memory_hwm, artifact_path
                FROM runs
                WHERE model = ?
                  AND version IN ({version_placeholders})
                  AND date >= ?
                  AND date <= ?
                ORDER BY date DESC
                LIMIT 500
            """,
            duckdb_sql=f"""
                SELECT uid, name, model, version, date, modified, runtime, memory_hwm, artifact_path
                FROM runs
                WHERE model = ?
                  AND version IN ({version_placeholders})
                  AND date >= CAST(? AS TIMESTAMP)
                  AND date <= CAST(? AS TIMESTAMP)
                ORDER BY date DESC
                LIMIT 500
            """,
            params=filtered_params,
        ),
        Query(
            name="run_detail",
            description="Run Detail tab: lookup one run by uid.",
            sqlite_sql="SELECT * FROM runs WHERE uid = ?",
            duckdb_sql="SELECT * FROM runs WHERE uid = ?",
            params=(context.uid,),
        ),
        Query(
            name="pie_by_model",
            description="Pie chart: runtime by model.",
            sqlite_sql="""
                SELECT model, count(*) AS run_count, sum(runtime) AS total_runtime
                FROM runs
                GROUP BY model
                ORDER BY total_runtime DESC
            """,
            duckdb_sql="""
                SELECT model, count(*) AS run_count, sum(runtime) AS total_runtime
                FROM runs
                GROUP BY model
                ORDER BY total_runtime DESC
            """,
        ),
        Query(
            name="compare_versions",
            description="Compare Versions tab: per-model deltas.",
            sqlite_sql="""
                WITH version_means AS (
                    SELECT model, version, avg(runtime) AS mean_runtime, avg(error) AS mean_error
                    FROM runs
                    WHERE version IN (?, ?)
                    GROUP BY model, version
                )
                SELECT
                    base.model,
                    base.mean_runtime AS base_runtime,
                    new.mean_runtime AS new_runtime,
                    new.mean_runtime - base.mean_runtime AS runtime_delta,
                    base.mean_error AS base_error,
                    new.mean_error AS new_error,
                    new.mean_error - base.mean_error AS error_delta
                FROM version_means AS base
                JOIN version_means AS new ON base.model = new.model
                WHERE base.version = ? AND new.version = ?
                ORDER BY base.model
            """,
            duckdb_sql="""
                WITH version_means AS (
                    SELECT model, version, avg(runtime) AS mean_runtime, avg(error) AS mean_error
                    FROM runs
                    WHERE version IN (?, ?)
                    GROUP BY model, version
                )
                SELECT
                    base.model,
                    base.mean_runtime AS base_runtime,
                    new.mean_runtime AS new_runtime,
                    new.mean_runtime - base.mean_runtime AS runtime_delta,
                    base.mean_error AS base_error,
                    new.mean_error AS new_error,
                    new.mean_error - base.mean_error AS error_delta
                FROM version_means AS base
                JOIN version_means AS new ON base.model = new.model
                WHERE base.version = ? AND new.version = ?
                ORDER BY base.model
            """,
            params=(context.base_version, context.new_version, context.base_version, context.new_version),
        ),
    ]


def time_query(
    execute_query: Callable[[str, QueryParams], list[tuple[object, ...]]],
    sql: str,
    params: QueryParams,
    repeats: int,
    warmups: int,
) -> tuple[float, int]:
    """Time a query and return median milliseconds plus fetched row count."""
    for _ in range(warmups):
        execute_query(sql, params)

    durations = []
    row_count = 0
    for _ in range(repeats):
        start = time.perf_counter()
        rows = execute_query(sql, params)
        durations.append((time.perf_counter() - start) * 1000)
        row_count = len(rows)

    return statistics.median(durations), row_count


def run_benchmarks(
    sqlite_path: Path,
    duckdb_path: Path,
    repeats: int,
    warmups: int,
) -> list[QueryResult]:
    """Run all benchmark queries for SQLite and DuckDB."""
    with sqlite3.connect(sqlite_path) as sqlite_connection, duckdb.connect(str(duckdb_path)) as duckdb_connection:
        context = build_sample_context(sqlite_connection)
        queries = build_queries(context)

        def execute_sqlite(sql: str, params: QueryParams) -> list[tuple[object, ...]]:
            return sqlite_connection.execute(sql, params).fetchall()

        def execute_duckdb(sql: str, params: QueryParams) -> list[tuple[object, ...]]:
            return duckdb_connection.execute(sql, params).fetchall()

        results = []
        for query in queries:
            sqlite_ms, sqlite_rows = time_query(
                execute_sqlite,
                query.sqlite_sql,
                query.params,
                repeats,
                warmups,
            )
            duckdb_ms, duckdb_rows = time_query(
                execute_duckdb,
                query.duckdb_sql,
                query.params,
                repeats,
                warmups,
            )
            results.append(
                QueryResult(
                    name=query.name,
                    description=query.description,
                    sqlite_ms=sqlite_ms,
                    duckdb_ms=duckdb_ms,
                    sqlite_rows=sqlite_rows,
                    duckdb_rows=duckdb_rows,
                )
            )

    return results


def markdown_table(results: Sequence[QueryResult]) -> str:
    """Render benchmark results as a Markdown table."""
    lines = [
        "| Query | Rows | SQLite ms | DuckDB ms | SQLite / DuckDB | Description |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for result in results:
        speedup = "n/a" if result.speedup is None else f"{result.speedup:.2f}x"
        row_count = (
            str(result.sqlite_rows)
            if result.sqlite_rows == result.duckdb_rows
            else f"{result.sqlite_rows} / {result.duckdb_rows}"
        )
        lines.append(
            "| "
            f"`{result.name}` | "
            f"{row_count} | "
            f"{result.sqlite_ms:.3f} | "
            f"{result.duckdb_ms:.3f} | "
            f"{speedup} | "
            f"{result.description} |"
        )
    return "\n".join(lines)


def scaled_markdown_table(results: Sequence[ScaledQueryResult]) -> str:
    """Render scaled benchmark results as one Markdown table."""
    lines = [
        "| DB rows | Query | Result rows | SQLite ms | DuckDB ms | SQLite / DuckDB | Description |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for scaled_result in results:
        result = scaled_result.result
        speedup = "n/a" if result.speedup is None else f"{result.speedup:.2f}x"
        row_count = (
            str(result.sqlite_rows)
            if result.sqlite_rows == result.duckdb_rows
            else f"{result.sqlite_rows} / {result.duckdb_rows}"
        )
        lines.append(
            "| "
            f"{scaled_result.database_rows} | "
            f"`{result.name}` | "
            f"{row_count} | "
            f"{result.sqlite_ms:.3f} | "
            f"{result.duckdb_ms:.3f} | "
            f"{speedup} | "
            f"{result.description} |"
        )
    return "\n".join(lines)


def write_scaled_csv(results: Sequence[ScaledQueryResult], csv_path: Path) -> None:
    """Write scaled benchmark results as CSV."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "database_rows",
                "query",
                "result_rows_sqlite",
                "result_rows_duckdb",
                "sqlite_ms",
                "duckdb_ms",
                "sqlite_duckdb_ratio",
                "description",
            ],
        )
        writer.writeheader()
        for scaled_result in results:
            result = scaled_result.result
            writer.writerow(
                {
                    "database_rows": scaled_result.database_rows,
                    "query": result.name,
                    "result_rows_sqlite": result.sqlite_rows,
                    "result_rows_duckdb": result.duckdb_rows,
                    "sqlite_ms": f"{result.sqlite_ms:.6f}",
                    "duckdb_ms": f"{result.duckdb_ms:.6f}",
                    "sqlite_duckdb_ratio": "" if result.speedup is None else f"{result.speedup:.6f}",
                    "description": result.description,
                }
            )


def scaled_database_paths(output_dir: Path, size: int) -> tuple[Path, Path]:
    """Return SQLite and DuckDB paths for a scaled benchmark size."""
    return output_dir / f"runs_{size}.db", output_dir / f"runs_{size}.duckdb"


def synthetic_runs(size: int) -> pd.DataFrame:
    """Build deterministic wide synthetic runs with realistic metadata columns."""
    index = np.arange(size)
    major = index % 50 + 1
    minor = index // 50 % 20
    patch = index // 1_000 % 10
    versions = np.array(
        [
            f"v{major_item}.{minor_item}.{patch_item}"
            for major_item, minor_item, patch_item in zip(major, minor, patch, strict=True)
        ],
        dtype=object,
    )
    models = MODEL_NAMES[index % len(MODEL_NAMES)]
    dates = (
        pd.Timestamp("2026-01-01")
        + pd.to_timedelta(index % 365, unit="D")
        + pd.to_timedelta(index % 86_400, unit="s")
    )
    density_base = 0.15 + (index % len(MODEL_NAMES)) * 0.23
    velocity_base = 0.02 + (index % 200) / 2_000
    error_base = (index % 1_000) / 10_000
    artifacts = np.array([f"store/synthetic-run-{item:08d}" for item in index], dtype=object)

    data = {
        "uid": [f"synthetic-{item:08d}" for item in index],
        "name": [
            f"{model}-{version}-synthetic-{item:08d}"
            for item, model, version in zip(index, models, versions, strict=True)
        ],
        "model": models,
        "version": versions,
        "date": dates.strftime("%Y-%m-%d %H:%M:%S"),
        "modified": index % 10 < 3,
        "density": density_base + (index % 17) / 1_000,
        "velocity": velocity_base,
        "error": error_base,
        "runtime": 2.5 + (index % 300) / 10,
        "memory_hwm": 4.0 + (index % 120) / 20,
        "artifact": artifacts,
        "artifact_path": artifacts,
        "git_commit": [f"{(item * 2_654_435_761) % 0xFFFFFFFFFFFF:012x}" for item in index],
        "git_branch": np.take(["main", "develop", "release", "feature/shock", "hotfix"], index % 5),
        "git_tag": np.array(
            [
                f"tag-{major_item}.{minor_item}"
                for major_item, minor_item in zip(major, minor, strict=True)
            ]
        ),
        "code_version": versions,
        "compiler": np.take(["gcc", "clang", "intel", "nvhpc"], index % 4),
        "compiler_version": np.take(["12.3", "15.0", "2025.1", "24.7"], index % 4),
        "mpi_version": np.take(["openmpi-5.0", "mpich-4.2", "intelmpi-2025"], index % 3),
        "scheduler": np.take(["slurm", "pbs", "lsf"], index % 3),
        "queue": np.take(["debug", "standard", "long", "gpu"], index % 4),
        "partition": np.take(["cpu", "highmem", "gpu-a100", "gpu-h100"], index % 4),
        "hpc_system": np.take(["archer2", "frontier", "perlmutter", "local"], index % 4),
        "node_type": np.take(["zen3", "zen4", "ice-lake", "sapphire-rapids"], index % 4),
        "job_name": [f"qa-shock-{item % 10_000:04d}" for item in index],
        "job_id": [f"job-{1_000_000 + item}" for item in index],
        "user_name": np.take(["ellis", "qa", "ci", "bench"], index % 4),
        "project": np.take(["shock-bubble", "regression", "validation", "scaling"], index % 4),
        "container_image": np.take(["qa-tool:latest", "solver:cpu", "solver:gpu", "post:stable"], index % 4),
        "os_image": np.take(["rocky9", "ubuntu24.04", "sles15", "macos"], index % 4),
        "input_deck": [f"case-{item % 2_500:04d}.yaml" for item in index],
        "mesh_id": [f"mesh-{item % 1_000:04d}" for item in index],
    }

    for scalar_index, column in enumerate(SCALAR_METADATA_COLUMNS, start=1):
        data[column] = (
            (index % (97 + scalar_index)) * (0.01 * scalar_index)
            + (index // (scalar_index + 3) % 11)
        )

    return pd.DataFrame(data)


def write_synthetic_sqlite(dataframe: pd.DataFrame, db_path: Path) -> None:
    """Write synthetic rows to SQLite efficiently."""
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = MEMORY")
        dataframe.to_sql("runs", connection, if_exists="replace", index=False, chunksize=50_000)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_uid ON runs (uid)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_model_version ON runs (model, version)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_version ON runs (version)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_date ON runs (date)")
        connection.commit()


def write_synthetic_duckdb(dataframe: pd.DataFrame, db_path: Path) -> None:
    """Write synthetic rows to DuckDB efficiently."""
    with duckdb.connect(str(db_path)) as connection:
        connection.register("runs_frame", dataframe)
        connection.execute(
            """
            CREATE OR REPLACE TABLE runs AS
            SELECT * REPLACE (CAST(date AS TIMESTAMP) AS date)
            FROM runs_frame
            """
        )


def build_synthetic_scaled_databases(
    output_dir: Path,
    sizes: Sequence[int],
    reuse_existing: bool,
) -> dict[int, tuple[Path, Path]]:
    """Build scaled SQLite and DuckDB pairs from synthetic rows."""
    if not sizes:
        raise ValueError("At least one database size is required.")
    if any(size < 1 for size in sizes):
        raise ValueError("Database sizes must be positive.")

    output_dir.mkdir(parents=True, exist_ok=True)

    database_paths = {}
    for size in sizes:
        sqlite_path, duckdb_path = scaled_database_paths(output_dir, size)
        if not (reuse_existing and sqlite_path.exists() and duckdb_path.exists()):
            sqlite_path.unlink(missing_ok=True)
            duckdb_path.unlink(missing_ok=True)
            rows = synthetic_runs(size)
            write_synthetic_sqlite(rows, sqlite_path)
            write_synthetic_duckdb(rows, duckdb_path)
        database_paths[size] = (sqlite_path, duckdb_path)
    return database_paths


def build_store_scaled_databases(
    store_dir: Path,
    output_dir: Path,
    sizes: Sequence[int],
    seed: int,
    reuse_existing: bool,
) -> dict[int, tuple[Path, Path]]:
    """Build SQLite and DuckDB database pairs from store metadata."""
    if not sizes:
        raise ValueError("At least one database size is required.")
    if any(size < 1 for size in sizes):
        raise ValueError("Database sizes must be positive.")

    max_size = max(sizes)
    rows = load_metadata(store_dir)
    if len(rows) < max_size:
        raise ValueError(
            f"Store only contains {len(rows)} metadata file(s), but requested {max_size}."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    database_paths = {}
    for size in sizes:
        sqlite_path, duckdb_path = scaled_database_paths(output_dir, size)
        if not (reuse_existing and sqlite_path.exists() and duckdb_path.exists()):
            sqlite_path.unlink(missing_ok=True)
            duckdb_path.unlink(missing_ok=True)
            selected_rows = random.Random(seed + size).sample(rows, size)
            write_sqlite(selected_rows, sqlite_path)
            write_duckdb(selected_rows, duckdb_path)
        database_paths[size] = (sqlite_path, duckdb_path)
    return database_paths


def run_scaled_benchmarks(
    store_dir: Path,
    output_dir: Path,
    sizes: Sequence[int],
    repeats: int,
    warmups: int,
    seed: int,
    source: str,
    reuse_existing: bool,
) -> list[ScaledQueryResult]:
    """Build scaled DB pairs and benchmark each pair."""
    if source == "synthetic":
        database_paths = build_synthetic_scaled_databases(output_dir, sizes, reuse_existing)
    elif source == "store":
        database_paths = build_store_scaled_databases(store_dir, output_dir, sizes, seed, reuse_existing)
    else:
        raise ValueError(f"Unknown source: {source}")

    results = []
    for size in sizes:
        sqlite_path, duckdb_path = database_paths[size]
        for result in run_benchmarks(sqlite_path, duckdb_path, repeats, warmups):
            results.append(ScaledQueryResult(database_rows=size, result=result))
    return results


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    argument_parser = argparse.ArgumentParser(
        description="Benchmark equivalent QA Tool queries against SQLite and DuckDB."
    )
    argument_parser.add_argument("--sqlite-db", default="runs.db", type=Path)
    argument_parser.add_argument("--duckdb-db", default="runs.duckdb", type=Path)
    argument_parser.add_argument("--repeats", default=7, type=int)
    argument_parser.add_argument("--warmups", default=2, type=int)
    argument_parser.add_argument(
        "--scaled",
        action="store_true",
        help="Build scaled DB pairs before benchmarking.",
    )
    argument_parser.add_argument(
        "--source",
        choices=["synthetic", "store"],
        default="synthetic",
        help="Source for scaled DB generation.",
    )
    argument_parser.add_argument(
        "--reuse-existing-scaled-dbs",
        action="store_true",
        help="Use existing scaled database files when both SQLite and DuckDB files are present.",
    )
    argument_parser.add_argument("--store-dir", default="store", type=Path)
    argument_parser.add_argument(
        "--output-dir",
        default=Path("performance_comparison/generated"),
        type=Path,
        help="Directory for generated scaled database pairs.",
    )
    argument_parser.add_argument(
        "--sizes",
        default=DEFAULT_SIZES,
        nargs="+",
        type=int,
        help="Scaled database sizes to build and benchmark.",
    )
    argument_parser.add_argument(
        "--seed",
        default=0,
        type=int,
        help="Seed used to choose deterministic random metadata samples.",
    )
    argument_parser.add_argument(
        "--output-file",
        default=Path("performance_comparison/results.md"),
        type=Path,
        help="Markdown file to write benchmark results.",
    )
    argument_parser.add_argument(
        "--csv-output-file",
        default=Path("performance_comparison/results.csv"),
        type=Path,
        help="CSV file to write scaled benchmark results.",
    )
    return argument_parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the comparison script."""
    args = parser().parse_args(argv)
    if args.repeats < 1:
        raise ValueError("--repeats must be at least 1")
    if args.warmups < 0:
        raise ValueError("--warmups must be at least 0")

    if args.scaled:
        if args.source == "store" and not args.store_dir.exists():
            raise FileNotFoundError(f"Could not find store directory: {args.store_dir}")
        scaled_results = run_scaled_benchmarks(
            args.store_dir,
            args.output_dir,
            args.sizes,
            args.repeats,
            args.warmups,
            args.seed,
            args.source,
            args.reuse_existing_scaled_dbs,
        )
        report = scaled_markdown_table(scaled_results)
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        args.output_file.write_text(report + "\n", encoding="utf-8")
        write_scaled_csv(scaled_results, args.csv_output_file)
        print(f"Wrote Markdown results to {args.output_file}")
        print(f"Wrote CSV results to {args.csv_output_file}")
        print(report)
        return 0

    if not args.sqlite_db.exists():
        raise FileNotFoundError(f"Could not find SQLite database: {args.sqlite_db}")
    if not args.duckdb_db.exists():
        raise FileNotFoundError(f"Could not find DuckDB database: {args.duckdb_db}")

    results = run_benchmarks(args.sqlite_db, args.duckdb_db, args.repeats, args.warmups)
    report = markdown_table(results)
    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(report + "\n", encoding="utf-8")
    print(f"Wrote Markdown results to {args.output_file}")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
