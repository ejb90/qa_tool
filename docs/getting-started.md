# Getting started

This guide creates a small DuckDB database from one run, opens the dashboard, and generates a CLI report. Start with [Installation](installation.md) if QA Tool is not installed yet.

## Prepare a run

When working from a repository checkout, you can use the included example
directly:

```bash
qa-tool ingest examples/sample-run
```

Alternatively, create your own artifact directory with this layout:

```text
store/
└── run-001/
    ├── metadata.json
    └── density.parquet    # optional detailed artifact
```

Use this minimal `store/run-001/metadata.json`:

```json
{
  "uid": "run-001",
  "name": "baseline density",
  "model": "h2",
  "version": "v1.0.0",
  "date": "2026-11-17T12:00:00Z",
  "density": 1.41
}
```

`uid`, `date`, `model`, and `version` support the default analysis schema. Other numeric top-level values, such as `density`, automatically become available as metrics.

## Create the database

Ingest the artifact directory:

```bash
qa-tool ingest store/run-001
```

The first ingestion creates `runs.duckdb`, a `runs` table, and a `run_summary` table. Later invocations append rows and add columns for newly discovered metadata keys.

Use a different destination when needed:

```bash
qa-tool ingest store/run-001 --database results/experiment.duckdb
```

## Open the dashboard

```bash
qa-tool webapp
```

Open <http://localhost:8501>. The Overview page reads the stored summary; analysis tabs load the detailed run rows when opened.

## Create a report

```bash
qa-tool model h2 --metric density
```

The command prints a Rich table and writes interactive HTML plus CSV and Parquet files to `qa_tool_output/`.

## Next steps

- Add production metadata with [Data ingestion](ingestion.md).
- Choose output formats in [Plots and exports](plotting.md).
- Compare versions and collections with the [Command line](cli.md).
- Change paths, columns, tabs, and summaries in [Configuration](configuration.md).
- Learn how tables evolve in [Data model](database.md).
