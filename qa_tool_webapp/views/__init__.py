"""QA dashboard module for views."""

from __future__ import annotations

try:
    from qa_tool_webapp.views.all_runs import show_all_runs
    from qa_tool_webapp.views.compare_collection import show_compare_collection
    from qa_tool_webapp.views.compare_run import show_compare_run
    from qa_tool_webapp.views.compare_versions import show_version_comparison
    from qa_tool_webapp.views.models import show_models_tab
    from qa_tool_webapp.views.pie_charts import show_pie_charts
    from qa_tool_webapp.views.run_detail import show_run_detail
    from qa_tool_webapp.views.versions import show_versions_tab
except ModuleNotFoundError:
    from views.all_runs import show_all_runs
    from views.compare_collection import show_compare_collection
    from views.compare_run import show_compare_run
    from views.compare_versions import show_version_comparison
    from views.models import show_models_tab
    from views.pie_charts import show_pie_charts
    from views.run_detail import show_run_detail
    from views.versions import show_versions_tab

__all__ = [
    "show_all_runs",
    "show_compare_collection",
    "show_compare_run",
    "show_models_tab",
    "show_pie_charts",
    "show_run_detail",
    "show_version_comparison",
    "show_versions_tab",
]
