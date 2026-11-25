"""Policy loading, regression evaluation, and JUnit rendering."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from junitparser import Failure, JUnitXml
from junitparser.xunit2 import TestCase, TestSuite

Direction = Literal["increase", "decrease", "either"]
UnmatchedModels = Literal["fail", "ignore"]


@dataclass(frozen=True)
class MetricRule:
    """Allowed directional change for one metric."""

    direction: Direction
    absolute_tolerance: float | None = None
    percentage_tolerance: float | None = None


@dataclass(frozen=True)
class GatePolicy:
    """Validated, versioned regression policy."""

    schema_version: int
    unmatched_models: UnmatchedModels
    metrics: tuple[tuple[str, MetricRule], ...]

    @property
    def metric_names(self) -> list[str]:
        """Return policy metrics in source order."""
        return [name for name, _ in self.metrics]


@dataclass(frozen=True)
class GateResult:
    """One model/metric or model-coverage evaluation."""

    model: str
    metric: str
    status: Literal["passed", "failed"]
    reason: str
    direction: Direction | None = None
    base_mean: float | None = None
    test_mean: float | None = None
    mean_difference: float | None = None
    percentage_difference: float | None = None
    absolute_tolerance: float | None = None
    percentage_tolerance: float | None = None
    allowed_change: float | None = None
    regression_change: float | None = None


@dataclass(frozen=True)
class GateEvaluation:
    """Complete regression gate result."""

    results: tuple[GateResult, ...]

    @property
    def status(self) -> Literal["passed", "failed"]:
        """Return the aggregate gate status."""
        return "failed" if any(result.status == "failed" for result in self.results) else "passed"

    @property
    def passed(self) -> int:
        """Count passing cases."""
        return sum(result.status == "passed" for result in self.results)

    @property
    def failed(self) -> int:
        """Count failing cases."""
        return sum(result.status == "failed" for result in self.results)


def _strict_keys(value: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"Unknown {context} field(s): {', '.join(unknown)}")


def _non_negative_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"`{field}` must be a non-negative finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"`{field}` must be a non-negative finite number")
    return number


def parse_gate_policy(data: dict[str, Any]) -> GatePolicy:
    """Validate a decoded policy mapping and return its canonical model."""
    _strict_keys(data, {"schema_version", "gate", "metrics"}, "policy")
    schema_version = data.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise ValueError("`schema_version` must be 1")

    gate = data.get("gate", {})
    if not isinstance(gate, dict):
        raise ValueError("`gate` must be a table")
    _strict_keys(gate, {"unmatched_models"}, "gate")
    unmatched_models = gate.get("unmatched_models", "fail")
    if unmatched_models not in {"fail", "ignore"}:
        raise ValueError("`gate.unmatched_models` must be `fail` or `ignore`")

    configured_metrics = data.get("metrics")
    if not isinstance(configured_metrics, dict) or not configured_metrics:
        raise ValueError("`metrics` must contain at least one metric rule")
    metrics: list[tuple[str, MetricRule]] = []
    for name, raw_rule in configured_metrics.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Metric names must be non-empty strings")
        if not isinstance(raw_rule, dict):
            raise ValueError(f"`metrics.{name}` must be a table")
        _strict_keys(raw_rule, {"direction", "absolute_tolerance", "percentage_tolerance"}, f"metrics.{name}")
        direction = raw_rule.get("direction")
        if direction not in {"increase", "decrease", "either"}:
            raise ValueError(f"`metrics.{name}.direction` must be `increase`, `decrease`, or `either`")
        absolute = raw_rule.get("absolute_tolerance")
        percentage = raw_rule.get("percentage_tolerance")
        if absolute is None and percentage is None:
            raise ValueError(f"`metrics.{name}` must define at least one tolerance")
        metrics.append(
            (
                name,
                MetricRule(
                    direction=direction,
                    absolute_tolerance=(
                        _non_negative_number(absolute, f"metrics.{name}.absolute_tolerance")
                        if absolute is not None
                        else None
                    ),
                    percentage_tolerance=(
                        _non_negative_number(percentage, f"metrics.{name}.percentage_tolerance")
                        if percentage is not None
                        else None
                    ),
                ),
            )
        )
    return GatePolicy(1, unmatched_models, tuple(metrics))


def load_gate_policy(path: str | Path) -> tuple[GatePolicy, str]:
    """Load and validate a TOML policy while retaining its exact source text."""
    policy_path = Path(path)
    source = policy_path.read_text(encoding="utf-8")
    try:
        decoded = tomllib.loads(source)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"Invalid gate policy TOML: {error}") from error
    return parse_gate_policy(decoded), source


def _regression_change(direction: Direction, difference: float) -> float:
    if direction == "increase":
        return max(difference, 0.0)
    if direction == "decrease":
        return max(-difference, 0.0)
    return abs(difference)


def evaluate_gate(
    comparison: pd.DataFrame,
    policy: GatePolicy,
    *,
    base_models: set[str],
    test_models: set[str],
) -> GateEvaluation:
    """Evaluate long-form comparison rows against a validated policy."""
    required = {"model", "metric", "base_mean", "test_mean", "mean_difference"}
    missing_columns = sorted(required - set(comparison.columns))
    if missing_columns:
        raise ValueError("Comparison is missing gate column(s): " + ", ".join(missing_columns))
    shared_models = base_models & test_models
    if not shared_models:
        raise ValueError("The selected collections have no models in common")

    available_metrics = set(comparison["metric"].dropna().astype(str))
    missing_metrics = sorted(set(policy.metric_names) - available_metrics)
    if missing_metrics:
        raise ValueError("Policy metric(s) are unavailable: " + ", ".join(missing_metrics))

    results: list[GateResult] = []
    if policy.unmatched_models == "fail":
        for model in sorted(base_models - test_models):
            results.append(
                GateResult(model, "model_coverage", "failed", "Model is present only in the base collection")
            )
        for model in sorted(test_models - base_models):
            results.append(
                GateResult(model, "model_coverage", "failed", "Model is present only in the test collection")
            )

    rules = dict(policy.metrics)
    selected = comparison[comparison["metric"].isin(policy.metric_names)].sort_values(["model", "metric"])
    expected_pairs = {(model, metric) for model in shared_models for metric in policy.metric_names}
    actual_pairs = {(str(row.model), str(row.metric)) for row in selected.itertuples()}
    missing_pairs = sorted(expected_pairs - actual_pairs)
    if missing_pairs:
        rendered = ", ".join(f"{model}/{metric}" for model, metric in missing_pairs)
        raise ValueError(f"Comparison is missing model/metric result(s): {rendered}")

    for row in selected.itertuples():
        model = str(row.model)
        metric = str(row.metric)
        rule = rules[metric]
        base_mean = float(row.base_mean)
        test_mean = float(row.test_mean)
        difference = float(row.mean_difference)
        if not all(math.isfinite(value) for value in (base_mean, test_mean, difference)):
            raise ValueError(f"Cannot evaluate non-finite values for {model}/{metric}")
        percentage_difference = None if base_mean == 0 else 100 * difference / abs(base_mean)
        allowed_candidates = [rule.absolute_tolerance or 0.0]
        if rule.percentage_tolerance is not None:
            allowed_candidates.append(abs(base_mean) * rule.percentage_tolerance / 100)
        allowed_change = max(allowed_candidates)
        regression_change = _regression_change(rule.direction, difference)
        passed = regression_change <= allowed_change
        reason = (
            f"Regression change {regression_change:.12g} is within allowed change {allowed_change:.12g}"
            if passed
            else f"Regression change {regression_change:.12g} exceeds allowed change {allowed_change:.12g}"
        )
        results.append(
            GateResult(
                model=model,
                metric=metric,
                status="passed" if passed else "failed",
                reason=reason,
                direction=rule.direction,
                base_mean=base_mean,
                test_mean=test_mean,
                mean_difference=difference,
                percentage_difference=percentage_difference,
                absolute_tolerance=rule.absolute_tolerance,
                percentage_tolerance=rule.percentage_tolerance,
                allowed_change=allowed_change,
                regression_change=regression_change,
            )
        )
    return GateEvaluation(tuple(results))


def gate_evaluation_junit(evaluation: GateEvaluation, *, suite_name: str = "qa-tool regression gate") -> str:
    """Serialize a gate evaluation as standard xUnit2 JUnit XML."""
    suite = TestSuite(suite_name)
    suite.add_property("status", evaluation.status)
    suite.add_property("evaluated", str(len(evaluation.results)))
    suite.add_property("passed", str(evaluation.passed))
    suite.add_property("failed", str(evaluation.failed))
    for result in evaluation.results:
        case = TestCase(f"{result.model}.{result.metric}", classname="qa_tool.regression_gate")
        for name in (
            "model",
            "metric",
            "direction",
            "base_mean",
            "test_mean",
            "mean_difference",
            "percentage_difference",
            "absolute_tolerance",
            "percentage_tolerance",
            "allowed_change",
            "regression_change",
        ):
            value = getattr(result, name)
            if value is not None:
                case.add_property(name, str(value))
        if result.status == "failed":
            failure = Failure(result.reason, "regression")
            failure.text = result.reason
            case.result = [failure]
        suite.add_testcase(case)
    suite.update_statistics()
    xml = JUnitXml()
    xml.add_testsuite(suite)
    xml.update_statistics()
    output = BytesIO()
    xml.write(output, pretty=True)
    return output.getvalue().decode("utf-8")
