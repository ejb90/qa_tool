# QA Tool

![tests](https://github.com/ejb90/qa_tool/actions/workflows/test.yml/badge.svg)
[![License](https://img.shields.io/github/license/ejb90/qa_tool)](LICENSE.md)
![Ruff](https://img.shields.io/badge/code%20style-ruff-261230)
[![Documentation](https://readthedocs.org/projects/qa-tool/badge/?version=latest)](https://qa-tool.readthedocs.io/en/latest/?badge=latest)
[![PyPI](https://img.shields.io/pypi/v/qa-tool)](https://pypi.org/project/qa-tool/)
[![Python versions](https://img.shields.io/pypi/pyversions/qa-tool)](https://pypi.org/project/qa-tool/)

DuckDB-backed web and command-line tools for browsing and comparing QA/regression runs.

[Live Streamlit app](https://apptool-mqfugq9a6cwqqje6zklh2o.streamlit.app/)

For setup, ingestion, configuration, UI, CLI, export, and development guides, see the [MkDocs documentation](docs/index.md).

## What It Does

The app reads run metadata from DuckDB and links each run back to an artifact directory containing detailed output files, including Parquet time-series data.

Current views include:

- all runs, with search, sorting, and pagination
- version and model summaries
- compare versions
- compare arbitrary collections of runs
- compare two runs directly
- run detail pages with Parquet time-series plots
- pie charts and summary tables

Comparison pages include aggregate tables with standard deviations and percentage differences, CDF plots, bar charts, coloured difference cells, and downloads of the calculated comparison data.

## Project Layout

```text
qa_tool_core/      # Shared DuckDB queries, comparisons, and Plotly figure builders
qa_tool_webapp/    # Streamlit user interface
qa_tool_cli/       # Rich terminal user interface
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
uv run streamlit run qa_tool_webapp/app.py
```

## Run with Docker

The repository includes a `Dockerfile` that packages the web application. The
database and artifacts are deliberately excluded from the image; mount them at
runtime so data can be updated independently of the application image.

```bash
docker build -t qa-tool .
docker run --rm -p 8501:8501 \
  -v "$PWD/runs.duckdb:/app/runs.duckdb" \
  -v "$PWD/store:/app/store:ro" \
  qa-tool
```

Open <http://localhost:8501> after the container starts. The DuckDB database
is mounted read/write for ingestion; artifact files are mounted read-only
because the dashboard only reads them.

The default base image is `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`. To
build from a Harbor-mirrored copy instead, supply its full image name:

```bash
docker build \
  --build-arg BASE_IMAGE=harbor.example.com/base/uv:python3.13-bookworm-slim \
  -t qa-tool .
```

Replace `harbor.example.com/base/uv:python3.13-bookworm-slim` with your
organization's Harbor repository and tag.

For Docker Swarm, adapt [swarm-compose.yml](swarm-compose.yml) with your
Harbor image name and administrator-provisioned data paths, then deploy it from
a Swarm manager:

```bash
docker stack deploy --with-registry-auth -c swarm-compose.yml qa-tool
```

See [the deployment workflow](docs/deployment.md) for safely refreshing the
dashboard from object-store snapshots when new runs arrive every few minutes.

## Install from PyPI

Install the command-line and ingestion tools from PyPI:

```bash
pip install qa-tool
# or
uv tool install qa-tool
```

The web interface is included in the package. Start it with:

```bash
qa_tool_webapp
```

For the complete setup and configuration guide, see the [Read the Docs documentation](https://qa-tool.readthedocs.io/).

By default the app uses `qa_tool_webapp/default_settings.toml`, which points at:

```toml
[database]
path = "runs.duckdb"
artifact_root = "./store"
```

## Rebuild The Database

The app uses DuckDB only. Ingest each run artifact with `qa_tool_ingest` to append its metadata and refresh the summary table.

## Command-line interface

`qa_tool` reads the same settings and DuckDB database as the web application. By default it generates tables and plots for every numeric variable, writing HTML and PNG plots plus CSV and Parquet raw-data and displayed-table files to `qa_tool_output/` (or `--output-dir`). Use `--metric` to select one variable, `--database` to override the configured database, and `--formats` to select artifacts, for example `--formats png csv` or `--formats html parquet`.

```bash
# Tables by version and a plot for each selected model
uv run qa_tool model --models h2 co2 --metric density

# Tables by model, a multi-model version plot, and an empirical CDF
uv run qa_tool version --versions v1.0.0 v2.0.0 --metric density --cdf-version v2.0.0

# Compare two versions across their shared models
uv run qa_tool compare versions --base-version v1.0.0 --test-version v2.0.0 --metric density

# Compare aggregate values for two model selections
uv run qa_tool compare models --base-models h2 --test-models co2 --metric density

# Compare arbitrary collections using a database column and matching values
uv run qa_tool compare collections --field git_branch --base main --test release --metric density

# Donut charts by model or version; omit --metric for run counts and every numeric metric
uv run qa_tool pie --slice-by model
uv run qa_tool pie --slice-by version --metric density
```

`compare collections` supports `--match exact`, `starts-with`, `contains`, `regex`, and `non-empty`. For a datetime field, give a start and end value to `--base` and `--test`.

PNG generation uses Kaleido and a local Chrome-compatible browser. If that optional renderer is unavailable, choose `--formats html csv parquet` to keep all non-image artifacts.

Each metadata file is expected to contain the run-level fields used by the app, including identifiers, model/version information, scalar metrics, and the artifact path.

## Ingest a Run

`qa_tool_ingest` appends a metadata JSON document to DuckDB, records its artifact directory, adds newly discovered JSON keys as columns, and rebuilds `run_summary`.

```bash
uv run python -m qa_tool_ingest store/my-run --metadata store/my-run/metadata.json
```

The ingestion TOML's `[database].path` is the default destination. Override it per command with `--database`:

```bash
uv run python -m qa_tool_ingest store/my-run --settings ingest.toml --database other-runs.duckdb
```

By default, every top-level JSON key is stored. Use an ingestion settings file to select or rename keys and define summary aggregates:

```toml
[database]
path = "runs.duckdb"

[input]
include = ["uid", "model", "version", "date", "elapsed_seconds"]

[input.rename]
model = "device"

[summary]
distinct_columns = ["model", "version"]
mean_columns = ["elapsed_seconds"]
```

## Artifact Data

Each run has an artifact directory under `store/`. The app uses the database row to find the artifact directory, then loads Parquet files from that directory when detailed time-series plots are needed.

For Parquet plotting, files with a time-like column such as `time`, `Time`, or `TIME` are treated as time series. Other numeric columns are plotted as material or quantity lines depending on the comparison view.

## Settings

The main settings live in `qa_tool_webapp/default_settings.toml`.

Useful sections:

- `[database]`: database path and artifact root
- `[tabs]`: enable or disable app tabs
- `[tables.all_runs].columns`: choose and order All Runs table columns
- `[summaries]`: configure summary metrics per tab
- `[plots]`: plot sizing
- `[comparison.color_bounds]`: optional fixed colour limits, in percentage points, for comparison differences

Example colour bounds:

```toml
[comparison.color_bounds]
metric_name = 0.1
```

Metrics without explicit bounds keep the automatic scaling behaviour.

## Performance Comparison

The `performance_comparison/` directory contains scripts for comparing SQLite and DuckDB query performance at different database sizes.

```bash
uv run python performance_comparison/compare.py
uv run python performance_comparison/plot_results.py
```

Generated results include CSV/Markdown summaries and an HTML performance plot.

## Development Checks

Compile the main modules:

```bash
uv run python -m py_compile qa_tool_webapp/app.py qa_tool_webapp/settings.py qa_tool_webapp/compare.py qa_tool_webapp/exports.py qa_tool_webapp/styling.py
```

Run tests:

```bash
uv run pytest
```
