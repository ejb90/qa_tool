# QA Tool: Remaining Review Work

This document records only the outstanding work from the project-wide review performed on 24 November 2026. It was reconciled against release `v0.6.1` on 26 November 2026; completed items have been removed.

## Priority 1: Product and operational correctness

### Make tagged publishing run the full release gate

- [ ] Reuse one validation workflow for pull requests and tagged releases.
  Define the release checks once in a reusable GitHub Actions workflow, then call that same workflow from branch/pull-request validation and from the tag-triggered publishing workflow. The tag path must not maintain a smaller, separate approximation of the checks used during development.

- [ ] Require tests, Ruff, formatting, strict documentation, build, and Twine validation before publishing.
  The release gate should run the supported Python test matrix, Ruff linting and formatting checks, `mkdocs build --strict`, distribution builds, and `twine check`. Each check must be a required dependency of publication so a failure or cancellation prevents the release from advancing.

- [ ] Install the built wheel in a clean environment and invoke its CLI entry point.
  Create an isolated environment that cannot import QA Tool from the repository checkout, install the wheel produced by the build job, and invoke commands such as `qa-tool --version` and `qa-tool --help`. This verifies that package contents, runtime dependencies, and the declared console-script entry point work as installed rather than only from the source tree.

- [ ] Prevent PyPI publication when any validation job fails.
  Make the PyPI job depend explicitly on every required validation result and consume only the already validated distribution artifacts. It must not rebuild a different package or use an unconditional execution path; GitHub environment approval, release creation, and trusted publishing should occur only after the complete gate succeeds.

Completion criterion: a manually pushed tag cannot publish code that has not passed the complete release suite.

## Priority 2: Production hardening

### Add batch ingestion and dry-run support

- [ ] Validate a collection of artifacts before committing any of them.
- [ ] Add a dry-run mode that reports inferred types, required-field failures, and UID conflicts without writing.
- [ ] Define batch failure semantics and produce a machine-readable result summary.
- [ ] Preserve the existing single-writer DuckDB constraint in documentation and tests.

Completion criterion: an automated pipeline can validate and ingest a batch atomically instead of relying on a shell loop with partial progress.

### Expand integration and security testing

- [ ] Add actual tests under the existing `integration` marker.
- [ ] Test the installed wheel and CLI through subprocesses rather than only in-process invocation.
- [ ] Add cache-refresh and concurrent-access tests.
- [ ] Increase coverage in artifact rendering, exports, summaries, and major Streamlit views.
- [ ] Keep security regression tests for pickle handling, archive traversal, root confinement, and resource limits.

Completion criterion: critical packaging and security paths are tested at their real process boundaries.

### Add static and supply-chain checks

- [ ] Add Pyright or mypy with an explicit strictness policy.
- [ ] Add dependency vulnerability and secret scanning.
- [ ] Configure automated dependency updates.
- [ ] Pin third-party GitHub Actions to reviewed commit SHAs.

Completion criterion: type regressions and known dependency or workflow risks are detected automatically in CI.

## Priority 3: Maintainability and documentation

### Improve internal code quality

- [ ] Replace non-informative docstrings such as `Handle ...` with useful contracts or remove them where a docstring adds no value.
- [ ] Consolidate duplicated collection-selection behavior between core and Streamlit code.
- [ ] Narrow broad `except Exception` handlers and log optional-feature failures with useful context.
- [ ] Continue moving reusable calculations out of Streamlit views and into `qa_tool.core`.

Completion criterion: shared behavior has one tested implementation, and operational failures are not silently hidden by broad exception handling.

### Complete operational documentation

- [ ] Add backup, restore, retention, and disaster-recovery guidance.
- [ ] Document artifact security and resource limits after they are implemented.
- [ ] Ensure release documentation accurately lists every enforced release check.
- [ ] Replace shock-bubble-specific packaged defaults with generic QA Tool defaults, leaving domain-specific values in examples.

Completion criterion: installation, operation, upgrade, recovery, and security expectations are documented without relying on project-specific knowledge.

## Priority 4: Container and Docker Swarm deployment

This section is intentionally deferred until the core release, data-management, testing, and documentation work above is complete.

### Reconcile the Swarm example with the deployment guide

- [ ] Change `swarm-compose.yml` to mount the parent snapshot directory rather than individual database and store paths.
- [ ] Supply a settings file through a Swarm config and point it at `/data/current/...`.
- [ ] Test atomic snapshot promotion and rollback using the documented layout.

Completion criterion: the supplied compose file implements the same atomic `current`-snapshot design described in the deployment documentation.

### Harden the container image and service

- [ ] Run the application as a non-root user.
- [ ] Add a container health check.
- [ ] Add documented CPU and memory limits to the deployment example.
- [ ] Consider a multi-stage build with a smaller runtime image.
- [ ] Add a Docker build and startup smoke test to CI.
- [ ] Add deployment tests covering the supplied container and Swarm configuration.

Completion criterion: the standard image runs without root privileges, reports health, and is exercised automatically before release.

