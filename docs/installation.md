# Installation

QA Tool requires Python 3.11 or newer. The base installation includes the dashboard, command-line reporting, ingestion, interactive Plotly output, and CSV/Parquet export.

## Install from PyPI

=== "pip"

    Install QA Tool into the active Python environment:

    ```bash
    python -m pip install qa-tool
    ```

=== "uv tool"

    Install the three commands into an isolated, managed environment:

    ```bash
    uv tool install qa-tool
    ```

The installation provides one command tree:

| Command | Purpose |
| --- | --- |
| `qa-tool ingest` | Add one run's metadata to DuckDB. |
| `qa-tool serve` | Start the Streamlit dashboard. |
| `qa-tool report models`, `versions`, `breakdown` | Generate terminal reports, plots, and tabular exports. |
| `qa-tool compare` | Compare runs, versions, models, or collections and save a snapshot. |

Verify the installation with `qa-tool --help`.

The installed executable is `qa-tool`. Ingestion, reporting, comparison, and the web application are exposed as subcommands such as `qa-tool ingest`, `qa-tool report`, and `qa-tool serve`.

## Optional extras

Optional features are kept out of the base environment.

| Extra | Adds | Required when |
| --- | --- | --- |
| `png` | Kaleido | Writing static Plotly PNG files. |
| `docs` | MkDocs, Material for MkDocs, and mkdocstrings | Building or previewing this documentation. |

Install an extra with the package:

=== "pip"

    ```bash
    python -m pip install "qa-tool[png]"
    python -m pip install "qa-tool[docs]"
    ```

=== "uv tool"

    ```bash
    uv tool install "qa-tool[png]"
    ```

Combine extras when both are needed:

```bash
python -m pip install "qa-tool[png,docs]"
```

!!! note "PNG browser requirement"

    Kaleido also needs access to a compatible Chrome or Chromium browser. QA Tool checks for the optional Python dependency before running and reports an actionable error if PNG rendering is unavailable.

## Install from a checkout

Clone the repository, then let uv create the project environment:

```bash
git clone https://github.com/ejb90/qa_tool.git
cd qa_tool
uv sync --no-dev
```

Add only the optional features you need:

```bash
uv sync --no-dev --extra png
uv sync --no-dev --extra docs
```

For contribution work, install test, lint, release, and documentation tools:

```bash
uv sync --group dev --extra docs
```

Run project commands from a checkout with `uv run`, for example:

```bash
uv run qa-tool --help
uv run qa-tool serve
```

## Upgrade or remove

With pip:

```bash
python -m pip install --upgrade qa-tool
python -m pip uninstall qa-tool
```

With uv tool:

```bash
uv tool upgrade qa-tool
uv tool uninstall qa-tool
```
