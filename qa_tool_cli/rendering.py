"""Rich-table and Plotly-file rendering for the QA Tool CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TextIO

import pandas as pd
from plotly.graph_objects import Figure
from rich.console import Console
from rich.table import Table

OutputFormat = Literal["html", "png", "csv", "parquet"]


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
        except (RuntimeError, ValueError):
            if stderr is not None:
                print(
                    "Could not write PNG; install or repair Kaleido's Chrome-compatible browser backend. "
                    "Other requested artifacts were written.",
                    file=stderr,
                )
        else:
            paths.append(path)
    if stderr is not None:
        print(f"Wrote artifacts: {', '.join(str(path) for path in paths)}", file=stderr)
    return paths
