# QA Tool: Remaining Review Work

This document records only the outstanding work from the project-wide review performed on 24 November 2026. It was reconciled against release `v0.6.0` on 25 November 2026; completed items have been removed.

## Priority 1: Product and operational correctness

### Reconcile the Swarm example with the deployment guide

- [ ] Change `swarm-compose.yml` to mount the parent snapshot directory rather than individual database and store paths.
- [ ] Supply a settings file through a Swarm config and point it at `/data/current/...`.
- [ ] Test atomic snapshot promotion and rollback using the documented layout.

Completion criterion: the supplied compose file implements the same atomic `current`-snapshot design described in the deployment documentation.

### Make tagged publishing run the full release gate

- [ ] Reuse one validation workflow for pull requests and tagged releases.
- [ ] Require tests, Ruff, formatting, strict documentation, build, and Twine validation before publishing.
- [ ] Install the built wheel in a clean environment and invoke its CLI entry point.
- [ ] Prevent PyPI publication when any validation job fails.

Completion criterion: a manually pushed tag cannot publish code that has not passed the complete release suite.

## Priority 2: Production hardening

### Harden the container image and service

- [ ] Run the application as a non-root user.
- [ ] Add a container health check.
- [ ] Add documented CPU and memory limits to the deployment example.
- [ ] Consider a multi-stage build with a smaller runtime image.
- [ ] Add a Docker build and startup smoke test to CI.

Completion criterion: the standard image runs without root privileges, reports health, and is exercised automatically before release.

### Define the authentication and deployment trust model

- [ ] State explicitly whether QA Tool is intended only for trusted local/internal networks.
- [ ] Document reverse-proxy authentication and TLS requirements for shared deployments.
- [ ] Review which database fields, file paths, logs, and artifacts are exposed to authenticated users.
- [ ] Decide whether authorization belongs in QA Tool or remains an external proxy responsibility.

Completion criterion: an operator can determine from the documentation whether a proposed deployment is safe and what access controls it requires.

### Add database inspection and migration tooling

- [ ] Add a `qa-tool doctor` command to report missing required fields, duplicate UIDs, invalid dates, incompatible types, and stale summaries.
- [ ] Define a database schema/version marker.
- [ ] Document supported migrations and compatibility guarantees.
- [ ] Provide safe repair or migration commands where automation is unambiguous.

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
- [ ] Add cache-refresh, concurrent-access, migration, and deployment tests.
- [ ] Increase coverage in artifact rendering, exports, summaries, and major Streamlit views.
- [ ] Keep security regression tests for pickle handling, archive traversal, root confinement, and resource limits.

Completion criterion: critical packaging, deployment, and security paths are tested at their real process or container boundaries.

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

