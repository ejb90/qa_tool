# Ingestion

`qa_tool_ingest` turns an artifact directory and one JSON metadata document into a row in DuckDB. It appends the row, evolves the table schema when necessary, records the artifact path, and rebuilds `run_summary`.

## Basic use

```bash
uv run python -m qa_tool_ingest store/my-run
```

By default the metadata file is `store/my-run/metadata.json`. Specify another file when needed:

```bash
uv run python -m qa_tool_ingest store/my-run --metadata results/run.json
```

## Choose a database

The ingestion settings file supplies the default destination. A command-line database always wins:

```bash
uv run python -m qa_tool_ingest store/my-run \
  --settings ingest.toml \
  --database results/experiment.duckdb
```

## Metadata example

```json
{
  "uid": "e2f3bdf2",
  "model": "h2",
  "version": "v2.1.0",
  "date": "2026-07-10T12:30:00",
  "density": 1.41,
  "error": 0.003,
  "git_branch": "release",
  "modified": false
}
```

Top-level scalar values are stored in native DuckDB columns. Nested objects and lists are stored as JSON text, preserving their information without forcing a fixed nested schema.

## Select, exclude, and rename keys

Start from `qa_tool_ingest/default_settings.toml`, then create an override such as:

```toml
[database]
path = "runs.duckdb"
runs_table = "runs"
summary_table = "run_summary"

[input]
include = ["run_id", "device", "release", "date", "density", "elapsed_seconds"]
exclude = []
artifact_column = "artifact"

[input.rename]
uid = "run_id"
model = "device"
version = "release"

[summary]
distinct_columns = ["model", "version"]
mean_columns = ["density", "elapsed_seconds"]
```

An empty `include` ingests every top-level JSON key. `rename` provides the output-column name on the left and JSON key on the right.

## What gets updated

After every successful insertion, ingestion rebuilds `run_summary` with:

- `refreshed_at`
- `run_count`
- one `<column>_count` field for every configured, available `distinct_columns` entry
- one `mean_<column>` field for every configured numeric `mean_columns` entry

The splash page renders all non-metadata fields in that summary row, so the summary can grow with your needs.
