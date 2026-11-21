"""Shared comparison calculations for versions, models, and collections."""

from __future__ import annotations

import pandas as pd


def percentage_difference(base_mean: float, test_mean: float) -> float | None:
    """Return the test-minus-base difference as a percentage of the base mean."""
    if base_mean == 0 or pd.isna(base_mean) or pd.isna(test_mean):
        return None
    return 100 * (test_mean - base_mean) / abs(base_mean)


def percentage_uncertainty(base_mean: float, absolute_uncertainty: float) -> float | None:
    """Convert an absolute uncertainty into percentage points of the base mean."""
    if base_mean == 0 or pd.isna(base_mean) or pd.isna(absolute_uncertainty):
        return None
    return 100 * absolute_uncertainty / abs(base_mean)


def build_collection_comparison(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    metrics: list[str],
) -> pd.DataFrame:
    """Compare matching models with means, standard deviations, and percent differences."""
    rows: list[dict[str, object]] = []
    shared_models = sorted(set(base_runs["model"].dropna()) & set(test_runs["model"].dropna()))
    for model in shared_models:
        base_model_runs = base_runs[base_runs["model"] == model]
        test_model_runs = test_runs[test_runs["model"] == model]
        row: dict[str, object] = {
            "model": model,
            f"{base_label}_runs": len(base_model_runs),
            f"{test_label}_runs": len(test_model_runs),
        }
        for metric in metrics:
            base_mean = base_model_runs[metric].mean()
            test_mean = test_model_runs[metric].mean()
            base_std = base_model_runs[metric].std(ddof=1)
            test_std = test_model_runs[metric].std(ddof=1)
            absolute_uncertainty = ((base_std**2 / len(base_model_runs)) + (test_std**2 / len(test_model_runs))) ** 0.5
            row[f"base_mean_{metric}"] = base_mean
            row[f"base_std_{metric}"] = base_std
            row[f"test_mean_{metric}"] = test_mean
            row[f"test_std_{metric}"] = test_std
            row[f"percent_difference_{metric}"] = percentage_difference(base_mean, test_mean)
            row[f"percent_uncertainty_{metric}"] = percentage_uncertainty(base_mean, absolute_uncertainty)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("model") if rows else pd.DataFrame()


def build_collection_metric_deltas(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    metrics: list[str],
) -> pd.DataFrame:
    """Return a long-form comparison table with standard deviations and percent differences."""
    rows: list[dict[str, object]] = []
    shared_models = sorted(set(base_runs["model"].dropna()) & set(test_runs["model"].dropna()))
    for model in shared_models:
        base_model_runs = base_runs[base_runs["model"] == model]
        test_model_runs = test_runs[test_runs["model"] == model]
        for metric in metrics:
            base_mean = base_model_runs[metric].mean()
            test_mean = test_model_runs[metric].mean()
            base_std = base_model_runs[metric].std(ddof=1)
            test_std = test_model_runs[metric].std(ddof=1)
            rows.append(
                {
                    "base_label": base_label,
                    "test_label": test_label,
                    "model": model,
                    "metric": metric,
                    "base_mean": base_mean,
                    "test_mean": test_mean,
                    "mean_difference": test_mean - base_mean,
                    "percent_difference": percentage_difference(base_mean, test_mean),
                    "base_std": base_std,
                    "test_std": test_std,
                    "uncertainty": ((base_std**2 / len(base_model_runs)) + (test_std**2 / len(test_model_runs))) ** 0.5,
                    "percent_uncertainty": percentage_uncertainty(
                        base_mean,
                        ((base_std**2 / len(base_model_runs)) + (test_std**2 / len(test_model_runs))) ** 0.5,
                    ),
                    "base_runs": len(base_model_runs),
                    "test_runs": len(test_model_runs),
                }
            )
    return pd.DataFrame(rows)


def build_version_comparison(
    runs: pd.DataFrame,
    base_version: str,
    test_version: str,
    metrics: list[str],
) -> pd.DataFrame:
    """Compare all shared models between two version selections."""
    return build_collection_comparison(
        runs[runs["version"] == base_version],
        base_version,
        runs[runs["version"] == test_version],
        test_version,
        metrics,
    )


def build_model_comparison(
    runs: pd.DataFrame,
    base_models: list[str],
    test_models: list[str],
    metrics: list[str],
) -> pd.DataFrame:
    """Compare aggregate means with standard deviations and percent differences for model collections."""
    base_runs = runs[runs["model"].isin(base_models)]
    test_runs = runs[runs["model"].isin(test_models)]
    rows = []
    for metric in metrics:
        base_mean = base_runs[metric].mean()
        test_mean = test_runs[metric].mean()
        base_std = base_runs[metric].std(ddof=1)
        test_std = test_runs[metric].std(ddof=1)
        absolute_uncertainty = ((base_std**2 / len(base_runs)) + (test_std**2 / len(test_runs))) ** 0.5
        rows.append(
            {
                "metric": metric,
                "base_mean": base_mean,
                "test_mean": test_mean,
                "mean_difference": test_mean - base_mean,
                "percent_difference": percentage_difference(base_mean, test_mean),
                "base_std": base_std,
                "test_std": test_std,
                "percent_uncertainty": percentage_uncertainty(base_mean, absolute_uncertainty),
                "base_runs": len(base_runs),
                "test_runs": len(test_runs),
            }
        )
    return pd.DataFrame(rows)


def build_run_scalar_comparison(top_run: pd.Series, bottom_run: pd.Series, metrics: list[str]) -> pd.DataFrame:
    """Calculate scalar metric deltas and ratios for a selected pair of runs."""
    rows = []
    for metric in metrics:
        top_value = top_run.get(metric)
        bottom_value = bottom_run.get(metric)
        if pd.isna(top_value) or pd.isna(bottom_value):
            delta = None
            ratio = None
        else:
            delta = bottom_value - top_value
            ratio = None if top_value == 0 else bottom_value / top_value
        rows.append(
            {
                "metric": metric,
                "top": top_value,
                "bottom": bottom_value,
                "bottom_minus_top": delta,
                "bottom_over_top": ratio,
            }
        )
    return pd.DataFrame(rows)
