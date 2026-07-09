from __future__ import annotations

import json
import re
import tarfile
import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

TIME_COLUMN_PATTERN = re.compile(r"(^|[\s_-])time([\s_-]|$)|^t$", re.IGNORECASE)
MATERIAL_COLUMN_PATTERN = re.compile(r"^materials?$", re.IGNORECASE)
SERIES_SEPARATOR_PATTERN = re.compile(r"[\s_.:/|-]+")

def run_display_name(row: pd.Series) -> str:
    return f"{row['model']} {row['version']} | {row['name']}"

def run_option_match_index(run_options: pd.DataFrame, pasted_id: str) -> int | None:
    if not pasted_id:
        return None

    pasted_id = pasted_id.strip()
    matches = run_options[
        (run_options["uid"].astype(str) == pasted_id)
        | (run_options["name"].astype(str) == pasted_id)
    ]
    if matches.empty:
        return None
    return int(matches.index[0])

def run_artifact_candidates(row: pd.Series, artifact_root: str) -> list[Path | str]:
    candidates: list[Path | str] = []
    artifact = row.get("artifact")
    if isinstance(artifact, str) and artifact:
        candidates.append(artifact if artifact.startswith("s3://") else Path(artifact))

    if artifact_root:
        root = Path(artifact_root)
        candidates.extend([root / str(row["uid"]), root / str(row["name"])])
    return candidates

def first_local_artifact_path(row: pd.Series, artifact_root: str) -> Path | None:
    for candidate in run_artifact_candidates(row, artifact_root):
        if isinstance(candidate, str) and candidate.startswith("s3://"):
            continue

        path = Path(candidate)
        if path.exists():
            return path
        parent = path.parent
        metadata_path = parent / "metadata.json"
        if metadata_path.exists() and any(parent.glob("*.parquet")):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if str(metadata.get("uid", "")) == str(row.get("uid", "")):
                return parent
    return None

def parquet_files_for_run(row: pd.Series, artifact_root: str) -> dict[str, Path]:
    artifact_path = first_local_artifact_path(row, artifact_root)
    if artifact_path is None:
        return {}
    if artifact_path.is_file():
        return {artifact_path.name: artifact_path} if artifact_path.suffix.lower() == ".parquet" else {}
    return {
        parquet_file.name: parquet_file
        for parquet_file in sorted(artifact_path.rglob("*.parquet"))
    }

def render_artifact_file(path: Path) -> None:
    suffix = path.suffix.lower()
    if is_tar_artifact(path):
        render_tar_artifact(path)
        return

    with st.expander(path.name, expanded=False):
        st.caption(str(path))
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            st.image(str(path))
        elif suffix == ".csv":
            st.dataframe(pd.read_csv(path), use_container_width=True)
        elif suffix == ".parquet":
            render_parquet_artifact(path)
        elif suffix in {".pkl", ".pickle"}:
            artifact = pd.read_pickle(path)
            if isinstance(artifact, pd.DataFrame):
                st.dataframe(artifact, use_container_width=True)
            elif isinstance(artifact, pd.Series):
                st.dataframe(artifact.to_frame(), use_container_width=True)
            else:
                st.write(artifact)
        elif suffix in {".json", ".jsonl"}:
            if suffix == ".jsonl":
                st.dataframe(pd.read_json(path, lines=True), use_container_width=True)
            else:
                st.json(json.loads(path.read_text(encoding="utf-8")))
        elif suffix in {".txt", ".log", ".out", ".err", ".yaml", ".yml", ".toml"}:
            st.code(path.read_text(encoding="utf-8", errors="replace"))
        elif suffix == ".html":
            components.html(path.read_text(encoding="utf-8", errors="replace"), height=500, scrolling=True)
        else:
            st.download_button(
                "Download artifact",
                data=path.read_bytes(),
                file_name=path.name,
                use_container_width=True,
            )

def find_time_column(dataframe: pd.DataFrame) -> str | None:
    for column in dataframe.columns:
        if TIME_COLUMN_PATTERN.search(str(column)):
            return str(column)
    return None

def parquet_plot_key(path: Path, column: str) -> str:
    safe_path = re.sub(r"\W+", "_", str(path))
    safe_column = re.sub(r"\W+", "_", column)
    return f"parquet_line_{safe_path}_{safe_column}"

def material_column(dataframe: pd.DataFrame) -> str | None:
    for column in dataframe.columns:
        if MATERIAL_COLUMN_PATTERN.search(str(column)):
            return str(column)
    return None

def split_series_column(column: str, default_thing: str | None = None) -> tuple[str, str]:
    first_part = SERIES_SEPARATOR_PATTERN.split(column, maxsplit=1)[0].lower()
    if first_part in {"material", "mat"}:
        return default_thing or column, column

    parts = [part for part in SERIES_SEPARATOR_PATTERN.split(column) if part]
    if len(parts) >= 2:
        return parts[0], "_".join(parts[1:])
    return default_thing or column, column

def wide_parquet_series(
    dataframe: pd.DataFrame,
    time_column: str,
    default_thing: str | None = None,
) -> dict[str, pd.DataFrame]:
    numeric_columns = [
        column
        for column in dataframe.select_dtypes(include="number").columns
        if str(column) != time_column
    ]
    series_frames: dict[str, list[pd.DataFrame]] = {}
    for column in numeric_columns:
        thing, material = split_series_column(str(column), default_thing)
        series_frame = dataframe[[time_column, column]].rename(columns={column: "value"})
        series_frame["material"] = material
        series_frames.setdefault(thing, []).append(series_frame)
    return {
        thing: pd.concat(frames, ignore_index=True)
        for thing, frames in series_frames.items()
    }

def long_parquet_series(
    dataframe: pd.DataFrame,
    time_column: str,
    material_column_name: str,
) -> dict[str, pd.DataFrame]:
    value_columns = [
        column
        for column in dataframe.select_dtypes(include="number").columns
        if str(column) != time_column
    ]
    return {
        str(column): dataframe[[time_column, material_column_name, column]].rename(
            columns={material_column_name: "material", column: "value"}
        )
        for column in value_columns
    }

def parquet_series_by_thing(
    dataframe: pd.DataFrame,
    time_column: str,
    default_thing: str | None = None,
) -> dict[str, pd.DataFrame]:
    material_column_name = material_column(dataframe)
    if material_column_name is not None:
        return long_parquet_series(dataframe, time_column, material_column_name)
    return wide_parquet_series(dataframe, time_column, default_thing)

def selected_materials(path: Path, thing: str, materials: list[str]) -> list[str]:
    checkbox_columns = st.columns(min(4, len(materials)))
    selected = []
    for index, material in enumerate(materials):
        enabled = checkbox_columns[index % len(checkbox_columns)].checkbox(
            material,
            value=True,
            key=parquet_plot_key(path, f"{thing}_{material}"),
        )
        if enabled:
            selected.append(material)
    return selected

def render_parquet_series_plot(path: Path, thing: str, series_data: pd.DataFrame, time_column: str) -> None:
    materials = sorted(series_data["material"].astype(str).unique())
    st.markdown(f"**{thing}**")
    selected = selected_materials(path, thing, materials)
    if not selected:
        st.info("Select at least one material to plot.")
        return

    plot_data = series_data[series_data["material"].astype(str).isin(selected)]
    fig = px.line(
        plot_data,
        x=time_column,
        y="value",
        color="material",
        markers=False,
        title=f"{path.name}: {thing}",
    )
    fig.update_layout(
        height=420,
        margin={"l": 10, "r": 10, "t": 44, "b": 10},
        xaxis_title=time_column,
        yaxis_title=thing,
    )
    st.plotly_chart(fig, use_container_width=True)

def render_parquet_time_plots(path: Path, dataframe: pd.DataFrame) -> None:
    time_column = find_time_column(dataframe)
    if time_column is None:
        return

    for thing, series_data in parquet_series_by_thing(dataframe, time_column, path.stem).items():
        render_parquet_series_plot(path, thing, series_data, time_column)

def render_parquet_artifact(path: Path) -> None:
    dataframe = pd.read_parquet(path)
    render_parquet_time_plots(path, dataframe)
    st.dataframe(dataframe, use_container_width=True)

def is_tar_artifact(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith((".tar", ".tar.gz", ".tgz"))

def safe_extract_tar(tar: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in tar.getmembers():
        member_path = (destination / member.name).resolve()
        if destination not in member_path.parents and member_path != destination:
            raise ValueError(f"Unsafe path in archive: {member.name}")
    tar.extractall(destination)

def render_tar_artifact(path: Path) -> None:
    st.caption(f"Archive: `{path}`")
    with tarfile.open(path) as tar:
        members = [member for member in tar.getmembers() if member.isfile()]
        st.dataframe(
            pd.DataFrame(
                {
                    "name": [member.name for member in members],
                    "size_bytes": [member.size for member in members],
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            safe_extract_tar(tar, temp_path)
            for artifact_file in sorted(item for item in temp_path.rglob("*") if item.is_file()):
                render_artifact_file(artifact_file)

def show_run_artifacts(row: pd.Series, artifact_root: str) -> None:
    st.subheader("Artifacts")
    candidates = run_artifact_candidates(row, artifact_root)
    if not candidates:
        st.info("No artifact path or artifact root is configured.")
        return

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith("s3://"):
            st.info(f"S3 artifact location: `{candidate}`")
            continue

        path = Path(candidate)
        if not path.exists():
            continue
        if path.is_file():
            render_artifact_file(path)
            return

        artifact_files = [item for item in sorted(path.rglob("*")) if item.is_file()]
        if not artifact_files:
            st.info(f"Artifact directory is empty: `{path}`")
            return

        st.caption(f"Artifact directory: `{path}`")
        for artifact_file in artifact_files:
            render_artifact_file(artifact_file)
        return

    st.info("No local artifacts found for this run.")
    st.caption(
        "Checked: "
        + ", ".join(f"`{candidate}`" for candidate in candidates)
    )


def compare_run_plot_key(top_path: Path, bottom_path: Path, thing: str, material: str) -> str:
    key_text = f"{top_path}_{bottom_path}_{thing}_{material}"
    return "compare_run_" + re.sub(r"\W+", "_", key_text)

def selected_compare_materials(
    top_path: Path,
    bottom_path: Path,
    thing: str,
    materials: list[str],
) -> list[str]:
    checkbox_columns = st.columns(min(4, len(materials)))
    selected = []
    for index, material in enumerate(materials):
        enabled = checkbox_columns[index % len(checkbox_columns)].checkbox(
            material,
            value=True,
            key=compare_run_plot_key(top_path, bottom_path, thing, material),
        )
        if enabled:
            selected.append(material)
    return selected

def parquet_thing_series(path: Path) -> tuple[str | None, dict[str, pd.DataFrame]]:
    dataframe = pd.read_parquet(path)
    time_column = find_time_column(dataframe)
    if time_column is None:
        return None, {}
    return time_column, parquet_series_by_thing(dataframe, time_column, path.stem)

def compare_run_parquet_pairs(
    top_run: pd.Series,
    bottom_run: pd.Series,
    artifact_root: str,
) -> list[dict[str, object]]:
    top_files = parquet_files_for_run(top_run, artifact_root)
    bottom_files = parquet_files_for_run(bottom_run, artifact_root)
    pairs = []
    for name in sorted(set(top_files).intersection(bottom_files)):
        top_path = top_files[name]
        bottom_path = bottom_files[name]
        top_time_column, top_groups = parquet_thing_series(top_path)
        bottom_time_column, bottom_groups = parquet_thing_series(bottom_path)
        if top_time_column is None or bottom_time_column is None:
            continue

        shared_things = sorted(set(top_groups).intersection(bottom_groups))
        if not shared_things:
            continue

        pairs.append(
            {
                "name": name,
                "top_path": top_path,
                "bottom_path": bottom_path,
                "top_time_column": top_time_column,
                "bottom_time_column": bottom_time_column,
                "top_groups": top_groups,
                "bottom_groups": bottom_groups,
                "shared_things": shared_things,
            }
        )
    return pairs

def render_compare_run_series_plot(
    top_path: Path,
    bottom_path: Path,
    thing: str,
    top_series: pd.DataFrame,
    bottom_series: pd.DataFrame,
    top_time_column: str,
    bottom_time_column: str,
    top_label: str,
    bottom_label: str,
    plot_height: int,
) -> None:
    top_materials = set(top_series["material"].astype(str).unique())
    bottom_materials = set(bottom_series["material"].astype(str).unique())
    shared_materials = sorted(top_materials.intersection(bottom_materials))
    if not shared_materials:
        st.info(f"No shared materials for `{thing}`.")
        return

    st.markdown(f"**{thing}**")
    selected_materials_for_plot = selected_compare_materials(
        top_path,
        bottom_path,
        thing,
        shared_materials,
    )
    if not selected_materials_for_plot:
        st.info("Select at least one material to plot.")
        return

    figure = go.Figure()
    palette = px.colors.qualitative.Plotly
    color_by_material = {
        material: palette[index % len(palette)]
        for index, material in enumerate(shared_materials)
    }
    for material in selected_materials_for_plot:
        top_material_data = top_series[top_series["material"].astype(str) == material]
        bottom_material_data = bottom_series[bottom_series["material"].astype(str) == material]
        figure.add_trace(
            go.Scatter(
                x=top_material_data[top_time_column],
                y=top_material_data["value"],
                mode="lines",
                name=f"{material} ({top_label})",
                legendgroup=material,
                line={"color": color_by_material[material], "dash": "solid"},
            )
        )
        figure.add_trace(
            go.Scatter(
                x=bottom_material_data[bottom_time_column],
                y=bottom_material_data["value"],
                mode="lines",
                name=f"{material} ({bottom_label})",
                legendgroup=material,
                line={"color": color_by_material[material], "dash": "dash"},
            )
        )

    figure.update_layout(
        height=plot_height,
        margin={"l": 10, "r": 10, "t": 44, "b": 10},
        title=f"{top_path.name}: {thing}",
        xaxis_title=top_time_column,
        yaxis_title=thing,
    )
    st.plotly_chart(figure, use_container_width=True)

def show_compare_run_artifacts(
    top_run: pd.Series,
    bottom_run: pd.Series,
    artifact_root: str,
    plot_height: int,
) -> None:
    top_label = "top"
    bottom_label = "bottom"
    for pair in compare_run_parquet_pairs(top_run, bottom_run, artifact_root):
        top_path = pair["top_path"]
        bottom_path = pair["bottom_path"]
        with st.expander(str(pair["name"]), expanded=False):
            st.caption(f"Top: `{top_path}`")
            st.caption(f"Bottom: `{bottom_path}`")
            for thing in pair["shared_things"]:
                render_compare_run_series_plot(
                    top_path=top_path,
                    bottom_path=bottom_path,
                    thing=thing,
                    top_series=pair["top_groups"][thing],
                    bottom_series=pair["bottom_groups"][thing],
                    top_time_column=pair["top_time_column"],
                    bottom_time_column=pair["bottom_time_column"],
                    top_label=top_label,
                    bottom_label=bottom_label,
                    plot_height=plot_height,
                )
