"""Plotly figure builders shared by the web application and command-line client."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure


def model_version_figure(runs: pd.DataFrame, model: str, metric: str, height: int) -> Figure:
    """Build the model-by-version mean and standard-deviation line figure."""
    data = (
        runs[runs["model"] == model]
        .groupby("version", as_index=False)
        .agg(mean_value=(metric, "mean"), uncertainty=(metric, "std"), run_count=("uid", "count"))
    )
    data["uncertainty"] = data["uncertainty"].fillna(0.0)
    figure = px.line(
        data, x="version", y="mean_value", error_y="uncertainty", markers=True, title=f"{model}: {metric} by version"
    )
    figure.update_layout(height=height, xaxis_title="Version", yaxis_title=metric)
    return figure


def versions_by_model_figure(runs: pd.DataFrame, metric: str, height: int) -> Figure:
    """Build the metric-by-version plot split into model series."""
    data = runs.groupby(["version", "model"], as_index=False).agg(
        mean_value=(metric, "mean"), uncertainty=(metric, "std"), run_count=("uid", "count")
    )
    data["uncertainty"] = data["uncertainty"].fillna(0.0)
    figure = px.line(data, x="version", y="mean_value", error_y="uncertainty", color="model", markers=True)
    figure.update_layout(height=height, title=f"{metric} by version", xaxis_title="Version", yaxis_title=metric)
    return figure


def cdf_figure(cdf_data: pd.DataFrame, metric: str, height: int, title: str) -> Figure:
    """Build a labelled empirical-CDF line plot from model-level summary data."""
    color = "curve" if "curve" in cdf_data.columns else None
    figure = px.line(cdf_data, x="value", y="cdf", color=color, text="model", markers=True, title=title)
    figure.update_traces(textposition="top center")
    figure.update_layout(height=height, xaxis_title=metric, yaxis_title="Cumulative probability", yaxis_range=[0, 1.02])
    return figure


def comparison_delta_figure(comparison: pd.DataFrame, metric: str, height: int, title: str) -> Figure:
    """Build a model percentage-difference bar chart with percentage uncertainty bars."""
    difference_column = f"percent_difference_{metric}"
    figure = px.bar(
        comparison.sort_values(difference_column),
        x="model",
        y=difference_column,
        error_y=f"percent_uncertainty_{metric}",
        title=title,
    )
    figure.update_layout(height=height, xaxis_title="Model", yaxis_title="Difference (%)")
    return figure


def model_collection_delta_figure(comparison: pd.DataFrame, height: int, title: str) -> Figure:
    """Build a percentage-difference bar chart for an aggregate model-to-model comparison."""
    figure = px.bar(comparison, x="metric", y="percent_difference", error_y="percent_uncertainty", title=title)
    figure.update_layout(height=height, xaxis_title="Metric", yaxis_title="Difference (%)")
    return figure


def pie_figure(data: pd.DataFrame, slice_by: str, value_label: str, height: int) -> Figure:
    """Build a donut chart for run-count or metric-total slices."""
    figure = px.pie(data, names=slice_by, values="value", hole=0.35, title=f"{value_label} by {slice_by}")
    figure.update_traces(textposition="inside", textinfo="percent+label")
    figure.update_layout(height=height)
    return figure
