"""QA dashboard module for run tables."""

from __future__ import annotations

try:
    from qa_tool.views.all_runs import show_all_runs
    from qa_tool.views.pie_charts import show_pie_charts
except ModuleNotFoundError:
    from views.all_runs import show_all_runs
    from views.pie_charts import show_pie_charts

__all__ = ["show_all_runs", "show_pie_charts"]
