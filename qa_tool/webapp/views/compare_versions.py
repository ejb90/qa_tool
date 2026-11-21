"""QA dashboard module for compare versions."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from packaging.version import Version

from qa_tool.webapp.compare import build_collection_metric_deltas, build_version_comparison
from qa_tool.webapp.data import dataframe_to_csv
from qa_tool.webapp.exports import export_name, show_comparison_archive_controls
from qa_tool.webapp.styling import select_comparison_color_scheme, styled_comparison_table
from qa_tool.webapp.views.common import show_comparison_cdf_plot


def show_version_comparison(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    """Handle show version comparison."""
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    versions = sorted(filtered["version"].unique(), key=Version)
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

    selected_metric = st.selectbox("Difference metric", metrics)
    difference_column = f"percent_difference_{selected_metric}"
    uncertainty_column = f"percent_uncertainty_{selected_metric}"
    plot_data = comparison.sort_values(difference_column)
    fig = px.bar(
        plot_data,
        x="model",
        y=difference_column,
        error_y=uncertainty_column,
        color=difference_column,
        color_continuous_scale="RdBu",
        title=f"{selected_metric} difference: {new_version} - {base_version}",
    )
    fig.update_layout(
        height=plot_height,
        margin={"l": 10, "r": 10, "t": 44, "b": 10},
        xaxis_title="Model",
        yaxis_title="Difference (%)",
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
        file_name=(f"mean_differences_{export_name(base_version)}_to_{export_name(new_version)}.csv"),
        mime="text/csv",
        key="compare_versions_mean_differences_download",
        use_container_width=True,
    )
    show_comparison_archive_controls(
        settings=settings,
        comparison_type="versions",
        base_label=base_version,
        test_label=new_version,
        base_runs=base_runs,
        test_runs=test_runs,
        comparison=build_collection_metric_deltas(base_runs, base_version, test_runs, new_version, metrics),
        metrics=metrics,
        key="compare_versions_archive",
    )
