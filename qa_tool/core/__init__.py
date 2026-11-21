"""Shared database queries, calculations, and plot builders for QA Tool."""

from qa_tool.core.archive import (
    ComparisonArchive,
    create_comparison_archive,
    find_comparison_archive,
    find_comparison_archive_in_roots,
    list_comparison_archives,
    list_comparison_archives_from_roots,
    verify_comparison_archive,
)
from qa_tool.core.comparisons import (
    build_collection_comparison,
    build_collection_metric_deltas,
    build_model_comparison,
    build_run_scalar_comparison,
    build_version_comparison,
)
from qa_tool.core.queries import (
    aggregate_runs,
    load_runs,
    metric_columns,
    model_mean_cdf_data,
    select_collection,
)

__all__ = [
    "ComparisonArchive",
    "aggregate_runs",
    "build_collection_comparison",
    "build_collection_metric_deltas",
    "build_model_comparison",
    "build_run_scalar_comparison",
    "build_version_comparison",
    "create_comparison_archive",
    "find_comparison_archive",
    "find_comparison_archive_in_roots",
    "list_comparison_archives",
    "list_comparison_archives_from_roots",
    "load_runs",
    "metric_columns",
    "model_mean_cdf_data",
    "select_collection",
    "verify_comparison_archive",
]
