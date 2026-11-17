"""QA dashboard module for run detail."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

try:
    from qa_tool.webapp.artifacts import run_display_name, run_option_match_index, show_run_artifacts
except ModuleNotFoundError:
    from artifacts import run_display_name, run_option_match_index, show_run_artifacts


def show_run_detail(filtered: pd.DataFrame, settings: dict[str, Any]) -> None:
    """Handle show run detail."""
    if filtered.empty:
        st.info("No runs match the current filters.")
        return

    run_options = filtered.sort_values(["model", "version", "name"]).reset_index(drop=True)
    pasted_id = st.text_input("Paste run UID or name", value="")
    matched_index = run_option_match_index(run_options, pasted_id)
    if pasted_id and matched_index is None:
        st.warning("No run matched that UID or name in the current filters.")

    selected_index = st.selectbox(
        "Run",
        run_options.index,
        index=matched_index or 0,
        format_func=lambda index: run_display_name(run_options.loc[index]),
    )
    selected_run = run_options.loc[selected_index]

    st.subheader("Results")
    details = selected_run.to_frame(name="value").reset_index().rename(columns={"index": "field"})
    st.dataframe(details, use_container_width=True, hide_index=True)

    show_run_artifacts(selected_run, settings["database"].get("artifact_root", ""))
