# Development

Install the development tools and documentation toolchain:

```bash
uv sync --group dev --extra docs
```

## Package responsibilities

| Package | Responsibility |
| --- | --- |
| `qa_tool.core` | DuckDB loading, schema normalization, run aggregation, collection selection, comparisons, settings helpers, and Plotly figure builders. |
| `qa_tool.webapp` | Streamlit-specific widgets, styling, navigation, artifact browsing, and download controls. |
| `qa_tool.cli` | Rich Click command tree, Rich terminal tables, and file export orchestration. |
| `qa_tool.ingest` | JSON/artifact ingestion, evolving DuckDB schema, and summary refresh. |

Keep data calculations in `qa_tool.core` whenever they are useful to both the web and command-line interfaces.

## Repository layout

```text
qa_tool/
├── cli/       # Rich Click commands and terminal rendering
├── core/      # Shared queries, comparisons, plots, and settings
├── ingest/    # JSON and artifact ingestion
└── webapp/    # Streamlit application and views
tests/         # Unit and application tests
docs/          # MkDocs documentation
examples/      # Small inputs that can be run locally
```

## Checks

Format and lint all packages and tests:

```bash
uv run ruff format qa_tool tests
uv run ruff check qa_tool tests
```

Run the focused test suite:

```bash
uv run pytest tests/cli tests/app tests/core tests/ingestion -o addopts=''
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
