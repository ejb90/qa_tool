"""QA dashboard module for app."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import streamlit as st

try:
    from qa_tool.data import (
        filter_runs,
        load_run_summary,
        load_runs,
        metric_columns,
        show_downloads,
    )
    from qa_tool.settings import load_settings
    from qa_tool.summaries import (
        show_intro,
        show_navigation_cards,
        show_stored_summary,
        show_tab_summary,
    )
    from qa_tool.views import (
        show_all_runs,
        show_compare_collection,
        show_compare_run,
        show_models_tab,
        show_pie_charts,
        show_run_detail,
        show_version_comparison,
        show_versions_tab,
    )
except ModuleNotFoundError:
    from data import filter_runs, load_run_summary, load_runs, metric_columns, show_downloads
    from settings import load_settings
    from summaries import show_intro, show_navigation_cards, show_stored_summary, show_tab_summary
    from views import (
        show_all_runs,
        show_compare_collection,
        show_compare_run,
        show_models_tab,
        show_pie_charts,
        show_run_detail,
        show_version_comparison,
        show_versions_tab,
    )


def cli_settings_path(argv: Sequence[str] | None = None) -> str | None:
    """Handle cli settings path."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--settings")
    args, _ = parser.parse_known_args(argv)
    return args.settings


def main(settings_path: str | Path | None = None) -> None:
    """Handle main."""
    try:
        settings = load_settings(settings_path or cli_settings_path())
    except FileNotFoundError as error:
        st.set_page_config(page_title="QA Tool", layout="wide")
        st.error(str(error))
        return

    page_title = settings["page"]["title"]
    plot_height = settings["plots"]["height"]

    st.set_page_config(page_title=page_title, layout=settings["page"]["layout"])
    st.title(page_title)

    db_path = Path(settings["database"]["path"])
    if not db_path.exists():
        st.error(f"Could not find {db_path}. Run `uv run python -m qa_tool.load_dummy_data` first.")
        return
    if db_path.suffix != ".duckdb":
        st.error("QA Tool requires a DuckDB database with a `.duckdb` extension.")
        return

    show_intro(settings, db_path)
    stored_summary = load_run_summary(str(db_path))

    configured_tabs = [
        ("overview", "Overview"),
        (
            "all_runs",
            "All Runs",
        ),
        ("versions", "Versions"),
        ("models", "Models"),
        ("compare_versions", "Compare Versions"),
        ("compare_collection", "Compare Collection"),
        ("compare_run", "Compare Run"),
        ("pie_charts", "Pie Charts"),
        ("run_detail", "Run Detail"),
    ]
    enabled_tabs = [(key, label) for key, label in configured_tabs if settings["tabs"].get(key, True)]
    if not enabled_tabs:
        st.warning("No views are enabled in the settings.")
        return
    tab_containers = st.tabs(
        [label for _, label in enabled_tabs],
        key="main_tabs",
        on_change="rerun",
    )
    open_tabs = [(key, label, tab) for (key, label), tab in zip(enabled_tabs, tab_containers, strict=True) if tab.open]
    active_key, _, active_tab = open_tabs[0] if open_tabs else (*enabled_tabs[0], tab_containers[0])
    enabled_tab_labels = [(key, label) for key, label in enabled_tabs if key != "overview"]

    if active_key == "overview":
        with active_tab:
            if stored_summary is not None:
                show_stored_summary(stored_summary)
            else:
                st.warning("No saved summary is available yet.")
            show_navigation_cards(enabled_tab_labels, "main_tabs")
        return

    database_columns = settings["database"].get("columns", {})
    try:
        runs = load_runs(
            str(db_path),
            database_columns.get("model", "model"),
            database_columns.get("version", "version"),
        )
    except Exception as error:
        st.error(f"Could not load database: {error}")
        return

    metrics = metric_columns(runs)
    filtered = filter_runs(runs, metrics, settings)
    metrics = st.session_state.get("summary_metrics", metrics)

    with active_tab:
        if active_key == "all_runs":
            show_tab_summary(filtered, settings, "all_runs", metrics)
            show_all_runs(filtered, settings)
            show_downloads(filtered)
        elif active_key == "versions":
            show_versions_tab(filtered, settings, metrics, plot_height)
        elif active_key == "models":
            show_models_tab(filtered, settings, metrics, plot_height)
        elif active_key == "compare_versions":
            show_tab_summary(filtered, settings, "compare_versions", metrics)
            show_version_comparison(filtered, settings, metrics, plot_height)
        elif active_key == "compare_collection":
            show_tab_summary(filtered, settings, "compare_collection", metrics)
            show_compare_collection(filtered, settings, metrics, plot_height)
        elif active_key == "compare_run":
            show_compare_run(filtered, settings, metrics, plot_height)
        elif active_key == "pie_charts":
            show_tab_summary(filtered, settings, "pie_charts", metrics)
            show_pie_charts(filtered, metrics, plot_height)
        elif active_key == "run_detail":
            show_tab_summary(filtered, settings, "run_detail", metrics)
            show_run_detail(filtered, settings)


if __name__ == "__main__":
    main()
