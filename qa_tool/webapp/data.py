"""QA dashboard module for data."""

from __future__ import annotations

import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from packaging.version import Version

from qa_tool.core.queries import load_runs as core_load_runs
from qa_tool.core.queries import metric_columns as core_metric_columns
from qa_tool.core.queries import normalize_run_columns as core_normalize_run_columns
from qa_tool.webapp.settings import configured_metrics

DEFAULT_DATABASE_CACHE_TTL_SECONDS = 60
DATABASE_CACHE_MAX_ENTRIES = 8


@dataclass(frozen=True)
class DatabaseRevision:
    """Filesystem identity used to bind cached data to one database revision."""

    resolved_path: str
    device: int
    inode: int
    size: int
    modified_ns: int


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
) -> pd.DataFrame:
    """Load runs through the shared core query layer with Streamlit caching."""
    del generation
    source_path = revision.resolved_path if revision is not None else db_path
    return core_load_runs(source_path, model_column, version_column)


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


def filter_runs(
    runs: pd.DataFrame,
    metrics: list[str],
    settings: dict[str, Any],
) -> pd.DataFrame:
    """Handle filter runs."""
    defaults = settings["defaults"]
    with st.sidebar:
        st.header("Filters")
        models = st.multiselect(
            "Models",
            sorted(runs["model"].unique()),
            default=sorted(runs["model"].unique()),
        )
        versions = st.multiselect(
            "Versions",
            sorted(runs["version"].unique(), key=Version),
            default=sorted(runs["version"].unique(), key=Version),
        )
        selected_metrics = st.multiselect(
            "Table metrics",
            metrics,
            default=configured_metrics(defaults["table_metrics"], metrics, metrics),
        )

        min_date = runs["date"].min().date()
        max_date = runs["date"].max().date()
        date_range = st.date_input(
            "Date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

    filtered = runs[runs["model"].isin(models) & runs["version"].isin(versions)].copy()

    if len(date_range) == 2:
        start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        filtered = filtered[(filtered["date"] >= start) & (filtered["date"] < end + pd.Timedelta(1, unit="day"))]

    st.session_state["summary_metrics"] = selected_metrics
    return filtered


def show_downloads(filtered: pd.DataFrame) -> None:
    """Handle show downloads."""
    with st.expander("Filtered raw run downloads", expanded=False):
        csv_column, json_column, dataframe_column = st.columns(3)
        csv_column.download_button(
            "Download filtered rows CSV",
            data=dataframe_to_csv(filtered),
            file_name="filtered_runs.csv",
            mime="text/csv",
            disabled=filtered.empty,
            use_container_width=True,
        )
        json_column.download_button(
            "Download filtered rows JSON",
            data=dataframe_to_json(filtered),
            file_name="filtered_runs.json",
            mime="application/json",
            disabled=filtered.empty,
            use_container_width=True,
        )
        dataframe_column.download_button(
            "Download filtered rows DataFrame",
            data=dataframe_to_pickle(filtered),
            file_name="filtered_runs.pkl",
            mime="application/octet-stream",
            disabled=filtered.empty,
            use_container_width=True,
        )
