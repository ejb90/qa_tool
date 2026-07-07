from __future__ import annotations

import pandas as pd

try:
    from qa_tool.exports import export_name
except ModuleNotFoundError:
    from exports import export_name


COLLECTION_LABEL_COLUMN = "__collection__"


def comparison_metadata(
    base_label: str,
    test_label: str,
    base_runs: pd.DataFrame,
    test_runs: pd.DataFrame,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"item": "base_label", "value": base_label},
            {"item": "test_label", "value": test_label},
            {"item": "base_run_count", "value": len(base_runs)},
            {"item": "test_run_count", "value": len(test_runs)},
            {"item": "base_model_count", "value": base_runs["model"].nunique()},
            {"item": "test_model_count", "value": test_runs["model"].nunique()},
        ]
    )


def comparison_coverage(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
) -> pd.DataFrame:
    base_models = set(base_runs["model"].dropna().astype(str))
    test_models = set(test_runs["model"].dropna().astype(str))
    rows = []
    for model in sorted(base_models | test_models):
        in_base = model in base_models
        in_test = model in test_models
        if in_base and in_test:
            status = "shared"
        elif in_base:
            status = f"only_{export_name(base_label)}"
        else:
            status = f"only_{export_name(test_label)}"
        rows.append(
            {
                "model": model,
                "in_base": in_base,
                "in_test": in_test,
                "status": status,
            }
        )
    return pd.DataFrame(rows)


def build_collection_metric_deltas(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    metrics: list[str],
) -> pd.DataFrame:
    base_summary = (
        base_runs.groupby("model")[metrics]
        .agg(["mean", "std", "count"])
        .stack(level=0, future_stack=True)
        .reset_index()
        .rename(
            columns={
                "level_1": "metric",
                "mean": "base_mean",
                "std": "base_std",
                "count": "base_runs",
            }
        )
    )
    test_summary = (
        test_runs.groupby("model")[metrics]
        .agg(["mean", "std", "count"])
        .stack(level=0, future_stack=True)
        .reset_index()
        .rename(
            columns={
                "level_1": "metric",
                "mean": "test_mean",
                "std": "test_std",
                "count": "test_runs",
            }
        )
    )
    comparison = base_summary.merge(
        test_summary,
        on=["model", "metric"],
        how="outer",
    ).sort_values(["metric", "model"])
    comparison["base_label"] = base_label
    comparison["test_label"] = test_label
    comparison["mean_delta"] = comparison["test_mean"] - comparison["base_mean"]
    comparison["percent_mean_delta"] = 100 * comparison["mean_delta"] / comparison["base_mean"]
    comparison.loc[comparison["base_mean"] == 0, "percent_mean_delta"] = pd.NA
    comparison["uncertainty"] = (
        (comparison["base_std"].fillna(0.0) ** 2 / comparison["base_runs"])
        + (comparison["test_std"].fillna(0.0) ** 2 / comparison["test_runs"])
    ) ** 0.5
    return comparison[
        [
            "base_label",
            "test_label",
            "model",
            "metric",
            "base_mean",
            "test_mean",
            "mean_delta",
            "percent_mean_delta",
            "base_std",
            "test_std",
            "uncertainty",
            "base_runs",
            "test_runs",
        ]
    ]


def build_collection_comparison(
    base_runs: pd.DataFrame,
    base_label: str,
    test_runs: pd.DataFrame,
    test_label: str,
    metrics: list[str],
) -> pd.DataFrame:
    base_runs = base_runs.copy()
    test_runs = test_runs.copy()
    base_runs[COLLECTION_LABEL_COLUMN] = base_label
    test_runs[COLLECTION_LABEL_COLUMN] = test_label
    comparison_data = pd.concat([base_runs, test_runs], ignore_index=True)

    means = comparison_data.groupby(["model", COLLECTION_LABEL_COLUMN], as_index=False)[metrics].mean()
    stds = comparison_data.groupby(["model", COLLECTION_LABEL_COLUMN], as_index=False)[metrics].std()
    counts = comparison_data.groupby(["model", COLLECTION_LABEL_COLUMN], as_index=False).agg(
        run_count=("uid", "count")
    )
    mean_wide = means.pivot(index="model", columns=COLLECTION_LABEL_COLUMN, values=metrics)
    std_wide = stds.pivot(index="model", columns=COLLECTION_LABEL_COLUMN, values=metrics).fillna(0.0)
    count_wide = counts.pivot(index="model", columns=COLLECTION_LABEL_COLUMN, values="run_count")
    shared_models = [
        model
        for model in mean_wide.index
        if all((metric, base_label) in mean_wide.columns for metric in metrics)
        and all((metric, test_label) in mean_wide.columns for metric in metrics)
        and mean_wide.loc[model].notna().all()
    ]

    rows = []
    for model in shared_models:
        row = {
            "model": model,
            f"{base_label}_runs": int(count_wide.loc[model, base_label]),
            f"{test_label}_runs": int(count_wide.loc[model, test_label]),
        }
        for metric in metrics:
            base_std = std_wide.loc[model, (metric, base_label)]
            test_std = std_wide.loc[model, (metric, test_label)]
            base_count = count_wide.loc[model, base_label]
            test_count = count_wide.loc[model, test_label]
            row[f"delta_{metric}"] = (
                mean_wide.loc[model, (metric, test_label)]
                - mean_wide.loc[model, (metric, base_label)]
            )
            row[f"uncertainty_{metric}"] = (
                (base_std ** 2 / base_count) + (test_std ** 2 / test_count)
            ) ** 0.5
        rows.append(row)

    return pd.DataFrame(rows).sort_values("model")


def build_version_comparison(
    filtered: pd.DataFrame,
    base_version: str,
    new_version: str,
    metrics: list[str],
) -> pd.DataFrame:
    return build_collection_comparison(
        base_runs=filtered[filtered["version"] == base_version],
        base_label=base_version,
        test_runs=filtered[filtered["version"] == new_version],
        test_label=new_version,
        metrics=metrics,
    )


def build_run_scalar_comparison(top_run: pd.Series, bottom_run: pd.Series, metrics: list[str]) -> pd.DataFrame:
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
