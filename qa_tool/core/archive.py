"""Durable, self-contained archives for QA comparisons."""

from __future__ import annotations

import getpass
import hashlib
import html
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import plotly.express as px
import plotly.io as pio

ARCHIVE_SCHEMA_VERSION = 3


@dataclass(frozen=True)
class ComparisonArchive:
    """A comparison archive written to disk."""

    snapshot_id: str
    path: Path
    manifest: dict[str, Any]


def _safe_name(value: str) -> str:
    """Return a short filesystem-safe name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "comparison"


def _package_version() -> str:
    """Return the installed package version, including editable checkouts."""
    try:
        return version("qa-tool")
    except PackageNotFoundError:
        return "unknown"


def _uid_values(runs: pd.DataFrame) -> list[str]:
    """Return stable run identifiers when the input provides them."""
    if "uid" not in runs:
        return []
    return runs["uid"].dropna().astype(str).tolist()


def local_artifact_paths(runs: pd.DataFrame, artifact_root: str | Path = "") -> dict[str, Path]:
    """Resolve the first existing local artifact path for each recorded run."""
    resolved = {}
    root = Path(artifact_root) if artifact_root else None
    for _, run in runs.iterrows():
        uid = str(run.get("uid", ""))
        candidates = []
        artifact = run.get("artifact")
        if isinstance(artifact, str) and artifact and not artifact.startswith("s3://"):
            candidates.append(Path(artifact))
        if root is not None:
            candidates.extend([root / uid, root / str(run.get("name", uid))])
        if path := next((candidate for candidate in candidates if candidate.exists()), None):
            resolved[uid] = path
    return resolved


def _sha256(path: Path) -> str:
    """Calculate a file's SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _report_html(manifest: dict[str, Any], comparison: pd.DataFrame, runs: pd.DataFrame) -> str:
    """Build a standalone, dependency-free HTML report."""
    title = html.escape(
        f"{manifest['comparison_type'].replace('_', ' ').title()}: {manifest['test_label']} vs {manifest['base_label']}"
    )
    metadata = pd.DataFrame(
        [
            ("Snapshot ID", manifest["snapshot_id"]),
            ("Created", manifest["created_at"]),
            ("Created by", manifest["created_by"]),
            ("QA Tool version", manifest["qa_tool_version"]),
            ("Base", manifest["base_label"]),
            ("Test", manifest["test_label"]),
            ("Metrics", ", ".join(manifest["metrics"])),
        ],
        columns=["Item", "Value"],
    )
    styles = """
body { font-family: system-ui, sans-serif; margin: 2rem; color: #202124; }
h1, h2 { margin-top: 1.5rem; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { border: 1px solid #d8dce2; padding: 0.4rem 0.55rem; text-align: left; }
th { background: #f2f4f7; position: sticky; top: 0; }
.scroll { overflow-x: auto; }
code { background: #f2f4f7; padding: 0.1rem 0.25rem; }
""".strip()
    figures = []
    if {"model", "metric", "percent_difference"}.issubset(comparison.columns):
        for metric in comparison["metric"].dropna().unique():
            data = comparison[comparison["metric"] == metric]
            figures.append(
                px.bar(
                    data,
                    x="model",
                    y="percent_difference",
                    error_y="percent_uncertainty" if "percent_uncertainty" in data else None,
                    title=f"{metric}: test minus base (%)",
                )
            )
    elif {"metric", "percent_difference"}.issubset(comparison.columns):
        figures.append(px.bar(comparison, x="metric", y="percent_difference", title="Test minus base (%)"))
    elif {"metric", "bottom_minus_top"}.issubset(comparison.columns):
        figures.append(px.bar(comparison, x="metric", y="bottom_minus_top", title="Bottom minus top"))
    plot_html = "".join(
        pio.to_html(figure, full_html=False, include_plotlyjs=index == 0) for index, figure in enumerate(figures)
    )
    plot_section = f"<h2>Plots</h2>{plot_html}" if plot_html else ""
    gate = manifest.get("gate")
    gate_section = ""
    if isinstance(gate, dict):
        failures = gate.get("failures", [])
        failure_items = "".join(f"<li>{html.escape(str(failure))}</li>" for failure in failures)
        failure_list = f"<ul>{failure_items}</ul>" if failure_items else "<p>No policy failures.</p>"
        gate_section = (
            "<h2>Regression gate</h2>"
            f"<p><strong>Status:</strong> {html.escape(str(gate.get('status', 'unknown')).upper())}; "
            f"passed: {html.escape(str(gate.get('passed', 0)))}; "
            f"failed: {html.escape(str(gate.get('failed', 0)))}</p>"
            f"{failure_list}"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title>"
        f"<style>{styles}</style></head><body><h1>{title}</h1>"
        "<p>This report is rendered from an immutable QA Tool comparison snapshot.</p>"
        f"<div class='scroll'>{metadata.to_html(index=False, escape=True)}</div>"
        f"{gate_section}"
        f"{plot_section}"
        f"<h2>Comparison</h2><div class='scroll'>{comparison.to_html(index=False, escape=True)}</div>"
        f"<h2>Recorded runs</h2><div class='scroll'>{runs.to_html(index=False, escape=True)}</div>"
        "</body></html>"
    )


def create_comparison_archive(
    archive_root: str | Path,
    *,
    comparison_type: str,
    base_label: str,
    test_label: str,
    base_runs: pd.DataFrame,
    test_runs: pd.DataFrame,
    comparison: pd.DataFrame,
    metrics: list[str],
    parameters: dict[str, Any] | None = None,
    artifact_paths: dict[str, Path] | None = None,
    gate_policy_text: str | None = None,
    gate_results_xml: str | None = None,
    gate_summary: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> ComparisonArchive:
    """Atomically write an immutable comparison archive and return its identity."""
    gate_values = (gate_policy_text, gate_results_xml, gate_summary)
    if any(value is not None for value in gate_values) and not all(value is not None for value in gate_values):
        raise ValueError("Gate archives require policy text, JUnit results, and a summary")
    timestamp = (created_at or datetime.now(UTC)).astimezone(UTC)
    snapshot_id = uuid4().hex[:12]
    root = Path(archive_root)
    root.mkdir(parents=True, exist_ok=True)
    directory_name = (
        f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}_{_safe_name(comparison_type)}_"
        f"{_safe_name(base_label)}_to_{_safe_name(test_label)}_{snapshot_id}"
    )
    destination = root / directory_name
    temporary = Path(tempfile.mkdtemp(prefix=".qa-tool-archive-", dir=root))

    recorded_base = base_runs.copy()
    recorded_base.insert(0, "comparison_role", "base")
    recorded_test = test_runs.copy()
    recorded_test.insert(0, "comparison_role", "test")
    recorded_runs = pd.concat([recorded_base, recorded_test], ignore_index=True)
    manifest: dict[str, Any] = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": timestamp.isoformat().replace("+00:00", "Z"),
        "created_by": getpass.getuser(),
        "qa_tool_version": _package_version(),
        "comparison_type": comparison_type,
        "base_label": str(base_label),
        "test_label": str(test_label),
        "base_run_uids": _uid_values(base_runs),
        "test_run_uids": _uid_values(test_runs),
        "metrics": list(metrics),
        "parameters": parameters or {},
        "artifacts": [],
        "files": {
            "runs": "runs.parquet",
            "comparison_csv": "comparison.csv",
            "comparison_parquet": "comparison.parquet",
            "report": "report.html",
            "checksums": "checksums.sha256",
        },
    }
    if gate_summary is not None:
        manifest["gate"] = gate_summary
        manifest["files"].update(
            {
                "gate_policy": "gate-policy.toml",
                "gate_results": "gate-results.xml",
            }
        )

    try:
        for run_uid, source in sorted((artifact_paths or {}).items()):
            source = Path(source)
            if not source.exists():
                continue
            relative_destination = Path("artifacts") / _safe_name(run_uid)
            artifact_destination = temporary / relative_destination
            if source.is_dir():
                shutil.copytree(source, artifact_destination)
            else:
                artifact_destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, artifact_destination / source.name)
            manifest["artifacts"].append(
                {"run_uid": str(run_uid), "source": str(source), "path": relative_destination.as_posix()}
            )
        recorded_runs.to_parquet(temporary / "runs.parquet", index=False)
        comparison.to_csv(temporary / "comparison.csv", index=False)
        comparison.to_parquet(temporary / "comparison.parquet", index=False)
        if gate_policy_text is not None and gate_results_xml is not None:
            (temporary / "gate-policy.toml").write_text(gate_policy_text, encoding="utf-8")
            (temporary / "gate-results.xml").write_text(gate_results_xml, encoding="utf-8")
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        (temporary / "report.html").write_text(
            _report_html(manifest, comparison, recorded_runs),
            encoding="utf-8",
        )
        checksummed_files = sorted(
            path.relative_to(temporary).as_posix()
            for path in temporary.rglob("*")
            if path.is_file() and path.name != "checksums.sha256"
        )
        checksum_text = "".join(f"{_sha256(temporary / name)}  {name}\n" for name in checksummed_files)
        (temporary / "checksums.sha256").write_text(checksum_text, encoding="utf-8")
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return ComparisonArchive(snapshot_id=snapshot_id, path=destination, manifest=manifest)


def list_comparison_archives(archive_root: str | Path) -> list[ComparisonArchive]:
    """List valid archive manifests newest first, ignoring partial directories."""
    root = Path(archive_root)
    if not root.exists():
        return []
    archives = []
    for manifest_path in root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            archives.append(
                ComparisonArchive(
                    snapshot_id=str(manifest["snapshot_id"]),
                    path=manifest_path.parent,
                    manifest=manifest,
                )
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(archives, key=lambda item: str(item.manifest.get("created_at", "")), reverse=True)


def list_comparison_archives_from_roots(archive_roots: list[str | Path]) -> list[ComparisonArchive]:
    """Merge archives from ordered roots, preferring the first copy of each snapshot."""
    archives_by_id = {}
    for archive_root in archive_roots:
        for archive in list_comparison_archives(archive_root):
            archives_by_id.setdefault(archive.snapshot_id, archive)
    return sorted(
        archives_by_id.values(),
        key=lambda item: str(item.manifest.get("created_at", "")),
        reverse=True,
    )


def find_comparison_archive(archive_root: str | Path, snapshot_id: str) -> ComparisonArchive:
    """Find one archive by a unique full or leading snapshot ID."""
    matches = [item for item in list_comparison_archives(archive_root) if item.snapshot_id.startswith(snapshot_id)]
    if not matches:
        raise ValueError(f"No comparison archive matches snapshot ID {snapshot_id!r}.")
    if len(matches) > 1:
        raise ValueError(f"Snapshot ID prefix {snapshot_id!r} is ambiguous.")
    return matches[0]


def find_comparison_archive_in_roots(archive_roots: list[str | Path], snapshot_id: str) -> ComparisonArchive:
    """Find one snapshot across ordered archive roots."""
    matches = [
        item for item in list_comparison_archives_from_roots(archive_roots) if item.snapshot_id.startswith(snapshot_id)
    ]
    if not matches:
        raise ValueError(f"No comparison archive matches snapshot ID {snapshot_id!r}.")
    if len(matches) > 1:
        raise ValueError(f"Snapshot ID prefix {snapshot_id!r} is ambiguous.")
    return matches[0]


def verify_comparison_archive(archive: ComparisonArchive) -> list[str]:
    """Return verification failures for an archive, or an empty list when valid."""
    checksum_path = archive.path / "checksums.sha256"
    if not checksum_path.is_file():
        return ["missing checksums.sha256"]
    failures = []
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        expected, separator, relative_name = line.partition("  ")
        relative_path = Path(relative_name)
        path = archive.path / relative_path
        if not separator or not relative_name:
            failures.append(f"invalid checksum line: {line}")
        elif not re.fullmatch(r"[0-9a-f]{64}", expected):
            failures.append(f"invalid checksum digest: {relative_name}")
        elif relative_path.is_absolute() or archive.path.resolve() not in path.resolve().parents:
            failures.append(f"unsafe checksum path: {relative_name}")
        elif not path.is_file():
            failures.append(f"missing {relative_name}")
        elif _sha256(path) != expected:
            failures.append(f"checksum mismatch: {relative_name}")
    return failures


def comparison_archive_zip(archive: ComparisonArchive) -> bytes:
    """Return an archive directory as a portable ZIP file."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(archive.path.rglob("*")):
            if path.is_file():
                relative_path = path.relative_to(archive.path)
                output.write(path, arcname=str(Path(archive.path.name) / relative_path))
    return buffer.getvalue()
