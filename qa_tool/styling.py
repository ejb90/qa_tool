"""QA dashboard module for styling."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler

COMPARISON_COLOR_SCHEMES = {
    "Red / blue": {
        "negative": (31, 119, 180),
        "positive": (214, 39, 40),
        "sequential": (44, 160, 120),
    },
    "Blue / orange": {
        "negative": (0, 114, 178),
        "positive": (230, 159, 0),
        "sequential": (0, 158, 115),
    },
    "Purple / green": {
        "negative": (117, 112, 179),
        "positive": (27, 158, 119),
        "sequential": (102, 166, 30),
    },
}


def comparison_color_bounds(settings: dict[str, Any]) -> dict[str, float]:
    """Handle comparison color bounds."""
    configured_bounds = settings.get("comparison", {}).get("color_bounds", {})
    return {
        str(metric): float(bound)
        for metric, bound in configured_bounds.items()
        if not isinstance(bound, bool) and isinstance(bound, int | float) and bound > 0
    }


def comparison_column_bound(column: str, bounds: dict[str, float]) -> float | None:
    """Handle comparison column bound."""
    if column in bounds:
        return bounds[column]
    for prefix in ("delta_", "uncertainty_"):
        if column.startswith(prefix):
            metric = column.removeprefix(prefix)
            return bounds.get(metric)
    return None


def select_comparison_color_scheme(key: str) -> str:
    """Handle select comparison color scheme."""
    return st.selectbox(
        "Cell colours",
        ["Red / blue", "Blue / orange", "Purple / green", "Off"],
        index=0,
        key=key,
    )


def styled_comparison_table(
    dataframe: pd.DataFrame,
    settings: dict[str, Any],
    color_scheme: str = "Red / blue",
) -> pd.DataFrame | Styler:
    """Handle styled comparison table."""
    if color_scheme == "Off":
        return dataframe

    color_bounds = comparison_color_bounds(settings)
    colours = COMPARISON_COLOR_SCHEMES.get(
        color_scheme,
        COMPARISON_COLOR_SCHEMES["Red / blue"],
    )

    def alpha_style(red: int, green: int, blue: int, fraction: float) -> str:
        """Handle alpha style."""
        fraction = min(1.0, max(0.0, fraction))
        alpha = 0.18 + 0.62 * fraction
        return f"background-color: rgba({red}, {green}, {blue}, {alpha:.3f})"

    def delta_styles(values: pd.Series, bound: float | None = None) -> list[str]:
        """Handle delta styles."""
        numeric_values = pd.to_numeric(values, errors="coerce")
        max_abs = bound or numeric_values.abs().max()
        if pd.isna(max_abs) or max_abs == 0:
            return [""] * len(values)
        styles = []
        for value in numeric_values:
            if pd.isna(value) or value == 0:
                styles.append("")
            elif value > 0:
                styles.append(alpha_style(*colours["positive"], float(value / max_abs)))
            else:
                styles.append(alpha_style(*colours["negative"], float(abs(value) / max_abs)))
        return styles

    def sequential_styles(values: pd.Series) -> list[str]:
        """Handle sequential styles."""
        numeric_values = pd.to_numeric(values, errors="coerce")
        minimum = numeric_values.min()
        maximum = numeric_values.max()
        if pd.isna(minimum) or pd.isna(maximum) or minimum == maximum:
            return [""] * len(values)
        return [
            ""
            if pd.isna(value)
            else alpha_style(*colours["sequential"], float((value - minimum) / (maximum - minimum)))
            for value in numeric_values
        ]

    def metric_row_styles(row: pd.Series) -> list[str]:
        """Handle metric row styles."""
        styles = pd.Series("", index=row.index)
        metric = str(row.get("metric", ""))
        bound = color_bounds.get(metric)
        if bound is None:
            return styles.tolist()
        for column in ("bottom_minus_top", "mean_delta", "delta"):
            if column not in row.index:
                continue
            value = pd.to_numeric(pd.Series([row[column]]), errors="coerce").iloc[0]
            if pd.isna(value) or value == 0:
                continue
            fraction = min(1.0, abs(float(value)) / bound)
            if value > 0:
                styles[column] = alpha_style(*colours["positive"], fraction)
            else:
                styles[column] = alpha_style(*colours["negative"], fraction)
        return styles.tolist()

    style = dataframe.style
    delta_columns = [
        column
        for column in dataframe.columns
        if str(column).startswith("delta_")
        or str(column).endswith("_minus_top")
        or str(column) in {"delta", "mean_delta", "percent_mean_delta"}
    ]
    for column in delta_columns:
        values = pd.to_numeric(dataframe[column], errors="coerce").dropna()
        if values.empty:
            continue
        style = style.apply(
            delta_styles,
            subset=[column],
            axis=0,
            bound=comparison_column_bound(str(column), color_bounds),
        )

    sequential_columns = [
        column
        for column in dataframe.columns
        if str(column).startswith("uncertainty") or str(column) in {"base_std", "test_std", "std"}
    ]
    for column in sequential_columns:
        values = pd.to_numeric(dataframe[column], errors="coerce").dropna()
        if values.empty or values.max() == values.min():
            continue
        style = style.apply(sequential_styles, subset=[column], axis=0)

    if "metric" in dataframe.columns and color_bounds:
        style = style.apply(metric_row_styles, axis=1)

    return style
