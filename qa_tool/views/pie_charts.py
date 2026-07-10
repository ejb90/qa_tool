"""QA dashboard module for pie charts."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st


def show_pie_charts(
    filtered: pd.DataFrame,
    metrics: list[str],
    plot_height: int,
) -> None:
    """Handle show pie charts."""
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
            filtered.groupby(slice_by, as_index=False).agg(value=("uid", "count")).sort_values("value", ascending=False)
        )
        value_label = "run_count"
    else:
        metric = value_choice.removeprefix("sum_")
        pie_data = (
            filtered.groupby(slice_by, as_index=False).agg(value=(metric, "sum")).sort_values("value", ascending=False)
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
    fig.update_layout(height=plot_height, margin={"l": 10, "r": 10, "t": 44, "b": 10})
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        pie_data.rename(columns={"value": value_label}),
        use_container_width=True,
        hide_index=True,
    )
