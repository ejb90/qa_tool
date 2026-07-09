"""Command-line entry point for DuckDB run ingestion."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich_argparse import RichHelpFormatter

from qa_tool_ingest.core import ingest_run
from qa_tool_ingest.settings import load_settings


console = Console()


def parse_args() -> argparse.Namespace:
    """Parse ingestion CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Append run metadata and refresh DuckDB summaries.",
        formatter_class=RichHelpFormatter,
    )
    parser.add_argument("artifact_dir", type=Path, help="Directory containing the run artifacts")
    parser.add_argument(
        "--metadata",
        type=Path,
        help="Metadata JSON path (defaults to <artifact_dir>/metadata.json)",
    )
    parser.add_argument("--settings", type=Path, help="Optional ingestion TOML settings")
    return parser.parse_args()


def main() -> None:
    """Ingest one run artifact directory."""
    args = parse_args()
    metadata_path = args.metadata or args.artifact_dir / "metadata.json"
    with console.status("[bold cyan]Ingesting metadata and refreshing summaries…"):
        result = ingest_run(args.artifact_dir, metadata_path, load_settings(args.settings))

    details = Table.grid(padding=(0, 2))
    details.add_column(style="bold cyan", justify="right")
    details.add_column()
    details.add_row("Artifact", str(args.artifact_dir))
    details.add_row("Database", str(result["database"]))
    details.add_row("Runs table", str(result["runs_table"]))
    details.add_row("Summary table", str(result["summary_table"]))
    details.add_row("Stored columns", ", ".join(result["columns"]))
    console.print(Panel(details, title="[bold green]✓ Ingested run", border_style="green"))
