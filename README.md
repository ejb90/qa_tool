# QA Tool

[![Tests](https://github.com/ejb90/qa_tool/actions/workflows/test.yml/badge.svg)](https://github.com/ejb90/qa_tool/actions/workflows/test.yml)
[![Documentation](https://readthedocs.org/projects/qa-tool/badge/?version=latest)](https://qa-tool.readthedocs.io/en/latest/)
[![PyPI](https://img.shields.io/pypi/v/qa-tool)](https://pypi.org/project/qa-tool/)
[![Python versions](https://img.shields.io/pypi/pyversions/qa-tool)](https://pypi.org/project/qa-tool/)
[![License](https://img.shields.io/github/license/ejb90/qa_tool)](LICENSE.md)

QA Tool collects run metadata in DuckDB and exposes it through a Streamlit dashboard and a Rich command-line interface. It is designed for regression and quality-assurance results that have scalar metadata plus optional artifact files such as Parquet time series.

## Capabilities

- ingest JSON metadata into an evolving DuckDB schema
- browse, filter, and download run data in Streamlit
- compare versions, models, arbitrary collections, or individual runs
- create Plotly trends, CDFs, difference charts, and donut charts
- export interactive HTML, CSV, and Parquet by default
- export static PNG files through an optional Kaleido installation

## Install

```bash
pip install qa-tool
# or
uv tool install qa-tool
```

Optional extras:

```bash
pip install "qa-tool[png]"   # Static Plotly PNG export
pip install "qa-tool[docs]"  # Build this MkDocs site
```

See the [installation guide](https://qa-tool.readthedocs.io/en/latest/installation/) for uv development setup and combined extras.

## Quick start

Create `store/my-run/metadata.json`:

```json
{
  "uid": "run-001",
  "model": "h2",
  "version": "v1.0.0",
  "date": "2026-11-17T12:00:00Z",
  "density": 1.41
}
```

Ingest it. The command creates `runs.duckdb` and its tables when they do not already exist:

```bash
qa-tool ingest store/my-run
```

Open the dashboard:

```bash
qa-tool webapp
```

Or create a terminal report and export files:

```bash
qa-tool model h2 --metric density
```

## Documentation

- [Getting started](https://qa-tool.readthedocs.io/en/latest/getting-started/)
- [Data ingestion](https://qa-tool.readthedocs.io/en/latest/ingestion/)
- [Configuration](https://qa-tool.readthedocs.io/en/latest/configuration/)
- [Command line](https://qa-tool.readthedocs.io/en/latest/cli/)
- [Plots and exports](https://qa-tool.readthedocs.io/en/latest/plotting/)
- [Web application](https://qa-tool.readthedocs.io/en/latest/web-app/)
- [Deployment](https://qa-tool.readthedocs.io/en/latest/deployment/)
- [Python API](https://qa-tool.readthedocs.io/en/latest/api/)

The complete manual is built with MkDocs and published on [Read the Docs](https://qa-tool.readthedocs.io/).

## Development

```bash
uv sync --group dev --extra docs
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run mkdocs build --strict
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full release checks.
