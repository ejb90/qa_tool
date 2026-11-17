"""QA dashboard module for common."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from qa_tool.core.queries import model_mean_cdf_data

try:
    from qa_tool.webapp.styling import styled_comparison_table
except ModuleNotFoundError:
    from styling import styled_comparison_table


def empirical_cdf(values: pd.Series) -> pd.DataFrame:
    """Handle empirical cdf."""
    sorted_values = values.sort_values(ignore_index=True)
    return pd.DataFrame(
        {
            "value": sorted_values,
            "cdf": (sorted_values.index + 1) / len(sorted_values),
        }
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
    """Handle show comparison cdf plot."""
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
        margin={"l": 10, "r": 10, "t": 36, "b": 10},
        xaxis_title=selected_metric,
        yaxis_title="Cumulative probability",
        yaxis_range=[0, 1.02],
    )
    st.plotly_chart(fig, use_container_width=True)
    return {
        f"cdf_points_{selected_metric}": cdf_data,
        f"cdf_stats_{selected_metric}": stats,
    }
