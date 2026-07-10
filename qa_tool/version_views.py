"""QA dashboard module for version views."""

from __future__ import annotations

try:
    from qa_tool.views.common import (
        aggregate_runs,
        empirical_cdf,
        model_mean_cdf_data,
        show_comparison_cdf_plot,
        version_sort_key,
    )
    from qa_tool.views.compare_versions import show_version_comparison
    from qa_tool.views.models import (
        show_model_tables,
        show_model_version_plot,
        show_models_tab,
    )
    from qa_tool.views.versions import (
        show_version_cdf_plot,
        show_version_plots,
        show_version_tables,
        show_versions_tab,
    )
except ModuleNotFoundError:
    from views.common import (
        aggregate_runs,
        empirical_cdf,
        model_mean_cdf_data,
        show_comparison_cdf_plot,
        version_sort_key,
    )
    from views.compare_versions import show_version_comparison
    from views.models import (
        show_model_tables,
        show_model_version_plot,
        show_models_tab,
    )
    from views.versions import (
        show_version_cdf_plot,
        show_version_plots,
        show_version_tables,
        show_versions_tab,
    )

__all__ = [
    "aggregate_runs",
    "empirical_cdf",
    "model_mean_cdf_data",
    "show_comparison_cdf_plot",
    "show_model_tables",
    "show_model_version_plot",
    "show_models_tab",
    "show_version_cdf_plot",
    "show_version_comparison",
    "show_version_plots",
    "show_version_tables",
    "show_versions_tab",
    "version_sort_key",
]
