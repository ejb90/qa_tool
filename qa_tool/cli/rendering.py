"""Rich-table and Plotly-file rendering for the QA Tool CLI."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
from typing import Literal, TextIO

import pandas as pd
from plotly.graph_objects import Figure
from rich.console import Console
from rich.markup import escape
from rich.table import Table

OutputFormat = Literal["html", "png", "csv", "parquet"]


def require_png_support(formats: list[OutputFormat]) -> None:
    """Reject PNG output when the optional Kaleido dependency is unavailable."""
    if "png" in formats and find_spec("kaleido") is None:
        raise ValueError(
            "PNG export requires the optional `png` dependencies. Install them with "
            "`pip install 'qa-tool[png]'`, `uv tool install 'qa-tool[png]'`, or `uv sync --extra png`."
        )


def print_dataframe(console: Console, dataframe: pd.DataFrame, title: str) -> None:
    """Print a dataframe as a consistently formatted Rich table."""
    table = Table(title=title, show_lines=False)
    for column in dataframe.columns:
        table.add_column(str(column), overflow="fold")
    for row in dataframe.itertuples(index=False, name=None):
        table.add_row(*[format_value(value) for value in row])
    console.print(table)


def format_value(value: object) -> str:
    """Format scalar dataframe values compactly for a terminal table."""
    if isinstance(value, float):
        return f"{value:.6g}"
    if pd.isna(value):
        return ""
    return str(value)


def write_dataframe(dataframe: pd.DataFrame, output_dir: Path, name: str, formats: list[OutputFormat]) -> list[Path]:
    """Write a dataframe in each requested tabular format and return the created paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    if "csv" in formats:
        path = output_dir / f"{name}.csv"
        dataframe.to_csv(path, index=False)
        paths.append(path)
    if "parquet" in formats:
        path = output_dir / f"{name}.parquet"
        dataframe.to_parquet(path, index=False)
        paths.append(path)
    return paths


def write_plot(
    figure: Figure,
    raw_data: pd.DataFrame,
    table_data: pd.DataFrame,
    output_dir: Path,
    name: str,
    formats: list[OutputFormat],
    stderr: TextIO | None = None,
) -> list[Path]:
    """Write requested plot files plus raw plot data and the displayed table beside them."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    if "html" in formats:
        path = output_dir / f"{name}.html"
        figure.write_html(path, include_plotlyjs="cdn", full_html=True)
        paths.append(path)
    paths.extend(write_dataframe(raw_data, output_dir, name, formats))
    paths.extend(write_dataframe(table_data, output_dir, f"{name}_table", formats))
    if "png" in formats:
        path = output_dir / f"{name}.png"
        try:
            figure.write_image(path)
        except (RuntimeError, ValueError) as error:
            raise ValueError(
                "PNG export failed. Install the optional `qa-tool[png]` dependencies and ensure "
                "Kaleido can access a compatible Chrome or Chromium browser."
            ) from error
        else:
            paths.append(path)
    output_console = Console(file=stderr) if stderr is not None else Console(stderr=True)
    if stderr is not None:
        output_console.print("[bold cyan]Wrote files:[/bold cyan]")
        for path in paths:
            output_console.print(f"  [dim]{escape(str(path))}[/dim]", soft_wrap=True)
    elif len(paths) == 1:
        output_console.print(
            f"[bold green]✓[/bold green] Wrote [cyan]{escape(str(paths[0]))}[/cyan]",
            soft_wrap=True,
        )
    else:
        output_console.print(
            f"[bold green]✓[/bold green] Wrote [cyan]{len(paths)} files[/cyan] to "
            f"[cyan]{escape(str(output_dir))}[/cyan]",
            soft_wrap=True,
        )
    return paths
