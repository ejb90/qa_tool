# Plots and exports

QA Tool uses Plotly for both the web application and command-line figures. The web application displays figures interactively; CLI report commands can save each figure together with the data and aggregate table used to create it. Comparison commands instead create a complete [comparison archive](comparison-archives.md).

## Available plots

| Command or view | Plot |
| --- | --- |
| Model report | Metric mean by version for each selected model, with standard-deviation error bars. |
| Version report | Metric mean by version, split into model series, plus an empirical CDF. |
| Version comparison | Model percentage differences with uncertainty, plus a comparison CDF. |
| Collection comparison | The same difference and CDF views for two metadata-selected collections. |
| Model comparison | Aggregate percentage difference between two model groups. |
| Pie chart | Run count or summed metric grouped by model or version. |
| Run detail | Parquet time-series plots in the web application. |

Use `--metric NAME` to select one numeric database column. Without it, most CLI commands produce a report for every numeric metric. `report breakdown` additionally creates a run-count plot when no metric is supplied.

## Output formats

The `report models`, `report versions`, and `report breakdown` commands accept repeatable `--format` options:

| Format | Output | Base install |
| --- | --- | --- |
| `html` | Interactive Plotly page using the Plotly CDN. | Yes |
| `csv` | Raw plot data and displayed aggregate table. | Yes |
| `parquet` | Raw plot data and displayed aggregate table. | Yes |
| `png` | Static Plotly image rendered by Kaleido. | Requires `qa-tool[png]` |

The default is:

```text
--format html --format csv --format parquet
```

Examples:

```bash
# Interactive plot and portable tables
qa-tool report models h2 --metric density --format html --format csv

# Data only
qa-tool report versions v1.0.0 v2.0.0 --format csv --format parquet

# Static image plus the displayed table
qa-tool report breakdown --by model --metric density --format png --format csv
```

## File layout

Files are written to `qa_tool_output/` unless `--output-dir` is supplied. For a plot named `model_h2_density`, selected formats produce:

```text
qa_tool_output/
├── model_h2_density.html
├── model_h2_density.png
├── model_h2_density.csv
├── model_h2_density.parquet
├── model_h2_density_table.csv
└── model_h2_density_table.parquet
```

The un-suffixed CSV or Parquet file contains the figure's source rows. The `_table` file contains the aggregate values displayed in the terminal.

Reports always print either the generated filename or a concise file-count and destination summary. Use the top-level `--verbose` option to list every generated path:

```bash
qa-tool --verbose report models h2 --metric density
```

## Enable PNG output

Install the optional dependencies before requesting PNG:

```bash
python -m pip install "qa-tool[png]"
# or, in a checkout
uv sync --extra png
```

Kaleido requires a compatible Chrome or Chromium browser. If the extra is missing, QA Tool stops before loading the database and prints the installation commands. If Kaleido cannot use a browser, the command reports that rendering failure rather than silently omitting the requested file.

## Web plots

The web application does not require Kaleido because Streamlit renders Plotly figures interactively. Plot height is configured through `[plots].height`; comparison-table colour limits are controlled through `[comparison.color_bounds]`. See [Configuration](configuration.md).

Saved comparison reports embed Plotly directly in `report.html`, making those reports self-contained and usable offline. They always include CSV and Parquet result data plus the full input rows; `--format` does not apply to comparison snapshots.
