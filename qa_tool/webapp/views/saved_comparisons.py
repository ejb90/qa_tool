"""Browse and recover immutable comparison snapshots."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from qa_tool.core.archive import (
    comparison_archive_zip,
    list_comparison_archives_from_roots,
    verify_comparison_archive,
)


def show_saved_comparisons(settings: dict[str, Any]) -> None:
    """List saved snapshots and render one without querying the runs database."""
    archive_roots = settings.get("archive", {}).get("search_paths", ["qa_tool_archive"])
    archives = list_comparison_archives_from_roots(archive_roots)
    if not archives:
        searched_paths = ", ".join(f"`{path}`" for path in archive_roots)
        st.info(f"No saved comparisons were found in {searched_paths}.")
        return

    labels = {
        item.snapshot_id: (
            f"{item.manifest.get('created_at', '')} | {item.manifest.get('created_by', 'unknown')} | "
            f"{item.manifest.get('comparison_type', '')} | "
            f"{item.manifest.get('test_label', '')} vs {item.manifest.get('base_label', '')} | {item.snapshot_id}"
        )
        for item in archives
    }
    snapshot_ids = [item.snapshot_id for item in archives]
    requested_id = st.query_params.get("comparison")
    selected_index = snapshot_ids.index(requested_id) if requested_id in snapshot_ids else 0
    if requested_id and requested_id not in snapshot_ids:
        st.warning(f"The linked comparison `{requested_id}` was not found in the configured archive locations.")
    selected_id = st.selectbox(
        "Saved comparison",
        snapshot_ids,
        index=selected_index,
        format_func=labels.__getitem__,
        key="saved_comparison_selector",
    )
    if st.query_params.get("comparison") != selected_id:
        st.query_params["comparison"] = selected_id
    archive = next(item for item in archives if item.snapshot_id == selected_id)
    failures = verify_comparison_archive(archive)
    if failures:
        st.error("Snapshot verification failed: " + "; ".join(failures))
    else:
        st.success("All recorded files passed checksum verification.")

    st.caption(f"Created by `{archive.manifest.get('created_by', 'unknown')}`")
    st.caption("Copy the current browser address to share this comparison.")

    with st.expander("Snapshot manifest"):
        st.json(archive.manifest)
    st.subheader("Comparison")
    st.dataframe(pd.read_parquet(archive.path / "comparison.parquet"), use_container_width=True, hide_index=True)
    with st.expander("Recorded input runs"):
        st.dataframe(pd.read_parquet(archive.path / "runs.parquet"), use_container_width=True, hide_index=True)
    st.download_button(
        "Download snapshot ZIP",
        data=comparison_archive_zip(archive),
        file_name=f"{archive.path.name}.zip",
        mime="application/zip",
        key="saved_comparison_download",
        use_container_width=True,
    )
