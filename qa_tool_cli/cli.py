"""Argument parsing and dispatch for the ``qa_tool`` command."""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path
from typing import cast

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich_argparse import RichHelpFormatter

from qa_tool_cli import commands
from qa_tool_cli.rendering import OutputFormat
from qa_tool_core.queries import load_runs, metric_columns
from qa_tool_core.settings import load_settings


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add database, settings, output-directory, and metric options to a command parser."""
    parser.add_argument("--database", help="DuckDB database path; overrides the configured default.")
    parser.add_argument("--settings", help="Web-app settings TOML used for the database and column mappings.")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("qa_tool_output"), help="Directory for interactive HTML plots."
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=["html", "png", "csv", "parquet"],
        default=["html", "png", "csv", "parquet"],
        help="Artifacts to write: plot HTML/PNG and raw-data/table CSV/Parquet files.",
    )
    parser.add_argument(
        "--metric", help="Numeric metric to display and plot; defaults to every available numeric metric."
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the Rich-help command parser for all supported QA Tool capabilities."""
    parser = argparse.ArgumentParser(
        prog="qa_tool", description="Inspect QA runs from DuckDB.", formatter_class=RichHelpFormatter
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each generated artifact path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    model_parser = subparsers.add_parser(
        "model", help="Show tables and plots for models.", formatter_class=RichHelpFormatter
    )
    add_common_arguments(model_parser)
    model_parser.add_argument("--models", nargs="+", required=True, help="Model values to include.")

    version_parser = subparsers.add_parser(
        "version", help="Show tables and plots for versions.", formatter_class=RichHelpFormatter
    )
    add_common_arguments(version_parser)
    version_parser.add_argument("--versions", nargs="+", required=True, help="Version values to include.")
    version_parser.add_argument("--cdf-version", help="One selected version to use for the empirical CDF plot.")

    compare_parser = subparsers.add_parser(
        "compare", help="Compare versions, models, or arbitrary collections.", formatter_class=RichHelpFormatter
    )
    compare_subparsers = compare_parser.add_subparsers(dest="compare_command", required=True)

    compare_versions = compare_subparsers.add_parser(
        "versions", help="Compare two versions by shared model.", formatter_class=RichHelpFormatter
    )
    add_common_arguments(compare_versions)
    compare_versions.add_argument("--base-version", required=True)
    compare_versions.add_argument("--test-version", required=True)

    compare_models = compare_subparsers.add_parser(
        "models", help="Compare two model collections.", formatter_class=RichHelpFormatter
    )
    add_common_arguments(compare_models)
    compare_models.add_argument("--base-models", nargs="+", required=True)
    compare_models.add_argument("--test-models", nargs="+", required=True)

    compare_collections = compare_subparsers.add_parser(
        "collections", help="Compare two field-based run collections.", formatter_class=RichHelpFormatter
    )
    add_common_arguments(compare_collections)
    compare_collections.add_argument("--field", required=True, help="Database column used to select each collection.")
    compare_collections.add_argument(
        "--base", nargs="+", required=True, help="Base collection values; datetimes require start then end."
    )
    compare_collections.add_argument(
        "--test", nargs="+", required=True, help="Test collection values; datetimes require start then end."
    )
    compare_collections.add_argument(
        "--match",
        choices=["exact", "starts-with", "contains", "regex", "non-empty"],
        default="exact",
        help="Matching mode for non-date, non-boolean collection fields.",
    )
    compare_collections.add_argument(
        "--terse",
        action="store_true",
        help="Print one combined percentage-difference table and skip plots and exports.",
    )

    pie_parser = subparsers.add_parser(
        "pie", help="Print data and generate a pie chart.", formatter_class=RichHelpFormatter
    )
    add_common_arguments(pie_parser)
    pie_parser.add_argument("--slice-by", choices=["model", "version"], default="model")
    return parser


def load_command_runs(args: argparse.Namespace) -> tuple[pd.DataFrame, list[str], int]:
    """Load settings and normalized runs for one CLI command invocation."""
    settings_text = files("qa_tool_webapp").joinpath("default_settings.toml").read_text(encoding="utf-8")
    settings = load_settings(tomllib.loads(settings_text), args.settings)
    database_settings = settings["database"]
    database_path = args.database or database_settings["path"]
    columns = database_settings.get("columns", {})
    runs = load_runs(database_path, columns.get("model", "model"), columns.get("version", "version"))
    return runs, metric_columns(runs), int(settings["plots"]["height"])


def main(argv: Sequence[str] | None = None) -> None:
    """Run the requested QA Tool CLI command and report errors without a traceback."""
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()
    try:
        runs, available_metrics, plot_height = load_command_runs(args)
        metrics = commands.selected_metrics(args.metric, available_metrics)
        formats = cast(list[OutputFormat], args.formats)
        artifact_output = sys.stderr if args.verbose else None
        if args.command == "model":
            for metric in metrics:
                commands.show_models(
                    console, runs, args.models, metric, args.output_dir, formats, plot_height, artifact_output
                )
        elif args.command == "version":
            for metric in metrics:
                commands.show_versions(
                    console,
                    runs,
                    args.versions,
                    metric,
                    args.cdf_version,
                    args.output_dir,
                    formats,
                    plot_height,
                    artifact_output,
                )
        elif args.command == "compare" and args.compare_command == "versions":
            for metric in metrics:
                commands.show_version_comparison(
                    console,
                    runs,
                    args.base_version,
                    args.test_version,
                    metric,
                    args.output_dir,
                    formats,
                    plot_height,
                    artifact_output,
                )
        elif args.command == "compare" and args.compare_command == "models":
            for metric in metrics:
                commands.show_model_comparison(
                    console,
                    runs,
                    args.base_models,
                    args.test_models,
                    metric,
                    args.output_dir,
                    formats,
                    plot_height,
                    artifact_output,
                )
        elif args.command == "compare" and args.compare_command == "collections":
            if args.terse:
                commands.show_terse_collection_comparison(
                    console, runs, args.field, args.base, args.test, args.match, metrics
                )
            else:
                for metric in metrics:
                    commands.show_collection_comparison(
                        console,
                        runs,
                        args.field,
                        args.base,
                        args.test,
                        args.match,
                        metric,
                        args.output_dir,
                        formats,
                        plot_height,
                        artifact_output,
                    )
        elif args.command == "pie":
            pie_metrics = [None, *metrics] if args.metric is None else metrics
            for metric in pie_metrics:
                commands.show_pie_chart(
                    console, runs, args.slice_by, metric, args.output_dir, formats, plot_height, artifact_output
                )
    except (FileNotFoundError, ValueError) as error:
        console.print(Panel(str(error), title="QA Tool error", border_style="red"))
        raise SystemExit(2) from error
