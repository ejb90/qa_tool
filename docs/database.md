# Data model and settings

## DuckDB tables

QA Tool requires a DuckDB file (`.duckdb`) with a `runs` table.

| Table | Purpose |
| --- | --- |
| `runs` | One metadata row per run; schema expands as new JSON keys are ingested. |
| `run_summary` | One precomputed row used for the splash-page quantities. |

The ingestion command creates or refreshes these tables. It is safe to append runs with additional keys: the ingestion layer adds the corresponding DuckDB columns before inserting the row.

## Required and conventional columns

| Column | Requirement | Meaning |
| --- | --- | --- |
| `uid` | Required | Stable, unique run identifier. |
| `date` | Required | Run timestamp; used for sorting and date selections. |
| `model` | Required by default | Model/device/material grouping. Can be mapped from another source field. |
| `version` | Required by default | Software/version grouping. Can be mapped from another source field. |
| `name` | Optional | Display name. If absent, the app uses `uid`. |
| `artifact` | Recommended | Artifact directory or location associated with this run. |
| `modified` | Optional | If absent, the web app treats all runs as unmodified. |

Any numeric column other than the identifier/date columns is eligible for metrics, tables, comparisons, and plots.

## Web-app settings

The web application starts with `qa_tool_webapp/default_settings.toml`. Pass an override with `--settings` or set `QA_TOOL_SETTINGS`.

```toml
[database]
path = "runs.duckdb"
artifact_root = "./store"

[database.columns]
# Map a differently named source schema to QA Tool's canonical names.
model = "device"
version = "release"

[tables.all_runs]
# Empty keeps database order. Otherwise this is both the visible set and order.
columns = ["uid", "model", "version", "date", "density", "artifact"]

[tabs]
run_detail = false
```

The CLI reads the same settings, including model/version mappings and plot height.

## Summary refresh timing

`run_summary` is refreshed when ingestion completes. This makes the splash page cheap: it reads a single precomputed row rather than aggregating every run when the page is opened. Re-run ingestion whenever the underlying `runs` table is changed outside QA Tool.
