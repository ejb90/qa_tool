| DB rows | Query | Result rows | SQLite ms | DuckDB ms | SQLite / DuckDB | Description |
|---:|---|---:|---:|---:|---:|---|
| 10 | `row_count` | 1 | 0.016 | 0.539 | 0.03x | Count all runs. |
| 10 | `filter_options` | 22 | 0.110 | 3.777 | 0.03x | Load model/version/date sidebar options. |
| 10 | `version_means` | 7 | 0.062 | 2.127 | 0.03x | Versions tab: mean metrics by version. |
| 10 | `model_means` | 7 | 0.072 | 1.890 | 0.04x | Models tab: mean metrics by model. |
| 10 | `filtered_summary` | 1 | 0.033 | 3.144 | 0.01x | Summary cards after sidebar filters. |
| 10 | `paged_all_runs` | 1 | 0.019 | 0.638 | 0.03x | All Runs tab: first page after filters. |
| 10 | `run_detail` | 1 | 0.019 | 0.960 | 0.02x | Run Detail tab: lookup one run by uid. |
| 10 | `pie_by_model` | 10 | 0.017 | 1.228 | 0.01x | Pie chart: runtime by model. |
| 10 | `compare_versions` | 1 | 0.029 | 1.844 | 0.02x | Compare Versions tab: per-model deltas. |
| 1000 | `row_count` | 1 | 0.015 | 0.193 | 0.08x | Count all runs. |
| 1000 | `filter_options` | 1029 | 0.568 | 1.837 | 0.31x | Load model/version/date sidebar options. |
| 1000 | `version_means` | 700 | 0.929 | 2.042 | 0.45x | Versions tab: mean metrics by version. |
| 1000 | `model_means` | 27 | 0.537 | 1.819 | 0.30x | Models tab: mean metrics by model. |
| 1000 | `filtered_summary` | 1 | 0.019 | 2.161 | 0.01x | Summary cards after sidebar filters. |
| 1000 | `paged_all_runs` | 5 | 0.023 | 1.331 | 0.02x | All Runs tab: first page after filters. |
| 1000 | `run_detail` | 1 | 0.078 | 1.941 | 0.04x | Run Detail tab: lookup one run by uid. |
| 1000 | `pie_by_model` | 27 | 0.388 | 1.099 | 0.35x | Pie chart: runtime by model. |
| 1000 | `compare_versions` | 1 | 0.023 | 3.387 | 0.01x | Compare Versions tab: per-model deltas. |
