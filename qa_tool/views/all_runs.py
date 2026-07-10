"""QA dashboard module for all runs."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def show_all_runs(filtered: pd.DataFrame, settings: dict[str, Any]) -> None:
    """Handle show all runs."""
    st.subheader("Runs")
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    searchable_columns = [
        column for column in ["uid", "name", "model", "version", "artifact"] if column in filtered.columns
    ]
    search_text = st.text_input(
        "Search runs",
        placeholder="UID, name, model, version, artifact...",
        key="all_runs_search",
    ).strip()
    table_data = filtered.sort_values("date", ascending=False) if "date" in filtered.columns else filtered
    if search_text and searchable_columns:
        search_mask = pd.Series(False, index=filtered.index)
        for column in searchable_columns:
            search_mask |= (
                filtered[column]
                .fillna("")
                .astype(str)
                .str.contains(
                    search_text,
                    case=False,
                    regex=False,
                    na=False,
                )
            )
        table_data = filtered[search_mask]

    if table_data.empty:
        st.info("No runs match the table search.")
        return

    configured_columns = settings.get("tables", {}).get("all_runs", {}).get("columns", [])
    visible_columns = [column for column in configured_columns if column in table_data.columns]
    if visible_columns:
        table_data = table_data.loc[:, visible_columns]

    pagination_columns = st.columns([1, 1, 3])
    page_size = pagination_columns[0].selectbox(
        "Rows per page",
        [100, 250, 500, 1000],
        index=1,
        key="all_runs_page_size",
    )
    page_count = max(1, (len(table_data) - 1) // page_size + 1)
    page_number = pagination_columns[1].number_input(
        "Page",
        min_value=1,
        max_value=page_count,
        value=min(st.session_state.get("all_runs_page_number", 1), page_count),
        step=1,
        key="all_runs_page_number",
    )
    start_index = (page_number - 1) * page_size
    end_index = min(start_index + page_size, len(table_data))
    page_data = table_data.iloc[start_index:end_index]
    pagination_columns[2].caption(f"Showing {start_index + 1:,}-{end_index:,} of {len(table_data):,} runs")

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
