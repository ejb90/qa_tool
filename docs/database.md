# Data model

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

## Existing databases

The dashboard and CLI can read an existing DuckDB `runs` table when it provides `uid`, `date`, and the configured model/version columns. Use `[database.columns]` to map differently named grouping columns without rewriting the table. See [Configuration](configuration.md).

## Summary refresh timing

`run_summary` is refreshed when ingestion completes. This makes the splash page cheap: it reads a single precomputed row rather than aggregating every run when the page is opened. Re-run ingestion whenever the underlying `runs` table is changed outside QA Tool.
