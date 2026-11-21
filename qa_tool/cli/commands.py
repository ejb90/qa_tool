"""Command implementations for tables and plots produced by the QA Tool CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO, cast

import pandas as pd
from packaging.version import Version
from rich.console import Console

from qa_tool.cli.rendering import OutputFormat, print_dataframe, write_plot
from qa_tool.core.comparisons import build_collection_metric_deltas
from qa_tool.core.plots import (
    cdf_figure,
    model_version_figure,
    pie_figure,
    versions_by_model_figure,
)
from qa_tool.core.queries import MatchMode, aggregate_runs, model_mean_cdf_data, select_collection


def selected_metrics(requested_metric: str | None, available_metrics: list[str]) -> list[str]:
    """Validate an optional metric selection or return every available numeric metric."""
    if not available_metrics:
        raise ValueError("The database has no numeric metrics to display.")
    if requested_metric is None:
        return available_metrics
    if requested_metric not in available_metrics:
        raise ValueError(f"Unknown metric `{requested_metric}`. Available metrics: {', '.join(available_metrics)}")
    return [requested_metric]


def show_models(
    console: Console,
    runs: pd.DataFrame,
    models: list[str],
    metric: str,
    output_dir: Path,
    formats: list[OutputFormat],
    plot_height: int,
    stderr: TextIO | None,
) -> None:
    """Print model version tables and save each model plot, raw runs, and table artifacts."""
    selected = runs[runs["model"].isin(models)]
    missing = sorted(set(models) - set(selected["model"]))
    if missing:
        raise ValueError(f"Unknown model(s): {', '.join(missing)}")
    for model in models:
        model_runs = selected[selected["model"] == model]
        table_data = aggregate_runs(model_runs, ["version"], [metric])
        print_dataframe(console, table_data, f"{model} ({len(model_runs)} runs)")
        write_plot(
            model_version_figure(model_runs, model, metric, plot_height),
            model_runs,
            table_data,
            output_dir,
            f"model_{model}_{metric}",
            formats,
            stderr,
        )


def show_versions(
    console: Console,
    runs: pd.DataFrame,
    versions: list[str],
    metric: str,
    cdf_version: str | None,
    output_dir: Path,
    formats: list[OutputFormat],
    plot_height: int,
    stderr: TextIO | None,
) -> None:
    """Print version tables and save version plus CDF plots with their data and tables."""
    selected = runs[runs["version"].isin(versions)]
    missing = sorted(set(versions) - set(selected["version"]))
    if missing:
        raise ValueError(f"Unknown version(s): {', '.join(missing)}")
    for version in sorted(versions, key=Version, reverse=True):
        version_runs = selected[selected["version"] == version]
        print_dataframe(
            console, aggregate_runs(version_runs, ["model"], [metric]), f"{version} ({len(version_runs)} runs)"
        )
    version_table = aggregate_runs(selected, ["version", "model"], [metric])
    write_plot(
        versions_by_model_figure(selected, metric, plot_height),
        selected,
        version_table,
        output_dir,
        f"versions_{metric}",
        formats,
        stderr,
    )
    selected_cdf_version = cdf_version or versions[0]
    if selected_cdf_version not in versions:
        raise ValueError("The CDF version must be included in --versions.")
    cdf_data = model_mean_cdf_data(selected[selected["version"] == selected_cdf_version], metric)
    print_dataframe(console, cdf_data, f"{selected_cdf_version} {metric} empirical CDF")
    write_plot(
        cdf_figure(cdf_data, metric, plot_height, f"{selected_cdf_version}: {metric} empirical CDF"),
        cdf_data,
        cdf_data,
        output_dir,
        f"version_cdf_{selected_cdf_version}_{metric}",
        formats,
        stderr,
    )


def show_terse_collection_comparison(
    console: Console,
    runs: pd.DataFrame,
    field: str,
    base_values: list[str],
    test_values: list[str],
    match_mode: str,
    metrics: list[str],
) -> None:
    """Print one model-and-metric percentage-difference table without plots or exports."""
    validated_match_mode = cast(MatchMode, match_mode)
    base_runs = select_collection(runs, field, base_values, validated_match_mode)
    test_runs = select_collection(runs, field, test_values, validated_match_mode)
    if base_runs.empty or test_runs.empty:
        raise ValueError("Both collection selections must match at least one run.")
    comparison = build_collection_metric_deltas(base_runs, "base", test_runs, "test", metrics)
    if comparison.empty:
        raise ValueError("The selected collections have no models in common.")
    table_data = (
        comparison.loc[:, ["model", "metric", "percent_difference"]]
        .rename(columns={"percent_difference": "difference (%)"})
        .sort_values(["metric", "model"])
    )
    title = f"Deltas: {field} {match_mode}; {', '.join(test_values)} - {', '.join(base_values)}"
    print_dataframe(console, table_data, title)


def show_breakdown(
    console: Console,
    runs: pd.DataFrame,
    slice_by: str,
    metric: str | None,
    output_dir: Path,
    formats: list[OutputFormat],
    plot_height: int,
    stderr: TextIO | None,
) -> None:
    """Print breakdown values and save the donut plot with its data and table artifacts."""
    if slice_by not in {"model", "version"}:
        raise ValueError("Pie charts can be sliced by `model` or `version`.")
    if metric is None:
        data = runs.groupby(slice_by, as_index=False).agg(value=("uid", "count")).sort_values("value", ascending=False)
        label = "run_count"
    else:
        data = runs.groupby(slice_by, as_index=False).agg(value=(metric, "sum")).sort_values("value", ascending=False)
        label = f"sum_{metric}"
    table_data = data.rename(columns={"value": label})
    print_dataframe(console, table_data, f"{label} by {slice_by}")
    write_plot(
        pie_figure(data, slice_by, label, plot_height),
        data,
        table_data,
        output_dir,
        f"breakdown_{slice_by}_{label}",
        formats,
        stderr,
    )
