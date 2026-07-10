"""Plot benchmark runtime against database size."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import plotly.graph_objects as go

SeriesKey = tuple[str, str]


def load_series(results_path: Path) -> dict[SeriesKey, list[tuple[int, float]]]:
    """Load benchmark runtime series from a comparison CSV."""
    series: dict[SeriesKey, list[tuple[int, float]]] = defaultdict(list)
    with results_path.open(encoding="utf-8", newline="") as results_file:
        reader = csv.DictReader(results_file)
        for row in reader:
            database_rows = int(row["database_rows"])
            query = row["query"]
            series[(query, "SQLite")].append((database_rows, float(row["sqlite_ms"])))
            series[(query, "DuckDB")].append((database_rows, float(row["duckdb_ms"])))

    for values in series.values():
        values.sort(key=lambda item: item[0])
    return dict(series)


def build_figure(series: dict[SeriesKey, list[tuple[int, float]]]) -> go.Figure:
    """Build a Plotly runtime comparison figure."""
    figure = go.Figure()
    colors = [
        "#2563eb",
        "#dc2626",
        "#16a34a",
        "#9333ea",
        "#ea580c",
        "#0891b2",
        "#be123c",
        "#4d7c0f",
        "#7c3aed",
    ]
    queries = sorted({query for query, _engine in series})
    color_by_query = {
        query: colors[index % len(colors)]
        for index, query in enumerate(queries)
    }

    for query in queries:
        for engine, dash in (("SQLite", "solid"), ("DuckDB", "dash")):
            values = series[(query, engine)]
            figure.add_trace(
                go.Scatter(
                    x=[database_rows for database_rows, _runtime in values],
                    y=[runtime for _database_rows, runtime in values],
                    mode="lines+markers",
                    name=f"{query} ({engine})",
                    line={
                        "color": color_by_query[query],
                        "dash": dash,
                        "width": 2,
                    },
                    marker={"size": 7},
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>"
                        "DB rows: %{x:,}<br>"
                        "Runtime: %{y:.3f} ms"
                        "<extra></extra>"
                    ),
                )
            )

    figure.update_layout(
        title="Benchmark Runtime vs Database Size",
        xaxis_title="Database rows",
        yaxis_title="Median runtime (ms)",
        xaxis={"type": "log", "tickformat": ",d"},
        yaxis={"type": "log"},
        hovermode="closest",
        template="plotly_white",
        legend={
            "orientation": "v",
            "yanchor": "top",
            "y": 1,
            "xanchor": "left",
            "x": 1.02,
        },
        margin={"l": 70, "r": 260, "t": 70, "b": 60},
        width=1400,
        height=850,
    )
    return figure


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    argument_parser = argparse.ArgumentParser(
        description="Plot runtime vs database size from performance comparison results."
    )
    argument_parser.add_argument(
        "--results",
        default=Path("performance_comparison/results.csv"),
        type=Path,
        help="CSV results file produced by compare.py --scaled.",
    )
    argument_parser.add_argument(
        "--output",
        default=Path("performance_comparison/runtime_vs_db_size.html"),
        type=Path,
        help="HTML plot output path.",
    )
    return argument_parser


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the runtime comparison plot."""
    args = parser().parse_args(argv)
    series = load_series(args.results)
    figure = build_figure(series)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(args.output, include_plotlyjs="cdn", full_html=True)
    print(f"Wrote runtime plot to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
