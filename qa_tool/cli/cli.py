"""Rich Click command tree for QA Tool."""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Callable, Sequence
from functools import wraps
from importlib.resources import files
from pathlib import Path
from typing import Any, ParamSpec, TextIO, TypeVar, cast

import pandas as pd
import rich_click as click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from qa_tool.cli import commands
from qa_tool.cli.rendering import OutputFormat, require_png_support
from qa_tool.core.queries import load_runs, metric_columns
from qa_tool.core.settings import load_settings
from qa_tool.ingest.core import ingest_run
from qa_tool.ingest.settings import load_settings as load_ingest_settings
from qa_tool.webapp.launch import launch_webapp

DEFAULT_FORMATS = ("html", "csv", "parquet")
OUTPUT_FORMAT = click.Choice(["html", "png", "csv", "parquet"], case_sensitive=False)
MATCH_MODE = click.Choice(["exact", "starts-with", "contains", "regex", "non-empty"], case_sensitive=False)

click.rich_click.TEXT_MARKUP = None
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True

CommandCallback = TypeVar("CommandCallback", bound=Callable[..., Any])
CallbackParams = ParamSpec("CallbackParams")
CallbackResult = TypeVar("CallbackResult")


def handle_errors(
    function: Callable[CallbackParams, CallbackResult],
) -> Callable[CallbackParams, CallbackResult]:
    """Convert expected domain failures into concise Rich Click errors."""

    @wraps(function)
    def wrapped(*args: CallbackParams.args, **kwargs: CallbackParams.kwargs) -> CallbackResult:
        try:
            return function(*args, **kwargs)
        except (FileNotFoundError, ValueError) as error:
            raise click.ClickException(str(error)) from error

    return wrapped


def analysis_options(function: CommandCallback) -> CommandCallback:
    """Add options shared by commands that analyze the runs database."""
    decorators = (
        click.option("--database", type=click.Path(path_type=Path), help="Override the configured DuckDB path."),
        click.option(
            "--settings", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Analysis settings TOML."
        ),
        click.option(
            "--output-dir",
            type=click.Path(file_okay=False, path_type=Path),
            default=Path("qa_tool_output"),
            show_default=True,
            help="Directory for generated artifacts.",
        ),
        click.option(
            "--format",
            "formats",
            type=OUTPUT_FORMAT,
            multiple=True,
            default=DEFAULT_FORMATS,
            show_default=True,
            help="Output format; repeat to select several. PNG requires qa-tool[png].",
        ),
        click.option("--metric", help="Numeric metric to analyze; omit to use every numeric metric."),
    )
    callback: Callable[..., Any] = function
    for decorator in reversed(decorators):
        callback = decorator(callback)
    return cast(CommandCallback, callback)


def load_command_runs(
    database: Path | None,
    settings_path: Path | None,
) -> tuple[pd.DataFrame, list[str], int]:
    """Load configured, normalized runs and the plot height."""
    settings_text = files("qa_tool.webapp").joinpath("default_settings.toml").read_text(encoding="utf-8")
    settings = load_settings(tomllib.loads(settings_text), settings_path)
    database_settings = settings["database"]
    database_path = database or Path(database_settings["path"])
    columns = database_settings.get("columns", {})
    runs = load_runs(database_path, columns.get("model", "model"), columns.get("version", "version"))
    return runs, metric_columns(runs), int(settings["plots"]["height"])


def prepare_analysis(
    database: Path | None,
    settings: Path | None,
    metric: str | None,
    formats: tuple[str, ...],
    *,
    require_outputs: bool = True,
) -> tuple[pd.DataFrame, list[str], int, list[OutputFormat]]:
    """Validate output support and load data shared by analysis commands."""
    selected_formats = cast(list[OutputFormat], list(formats))
    if require_outputs:
        require_png_support(selected_formats)
    runs, available_metrics, plot_height = load_command_runs(database, settings)
    metrics = commands.selected_metrics(metric, available_metrics)
    return runs, metrics, plot_height, selected_formats


def artifact_stream(context: click.Context) -> TextIO | None:
    """Return stderr for verbose artifact reporting, otherwise no stream."""
    return sys.stderr if context.find_root().params.get("verbose", False) else None


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Print each generated artifact path.")
@click.version_option(package_name="qa-tool")
def cli(*, verbose: bool) -> None:
    """Inspect, ingest, and serve QA run data."""


@cli.command()
@click.argument("artifact_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--metadata", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--settings", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--database", type=click.Path(path_type=Path), help="Override the ingestion database path.")
@handle_errors
def ingest(artifact_dir: Path, metadata: Path | None, settings: Path | None, database: Path | None) -> None:
    """Append one artifact directory's metadata to DuckDB."""
    metadata_path = metadata or artifact_dir / "metadata.json"
    ingestion_settings = load_ingest_settings(settings)
    if database is not None:
        ingestion_settings["database"]["path"] = str(database)
    result = ingest_run(artifact_dir, metadata_path, ingestion_settings)

    details = Table.grid(padding=(0, 2))
    details.add_column(style="bold cyan", justify="right")
    details.add_column()
    details.add_row("Artifact", str(artifact_dir))
    details.add_row("Database", str(result["database"]))
    details.add_row("Runs table", str(result["runs_table"]))
    details.add_row("Summary table", str(result["summary_table"]))
    details.add_row("Stored columns", ", ".join(result["columns"]))
    Console().print(Panel(details, title="[bold green]✓ Ingested run", border_style="green"))


@cli.command(context_settings={"ignore_unknown_options": True})
@click.option("--settings", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("streamlit_args", nargs=-1, type=click.UNPROCESSED)
def webapp(settings: Path | None, streamlit_args: tuple[str, ...]) -> None:
    """Launch the Streamlit dashboard."""
    arguments = list(streamlit_args)
    if settings is not None:
        arguments.extend(["--", "--settings", str(settings)])
    exit_code = launch_webapp(arguments)
    if exit_code:
        raise click.ClickException(f"Streamlit exited with status {exit_code}.")


@cli.command()
@click.argument("models", nargs=-1, required=True)
@analysis_options
@click.pass_context
@handle_errors
def model(
    context: click.Context,
    models: tuple[str, ...],
    database: Path | None,
    settings: Path | None,
    output_dir: Path,
    formats: tuple[str, ...],
    metric: str | None,
) -> None:
    """Report metrics by version for one or more models."""
    runs, metrics, plot_height, selected_formats = prepare_analysis(database, settings, metric, formats)
    console = Console()
    for selected_metric in metrics:
        commands.show_models(
            console,
            runs,
            list(models),
            selected_metric,
            output_dir,
            selected_formats,
            plot_height,
            artifact_stream(context),
        )


@cli.command()
@click.argument("versions", nargs=-1, required=True)
@click.option("--cdf-version", help="Selected version to use for the empirical CDF.")
@analysis_options
@click.pass_context
@handle_errors
def version(
    context: click.Context,
    versions: tuple[str, ...],
    cdf_version: str | None,
    database: Path | None,
    settings: Path | None,
    output_dir: Path,
    formats: tuple[str, ...],
    metric: str | None,
) -> None:
    """Report metrics by model for one or more versions."""
    runs, metrics, plot_height, selected_formats = prepare_analysis(database, settings, metric, formats)
    console = Console()
    for selected_metric in metrics:
        commands.show_versions(
            console,
            runs,
            list(versions),
            selected_metric,
            cdf_version,
            output_dir,
            selected_formats,
            plot_height,
            artifact_stream(context),
        )


@cli.group()
def compare() -> None:
    """Compare versions, models, or arbitrary run collections."""


@compare.command("versions")
@click.argument("base_version")
@click.argument("test_version")
@analysis_options
@click.pass_context
@handle_errors
def compare_versions(
    context: click.Context,
    base_version: str,
    test_version: str,
    database: Path | None,
    settings: Path | None,
    output_dir: Path,
    formats: tuple[str, ...],
    metric: str | None,
) -> None:
    """Compare two versions across their shared models."""
    runs, metrics, plot_height, selected_formats = prepare_analysis(database, settings, metric, formats)
    console = Console()
    for selected_metric in metrics:
        commands.show_version_comparison(
            console,
            runs,
            base_version,
            test_version,
            selected_metric,
            output_dir,
            selected_formats,
            plot_height,
            artifact_stream(context),
        )


@compare.command("models")
@click.option("--base", "base_models", multiple=True, required=True, help="Base model; repeat for several.")
@click.option("--test", "test_models", multiple=True, required=True, help="Test model; repeat for several.")
@analysis_options
@click.pass_context
@handle_errors
def compare_models(
    context: click.Context,
    base_models: tuple[str, ...],
    test_models: tuple[str, ...],
    database: Path | None,
    settings: Path | None,
    output_dir: Path,
    formats: tuple[str, ...],
    metric: str | None,
) -> None:
    """Compare aggregate values for two model groups."""
    runs, metrics, plot_height, selected_formats = prepare_analysis(database, settings, metric, formats)
    console = Console()
    for selected_metric in metrics:
        commands.show_model_comparison(
            console,
            runs,
            list(base_models),
            list(test_models),
            selected_metric,
            output_dir,
            selected_formats,
            plot_height,
            artifact_stream(context),
        )


@compare.command("collections")
@click.option("--field", required=True, help="Database column used to select each collection.")
@click.option("--base", "base_values", multiple=True, required=True, help="Base value; repeat for several.")
@click.option("--test", "test_values", multiple=True, required=True, help="Test value; repeat for several.")
@click.option("--match", "match_mode", type=MATCH_MODE, default="exact", show_default=True)
@click.option("--terse", is_flag=True, help="Print one compact delta table without writing artifacts.")
@analysis_options
@click.pass_context
@handle_errors
def compare_collections(
    context: click.Context,
    field: str,
    base_values: tuple[str, ...],
    test_values: tuple[str, ...],
    match_mode: str,
    terse: bool,
    database: Path | None,
    settings: Path | None,
    output_dir: Path,
    formats: tuple[str, ...],
    metric: str | None,
) -> None:
    """Compare two collections selected from any database field."""
    runs, metrics, plot_height, selected_formats = prepare_analysis(
        database, settings, metric, formats, require_outputs=not terse
    )
    console = Console()
    if terse:
        commands.show_terse_collection_comparison(
            console, runs, field, list(base_values), list(test_values), match_mode, metrics
        )
        return
    for selected_metric in metrics:
        commands.show_collection_comparison(
            console,
            runs,
            field,
            list(base_values),
            list(test_values),
            match_mode,
            selected_metric,
            output_dir,
            selected_formats,
            plot_height,
            artifact_stream(context),
        )


@cli.command()
@click.option("--slice-by", type=click.Choice(["model", "version"]), default="model", show_default=True)
@analysis_options
@click.pass_context
@handle_errors
def pie(
    context: click.Context,
    slice_by: str,
    database: Path | None,
    settings: Path | None,
    output_dir: Path,
    formats: tuple[str, ...],
    metric: str | None,
) -> None:
    """Create run-count or metric-total donut charts."""
    runs, metrics, plot_height, selected_formats = prepare_analysis(database, settings, metric, formats)
    pie_metrics: list[str | None] = [None, *metrics] if metric is None else metrics
    console = Console()
    for selected_metric in pie_metrics:
        commands.show_pie_chart(
            console,
            runs,
            slice_by,
            selected_metric,
            output_dir,
            selected_formats,
            plot_height,
            artifact_stream(context),
        )


def main(argv: Sequence[str] | None = None) -> None:
    """Run the command tree with optional explicit arguments for tests and modules."""
    try:
        cli.main(args=list(argv) if argv is not None else None, prog_name="qa-tool", standalone_mode=False)
    except click.ClickException as error:
        error.show()
        raise SystemExit(error.exit_code) from error
    except click.exceptions.Exit as error:
        if error.exit_code:
            raise SystemExit(error.exit_code) from error
