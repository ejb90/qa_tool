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
cache_ttl_seconds = 60
max_query_rows = 50000

[artifacts]
max_archive_members = 1000
max_expanded_bytes = 536870912
max_file_bytes = 134217728
max_recursive_files = 1000
max_render_rows = 10000
max_plot_points = 10000

[database.columns]
model = "device"
version = "release"

[tables.all_runs]
columns = ["uid", "model", "version", "date", "density", "artifact"]

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

### Database cache refresh

`[database].cache_ttl_seconds` bounds how long cached runs and summary data can remain stale after a user interaction. The default is 60 seconds. Set it to `0` to disable time-based expiry and rely on database revision detection plus the manual refresh control.

The dashboard fingerprints the resolved database file using its path, filesystem identity, size, and modification time. Promoting an immutable snapshot through a symlink therefore changes the cache key immediately. The TTL is a fallback for environments where a change is not otherwise observable; it does not poll or modify DuckDB.

### Dashboard query bounds

`[database].max_query_rows` limits the detailed rows materialized by one analytical dashboard view. The default is 50,000. Shared model, version, and date filters are applied in DuckDB before this window is returned. When a selection is larger, the dashboard shows a warning and uses the most recent rows; narrow the filters to analyse the complete selection.

**All Runs** is not limited to the first window. It uses a database-side count plus `LIMIT`/`OFFSET` pagination, and downloads contain only the current page. Summary cards are calculated over the complete filtered selection inside DuckDB, so their values remain exact without loading every run.

### Artifact trust boundary and limits

Local artifact inspection is disabled unless `[database].artifact_root` is configured. The dashboard treats the database `artifact`, `uid`, and `name` fields as untrusted input: relative artifact paths may be relative to the process working directory or to `artifact_root`, but every canonical target must be inside that root. Absolute paths are accepted only inside the same root, while paths or symbolic links that escape it are ignored or rejected. `s3://` values are displayed as remote locations and are not opened by the dashboard.

The `[artifacts]` limits bound work performed by the hosted process:

- `max_archive_members` limits all entries in a tar archive.
- `max_expanded_bytes` limits the combined declared size of extracted regular files.
- `max_file_bytes` limits each inspected or extracted file.
- `max_recursive_files` limits files discovered in a directory or archive.
- `max_render_rows` limits CSV, JSON Lines, and Parquet previews.
- `max_plot_points` limits points supplied to one plot.

Tar inspection rejects traversal paths, symbolic and hard links, devices, and other special members before extraction. Directory inspection does not follow symbolic links. These controls protect the server from database-directed file access and accidental or hostile resource exhaustion; they do not make untrusted pickle deserialization safe. Pickle preview remains disabled unless the server is started locally with `--allow-unsafe-pickle`.

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

The ingestion file controls the destination tables, selected JSON keys, renames, authoritative column types, artifact-column name, and stored summary. See [Data ingestion](ingestion.md#configure-ingestion) for a complete example.

!!! warning "Two settings formats"

    Dashboard/CLI settings and ingestion settings have different schemas. Keep them in separate files unless the combined file contains every section required by both loaders.
