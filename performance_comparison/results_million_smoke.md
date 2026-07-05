| Query | Rows | SQLite ms | DuckDB ms | SQLite / DuckDB | Description |
|---|---:|---:|---:|---:|---|
| `row_count` | 1 | 5.988 | 7.520 | 0.80x | Count all runs. |
| `filter_options` | 10029 | 133.201 | 20.162 | 6.61x | Load model/version/date sidebar options. |
| `version_means` | 7000 | 4330.404 | 30.082 | 143.95x | Versions tab: mean metrics by version. |
| `model_means` | 27 | 2063.979 | 5.102 | 404.52x | Models tab: mean metrics by model. |
| `filtered_summary` | 1 | 0.175 | 8.778 | 0.02x | Summary cards after sidebar filters. |
| `paged_all_runs` | 20 | 0.141 | 12.681 | 0.01x | All Runs tab: first page after filters. |
| `run_detail` | 1 | 0.116 | 20.996 | 0.01x | Run Detail tab: lookup one run by uid. |
| `pie_by_model` | 27 | 1992.908 | 2.242 | 888.86x | Pie chart: runtime by model. |
| `compare_versions` | 27 | 0.624 | 11.874 | 0.05x | Compare Versions tab: per-model deltas. |
