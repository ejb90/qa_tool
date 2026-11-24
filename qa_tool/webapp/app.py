"""QA dashboard module for app."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import streamlit as st

# Streamlit executes an app file with its directory on sys.path. Add the
# directory containing the qa_tool package too, so direct file execution works
# both from a repository checkout and from an installed distribution.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DATABASE = PROJECT_ROOT / "examples" / "runs.duckdb"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qa_tool.webapp.data import (  # noqa: E402
    filter_runs,
    load_run_summary,
    load_runs,
    metric_columns,
    show_downloads,
)
from qa_tool.webapp.settings import load_settings  # noqa: E402
from qa_tool.webapp.summaries import (  # noqa: E402
    show_intro,
    show_navigation_cards,
    show_stored_summary,
    show_tab_summary,
)
from qa_tool.webapp.views import (  # noqa: E402
    show_all_runs,
    show_compare_collection,
    show_compare_run,
    show_models_tab,
    show_pie_charts,
    show_run_detail,
    show_saved_comparisons,
    show_version_comparison,
    show_versions_tab,
)


def cli_app_options(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse application arguments forwarded after Streamlit's separator."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--settings")
    parser.add_argument("--allow-unsafe-pickle", action="store_true")
    args, _ = parser.parse_known_args(argv)
    return args


def cli_settings_path(argv: Sequence[str] | None = None) -> str | None:
    """Return the settings path forwarded to the Streamlit application."""
    return cli_app_options(argv).settings


def resolve_database_path(configured_path: str | Path) -> Path:
    """Use the repository example only when the default live database is absent."""
    database_path = Path(configured_path)
    if database_path == Path("runs.duckdb") and not database_path.exists() and EXAMPLE_DATABASE.exists():
        return EXAMPLE_DATABASE
    return database_path


def main(settings_path: str | Path | None = None) -> None:
    """Handle main."""
    app_options = cli_app_options()
    try:
        settings = load_settings(settings_path or app_options.settings)
    except FileNotFoundError as error:
        st.set_page_config(page_title="QA Tool", layout="wide")
        st.error(str(error))
        return

    page_title = settings["page"]["title"]
    plot_height = settings["plots"]["height"]

    st.set_page_config(page_title=page_title, layout=settings["page"]["layout"])
    st.title(page_title)
    if app_options.allow_unsafe_pickle:
        st.warning("Unsafe pickle rendering is enabled. Open only trusted pickle artifacts on this local dashboard.")

    db_path = resolve_database_path(settings["database"]["path"])
    show_intro(settings, db_path)

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
        ("saved_comparisons", "Saved Comparisons"),
    ]
    enabled_tabs = [(key, label) for key, label in configured_tabs if settings["tabs"].get(key, True)]
    if not enabled_tabs:
        st.warning("No views are enabled in the settings.")
        return
    tab_labels = dict(enabled_tabs)
    requested_view = st.query_params.get("view")
    requested_comparison = st.query_params.get("comparison")
    previous_url_view = st.session_state.get("_qa_tool_url_view")
    selected_tab = st.session_state.get("main_tabs")
    if requested_view == previous_url_view and selected_tab in tab_labels.values():
        default_tab = selected_tab
    elif requested_view in tab_labels:
        default_tab = tab_labels[requested_view]
    elif requested_comparison and "saved_comparisons" in tab_labels:
        default_tab = tab_labels["saved_comparisons"]
    else:
        default_tab = None
    tab_containers = st.tabs(
        [label for _, label in enabled_tabs],
        default=default_tab,
        key="main_tabs",
        on_change="rerun",
    )
    open_tabs = [(key, label, tab) for (key, label), tab in zip(enabled_tabs, tab_containers, strict=True) if tab.open]
    active_key, _, active_tab = open_tabs[0] if open_tabs else (*enabled_tabs[0], tab_containers[0])
    if st.query_params.get("view") != active_key:
        st.query_params["view"] = active_key
    st.session_state["_qa_tool_url_view"] = active_key
    if active_key != "saved_comparisons" and requested_view == active_key and "comparison" in st.query_params:
        del st.query_params["comparison"]
    enabled_tab_labels = [(key, label) for key, label in enabled_tabs if key != "overview"]

    if active_key == "saved_comparisons":
        with active_tab:
            show_saved_comparisons(settings)
        return

    if not db_path.exists():
        st.error(f"Could not find {db_path}. Add a run with `qa-tool ingest ARTIFACT_DIR` first.")
        return
    if db_path.suffix != ".duckdb":
        st.error("QA Tool requires a DuckDB database with a `.duckdb` extension.")
        return

    if active_key == "overview":
        stored_summary = load_run_summary(str(db_path))
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
            show_run_detail(filtered, settings, allow_unsafe_pickle=app_options.allow_unsafe_pickle)


if __name__ == "__main__":
    main()
