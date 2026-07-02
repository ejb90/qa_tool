"""Compare SQLite and DuckDB performance for dashboard-style run queries."""

from __future__ import annotations

import argparse
import csv
import random
import sqlite3
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

from qa_tool.load_dummy_data import load_metadata, write_duckdb, write_sqlite

QueryParams = tuple[object, ...]


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

    comparison_versions = connection.execute(
        """
        WITH version_models AS (
            SELECT version, model
            FROM runs
            GROUP BY version, model
        )
        SELECT base.version, new.version, count(*) AS shared_models
        FROM version_models AS base
        JOIN version_models AS new
          ON base.model = new.model
         AND base.version < new.version
        GROUP BY base.version, new.version
        ORDER BY shared_models DESC, base.version, new.version
        LIMIT 1
        """
    ).fetchone()

    if comparison_versions is None:
        base_version = versions[0]
        new_version = versions[1] if len(versions) > 1 else versions[0]
    else:
        base_version = str(comparison_versions[0])
        new_version = str(comparison_versions[1])
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


def build_scaled_databases(
    store_dir: Path,
    output_dir: Path,
    sizes: Sequence[int],
    seed: int,
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
) -> list[ScaledQueryResult]:
    """Build scaled DB pairs and benchmark each pair."""
    database_paths = build_scaled_databases(store_dir, output_dir, sizes, seed)
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
        help="Build scaled DB pairs from store metadata before benchmarking.",
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
        default=[10, 100, 1_000, 10_000, 100_000],
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
    if not args.sqlite_db.exists():
        raise FileNotFoundError(f"Could not find SQLite database: {args.sqlite_db}")
    if not args.duckdb_db.exists():
        raise FileNotFoundError(f"Could not find DuckDB database: {args.duckdb_db}")
    if args.repeats < 1:
        raise ValueError("--repeats must be at least 1")
    if args.warmups < 0:
        raise ValueError("--warmups must be at least 0")

    if args.scaled:
        if not args.store_dir.exists():
            raise FileNotFoundError(f"Could not find store directory: {args.store_dir}")
        scaled_results = run_scaled_benchmarks(
            args.store_dir,
            args.output_dir,
            args.sizes,
            args.repeats,
            args.warmups,
            args.seed,
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
