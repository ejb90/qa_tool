from __future__ import annotations

try:
    from qa_tool.views.compare_collection import (
        collection_parameter_columns,
        compact_collection_label,
        select_bool_collection,
        select_collection_runs,
        select_datetime_collection,
        select_string_collection,
        show_collection_comparison_result,
        show_compare_collection,
        string_collection_mask,
        unique_string_values,
    )
except ModuleNotFoundError:
    from views.compare_collection import (
        collection_parameter_columns,
        compact_collection_label,
        select_bool_collection,
        select_collection_runs,
        select_datetime_collection,
        select_string_collection,
        show_collection_comparison_result,
        show_compare_collection,
        string_collection_mask,
        unique_string_values,
    )

__all__ = [
    "collection_parameter_columns",
    "compact_collection_label",
    "select_bool_collection",
    "select_collection_runs",
    "select_datetime_collection",
    "select_string_collection",
    "show_collection_comparison_result",
    "show_compare_collection",
    "string_collection_mask",
    "unique_string_values",
]
