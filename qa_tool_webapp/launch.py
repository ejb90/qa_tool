"""Console launcher for the packaged Streamlit web application."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from importlib.resources import files


def launch_webapp(arguments: Sequence[str] = ()) -> int:
    """Start Streamlit with the packaged application and return its exit code."""
    app_path = files("qa_tool_webapp").joinpath("app.py")
    result = subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path), *arguments], check=False)
    return result.returncode


def main() -> None:
    """Start Streamlit with QA Tool's packaged application module."""
    raise SystemExit(launch_webapp(sys.argv[1:]))
