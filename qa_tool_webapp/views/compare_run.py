"""QA dashboard module for compare run."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

try:
    from qa_tool_webapp.artifacts import (
        compare_run_parquet_pairs,
        run_display_name,
        run_option_match_index,
        show_compare_run_artifacts,
    )
    from qa_tool_webapp.compare import build_run_scalar_comparison
    from qa_tool_webapp.styling import select_comparison_color_scheme, styled_comparison_table
except ModuleNotFoundError:
    from artifacts import (
        compare_run_parquet_pairs,
        run_display_name,
        run_option_match_index,
        show_compare_run_artifacts,
    )
    from compare import build_run_scalar_comparison
    from styling import select_comparison_color_scheme, styled_comparison_table


def show_compare_run(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    metrics: list[str],
    plot_height: int,
) -> None:
    """Handle show compare run."""
    if filtered.empty:
        st.info("No runs match the current filters.")
        return
    if len(filtered) < 2:
        st.info("At least two runs are needed for a comparison.")
        return

    run_options = filtered.sort_values(["model", "version", "name"]).reset_index(drop=True)
    selector_columns = st.columns(2)
    top_pasted_id = selector_columns[0].text_input("Paste top run UID or name", value="")
    bottom_pasted_id = selector_columns[1].text_input("Paste bottom run UID or name", value="")
    top_matched_index = run_option_match_index(run_options, top_pasted_id)
    bottom_matched_index = run_option_match_index(run_options, bottom_pasted_id)
    if top_pasted_id and top_matched_index is None:
        selector_columns[0].warning("No run matched that UID or name in the current filters.")
    if bottom_pasted_id and bottom_matched_index is None:
        selector_columns[1].warning("No run matched that UID or name in the current filters.")
    top_index = selector_columns[0].selectbox(
        "Top run",
        run_options.index,
        index=top_matched_index or 0,
        format_func=lambda index: run_display_name(run_options.loc[index]),
    )
    bottom_index = selector_columns[1].selectbox(
        "Bottom run",
        run_options.index,
        index=bottom_matched_index or (1 if len(run_options) > 1 else 0),
        format_func=lambda index: run_display_name(run_options.loc[index]),
    )
    top_run = run_options.loc[top_index]
    bottom_run = run_options.loc[bottom_index]
    if top_run["uid"] == bottom_run["uid"]:
        st.info("Choose two different runs.")
        return

    st.subheader("Scalar Comparison")
    color_scheme = select_comparison_color_scheme("compare_run_color_scheme")
    scalar_comparison = build_run_scalar_comparison(top_run, bottom_run, metrics)
    st.dataframe(
        styled_comparison_table(scalar_comparison, settings, color_scheme),
        use_container_width=True,
        hide_index=True,
    )

    artifact_root = settings["database"].get("artifact_root", "")
    if compare_run_parquet_pairs(top_run, bottom_run, artifact_root):
        st.subheader("Artifact Time Series")
        show_compare_run_artifacts(top_run, bottom_run, artifact_root, plot_height)
