"""QA dashboard module for all runs."""

from __future__ import annotations

from typing import Any

import streamlit as st

from qa_tool.webapp.data import (
    DatabaseRevision,
    RunFilters,
    RunSchema,
    count_runs,
    load_runs,
    show_downloads,
)


def show_all_runs(
    db_path: str,
    model_column: str,
    version_column: str,
    revision: DatabaseRevision,
    generation: int,
    filters: RunFilters,
    schema: RunSchema,
    settings: dict[str, Any],
) -> None:
    """Query and display one database-backed page of matching runs."""
    st.subheader("Runs")
    search_text = st.text_input(
        "Search runs",
        placeholder="UID, name, model, version, artifact...",
        key="all_runs_search",
    ).strip()
    configured_columns = settings.get("tables", {}).get("all_runs", {}).get("columns", [])
    visible_columns = tuple(column for column in configured_columns if column in schema.columns) or schema.columns
    searchable_columns = tuple(
        source
        for column in ("uid", "name", "model", "version", "artifact")
        if (source := schema.source_for(column)) is not None
    )
    total_rows = count_runs(
        db_path,
        model_column,
        version_column,
        revision,
        generation,
        filters,
        search_text,
        searchable_columns,
    )
    if total_rows == 0:
        st.info("No runs match the current filters and table search.")
        return

    pagination_columns = st.columns([1, 1, 3])
    page_size = pagination_columns[0].selectbox(
        "Rows per page",
        [100, 250, 500, 1000],
        index=1,
        key="all_runs_page_size",
    )
    page_count = max(1, (total_rows - 1) // page_size + 1)
    page_number = pagination_columns[1].number_input(
        "Page",
        min_value=1,
        max_value=page_count,
        value=min(st.session_state.get("all_runs_page_number", 1), page_count),
        step=1,
        key="all_runs_page_number",
    )
    start_index = (page_number - 1) * page_size
    end_index = min(start_index + page_size, total_rows)
    page_data = load_runs(
        db_path,
        model_column,
        version_column,
        revision,
        generation,
        visible_columns,
        filters,
        page_size,
        start_index,
        search_text,
        searchable_columns,
    )
    pagination_columns[2].caption(f"Showing {start_index + 1:,}-{end_index:,} of {total_rows:,} runs")

    st.dataframe(
        page_data,
        use_container_width=True,
        hide_index=True,
        column_config={
            "uid": st.column_config.TextColumn("UID", width="medium"),
            "name": st.column_config.TextColumn("Run", width="large"),
            "date": st.column_config.DatetimeColumn("Date"),
            "density": st.column_config.NumberColumn("Density", format="%.5f"),
            "velocity": st.column_config.NumberColumn("Velocity", format="%.5f"),
            "error": st.column_config.NumberColumn("Error", format="%.5f"),
        },
    )
    show_downloads(page_data, label="current page")
