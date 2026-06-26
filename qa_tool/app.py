from __future__ import annotations

import json
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
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


def run_display_name(row: pd.Series) -> str:
    return f"{row['model']} {row['version']} | {row['name']}"


def run_artifact_candidates(row: pd.Series, artifact_root: str) -> list[Path | str]:
    candidates: list[Path | str] = []
    artifact_path = row.get("artifact_path")
    if isinstance(artifact_path, str) and artifact_path:
        candidates.append(artifact_path if artifact_path.startswith("s3://") else Path(artifact_path))

    if artifact_root:
        root = Path(artifact_root)
        candidates.extend([root / str(row["uid"]), root / str(row["name"])])
    return candidates


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
            st.dataframe(pd.read_parquet(path), use_container_width=True)
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
    matched_index = None
    if pasted_id:
        pasted_id = pasted_id.strip()
        matches = run_options[
            (run_options["uid"].astype(str) == pasted_id)
            | (run_options["name"].astype(str) == pasted_id)
        ]
        if matches.empty:
            st.warning("No run matched that UID or name in the current filters.")
        else:
            matched_index = int(matches.index[0])

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

    for version in sorted(filtered["version"].unique()):
        version_runs = filtered[filtered["version"] == version]
        with st.expander(f"{version} ({len(version_runs)} runs)", expanded=False):
            st.dataframe(
                aggregate_runs(version_runs, ["model"], metrics),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    show_version_plots(filtered, metrics, plot_height)
    st.divider()
    show_version_cdf_plot(filtered, metrics, plot_height)


def show_model_tables(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> None:
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

    st.divider()
    show_model_version_plot(filtered, metrics, plot_height)


def version_sort_key(version: str) -> tuple[int, ...]:
    return tuple(
        int(part)
        for part in version.removeprefix("v").split(".")
        if part.isdigit()
    )


def show_version_plots(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    selected_metric = st.selectbox("Plot metric", metrics)

    version_order = sorted(filtered["version"].unique(), key=version_sort_key)
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
) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    st.subheader("Cumulative Distribution")
    versions = sorted(filtered["version"].unique(), key=version_sort_key)
    selected_version = st.selectbox("CDF version", versions)
    selected_metric = st.selectbox("CDF metric", metrics)
    version_runs = filtered[filtered["version"] == selected_version]

    if version_runs.empty:
        st.info("No data is available for the selected version.")
        return

    model_values = model_mean_cdf_data(version_runs, selected_metric)
    selected_values = model_values["value"]
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


def show_model_version_plot(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> None:
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


def build_version_comparison(
    filtered: pd.DataFrame,
    base_version: str,
    new_version: str,
    metrics: list[str],
) -> pd.DataFrame:
    comparison_data = filtered[filtered["version"].isin([base_version, new_version])]
    means = comparison_data.groupby(["model", "version"], as_index=False)[metrics].mean()
    stds = comparison_data.groupby(["model", "version"], as_index=False)[metrics].std()
    counts = comparison_data.groupby(["model", "version"], as_index=False).agg(
        run_count=("uid", "count")
    )
    mean_wide = means.pivot(index="model", columns="version", values=metrics)
    std_wide = stds.pivot(index="model", columns="version", values=metrics).fillna(0.0)
    count_wide = counts.pivot(index="model", columns="version", values="run_count")
    shared_models = [
        model
        for model in mean_wide.index
        if all((metric, base_version) in mean_wide.columns for metric in metrics)
        and all((metric, new_version) in mean_wide.columns for metric in metrics)
        and mean_wide.loc[model].notna().all()
    ]

    rows = []
    for model in shared_models:
        row = {"model": model}
        for metric in metrics:
            base_std = std_wide.loc[model, (metric, base_version)]
            new_std = std_wide.loc[model, (metric, new_version)]
            base_count = count_wide.loc[model, base_version]
            new_count = count_wide.loc[model, new_version]
            row[f"delta_{metric}"] = (
                mean_wide.loc[model, (metric, new_version)]
                - mean_wide.loc[model, (metric, base_version)]
            )
            row[f"uncertainty_{metric}"] = (
                (base_std ** 2 / base_count) + (new_std ** 2 / new_count)
            ) ** 0.5
            row[f"{base_version}_runs"] = count_wide.loc[model, base_version]
            row[f"{new_version}_runs"] = count_wide.loc[model, new_version]
        rows.append(row)

    return pd.DataFrame(rows).sort_values("model")


def show_version_comparison(
    filtered: pd.DataFrame,
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

    comparison = build_version_comparison(
        filtered=filtered,
        base_version=base_version,
        new_version=new_version,
        metrics=metrics,
    )
    if comparison.empty:
        st.info("No models are present in both selected versions.")
        return

    st.dataframe(comparison, use_container_width=True, hide_index=True)

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
        filtered=filtered,
        metrics=metrics,
        plot_height=plot_height,
        null_version=base_version,
        test_version=new_version,
    )


def show_comparison_cdf_plot(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
    null_version: str,
    test_version: str,
) -> None:
    st.subheader("Cumulative Distribution")
    selected_metric = st.selectbox("CDF comparison metric", metrics)

    null_runs = filtered[filtered["version"] == null_version]
    test_runs = filtered[filtered["version"] == test_version]
    if null_runs.empty or test_runs.empty:
        st.info("Both selected versions need data.")
        return

    null_cdf = model_mean_cdf_data(null_runs, selected_metric, label=f"Null: {null_version}")
    test_cdf = model_mean_cdf_data(test_runs, selected_metric, label=f"Test: {test_version}")
    cdf_data = pd.concat([null_cdf, test_cdf], ignore_index=True)

    stats = (
        cdf_data.groupby("curve")["value"]
        .agg(mean="mean", std="std", skew="skew", kurtosis=pd.Series.kurtosis)
        .reset_index()
    )
    st.dataframe(stats, use_container_width=True, hide_index=True)

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


def main() -> None:
    settings = load_settings()
    page_title = settings["page"]["title"]
    plot_height = settings["plots"]["height"]

    st.set_page_config(page_title=page_title, layout=settings["page"]["layout"])
    st.title(page_title)

    db_path = Path(settings["database"]["path"])
    if not db_path.exists():
        st.error(f"Could not find {db_path}. Run `uv run python -m qa_tool.sqlite_store` first.")
        return

    show_intro(settings, db_path)

    runs = load_runs(str(db_path))
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
                show_version_comparison(filtered, metrics, plot_height),
            ),
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
