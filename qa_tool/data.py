"""QA dashboard module for data."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

try:
    from qa_tool.settings import configured_metrics
except ModuleNotFoundError:
    from settings import configured_metrics


METRIC_EXCLUDE_COLUMNS = {"uid", "name", "model", "version", "date"}


def normalize_run_columns(
    runs: pd.DataFrame,
    model_column: str,
    version_column: str,
) -> pd.DataFrame:
    """Handle normalize run columns."""
    required_columns = {
        "model": model_column,
        "version": version_column,
    }
    missing_columns = [
        source_column for source_column in required_columns.values() if source_column not in runs.columns
    ]
    if missing_columns:
        raise ValueError(
            "Missing configured database column(s): " + ", ".join(f"`{column}`" for column in missing_columns)
        )

    rename_columns = {
        source_column: canonical_column
        for canonical_column, source_column in required_columns.items()
        if source_column != canonical_column
    }
    collisions = [
        canonical_column
        for canonical_column, source_column in required_columns.items()
        if source_column != canonical_column and canonical_column in runs.columns
    ]
    if collisions:
        raise ValueError(
            "Cannot map configured column(s) because the canonical column already exists: "
            + ", ".join(f"`{column}`" for column in collisions)
        )

    runs = runs.rename(columns=rename_columns)
    if "uid" not in runs.columns:
        raise ValueError("Missing required database column `uid`")
    if "name" not in runs.columns:
        runs["name"] = runs["uid"].astype(str)
    return runs


@st.cache_data(show_spinner=False)
def load_runs(db_path: str, model_column: str, version_column: str) -> pd.DataFrame:
    """Handle load runs."""
    path = Path(db_path)
    if path.suffix != ".duckdb":
        raise ValueError("QA Tool requires a DuckDB database with a `.duckdb` extension.")

    import duckdb

    with duckdb.connect(str(path), read_only=True) as connection:
        runs = connection.execute("SELECT * FROM runs").df()

    runs = normalize_run_columns(runs, model_column, version_column)
    if not pd.api.types.is_datetime64_any_dtype(runs["date"]):
        runs["date"] = pd.to_datetime(runs["date"], format="%Y-%m-%d %H:%M:%S")
    return runs.sort_values("date", ascending=False)


@st.cache_data(show_spinner=False)
def load_run_summary(db_path: str) -> dict[str, Any] | None:
    """Load the precomputed overview metrics when the database provides them."""
    path = Path(db_path)
    if path.suffix != ".duckdb":
        return None
    try:
        import duckdb

        with duckdb.connect(str(path), read_only=True) as connection:
            summary = connection.execute("SELECT * FROM run_summary LIMIT 1").df()
    except Exception:  # A summary table is optional for existing databases.
        return None

    return summary.iloc[0].to_dict() if not summary.empty else None


def metric_columns(runs: pd.DataFrame) -> list[str]:
    """Handle metric columns."""
    return [column for column in runs.select_dtypes(include="number").columns if column not in METRIC_EXCLUDE_COLUMNS]


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
            sorted(runs["version"].unique()),
            default=sorted(runs["version"].unique()),
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
