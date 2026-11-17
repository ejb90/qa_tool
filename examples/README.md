# Examples

The `sample-run` directory contains the smallest useful ingestion example. From
the repository root, ingest it into the default `runs.duckdb` database:

```bash
uv run qa-tool ingest examples/sample-run
```

Inspect the result from the terminal or start the web application:

```bash
uv run qa-tool model h2 --metric density
uv run qa-tool webapp
```

After starting the web application, open the Streamlit dashboard at
<http://localhost:8501>.

Copy the directory when experimenting with additional metadata fields or
artifact files. QA Tool adds new scalar metadata fields to the DuckDB schema as
they are encountered.
