| DB rows | Query | Result rows | SQLite ms | DuckDB ms | SQLite / DuckDB | Description |
|---:|---|---:|---:|---:|---:|---|
| 10 | `row_count` | 1 | 0.005 | 0.114 | 0.05x | Count all runs. |
| 10 | `filter_options` | 22 | 0.013 | 0.801 | 0.02x | Load model/version/date sidebar options. |
| 10 | `version_means` | 7 | 0.013 | 0.646 | 0.02x | Versions tab: mean metrics by version. |
| 10 | `model_means` | 7 | 0.012 | 0.596 | 0.02x | Models tab: mean metrics by model. |
| 10 | `filtered_summary` | 1 | 0.010 | 0.671 | 0.01x | Summary cards after sidebar filters. |
| 10 | `paged_all_runs` | 1 | 0.008 | 0.376 | 0.02x | All Runs tab: first page after filters. |
| 10 | `run_detail` | 1 | 0.015 | 1.091 | 0.01x | Run Detail tab: lookup one run by uid. |
| 10 | `pie_by_model` | 10 | 0.013 | 0.868 | 0.01x | Pie chart: runtime by model. |
| 10 | `compare_versions` | 1 | 0.014 | 0.939 | 0.01x | Compare Versions tab: per-model deltas. |
| 100 | `row_count` | 1 | 0.006 | 0.191 | 0.03x | Count all runs. |
| 100 | `filter_options` | 129 | 0.167 | 1.776 | 0.09x | Load model/version/date sidebar options. |
| 100 | `version_means` | 70 | 0.095 | 1.343 | 0.07x | Versions tab: mean metrics by version. |
| 100 | `model_means` | 27 | 0.133 | 1.664 | 0.08x | Models tab: mean metrics by model. |
| 100 | `filtered_summary` | 1 | 0.021 | 0.848 | 0.02x | Summary cards after sidebar filters. |
| 100 | `paged_all_runs` | 4 | 0.020 | 0.516 | 0.04x | All Runs tab: first page after filters. |
| 100 | `run_detail` | 1 | 0.015 | 0.598 | 0.02x | Run Detail tab: lookup one run by uid. |
| 100 | `pie_by_model` | 27 | 0.034 | 0.529 | 0.06x | Pie chart: runtime by model. |
| 100 | `compare_versions` | 1 | 0.015 | 0.916 | 0.02x | Compare Versions tab: per-model deltas. |
| 1000 | `row_count` | 1 | 0.005 | 0.119 | 0.04x | Count all runs. |
| 1000 | `filter_options` | 1029 | 0.408 | 1.149 | 0.36x | Load model/version/date sidebar options. |
| 1000 | `version_means` | 700 | 0.939 | 0.986 | 0.95x | Versions tab: mean metrics by version. |
| 1000 | `model_means` | 27 | 0.251 | 0.661 | 0.38x | Models tab: mean metrics by model. |
| 1000 | `filtered_summary` | 1 | 0.018 | 0.835 | 0.02x | Summary cards after sidebar filters. |
| 1000 | `paged_all_runs` | 5 | 0.017 | 0.630 | 0.03x | All Runs tab: first page after filters. |
| 1000 | `run_detail` | 1 | 0.015 | 0.675 | 0.02x | Run Detail tab: lookup one run by uid. |
| 1000 | `pie_by_model` | 27 | 0.203 | 0.600 | 0.34x | Pie chart: runtime by model. |
| 1000 | `compare_versions` | 1 | 0.018 | 0.897 | 0.02x | Compare Versions tab: per-model deltas. |
| 10000 | `row_count` | 1 | 0.006 | 0.127 | 0.05x | Count all runs. |
| 10000 | `filter_options` | 10029 | 4.259 | 3.459 | 1.23x | Load model/version/date sidebar options. |
| 10000 | `version_means` | 7000 | 11.260 | 4.309 | 2.61x | Versions tab: mean metrics by version. |
| 10000 | `model_means` | 27 | 10.838 | 0.830 | 13.07x | Models tab: mean metrics by model. |
| 10000 | `filtered_summary` | 1 | 0.014 | 0.913 | 0.01x | Summary cards after sidebar filters. |
| 10000 | `paged_all_runs` | 5 | 0.016 | 0.769 | 0.02x | All Runs tab: first page after filters. |
| 10000 | `run_detail` | 1 | 0.014 | 0.996 | 0.01x | Run Detail tab: lookup one run by uid. |
| 10000 | `pie_by_model` | 27 | 7.327 | 0.540 | 13.56x | Pie chart: runtime by model. |
| 10000 | `compare_versions` | 1 | 0.014 | 1.204 | 0.01x | Compare Versions tab: per-model deltas. |
| 100000 | `row_count` | 1 | 0.431 | 0.125 | 3.45x | Count all runs. |
| 100000 | `filter_options` | 10029 | 11.099 | 5.868 | 1.89x | Load model/version/date sidebar options. |
| 100000 | `version_means` | 7000 | 124.771 | 6.669 | 18.71x | Versions tab: mean metrics by version. |
| 100000 | `model_means` | 27 | 124.466 | 1.668 | 74.62x | Models tab: mean metrics by model. |
| 100000 | `filtered_summary` | 1 | 0.013 | 1.530 | 0.01x | Summary cards after sidebar filters. |
| 100000 | `paged_all_runs` | 5 | 0.016 | 1.991 | 0.01x | All Runs tab: first page after filters. |
| 100000 | `run_detail` | 1 | 0.015 | 2.056 | 0.01x | Run Detail tab: lookup one run by uid. |
| 100000 | `pie_by_model` | 27 | 125.543 | 0.789 | 159.21x | Pie chart: runtime by model. |
| 100000 | `compare_versions` | 2 | 0.034 | 3.070 | 0.01x | Compare Versions tab: per-model deltas. |
| 1000000 | `row_count` | 1 | 5.039 | 0.126 | 40.13x | Count all runs. |
| 1000000 | `filter_options` | 10029 | 70.977 | 9.921 | 7.15x | Load model/version/date sidebar options. |
| 1000000 | `version_means` | 7000 | 1712.778 | 16.921 | 101.22x | Versions tab: mean metrics by version. |
| 1000000 | `model_means` | 27 | 2083.767 | 5.897 | 353.37x | Models tab: mean metrics by model. |
| 1000000 | `filtered_summary` | 1 | 0.024 | 3.226 | 0.01x | Summary cards after sidebar filters. |
| 1000000 | `paged_all_runs` | 20 | 0.040 | 6.037 | 0.01x | All Runs tab: first page after filters. |
| 1000000 | `run_detail` | 1 | 0.015 | 4.890 | 0.00x | Run Detail tab: lookup one run by uid. |
| 1000000 | `pie_by_model` | 27 | 1964.465 | 1.726 | 1138.24x | Pie chart: runtime by model. |
| 1000000 | `compare_versions` | 27 | 0.161 | 6.394 | 0.03x | Compare Versions tab: per-model deltas. |
