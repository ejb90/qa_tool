"""Focused tests for reusable web-app helpers that do not require a browser."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest
from pandas.io.formats.style import Styler

from qa_tool.core.artifacts import ArtifactLimits, iter_artifact_files, local_artifact_candidates
from qa_tool.webapp.artifacts import (
    bounded_plot_data,
    compare_run_parquet_pairs,
    find_time_column,
    first_local_artifact_path,
    is_tar_artifact,
    load_pickle_artifact,
    material_column,
    parquet_files_for_run,
    parquet_plot_key,
    parquet_preview,
    parquet_series_by_thing,
    run_artifact_candidates,
    run_display_name,
    run_option_match_index,
    safe_extract_tar,
    split_series_column,
)
from qa_tool.webapp.compare import (
    build_run_scalar_comparison,
    comparison_coverage,
    comparison_metadata,
)
from qa_tool.webapp.data import (
    database_cache_generation,
    database_cache_ttl_seconds,
    database_max_query_rows,
    database_revision,
    dataframe_to_csv,
    dataframe_to_json,
    dataframe_to_pickle,
)
from qa_tool.webapp.exports import dataframes_to_zip, export_name
from qa_tool.webapp.settings import configured_metrics, deep_merge_settings, override_settings_path
from qa_tool.webapp.styling import (
    comparison_color_bounds,
    comparison_column_bound,
    styled_comparison_table,
)
from qa_tool.webapp.views.common import empirical_cdf
from qa_tool.webapp.views.compare_collection import (
    collection_parameter_columns,
    compact_collection_label,
    string_collection_mask,
    unique_string_values,
)


def test_artifact_location_and_run_identity_helpers(tmp_path: Path) -> None:
    """Run labels, pasted identifiers, and artifact candidates are deterministic."""
    artifact = tmp_path / "artifact.parquet"
    pd.DataFrame({"time": [0], "density": [1.0]}).to_parquet(artifact)
    row = pd.Series({"uid": "uid-1", "name": "run-one", "model": "h2", "version": "v1", "artifact": str(artifact)})
    second_row = row.copy()
    second_row.loc[["uid", "name"]] = ["uid-2", "run-two"]
    options = pd.DataFrame([row, second_row]).reset_index(drop=True)

    assert run_display_name(row) == "h2 v1 | run-one"
    assert run_option_match_index(options, " run-two ") == 1
    assert run_option_match_index(options, "missing") is None
    assert run_option_match_index(options, "") is None
    assert run_artifact_candidates(row, str(tmp_path))[0] == artifact
    assert first_local_artifact_path(row, str(tmp_path)) == artifact
    assert parquet_files_for_run(row, str(tmp_path)) == {artifact.name: artifact}


def test_artifact_directory_fallback_and_series_parsing(tmp_path: Path) -> None:
    """Parquet directories and both wide and long series layouts are recognized."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text('{"uid": "uid-1"}', encoding="utf-8")
    wide_path = run_dir / "series.parquet"
    wide = pd.DataFrame({"simulation_time": [0.0, 1.0], "density.h2": [1.0, 2.0], "density_he": [3.0, 4.0]})
    wide.to_parquet(wide_path)
    row = pd.Series({"uid": "uid-1", "name": "run", "artifact": str(run_dir / "missing.json")})

    assert first_local_artifact_path(row, str(tmp_path)) == run_dir
    assert parquet_files_for_run(row, str(tmp_path)) == {"series.parquet": wide_path}
    assert find_time_column(wide) == "simulation_time"
    assert material_column(wide) is None
    assert split_series_column("density.h2") == ("density", "h2")
    assert split_series_column("material-h2", "density") == ("density", "material-h2")
    wide_groups = parquet_series_by_thing(wide, "simulation_time")
    assert list(wide_groups) == ["density"]
    assert sorted(wide_groups["density"]["material"].unique()) == ["h2", "he"]

    long = pd.DataFrame({"t": [0.0, 0.0], "material": ["h2", "he"], "pressure": [1.0, 2.0]})
    assert material_column(long) == "material"
    assert list(parquet_series_by_thing(long, "t")) == ["pressure"]
    assert parquet_plot_key(Path("a path/file.parquet"), "density h2").startswith("parquet_line_")


def test_matching_parquet_artifacts_are_paired_for_run_comparison(tmp_path: Path) -> None:
    """Only shared, plottable Parquet artifacts are paired across two runs."""
    top_dir = tmp_path / "top"
    bottom_dir = tmp_path / "bottom"
    top_dir.mkdir()
    bottom_dir.mkdir()
    for directory, scale in ((top_dir, 1.0), (bottom_dir, 2.0)):
        pd.DataFrame({"time": [0.0, 1.0], "density.h2": [scale, scale + 1]}).to_parquet(directory / "series.parquet")
    pd.DataFrame({"value": [1.0]}).to_parquet(top_dir / "top-only.parquet")

    pairs = compare_run_parquet_pairs(
        pd.Series({"uid": "top", "name": "top", "artifact": str(top_dir)}),
        pd.Series({"uid": "bottom", "name": "bottom", "artifact": str(bottom_dir)}),
        str(tmp_path),
    )

    assert len(pairs) == 1
    assert pairs[0]["name"] == "series.parquet"
    assert pairs[0]["shared_things"] == ["density"]


def test_tar_helpers_accept_safe_members_and_reject_traversal(tmp_path: Path) -> None:
    """Tar detection and extraction protect the destination directory."""
    safe_tar = tmp_path / "safe.tar.gz"
    with tarfile.open(safe_tar, "w:gz") as archive:
        contents = b"ok"
        member = tarfile.TarInfo("nested/result.txt")
        member.size = len(contents)
        archive.addfile(member, io.BytesIO(contents))
    destination = tmp_path / "extracted"
    destination.mkdir()
    with tarfile.open(safe_tar) as archive:
        safe_extract_tar(archive, destination)
    assert (destination / "nested" / "result.txt").read_bytes() == b"ok"
    assert is_tar_artifact(safe_tar)
    assert not is_tar_artifact(tmp_path / "result.zip")

    unsafe_tar = tmp_path / "unsafe.tar"
    with tarfile.open(unsafe_tar, "w") as archive:
        member = tarfile.TarInfo("../outside.txt")
        member.size = 0
        archive.addfile(member, io.BytesIO())
    with tarfile.open(unsafe_tar) as archive, pytest.raises(ValueError, match="Unsafe path"):
        safe_extract_tar(archive, destination)


def test_artifact_paths_are_confined_to_root_and_reject_symlink_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Database path fields cannot select files outside the approved root."""
    root = tmp_path / "artifacts"
    root.mkdir()
    inside = root / "inside.txt"
    outside = tmp_path / "outside.txt"
    inside.write_text("inside", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")

    safe = pd.Series({"uid": "safe", "name": "safe", "artifact": str(inside)})
    hostile = pd.Series({"uid": "../outside.txt", "name": str(outside), "artifact": str(outside)})
    assert local_artifact_candidates(safe, root)[0] == inside
    assert local_artifact_candidates(hostile, root) == []
    assert local_artifact_candidates(safe, "") == []

    monkeypatch.chdir(tmp_path)
    relative = pd.Series({"uid": "safe", "name": "safe", "artifact": "artifacts/inside.txt"})
    assert local_artifact_candidates(relative, "artifacts")[0] == inside

    escape = root / "escape"
    escape.symlink_to(outside)
    escaped = pd.Series({"uid": "escape", "name": "escape", "artifact": str(escape)})
    assert local_artifact_candidates(escaped, root) == []


def test_recursive_artifact_limits_reject_too_many_large_and_linked_files(tmp_path: Path) -> None:
    """Recursive inspection stops at file-count, file-size, and symlink boundaries."""
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "one.txt").write_bytes(b"1")
    (root / "two.txt").write_bytes(b"22")

    with pytest.raises(ValueError, match="max_recursive_files"):
        list(iter_artifact_files(root, ArtifactLimits(max_recursive_files=1)))
    with pytest.raises(ValueError, match="max_file_bytes"):
        list(iter_artifact_files(root, ArtifactLimits(max_file_bytes=1)))

    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "linked.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="symlinks are not allowed"):
        list(iter_artifact_files(root, ArtifactLimits()))


def test_archive_limits_reject_links_member_counts_and_expanded_size(tmp_path: Path) -> None:
    """Archive validation occurs before extracting hostile or oversized contents."""
    destination = tmp_path / "extracted"
    destination.mkdir()
    archive_path = tmp_path / "bounded.tar"
    with tarfile.open(archive_path, "w") as archive:
        for name in ("one.txt", "two.txt"):
            member = tarfile.TarInfo(name)
            member.size = 2
            archive.addfile(member, io.BytesIO(b"ok"))

    with tarfile.open(archive_path) as archive, pytest.raises(ValueError, match="max_archive_members"):
        safe_extract_tar(archive, destination, ArtifactLimits(max_archive_members=1))
    with tarfile.open(archive_path) as archive, pytest.raises(ValueError, match="max_expanded_bytes"):
        safe_extract_tar(archive, destination, ArtifactLimits(max_expanded_bytes=3))

    link_path = tmp_path / "link.tar"
    with tarfile.open(link_path, "w") as archive:
        member = tarfile.TarInfo("linked")
        member.type = tarfile.SYMTYPE
        member.linkname = "target"
        archive.addfile(member)
    with tarfile.open(link_path) as archive, pytest.raises(ValueError, match="Unsupported archive member"):
        safe_extract_tar(archive, destination)

    compressed_path = tmp_path / "compressed-bomb.tar.gz"
    expanded = b"0" * 16_384
    with tarfile.open(compressed_path, "w:gz") as archive:
        member = tarfile.TarInfo("expanded.txt")
        member.size = len(expanded)
        archive.addfile(member, io.BytesIO(expanded))
    assert compressed_path.stat().st_size < len(expanded)
    with tarfile.open(compressed_path) as archive, pytest.raises(ValueError, match="max_expanded_bytes"):
        safe_extract_tar(
            archive,
            destination,
            ArtifactLimits(max_file_bytes=len(expanded), max_expanded_bytes=1024),
        )


def test_table_and_plot_previews_are_bounded(tmp_path: Path) -> None:
    """Parquet reads and plot frames honor independent row and point budgets."""
    path = tmp_path / "series.parquet"
    frame = pd.DataFrame({"time": range(20), "value": range(20)})
    frame.to_parquet(path, row_group_size=4)

    preview, truncated = parquet_preview(path, 7)
    assert truncated
    assert preview["time"].tolist() == list(range(7))
    plotted = bounded_plot_data(frame, 5)
    assert len(plotted) == 5
    assert plotted["time"].tolist() == [0, 4, 8, 12, 16]


def test_pickle_loading_requires_explicit_unsafe_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pickle deserialization is unavailable unless local CLI use opts in."""
    pickle_path = tmp_path / "artifact.pkl"
    frame = pd.DataFrame({"value": [1.5]})
    frame.to_pickle(pickle_path)
    called = False
    pandas_read_pickle = pd.read_pickle

    def tracked_read_pickle(path: Path) -> object:
        nonlocal called
        called = True
        return pandas_read_pickle(path)

    monkeypatch.setattr(pd, "read_pickle", tracked_read_pickle)

    with pytest.raises(ValueError, match="Pickle loading is disabled"):
        load_pickle_artifact(pickle_path)
    assert not called
    assert load_pickle_artifact(pickle_path, allow_unsafe_pickle=True).equals(frame)
    assert called


def test_web_comparison_and_export_helpers_round_trip() -> None:
    """Web adapters produce useful metadata, coverage labels, and portable downloads."""
    base = pd.DataFrame({"uid": ["a", "b"], "model": ["shared", "base only"], "density": [1.0, 2.0]})
    test = pd.DataFrame({"uid": ["c", "d"], "model": ["shared", "test only"], "density": [2.0, 3.0]})

    metadata = comparison_metadata("base", "test", base, test).set_index("item")["value"]
    coverage = comparison_coverage(base, "Base group", test, "Test group").set_index("model")
    scalar = build_run_scalar_comparison(base.iloc[0], test.iloc[0], ["density"])

    assert metadata["base_run_count"] == 2
    assert coverage.loc["shared", "status"] == "shared"
    assert coverage.loc["base only", "status"] == "only_Base_group"
    assert scalar.loc[0, "bottom_minus_top"] == 1.0
    assert export_name(" test / result ") == "test_result"
    with ZipFile(io.BytesIO(dataframes_to_zip({"comparison result": scalar}))) as archive:
        assert archive.namelist() == ["comparison_result.csv"]


def test_dataframe_settings_and_styling_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Serialization, settings merging, and table styles retain expected values."""
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "value": [1.5]})
    assert b"value" in dataframe_to_csv(frame)
    assert b"2026-01-01" in dataframe_to_json(frame)
    assert pd.read_pickle(io.BytesIO(dataframe_to_pickle(frame))).equals(frame)

    merged = deep_merge_settings({"page": {"title": "A", "layout": "wide"}}, {"page": {"title": "B"}})
    assert merged == {"page": {"title": "B", "layout": "wide"}}
    monkeypatch.setenv("QA_TOOL_SETTINGS", str(tmp_path / "settings.toml"))
    assert override_settings_path() == tmp_path / "settings.toml"
    assert configured_metrics(["missing", "density"], ["density"], ["density"]) == ["density"]

    settings = {"comparison": {"color_bounds": {"density": 10, "invalid": -1, "flag": True}}}
    assert comparison_color_bounds(settings) == {"density": 10.0}
    assert comparison_column_bound("percent_difference_density", {"density": 10.0}) == 10.0
    assert styled_comparison_table(frame, settings, "Off") is frame
    styled = styled_comparison_table(
        pd.DataFrame({"metric": ["density", "density"], "percent_difference": [-5.0, 10.0], "base_std": [1.0, 2.0]}),
        settings,
    )
    assert isinstance(styled, Styler)
    assert "background-color" in styled.to_html()


def test_database_revision_and_cache_generation_track_promoted_files(tmp_path: Path) -> None:
    """Database cache keys change for file updates, symlink promotion, and TTL boundaries."""
    first = tmp_path / "release-one" / "runs.duckdb"
    second = tmp_path / "release-two" / "runs.duckdb"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"first")
    second.write_bytes(b"second snapshot")
    current = tmp_path / "current.duckdb"
    current.symlink_to(first)

    first_revision = database_revision(current)
    replacement_link = tmp_path / "next.duckdb"
    replacement_link.symlink_to(second)
    replacement_link.replace(current)
    second_revision = database_revision(current)

    assert first_revision.resolved_path == str(first)
    assert second_revision.resolved_path == str(second)
    assert first_revision != second_revision
    assert database_cache_generation(60, now=119.9) == 1
    assert database_cache_generation(60, now=120.0) == 2
    assert database_cache_generation(0, now=120.0) == 0
    assert database_cache_ttl_seconds({"database": {}}) == 60
    assert database_cache_ttl_seconds({"database": {"cache_ttl_seconds": 0}}) == 0
    assert database_max_query_rows({"database": {}}) == 50_000
    assert database_max_query_rows({"database": {"max_query_rows": 1_000}}) == 1_000
    with pytest.raises(ValueError, match="non-negative integer"):
        database_cache_ttl_seconds({"database": {"cache_ttl_seconds": -1}})
    with pytest.raises(ValueError, match="positive integer"):
        database_max_query_rows({"database": {"max_query_rows": 0}})


def test_collection_and_cdf_helpers_cover_labels_and_masks() -> None:
    """Collection controls share stable ordering, concise labels, and predictable masks."""
    runs = pd.DataFrame(
        {
            "uid": ["a", "b", "c"],
            "version": ["v1", "v2", "v3"],
            "branch": ["main", "Release", None],
            "density": [1.0, 2.0, 3.0],
        }
    )

    assert collection_parameter_columns(runs, ["density"])[:2] == ["version", "branch"]
    assert compact_collection_label("branch", "is", ["a", "b", "c", "d"]) == "branch is a, b, c, +1"
    assert unique_string_values(runs, "branch") == ["main", "Release"]
    assert string_collection_mask(runs["branch"], "Contains", [], "LEAS").tolist() == [False, True, False]
    assert string_collection_mask(runs["branch"], "Non-empty", [], "").tolist() == [True, True, False]
    assert empirical_cdf(pd.Series([3.0, 1.0, 2.0])).to_dict("list") == {
        "value": [1.0, 2.0, 3.0],
        "cdf": [1 / 3, 2 / 3, 1.0],
    }
