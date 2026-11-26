# QA Tool: Remaining Review Work

This document records only the outstanding work from the project-wide review performed on 24 November 2026. It was reconciled against release `v0.6.0` on 25 November 2026; completed items have been removed.

## Priority 1: Product and operational correctness

### Make tagged publishing run the full release gate

- [ ] Reuse one validation workflow for pull requests and tagged releases.
- [ ] Require tests, Ruff, formatting, strict documentation, build, and Twine validation before publishing.
- [ ] Install the built wheel in a clean environment and invoke its CLI entry point.
- [ ] Prevent PyPI publication when any validation job fails.

Completion criterion: a manually pushed tag cannot publish code that has not passed the complete release suite.

## Priority 2: Production hardening

### Add database inspection and migration tooling

- [ ] Add a `qa-tool doctor` command to report missing required fields, duplicate UIDs, invalid dates, incompatible types, and stale summaries.
  The command should be read-only by default, inspect an existing database against the active ingestion and dashboard settings, print actionable human-readable findings, and offer a machine-readable result with a non-zero status for automation.

- [ ] Define a database schema/version marker.
  Store an explicit QA Tool data-schema version in the database, separate from the package version, so commands can identify legacy, current, and unsupported future databases before querying or changing them.

- [ ] Document supported migrations and compatibility guarantees.
  State which schema versions each QA Tool release can read and write, whether direct or sequential upgrades are supported, what operators must back up first, and what downgrade or rollback behavior they can rely on.

- [ ] Provide safe repair or migration commands where automation is unambiguous.
  Repairs should cover deterministic operations such as rebuilding stale summaries or applying a defined schema migration. They should support a preview, run transactionally, avoid guessing how ambiguous data should be changed, and leave the original database recoverable if validation fails.

Completion criterion: existing databases can be assessed before upgrade without discovering incompatibilities only when the dashboard starts.

### Add batch ingestion and dry-run support

- [ ] Validate a collection of artifacts before committing any of them.
- [ ] Add a dry-run mode that reports inferred types, required-field failures, and UID conflicts without writing.
- [ ] Define batch failure semantics and produce a machine-readable result summary.
- [ ] Preserve the existing single-writer DuckDB constraint in documentation and tests.

Completion criterion: an automated pipeline can validate and ingest a batch atomically instead of relying on a shell loop with partial progress.

### Expand integration and security testing

- [ ] Add actual tests under the existing `integration` marker.
- [ ] Test the installed wheel and CLI through subprocesses rather than only in-process invocation.
- [ ] Add cache-refresh, concurrent-access, and migration tests.
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
- [ ] Document schema migration and compatibility policy.
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

