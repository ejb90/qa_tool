from __future__ import annotations

import re
import zipfile
from io import BytesIO

import pandas as pd
import streamlit as st


def export_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_") or "data"


def dataframes_to_zip(dataframes: dict[str, pd.DataFrame]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, dataframe in dataframes.items():
            archive.writestr(
                f"{export_name(name)}.csv",
                dataframe.to_csv(index=False),
            )
    return buffer.getvalue()


def show_export_download(
    label: str,
    dataframes: dict[str, pd.DataFrame],
    file_name: str,
    key: str,
) -> None:
    if not dataframes:
        return
    st.download_button(
        label,
        data=dataframes_to_zip(dataframes),
        file_name=file_name,
        mime="application/zip",
        key=key,
        use_container_width=True,
    )
