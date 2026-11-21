# Releases

QA Tool is published as [`qa-tool`](https://pypi.org/project/qa-tool/) on PyPI and documented at [Read the Docs](https://qa-tool.readthedocs.io/).

## Publishing prerequisites

Before the first release, configure the following services for the `ejb90/qa_tool` repository:

1. Create the `qa-tool` project on Read the Docs and connect the GitHub repository. Read the Docs reads the repository’s `.readthedocs.yaml` configuration and installs the `docs` optional dependency group.
2. Create a PyPI trusted publisher for this repository’s `Publish` GitHub Actions workflow, using the `pypi` environment.
3. Create a GitHub environment named `pypi`; protect it according to the project’s release policy.
4. Optionally add `READTHEDOCS_API_KEY` as a repository secret. This asks Read the Docs to rebuild `latest` after a successful PyPI release.

## Release process

1. Update the version in `pyproject.toml`.
2. Run the release checks described in [Development](development.md).
3. Merge the version change to `main`.
4. The `Tag` workflow creates `vX.Y.Z` when no matching tag exists. A maintainer may instead push that tag manually.
5. The `Publish` workflow confirms the tag matches the project version, creates a GitHub release, uploads the built wheel and source distribution to PyPI, then triggers Read the Docs when configured.

PyPI publishing uses OpenID Connect trusted publishing: no long-lived PyPI token is stored in GitHub.

## Manual verification

After publishing, verify the installed commands in a clean environment:

```bash
uv tool install qa-tool
qa-tool --help
qa-tool ingest --help
qa-tool serve --help
qa-tool report --help
```
