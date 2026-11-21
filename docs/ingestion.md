# Data ingestion

`qa-tool ingest` converts one JSON metadata object and its artifact location into a row in DuckDB. The artifact can be a directory or a `.tar`, `.tar.gz`, or `.tgz` archive. Ingestion creates the database on first use, evolves the `runs` schema when new keys appear, records the artifact path, and rebuilds `run_summary` after every insertion.

## Ingest one run

Given this layout:

```text
store/
└── my-run/
    ├── metadata.json
    ├── density.parquet
    └── report.txt
```

run:

```bash
qa-tool ingest store/my-run
```

The metadata path defaults to `<artifact_dir>/metadata.json`. Override it when the JSON lives elsewhere:

```bash
qa-tool ingest store/my-run --metadata results/my-run.json
```

Choose a destination database explicitly:

```bash
qa-tool ingest store/my-run --database results/experiment.duckdb
```

Parent directories and the `.duckdb` file are created automatically.

## Ingest a tar archive

Pass an archive in place of the artifact directory:

```bash
qa-tool ingest results/my-run.tar.gz
```

The archive can contain nested directories. QA Tool uses its sole JSON member as metadata, or prefers a file named `metadata.json` when the archive also contains other JSON artifacts. The Parquet files do not need to be named or referenced by the metadata; recording the archive as the run's artifact location associates every file in it with that run.

If an archive has several possible metadata JSON files and none is uniquely named `metadata.json`, select the member explicitly using its archive-relative path:

```bash
qa-tool ingest results/my-run.tar.gz --metadata output/run.json
```

Ambiguous archives are rejected rather than choosing a JSON file arbitrarily. Metadata is read directly from the archive without extracting it during ingestion. The dashboard safely extracts the archive to a temporary location when you inspect the run's artifacts.

## Metadata format

The JSON document must contain an object at its top level:

```json
{
  "uid": "e2f3bdf2",
  "name": "release density",
  "model": "h2",
  "version": "v2.1.0",
  "date": "2026-11-17T12:30:00Z",
  "density": 1.41,
  "error": 0.003,
  "git_branch": "release",
  "modified": false,
  "provenance": {
    "commit": "abc123"
  }
}
```

Top-level scalar values are stored using DuckDB-compatible native types inferred from the first row. Dictionaries and lists are serialized as JSON text. The ingestion command adds its own `artifact` value containing the artifact-directory path supplied on the command line.

The analysis interfaces expect these conventional fields:

| Field | Purpose |
| --- | --- |
| `uid` | Stable run identifier. |
| `date` | Sorting and date-window selection. |
| `model` | Default model/device/material grouping. |
| `version` | Default release grouping. |
| `name` | Optional display name; the analysis layer falls back to `uid`. |
| `modified` | Optional filtering of modified runs. |

Any other numeric column is eligible for tables, summaries, and plots.

## Configure ingestion

Create an `ingest.toml` override when metadata keys need selecting or renaming:

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

Apply it with:

```bash
qa-tool ingest store/my-run --settings ingest.toml
```

An empty `include` list selects every top-level key. `exclude` removes selected keys. Each rename uses the output column on the left and source JSON key on the right.

## Schema evolution

The first row creates the `runs` table. For later rows, ingestion:

1. compares incoming fields with existing columns;
2. adds missing columns using the incoming DuckDB type;
3. inserts values for the fields present in that run;
4. leaves other existing columns null;
5. replaces `run_summary` with freshly calculated values.

`run_summary` always contains `refreshed_at` and `run_count`. It also contains `<column>_count` for configured distinct columns and `mean_<column>` for configured numeric mean columns.

!!! warning "Type changes"

    Schema evolution adds columns; it does not migrate an existing column to a new type. Keep the type of a metadata key consistent across runs.

## Ingest several directories

The command accepts one artifact directory or tar archive at a time. A shell loop can ingest an existing store:

```bash
for run_dir in store/*; do
  [ -f "$run_dir/metadata.json" ] || continue
  qa-tool ingest "$run_dir"
done
```

For automated pipelines, stop on the first failed ingestion and publish the database only after the complete batch succeeds.

## Operational considerations

- Ingestion appends; it does not update or deduplicate an existing `uid`.
- Use one writer at a time. Do not let the dashboard or another job write the same DuckDB file concurrently.
- Store paths that remain valid wherever the dashboard runs. Relative artifact paths are resolved from the dashboard's working directory.
- When modifying `runs` outside QA Tool, rebuild `run_summary` before relying on the Overview page.
- For remote deployment, publish complete database-and-artifact snapshots rather than replacing a live database in place. See [Deployment](deployment.md).
