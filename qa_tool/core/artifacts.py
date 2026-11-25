"""Security boundaries and resource limits for local run artifacts."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactLimits:
    """Bound filesystem traversal, archive expansion, and artifact rendering."""

    max_archive_members: int = 1_000
    max_expanded_bytes: int = 512 * 1024 * 1024
    max_file_bytes: int = 128 * 1024 * 1024
    max_recursive_files: int = 1_000
    max_render_rows: int = 10_000
    max_plot_points: int = 10_000

    @classmethod
    def from_mapping(cls, configured: Mapping[str, Any] | None = None) -> ArtifactLimits:
        """Build validated limits from a settings mapping."""
        configured = configured or {}
        known = {field.name for field in fields(cls)}
        values = {key: value for key, value in configured.items() if key in known}
        limits = cls(**values)
        for field in fields(limits):
            value = getattr(limits, field.name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"Artifact limit {field.name} must be a positive integer")
        return limits


def artifact_root_path(artifact_root: str | Path) -> Path | None:
    """Return the canonical approved artifact root, if one is configured."""
    if not artifact_root:
        return None
    return Path(artifact_root).expanduser().resolve()


def path_within_root(path: Path, root: Path) -> bool:
    """Return whether a path resolves to the root or one of its descendants."""
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def local_artifact_candidates(record: Mapping[str, Any], artifact_root: str | Path) -> list[Path]:
    """Resolve safe database-derived paths beneath the configured artifact root.

    No local candidates are returned without an approved root. Absolute artifact
    paths are accepted only when their canonical target remains inside that root.
    """
    root = artifact_root_path(artifact_root)
    if root is None:
        return []

    raw_candidates: list[Path] = []
    artifact = record.get("artifact")
    if isinstance(artifact, str) and artifact and not artifact.startswith("s3://"):
        artifact_path = Path(artifact).expanduser()
        if artifact_path.is_absolute():
            raw_candidates.append(artifact_path)
        else:
            # Preserve commonly stored paths such as ``store/run-id`` while
            # also supporting paths relative to the configured root.
            raw_candidates.extend([artifact_path, root / artifact_path])
    for key in ("uid", "name"):
        value = record.get(key)
        if value is not None and str(value):
            raw_candidates.append(root / str(value))

    safe_candidates: list[Path] = []
    for candidate in raw_candidates:
        resolved = candidate.resolve()
        if path_within_root(resolved, root) and resolved not in safe_candidates:
            safe_candidates.append(resolved)
    return safe_candidates


def remote_artifact_location(record: Mapping[str, Any]) -> str | None:
    """Return an object-store location without treating it as a local path."""
    artifact = record.get("artifact")
    if isinstance(artifact, str) and artifact.startswith("s3://"):
        return artifact
    return None


def check_artifact_file(path: Path, root: Path, limits: ArtifactLimits) -> Path:
    """Validate that a regular file is confined to the root and within limits."""
    if path.is_symlink():
        raise ValueError(f"Artifact symlinks are not allowed: {path}")
    resolved = path.resolve()
    if not path_within_root(resolved, root):
        raise ValueError(f"Artifact path escapes the configured root: {path}")
    if not resolved.is_file():
        raise ValueError(f"Artifact is not a regular file: {path}")
    size = resolved.stat().st_size
    if size > limits.max_file_bytes:
        raise ValueError(f"Artifact file exceeds max_file_bytes ({size} > {limits.max_file_bytes}): {path}")
    return resolved


def iter_artifact_files(path: Path, limits: ArtifactLimits) -> Iterator[Path]:
    """Yield confined regular files without following links or exceeding budgets."""
    root = path.resolve()
    if path.is_symlink():
        raise ValueError(f"Artifact symlinks are not allowed: {path}")
    if root.is_file():
        yield check_artifact_file(root, root.parent, limits)
        return
    if not root.is_dir():
        return

    count = 0
    for current, directories, files_in_directory in os.walk(root, followlinks=False):
        current_path = Path(current)
        symlinked_directories = [name for name in directories if (current_path / name).is_symlink()]
        if symlinked_directories:
            raise ValueError(f"Artifact directory contains a symlink: {current_path / symlinked_directories[0]}")
        directories.sort()
        files_in_directory.sort()
        for name in files_in_directory:
            count += 1
            if count > limits.max_recursive_files:
                raise ValueError(
                    f"Artifact directory exceeds max_recursive_files ({limits.max_recursive_files}): {root}"
                )
            yield check_artifact_file(current_path / name, root, limits)
