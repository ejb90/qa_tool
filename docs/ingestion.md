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

Top-level scalar values are stored using DuckDB-compatible native types inferred from the first non-null value for each field. A JSON `null` is treated as an absent value: it does not create or constrain a column, and becomes SQL `NULL` if a later run supplies that field. Dictionaries and lists are serialized as JSON text. The ingestion command adds its own `artifact` value containing the artifact-directory path supplied on the command line.

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
required = ["uid", "model", "version", "date"]

[input.rename]
uid = "run_id"
model = "device"
version = "release"

[input.types]
uid = "VARCHAR"
date = "TIMESTAMP"
density = "DOUBLE"
elapsed_seconds = "DOUBLE"

[summary]
distinct_columns = ["model", "version"]
mean_columns = ["density", "elapsed_seconds"]
```

Apply it with:

```bash
qa-tool ingest store/my-run --settings ingest.toml
```

An empty `include` list selects every top-level key. `exclude` removes selected keys. Each rename uses the output column on the left and source JSON key on the right.

`required` names stored columns after rename rules have been applied. By default, `uid`, `model`, `version`, and `date` must be present and non-null, and `date` must be parseable. Override the list only when intentionally building a database for a different consumer.

`[input.types]` optionally declares authoritative DuckDB types. Supported declarations are `BIGINT`, `BOOLEAN`, `DATE`, `DOUBLE`, `JSON`, `TIMESTAMP`, `TIMESTAMPTZ`, and `VARCHAR`. Declared columns are created even when their first value is `null`. Every non-null value is checked before the database schema is changed; incompatible values reject the complete ingestion. Undeclared fields continue to infer their type from their first non-null value. When a new type is inferred, the CLI prints a warning and ready-to-copy `[input.types]` entries; later rows using the already established type do not repeat that warning.

## Schema evolution

The first row creates the `runs` table. For later rows, ingestion:

1. compares incoming fields with existing columns;
2. adds missing columns using the incoming DuckDB type;
3. inserts values for the fields present in that run;
4. leaves other existing columns null;
5. replaces `run_summary` with freshly calculated values.

`run_summary` always contains `refreshed_at` and `run_count`. It also contains `<column>_count` for configured distinct columns and `mean_<column>` for configured numeric mean columns.

!!! warning "Type changes"

    Each DuckDB column has one nullable type. Schema evolution adds columns and safely widens integer columns to `DOUBLE` when a later run supplies a floating-point value. Other incompatible type changes are rejected rather than silently converting data. A configured type takes precedence over inference. Keep the type of a metadata key consistent across runs.

## Recover or replace a duplicate UID

Ordinary ingestion rejects a `uid` that already exists. If a previous ingestion left exactly one incomplete row, replace it with complete metadata using:

```bash
qa-tool ingest store/recovered-run --force
```

`--force` checks the stored row against the current `required` list and refuses to overwrite a complete run.

To deliberately replace a complete run—or collapse several legacy duplicate rows into one validated row—use the stronger option:

```bash
qa-tool ingest store/replacement-run --clobber
```

`--clobber` deletes every row with the incoming UID, then inserts the replacement inside the same transaction. The replacement must still satisfy required-field and type validation. The option changes rows only; it preserves the existing table and its column types. `--force` and `--clobber` cannot be combined.

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

- A duplicate `uid` is rejected. `--force` may replace exactly one matching row only when that stored row is incomplete under the current `required` policy; it never overwrites a complete run.
- `--clobber` is the explicit destructive alternative: it deletes every existing row with the incoming UID and inserts the new validated row, even when the old run is complete. It does not bypass required-field or type validation, and it does not recreate the table schema. `--force` and `--clobber` are mutually exclusive.
- Use one writer at a time. Do not let the dashboard or another job write the same DuckDB file concurrently.
- Configure `[database].artifact_root` for every dashboard deployment and store artifact paths that resolve inside it. Relative database paths may be relative to the process working directory or to `artifact_root`, but their canonical target must remain beneath the configured root.
- When modifying `runs` outside QA Tool, rebuild `run_summary` before relying on the Overview page.
- For remote deployment, publish complete database-and-artifact snapshots rather than replacing a live database in place. See [Deployment](deployment.md).
