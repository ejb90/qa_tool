# Releases

QA Tool is published as [`qa-tool`](https://pypi.org/project/qa-tool/) on PyPI and documented at [Read the Docs](https://qa-tool.readthedocs.io/).

## Publishing prerequisites

Before the first release, configure the following services for the `ejb90/qa_tool` repository:

1. Create the `qa-tool` project on Read the Docs and connect the GitHub repository. Read the Docs reads the repository’s `.readthedocs.yaml` configuration and installs the `docs` optional dependency group.
2. When PyPI publishing is ready to be enabled, create the `qa-tool` project or pending trusted publisher for this repository’s `Publish` workflow, using the `pypi` environment.
3. Create a GitHub environment named `pypi`; protect it according to the project’s release policy.
4. Set the repository variable `PYPI_PUBLISH_ENABLED` to `true` only after the PyPI project and trusted publisher are ready. Publishing is deliberately disabled when this variable is absent or has any other value.
5. Optionally add `READTHEDOCS_API_KEY` as a repository secret. This asks Read the Docs to rebuild `latest` after a successful GitHub release.

## Release process

1. Update the version in `pyproject.toml`.
2. Run the release checks described in [Development](development.md).
3. Merge the version change to `main`.
4. The `Tag` workflow creates `vX.Y.Z` when no matching tag exists. A maintainer may instead push that tag manually.
5. The `Publish` workflow invokes the same reusable validation workflow as branch and pull-request checks. It creates a GitHub release containing the validated wheel and source distribution only after every validation job succeeds.
6. When `PYPI_PUBLISH_ENABLED=true`, the publish job also uploads those unchanged files to PyPI with Twine. Read the Docs is triggered after the GitHub release when configured, whether the optional PyPI job runs or is skipped.

Validation covers Ruff linting and formatting, the supported Python test matrix,
strict MkDocs, package build and Twine metadata checks, and a clean-environment
installation of the built wheel followed by CLI entry-point invocations. PyPI
publishing, when enabled, uses Twine with OpenID Connect trusted publishing,
following the working release strategy used by module-manager; no long-lived
PyPI token is stored in GitHub.

## Manual verification

After publishing, verify the installed commands in a clean environment:

```bash
uv tool install qa-tool
qa-tool --help
qa-tool ingest --help
qa-tool doctor --help
qa-tool serve --help
qa-tool report --help
```
