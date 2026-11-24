# Docker Swarm deployment and data refresh

This workflow deploys the dashboard as a single read-only Docker Swarm service
while new runs are added every few minutes. It assumes the authoritative data
is kept in object storage and that each new run creates one new row in the
DuckDB database and an associated artifact directory.

## Roles

| Role | Responsibility | Write access |
| --- | --- | --- |
| Ingestion job | Adds the new run to DuckDB and publishes a complete snapshot. | Database and object store |
| Synchronizer | Downloads and validates the published snapshot on the Swarm data node. | Local staging area |
| Dashboard service | Serves the currently promoted snapshot. | None |

Only the ingestion job writes DuckDB. The dashboard mounts the database and
artifacts read-only.

## Storage layout

Publish immutable snapshots rather than overwriting a database object that the
dashboard might be reading:

```text
object store
└── qa-tool/
    ├── snapshots/
    │   ├── 2026-07-15T12-00-00Z/
    │   │   ├── runs.duckdb
    │   │   └── store/
    │   └── 2026-07-15T12-03-00Z/
    │       ├── runs.duckdb
    │       └── store/
    └── latest.json
```

`latest.json` is a small manifest identifying the newest complete snapshot,
for example:

```json
{
  "snapshot": "2026-07-15T12-03-00Z",
  "database_sha256": "..."
}
```

Upload the database, newly created artifacts, and checksums first. Upload or
replace `latest.json` last. That makes the manifest the publish point: a
synchronizer never sees an incomplete snapshot.

## Per-run workflow

1. A run finishes and its artifact files are uploaded or otherwise made
   available to the ingestion job.
2. A scheduled ingestion job runs as the only DuckDB writer. It adds the run's
   metadata as one new row and rebuilds any required summary data.
3. The job produces a new immutable snapshot containing the resulting
   `runs.duckdb` and all artifacts needed by that database version.
4. The job verifies the upload, then updates `latest.json` to point to the new
   snapshot.
5. A synchronizer on the labelled Swarm data node polls `latest.json` every
   minute (or is triggered by the ingestion job). If the snapshot is new, it
   downloads it to a local staging directory such as
   `/srv/qa-tool/releases/<snapshot>/`.
6. The synchronizer verifies the checksum and opens the staged database in
   read-only mode for a basic validation query. It must not modify the current
   release in place.
7. The synchronizer atomically changes
   `/srv/qa-tool/current` to point at the new release. The dashboard receives
   only complete database/artifact pairs.
8. The next dashboard interaction resolves the promoted `current` pointer and
   uses the new file identity as its cache key. A configurable cache TTL
   (60 seconds by default) provides a bounded-staleness fallback, and the
   **Refresh database** control forces an immediate scoped reload. No service
   restart is required.

## Swarm mount arrangement

Mount the parent directory, not an individual `runs.duckdb` file. This allows
the `current` pointer to change without replacing a bind-mounted file:

```yaml
volumes:
  - type: bind
    source: /srv/qa-tool
    target: /data
    read_only: true
```

Configure the dashboard to use these paths:

```toml
[database]
path = "/data/current/runs.duckdb"
artifact_root = "/data/current/store"
```

Provide that TOML file to the service using a Docker Swarm config and set
`QA_TOOL_SETTINGS` to its in-container path. Keep the service at one replica
unless the data-storage and refresh design has been tested for multiple
readers. The ingestion job is separate and has its own read-write working
area; it must never write through the dashboard's read-only mount.

## Operations

- Retain several prior snapshots so the `current` pointer can be rolled back.
- Record the snapshot identifier in service logs or a health page to make the
  displayed data version observable.
- Alert if the latest manifest is newer than the promoted local snapshot by
  more than the expected refresh interval.
- Run the synchronizer from an external scheduler or CI system. Docker Swarm
  does not provide a built-in cron scheduler.
