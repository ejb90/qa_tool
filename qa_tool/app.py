from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import streamlit as st

try:
    from qa_tool.data import filter_runs, load_runs, metric_columns, show_downloads
    from qa_tool.settings import load_settings
    from qa_tool.summaries import show_intro, show_tab_summary
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
    from data import filter_runs, load_runs, metric_columns, show_downloads
    from settings import load_settings
    from summaries import show_intro, show_tab_summary
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
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--settings")
    args, _ = parser.parse_known_args(argv)
    return args.settings


def main(settings_path: str | Path | None = None) -> None:
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

    show_intro(settings, db_path)

    database_columns = settings["database"].get("columns", {})
    try:
        runs = load_runs(
            str(db_path),
            database_columns.get("model", "model"),
            database_columns.get("version", "version"),
        )
    except ValueError as error:
        st.error(str(error))
        return

    metrics = metric_columns(runs)
    filtered = filter_runs(runs, metrics, settings)
    metrics = st.session_state.get("summary_metrics", metrics)

    show_downloads(filtered)

    available_tabs = [
        (
            "all_runs",
            "All Runs",
            lambda: (
                show_tab_summary(filtered, settings, "all_runs", metrics),
                show_all_runs(filtered),
            ),
        ),
        (
            "versions",
            "Versions",
            lambda: show_versions_tab(filtered, settings, metrics, plot_height),
        ),
        (
            "models",
            "Models",
            lambda: show_models_tab(filtered, settings, metrics, plot_height),
        ),
        (
            "compare_versions",
            "Compare Versions",
            lambda: (
                show_tab_summary(filtered, settings, "compare_versions", metrics),
                show_version_comparison(filtered, settings, metrics, plot_height),
            ),
        ),
        (
            "compare_collection",
            "Compare Collection",
            lambda: (
                show_tab_summary(filtered, settings, "compare_collection", metrics),
                show_compare_collection(filtered, settings, metrics, plot_height),
            ),
        ),
        (
            "compare_run",
            "Compare Run",
            lambda: show_compare_run(filtered, settings, metrics, plot_height),
        ),
        (
            "pie_charts",
            "Pie Charts",
            lambda: (
                show_tab_summary(filtered, settings, "pie_charts", metrics),
                show_pie_charts(filtered, metrics, plot_height),
            ),
        ),
        (
            "run_detail",
            "Run Detail",
            lambda: (
                show_tab_summary(filtered, settings, "run_detail", metrics),
                show_run_detail(filtered, settings),
            ),
        ),
    ]
    enabled_tabs = [
        (label, renderer)
        for key, label, renderer in available_tabs
        if settings["tabs"].get(key, True)
    ]
    for tab, (_, renderer) in zip(st.tabs([label for label, _ in enabled_tabs]), enabled_tabs):
        with tab:
            renderer()


if __name__ == "__main__":
    main()
