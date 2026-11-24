"""QA dashboard module for data."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import streamlit as st
from packaging.version import Version

from qa_tool.core.queries import load_runs as core_load_runs
from qa_tool.core.queries import metric_columns as core_metric_columns
from qa_tool.core.queries import normalize_run_columns as core_normalize_run_columns
from qa_tool.webapp.settings import configured_metrics

DEFAULT_DATABASE_CACHE_TTL_SECONDS = 60
DATABASE_CACHE_MAX_ENTRIES = 8
DEFAULT_MAX_QUERY_ROWS = 50_000
NUMERIC_DUCKDB_TYPES = frozenset(
    {
        "BIGINT",
        "DECIMAL",
        "DOUBLE",
        "FLOAT",
        "HUGEINT",
        "INTEGER",
        "REAL",
        "SMALLINT",
        "TINYINT",
        "UBIGINT",
        "UHUGEINT",
        "UINTEGER",
        "USMALLINT",
        "UTINYINT",
    }
)


@dataclass(frozen=True)
class DatabaseRevision:
    """Filesystem identity used to bind cached data to one database revision."""

    resolved_path: str
    device: int
    inode: int
    size: int
    modified_ns: int


@dataclass(frozen=True)
class RunSchema:
    """Canonical dashboard columns and numeric metric names."""

    columns: tuple[str, ...]
    metrics: tuple[str, ...]
    sources: tuple[tuple[str, str], ...]

    def source_for(self, column: str) -> str | None:
        """Return the physical DuckDB column for a canonical dashboard name."""
        return dict(self.sources).get(column)


@dataclass(frozen=True)
class RunFilters:
    """Shared predicates applied by DuckDB before rows reach pandas."""

    models: tuple[str, ...] = ()
    versions: tuple[str, ...] = ()
    start_date: date | None = None
    end_date: date | None = None


@dataclass(frozen=True)
class RunFilterOptions:
    """Small filter-domain result loaded without materializing run rows."""

    models: tuple[str, ...]
    versions: tuple[str, ...]
    min_date: date
    max_date: date


def database_revision(db_path: str | Path) -> DatabaseRevision:
    """Return a stable cache token for the current resolved database file."""
    resolved_path = Path(db_path).resolve(strict=True)
    stat = resolved_path.stat()
    return DatabaseRevision(
        resolved_path=str(resolved_path),
        device=stat.st_dev,
        inode=stat.st_ino,
        size=stat.st_size,
        modified_ns=stat.st_mtime_ns,
    )


def database_cache_ttl_seconds(settings: dict[str, Any]) -> int:
    """Return the configured non-negative database cache TTL."""
    value = settings["database"].get("cache_ttl_seconds", DEFAULT_DATABASE_CACHE_TTL_SECONDS)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("`database.cache_ttl_seconds` must be a non-negative integer")
    return value


def database_cache_generation(ttl_seconds: int, now: float | None = None) -> int:
    """Return a time bucket used as a bounded-staleness cache key."""
    if ttl_seconds < 0:
        raise ValueError("Database cache TTL cannot be negative")
    if ttl_seconds == 0:
        return 0
    current_time = time.time() if now is None else now
    return int(current_time // ttl_seconds)


def database_max_query_rows(settings: dict[str, Any]) -> int:
    """Return the positive upper bound for one interactive analytical query."""
    value = settings["database"].get("max_query_rows", DEFAULT_MAX_QUERY_ROWS)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("`database.max_query_rows` must be a positive integer")
    return value


def _quote_identifier(identifier: str) -> str:
    """Quote a DuckDB identifier after escaping embedded quote characters."""
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _source_columns(model_column: str, version_column: str) -> dict[str, str]:
    return {"model": model_column, "version": version_column}


def _canonical_columns(
    described_columns: list[tuple[str, str]],
    model_column: str,
    version_column: str,
) -> list[tuple[str, str, str]]:
    """Return source, canonical, and type triples after validating aliases."""
    aliases = _source_columns(model_column, version_column)
    source_names = {name for name, _ in described_columns}
    missing = [source for source in aliases.values() if source not in source_names]
    if missing:
        raise ValueError("Missing configured database column(s): " + ", ".join(f"`{name}`" for name in missing))
    collisions = [
        canonical for canonical, source in aliases.items() if source != canonical and canonical in source_names
    ]
    if collisions:
        raise ValueError(
            "Cannot map configured column(s) because the canonical column already exists: "
            + ", ".join(f"`{name}`" for name in collisions)
        )
    canonical = []
    for source, data_type in described_columns:
        name = next((target for target, mapped in aliases.items() if mapped == source), source)
        canonical.append((source, name, data_type))
    canonical_names = {name for _, name, _ in canonical}
    if "uid" not in canonical_names:
        raise ValueError("Missing required database column `uid`")
    if "date" not in canonical_names:
        raise ValueError("Missing required database column `date`")
    if "name" not in canonical_names:
        canonical.insert(1, ("uid", "name", "VARCHAR"))
    return canonical


def _connect(source_path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(source_path, read_only=True)


def _resolved_source(db_path: str, revision: DatabaseRevision | None) -> str:
    return revision.resolved_path if revision is not None else db_path


@st.cache_data(show_spinner=False, max_entries=DATABASE_CACHE_MAX_ENTRIES)
def load_run_schema(
    db_path: str,
    model_column: str,
    version_column: str,
    revision: DatabaseRevision | None = None,
    generation: int = 0,
) -> RunSchema:
    """Inspect the runs schema without loading any run rows."""
    del generation
    with _connect(_resolved_source(db_path, revision)) as connection:
        described = connection.execute("DESCRIBE runs").fetchall()
    canonical = _canonical_columns([(str(row[0]), str(row[1])) for row in described], model_column, version_column)
    columns = tuple(name for _, name, _ in canonical)
    metrics = tuple(
        name
        for _, name, data_type in canonical
        if name not in {"uid", "name", "model", "version", "date"}
        and data_type.upper().split("(", maxsplit=1)[0] in NUMERIC_DUCKDB_TYPES
    )
    sources = tuple((name, source) for source, name, _ in canonical)
    return RunSchema(columns, metrics, sources)


def _projection_sql(
    available: list[tuple[str, str, str]],
    requested_columns: tuple[str, ...] | None,
) -> str:
    selected = available if requested_columns is None else [item for item in available if item[1] in requested_columns]
    if requested_columns is not None:
        missing = set(requested_columns) - {name for _, name, _ in selected}
        if missing:
            raise ValueError("Unknown run column(s): " + ", ".join(f"`{name}`" for name in sorted(missing)))
    expressions = []
    for source, canonical, _ in selected:
        expression = _quote_identifier(source)
        if source != canonical:
            expression += f" AS {_quote_identifier(canonical)}"
        expressions.append(expression)
    if not expressions:
        raise ValueError("At least one run column must be selected")
    return ", ".join(expressions)


def _where_sql(
    filters: RunFilters | None,
    model_column: str,
    version_column: str,
    *,
    search: str = "",
    search_columns: tuple[str, ...] = (),
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    parameters: list[Any] = []
    if filters is not None:
        for values, source in ((filters.models, model_column), (filters.versions, version_column)):
            if values:
                clauses.append(f"{_quote_identifier(source)} IN ({', '.join('?' for _ in values)})")
                parameters.extend(values)
            else:
                clauses.append("FALSE")
        if filters.start_date is not None:
            clauses.append(f"{_quote_identifier('date')} >= ?")
            parameters.append(filters.start_date)
        if filters.end_date is not None:
            clauses.append(f"{_quote_identifier('date')} < ? + INTERVAL 1 DAY")
            parameters.append(filters.end_date)
    if search and search_columns:
        expressions = (f"CAST({_quote_identifier(column)} AS VARCHAR) ILIKE ?" for column in search_columns)
        clauses.append("(" + " OR ".join(expressions) + ")")
        parameters.extend([f"%{search}%"] * len(search_columns))
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters


def _described_columns(
    connection: duckdb.DuckDBPyConnection,
    model_column: str,
    version_column: str,
) -> list[tuple[str, str, str]]:
    rows = connection.execute("DESCRIBE runs").fetchall()
    return _canonical_columns([(str(row[0]), str(row[1])) for row in rows], model_column, version_column)


@st.cache_data(show_spinner=False, max_entries=DATABASE_CACHE_MAX_ENTRIES)
def load_run_filter_options(
    db_path: str,
    model_column: str,
    version_column: str,
    revision: DatabaseRevision | None = None,
    generation: int = 0,
) -> RunFilterOptions:
    """Load distinct filter values and date bounds using database aggregation."""
    del generation
    with _connect(_resolved_source(db_path, revision)) as connection:
        models = tuple(
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT {_quote_identifier(model_column)} FROM runs "
                f"WHERE {_quote_identifier(model_column)} IS NOT NULL ORDER BY 1"
            ).fetchall()
        )
        versions = tuple(
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT {_quote_identifier(version_column)} FROM runs "
                f"WHERE {_quote_identifier(version_column)} IS NOT NULL"
            ).fetchall()
        )
        bounds = connection.execute(
            f"SELECT MIN({_quote_identifier('date')}), MAX({_quote_identifier('date')}) FROM runs"
        ).fetchone()
    if bounds is None or bounds[0] is None or bounds[1] is None:
        raise ValueError("The runs table contains no dated rows")
    return RunFilterOptions(models, versions, pd.Timestamp(bounds[0]).date(), pd.Timestamp(bounds[1]).date())


def normalize_run_columns(
    runs: pd.DataFrame,
    model_column: str,
    version_column: str,
) -> pd.DataFrame:
    """Map source columns to the shared core package's canonical run schema."""
    return core_normalize_run_columns(runs, model_column, version_column)


@st.cache_data(show_spinner=False, max_entries=DATABASE_CACHE_MAX_ENTRIES)
def load_runs(
    db_path: str,
    model_column: str,
    version_column: str,
    revision: DatabaseRevision | None = None,
    generation: int = 0,
    columns: tuple[str, ...] | None = None,
    filters: RunFilters | None = None,
    limit: int | None = None,
    offset: int = 0,
    search: str = "",
    search_columns: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Load a projected, filtered, and optionally bounded run window."""
    del generation
    source_path = _resolved_source(db_path, revision)
    if columns is None and filters is None and limit is None and not search and offset == 0:
        return core_load_runs(source_path, model_column, version_column)
    if limit is not None and limit <= 0:
        raise ValueError("Run query limit must be positive")
    if offset < 0:
        raise ValueError("Run query offset cannot be negative")
    with _connect(source_path) as connection:
        available = _described_columns(connection, model_column, version_column)
        source_names = {source for source, _, _ in available}
        invalid_search = set(search_columns) - source_names
        if invalid_search:
            raise ValueError("Unknown search column(s): " + ", ".join(sorted(invalid_search)))
        projection = _projection_sql(available, columns)
        where, parameters = _where_sql(
            filters,
            model_column,
            version_column,
            search=search,
            search_columns=search_columns,
        )
        query = f"SELECT {projection} FROM runs{where} ORDER BY {_quote_identifier('date')} DESC"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            parameters.extend([limit, offset])
        runs = connection.execute(query, parameters).df()
    if "date" in runs.columns:
        runs["date"] = pd.to_datetime(runs["date"], errors="raise")
    return runs


@st.cache_data(show_spinner=False, max_entries=DATABASE_CACHE_MAX_ENTRIES)
def count_runs(
    db_path: str,
    model_column: str,
    version_column: str,
    revision: DatabaseRevision | None = None,
    generation: int = 0,
    filters: RunFilters | None = None,
    search: str = "",
    search_columns: tuple[str, ...] = (),
) -> int:
    """Count matching rows in DuckDB without materializing them."""
    del generation
    with _connect(_resolved_source(db_path, revision)) as connection:
        source_names = {str(row[0]) for row in connection.execute("DESCRIBE runs").fetchall()}
        invalid_search = set(search_columns) - source_names
        if invalid_search:
            raise ValueError("Unknown search column(s): " + ", ".join(sorted(invalid_search)))
        where, parameters = _where_sql(
            filters,
            model_column,
            version_column,
            search=search,
            search_columns=search_columns,
        )
        return int(connection.execute(f"SELECT COUNT(*) FROM runs{where}", parameters).fetchone()[0])


@st.cache_data(show_spinner=False, max_entries=DATABASE_CACHE_MAX_ENTRIES)
def load_run_statistics(
    db_path: str,
    model_column: str,
    version_column: str,
    revision: DatabaseRevision | None = None,
    generation: int = 0,
    filters: RunFilters | None = None,
    metrics: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Calculate exact filtered summary values inside DuckDB."""
    del generation
    with _connect(_resolved_source(db_path, revision)) as connection:
        available = _described_columns(connection, model_column, version_column)
        sources = {canonical: source for source, canonical, _ in available}
        missing = set(metrics) - set(sources)
        if missing:
            raise ValueError("Unknown summary metric(s): " + ", ".join(sorted(missing)))
        expressions = [
            'COUNT(*) AS "runs"',
            f'COUNT(DISTINCT {_quote_identifier(model_column)}) AS "models"',
            f'COUNT(DISTINCT {_quote_identifier(version_column)}) AS "versions"',
        ]
        for metric in metrics:
            source = _quote_identifier(sources[metric])
            for aggregation in ("AVG", "MIN", "MAX"):
                label = f"{'mean' if aggregation == 'AVG' else aggregation.lower()}_{metric}"
                expressions.append(f"{aggregation}({source}) AS {_quote_identifier(label)}")
        where, parameters = _where_sql(filters, model_column, version_column)
        result = connection.execute(f"SELECT {', '.join(expressions)} FROM runs{where}", parameters)
        row = result.fetchone()
        return dict(zip((description[0] for description in result.description), row, strict=True))


@st.cache_data(show_spinner=False, max_entries=DATABASE_CACHE_MAX_ENTRIES)
def load_run_summary(
    db_path: str,
    revision: DatabaseRevision | None = None,
    generation: int = 0,
) -> dict[str, Any] | None:
    """Load the precomputed overview metrics when the database provides them."""
    del generation
    path = Path(revision.resolved_path if revision is not None else db_path)
    if path.suffix != ".duckdb":
        return None
    try:
        import duckdb

        with duckdb.connect(str(path), read_only=True) as connection:
            summary = connection.execute("SELECT * FROM run_summary LIMIT 1").df()
    except Exception:  # A summary table is optional for existing databases.
        return None

    return summary.iloc[0].to_dict() if not summary.empty else None


def clear_database_caches() -> None:
    """Clear only cached database rows and stored summaries."""
    load_runs.clear()
    load_run_summary.clear()
    load_run_schema.clear()
    load_run_filter_options.clear()
    count_runs.clear()
    load_run_statistics.clear()


def metric_columns(runs: pd.DataFrame) -> list[str]:
    """Return numeric metrics using the shared core selection rules."""
    return core_metric_columns(runs)


@st.cache_data(show_spinner=False)
def dataframe_to_csv(dataframe: pd.DataFrame) -> bytes:
    """Handle dataframe to csv."""
    return dataframe.to_csv(index=False).encode("utf-8")


@st.cache_data(show_spinner=False)
def dataframe_to_json(dataframe: pd.DataFrame) -> bytes:
    """Handle dataframe to json."""
    return dataframe.to_json(orient="records", date_format="iso", indent=2).encode("utf-8")


@st.cache_data(show_spinner=False)
def dataframe_to_pickle(dataframe: pd.DataFrame) -> bytes:
    """Handle dataframe to pickle."""
    buffer = BytesIO()
    dataframe.to_pickle(buffer)
    return buffer.getvalue()


def select_run_filters(
    options: RunFilterOptions,
    metrics: list[str],
    settings: dict[str, Any],
) -> tuple[RunFilters, list[str]]:
    """Render shared controls and return predicates for the database query."""
    defaults = settings["defaults"]
    with st.sidebar:
        st.header("Filters")
        models = st.multiselect(
            "Models",
            list(options.models),
            default=list(options.models),
        )
        versions = st.multiselect(
            "Versions",
            sorted(options.versions, key=Version),
            default=sorted(options.versions, key=Version),
        )
        selected_metrics = st.multiselect(
            "Table metrics",
            metrics,
            default=configured_metrics(defaults["table_metrics"], metrics, metrics),
        )

        date_range = st.date_input(
            "Date range",
            value=(options.min_date, options.max_date),
            min_value=options.min_date,
            max_value=options.max_date,
        )
    start_date, end_date = date_range if len(date_range) == 2 else (None, None)
    return RunFilters(tuple(models), tuple(versions), start_date, end_date), selected_metrics


def show_downloads(filtered: pd.DataFrame, *, label: str = "filtered rows") -> None:
    """Offer bounded run rows in safe and opt-in legacy formats."""
    with st.expander(f"Download {label}", expanded=False):
        csv_column, json_column, dataframe_column = st.columns(3)
        csv_column.download_button(
            f"Download {label} CSV",
            data=dataframe_to_csv(filtered),
            file_name="filtered_runs.csv",
            mime="text/csv",
            disabled=filtered.empty,
            use_container_width=True,
        )
        json_column.download_button(
            f"Download {label} JSON",
            data=dataframe_to_json(filtered),
            file_name="filtered_runs.json",
            mime="application/json",
            disabled=filtered.empty,
            use_container_width=True,
        )
        dataframe_column.download_button(
            f"Download {label} DataFrame",
            data=dataframe_to_pickle(filtered),
            file_name="filtered_runs.pkl",
            mime="application/octet-stream",
            disabled=filtered.empty,
            use_container_width=True,
        )
