| DB rows | Query | Result rows | SQLite ms | DuckDB ms | SQLite / DuckDB | Description |
|---:|---|---:|---:|---:|---:|---|
| 10 | `row_count` | 1 | 0.005 | 0.134 | 0.04x | Count all runs. |
| 10 | `filter_options` | 21 | 0.018 | 0.805 | 0.02x | Load model/version/date sidebar options. |
| 10 | `version_means` | 5 | 0.011 | 0.634 | 0.02x | Versions tab: mean metrics by version. |
| 10 | `model_means` | 5 | 0.010 | 0.551 | 0.02x | Models tab: mean metrics by model. |
| 10 | `filtered_summary` | 1 | 0.027 | 0.572 | 0.05x | Summary cards after sidebar filters. |
| 10 | `paged_all_runs` | 2 | 0.015 | 0.462 | 0.03x | All Runs tab: first page after filters. |
| 10 | `run_detail` | 1 | 0.008 | 0.210 | 0.04x | Run Detail tab: lookup one run by uid. |
| 10 | `pie_by_model` | 9 | 0.011 | 0.432 | 0.03x | Pie chart: runtime by model. |
| 10 | `compare_versions` | 1 | 0.023 | 0.909 | 0.03x | Compare Versions tab: per-model deltas. |
| 100 | `row_count` | 1 | 0.005 | 0.119 | 0.04x | Count all runs. |
| 100 | `filter_options` | 124 | 0.066 | 0.751 | 0.09x | Load model/version/date sidebar options. |
| 100 | `version_means` | 61 | 0.070 | 0.573 | 0.12x | Versions tab: mean metrics by version. |
| 100 | `model_means` | 24 | 0.043 | 0.615 | 0.07x | Models tab: mean metrics by model. |
| 100 | `filtered_summary` | 1 | 0.020 | 0.809 | 0.02x | Summary cards after sidebar filters. |
| 100 | `paged_all_runs` | 5 | 0.022 | 0.742 | 0.03x | All Runs tab: first page after filters. |
| 100 | `run_detail` | 1 | 0.014 | 0.211 | 0.07x | Run Detail tab: lookup one run by uid. |
| 100 | `pie_by_model` | 27 | 0.034 | 0.497 | 0.07x | Pie chart: runtime by model. |
| 100 | `compare_versions` | 1 | 0.016 | 0.889 | 0.02x | Compare Versions tab: per-model deltas. |
| 1000 | `row_count` | 1 | 0.005 | 0.087 | 0.06x | Count all runs. |
| 1000 | `filter_options` | 737 | 0.316 | 1.063 | 0.30x | Load model/version/date sidebar options. |
| 1000 | `version_means` | 549 | 0.654 | 0.772 | 0.85x | Versions tab: mean metrics by version. |
| 1000 | `model_means` | 27 | 0.247 | 0.640 | 0.39x | Models tab: mean metrics by model. |
| 1000 | `filtered_summary` | 1 | 0.018 | 0.846 | 0.02x | Summary cards after sidebar filters. |
| 1000 | `paged_all_runs` | 7 | 0.023 | 0.715 | 0.03x | All Runs tab: first page after filters. |
| 1000 | `run_detail` | 1 | 0.007 | 0.200 | 0.04x | Run Detail tab: lookup one run by uid. |
| 1000 | `pie_by_model` | 27 | 0.188 | 0.495 | 0.38x | Pie chart: runtime by model. |
| 1000 | `compare_versions` | 3 | 0.025 | 0.967 | 0.03x | Compare Versions tab: per-model deltas. |
| 10000 | `row_count` | 1 | 0.007 | 0.121 | 0.06x | Count all runs. |
| 10000 | `filter_options` | 1664 | 1.229 | 1.754 | 0.70x | Load model/version/date sidebar options. |
| 10000 | `version_means` | 1583 | 9.506 | 5.444 | 1.75x | Versions tab: mean metrics by version. |
| 10000 | `model_means` | 27 | 6.109 | 0.981 | 6.23x | Models tab: mean metrics by model. |
| 10000 | `filtered_summary` | 1 | 0.018 | 0.987 | 0.02x | Summary cards after sidebar filters. |
| 10000 | `paged_all_runs` | 17 | 0.035 | 1.994 | 0.02x | All Runs tab: first page after filters. |
| 10000 | `run_detail` | 1 | 0.007 | 0.279 | 0.03x | Run Detail tab: lookup one run by uid. |
| 10000 | `pie_by_model` | 27 | 5.701 | 0.684 | 8.34x | Pie chart: runtime by model. |
| 10000 | `compare_versions` | 12 | 0.056 | 1.566 | 0.04x | Compare Versions tab: per-model deltas. |
| 100000 | `row_count` | 1 | 0.556 | 0.132 | 4.21x | Count all runs. |
| 100000 | `filter_options` | 1697 | 7.371 | 1.199 | 6.15x | Load model/version/date sidebar options. |
| 100000 | `version_means` | 1668 | 108.678 | 2.810 | 38.68x | Versions tab: mean metrics by version. |
| 100000 | `model_means` | 27 | 108.275 | 2.106 | 51.42x | Models tab: mean metrics by model. |
| 100000 | `filtered_summary` | 1 | 0.036 | 1.566 | 0.02x | Summary cards after sidebar filters. |
| 100000 | `paged_all_runs` | 59 | 0.096 | 3.537 | 0.03x | All Runs tab: first page after filters. |
| 100000 | `run_detail` | 1 | 0.007 | 0.226 | 0.03x | Run Detail tab: lookup one run by uid. |
| 100000 | `pie_by_model` | 27 | 105.090 | 0.950 | 110.59x | Pie chart: runtime by model. |
| 100000 | `compare_versions` | 27 | 0.209 | 1.875 | 0.11x | Compare Versions tab: per-model deltas. |
