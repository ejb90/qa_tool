# Getting started

## Install

Install the published package with pip:

```bash
pip install qa-tool
```

Or use uv to install the CLI as a managed tool:

```bash
uv tool install qa-tool
```

For development from a checkout, QA Tool uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

This installs the web app, ingestion package, CLI, test tools, Plotly, and Kaleido for PNG export.

## Expected local layout

```text
project/
├── runs.duckdb
├── store/
│   └── my-run/
│       ├── metadata.json
│       └── density.parquet
└── settings.toml        # optional
```

`runs.duckdb` is the default database. Artifact directories can live elsewhere; record their path in the `artifact` field during ingestion.

## Add a run

Place a JSON metadata file in the artifact directory, then ingest it:

```bash
qa_tool_ingest store/my-run
```

The command uses `store/my-run/metadata.json` by default, appends the run to `runs.duckdb`, and refreshes `run_summary`.

## Open the dashboard

```bash
qa_tool_webapp
```

The splash page reads only `run_summary`, so it opens without loading the complete run table. Other tabs load the detailed `runs` data only when opened.

## Run a terminal report

```bash
qa_tool model --models h2 co2 --metric density
```

This prints a Rich table and writes plots and data artifacts into `qa_tool_output/`. See [Command line](cli.md) for every command and export option.

!!! tip "Use a different database"

    Both ingestion and the CLI accept `--database path/to/other.duckdb`. The CLI argument takes precedence over the database path in settings.
