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
from qa_tool.core.archive import (
    ComparisonArchive,
    create_comparison_archive,
    find_comparison_archive_in_roots,
    list_comparison_archives_from_roots,
    local_artifact_paths,
    verify_comparison_archive,
)
from qa_tool.core.comparisons import (
    build_collection_metric_deltas,
    build_model_comparison,
    build_run_scalar_comparison,
)
from qa_tool.core.queries import load_runs, metric_columns, select_collection
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


def comparison_options(function: CommandCallback) -> CommandCallback:
    """Add options shared by commands that create comparison snapshots."""
    decorators = (
        click.option("--database", type=click.Path(path_type=Path), help="Override the configured DuckDB path."),
        click.option(
            "--settings", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Analysis settings TOML."
        ),
        click.option(
            "--archive-dir",
            type=click.Path(file_okay=False, path_type=Path),
            help="Override the comparison archive directory from settings.",
        ),
        click.option("--metric", help="Numeric metric to compare; omit to use every numeric metric."),
    )
    callback: Callable[..., Any] = function
    for decorator in reversed(decorators):
        callback = decorator(callback)
    return cast(CommandCallback, callback)


def print_saved_archive(archive: ComparisonArchive) -> None:
    """Print the identity and location of a newly saved archive."""
    Console().print(f"[bold green]Saved comparison {archive.snapshot_id}[/bold green]\n{archive.path}")


def comparison_archive_root(archive_dir: Path | None, settings: dict[str, Any]) -> Path:
    """Resolve a CLI override or the archive path from analysis settings."""
    return archive_dir or Path(settings.get("archive", {}).get("save_path", "qa_tool_archive"))


def load_command_settings(settings_path: Path | None) -> dict[str, Any]:
    """Load packaged analysis settings with an optional TOML override."""
    settings_text = files("qa_tool.webapp").joinpath("default_settings.toml").read_text(encoding="utf-8")
    return load_settings(tomllib.loads(settings_text), settings_path)


def load_command_runs(
    database: Path | None,
    settings_path: Path | None,
) -> tuple[pd.DataFrame, list[str], int, dict[str, Any]]:
    """Load configured, normalized runs and the plot height."""
    settings = load_command_settings(settings_path)
    database_settings = settings["database"]
    database_path = database or Path(database_settings["path"])
    columns = database_settings.get("columns", {})
    runs = load_runs(database_path, columns.get("model", "model"), columns.get("version", "version"))
    return runs, metric_columns(runs), int(settings["plots"]["height"]), settings


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
    runs, available_metrics, plot_height, _ = load_command_runs(database, settings)
    metrics = commands.selected_metrics(metric, available_metrics)
    return runs, metrics, plot_height, selected_formats


def artifact_stream(context: click.Context) -> TextIO | None:
    """Return stderr for verbose artifact reporting, otherwise no stream."""
    return sys.stderr if context.find_root().params.get("verbose", False) else None


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="Print every generated file path.")
@click.version_option(package_name="qa-tool")
def cli(*, verbose: bool) -> None:
    """Ingest, report on, compare, and serve QA run data."""


@cli.command()
@click.argument("artifact_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--metadata",
    type=click.Path(path_type=Path),
    help="Metadata JSON path, or member path when ingesting an archive.",
)
@click.option("--settings", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--database", type=click.Path(path_type=Path), help="Override the ingestion database path.")
@handle_errors
def ingest(artifact_path: Path, metadata: Path | None, settings: Path | None, database: Path | None) -> None:
    """Append metadata from an artifact directory or tar archive to DuckDB."""
    ingestion_settings = load_ingest_settings(settings)
    if database is not None:
        ingestion_settings["database"]["path"] = str(database)
    result = ingest_run(artifact_path, metadata, ingestion_settings)

    details = Table.grid(padding=(0, 2))
    details.add_column(style="bold cyan", justify="right")
    details.add_column()
    details.add_row("Artifact", str(artifact_path))
    details.add_row("Database", str(result["database"]))
    details.add_row("Runs table", str(result["runs_table"]))
    details.add_row("Summary table", str(result["summary_table"]))
    details.add_row("Stored columns", ", ".join(result["columns"]))
    Console().print(Panel(details, title="[bold green]✓ Ingested run", border_style="green"))


@cli.command("serve", context_settings={"ignore_unknown_options": True})
@click.option("--settings", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--allow-unsafe-pickle",
    is_flag=True,
    help="Render trusted pickle artifacts. Use only for a local dashboard.",
)
@click.argument("streamlit_args", nargs=-1, type=click.UNPROCESSED)
def serve(settings: Path | None, allow_unsafe_pickle: bool, streamlit_args: tuple[str, ...]) -> None:
    """Launch the Streamlit dashboard."""
    arguments = list(streamlit_args)
    if allow_unsafe_pickle:
        address = next(
            (argument.partition("=")[2] for argument in arguments if argument.startswith("--server.address=")),
            None,
        )
        if "--server.address" in arguments:
            address_index = arguments.index("--server.address")
            address = arguments[address_index + 1] if address_index + 1 < len(arguments) else ""
        if address not in {None, "127.0.0.1", "localhost", "::1"}:
            raise click.ClickException("Unsafe pickle rendering is restricted to a loopback server address.")
        if address is None:
            arguments.append("--server.address=127.0.0.1")

    app_arguments: list[str] = []
    if settings is not None:
        app_arguments.extend(["--settings", str(settings)])
    if allow_unsafe_pickle:
        app_arguments.append("--allow-unsafe-pickle")
    if app_arguments:
        arguments.extend(["--", *app_arguments])
    exit_code = launch_webapp(arguments)
    if exit_code:
        raise click.ClickException(f"Streamlit exited with status {exit_code}.")


@cli.group()
def report() -> None:
    """Generate exploratory reports and plots."""


@report.command("models")
@click.argument("models", nargs=-1, required=True)
@analysis_options
@click.pass_context
@handle_errors
def report_models(
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


@report.command("versions")
@click.argument("versions", nargs=-1, required=True)
@click.option("--cdf-version", help="Selected version to use for the empirical CDF.")
@analysis_options
@click.pass_context
@handle_errors
def report_versions(
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
    """Compare runs, versions, models, or arbitrary collections."""


@compare.command("versions")
@click.argument("base_version")
@click.argument("test_version")
@comparison_options
@handle_errors
def compare_versions(
    base_version: str,
    test_version: str,
    database: Path | None,
    settings: Path | None,
    archive_dir: Path | None,
    metric: str | None,
) -> None:
    """Compare two versions across their shared models."""
    runs, available_metrics, _, analysis_settings = load_command_runs(database, settings)
    metrics = commands.selected_metrics(metric, available_metrics)
    base_runs = runs[runs["version"] == base_version]
    test_runs = runs[runs["version"] == test_version]
    comparison = build_collection_metric_deltas(base_runs, base_version, test_runs, test_version, metrics)
    if comparison.empty:
        raise ValueError("No models are present in both selected versions.")
    commands.print_dataframe(Console(), comparison, f"{test_version} minus {base_version}")
    print_saved_archive(
        create_comparison_archive(
            comparison_archive_root(archive_dir, analysis_settings),
            comparison_type="versions",
            base_label=base_version,
            test_label=test_version,
            base_runs=base_runs,
            test_runs=test_runs,
            comparison=comparison,
            metrics=metrics,
        )
    )


@compare.command("models")
@click.option("--base", "base_models", multiple=True, required=True, help="Base model; repeat for several.")
@click.option("--test", "test_models", multiple=True, required=True, help="Test model; repeat for several.")
@comparison_options
@handle_errors
def compare_models(
    base_models: tuple[str, ...],
    test_models: tuple[str, ...],
    database: Path | None,
    settings: Path | None,
    archive_dir: Path | None,
    metric: str | None,
) -> None:
    """Compare aggregate values for two model groups."""
    runs, available_metrics, _, analysis_settings = load_command_runs(database, settings)
    metrics = commands.selected_metrics(metric, available_metrics)
    base_runs = runs[runs["model"].isin(base_models)]
    test_runs = runs[runs["model"].isin(test_models)]
    if base_runs.empty or test_runs.empty:
        raise ValueError("Both model selections must match at least one run.")
    comparison = build_model_comparison(runs, list(base_models), list(test_models), metrics)
    commands.print_dataframe(Console(), comparison, f"Models {', '.join(test_models)} minus {', '.join(base_models)}")
    print_saved_archive(
        create_comparison_archive(
            comparison_archive_root(archive_dir, analysis_settings),
            comparison_type="models",
            base_label=", ".join(base_models),
            test_label=", ".join(test_models),
            base_runs=base_runs,
            test_runs=test_runs,
            comparison=comparison,
            metrics=metrics,
            parameters={"base_models": list(base_models), "test_models": list(test_models)},
        )
    )


@compare.command("collections")
@click.option("--field", required=True, help="Database column used to select each collection.")
@click.option("--base", "base_values", multiple=True, required=True, help="Base value; repeat for several.")
@click.option("--test", "test_values", multiple=True, required=True, help="Test value; repeat for several.")
@click.option("--match", "match_mode", type=MATCH_MODE, default="exact", show_default=True)
@click.option("--terse", is_flag=True, help="Print one compact delta table without saving a snapshot.")
@comparison_options
@handle_errors
def compare_collections(
    field: str,
    base_values: tuple[str, ...],
    test_values: tuple[str, ...],
    match_mode: str,
    terse: bool,
    database: Path | None,
    settings: Path | None,
    archive_dir: Path | None,
    metric: str | None,
) -> None:
    """Compare two collections selected from any database field."""
    runs, available_metrics, _, analysis_settings = load_command_runs(database, settings)
    metrics = commands.selected_metrics(metric, available_metrics)
    console = Console()
    if terse:
        commands.show_terse_collection_comparison(
            console, runs, field, list(base_values), list(test_values), match_mode, metrics
        )
        return
    base_runs = select_collection(runs, field, list(base_values), match_mode)
    test_runs = select_collection(runs, field, list(test_values), match_mode)
    if base_runs.empty or test_runs.empty:
        raise ValueError("Both collection selections must match at least one run.")
    base_label = ", ".join(base_values)
    test_label = ", ".join(test_values)
    comparison = build_collection_metric_deltas(base_runs, base_label, test_runs, test_label, metrics)
    if comparison.empty:
        raise ValueError("No models are present in both selected collections.")
    commands.print_dataframe(console, comparison, f"{test_label} minus {base_label}")
    print_saved_archive(
        create_comparison_archive(
            comparison_archive_root(archive_dir, analysis_settings),
            comparison_type="collections",
            base_label=base_label,
            test_label=test_label,
            base_runs=base_runs,
            test_runs=test_runs,
            comparison=comparison,
            metrics=metrics,
            parameters={
                "field": field,
                "match": match_mode,
                "base_values": list(base_values),
                "test_values": list(test_values),
            },
        )
    )


@compare.command("runs")
@click.argument("top_uid")
@click.argument("bottom_uid")
@comparison_options
@handle_errors
def compare_runs(
    top_uid: str,
    bottom_uid: str,
    database: Path | None,
    settings: Path | None,
    archive_dir: Path | None,
    metric: str | None,
) -> None:
    """Compare scalar metrics for two runs selected by UID."""
    runs, available_metrics, _, analysis_settings = load_command_runs(database, settings)
    metrics = commands.selected_metrics(metric, available_metrics)
    top_matches = runs[runs["uid"].astype(str) == top_uid]
    bottom_matches = runs[runs["uid"].astype(str) == bottom_uid]
    if len(top_matches) != 1:
        raise ValueError(f"Top UID {top_uid!r} must match exactly one run; found {len(top_matches)}.")
    if len(bottom_matches) != 1:
        raise ValueError(f"Bottom UID {bottom_uid!r} must match exactly one run; found {len(bottom_matches)}.")
    if top_uid == bottom_uid:
        raise ValueError("Choose two different run UIDs.")

    top_run = top_matches.iloc[0]
    bottom_run = bottom_matches.iloc[0]
    comparison = build_run_scalar_comparison(top_run, bottom_run, metrics)
    commands.print_dataframe(Console(), comparison, f"Run {bottom_uid} minus {top_uid}")
    print_saved_archive(
        create_comparison_archive(
            comparison_archive_root(archive_dir, analysis_settings),
            comparison_type="runs",
            base_label=top_uid,
            test_label=bottom_uid,
            base_runs=top_matches,
            test_runs=bottom_matches,
            comparison=comparison,
            metrics=metrics,
            parameters={"orientation": "bottom_minus_top"},
            artifact_paths=local_artifact_paths(
                pd.concat([top_matches, bottom_matches], ignore_index=True),
                analysis_settings["database"].get("artifact_root", ""),
            ),
        )
    )


@cli.group("archive")
def archive_group() -> None:
    """Inspect and recover saved comparison snapshots."""


def archive_search_options(function: CommandCallback) -> CommandCallback:
    """Add archive search settings to inspection commands."""
    decorators = (
        click.option(
            "--archive-dir",
            type=click.Path(file_okay=False, path_type=Path),
            multiple=True,
            help="Archive search directory; repeat to search several and override settings.",
        ),
        click.option(
            "--settings",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            help="Analysis settings TOML containing archive.search_paths.",
        ),
    )
    callback: Callable[..., Any] = function
    for decorator in reversed(decorators):
        callback = decorator(callback)
    return cast(CommandCallback, callback)


def archive_search_roots(archive_dirs: tuple[Path, ...], settings_path: Path | None) -> list[Path]:
    """Resolve explicit archive directories or configured search paths."""
    if archive_dirs:
        return list(archive_dirs)
    settings = load_command_settings(settings_path)
    return [Path(path) for path in settings.get("archive", {}).get("search_paths", ["qa_tool_archive"])]


@archive_group.command("list")
@archive_search_options
def list_archives(archive_dir: tuple[Path, ...], settings: Path | None) -> None:
    """List saved comparison snapshots."""
    table = Table("ID", "Created", "User", "Type", "Base", "Test")
    for item in list_comparison_archives_from_roots(archive_search_roots(archive_dir, settings)):
        manifest = item.manifest
        table.add_row(
            item.snapshot_id,
            str(manifest.get("created_at", "")),
            str(manifest.get("created_by", "unknown")),
            str(manifest.get("comparison_type", "")),
            str(manifest.get("base_label", "")),
            str(manifest.get("test_label", "")),
        )
    Console().print(table)


@archive_group.command("show")
@click.argument("snapshot_id")
@archive_search_options
@handle_errors
def show_archive(snapshot_id: str, archive_dir: tuple[Path, ...], settings: Path | None) -> None:
    """Show the manifest for one comparison snapshot."""
    item = find_comparison_archive_in_roots(archive_search_roots(archive_dir, settings), snapshot_id)
    Console().print_json(data=item.manifest)
    Console().print(f"[dim]{item.path}[/dim]")


@archive_group.command("verify")
@click.argument("snapshot_id")
@archive_search_options
@handle_errors
def verify_archive(snapshot_id: str, archive_dir: tuple[Path, ...], settings: Path | None) -> None:
    """Verify every recorded file checksum in a comparison snapshot."""
    item = find_comparison_archive_in_roots(archive_search_roots(archive_dir, settings), snapshot_id)
    failures = verify_comparison_archive(item)
    if failures:
        raise ValueError("Archive verification failed: " + "; ".join(failures))
    Console().print(f"[bold green]Verified comparison {item.snapshot_id}[/bold green]")


@archive_group.command("export")
@click.argument("snapshot_id")
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), required=True)
@click.option("--force", is_flag=True, help="Replace an existing output file.")
@archive_search_options
@handle_errors
def export_archive(
    snapshot_id: str,
    output: Path,
    force: bool,
    archive_dir: tuple[Path, ...],
    settings: Path | None,
) -> None:
    """Recover a snapshot's standalone HTML report."""
    item = find_comparison_archive_in_roots(archive_search_roots(archive_dir, settings), snapshot_id)
    if output.exists() and not force:
        raise ValueError(f"Output already exists: {output}. Use --force to replace it.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes((item.path / "report.html").read_bytes())
    Console().print(f"Exported {item.snapshot_id} to {output}")


@report.command("breakdown")
@click.option(
    "--by",
    "slice_by",
    type=click.Choice(["model", "version"]),
    default="model",
    show_default=True,
    help="Field used to group the breakdown.",
)
@analysis_options
@click.pass_context
@handle_errors
def report_breakdown(
    context: click.Context,
    slice_by: str,
    database: Path | None,
    settings: Path | None,
    output_dir: Path,
    formats: tuple[str, ...],
    metric: str | None,
) -> None:
    """Create run-count or metric-total breakdown charts."""
    runs, metrics, plot_height, selected_formats = prepare_analysis(database, settings, metric, formats)
    breakdown_metrics: list[str | None] = [None, *metrics] if metric is None else metrics
    console = Console()
    for selected_metric in breakdown_metrics:
        commands.show_breakdown(
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
