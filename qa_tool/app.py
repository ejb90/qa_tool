from __future__ import annotations

import argparse
import json
import re
import tarfile
import tempfile
import zipfile
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import create_engine

try:
    from qa_tool.settings import configured_metrics, load_settings
except ModuleNotFoundError:
    from settings import configured_metrics, load_settings


METRIC_EXCLUDE_COLUMNS = {"uid", "name", "model", "version", "date"}
SUMMARY_AGGREGATIONS = {
    "mean": "Mean",
    "min": "Min",
    "max": "Max",
}
TOP_SUMMARY_LABELS = {
    "runs": "Runs",
    "versions": "Versions",
    "models": "Models",
    "total_runtime": "Total runtime",
}
TIME_COLUMN_PATTERN = re.compile(r"(^|[\s_-])time([\s_-]|$)|^t$", re.IGNORECASE)
MATERIAL_COLUMN_PATTERN = re.compile(r"^materials?$", re.IGNORECASE)
SERIES_SEPARATOR_PATTERN = re.compile(r"[\s_.:/|-]+")
COLLECTION_LABEL_COLUMN = "__collection__"
COMPARISON_COLOR_SCHEMES = {
    "Red / blue": {
        "negative": (31, 119, 180),
        "positive": (214, 39, 40),
        "sequential": (44, 160, 120),
    },
    "Blue / orange": {
        "negative": (0, 114, 178),
        "positive": (230, 159, 0),
        "sequential": (0, 158, 115),
    },
    "Purple / green": {
        "negative": (117, 112, 179),
        "positive": (27, 158, 119),
        "sequential": (102, 166, 30),
    },
}


def export_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "data"


def dataframes_to_zip(dataframes: dict[str, pd.DataFrame]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, dataframe in dataframes.items():
            archive.writestr(
                f"{export_name(name)}.csv",
                dataframe.to_csv(index=False),
            )
    return buffer.getvalue()


def comparison_metadata(
    base_label: str,
    test_label: str,
    base_runs: pd.DataFrame,
    test_runs: pd.DataFrame,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"item": "base_label", "value": base_label},
            {"item": "test_label", "value": test_label},
            {"item": "base_run_count", "value": len(base_runs)},
            {"item": "test_run_count", "value": len(test_runs)},
            {"item": "base_model_count", "value": base_runs["model"].nunique()},
            {"item": "test_model_count", "value": test_runs["model"].nunique()},
        ]
    )


def comparison_coverage(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
) -> pd.DataFrame:
    base_models = set(base_runs["model"].dropna().astype(str))
    test_models = set(test_runs["model"].dropna().astype(str))
    rows = []
    for model in sorted(base_models | test_models):
        in_base = model in base_models
        in_test = model in test_models
        if in_base and in_test:
            status = "shared"
        elif in_base:
            status = f"only_{export_name(base_label)}"
        else:
            status = f"only_{export_name(test_label)}"
        rows.append(
            {
                "model": model,
                "in_base": in_base,
                "in_test": in_test,
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def build_collection_metric_deltas(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    metrics: list[str],
) -> pd.DataFrame:
    base_summary = (
        base_runs.groupby("model")[metrics]
        .agg(["mean", "std", "count"])
        .stack(level=0, future_stack=True)
        .reset_index()
        .rename(
            columns={
                "level_1": "metric",
                "mean": "base_mean",
                "std": "base_std",
                "count": "base_runs",
            }
        )
    )
    test_summary = (
        test_runs.groupby("model")[metrics]
        .agg(["mean", "std", "count"])
        .stack(level=0, future_stack=True)
        .reset_index()
        .rename(
            columns={
                "level_1": "metric",
                "mean": "test_mean",
                "std": "test_std",
                "count": "test_runs",
            }
        )
    )
    comparison = base_summary.merge(
        test_summary,
        on=["model", "metric"],
        how="outer",
    ).sort_values(["metric", "model"])
    comparison["base_label"] = base_label
    comparison["test_label"] = test_label
    comparison["mean_delta"] = comparison["test_mean"] - comparison["base_mean"]
    comparison["percent_mean_delta"] = 100 * comparison["mean_delta"] / comparison["base_mean"]
    comparison.loc[comparison["base_mean"] == 0, "percent_mean_delta"] = pd.NA
    comparison["uncertainty"] = (
        (comparison["base_std"].fillna(0.0) ** 2 / comparison["base_runs"])
        + (comparison["test_std"].fillna(0.0) ** 2 / comparison["test_runs"])
    ) ** 0.5
    return comparison[
        [
            "base_label",
            "test_label",
            "model",
            "metric",
            "base_mean",
            "test_mean",
            "mean_delta",
            "percent_mean_delta",
            "base_std",
            "test_std",
            "uncertainty",
            "base_runs",
            "test_runs",
        ]
    ]


def show_export_download(
    label: str,
    dataframes: dict[str, pd.DataFrame],
    file_name: str,
    key: str,
) -> None:
    if not dataframes:
        return
    st.download_button(
        label,
        data=dataframes_to_zip(dataframes),
        file_name=file_name,
        mime="application/zip",
        key=key,
        use_container_width=True,
    )


def comparison_color_bounds(settings: dict[str, Any]) -> dict[str, float]:
    configured_bounds = settings.get("comparison", {}).get("color_bounds", {})
    return {
        str(metric): float(bound)
        for metric, bound in configured_bounds.items()
        if not isinstance(bound, bool) and isinstance(bound, int | float) and bound > 0
    }


def comparison_column_bound(column: str, bounds: dict[str, float]) -> float | None:
    if column in bounds:
        return bounds[column]
    for prefix in ("delta_", "uncertainty_"):
        if column.startswith(prefix):
            metric = column.removeprefix(prefix)
            return bounds.get(metric)
    return None


def select_comparison_color_scheme(key: str) -> str:
    return st.selectbox(
        "Cell colours",
        ["Red / blue", "Blue / orange", "Purple / green", "Off"],
        index=0,
        key=key,
    )


def styled_comparison_table(
    dataframe: pd.DataFrame,
    settings: dict[str, Any],
    color_scheme: str = "Red / blue",
) -> Any:
    if color_scheme == "Off":
        return dataframe

    color_bounds = comparison_color_bounds(settings)
    colours = COMPARISON_COLOR_SCHEMES.get(
        color_scheme,
        COMPARISON_COLOR_SCHEMES["Red / blue"],
    )

    def alpha_style(red: int, green: int, blue: int, fraction: float) -> str:
        fraction = min(1.0, max(0.0, fraction))
        alpha = 0.18 + 0.62 * fraction
        return f"background-color: rgba({red}, {green}, {blue}, {alpha:.3f})"

    def delta_styles(values: pd.Series, bound: float | None = None) -> list[str]:
        numeric_values = pd.to_numeric(values, errors="coerce")
        max_abs = bound or numeric_values.abs().max()
        if pd.isna(max_abs) or max_abs == 0:
            return [""] * len(values)
        styles = []
        for value in numeric_values:
            if pd.isna(value) or value == 0:
                styles.append("")
            elif value > 0:
                styles.append(alpha_style(*colours["positive"], float(value / max_abs)))
            else:
                styles.append(alpha_style(*colours["negative"], float(abs(value) / max_abs)))
        return styles

    def sequential_styles(values: pd.Series) -> list[str]:
        numeric_values = pd.to_numeric(values, errors="coerce")
        minimum = numeric_values.min()
        maximum = numeric_values.max()
        if pd.isna(minimum) or pd.isna(maximum) or minimum == maximum:
            return [""] * len(values)
        return [
            ""
            if pd.isna(value)
            else alpha_style(*colours["sequential"], float((value - minimum) / (maximum - minimum)))
            for value in numeric_values
        ]

    def metric_row_styles(row: pd.Series) -> list[str]:
        styles = pd.Series("", index=row.index)
        metric = str(row.get("metric", ""))
        bound = color_bounds.get(metric)
        if bound is None:
            return styles.tolist()
        for column in ("bottom_minus_top", "mean_delta", "delta"):
            if column not in row.index:
                continue
            value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
            if pd.isna(value) or value == 0:
                continue
            fraction = min(1.0, abs(float(value)) / bound)
            if value > 0:
                styles[column] = alpha_style(*colours["positive"], fraction)
            else:
                styles[column] = alpha_style(*colours["negative"], fraction)
        return styles.tolist()

    style = dataframe.style
    delta_columns = [
        column
        for column in dataframe.columns
        if str(column).startswith("delta_")
        or str(column).endswith("_minus_top")
        or str(column) in {"delta", "mean_delta", "percent_mean_delta"}
    ]
    for column in delta_columns:
        values = pd.to_numeric(dataframe[column], errors="coerce").dropna()
        if values.empty:
            continue
        style = style.apply(
            delta_styles,
            subset=[column],
            axis=0,
            bound=comparison_column_bound(str(column), color_bounds),
        )

    sequential_columns = [
        column
        for column in dataframe.columns
        if str(column).startswith("uncertainty")
        or str(column) in {"base_std", "test_std", "std"}
    ]
    for column in sequential_columns:
        values = pd.to_numeric(dataframe[column], errors="coerce").dropna()
        if values.empty or values.max() == values.min():
            continue
        style = style.apply(sequential_styles, subset=[column], axis=0)

    if "metric" in dataframe.columns and color_bounds:
        style = style.apply(metric_row_styles, axis=1)

    return style


def normalize_run_columns(
    runs: pd.DataFrame,
    model_column: str,
    version_column: str,
) -> pd.DataFrame:
    required_columns = {
        "model": model_column,
        "version": version_column,
    }
    missing_columns = [
        source_column
        for source_column in required_columns.values()
        if source_column not in runs.columns
    ]
    if missing_columns:
        raise ValueError(
            "Missing configured database column(s): "
            + ", ".join(f"`{column}`" for column in missing_columns)
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

    return runs.rename(columns=rename_columns)


@st.cache_data(show_spinner=False)
def load_runs(db_path: str, model_column: str, version_column: str) -> pd.DataFrame:
    path = Path(db_path)
    if path.suffix == ".duckdb":
        import duckdb

        with duckdb.connect(str(path), read_only=True) as connection:
            runs = connection.execute("SELECT * FROM runs").df()
    else:
        engine = create_engine(f"sqlite:///{path}")
        runs = pd.read_sql_table("runs", engine)

    runs = normalize_run_columns(runs, model_column, version_column)
    if not pd.api.types.is_datetime64_any_dtype(runs["date"]):
        runs["date"] = pd.to_datetime(runs["date"], format="%Y-%m-%d %H:%M:%S")
    return runs.sort_values("date", ascending=False)


def metric_columns(runs: pd.DataFrame) -> list[str]:
    return [
        column
        for column in runs.select_dtypes(include="number").columns
        if column not in METRIC_EXCLUDE_COLUMNS
    ]


@st.cache_data(show_spinner=False)
def dataframe_to_csv(dataframe: pd.DataFrame) -> bytes:
    return dataframe.to_csv(index=False).encode("utf-8")


@st.cache_data(show_spinner=False)
def dataframe_to_json(dataframe: pd.DataFrame) -> bytes:
    return dataframe.to_json(orient="records", date_format="iso", indent=2).encode("utf-8")


@st.cache_data(show_spinner=False)
def dataframe_to_pickle(dataframe: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    dataframe.to_pickle(buffer)
    return buffer.getvalue()


def filter_runs(
    runs: pd.DataFrame,
    metrics: list[str],
    settings: dict[str, Any],
) -> pd.DataFrame:
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

    filtered = runs[
        runs["model"].isin(models)
        & runs["version"].isin(versions)
    ].copy()

    if len(date_range) == 2:
        start, end = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        filtered = filtered[
            (filtered["date"] >= start)
            & (filtered["date"] < end + pd.Timedelta(days=1))
        ]

    st.session_state["summary_metrics"] = selected_metrics
    return filtered


def show_downloads(filtered: pd.DataFrame) -> None:
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


def show_intro(settings: dict[str, Any], db_path: Path) -> None:
    intro = settings["intro"]
    description = intro.get("description", "")
    links = [
        link
        for link in intro.get("links", [])
        if link.get("label") and link.get("url")
    ]
    artifact_root = settings["database"].get("artifact_root", "")

    if description:
        st.markdown(description)

    if links:
        link_markdown = " | ".join(
            f"[{link['label']}]({link['url']})"
            for link in links
        )
        st.markdown(link_markdown)

    info_items = []
    if intro.get("show_database_path", True):
        info_items.append(f"Database: `{db_path}`")
    if intro.get("show_artifact_root", True) and artifact_root:
        info_items.append(f"Artifact root: `{artifact_root}`")
    if info_items:
        st.caption("  |  ".join(info_items))


def show_summary(
    filtered: pd.DataFrame,
    top_items: list[str],
    metrics: list[str],
    aggregations: list[str],
) -> None:
    top_items = [item for item in top_items if item in TOP_SUMMARY_LABELS]
    if top_items:
        top_columns = st.columns(min(4, len(top_items)))
        for index, item in enumerate(top_items):
            if item == "runs":
                value = len(filtered)
            elif item == "versions":
                value = filtered["version"].nunique()
            elif item == "models":
                value = filtered["model"].nunique()
            elif item == "total_runtime" and not filtered.empty:
                value = f"{filtered['runtime'].sum():.4g}"
            else:
                value = "n/a"
            top_columns[index % len(top_columns)].metric(TOP_SUMMARY_LABELS[item], value)

    summary_items = [
        (metric, aggregation)
        for metric in metrics
        for aggregation in aggregations
    ]
    if not summary_items:
        return

    summary_columns = st.columns(min(4, len(summary_items)))
    if filtered.empty:
        for index, (metric, aggregation) in enumerate(summary_items):
            label = f"{SUMMARY_AGGREGATIONS[aggregation]} {metric}"
            summary_columns[index % len(summary_columns)].metric(label, "n/a")
        return

    for index, (metric, aggregation) in enumerate(summary_items):
        label = f"{SUMMARY_AGGREGATIONS[aggregation]} {metric}"
        value = getattr(filtered[metric], aggregation)()
        summary_columns[index % len(summary_columns)].metric(label, f"{value:.4g}")


def tab_summary_options(
    settings: dict[str, Any],
    tab_key: str,
    available_metrics: list[str],
) -> tuple[list[str], list[str], list[str]]:
    default_summary = settings["summaries"]["default"]
    tab_summary = settings["summaries"]["tabs"].get(tab_key, {})
    fallback_top = ["runs", "versions", "models", "total_runtime"]
    fallback_metrics = ["runtime", "memory_hwm"]
    fallback_aggregations = ["mean", "max"]
    top_items = tab_summary.get("top", default_summary.get("top", fallback_top))
    configured_summary_metrics = tab_summary.get(
        "metrics",
        default_summary.get("metrics", fallback_metrics),
    )
    configured_aggregations = tab_summary.get(
        "aggregations",
        default_summary.get("aggregations", fallback_aggregations),
    )
    summary_metrics = configured_metrics(
        configured_summary_metrics,
        available_metrics,
        default_summary.get("metrics", fallback_metrics),
    )
    summary_aggregations = [
        aggregation
        for aggregation in configured_aggregations
        if aggregation in SUMMARY_AGGREGATIONS
    ]
    return top_items, summary_metrics, summary_aggregations


def show_tab_summary(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    tab_key: str,
    available_metrics: list[str],
) -> None:
    top_items, summary_metrics, summary_aggregations = tab_summary_options(
        settings,
        tab_key,
        available_metrics,
    )
    show_summary(filtered, top_items, summary_metrics, summary_aggregations)


def modified_filtered_runs(filtered: pd.DataFrame, tab_key: str) -> pd.DataFrame:
    if "modified" not in filtered.columns:
        return filtered

    include_modified = st.checkbox(
        "Include modified runs",
        value=False,
        key=f"{tab_key}_include_modified_runs",
    )
    if include_modified:
        return filtered
    return filtered[~filtered["modified"]].copy()


def show_versions_tab(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    tab_filtered = modified_filtered_runs(filtered, "versions")
    show_tab_summary(tab_filtered, settings, "versions", metrics)
    show_version_tables(tab_filtered, metrics, plot_height)


def show_models_tab(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    tab_filtered = modified_filtered_runs(filtered, "models")
    show_tab_summary(tab_filtered, settings, "models", metrics)
    show_model_tables(tab_filtered, metrics, plot_height)


def show_all_runs(filtered: pd.DataFrame) -> None:
    st.subheader("Runs")
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    searchable_columns = [
        column
        for column in ["uid", "name", "model", "version", "artifact", "artifact_path"]
        if column in filtered.columns
    ]
    search_text = st.text_input(
        "Search runs",
        placeholder="UID, name, model, version, artifact...",
        key="all_runs_search",
    ).strip()
    table_data = filtered.sort_values("date", ascending=False) if "date" in filtered.columns else filtered
    if search_text and searchable_columns:
        search_mask = pd.Series(False, index=filtered.index)
        for column in searchable_columns:
            search_mask |= filtered[column].fillna("").astype(str).str.contains(
                search_text,
                case=False,
                regex=False,
                na=False,
            )
        table_data = filtered[search_mask]

    if table_data.empty:
        st.info("No runs match the table search.")
        return

    pagination_columns = st.columns([1, 1, 3])
    page_size = pagination_columns[0].selectbox(
        "Rows per page",
        [100, 250, 500, 1000],
        index=1,
        key="all_runs_page_size",
    )
    page_count = max(1, (len(table_data) - 1) // page_size + 1)
    page_number = pagination_columns[1].number_input(
        "Page",
        min_value=1,
        max_value=page_count,
        value=min(st.session_state.get("all_runs_page_number", 1), page_count),
        step=1,
        key="all_runs_page_number",
    )
    start_index = (page_number - 1) * page_size
    end_index = min(start_index + page_size, len(table_data))
    page_data = table_data.iloc[start_index:end_index]
    pagination_columns[2].caption(
        f"Showing {start_index + 1:,}-{end_index:,} of {len(table_data):,} runs"
    )

    st.dataframe(
        page_data,
        use_container_width=True,
        hide_index=True,
        column_config={
            "uid": st.column_config.TextColumn("UID", width="medium"),
            "name": st.column_config.TextColumn("Run", width="large"),
            "date": st.column_config.DatetimeColumn("Date"),
            "density": st.column_config.NumberColumn("Density", format="%.5f"),
            "velocity": st.column_config.NumberColumn("Velocity", format="%.5f"),
            "error": st.column_config.NumberColumn("Error", format="%.5f"),
        },
    )


def run_display_name(row: pd.Series) -> str:
    return f"{row['model']} {row['version']} | {row['name']}"


def run_option_match_index(run_options: pd.DataFrame, pasted_id: str) -> int | None:
    if not pasted_id:
        return None

    pasted_id = pasted_id.strip()
    matches = run_options[
        (run_options["uid"].astype(str) == pasted_id)
        | (run_options["name"].astype(str) == pasted_id)
    ]
    if matches.empty:
        return None
    return int(matches.index[0])


def run_artifact_candidates(row: pd.Series, artifact_root: str) -> list[Path | str]:
    candidates: list[Path | str] = []
    artifact_path = row.get("artifact_path")
    if isinstance(artifact_path, str) and artifact_path:
        candidates.append(artifact_path if artifact_path.startswith("s3://") else Path(artifact_path))

    if artifact_root:
        root = Path(artifact_root)
        candidates.extend([root / str(row["uid"]), root / str(row["name"])])
    return candidates


def first_local_artifact_path(row: pd.Series, artifact_root: str) -> Path | None:
    for candidate in run_artifact_candidates(row, artifact_root):
        if isinstance(candidate, str) and candidate.startswith("s3://"):
            continue

        path = Path(candidate)
        if path.exists():
            return path
        parent = path.parent
        metadata_path = parent / "metadata.json"
        if metadata_path.exists() and any(parent.glob("*.parquet")):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if str(metadata.get("uid", "")) == str(row.get("uid", "")):
                return parent
    return None


def parquet_files_for_run(row: pd.Series, artifact_root: str) -> dict[str, Path]:
    artifact_path = first_local_artifact_path(row, artifact_root)
    if artifact_path is None:
        return {}
    if artifact_path.is_file():
        return {artifact_path.name: artifact_path} if artifact_path.suffix.lower() == ".parquet" else {}
    return {
        parquet_file.name: parquet_file
        for parquet_file in sorted(artifact_path.rglob("*.parquet"))
    }


def render_artifact_file(path: Path) -> None:
    suffix = path.suffix.lower()
    if is_tar_artifact(path):
        render_tar_artifact(path)
        return

    with st.expander(path.name, expanded=False):
        st.caption(str(path))
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            st.image(str(path))
        elif suffix == ".csv":
            st.dataframe(pd.read_csv(path), use_container_width=True)
        elif suffix == ".parquet":
            render_parquet_artifact(path)
        elif suffix in {".pkl", ".pickle"}:
            artifact = pd.read_pickle(path)
            if isinstance(artifact, pd.DataFrame):
                st.dataframe(artifact, use_container_width=True)
            elif isinstance(artifact, pd.Series):
                st.dataframe(artifact.to_frame(), use_container_width=True)
            else:
                st.write(artifact)
        elif suffix in {".json", ".jsonl"}:
            if suffix == ".jsonl":
                st.dataframe(pd.read_json(path, lines=True), use_container_width=True)
            else:
                st.json(json.loads(path.read_text(encoding="utf-8")))
        elif suffix in {".txt", ".log", ".out", ".err", ".yaml", ".yml", ".toml"}:
            st.code(path.read_text(encoding="utf-8", errors="replace"))
        elif suffix == ".html":
            components.html(path.read_text(encoding="utf-8", errors="replace"), height=500, scrolling=True)
        else:
            st.download_button(
                "Download artifact",
                data=path.read_bytes(),
                file_name=path.name,
                use_container_width=True,
            )


def find_time_column(dataframe: pd.DataFrame) -> str | None:
    for column in dataframe.columns:
        if TIME_COLUMN_PATTERN.search(str(column)):
            return str(column)
    return None


def parquet_plot_key(path: Path, column: str) -> str:
    safe_path = re.sub(r"\W+", "_", str(path))
    safe_column = re.sub(r"\W+", "_", column)
    return f"parquet_line_{safe_path}_{safe_column}"


def material_column(dataframe: pd.DataFrame) -> str | None:
    for column in dataframe.columns:
        if MATERIAL_COLUMN_PATTERN.search(str(column)):
            return str(column)
    return None


def split_series_column(column: str, default_thing: str | None = None) -> tuple[str, str]:
    first_part = SERIES_SEPARATOR_PATTERN.split(column, maxsplit=1)[0].lower()
    if first_part in {"material", "mat"}:
        return default_thing or column, column

    parts = [part for part in SERIES_SEPARATOR_PATTERN.split(column) if part]
    if len(parts) >= 2:
        return parts[0], "_".join(parts[1:])
    return default_thing or column, column


def wide_parquet_series(
    dataframe: pd.DataFrame,
    time_column: str,
    default_thing: str | None = None,
) -> dict[str, pd.DataFrame]:
    numeric_columns = [
        column
        for column in dataframe.select_dtypes(include="number").columns
        if str(column) != time_column
    ]
    series_frames: dict[str, list[pd.DataFrame]] = {}
    for column in numeric_columns:
        thing, material = split_series_column(str(column), default_thing)
        series_frame = dataframe[[time_column, column]].rename(columns={column: "value"})
        series_frame["material"] = material
        series_frames.setdefault(thing, []).append(series_frame)
    return {
        thing: pd.concat(frames, ignore_index=True)
        for thing, frames in series_frames.items()
    }


def long_parquet_series(
    dataframe: pd.DataFrame,
    time_column: str,
    material_column_name: str,
) -> dict[str, pd.DataFrame]:
    value_columns = [
        column
        for column in dataframe.select_dtypes(include="number").columns
        if str(column) != time_column
    ]
    return {
        str(column): dataframe[[time_column, material_column_name, column]].rename(
            columns={material_column_name: "material", column: "value"}
        )
        for column in value_columns
    }


def parquet_series_by_thing(
    dataframe: pd.DataFrame,
    time_column: str,
    default_thing: str | None = None,
) -> dict[str, pd.DataFrame]:
    material_column_name = material_column(dataframe)
    if material_column_name is not None:
        return long_parquet_series(dataframe, time_column, material_column_name)
    return wide_parquet_series(dataframe, time_column, default_thing)


def selected_materials(path: Path, thing: str, materials: list[str]) -> list[str]:
    checkbox_columns = st.columns(min(4, len(materials)))
    selected = []
    for index, material in enumerate(materials):
        enabled = checkbox_columns[index % len(checkbox_columns)].checkbox(
            material,
            value=True,
            key=parquet_plot_key(path, f"{thing}_{material}"),
        )
        if enabled:
            selected.append(material)
    return selected


def render_parquet_series_plot(path: Path, thing: str, series_data: pd.DataFrame, time_column: str) -> None:
    materials = sorted(series_data["material"].astype(str).unique())
    st.markdown(f"**{thing}**")
    selected = selected_materials(path, thing, materials)
    if not selected:
        st.info("Select at least one material to plot.")
        return

    plot_data = series_data[series_data["material"].astype(str).isin(selected)]
    fig = px.line(
        plot_data,
        x=time_column,
        y="value",
        color="material",
        markers=False,
        title=f"{path.name}: {thing}",
    )
    fig.update_layout(
        height=420,
        margin={"l": 10, "r": 10, "t": 44, "b": 10},
        xaxis_title=time_column,
        yaxis_title=thing,
    )
    st.plotly_chart(fig, use_container_width=True)


def render_parquet_time_plots(path: Path, dataframe: pd.DataFrame) -> None:
    time_column = find_time_column(dataframe)
    if time_column is None:
        return

    for thing, series_data in parquet_series_by_thing(dataframe, time_column, path.stem).items():
        render_parquet_series_plot(path, thing, series_data, time_column)


def render_parquet_artifact(path: Path) -> None:
    dataframe = pd.read_parquet(path)
    render_parquet_time_plots(path, dataframe)
    st.dataframe(dataframe, use_container_width=True)


def is_tar_artifact(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith((".tar", ".tar.gz", ".tgz"))


def safe_extract_tar(tar: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in tar.getmembers():
        member_path = (destination / member.name).resolve()
        if destination not in member_path.parents and member_path != destination:
            raise ValueError(f"Unsafe path in archive: {member.name}")
    tar.extractall(destination)


def render_tar_artifact(path: Path) -> None:
    st.caption(f"Archive: `{path}`")
    with tarfile.open(path) as tar:
        members = [member for member in tar.getmembers() if member.isfile()]
        st.dataframe(
            pd.DataFrame(
                {
                    "name": [member.name for member in members],
                    "size_bytes": [member.size for member in members],
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            safe_extract_tar(tar, temp_path)
            for artifact_file in sorted(item for item in temp_path.rglob("*") if item.is_file()):
                render_artifact_file(artifact_file)


def show_run_artifacts(row: pd.Series, artifact_root: str) -> None:
    st.subheader("Artifacts")
    candidates = run_artifact_candidates(row, artifact_root)
    if not candidates:
        st.info("No artifact path or artifact root is configured.")
        return

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith("s3://"):
            st.info(f"S3 artifact location: `{candidate}`")
            continue

        path = Path(candidate)
        if not path.exists():
            continue
        if path.is_file():
            render_artifact_file(path)
            return

        artifact_files = [item for item in sorted(path.rglob("*")) if item.is_file()]
        if not artifact_files:
            st.info(f"Artifact directory is empty: `{path}`")
            return

        st.caption(f"Artifact directory: `{path}`")
        for artifact_file in artifact_files:
            render_artifact_file(artifact_file)
        return

    st.info("No local artifacts found for this run.")
    st.caption(
        "Checked: "
        + ", ".join(f"`{candidate}`" for candidate in candidates)
    )


def show_run_detail(filtered: pd.DataFrame, settings: dict[str, Any]) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    run_options = filtered.sort_values(["model", "version", "name"]).reset_index(drop=True)
    pasted_id = st.text_input("Paste run UID or name", value="")
    matched_index = run_option_match_index(run_options, pasted_id)
    if pasted_id and matched_index is None:
        st.warning("No run matched that UID or name in the current filters.")

    selected_index = st.selectbox(
        "Run",
        run_options.index,
        index=matched_index or 0,
        format_func=lambda index: run_display_name(run_options.loc[index]),
    )
    selected_run = run_options.loc[selected_index]

    st.subheader("Results")
    details = (
        selected_run.to_frame(name="value")
        .reset_index()
        .rename(columns={"index": "field"})
    )
    st.dataframe(details, use_container_width=True, hide_index=True)

    show_run_artifacts(selected_run, settings["database"].get("artifact_root", ""))


def build_run_scalar_comparison(top_run: pd.Series, bottom_run: pd.Series, metrics: list[str]) -> pd.DataFrame:
    rows = []
    for metric in metrics:
        top_value = top_run.get(metric)
        bottom_value = bottom_run.get(metric)
        if pd.isna(top_value) or pd.isna(bottom_value):
            delta = None
            ratio = None
        else:
            delta = bottom_value - top_value
            ratio = None if top_value == 0 else bottom_value / top_value
        rows.append(
            {
                "metric": metric,
                "top": top_value,
                "bottom": bottom_value,
                "bottom_minus_top": delta,
                "bottom_over_top": ratio,
            }
        )
    return pd.DataFrame(rows)


def compare_run_plot_key(top_path: Path, bottom_path: Path, thing: str, material: str) -> str:
    key_text = f"{top_path}_{bottom_path}_{thing}_{material}"
    return "compare_run_" + re.sub(r"\W+", "_", key_text)


def selected_compare_materials(
    top_path: Path,
    bottom_path: Path,
    thing: str,
    materials: list[str],
) -> list[str]:
    checkbox_columns = st.columns(min(4, len(materials)))
    selected = []
    for index, material in enumerate(materials):
        enabled = checkbox_columns[index % len(checkbox_columns)].checkbox(
            material,
            value=True,
            key=compare_run_plot_key(top_path, bottom_path, thing, material),
        )
        if enabled:
            selected.append(material)
    return selected


def parquet_thing_series(path: Path) -> tuple[str | None, dict[str, pd.DataFrame]]:
    dataframe = pd.read_parquet(path)
    time_column = find_time_column(dataframe)
    if time_column is None:
        return None, {}
    return time_column, parquet_series_by_thing(dataframe, time_column, path.stem)


def compare_run_parquet_pairs(
    top_run: pd.Series,
    bottom_run: pd.Series,
    artifact_root: str,
) -> list[dict[str, object]]:
    top_files = parquet_files_for_run(top_run, artifact_root)
    bottom_files = parquet_files_for_run(bottom_run, artifact_root)
    pairs = []
    for name in sorted(set(top_files).intersection(bottom_files)):
        top_path = top_files[name]
        bottom_path = bottom_files[name]
        top_time_column, top_groups = parquet_thing_series(top_path)
        bottom_time_column, bottom_groups = parquet_thing_series(bottom_path)
        if top_time_column is None or bottom_time_column is None:
            continue

        shared_things = sorted(set(top_groups).intersection(bottom_groups))
        if not shared_things:
            continue

        pairs.append(
            {
                "name": name,
                "top_path": top_path,
                "bottom_path": bottom_path,
                "top_time_column": top_time_column,
                "bottom_time_column": bottom_time_column,
                "top_groups": top_groups,
                "bottom_groups": bottom_groups,
                "shared_things": shared_things,
            }
        )
    return pairs


def render_compare_run_series_plot(
    top_path: Path,
    bottom_path: Path,
    thing: str,
    top_series: pd.DataFrame,
    bottom_series: pd.DataFrame,
    top_time_column: str,
    bottom_time_column: str,
    top_label: str,
    bottom_label: str,
    plot_height: int,
) -> None:
    top_materials = set(top_series["material"].astype(str).unique())
    bottom_materials = set(bottom_series["material"].astype(str).unique())
    shared_materials = sorted(top_materials.intersection(bottom_materials))
    if not shared_materials:
        st.info(f"No shared materials for `{thing}`.")
        return

    st.markdown(f"**{thing}**")
    selected_materials_for_plot = selected_compare_materials(
        top_path,
        bottom_path,
        thing,
        shared_materials,
    )
    if not selected_materials_for_plot:
        st.info("Select at least one material to plot.")
        return

    figure = go.Figure()
    palette = px.colors.qualitative.Plotly
    color_by_material = {
        material: palette[index % len(palette)]
        for index, material in enumerate(shared_materials)
    }
    for material in selected_materials_for_plot:
        top_material_data = top_series[top_series["material"].astype(str) == material]
        bottom_material_data = bottom_series[bottom_series["material"].astype(str) == material]
        figure.add_trace(
            go.Scatter(
                x=top_material_data[top_time_column],
                y=top_material_data["value"],
                mode="lines",
                name=f"{material} ({top_label})",
                legendgroup=material,
                line={"color": color_by_material[material], "dash": "solid"},
            )
        )
        figure.add_trace(
            go.Scatter(
                x=bottom_material_data[bottom_time_column],
                y=bottom_material_data["value"],
                mode="lines",
                name=f"{material} ({bottom_label})",
                legendgroup=material,
                line={"color": color_by_material[material], "dash": "dash"},
            )
        )

    figure.update_layout(
        height=plot_height,
        margin={"l": 10, "r": 10, "t": 44, "b": 10},
        title=f"{top_path.name}: {thing}",
        xaxis_title=top_time_column,
        yaxis_title=thing,
    )
    st.plotly_chart(figure, use_container_width=True)


def show_compare_run_artifacts(
    top_run: pd.Series,
    bottom_run: pd.Series,
    artifact_root: str,
    plot_height: int,
) -> None:
    top_label = "top"
    bottom_label = "bottom"
    for pair in compare_run_parquet_pairs(top_run, bottom_run, artifact_root):
        top_path = pair["top_path"]
        bottom_path = pair["bottom_path"]
        with st.expander(str(pair["name"]), expanded=False):
            st.caption(f"Top: `{top_path}`")
            st.caption(f"Bottom: `{bottom_path}`")
            for thing in pair["shared_things"]:
                render_compare_run_series_plot(
                    top_path=top_path,
                    bottom_path=bottom_path,
                    thing=thing,
                    top_series=pair["top_groups"][thing],
                    bottom_series=pair["bottom_groups"][thing],
                    top_time_column=pair["top_time_column"],
                    bottom_time_column=pair["bottom_time_column"],
                    top_label=top_label,
                    bottom_label=bottom_label,
                    plot_height=plot_height,
                )


def show_compare_run(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return
    if len(filtered) < 2:
        st.info("At least two runs are needed for a comparison.")
        return

    run_options = filtered.sort_values(["model", "version", "name"]).reset_index(drop=True)
    selector_columns = st.columns(2)
    top_pasted_id = selector_columns[0].text_input("Paste top run UID or name", value="")
    bottom_pasted_id = selector_columns[1].text_input("Paste bottom run UID or name", value="")
    top_matched_index = run_option_match_index(run_options, top_pasted_id)
    bottom_matched_index = run_option_match_index(run_options, bottom_pasted_id)
    if top_pasted_id and top_matched_index is None:
        selector_columns[0].warning("No run matched that UID or name in the current filters.")
    if bottom_pasted_id and bottom_matched_index is None:
        selector_columns[1].warning("No run matched that UID or name in the current filters.")
    top_index = selector_columns[0].selectbox(
        "Top run",
        run_options.index,
        index=top_matched_index or 0,
        format_func=lambda index: run_display_name(run_options.loc[index]),
    )
    bottom_index = selector_columns[1].selectbox(
        "Bottom run",
        run_options.index,
        index=bottom_matched_index or (1 if len(run_options) > 1 else 0),
        format_func=lambda index: run_display_name(run_options.loc[index]),
    )
    top_run = run_options.loc[top_index]
    bottom_run = run_options.loc[bottom_index]
    if top_run["uid"] == bottom_run["uid"]:
        st.info("Choose two different runs.")
        return

    st.subheader("Scalar Comparison")
    color_scheme = select_comparison_color_scheme("compare_run_color_scheme")
    scalar_comparison = build_run_scalar_comparison(top_run, bottom_run, metrics)
    st.dataframe(
        styled_comparison_table(scalar_comparison, settings, color_scheme),
        use_container_width=True,
        hide_index=True,
    )

    artifact_root = settings["database"].get("artifact_root", "")
    if compare_run_parquet_pairs(top_run, bottom_run, artifact_root):
        st.subheader("Artifact Time Series")
        show_compare_run_artifacts(top_run, bottom_run, artifact_root, plot_height)


def aggregate_runs(
    runs: pd.DataFrame,
    group_columns: list[str],
    metrics: list[str],
) -> pd.DataFrame:
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


def show_version_tables(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    export_dataframes = {}
    for version in sorted(filtered["version"].unique(), key=version_sort_key, reverse=True):
        version_runs = filtered[filtered["version"] == version]
        version_table = aggregate_runs(version_runs, ["model"], metrics)
        export_dataframes[f"table_version_{version}"] = version_table
        with st.expander(f"{version} ({len(version_runs)} runs)", expanded=False):
            st.dataframe(
                version_table,
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    export_dataframes.update(show_version_plots(filtered, metrics, plot_height))
    st.divider()
    export_dataframes.update(show_version_cdf_plot(filtered, metrics, plot_height))
    show_export_download(
        "Download version tab data",
        export_dataframes,
        "versions_data.zip",
        "versions_download",
    )


def show_model_tables(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    export_dataframes = {}
    for model in sorted(filtered["model"].unique()):
        model_runs = filtered[filtered["model"] == model]
        model_table = aggregate_runs(model_runs, ["version"], metrics)
        export_dataframes[f"table_model_{model}"] = model_table
        with st.expander(f"{model} ({len(model_runs)} runs)", expanded=False):
            st.dataframe(
                model_table,
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    export_dataframes.update(show_model_version_plot(filtered, metrics, plot_height))
    show_export_download(
        "Download model tab data",
        export_dataframes,
        "models_data.zip",
        "models_download",
    )


def version_sort_key(version: str) -> tuple[int, ...]:
    return tuple(
        int(part)
        for part in str(version).removeprefix("v").split(".")
        if part.isdigit()
    )


def show_version_plots(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> dict[str, pd.DataFrame]:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return {}

    selected_metric = st.selectbox("Plot metric", metrics)

    version_order = sorted(filtered["version"].unique(), key=version_sort_key, reverse=True)
    plot_data = (
        filtered.groupby(["version", "model"], as_index=False)
        .agg(
            mean_value=(selected_metric, "mean"),
            uncertainty=(selected_metric, "std"),
            run_count=("uid", "count"),
        )
        .sort_values(["version", "model"])
    )
    plot_data["uncertainty"] = plot_data["uncertainty"].fillna(0.0)
    plot_data["version"] = pd.Categorical(
        plot_data["version"],
        categories=version_order,
        ordered=True,
    )
    plot_data = plot_data.sort_values(["version", "model"])

    fig = px.line(
        plot_data,
        x="version",
        y="mean_value",
        error_y="uncertainty",
        color="model",
        markers=True,
        hover_data=["model", "version", "mean_value", "uncertainty", "run_count"],
    )
    fig.update_layout(
        height=plot_height,
        margin=dict(l=10, r=10, t=36, b=10),
        title=f"{selected_metric} by version",
        xaxis_title="Version",
        yaxis_title=selected_metric,
    )
    st.plotly_chart(fig, use_container_width=True)
    return {f"plot_version_metric_{selected_metric}": plot_data}


def empirical_cdf(values: pd.Series) -> pd.DataFrame:
    sorted_values = values.sort_values(ignore_index=True)
    return pd.DataFrame(
        {
            "value": sorted_values,
            "cdf": (sorted_values.index + 1) / len(sorted_values),
        }
    )


def model_mean_cdf_data(
    runs: pd.DataFrame,
    metric: str,
    label: str | None = None,
) -> pd.DataFrame:
    model_values = (
        runs.groupby("model", as_index=False)
        .agg(
            value=(metric, "mean"),
            uncertainty=(metric, "std"),
            run_count=("uid", "count"),
        )
        .sort_values("value")
        .reset_index(drop=True)
    )
    model_values["uncertainty"] = model_values["uncertainty"].fillna(0.0)
    model_values["cdf"] = (model_values.index + 1) / len(model_values)
    if label is not None:
        model_values["curve"] = label
    return model_values


def show_version_cdf_plot(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> dict[str, pd.DataFrame]:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return {}

    st.subheader("Cumulative Distribution")
    versions = sorted(filtered["version"].unique(), key=version_sort_key, reverse=True)
    selected_version = st.selectbox("CDF version", versions)
    selected_metric = st.selectbox("CDF metric", metrics)
    version_runs = filtered[filtered["version"] == selected_version]

    if version_runs.empty:
        st.info("No data is available for the selected version.")
        return {}

    model_values = model_mean_cdf_data(version_runs, selected_metric)
    selected_values = model_values["value"]
    stats = pd.DataFrame(
        [
            {
                "statistic": "mean",
                "value": selected_values.mean(),
            },
            {
                "statistic": "std",
                "value": selected_values.std(),
            },
            {
                "statistic": "skew",
                "value": selected_values.skew(),
            },
            {
                "statistic": "kurtosis",
                "value": selected_values.kurtosis(),
            },
        ]
    )
    stats_columns = st.columns(4)
    stats_columns[0].metric("Mean", f"{selected_values.mean():.4g}")
    stats_columns[1].metric("Std", f"{selected_values.std():.4g}")
    stats_columns[2].metric("Skew", f"{selected_values.skew():.4g}")
    stats_columns[3].metric("Kurtosis", f"{selected_values.kurtosis():.4g}")

    fig = px.line(
        model_values,
        x="value",
        y="cdf",
        text="model",
        markers=True,
        hover_data=["model", "run_count", "value", "uncertainty", "cdf"],
        title=f"{selected_version}: model-averaged {selected_metric} empirical CDF",
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(
        height=plot_height,
        margin=dict(l=10, r=10, t=36, b=10),
        xaxis_title=selected_metric,
        yaxis_title="Cumulative probability",
        yaxis_range=[0, 1.02],
    )
    st.plotly_chart(fig, use_container_width=True)
    return {
        f"cdf_version_{selected_version}_{selected_metric}": model_values,
        f"cdf_stats_version_{selected_version}_{selected_metric}": stats,
    }


def show_model_version_plot(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> dict[str, pd.DataFrame]:
    selected_model = st.selectbox("Plot model", sorted(filtered["model"].unique()))
    selected_metric = st.selectbox("Model plot metric", metrics)
    model_data = filtered[filtered["model"] == selected_model]

    version_order = sorted(model_data["version"].unique(), key=version_sort_key)
    plot_data = (
        model_data.groupby("version", as_index=False)
        .agg(
            mean_value=(selected_metric, "mean"),
            uncertainty=(selected_metric, "std"),
            run_count=("uid", "count"),
        )
        .sort_values("version")
    )
    plot_data["uncertainty"] = plot_data["uncertainty"].fillna(0.0)
    plot_data["version"] = pd.Categorical(
        plot_data["version"],
        categories=version_order,
        ordered=True,
    )
    plot_data = plot_data.sort_values("version")

    fig = px.line(
        plot_data,
        x="version",
        y="mean_value",
        error_y="uncertainty",
        markers=True,
        hover_data=["version", "mean_value", "uncertainty", "run_count"],
        title=f"{selected_model}: {selected_metric} by version",
    )
    fig.update_layout(
        height=plot_height,
        margin=dict(l=10, r=10, t=36, b=10),
        xaxis_title="Version",
        yaxis_title=selected_metric,
    )
    st.plotly_chart(fig, use_container_width=True)
    return {f"plot_model_{selected_model}_{selected_metric}": plot_data}


def build_collection_comparison(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    metrics: list[str],
) -> pd.DataFrame:
    base_runs = base_runs.copy()
    test_runs = test_runs.copy()
    base_runs[COLLECTION_LABEL_COLUMN] = base_label
    test_runs[COLLECTION_LABEL_COLUMN] = test_label
    comparison_data = pd.concat([base_runs, test_runs], ignore_index=True)

    means = comparison_data.groupby(["model", COLLECTION_LABEL_COLUMN], as_index=False)[metrics].mean()
    stds = comparison_data.groupby(["model", COLLECTION_LABEL_COLUMN], as_index=False)[metrics].std()
    counts = comparison_data.groupby(["model", COLLECTION_LABEL_COLUMN], as_index=False).agg(
        run_count=("uid", "count")
    )
    mean_wide = means.pivot(index="model", columns=COLLECTION_LABEL_COLUMN, values=metrics)
    std_wide = stds.pivot(index="model", columns=COLLECTION_LABEL_COLUMN, values=metrics).fillna(0.0)
    count_wide = counts.pivot(index="model", columns=COLLECTION_LABEL_COLUMN, values="run_count")
    shared_models = [
        model
        for model in mean_wide.index
        if all((metric, base_label) in mean_wide.columns for metric in metrics)
        and all((metric, test_label) in mean_wide.columns for metric in metrics)
        and mean_wide.loc[model].notna().all()
    ]

    rows = []
    for model in shared_models:
        row = {
            "model": model,
            f"{base_label}_runs": int(count_wide.loc[model, base_label]),
            f"{test_label}_runs": int(count_wide.loc[model, test_label]),
        }
        for metric in metrics:
            base_std = std_wide.loc[model, (metric, base_label)]
            test_std = std_wide.loc[model, (metric, test_label)]
            base_count = count_wide.loc[model, base_label]
            test_count = count_wide.loc[model, test_label]
            row[f"delta_{metric}"] = (
                mean_wide.loc[model, (metric, test_label)]
                - mean_wide.loc[model, (metric, base_label)]
            )
            row[f"uncertainty_{metric}"] = (
                (base_std ** 2 / base_count) + (test_std ** 2 / test_count)
            ) ** 0.5
        rows.append(row)

    return pd.DataFrame(rows).sort_values("model")


def build_version_comparison(
    filtered: pd.DataFrame,
    base_version: str,
    new_version: str,
    metrics: list[str],
) -> pd.DataFrame:
    return build_collection_comparison(
        base_runs=filtered[filtered["version"] == base_version],
        base_label=base_version,
        test_runs=filtered[filtered["version"] == new_version],
        test_label=new_version,
        metrics=metrics,
    )


def comparison_export_dataframes(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    metrics: list[str],
    comparison: pd.DataFrame,
    selected_metric: str,
    plot_data: pd.DataFrame,
    cdf_dataframes: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    return {
        "metadata": comparison_metadata(base_label, test_label, base_runs, test_runs),
        "coverage": comparison_coverage(base_runs, base_label, test_runs, test_label),
        "comparison_table_wide": comparison,
        "all_metric_model_deltas": build_collection_metric_deltas(
            base_runs,
            base_label,
            test_runs,
            test_label,
            metrics,
        ),
        f"visible_bar_delta_{selected_metric}": plot_data,
        **cdf_dataframes,
    }


def show_version_comparison(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    versions = sorted(filtered["version"].unique(), key=version_sort_key)
    if len(versions) < 2:
        st.info("At least two versions are needed for a comparison.")
        return

    version_columns = st.columns(2)
    base_version = version_columns[0].selectbox(
        "Null / base version",
        versions,
        index=0,
    )
    new_version = version_columns[1].selectbox(
        "Test version",
        versions,
        index=1,
    )

    if base_version == new_version:
        st.info("Choose two different versions.")
        return

    base_runs = filtered[filtered["version"] == base_version]
    test_runs = filtered[filtered["version"] == new_version]
    comparison = build_version_comparison(
        filtered=filtered,
        base_version=base_version,
        new_version=new_version,
        metrics=metrics,
    )
    if comparison.empty:
        st.info("No models are present in both selected versions.")
        return

    color_scheme = select_comparison_color_scheme("compare_versions_color_scheme")
    st.dataframe(
        styled_comparison_table(comparison, settings, color_scheme),
        use_container_width=True,
        hide_index=True,
    )

    selected_metric = st.selectbox("Delta metric", metrics)
    delta_column = f"delta_{selected_metric}"
    uncertainty_column = f"uncertainty_{selected_metric}"
    plot_data = comparison.sort_values(delta_column)
    fig = px.bar(
        plot_data,
        x="model",
        y=delta_column,
        error_y=uncertainty_column,
        color=delta_column,
        color_continuous_scale="RdBu",
        title=f"{selected_metric} delta: {new_version} - {base_version}",
    )
    fig.update_layout(
        height=plot_height,
        margin=dict(l=10, r=10, t=44, b=10),
        xaxis_title="Model",
        yaxis_title=delta_column,
        coloraxis_showscale=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    show_comparison_cdf_plot(
        null_runs=base_runs,
        test_runs=test_runs,
        metrics=metrics,
        plot_height=plot_height,
        null_label=f"Null: {base_version}",
        test_label=f"Test: {new_version}",
        key_prefix="compare_versions",
        settings=settings,
        color_scheme=color_scheme,
    )
    st.download_button(
        "Download calculated mean differences CSV",
        data=dataframe_to_csv(
            build_collection_metric_deltas(
                base_runs,
                base_version,
                test_runs,
                new_version,
                metrics,
            )
        ),
        file_name=(
            f"mean_differences_{export_name(base_version)}_to_"
            f"{export_name(new_version)}.csv"
        ),
        mime="text/csv",
        key="compare_versions_mean_differences_download",
        use_container_width=True,
    )


def show_comparison_cdf_plot(
    null_runs: pd.DataFrame,
    test_runs: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
    null_label: str,
    test_label: str,
    key_prefix: str,
    settings: dict[str, Any],
    color_scheme: str,
) -> dict[str, pd.DataFrame]:
    st.subheader("Cumulative Distribution")
    selected_metric = st.selectbox(
        "CDF comparison metric",
        metrics,
        key=f"{key_prefix}_cdf_metric",
    )

    if null_runs.empty or test_runs.empty:
        st.info("Both selected collections need data.")
        return {}

    null_cdf = model_mean_cdf_data(null_runs, selected_metric, label=null_label)
    test_cdf = model_mean_cdf_data(test_runs, selected_metric, label=test_label)
    cdf_data = pd.concat([null_cdf, test_cdf], ignore_index=True)

    null_values = null_cdf["value"]
    test_values = test_cdf["value"]
    stats = pd.DataFrame(
        [
            {
                "statistic": "mean",
                "null": null_values.mean(),
                "test": test_values.mean(),
                "delta": test_values.mean() - null_values.mean(),
            },
            {
                "statistic": "std",
                "null": null_values.std(),
                "test": test_values.std(),
                "delta": test_values.std() - null_values.std(),
            },
            {
                "statistic": "skew",
                "null": null_values.skew(),
                "test": test_values.skew(),
                "delta": test_values.skew() - null_values.skew(),
            },
            {
                "statistic": "kurtosis",
                "null": null_values.kurtosis(),
                "test": test_values.kurtosis(),
                "delta": test_values.kurtosis() - null_values.kurtosis(),
            },
        ]
    )
    st.dataframe(
        styled_comparison_table(stats, settings, color_scheme),
        use_container_width=True,
        hide_index=True,
        column_config={
            "null": st.column_config.NumberColumn(null_label, format="%.5g"),
            "test": st.column_config.NumberColumn(test_label, format="%.5g"),
            "delta": st.column_config.NumberColumn("Delta", format="%.5g"),
        },
    )

    fig = px.line(
        cdf_data,
        x="value",
        y="cdf",
        color="curve",
        text="model",
        markers=True,
        hover_data=["curve", "model", "run_count", "value", "uncertainty", "cdf"],
        title=f"Model-averaged {selected_metric} empirical CDF",
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(
        height=plot_height,
        margin=dict(l=10, r=10, t=36, b=10),
        xaxis_title=selected_metric,
        yaxis_title="Cumulative probability",
        yaxis_range=[0, 1.02],
    )
    st.plotly_chart(fig, use_container_width=True)
    return {
        f"cdf_points_{selected_metric}": cdf_data,
        f"cdf_stats_{selected_metric}": stats,
    }


def collection_parameter_columns(
    runs: pd.DataFrame,
    metrics: list[str],
) -> list[str]:
    excluded_columns = set(metrics)
    preferred_columns = [
        "version",
        "date",
        "artifact",
        "artifact_path",
        "git_commit",
        "commit",
        "git_branch",
        "branch",
        "git_tag",
        "tag",
        "job_name",
        "hpc_system",
        "scheduler",
        "queue",
        "model",
        "modified",
    ]
    available_columns = [
        column
        for column in runs.columns
        if column not in excluded_columns and not runs[column].dropna().empty
    ]
    ordered_columns = [
        column
        for column in preferred_columns
        if column in available_columns
    ]
    ordered_columns.extend(
        sorted(column for column in available_columns if column not in ordered_columns)
    )
    return ordered_columns


def compact_collection_label(field: str, match_mode: str, values: Sequence[Any]) -> str:
    clean_values = [str(value) for value in values if str(value)]
    if not clean_values:
        return f"{field}: empty"
    if len(clean_values) == 1:
        return f"{field} {match_mode} {clean_values[0]}"
    first_values = ", ".join(clean_values[:3])
    if len(clean_values) > 3:
        first_values = f"{first_values}, +{len(clean_values) - 3}"
    return f"{field} {match_mode} {first_values}"


def unique_string_values(runs: pd.DataFrame, field: str) -> list[str]:
    return sorted(
        runs[field].dropna().astype(str).unique(),
        key=lambda value: value.lower(),
    )


def select_datetime_collection(
    filtered: pd.DataFrame,
    field: str,
    prefix: str,
    label: str,
) -> tuple[str, pd.DataFrame]:
    values = pd.to_datetime(filtered[field], errors="coerce")
    valid_values = values.dropna()
    if valid_values.empty:
        st.info(f"`{field}` has no datetime values.")
        return f"{label} {field}", filtered.iloc[0:0].copy()

    min_date = valid_values.min().date()
    max_date = valid_values.max().date()
    selected_range = st.date_input(
        f"{label} window",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        key=f"{prefix}_date_window",
    )
    if len(selected_range) != 2:
        return f"{label} {field}", filtered.iloc[0:0].copy()

    start = pd.to_datetime(selected_range[0])
    end = pd.to_datetime(selected_range[1]) + pd.Timedelta(days=1)
    selected_runs = filtered[(values >= start) & (values < end)].copy()
    default_name = f"{field} {selected_range[0]} to {selected_range[1]}"
    collection_name = st.text_input(
        f"{label} name",
        value=default_name,
        key=f"{prefix}_date_name",
    )
    return collection_name, selected_runs


def select_bool_collection(
    filtered: pd.DataFrame,
    field: str,
    prefix: str,
    label: str,
) -> tuple[str, pd.DataFrame]:
    values = sorted(filtered[field].dropna().unique())
    selected_values = st.multiselect(
        f"{label} values",
        values,
        default=values[:1],
        key=f"{prefix}_bool_values",
    )
    selected_runs = filtered[filtered[field].isin(selected_values)].copy()
    default_name = compact_collection_label(field, "is", selected_values)
    collection_name = st.text_input(
        f"{label} name",
        value=default_name,
        key=f"{prefix}_bool_name",
    )
    return collection_name, selected_runs


def string_collection_mask(
    values: pd.Series,
    match_mode: str,
    selected_values: Sequence[str],
    free_text: str,
) -> pd.Series:
    string_values = values.fillna("").astype(str)
    if match_mode == "Exact values":
        return string_values.isin(selected_values)
    if match_mode == "Starts with":
        return string_values.str.startswith(free_text, na=False)
    if match_mode == "Contains":
        return string_values.str.contains(free_text, case=False, regex=False, na=False)
    if match_mode == "Regex":
        try:
            return string_values.str.contains(free_text, case=False, regex=True, na=False)
        except re.error:
            st.warning(f"`{free_text}` is not a valid regular expression.")
            return pd.Series(False, index=values.index)
    if match_mode == "Non-empty":
        return string_values.str.len() > 0
    return pd.Series(False, index=values.index)


def select_string_collection(
    filtered: pd.DataFrame,
    field: str,
    prefix: str,
    label: str,
    match_mode: str,
    default_exact_index: int,
) -> tuple[str, pd.DataFrame]:
    value_options = unique_string_values(filtered, field)
    selected_values: list[str] = []
    free_text = ""
    if match_mode == "Exact values":
        default_values = value_options[default_exact_index:default_exact_index + 1]
        selected_values = st.multiselect(
            f"{label} values",
            value_options,
            default=default_values,
            key=f"{prefix}_exact_values",
        )
        default_name = compact_collection_label(field, "is", selected_values)
    elif match_mode in {"Starts with", "Contains", "Regex"}:
        free_text = st.text_input(
            f"{label} match text",
            value="",
            key=f"{prefix}_match_text",
        )
        default_name = compact_collection_label(field, match_mode.lower(), [free_text])
    else:
        default_name = f"{field} non-empty"

    mask = string_collection_mask(
        filtered[field],
        match_mode,
        selected_values,
        free_text,
    )
    selected_runs = filtered[mask].copy()
    collection_name = st.text_input(
        f"{label} name",
        value=default_name,
        key=f"{prefix}_string_name",
    )
    return collection_name, selected_runs


def select_collection_runs(
    filtered: pd.DataFrame,
    field: str,
    prefix: str,
    label: str,
    match_mode: str,
    default_exact_index: int,
) -> tuple[str, pd.DataFrame]:
    if pd.api.types.is_datetime64_any_dtype(filtered[field]):
        return select_datetime_collection(filtered, field, prefix, label)
    if pd.api.types.is_bool_dtype(filtered[field]):
        return select_bool_collection(filtered, field, prefix, label)
    return select_string_collection(
        filtered,
        field,
        prefix,
        label,
        match_mode,
        default_exact_index,
    )


def show_collection_comparison_result(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
    key_prefix: str,
) -> None:
    if base_runs.empty or test_runs.empty:
        st.info("Both selected collections need data.")
        return

    comparison = build_collection_comparison(
        base_runs=base_runs,
        base_label=base_label,
        test_runs=test_runs,
        test_label=test_label,
        metrics=metrics,
    )
    if comparison.empty:
        st.info("No models are present in both selected collections.")
        return

    count_columns = st.columns(2)
    count_columns[0].metric(f"{base_label} runs", len(base_runs))
    count_columns[1].metric(f"{test_label} runs", len(test_runs))

    color_scheme = select_comparison_color_scheme(f"{key_prefix}_color_scheme")
    st.dataframe(
        styled_comparison_table(comparison, settings, color_scheme),
        use_container_width=True,
        hide_index=True,
    )

    selected_metric = st.selectbox(
        "Delta metric",
        metrics,
        key=f"{key_prefix}_delta_metric",
    )
    delta_column = f"delta_{selected_metric}"
    uncertainty_column = f"uncertainty_{selected_metric}"
    plot_data = comparison.sort_values(delta_column)
    fig = px.bar(
        plot_data,
        x="model",
        y=delta_column,
        error_y=uncertainty_column,
        color=delta_column,
        color_continuous_scale="RdBu",
        title=f"{selected_metric} delta: {test_label} - {base_label}",
    )
    fig.update_layout(
        height=plot_height,
        margin=dict(l=10, r=10, t=44, b=10),
        xaxis_title="Model",
        yaxis_title=delta_column,
        coloraxis_showscale=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    show_comparison_cdf_plot(
        null_runs=base_runs,
        test_runs=test_runs,
        metrics=metrics,
        plot_height=plot_height,
        null_label=f"Null: {base_label}",
        test_label=f"Test: {test_label}",
        key_prefix=key_prefix,
        settings=settings,
        color_scheme=color_scheme,
    )
    st.download_button(
        "Download calculated mean differences CSV",
        data=dataframe_to_csv(
            build_collection_metric_deltas(
                base_runs,
                base_label,
                test_runs,
                test_label,
                metrics,
            )
        ),
        file_name=(
            f"mean_differences_{export_name(base_label)}_to_"
            f"{export_name(test_label)}.csv"
        ),
        mime="text/csv",
        key="compare_collection_mean_differences_download",
        use_container_width=True,
    )


def show_compare_collection(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return
    if not metrics:
        st.info("No numeric metrics are available for comparison.")
        return

    parameter_columns = collection_parameter_columns(filtered, metrics)
    if not parameter_columns:
        st.info("No collection parameters are available.")
        return

    selected_field = st.selectbox(
        "Collection parameter",
        parameter_columns,
        key="compare_collection_parameter",
    )
    match_mode = "Exact values"
    if (
        not pd.api.types.is_datetime64_any_dtype(filtered[selected_field])
        and not pd.api.types.is_bool_dtype(filtered[selected_field])
    ):
        match_mode = st.selectbox(
            "Match",
            ["Exact values", "Starts with", "Contains", "Regex", "Non-empty"],
            key="compare_collection_match_mode",
        )

    collection_columns = st.columns(2)
    with collection_columns[0]:
        base_label, base_runs = select_collection_runs(
            filtered=filtered,
            field=selected_field,
            prefix="compare_collection_base",
            label="Null / base collection",
            match_mode=match_mode,
            default_exact_index=0,
        )
    with collection_columns[1]:
        test_label, test_runs = select_collection_runs(
            filtered=filtered,
            field=selected_field,
            prefix="compare_collection_test",
            label="Test collection",
            match_mode=match_mode,
            default_exact_index=1,
        )

    if base_label == test_label:
        st.info("Choose different collection names.")
        return

    show_collection_comparison_result(
        base_runs=base_runs,
        base_label=base_label,
        test_runs=test_runs,
        test_label=test_label,
        settings=settings,
        metrics=metrics,
        plot_height=plot_height,
        key_prefix="compare_collection",
    )


def show_pie_charts(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    slice_by = st.selectbox("Slice by", ["model", "version"])
    value_choice = st.selectbox(
        "Pie value",
        ["run_count", *[f"sum_{metric}" for metric in metrics]],
        format_func=lambda value: "Run count" if value == "run_count" else value,
    )

    if value_choice == "run_count":
        pie_data = (
            filtered.groupby(slice_by, as_index=False)
            .agg(value=("uid", "count"))
            .sort_values("value", ascending=False)
        )
        value_label = "run_count"
    else:
        metric = value_choice.removeprefix("sum_")
        pie_data = (
            filtered.groupby(slice_by, as_index=False)
            .agg(value=(metric, "sum"))
            .sort_values("value", ascending=False)
        )
        value_label = value_choice

    fig = px.pie(
        pie_data,
        names=slice_by,
        values="value",
        hole=0.35,
        title=f"{value_label} by {slice_by}",
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(height=plot_height, margin=dict(l=10, r=10, t=44, b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        pie_data.rename(columns={"value": value_label}),
        use_container_width=True,
        hide_index=True,
    )


def cli_settings_path(argv: Sequence[str] | None = None) -> str | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--settings")
    args, _ = parser.parse_known_args(argv)
    return args.settings


def main(settings_path: str | Path | None = None) -> None:
    try:
        settings = load_settings(settings_path or cli_settings_path())
    except FileNotFoundError as error:
        st.set_page_config(page_title="QA Tool", layout="wide")
        st.error(str(error))
        return

    page_title = settings["page"]["title"]
    plot_height = settings["plots"]["height"]

    st.set_page_config(page_title=page_title, layout=settings["page"]["layout"])
    st.title(page_title)

    db_path = Path(settings["database"]["path"])
    if not db_path.exists():
        st.error(f"Could not find {db_path}. Run `uv run python -m qa_tool.load_dummy_data` first.")
        return

    show_intro(settings, db_path)

    database_columns = settings["database"].get("columns", {})
    try:
        runs = load_runs(
            str(db_path),
            database_columns.get("model", "model"),
            database_columns.get("version", "version"),
        )
    except ValueError as error:
        st.error(str(error))
        return
    metrics = metric_columns(runs)
    filtered = filter_runs(runs, metrics, settings)
    metrics = st.session_state.get("summary_metrics", metrics)

    show_downloads(filtered)

    available_tabs = [
        (
            "all_runs",
            "All Runs",
            lambda: (
                show_tab_summary(filtered, settings, "all_runs", metrics),
                show_all_runs(filtered),
            ),
        ),
        (
            "versions",
            "Versions",
            lambda: show_versions_tab(filtered, settings, metrics, plot_height),
        ),
        (
            "models",
            "Models",
            lambda: show_models_tab(filtered, settings, metrics, plot_height),
        ),
        (
            "compare_versions",
            "Compare Versions",
            lambda: (
                show_tab_summary(filtered, settings, "compare_versions", metrics),
                show_version_comparison(filtered, settings, metrics, plot_height),
            ),
        ),
        (
            "compare_collection",
            "Compare Collection",
            lambda: (
                show_tab_summary(filtered, settings, "compare_collection", metrics),
                show_compare_collection(filtered, settings, metrics, plot_height),
            ),
        ),
        (
            "compare_run",
            "Compare Run",
            lambda: show_compare_run(filtered, settings, metrics, plot_height),
        ),
        (
            "pie_charts",
            "Pie Charts",
            lambda: (
                show_tab_summary(filtered, settings, "pie_charts", metrics),
                show_pie_charts(filtered, metrics, plot_height),
            ),
        ),
        (
            "run_detail",
            "Run Detail",
            lambda: (
                show_tab_summary(filtered, settings, "run_detail", metrics),
                show_run_detail(filtered, settings),
            ),
        ),
    ]
    enabled_tabs = [
        (label, renderer)
        for key, label, renderer in available_tabs
        if settings["tabs"].get(key, True)
    ]
    for tab, (_, renderer) in zip(st.tabs([label for label, _ in enabled_tabs]), enabled_tabs):
        with tab:
            renderer()


if __name__ == "__main__":
    main()
