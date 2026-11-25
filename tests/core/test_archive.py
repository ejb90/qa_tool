"""Tests for durable comparison snapshots."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

from qa_tool.core.archive import (
    ComparisonArchive,
    comparison_archive_zip,
    create_comparison_archive,
    find_comparison_archive,
    find_comparison_archive_in_roots,
    list_comparison_archives,
    list_comparison_archives_from_roots,
    local_artifact_paths,
    verify_comparison_archive,
)


def test_archive_round_trip_includes_inputs_artifacts_and_checksums(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot is self-contained, discoverable, portable, and initially valid."""
    monkeypatch.setattr("qa_tool.core.archive.getpass.getuser", lambda: "qa-user")
    artifact = tmp_path / "source-artifact"
    artifact.mkdir()
    (artifact / "series.csv").write_text("time,value\n0,1\n", encoding="utf-8")
    base = pd.DataFrame([{"uid": "base-1", "model": "h2", "density": 1.0}])
    test = pd.DataFrame([{"uid": "test-1", "model": "h2", "density": 1.5}])
    comparison = pd.DataFrame(
        [
            {
                "model": "h2",
                "metric": "density",
                "percent_difference": 50.0,
                "percent_uncertainty": 2.0,
            }
        ]
    )

    archive = create_comparison_archive(
        tmp_path / "archives",
        comparison_type="versions",
        base_label="v1",
        test_label="v2",
        base_runs=base,
        test_runs=test,
        comparison=comparison,
        metrics=["density"],
        parameters={"purpose": "regression"},
        artifact_paths={"base-1": artifact},
        created_at=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
    )

    assert archive.path.name.startswith("20261121T120000Z_versions_v1_to_v2_")
    assert verify_comparison_archive(archive) == []
    assert pd.read_parquet(archive.path / "runs.parquet")["comparison_role"].tolist() == ["base", "test"]
    assert (archive.path / "artifacts" / "base-1" / "series.csv").exists()
    assert "plotly" in (archive.path / "report.html").read_text(encoding="utf-8").lower()
    manifest = json.loads((archive.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["base_run_uids"] == ["base-1"]
    assert manifest["created_by"] == "qa-user"
    assert manifest["artifacts"][0]["run_uid"] == "base-1"
    assert "qa-user" in (archive.path / "report.html").read_text(encoding="utf-8")

    assert list_comparison_archives(tmp_path / "archives")[0].snapshot_id == archive.snapshot_id
    assert list_comparison_archives_from_roots([tmp_path / "missing", tmp_path / "archives"])[0].path == archive.path

    preferred_root = tmp_path / "preferred"
    preferred_copy = preferred_root / archive.path.name
    shutil.copytree(archive.path, preferred_copy)
    assert list_comparison_archives_from_roots([preferred_root, tmp_path / "archives"])[0].path == preferred_copy

    assert find_comparison_archive(tmp_path / "archives", archive.snapshot_id[:6]).path == archive.path
    zip_path = tmp_path / "snapshot.zip"
    zip_path.write_bytes(comparison_archive_zip(archive))
    with ZipFile(zip_path) as snapshot_zip:
        assert any(name.endswith("artifacts/base-1/series.csv") for name in snapshot_zip.namelist())


def test_archive_verification_reports_tampering(tmp_path: Path) -> None:
    """Changing a recorded result is detected by checksum verification."""
    runs = pd.DataFrame([{"uid": "one", "model": "h2", "density": 1.0}])
    archive = create_comparison_archive(
        tmp_path,
        comparison_type="runs",
        base_label="one",
        test_label="two",
        base_runs=runs,
        test_runs=runs.assign(uid="two"),
        comparison=pd.DataFrame([{"metric": "density", "bottom_minus_top": 0.0}]),
        metrics=["density"],
    )
    (archive.path / "comparison.csv").write_text("tampered\n", encoding="utf-8")

    assert verify_comparison_archive(archive) == ["checksum mismatch: comparison.csv"]


def test_gate_archive_records_policy_junit_summary_and_report(tmp_path: Path) -> None:
    """Gate evidence is checksummed and visible in the immutable snapshot."""
    runs = pd.DataFrame([{"uid": "one", "model": "h2", "density": 1.0}])
    policy = 'schema_version = 1\n[metrics.density]\ndirection = "increase"\nabsolute_tolerance = 0.1\n'
    junit = '<?xml version="1.0"?><testsuites tests="1" failures="1" />\n'
    archive = create_comparison_archive(
        tmp_path,
        comparison_type="versions",
        base_label="v1",
        test_label="v2",
        base_runs=runs,
        test_runs=runs.assign(uid="two", density=2.0),
        comparison=pd.DataFrame([{"model": "h2", "metric": "density", "percent_difference": 100.0}]),
        metrics=["density"],
        gate_policy_text=policy,
        gate_results_xml=junit,
        gate_summary={
            "status": "failed",
            "evaluated": 1,
            "passed": 0,
            "failed": 1,
            "failures": ["h2/density: tolerance exceeded"],
        },
    )

    manifest = json.loads((archive.path / "manifest.json").read_text(encoding="utf-8"))
    assert (archive.path / "gate-policy.toml").read_text(encoding="utf-8") == policy
    assert (archive.path / "gate-results.xml").read_text(encoding="utf-8") == junit
    assert manifest["schema_version"] == 3
    assert manifest["gate"]["status"] == "failed"
    assert manifest["files"]["gate_results"] == "gate-results.xml"
    assert "FAILED" in (archive.path / "report.html").read_text(encoding="utf-8")
    assert verify_comparison_archive(archive) == []


def test_gate_archive_requires_complete_evidence_before_creating_files(tmp_path: Path) -> None:
    """Partial gate arguments fail before an archive directory is created."""
    runs = pd.DataFrame([{"uid": "one", "model": "h2", "density": 1.0}])
    archive_root = tmp_path / "archives"
    with pytest.raises(ValueError, match="require policy text"):
        create_comparison_archive(
            archive_root,
            comparison_type="versions",
            base_label="v1",
            test_label="v2",
            base_runs=runs,
            test_runs=runs,
            comparison=pd.DataFrame([{"model": "h2", "metric": "density"}]),
            metrics=["density"],
            gate_policy_text="schema_version = 1\n",
        )

    assert not archive_root.exists()


def test_local_artifact_paths_resolves_explicit_and_root_candidates(tmp_path: Path) -> None:
    """Local artifacts are found without resolving remote object-store references."""
    explicit = tmp_path / "explicit.parquet"
    explicit.touch()
    rooted = tmp_path / "artifacts" / "second"
    rooted.mkdir(parents=True)
    runs = pd.DataFrame(
        [
            {"uid": "first", "name": "one", "artifact": str(explicit)},
            {"uid": "second", "name": "two", "artifact": "s3://bucket/key"},
            {"uid": "missing", "name": "missing", "artifact": str(tmp_path / "absent")},
        ]
    )

    assert local_artifact_paths(runs, tmp_path / "artifacts") == {"first": explicit, "second": rooted}


def test_archive_discovery_ignores_invalid_manifests_and_checks_prefixes(tmp_path: Path) -> None:
    """Discovery skips corrupt entries and reports absent or ambiguous identifiers."""
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "manifest.json").write_text("not json", encoding="utf-8")
    assert list_comparison_archives(tmp_path) == []

    for snapshot_id, created_at in (("abc111", "2026-01-01T00:00:00Z"), ("abc222", "2026-01-02T00:00:00Z")):
        directory = tmp_path / snapshot_id
        directory.mkdir()
        (directory / "manifest.json").write_text(
            json.dumps({"snapshot_id": snapshot_id, "created_at": created_at}), encoding="utf-8"
        )

    assert [item.snapshot_id for item in list_comparison_archives(tmp_path)] == ["abc222", "abc111"]
    with pytest.raises(ValueError, match="ambiguous"):
        find_comparison_archive(tmp_path, "abc")
    with pytest.raises(ValueError, match="No comparison"):
        find_comparison_archive(tmp_path, "missing")
    assert find_comparison_archive_in_roots([tmp_path / "absent", tmp_path], "abc1").snapshot_id == "abc111"


@pytest.mark.parametrize(
    ("checksum_text", "expected_failure"),
    [
        ("malformed\n", "invalid checksum line: malformed"),
        ("not-a-digest  report.html\n", "invalid checksum digest: report.html"),
        (f"{'0' * 64}  missing.txt\n", "missing missing.txt"),
        (f"{'0' * 64}  ../outside.txt\n", "unsafe checksum path: ../outside.txt"),
    ],
)
def test_archive_verification_rejects_invalid_checksum_entries(
    tmp_path: Path, checksum_text: str, expected_failure: str
) -> None:
    """Checksum parsing rejects malformed, unsafe, and missing entries."""
    archive_path = tmp_path / "archive"
    archive_path.mkdir()
    (archive_path / "report.html").write_text("report", encoding="utf-8")
    (archive_path / "checksums.sha256").write_text(checksum_text, encoding="utf-8")
    archive = ComparisonArchive(snapshot_id="snapshot", path=archive_path, manifest={})

    assert verify_comparison_archive(archive) == [expected_failure]


def test_archive_verification_requires_checksum_file(tmp_path: Path) -> None:
    """A snapshot cannot verify without its digest inventory."""
    archive = ComparisonArchive(snapshot_id="snapshot", path=tmp_path, manifest={})

    assert verify_comparison_archive(archive) == ["missing checksums.sha256"]
