# Development

## Package responsibilities

| Package | Responsibility |
| --- | --- |
| `qa_tool_core` | DuckDB loading, schema normalization, run aggregation, collection selection, comparisons, settings helpers, and Plotly figure builders. |
| `qa_tool_webapp` | Streamlit-specific widgets, styling, navigation, artifact browsing, and download controls. |
| `qa_tool_cli` | Rich argument parsing, terminal tables, and file export orchestration. |
| `qa_tool_ingest` | JSON/artifact ingestion, evolving DuckDB schema, and summary refresh. |

Keep data calculations in `qa_tool_core` whenever they are useful to both the web and command-line interfaces.

## Checks

Format and lint all packages and tests:

```bash
uv run ruff format qa_tool_core qa_tool_cli qa_tool_webapp qa_tool_ingest tests
uv run ruff check qa_tool_core qa_tool_cli qa_tool_webapp qa_tool_ingest tests
```

Run the focused test suite:

```bash
uv run pytest tests/cli tests/app tests/ingestion -o addopts=''
```

Run the complete release check locally:

```bash
uv run ruff check --diff
uv run ruff format --check
uv run pytest
uv build
uv run twine check dist/*
uv run mkdocs build --strict
```

## Build documentation

Preview the site locally:

```bash
uv run mkdocs serve
```

Build a static site:

```bash
uv run mkdocs build --strict
```

The generated site is written to `site/` and is intentionally not committed.

## Releases

Set the release version in `pyproject.toml`, merge it to `main`, and let the `Tag` workflow create the matching `vX.Y.Z` tag. Alternatively, push a verified tag manually:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The tag-triggered `Publish` workflow verifies that the tag and project version agree, creates a GitHub release, publishes to PyPI through the configured `pypi` trusted-publishing environment, and optionally triggers Read the Docs. Configure the `READTHEDOCS_API_KEY` repository secret to enable the final step.
