"""Tests for policy-driven regression gates and JUnit output."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest
from junitparser import JUnitXml

from qa_tool.core.gates import evaluate_gate, gate_evaluation_junit, parse_gate_policy


def comparison_rows() -> pd.DataFrame:
    """Return deterministic long-form comparison results."""
    return pd.DataFrame(
        [
            {"model": "co2", "metric": "density", "base_mean": 2.0, "test_mean": 2.03, "mean_difference": 0.03},
            {"model": "h2", "metric": "density", "base_mean": 1.0, "test_mean": 1.02, "mean_difference": 0.02},
            {"model": "co2", "metric": "error", "base_mean": -2.0, "test_mean": -2.2, "mean_difference": -0.2},
            {"model": "h2", "metric": "error", "base_mean": 0.0, "test_mean": 0.1, "mean_difference": 0.1},
        ]
    )


def test_policy_combines_tolerances_and_evaluates_directions() -> None:
    """The larger absolute/relative allowance applies in each configured direction."""
    policy = parse_gate_policy(
        {
            "schema_version": 1,
            "metrics": {
                "density": {"direction": "increase", "absolute_tolerance": 0.01, "percentage_tolerance": 2.0},
                "error": {"direction": "decrease", "absolute_tolerance": 0.1},
            },
        }
    )

    evaluation = evaluate_gate(comparison_rows(), policy, base_models={"co2", "h2"}, test_models={"co2", "h2"})

    assert evaluation.status == "failed"
    assert evaluation.passed == 3
    assert evaluation.failed == 1
    results = {(result.model, result.metric): result for result in evaluation.results}
    assert results["h2", "density"].status == "passed"  # Exact boundary.
    assert results["co2", "density"].allowed_change == pytest.approx(0.04)
    assert results["co2", "error"].regression_change == pytest.approx(0.2)
    assert results["h2", "error"].percentage_difference is None


def test_either_direction_and_unmatched_model_policy() -> None:
    """Either-direction thresholds use magnitude and coverage can fail or be ignored."""
    failing_policy = parse_gate_policy(
        {
            "schema_version": 1,
            "gate": {"unmatched_models": "fail"},
            "metrics": {"density": {"direction": "either", "absolute_tolerance": 0.05}},
        }
    )
    ignored_policy = parse_gate_policy(
        {
            "schema_version": 1,
            "gate": {"unmatched_models": "ignore"},
            "metrics": {"density": {"direction": "either", "absolute_tolerance": 0.05}},
        }
    )
    density = comparison_rows().query("metric == 'density'")

    failed = evaluate_gate(density, failing_policy, base_models={"co2", "h2", "base-only"}, test_models={"co2", "h2"})
    ignored = evaluate_gate(density, ignored_policy, base_models={"co2", "h2", "base-only"}, test_models={"co2", "h2"})

    assert failed.failed == 1
    assert failed.results[0].metric == "model_coverage"
    assert ignored.status == "passed"
    assert len(ignored.results) == 2


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ({}, "schema_version"),
        ({"schema_version": 2, "metrics": {}}, "schema_version"),
        ({"schema_version": 1, "unknown": True, "metrics": {}}, "Unknown policy"),
        (
            {
                "schema_version": 1,
                "gate": {"unmatched_models": "maybe"},
                "metrics": {"x": {"direction": "either", "absolute_tolerance": 1}},
            },
            "unmatched_models",
        ),
        ({"schema_version": 1, "metrics": {}}, "at least one"),
        ({"schema_version": 1, "metrics": {"x": {"direction": "up", "absolute_tolerance": 1}}}, "direction"),
        ({"schema_version": 1, "metrics": {"x": {"direction": "increase"}}}, "at least one tolerance"),
        ({"schema_version": 1, "metrics": {"x": {"direction": "increase", "absolute_tolerance": -1}}}, "non-negative"),
        (
            {"schema_version": 1, "metrics": {"x": {"direction": "increase", "percentage_tolerance": float("inf")}}},
            "finite",
        ),
    ],
)
def test_invalid_policies_are_rejected(policy: dict[str, object], message: str) -> None:
    """Policy validation is strict and produces actionable errors."""
    with pytest.raises(ValueError, match=message):
        parse_gate_policy(policy)


def test_missing_and_non_finite_results_are_rejected() -> None:
    """A gate cannot silently pass incomplete or invalid comparison data."""
    policy = parse_gate_policy(
        {"schema_version": 1, "metrics": {"density": {"direction": "increase", "absolute_tolerance": 1}}}
    )
    with pytest.raises(ValueError, match="no models in common"):
        evaluate_gate(comparison_rows(), policy, base_models={"base"}, test_models={"test"})
    with pytest.raises(ValueError, match="unavailable"):
        evaluate_gate(
            comparison_rows().query("metric == 'error'"),
            policy,
            base_models={"co2", "h2"},
            test_models={"co2", "h2"},
        )
    invalid = comparison_rows().query("metric == 'density'").copy()
    invalid.loc[invalid.index[0], "test_mean"] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        evaluate_gate(invalid, policy, base_models={"co2", "h2"}, test_models={"co2", "h2"})


def test_junit_round_trip_records_cases_failures_and_properties() -> None:
    """Generated xUnit2 output is parseable and exposes gate evidence."""
    policy = parse_gate_policy(
        {"schema_version": 1, "metrics": {"density": {"direction": "increase", "absolute_tolerance": 0.025}}}
    )
    evaluation = evaluate_gate(
        comparison_rows().query("metric == 'density'"),
        policy,
        base_models={"co2", "h2"},
        test_models={"co2", "h2"},
    )

    rendered = gate_evaluation_junit(evaluation)
    parsed = JUnitXml.fromfile(BytesIO(rendered.encode()))
    suite = next(iter(parsed))
    cases = list(suite)

    assert rendered.startswith("<?xml")
    assert suite.name == "qa-tool regression gate"
    assert len(cases) == 2
    assert sum(bool(case.result) for case in cases) == 1
    assert "allowed_change" in rendered
    assert "regression" in rendered
