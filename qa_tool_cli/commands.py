"""Command implementations for tables and plots produced by the QA Tool CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO, cast

import pandas as pd
from rich.console import Console

from qa_tool_cli.rendering import OutputFormat, print_dataframe, write_plot
from qa_tool_core.comparisons import (
    build_collection_comparison,
    build_collection_metric_deltas,
    build_model_comparison,
    build_version_comparison,
)
from qa_tool_core.plots import (
    cdf_figure,
    comparison_delta_figure,
    model_collection_delta_figure,
    model_version_figure,
    pie_figure,
    versions_by_model_figure,
)
from qa_tool_core.queries import MatchMode, aggregate_runs, model_mean_cdf_data, select_collection, version_sort_key


def selected_metrics(requested_metric: str | None, available_metrics: list[str]) -> list[str]:
    """Validate an optional metric selection or return every available numeric metric."""
    if not available_metrics:
        raise ValueError("The database has no numeric metrics to display.")
    if requested_metric is None:
        return available_metrics
    if requested_metric not in available_metrics:
        raise ValueError(f"Unknown metric `{requested_metric}`. Available metrics: {', '.join(available_metrics)}")
    return [requested_metric]


def comparison_display_table(comparison: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Rename one-metric comparison columns into compact, terminal-friendly table headers."""
    renamed_columns = {
        f"base_mean_{metric}": "base mean",
        f"base_std_{metric}": "base std",
        f"test_mean_{metric}": "test mean",
        f"test_std_{metric}": "test std",
        f"percent_difference_{metric}": "difference (%)",
        f"percent_uncertainty_{metric}": "uncertainty (%)",
    }
    return comparison.rename(columns=renamed_columns)


def collection_selection_label(field: str, values: list[str]) -> str:
    """Return a compact, human-readable label for one collection selection."""
    return f"{field}={', '.join(values)}"


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
    for version in sorted(versions, key=version_sort_key, reverse=True):
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


def show_version_comparison(
    console: Console,
    runs: pd.DataFrame,
    base_version: str,
    test_version: str,
    metric: str,
    output_dir: Path,
    formats: list[OutputFormat],
    plot_height: int,
    stderr: TextIO | None,
) -> None:
    """Print and save shared-model version comparison plots with raw data and tables."""
    comparison = build_version_comparison(runs, base_version, test_version, [metric])
    if comparison.empty:
        raise ValueError("The selected versions have no models in common.")
    print_dataframe(console, comparison_display_table(comparison, metric), f"{test_version} minus {base_version}")
    write_plot(
        comparison_delta_figure(
            comparison, metric, plot_height, f"{metric} difference: {test_version} - {base_version}"
        ),
        comparison,
        comparison,
        output_dir,
        f"compare_versions_{base_version}_to_{test_version}_{metric}",
        formats,
        stderr,
    )
    cdf_data = pd.concat(
        [
            model_mean_cdf_data(runs[runs["version"] == base_version], metric, base_version),
            model_mean_cdf_data(runs[runs["version"] == test_version], metric, test_version),
        ],
        ignore_index=True,
    )
    write_plot(
        cdf_figure(cdf_data, metric, plot_height, f"{metric}: version comparison CDF"),
        cdf_data,
        cdf_data,
        output_dir,
        f"compare_versions_cdf_{metric}",
        formats,
        stderr,
    )


def show_model_comparison(
    console: Console,
    runs: pd.DataFrame,
    base_models: list[str],
    test_models: list[str],
    metric: str,
    output_dir: Path,
    formats: list[OutputFormat],
    plot_height: int,
    stderr: TextIO | None,
) -> None:
    """Print and save an aggregate model comparison plot with its source data and table."""
    comparison = build_model_comparison(runs, base_models, test_models, [metric])
    print_dataframe(
        console,
        comparison.rename(
            columns={
                "mean_difference": "mean difference",
                "percent_difference": "difference (%)",
                "percent_uncertainty": "uncertainty (%)",
            }
        ),
        f"Models {', '.join(test_models)} minus {', '.join(base_models)}",
    )
    write_plot(
        model_collection_delta_figure(comparison, plot_height, "Model collection comparison"),
        comparison,
        comparison,
        output_dir,
        f"compare_models_{metric}",
        formats,
        stderr,
    )


def show_collection_comparison(
    console: Console,
    runs: pd.DataFrame,
    field: str,
    base_values: list[str],
    test_values: list[str],
    match_mode: str,
    metric: str,
    output_dir: Path,
    formats: list[OutputFormat],
    plot_height: int,
    stderr: TextIO | None,
) -> None:
    """Select collections, then save comparison and CDF plots with their data and tables."""
    validated_match_mode = cast(MatchMode, match_mode)
    base_label = collection_selection_label(field, base_values)
    test_label = collection_selection_label(field, test_values)
    comparison_title = (
        f"{metric}: collection {field} ({match_mode}) — test {', '.join(test_values)} - base {', '.join(base_values)}"
    )
    base_runs = select_collection(runs, field, base_values, validated_match_mode)
    test_runs = select_collection(runs, field, test_values, validated_match_mode)
    if base_runs.empty or test_runs.empty:
        raise ValueError("Both collection selections must match at least one run.")
    comparison = build_collection_comparison(base_runs, "base", test_runs, "test", [metric])
    if comparison.empty:
        raise ValueError("The selected collections have no models in common.")
    print_dataframe(console, comparison_display_table(comparison, metric), comparison_title)
    write_plot(
        comparison_delta_figure(comparison, metric, plot_height, comparison_title),
        comparison,
        comparison,
        output_dir,
        f"compare_collections_{metric}",
        formats,
        stderr,
    )
    cdf_data = pd.concat(
        [model_mean_cdf_data(base_runs, metric, base_label), model_mean_cdf_data(test_runs, metric, test_label)],
        ignore_index=True,
    )
    write_plot(
        cdf_figure(cdf_data, metric, plot_height, f"{comparison_title} CDF"),
        cdf_data,
        cdf_data,
        output_dir,
        f"compare_collections_cdf_{metric}",
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


def show_pie_chart(
    console: Console,
    runs: pd.DataFrame,
    slice_by: str,
    metric: str | None,
    output_dir: Path,
    formats: list[OutputFormat],
    plot_height: int,
    stderr: TextIO | None,
) -> None:
    """Print pie source values and save the donut plot with its data and table artifacts."""
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
        f"pie_{slice_by}_{label}",
        formats,
        stderr,
    )
