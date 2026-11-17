# Python API reference

This section is generated directly from the public Python packages using `mkdocstrings`. It reflects the installed source, including type annotations and docstrings.

The first reference pass covers the shared core library, terminal CLI, and ingestion API—areas with purpose-specific docstrings. The Streamlit presentation layer remains documented in the [web-application guide](../web-app.md) until its older generic docstrings have been rewritten.

| Package | Role |
| --- | --- |
| [`qa_tool_core`](core.md) | Database queries, selections, comparisons, settings helpers, and Plotly figure builders. |
| [`qa_tool_cli`](cli.md) | Rich Click commands, terminal output, and file-artifact export. |
| [`qa_tool_ingest`](ingest.md) | JSON/artifact ingestion and DuckDB summary refresh. |
