"""QA dashboard module for summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from qa_tool.webapp.settings import configured_metrics

SUMMARY_AGGREGATIONS = {
    "mean": "Mean",
    "min": "Min",
    "max": "Max",
}
TOP_SUMMARY_LABELS = {
    "runs": "Runs",
    "versions": "Versions",
    "models": "Models",
}

TAB_DESCRIPTIONS = {
    "all_runs": "Search, filter, and inspect every run.",
    "versions": "See how results change between versions.",
    "models": "Compare performance across models.",
    "compare_versions": "Compare two versions side by side.",
    "compare_collection": "Build custom run collections to compare.",
    "compare_run": "Compare two individual runs directly.",
    "pie_charts": "Explore metric distributions visually.",
    "run_detail": "Open detailed time-series artifacts.",
    "saved_comparisons": "Recover a saved comparison without recalculating it.",
}


def show_navigation_cards(
    available_tabs: list[tuple[str, str]],
    tab_state_key: str,
) -> None:
    """Show prominent overview links for the enabled analysis views."""
    st.markdown("### Explore the database")
    st.caption("Choose a view to jump straight into the analysis.")
    columns = st.columns(3)
    for index, (key, label) in enumerate(available_tabs):
        with columns[index % len(columns)], st.container(border=True):
            st.markdown(f"#### {label}")
            st.caption(TAB_DESCRIPTIONS.get(key, ""))
            st.button(
                f"Open {label}",
                key=f"overview_nav_{key}",
                use_container_width=True,
                on_click=lambda selected_label=label: st.session_state.__setitem__(
                    tab_state_key,
                    selected_label,
                ),
            )


def show_intro(settings: dict[str, Any], db_path: Path) -> None:
    """Handle show intro."""
    intro = settings["intro"]
    description = intro.get("description", "")
    links = [link for link in intro.get("links", []) if link.get("label") and link.get("url")]
    artifact_root = settings["database"].get("artifact_root", "")

    if description:
        st.markdown(description)

    if links:
        link_markdown = " | ".join(f"[{link['label']}]({link['url']})" for link in links)
        st.markdown(link_markdown)

    info_items = []
    if intro.get("show_database_path", True):
        info_items.append(f"Database: `{db_path}`")
    if intro.get("show_artifact_root", True) and artifact_root:
        info_items.append(f"Artifact root: `{artifact_root}`")
    if info_items:
        st.caption("  |  ".join(info_items))


def show_summary(
    filtered: pd.DataFrame,
    top_items: list[str],
    metrics: list[str],
    aggregations: list[str],
    statistics: dict[str, Any] | None = None,
) -> None:
    """Handle show summary."""
    top_items = [item for item in top_items if item in TOP_SUMMARY_LABELS]
    if top_items:
        top_columns = st.columns(min(4, len(top_items)))
        for index, item in enumerate(top_items):
            if item == "runs":
                value = statistics["runs"] if statistics is not None else len(filtered)
            elif item == "versions":
                value = statistics["versions"] if statistics is not None else filtered["version"].nunique()
            elif item == "models":
                value = statistics["models"] if statistics is not None else filtered["model"].nunique()
            else:
                value = "n/a"
            top_columns[index % len(top_columns)].metric(TOP_SUMMARY_LABELS[item], value)

    summary_items = [(metric, aggregation) for metric in metrics for aggregation in aggregations]
    if not summary_items:
        return

    summary_columns = st.columns(min(4, len(summary_items)))
    if filtered.empty and statistics is None:
        for index, (metric, aggregation) in enumerate(summary_items):
            label = f"{SUMMARY_AGGREGATIONS[aggregation]} {metric}"
            summary_columns[index % len(summary_columns)].metric(label, "n/a")
        return

    for index, (metric, aggregation) in enumerate(summary_items):
        label = f"{SUMMARY_AGGREGATIONS[aggregation]} {metric}"
        value = (
            statistics[f"{aggregation}_{metric}"]
            if statistics is not None
            else getattr(filtered[metric], aggregation)()
        )
        formatted_value = "n/a" if value is None else f"{value:.4g}"
        summary_columns[index % len(summary_columns)].metric(label, formatted_value)


def show_stored_summary(
    summary: dict[str, Any],
) -> None:
    """Render every displayable value supplied by the summary table."""
    display_items = [(name, value) for name, value in summary.items() if name not in {"summary_id", "refreshed_at"}]
    summary_columns = st.columns(min(4, len(display_items)))
    for index, (name, value) in enumerate(display_items):
        formatted_value = f"{value:.4g}" if isinstance(value, int | float) else "n/a"
        label = str(name).replace("_", " ").title()
        summary_columns[index % len(summary_columns)].metric(label, formatted_value)


def tab_summary_options(
    settings: dict[str, Any],
    tab_key: str,
    available_metrics: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Handle tab summary options."""
    default_summary = settings["summaries"]["default"]
    tab_summary = settings["summaries"]["tabs"].get(tab_key, {})
    fallback_top = ["runs", "versions", "models"]
    fallback_metrics = available_metrics[:2]
    fallback_aggregations = ["mean", "max"]
    top_items = tab_summary.get("top", default_summary.get("top", fallback_top))
    configured_summary_metrics = tab_summary.get(
        "metrics",
        default_summary.get("metrics", fallback_metrics),
    )
    configured_aggregations = tab_summary.get(
        "aggregations",
        default_summary.get("aggregations", fallback_aggregations),
    )
    summary_metrics = (
        configured_metrics(
            configured_summary_metrics,
            available_metrics,
            fallback_metrics,
        )
        if configured_summary_metrics
        else []
    )
    summary_aggregations = [
        aggregation for aggregation in configured_aggregations if aggregation in SUMMARY_AGGREGATIONS
    ]
    return top_items, summary_metrics, summary_aggregations


def show_tab_summary(
    filtered: pd.DataFrame,
    settings: dict[str, Any],
    tab_key: str,
    available_metrics: list[str],
    statistics: dict[str, Any] | None = None,
) -> None:
    """Handle show tab summary."""
    top_items, summary_metrics, summary_aggregations = tab_summary_options(
        settings,
        tab_key,
        available_metrics,
    )
    show_summary(filtered, top_items, summary_metrics, summary_aggregations, statistics)


def modified_filtered_runs(filtered: pd.DataFrame, tab_key: str) -> pd.DataFrame:
    """Handle modified filtered runs."""
    if "modified" not in filtered.columns:
        return filtered

    include_modified = st.checkbox(
        "Include modified runs",
        value=False,
        key=f"{tab_key}_include_modified_runs",
    )
    if include_modified:
        return filtered
    return filtered[~filtered["modified"]].copy()
