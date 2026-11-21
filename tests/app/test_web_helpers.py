"""Focused tests for reusable web-app helpers that do not require a browser."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest
from pandas.io.formats.style import Styler

from qa_tool.webapp.artifacts import (
    compare_run_parquet_pairs,
    find_time_column,
    first_local_artifact_path,
    is_tar_artifact,
    material_column,
    parquet_files_for_run,
    parquet_plot_key,
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
from qa_tool.webapp.data import dataframe_to_csv, dataframe_to_json, dataframe_to_pickle
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
    assert run_artifact_candidates(row, str(tmp_path / "root"))[0] == artifact
    assert first_local_artifact_path(row, "") == artifact
    assert parquet_files_for_run(row, "") == {artifact.name: artifact}


def test_artifact_directory_fallback_and_series_parsing(tmp_path: Path) -> None:
    """Parquet directories and both wide and long series layouts are recognized."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "metadata.json").write_text('{"uid": "uid-1"}', encoding="utf-8")
    wide_path = run_dir / "series.parquet"
    wide = pd.DataFrame({"simulation_time": [0.0, 1.0], "density.h2": [1.0, 2.0], "density_he": [3.0, 4.0]})
    wide.to_parquet(wide_path)
    row = pd.Series({"uid": "uid-1", "name": "run", "artifact": str(run_dir / "missing.json")})

    assert first_local_artifact_path(row, "") == run_dir
    assert parquet_files_for_run(row, "") == {"series.parquet": wide_path}
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
        "",
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
