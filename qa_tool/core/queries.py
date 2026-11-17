"""Database loading, aggregation, and collection-selection queries."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import duckdb
import pandas as pd

METRIC_EXCLUDE_COLUMNS = frozenset({"uid", "name", "model", "version", "date"})
MatchMode = Literal["exact", "starts-with", "contains", "regex", "non-empty"]


def normalize_run_columns(runs: pd.DataFrame, model_column: str, version_column: str) -> pd.DataFrame:
    """Map configured source columns to the canonical QA run-column names."""
    required_columns = {"model": model_column, "version": version_column}
    missing_columns = [column for column in required_columns.values() if column not in runs.columns]
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

    normalized = runs.rename(columns=rename_columns)
    if "uid" not in normalized.columns:
        raise ValueError("Missing required database column `uid`")
    if "name" not in normalized.columns:
        normalized["name"] = normalized["uid"].astype(str)
    if "date" not in normalized.columns:
        raise ValueError("Missing required database column `date`")
    normalized["date"] = pd.to_datetime(normalized["date"], errors="raise")
    return normalized


def load_runs(database_path: str | Path, model_column: str = "model", version_column: str = "version") -> pd.DataFrame:
    """Load and normalize all run rows from a DuckDB database."""
    path = Path(database_path)
    if path.suffix != ".duckdb":
        raise ValueError("QA Tool requires a DuckDB database with a `.duckdb` extension.")
    if not path.exists():
        raise FileNotFoundError(f"Could not find database: {path}")
    with duckdb.connect(str(path), read_only=True) as connection:
        runs = connection.execute("SELECT * FROM runs").df()
    return normalize_run_columns(runs, model_column, version_column).sort_values("date", ascending=False)


def metric_columns(runs: pd.DataFrame) -> list[str]:
    """Return numeric columns suitable for QA metric summaries and plots."""
    return [column for column in runs.select_dtypes(include="number").columns if column not in METRIC_EXCLUDE_COLUMNS]


def aggregate_runs(runs: pd.DataFrame, group_columns: list[str], metrics: list[str]) -> pd.DataFrame:
    """Aggregate run counts, date bounds, and metric means by the requested columns."""
    return (
        runs.groupby(group_columns, as_index=False)
        .agg(
            run_count=("uid", "count"),
            first_run=("date", "min"),
            last_run=("date", "max"),
            **{f"mean_{metric}": (metric, "mean") for metric in metrics},
        )
        .sort_values(group_columns)
    )


def version_sort_key(version: str) -> tuple[int, ...]:
    """Return a natural numeric sort key for versions such as ``v2.10.0``."""
    return tuple(int(part) for part in str(version).removeprefix("v").split(".") if part.isdigit())


def model_mean_cdf_data(runs: pd.DataFrame, metric: str, label: str | None = None) -> pd.DataFrame:
    """Calculate an empirical CDF from one mean metric value per model."""
    model_values = (
        runs.groupby("model", as_index=False)
        .agg(value=(metric, "mean"), uncertainty=(metric, "std"), run_count=("uid", "count"))
        .sort_values("value")
        .reset_index(drop=True)
    )
    model_values["uncertainty"] = model_values["uncertainty"].fillna(0.0)
    model_values["cdf"] = (model_values.index + 1) / len(model_values)
    if label is not None:
        model_values["curve"] = label
    return model_values


def select_collection(
    runs: pd.DataFrame,
    field: str,
    values: list[str],
    match_mode: MatchMode = "exact",
) -> pd.DataFrame:
    """Select a collection using web-app-equivalent exact, text, boolean, or date matching."""
    if field not in runs.columns:
        raise ValueError(f"Unknown collection field: `{field}`")
    series = runs[field]
    if pd.api.types.is_datetime64_any_dtype(series):
        if len(values) != 2:
            raise ValueError("Datetime collections require exactly two values: start and end.")
        start, end = (pd.to_datetime(value) for value in values)
        return runs[(series >= start) & (series < end + pd.Timedelta(days=1))].copy()
    if pd.api.types.is_bool_dtype(series):
        accepted = {value.lower() in {"1", "true", "yes", "on"} for value in values}
        return runs[series.isin(accepted)].copy()

    strings = series.fillna("").astype(str)
    if match_mode == "exact":
        mask = strings.isin(values)
    elif match_mode == "starts-with":
        mask = strings.str.startswith(tuple(values), na=False)
    elif match_mode == "contains":
        mask = pd.Series(False, index=runs.index)
        for value in values:
            mask |= strings.str.contains(value, case=False, regex=False, na=False)
    elif match_mode == "regex":
        mask = pd.Series(False, index=runs.index)
        for value in values:
            try:
                mask |= strings.str.contains(value, case=False, regex=True, na=False)
            except re.error as error:
                raise ValueError(f"Invalid regular expression `{value}`: {error}") from error
    else:
        mask = strings.str.len() > 0
    return runs[mask].copy()
