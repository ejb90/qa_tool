# Machine-Readable Regression Gate Proposal

Status: implemented on `codex/regression-gate`; pending merge and release.

## Objective

Add a policy-driven regression gate that compares two run collections, produces
human- and machine-readable results, preserves the complete evaluation in a
comparison snapshot, and returns a stable exit code suitable for CI.

The gate should be a separate policy-evaluation layer built on the existing
long-form comparison data. It must produce its result and archive before
returning a CI-significant exit code.

## Proposed policy contract

Example policy:

```toml
schema_version = 1

[gate]
unmatched_models = "fail" # "fail" or "ignore"

[metrics.density]
direction = "increase" # "increase", "decrease", or "either"
absolute_tolerance = 0.02
percentage_tolerance = 1.0

[metrics.error]
direction = "increase"
percentage_tolerance = 5.0
```

For each shared model and configured metric, the evaluator should:

1. Calculate `test_mean - base_mean`.
2. Apply the configured regression direction.
3. Convert the percentage tolerance relative to `abs(base_mean)`.
4. When both tolerances exist, use the larger permitted change:
   `max(absolute_tolerance, abs(base_mean) * percentage_tolerance / 100)`.
5. Fail the result when its directional regression exceeds the permitted
   change.

The policy loader should reject unknown metrics, invalid directions,
negative or non-finite tolerances, unknown fields, and metric rules that do
not define a tolerance.

## Exit-code contract

| Exit code | Meaning |
| --- | --- |
| `0` | Every evaluated policy rule passed. |
| `1` | The comparison completed, but one or more policy rules failed. |
| `2` | The policy, input data, database, or command invocation was invalid. |

A regression is therefore a successful evaluation with exit code `1`, not an
execution error. A failed gate must still leave complete output and an audit
snapshot.

## Implementation plan

### 1. Add a strict policy and evaluation layer

Create `qa_tool/core/gates.py` containing immutable policy and result models
plus pure functions for:

- Loading and validating policy TOML.
- Evaluating the existing long-form output from
  `build_collection_metric_deltas`.
- Handling `increase`, `decrease`, and `either` rules.
- Detecting unmatched models and missing metrics.
- Producing one normalized result row per model and metric.
- Calculating the overall `passed`, `failed`, or `error` status.

Keep this layer independent of Click, Rich, archives, and Streamlit so its
behavior can be tested directly.

### 2. Add the CLI command group

Add these commands:

```text
qa-tool check versions BASE TEST --policy POLICY.toml
qa-tool check collections --field FIELD --base VALUE --test VALUE --policy POLICY.toml
qa-tool check models --base MODEL --test MODEL --policy POLICY.toml
```

Common options:

```text
--output PATH
--force
--archive-dir PATH
--database PATH
--settings PATH
```

The policy determines which metrics are loaded, so a separate `--metric`
option is unnecessary. Refactor the existing comparison commands so
`compare` and `check` share collection selection and comparison construction
rather than duplicating it.

### 3. Define stable JUnit output

The command should emit standard JUnit XML, with no separate JSON output
format. JUnit output should contain:

- One test suite for the complete gate.
- One test case per model and metric evaluation.
- A `<failure>` element for each policy regression.
- Properties for means, deltas, and thresholds.
- Stable test names suitable for CI interfaces.

Use `junitparser` version 5 to construct the xUnit2 document rather than
assembling XML manually:

```toml
dependencies = [
    # Existing dependencies...
    "junitparser>=5.0.3,<6",
]
```

`junitparser` can create suites and cases from scratch, attach failures and
properties, escape values, and write to files or file-like objects. Version 5
supports Python 3.10 and later, which is compatible with QA Tool's Python 3.11
minimum. The renderer should use its xUnit2 `TestSuite` and `TestCase` models,
with one case per model and metric and a `Failure` result for a policy
regression.

Do not use pytest's built-in JUnit writer for this output. That writer is tied
to executing pytest tests, whereas gate evaluations are QA Tool domain results;
pytest also documents compatibility limitations for some custom properties.
The standard library's `xml.etree.ElementTree` would work, but would require QA
Tool to own more schema, escaping, and serialization behavior.

Tests should parse generated reports back through `junitparser`, verify the
suite and case counts, failures, and properties, and retain a small expected
xUnit2 structure test for CI compatibility.

JUnit XML must be clean on standard output when `--output` is omitted, with
diagnostics written to standard error. `--output` should write atomically and
should refuse to replace a file unless `--force` is supplied.

### 4. Extend comparison snapshots

Extend `qa_tool/core/archive.py` so gate-created snapshots include:

```text
gate-policy.toml
gate-results.xml
```

The archive changes should:

- Increment the archive schema version.
- Add gate status and result counts to `manifest.json`.
- Add both gate files to the manifest inventory and checksums.
- Include a pass/fail summary and failed rules in `report.html`.
- Write the snapshot before returning exit code `1`.
- Preserve compatibility with existing ordinary comparison archives.

### 5. Add comprehensive tests

Core tests should cover:

- Absolute-only, percentage-only, and combined thresholds.
- Increase, decrease, and either-direction rules.
- Negative and zero baselines.
- Exact-boundary behavior.
- NaN and missing metric values.
- Unmatched-model `fail` and `ignore` modes.
- Invalid, incomplete, and unknown policy fields.
- Stable JUnit serialization.

CLI and archive tests should verify:

- Exit codes `0`, `1`, and `2`.
- Valid JUnit XML.
- Atomic `--output` writes.
- A failing gate still creates a complete, verifiable snapshot.
- Snapshot manifests, checksums, gate files, and HTML reports contain the
  evaluation.
- Existing `compare` commands remain unchanged.

### 6. Document CI usage

Add a dedicated regression-gate documentation page and update the CLI,
configuration, and comparison-archive documentation with:

- The complete policy reference.
- Threshold-combination and direction semantics.
- The exit-code contract.
- JUnit examples.
- A GitHub Actions example that uploads the snapshot and JUnit report even
  when the gate fails.
- Guidance for selecting tolerances and handling unmatched models.

### 7. Complete and release

Once implementation, tests, and documentation pass:

- Remove the completed task from `PROJECT_REVIEW.md`.
- Run Ruff, formatting, all tests, strict MkDocs, package build, and Twine
  validation.
- Treat the change as a minor feature release, likely version `0.5.0`.
- Tag and push using the established atomic release process.

## Completion criteria

The task is complete when a CI job can:

1. Select two run collections.
2. Evaluate them against a versioned policy.
3. Publish clean JUnit XML output.
4. Preserve the policy, inputs, calculations, and result in a verifiable
   comparison snapshot.
5. Exit with `1` solely because a configured QA regression exceeded policy.

