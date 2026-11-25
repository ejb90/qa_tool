# Regression gates

Regression gates turn an existing QA Tool comparison into a versioned CI
policy. Every invocation emits standard JUnit XML, preserves the selected run
rows and evaluated policy in a comparison snapshot, and returns an exit code
that distinguishes a regression from an invalid invocation.

## Policy file

Policies use TOML and require schema version 1:

```toml
schema_version = 1

[gate]
unmatched_models = "fail"

[metrics.density]
direction = "increase"
absolute_tolerance = 0.02
percentage_tolerance = 1.0

[metrics.error]
direction = "either"
percentage_tolerance = 5.0
```

Each metric rule requires `direction` and at least one tolerance.

| Field | Meaning |
| --- | --- |
| `direction = "increase"` | Only a higher test mean is a regression. |
| `direction = "decrease"` | Only a lower test mean is a regression. |
| `direction = "either"` | A change in either direction is a regression. |
| `absolute_tolerance` | Allowed change in the metric's own units. |
| `percentage_tolerance` | Allowed change as a percentage of the absolute base mean. |

When both tolerances are present, the effective allowance is:

```text
max(absolute_tolerance, abs(base_mean) * percentage_tolerance / 100)
```

The exact boundary passes. For a zero base mean, percentage tolerance
contributes zero, so configure an absolute tolerance when movement away from
zero is acceptable. Tolerances must be finite and non-negative; unknown policy
fields are rejected.

By default, a model found on only one side becomes a failing JUnit case. Set
`unmatched_models = "ignore"` only when differing model coverage is expected.
The selected collections must still have at least one model in common.

## Commands

Gate two versions:

```bash
qa-tool check versions v1.0.0 v2.0.0 \
  --policy regression-policy.toml \
  --output regression.xml
```

Gate aggregate model groups:

```bash
qa-tool check models \
  --base h2 --base he \
  --test co2 --test ar \
  --policy regression-policy.toml \
  --output regression.xml
```

Gate collections selected by any run field:

```bash
qa-tool check collections \
  --field git_branch \
  --base main \
  --test candidate \
  --match exact \
  --policy regression-policy.toml \
  --output regression.xml
```

The collection command supports the same `exact`, `starts-with`, `contains`,
`regex`, and `non-empty` matching modes as `qa-tool compare collections`.

If `--output` is omitted, clean JUnit XML is written to standard output and
archive diagnostics are written to standard error. Output files are written
atomically and are not replaced unless `--force` is supplied. `--database`,
`--settings`, and `--archive-dir` use the same meanings as comparison commands.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The policy was evaluated and every case passed. |
| `1` | The policy was evaluated and at least one regression or coverage case failed. |
| `2` | The policy, command, database, selection, or output was invalid. |

Exit code 1 is an evaluated QA result, not a tool failure. Passing and failing
evaluations both create a snapshot before the command exits.

## JUnit report

The report contains one xUnit2 test case per model and metric. Failed policy
rules have a `<failure type="regression">` element. Test-case properties record
the base and test means, absolute and percentage changes, direction, configured
tolerances, effective allowed change, and evaluated regression change.

Unmatched models are represented by `model_coverage` failure cases. Invalid or
non-finite input does not produce a misleading JUnit result; it exits with code
2 instead.

## CI example

This GitHub Actions fragment retains the JUnit report and immutable comparison
snapshot even when the policy fails, then propagates the gate's exit code:

```yaml
- name: Run QA regression gate
  id: qa_gate
  shell: bash
  run: |
    set +e
    qa-tool check versions v1.0.0 v2.0.0 \
      --policy regression-policy.toml \
      --output qa-regression.xml \
      --archive-dir qa_tool_archive
    code=$?
    echo "code=$code" >> "$GITHUB_OUTPUT"
    exit 0

- name: Upload gate evidence
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: qa-regression-gate
    path: |
      qa-regression.xml
      qa_tool_archive/

- name: Enforce gate result
  if: always()
  shell: bash
  run: exit "${{ steps.qa_gate.outputs.code }}"
```

CI systems with native JUnit ingestion can publish `qa-regression.xml` as a
test report so each model and metric appears as an individual case.

## Preserved evidence

Gate snapshots add `gate-policy.toml` and `gate-results.xml` to the normal
comparison inputs, calculated data, standalone HTML report, manifest, and
checksums. The manifest records the aggregate status and failed cases, while
the HTML report shows the same gate summary. Use `qa-tool archive verify` to
verify the complete snapshot.

