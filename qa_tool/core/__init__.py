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
from qa_tool.core.doctor import DoctorFinding, DoctorReport, inspect_database
from qa_tool.core.gates import (
    GateEvaluation,
    GatePolicy,
    GateResult,
    MetricRule,
    evaluate_gate,
    gate_evaluation_junit,
    load_gate_policy,
    parse_gate_policy,
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
    "DoctorFinding",
    "DoctorReport",
    "GateEvaluation",
    "GatePolicy",
    "GateResult",
    "MetricRule",
    "aggregate_runs",
    "build_collection_comparison",
    "build_collection_metric_deltas",
    "build_model_comparison",
    "build_run_scalar_comparison",
    "build_version_comparison",
    "create_comparison_archive",
    "evaluate_gate",
    "find_comparison_archive",
    "find_comparison_archive_in_roots",
    "gate_evaluation_junit",
    "inspect_database",
    "list_comparison_archives",
    "list_comparison_archives_from_roots",
    "load_gate_policy",
    "load_runs",
    "metric_columns",
    "model_mean_cdf_data",
    "parse_gate_policy",
    "select_collection",
    "verify_comparison_archive",
]
