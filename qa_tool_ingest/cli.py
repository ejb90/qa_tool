"""Compatibility wrapper for the unified QA Tool command tree."""

from qa_tool_cli.cli import ingest_main


def main() -> None:
    """Run the legacy ingestion entry point through ``qa-tool ingest``."""
    ingest_main()
