# QA Tool

Interactive Streamlit dashboard for browsing and comparing QA/regression runs.

[Live Streamlit app](https://apptool-qt5hejbcu4yzxgxsndhvem.streamlit.app/)

## What It Does

The app reads run metadata from a DuckDB or SQLite database and links each run back to an artifact directory containing detailed output files, including Parquet time-series data.

Current views include:

- all runs, with search, sorting, and pagination
- version and model summaries
- compare versions
- compare arbitrary collections of runs
- compare two runs directly
- run detail pages with Parquet time-series plots
- pie charts and summary tables

Comparison pages include aggregate tables, CDF plots, bar charts, coloured delta cells, and downloads of the calculated comparison data.

## Project Layout

```text
qa_tool/
  app.py                  Streamlit app
  default_settings.toml   Packaged default settings
  load_dummy_data.py      Load store/*/metadata.json into SQLite and DuckDB
  build_dummy_data.py     Generate dummy run artifacts
  compare.py             Comparison calculations
  styling.py             Table colouring and comparison styling
  exports.py             Download/export helpers

store/
  <run-artifact>/
    metadata.json
    *.parquet

runs.duckdb              Default local app database
performance_comparison/ Benchmark scripts and results
```

## Setup

This project uses `uv`.

```bash
uv sync
```

## Run Locally

```bash
uv run streamlit run qa_tool/app.py
```

By default the app uses `qa_tool/default_settings.toml`, which points at:

```toml
[database]
path = "runs.duckdb"
artifact_root = "./store"
```

## Rebuild The Database

The loader reads metadata from `store/*/metadata.json` and writes both SQLite and DuckDB databases.

```bash
uv run python -m qa_tool.load_dummy_data \
  --store-dir store \
  --sqlite-db runs.db \
  --duckdb-db runs.duckdb
```

Each metadata file is expected to contain the run-level fields used by the app, including identifiers, model/version information, scalar metrics, and the artifact path.

## Artifact Data

Each run has an artifact directory under `store/`. The app uses the database row to find the artifact directory, then loads Parquet files from that directory when detailed time-series plots are needed.

For Parquet plotting, files with a time-like column such as `time`, `Time`, or `TIME` are treated as time series. Other numeric columns are plotted as material or quantity lines depending on the comparison view.

## Settings

The main settings live in `qa_tool/default_settings.toml`.

Useful sections:

- `[database]`: database path and artifact root
- `[tabs]`: enable or disable app tabs
- `[summaries]`: configure summary metrics per tab
- `[plots]`: plot sizing
- `[comparison.color_bounds]`: optional fixed colour limits for comparison deltas

Example colour bounds:

```toml
[comparison.color_bounds]
density = 0.1
velocity = 0.05
runtime = 10.0
```

Metrics without explicit bounds keep the automatic scaling behaviour.

## Performance Comparison

The `performance_comparison/` directory contains scripts for comparing SQLite and DuckDB query performance at different database sizes.

```bash
uv run python performance_comparison/compare.py
uv run python performance_comparison/plot_results.py
```

Generated results include CSV/Markdown summaries and an HTML runtime plot.

## Development Checks

Compile the main modules:

```bash
uv run python -m py_compile qa_tool/app.py qa_tool/settings.py qa_tool/compare.py qa_tool/exports.py qa_tool/styling.py
```

Run tests:

```bash
uv run pytest
```
