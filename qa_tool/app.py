from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine


DB_PATH = Path("runs.db")
METRIC_EXCLUDE_COLUMNS = {"uid", "name", "model", "version", "date"}
SUMMARY_AGGREGATIONS = {
    "mean": "Mean",
    "min": "Min",
    "max": "Max",
}


@st.cache_data(show_spinner=False)
def load_runs(db_path: str) -> pd.DataFrame:
    engine = create_engine(f"sqlite:///{db_path}")
    runs = pd.read_sql_table("runs", engine)
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


def filter_runs(runs: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
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
        selected_metrics = st.multiselect("Table metrics", metrics, default=metrics)
        summary_metrics = st.multiselect(
            "Summary metrics",
            metrics,
            default=[metric for metric in ["runtime", "memory_hwm"] if metric in metrics],
        )
        summary_aggregations = st.multiselect(
            "Summary aggregations",
            list(SUMMARY_AGGREGATIONS),
            default=["mean", "max"],
            format_func=SUMMARY_AGGREGATIONS.get,
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
    st.session_state["summary_card_metrics"] = summary_metrics
    st.session_state["summary_card_aggregations"] = summary_aggregations
    return filtered


def show_downloads(filtered: pd.DataFrame) -> None:
    with st.expander("Downloads", expanded=False):
        csv_column, json_column, dataframe_column = st.columns(3)
        csv_column.download_button(
            "Download CSV",
            data=dataframe_to_csv(filtered),
            file_name="filtered_runs.csv",
            mime="text/csv",
            disabled=filtered.empty,
            use_container_width=True,
        )
        json_column.download_button(
            "Download JSON",
            data=dataframe_to_json(filtered),
            file_name="filtered_runs.json",
            mime="application/json",
            disabled=filtered.empty,
            use_container_width=True,
        )
        dataframe_column.download_button(
            "Download DataFrame",
            data=dataframe_to_pickle(filtered),
            file_name="filtered_runs.pkl",
            mime="application/octet-stream",
            disabled=filtered.empty,
            use_container_width=True,
        )


def show_summary(
    filtered: pd.DataFrame,
    metrics: list[str],
    aggregations: list[str],
) -> None:
    top_columns = st.columns(4)
    if filtered.empty:
        top_columns[0].metric("Runs", 0)
        top_columns[1].metric("Versions", 0)
        top_columns[2].metric("Models", 0)
        top_columns[3].metric("Total runtime", "n/a")
    else:
        top_columns[0].metric("Runs", len(filtered))
        top_columns[1].metric("Versions", filtered["version"].nunique())
        top_columns[2].metric("Models", filtered["model"].nunique())
        top_columns[3].metric("Total runtime", f"{filtered['runtime'].sum():.4g}")

    summary_items = [
        (metric, aggregation)
        for metric in metrics
        for aggregation in aggregations
    ]
    if not summary_items:
        st.info("Choose at least one summary metric and aggregation.")
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


def show_all_runs(filtered: pd.DataFrame) -> None:
    st.subheader("Runs")
    st.dataframe(
        filtered,
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
            **{f"min_{metric}": (metric, "min") for metric in metrics},
            **{f"max_{metric}": (metric, "max") for metric in metrics},
        )
        .sort_values(group_columns)
    )


def show_version_tables(filtered: pd.DataFrame, metrics: list[str]) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    for version in sorted(filtered["version"].unique()):
        version_runs = filtered[filtered["version"] == version]
        with st.expander(f"{version} ({len(version_runs)} runs)", expanded=False):
            st.dataframe(
                aggregate_runs(version_runs, ["model"], metrics),
                use_container_width=True,
                hide_index=True,
            )


def show_model_tables(filtered: pd.DataFrame, metrics: list[str]) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    for model in sorted(filtered["model"].unique()):
        model_runs = filtered[filtered["model"] == model]
        with st.expander(f"{model} ({len(model_runs)} runs)", expanded=False):
            st.dataframe(
                aggregate_runs(model_runs, ["version"], metrics),
                use_container_width=True,
                hide_index=True,
            )


def version_sort_key(version: str) -> tuple[int, ...]:
    return tuple(
        int(part)
        for part in version.removeprefix("v").split(".")
        if part.isdigit()
    )


def show_version_plots(filtered: pd.DataFrame, metrics: list[str]) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    selected_metric = st.selectbox("Plot metric", metrics)

    version_order = sorted(filtered["version"].unique(), key=version_sort_key)
    plot_data = (
        filtered.groupby(["version", "model"], as_index=False)[selected_metric]
        .mean()
        .sort_values(["version", "model"])
    )
    plot_data["version"] = pd.Categorical(
        plot_data["version"],
        categories=version_order,
        ordered=True,
    )
    plot_data = plot_data.sort_values(["version", "model"])

    fig = px.line(
        plot_data,
        x="version",
        y=selected_metric,
        color="model",
        markers=True,
        hover_data=["model", "version", selected_metric],
    )
    fig.update_layout(
        height=520,
        margin=dict(l=10, r=10, t=36, b=10),
        title=f"{selected_metric} by version",
        xaxis_title="Version",
        yaxis_title=selected_metric,
    )
    st.plotly_chart(fig, use_container_width=True)


def show_pie_charts(filtered: pd.DataFrame, metrics: list[str]) -> None:
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
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=44, b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        pie_data.rename(columns={"value": value_label}),
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    st.set_page_config(page_title="Shock Bubble Interaction Run Database", layout="wide")
    st.title("Shock Bubble Interaction Run Database")

    if not DB_PATH.exists():
        st.error(f"Could not find {DB_PATH}. Run `uv run python sqlite_store.py` first.")
        return

    runs = load_runs(str(DB_PATH))
    metrics = metric_columns(runs)
    filtered = filter_runs(runs, metrics)
    metrics = st.session_state.get("summary_metrics", metrics)
    summary_card_metrics = st.session_state.get("summary_card_metrics", [])
    summary_card_aggregations = st.session_state.get("summary_card_aggregations", [])

    show_summary(filtered, summary_card_metrics, summary_card_aggregations)
    show_downloads(filtered)

    tab_runs, tab_versions, tab_models, tab_plots, tab_pies = st.tabs(
        ["All Runs", "Versions", "Models", "Version Plots", "Pie Charts"]
    )
    with tab_runs:
        show_all_runs(filtered)
    with tab_versions:
        show_version_tables(filtered, metrics)
    with tab_models:
        show_model_tables(filtered, metrics)
    with tab_plots:
        show_version_plots(filtered, metrics)
    with tab_pies:
        show_pie_charts(filtered, metrics)


if __name__ == "__main__":
    main()
