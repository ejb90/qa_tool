"""Console launcher for the packaged Streamlit web application."""

from __future__ import annotations

import subprocess
import sys
from importlib.resources import files


def main() -> None:
    """Start Streamlit with QA Tool's packaged application module."""
    app_path = files("qa_tool_webapp").joinpath("app.py")
    result = subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path), *sys.argv[1:]], check=False)
    raise SystemExit(result.returncode)
