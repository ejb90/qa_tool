# Configuration

QA Tool uses TOML overrides for the dashboard/analysis interfaces and a separate TOML file for ingestion. Both loaders merge an override into packaged defaults, so a settings file only needs to contain changed values.

## Dashboard and CLI settings

The packaged defaults live in `qa_tool/webapp/default_settings.toml`. Supply an override in one of these ways:

=== "Web-app command"

    ```bash
    qa-tool serve --settings settings.toml
    ```

=== "Environment variable"

    ```bash
    export QA_TOOL_SETTINGS=/path/to/settings.toml
    qa-tool serve
    ```

=== "CLI command"

    ```bash
    qa-tool report models h2 --settings settings.toml
    ```

For the web app, an explicit `--settings` path takes precedence over `QA_TOOL_SETTINGS`. The CLI accepts `--settings` directly and does not read that environment variable. A CLI `--database` argument overrides the database path loaded from settings.

## Common settings

```toml
[page]
title = "Regression dashboard"
layout = "wide"

[database]
path = "results/runs.duckdb"
artifact_root = "./store"

[database.columns]
model = "device"
version = "release"

[tables.all_runs]
columns = ["uid", "device", "release", "date", "density", "artifact"]

[tabs]
compare_run = true
run_detail = false

[plots]
height = 600

[archive]
save_path = "./qa_tool_archive"
search_paths = ["./qa_tool_archive", "/shared/qa/comparisons"]

[comparison.color_bounds]
density = 0.1
```

### Database column mapping

The analysis layer uses canonical `model` and `version` names internally. `[database.columns]` maps existing database columns onto those names without rewriting the database. Do not map a source column onto a canonical name that already exists as a different column.

### Tables, tabs, and summaries

- `[tables.all_runs].columns` controls both visibility and ordering; an empty list displays all columns in database order.
- `[tabs]` enables or disables dashboard views.
- `[defaults].table_metrics` selects initial metrics; an empty list selects all numeric metrics.
- `[summaries.default]` supplies fallback summary cards.
- `[summaries.tabs.<name>]` customizes one tab's cards and aggregations.

Summary aggregations support `mean`, `min`, and `max`. Unknown metrics are ignored rather than causing the application to fail.

### Comparison colours

`[comparison.color_bounds]` sets a fixed symmetric colour bound in percentage points for a metric. Metrics without a configured value use automatic scaling.

### Comparison archive

`[archive].save_path` is the single destination for newly created snapshots. It defaults to `qa_tool_archive` relative to the process working directory. CLI comparison commands use the same setting and can override it with `--archive-dir`.

`[archive].search_paths` is an ordered list of locations displayed by **Saved Comparisons** and searched by CLI archive commands. This allows, for example, new comparisons to be saved locally while both a local directory and a read-only shared filesystem are browsed. If the same snapshot exists in more than one location, the copy in the first search path is used.

`save_path` must be writable wherever snapshots are created; entries in `search_paths` only need to be readable. Put important archives on persistent, backed-up storage and mount the required paths into containers separately from the artifact store. See [Comparison archives](comparison-archives.md).

## Ingestion settings

Ingestion starts from `qa_tool/ingest/default_settings.toml` and accepts an override with `--settings`:

```bash
qa-tool ingest store/my-run --settings ingest.toml
```

The ingestion file controls the destination tables, selected JSON keys, renames, artifact-column name, and stored summary. See [Data ingestion](ingestion.md#configure-ingestion) for a complete example.

!!! warning "Two settings formats"

    Dashboard/CLI settings and ingestion settings have different schemas. Keep them in separate files unless the combined file contains every section required by both loaders.
