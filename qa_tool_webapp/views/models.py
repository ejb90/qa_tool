"""QA dashboard module for models."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from qa_tool_core.queries import aggregate_runs, version_sort_key

try:
    from qa_tool_webapp.exports import show_export_download
    from qa_tool_webapp.summaries import modified_filtered_runs, show_tab_summary

except ModuleNotFoundError:
    from exports import show_export_download
    from summaries import modified_filtered_runs, show_tab_summary


def show_models_tab(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    """Handle show models tab."""
    tab_filtered = modified_filtered_runs(filtered, "models")
    show_tab_summary(tab_filtered, settings, "models", metrics)
    show_model_tables(tab_filtered, metrics, plot_height)


def show_model_tables(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> None:
    """Handle show model tables."""
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


def show_model_version_plot(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> dict[str, pd.DataFrame]:
    """Handle show model version plot."""
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
        margin={"l": 10, "r": 10, "t": 36, "b": 10},
        xaxis_title="Version",
        yaxis_title=selected_metric,
    )
    st.plotly_chart(fig, use_container_width=True)
    return {f"plot_model_{selected_model}_{selected_metric}": plot_data}
