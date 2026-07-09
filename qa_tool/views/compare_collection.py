from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

try:
    from qa_tool.compare import build_collection_comparison, build_collection_metric_deltas
    from qa_tool.data import dataframe_to_csv
    from qa_tool.exports import export_name
    from qa_tool.styling import select_comparison_color_scheme, styled_comparison_table
    from qa_tool.views.common import show_comparison_cdf_plot
except ModuleNotFoundError:
    from compare import build_collection_comparison, build_collection_metric_deltas
    from data import dataframe_to_csv
    from exports import export_name
    from styling import select_comparison_color_scheme, styled_comparison_table
    from views.common import show_comparison_cdf_plot

def collection_parameter_columns(
    runs: pd.DataFrame,
    metrics: list[str],
) -> list[str]:
    excluded_columns = set(metrics)
    preferred_columns = [
        "version",
        "date",
        "artifact",
        "git_commit",
        "commit",
        "git_branch",
        "branch",
        "git_tag",
        "tag",
        "job_name",
        "hpc_system",
        "scheduler",
        "queue",
        "model",
        "modified",
    ]
    available_columns = [
        column
        for column in runs.columns
        if column not in excluded_columns and not runs[column].dropna().empty
    ]
    ordered_columns = [
        column
        for column in preferred_columns
        if column in available_columns
    ]
    ordered_columns.extend(
        sorted(column for column in available_columns if column not in ordered_columns)
    )
    return ordered_columns

def compact_collection_label(field: str, match_mode: str, values: Sequence[Any]) -> str:
    clean_values = [str(value) for value in values if str(value)]
    if not clean_values:
        return f"{field}: empty"
    if len(clean_values) == 1:
        return f"{field} {match_mode} {clean_values[0]}"
    first_values = ", ".join(clean_values[:3])
    if len(clean_values) > 3:
        first_values = f"{first_values}, +{len(clean_values) - 3}"
    return f"{field} {match_mode} {first_values}"

def unique_string_values(runs: pd.DataFrame, field: str) -> list[str]:
    return sorted(
        runs[field].dropna().astype(str).unique(),
        key=lambda value: value.lower(),
    )

def select_datetime_collection(
    filtered: pd.DataFrame,
    field: str,
    prefix: str,
    label: str,
) -> tuple[str, pd.DataFrame]:
    values = pd.to_datetime(filtered[field], errors="coerce")
    valid_values = values.dropna()
    if valid_values.empty:
        st.info(f"`{field}` has no datetime values.")
        return f"{label} {field}", filtered.iloc[0:0].copy()

    min_date = valid_values.min().date()
    max_date = valid_values.max().date()
    selected_range = st.date_input(
        f"{label} window",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        key=f"{prefix}_date_window",
    )
    if len(selected_range) != 2:
        return f"{label} {field}", filtered.iloc[0:0].copy()

    start = pd.to_datetime(selected_range[0])
    end = pd.to_datetime(selected_range[1]) + pd.Timedelta(days=1)
    selected_runs = filtered[(values >= start) & (values < end)].copy()
    default_name = f"{field} {selected_range[0]} to {selected_range[1]}"
    collection_name = st.text_input(
        f"{label} name",
        value=default_name,
        key=f"{prefix}_date_name",
    )
    return collection_name, selected_runs

def select_bool_collection(
    filtered: pd.DataFrame,
    field: str,
    prefix: str,
    label: str,
) -> tuple[str, pd.DataFrame]:
    values = sorted(filtered[field].dropna().unique())
    selected_values = st.multiselect(
        f"{label} values",
        values,
        default=values[:1],
        key=f"{prefix}_bool_values",
    )
    selected_runs = filtered[filtered[field].isin(selected_values)].copy()
    default_name = compact_collection_label(field, "is", selected_values)
    collection_name = st.text_input(
        f"{label} name",
        value=default_name,
        key=f"{prefix}_bool_name",
    )
    return collection_name, selected_runs

def string_collection_mask(
    values: pd.Series,
    match_mode: str,
    selected_values: Sequence[str],
    free_text: str,
) -> pd.Series:
    string_values = values.fillna("").astype(str)
    if match_mode == "Exact values":
        return string_values.isin(selected_values)
    if match_mode == "Starts with":
        return string_values.str.startswith(free_text, na=False)
    if match_mode == "Contains":
        return string_values.str.contains(free_text, case=False, regex=False, na=False)
    if match_mode == "Regex":
        try:
            return string_values.str.contains(free_text, case=False, regex=True, na=False)
        except re.error:
            st.warning(f"`{free_text}` is not a valid regular expression.")
            return pd.Series(False, index=values.index)
    if match_mode == "Non-empty":
        return string_values.str.len() > 0
    return pd.Series(False, index=values.index)

def select_string_collection(
    filtered: pd.DataFrame,
    field: str,
    prefix: str,
    label: str,
    match_mode: str,
    default_exact_index: int,
) -> tuple[str, pd.DataFrame]:
    value_options = unique_string_values(filtered, field)
    selected_values: list[str] = []
    free_text = ""
    if match_mode == "Exact values":
        default_values = value_options[default_exact_index:default_exact_index + 1]
        selected_values = st.multiselect(
            f"{label} values",
            value_options,
            default=default_values,
            key=f"{prefix}_exact_values",
        )
        default_name = compact_collection_label(field, "is", selected_values)
    elif match_mode in {"Starts with", "Contains", "Regex"}:
        free_text = st.text_input(
            f"{label} match text",
            value="",
            key=f"{prefix}_match_text",
        )
        default_name = compact_collection_label(field, match_mode.lower(), [free_text])
    else:
        default_name = f"{field} non-empty"

    mask = string_collection_mask(
        filtered[field],
        match_mode,
        selected_values,
        free_text,
    )
    selected_runs = filtered[mask].copy()
    collection_name = st.text_input(
        f"{label} name",
        value=default_name,
        key=f"{prefix}_string_name",
    )
    return collection_name, selected_runs

def select_collection_runs(
    filtered: pd.DataFrame,
    field: str,
    prefix: str,
    label: str,
    match_mode: str,
    default_exact_index: int,
) -> tuple[str, pd.DataFrame]:
    if pd.api.types.is_datetime64_any_dtype(filtered[field]):
        return select_datetime_collection(filtered, field, prefix, label)
    if pd.api.types.is_bool_dtype(filtered[field]):
        return select_bool_collection(filtered, field, prefix, label)
    return select_string_collection(
        filtered,
        field,
        prefix,
        label,
        match_mode,
        default_exact_index,
    )

def show_collection_comparison_result(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
    key_prefix: str,
) -> None:
    if base_runs.empty or test_runs.empty:
        st.info("Both selected collections need data.")
        return

    comparison = build_collection_comparison(
        base_runs=base_runs,
        base_label=base_label,
        test_runs=test_runs,
        test_label=test_label,
        metrics=metrics,
    )
    if comparison.empty:
        st.info("No models are present in both selected collections.")
        return

    count_columns = st.columns(2)
    count_columns[0].metric(f"{base_label} runs", len(base_runs))
    count_columns[1].metric(f"{test_label} runs", len(test_runs))

    color_scheme = select_comparison_color_scheme(f"{key_prefix}_color_scheme")
    st.dataframe(
        styled_comparison_table(comparison, settings, color_scheme),
        use_container_width=True,
        hide_index=True,
    )

    selected_metric = st.selectbox(
        "Delta metric",
        metrics,
        key=f"{key_prefix}_delta_metric",
    )
    delta_column = f"delta_{selected_metric}"
    uncertainty_column = f"uncertainty_{selected_metric}"
    plot_data = comparison.sort_values(delta_column)
    fig = px.bar(
        plot_data,
        x="model",
        y=delta_column,
        error_y=uncertainty_column,
        color=delta_column,
        color_continuous_scale="RdBu",
        title=f"{selected_metric} delta: {test_label} - {base_label}",
    )
    fig.update_layout(
        height=plot_height,
        margin=dict(l=10, r=10, t=44, b=10),
        xaxis_title="Model",
        yaxis_title=delta_column,
        coloraxis_showscale=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    show_comparison_cdf_plot(
        null_runs=base_runs,
        test_runs=test_runs,
        metrics=metrics,
        plot_height=plot_height,
        null_label=f"Null: {base_label}",
        test_label=f"Test: {test_label}",
        key_prefix=key_prefix,
        settings=settings,
        color_scheme=color_scheme,
    )
    st.download_button(
        "Download calculated mean differences CSV",
        data=dataframe_to_csv(
            build_collection_metric_deltas(
                base_runs,
                base_label,
                test_runs,
                test_label,
                metrics,
            )
        ),
        file_name=(
            f"mean_differences_{export_name(base_label)}_to_"
            f"{export_name(test_label)}.csv"
        ),
        mime="text/csv",
        key="compare_collection_mean_differences_download",
        use_container_width=True,
    )

def show_compare_collection(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    if filtered.empty:
        st.info("No runs match the current filters.")
        return
    if not metrics:
        st.info("No numeric metrics are available for comparison.")
        return

    parameter_columns = collection_parameter_columns(filtered, metrics)
    if not parameter_columns:
        st.info("No collection parameters are available.")
        return

    selected_field = st.selectbox(
        "Collection parameter",
        parameter_columns,
        key="compare_collection_parameter",
    )
    match_mode = "Exact values"
    if (
        not pd.api.types.is_datetime64_any_dtype(filtered[selected_field])
        and not pd.api.types.is_bool_dtype(filtered[selected_field])
    ):
        match_mode = st.selectbox(
            "Match",
            ["Exact values", "Starts with", "Contains", "Regex", "Non-empty"],
            key="compare_collection_match_mode",
        )

    collection_columns = st.columns(2)
    with collection_columns[0]:
        base_label, base_runs = select_collection_runs(
            filtered=filtered,
            field=selected_field,
            prefix="compare_collection_base",
            label="Null / base collection",
            match_mode=match_mode,
            default_exact_index=0,
        )
    with collection_columns[1]:
        test_label, test_runs = select_collection_runs(
            filtered=filtered,
            field=selected_field,
            prefix="compare_collection_test",
            label="Test collection",
            match_mode=match_mode,
            default_exact_index=1,
        )

    if base_label == test_label:
        st.info("Choose different collection names.")
        return

    show_collection_comparison_result(
        base_runs=base_runs,
        base_label=base_label,
        test_runs=test_runs,
        test_label=test_label,
        settings=settings,
        metrics=metrics,
        plot_height=plot_height,
        key_prefix="compare_collection",
    )
