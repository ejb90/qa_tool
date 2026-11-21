"""QA dashboard module for exports."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from qa_tool.core.archive import ComparisonArchive, comparison_archive_zip, create_comparison_archive


def export_name(value: str) -> str:
    """Handle export name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "data"


def dataframes_to_zip(dataframes: dict[str, pd.DataFrame]) -> bytes:
    """Handle dataframes to zip."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, dataframe in dataframes.items():
            archive.writestr(
                f"{export_name(name)}.csv",
                dataframe.to_csv(index=False),
            )
    return buffer.getvalue()


def show_export_download(
    label: str,
    dataframes: dict[str, pd.DataFrame],
    file_name: str,
    key: str,
) -> None:
    """Handle show export download."""
    if not dataframes:
        return
    st.download_button(
        label,
        data=dataframes_to_zip(dataframes),
        file_name=file_name,
        mime="application/zip",
        key=key,
        use_container_width=True,
    )


def show_comparison_archive_controls(
    *,
    settings: dict[str, object],
    comparison_type: str,
    base_label: str,
    test_label: str,
    base_runs: pd.DataFrame,
    test_runs: pd.DataFrame,
    comparison: pd.DataFrame,
    metrics: list[str],
    key: str,
    parameters: dict[str, object] | None = None,
    artifact_paths: dict[str, Path] | None = None,
) -> None:
    """Save and download a durable comparison snapshot from Streamlit."""
    archive_settings = settings.get("archive", {})
    archive_root = (
        str(archive_settings.get("save_path", "qa_tool_archive"))
        if isinstance(archive_settings, dict)
        else "qa_tool_archive"
    )
    selection = (
        comparison_type,
        base_label,
        test_label,
        tuple(base_runs.get("uid", pd.Series(dtype=str)).astype(str)),
        tuple(test_runs.get("uid", pd.Series(dtype=str)).astype(str)),
        tuple(metrics),
    )
    state_key = f"{key}_saved_archive"
    with st.expander("Preserve this comparison", expanded=False):
        st.caption("Save the selected runs, calculated results, standalone report, and integrity checks together.")
        if st.button("Save comparison snapshot", key=f"{key}_save", use_container_width=True):
            archive = create_comparison_archive(
                archive_root,
                comparison_type=comparison_type,
                base_label=base_label,
                test_label=test_label,
                base_runs=base_runs,
                test_runs=test_runs,
                comparison=comparison,
                metrics=metrics,
                parameters=parameters,
                artifact_paths=artifact_paths,
            )
            st.session_state[state_key] = {"archive": archive, "selection": selection}
            st.query_params["view"] = "saved_comparisons"
            st.query_params["comparison"] = archive.snapshot_id

        saved = st.session_state.get(state_key)
        if not saved or saved.get("selection") != selection:
            return
        archive = saved.get("archive")
        if not isinstance(archive, ComparisonArchive):
            return
        st.success(f"Saved comparison `{archive.snapshot_id}` to `{archive.path}`.")
        st.caption("The current browser address now links to this saved comparison.")
        st.link_button(
            "Open saved comparison",
            f"?view=saved_comparisons&comparison={archive.snapshot_id}",
            width="stretch",
        )
        st.download_button(
            "Download saved snapshot ZIP",
            data=comparison_archive_zip(archive),
            file_name=f"{archive.path.name}.zip",
            mime="application/zip",
            key=f"{key}_download",
            use_container_width=True,
        )
