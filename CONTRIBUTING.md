# Contributing

Contributions are welcome. QA Tool uses uv for dependency management, Ruff for linting and formatting, Pytest for tests, and MkDocs for documentation.

## Setup

```sh
uv sync --group dev --extra docs
```

## Checks

Run the same checks enforced by continuous integration:

```sh
uv run ruff check --diff
uv run ruff format --check
uv run pytest
uv build
uv run twine check dist/*
uv run mkdocs build --strict
```

Use `uv run ruff format .` before opening a pull request to apply formatting.

## Documentation

Preview the documentation locally:

```sh
uv run mkdocs serve
```

Then open <http://127.0.0.1:8000>.

## Releases

Update the version in `pyproject.toml` and merge it to `main`. The `Tag` workflow creates the corresponding `vX.Y.Z` tag; the tag-triggered `Publish` workflow builds, checks, releases, and publishes the package. See the [release guide](docs/releases.md) for the required PyPI and Read the Docs configuration.
