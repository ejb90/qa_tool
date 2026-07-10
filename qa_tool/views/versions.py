"""QA dashboard module for versions."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

try:
    from qa_tool.exports import show_export_download
    from qa_tool.summaries import modified_filtered_runs, show_tab_summary
    from qa_tool.views.common import aggregate_runs, model_mean_cdf_data, version_sort_key
except ModuleNotFoundError:
    from exports import show_export_download
    from summaries import modified_filtered_runs, show_tab_summary
    from views.common import aggregate_runs, model_mean_cdf_data, version_sort_key


def show_versions_tab(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    """Handle show versions tab."""
    tab_filtered = modified_filtered_runs(filtered, "versions")
    show_tab_summary(tab_filtered, settings, "versions", metrics)
    show_version_tables(tab_filtered, metrics, plot_height)


def show_version_tables(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> None:
    """Handle show version tables."""
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


def show_version_plots(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> dict[str, pd.DataFrame]:
    """Handle show version plots."""
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
        margin={"l": 10, "r": 10, "t": 36, "b": 10},
        title=f"{selected_metric} by version",
        xaxis_title="Version",
        yaxis_title=selected_metric,
    )
    st.plotly_chart(fig, use_container_width=True)
    return {f"plot_version_metric_{selected_metric}": plot_data}


def show_version_cdf_plot(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> dict[str, pd.DataFrame]:
    """Handle show version cdf plot."""
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
        margin={"l": 10, "r": 10, "t": 36, "b": 10},
        xaxis_title=selected_metric,
        yaxis_title="Cumulative probability",
        yaxis_range=[0, 1.02],
    )
    st.plotly_chart(fig, use_container_width=True)
    return {
        f"cdf_version_{selected_version}_{selected_metric}": model_values,
        f"cdf_stats_version_{selected_version}_{selected_metric}": stats,
    }
