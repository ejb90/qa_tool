# Comparison archives

Every non-terse CLI comparison produces a durable snapshot. The web app can create the same snapshot from **Compare Versions**, **Compare Collection**, and **Compare Run** by opening the collapsed **Preserve this comparison** section. Both interfaces write new snapshots to `[archive].save_path` and discover existing snapshots across `[archive].search_paths`.

A snapshot records the selected inputs as well as the calculated answer. It can therefore be inspected after the live DuckDB database changes or disappears.

## Snapshot contents

Each comparison is written atomically to a uniquely named directory:

```text
qa_tool_archive/
└── 20261121T143022Z_versions_v1.0.0_to_v2.0.0_a8c41f92de10/
    ├── manifest.json
    ├── runs.parquet
    ├── comparison.csv
    ├── comparison.parquet
    ├── report.html
    ├── checksums.sha256
    ├── gate-policy.toml           # Gate snapshots only
    ├── gate-results.xml           # Gate snapshots only
    └── artifacts/                 # Present when local run artifacts were captured
```

| File | Purpose |
| --- | --- |
| `manifest.json` | Snapshot ID, UTC creation time, creating OS user, schema and QA Tool versions, comparison type, labels, run UIDs, metrics, selection parameters, and file inventory. |
| `runs.parquet` | Complete database rows used as the base and test inputs. `comparison_role` identifies the side. |
| `comparison.csv` | Portable calculated result table. |
| `comparison.parquet` | Typed calculated result table for exact programmatic reuse. |
| `report.html` | Standalone human-readable report with Plotly embedded; it does not require a network connection or the live database. |
| `checksums.sha256` | SHA-256 digest for every recorded file, including captured artifacts. |
| `gate-policy.toml` | Exact policy evaluated by a `qa-tool check` command; present only for gate snapshots. |
| `gate-results.xml` | Standard JUnit XML produced by the gate; present only for gate snapshots. |

Aggregate version, model, and collection comparisons are fully reproducible from their recorded run rows. A run-to-run snapshot created by either interface also copies each resolved local artifact directory. Remote object-store artifacts are not downloaded automatically; their original reference remains in the recorded run row.

Gate snapshots use archive schema version 3. Their manifest also records the
gate status, pass/failure counts, and concise failure descriptions. Existing
comparison snapshots remain readable and verifiable.

## Create snapshots from the CLI

Comparison snapshots are the standard CLI comparison output:

```bash
qa-tool compare versions v1.0.0 v2.0.0
qa-tool compare models --base h2 --test co2
qa-tool compare collections --field git_branch --base main --test release
qa-tool compare runs run-001 run-002
```

Use `--archive-dir` to choose another store and `--metric` to restrict the recorded calculation:

```bash
qa-tool compare versions v1.0.0 v2.0.0 \
  --metric density \
  --archive-dir /shared/qa/comparisons
```

`compare collections --terse` is the deliberate exception: it prints an ephemeral compact table and does not save a snapshot.

??? example "Example: preserve and hand off a release comparison"

    Create a snapshot in a shared archive, copy its printed ID, and verify it before handing the result to another user:

    ```bash
    qa-tool compare versions v1.8.0 v1.9.0 \
      --metric density \
      --archive-dir /shared/qa/comparisons

    qa-tool archive verify SNAPSHOT_ID \
      --archive-dir /shared/qa/comparisons
    ```

    The recipient can open the corresponding **Saved Comparisons** entry in the web app or recover the self-contained report without access to the original DuckDB database:

    ```bash
    qa-tool archive export SNAPSHOT_ID \
      --archive-dir /shared/qa/comparisons \
      --output v1.8.0-to-v1.9.0.html
    ```

## Find, verify, and recover snapshots

```bash
qa-tool archive list
qa-tool archive show a8c41f
qa-tool archive verify a8c41f
qa-tool archive export a8c41f --output recovered-report.html
```

Snapshot IDs may be shortened to any unique leading prefix. `verify` recalculates every digest and fails if a recorded file is missing or changed. `export` copies the stored standalone report and refuses to replace an existing file unless `--force` is supplied.

The web app's **Saved Comparisons** tab provides the same discovery, verification, result-table, input-row, and ZIP-download workflow. Its URL includes the selected snapshot ID, so a hosted comparison can be shared directly:

```text
https://qa.example.org/?view=saved_comparisons&comparison=a8c41f92de10
```

Opening the link selects the Saved Comparisons tab and snapshot automatically. A shorter link containing only `?comparison=...` is also accepted. The recipient still needs access to the hosted application, and that application must be able to read the snapshot from one of its configured `search_paths`; the URL does not contain the archived data. Manifest details and recorded input rows are collapsed by default so routine recovery remains uncluttered.

??? tip "What to inspect when a verification fails"

    Run `qa-tool archive show SNAPSHOT_ID` to confirm the expected archive and source labels, then rerun `verify` against each configured archive root. A missing file usually indicates an incomplete copy; a checksum mismatch means a recorded file changed after the snapshot was created. Restore the whole snapshot directory from an authoritative backup rather than replacing individual files.

The archive locations are deliberately asymmetric:

```toml
[archive]
save_path = "./qa_tool_archive"
search_paths = ["./qa_tool_archive", "/shared/qa/comparisons"]
```

Only `save_path` receives new comparisons. Saved Comparisons merges every readable `search_paths` entry, using their configured order when the same snapshot has been copied to multiple locations. CLI `archive` commands use the same list when given `--settings`; repeat `--archive-dir` to override it for one invocation.

The `created_by` field comes from `getpass.getuser()`, which uses the account running the CLI or web process (`$LOGNAME`, `$USER`, `$LNAME`, or `$USERNAME`, with an operating-system account lookup fallback). For a shared deployed web service this will normally be the service account, because the operating system does not expose the browser user's identity to Streamlit.

## Operational guidance

- Back up every archive location that holds an authoritative copy. DuckDB backups alone do not include comparison history.
- Treat snapshot directories as append-only. Editing is possible at the filesystem level, but checksum verification will expose the change.
- Use a shared writable archive path when CLI and web-app users need to see the same records.
- Account for artifact size when preserving individual runs. Files from the resolved local artifact directory are copied only within the configured artifact file-count, individual-size, and total-size limits; links are rejected.
- Keep `manifest.json` and `checksums.sha256` with the data files when transferring a snapshot. The web ZIP download does this automatically.

!!! warning "Archive writes"

    The web process needs write access to `[archive].save_path` and read access to each `[archive].search_paths` entry. In Docker or another container runtime, mount those paths on persistent storage; otherwise local snapshots disappear with the container.
