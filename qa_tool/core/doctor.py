"""Read-only validation of QA Tool DuckDB databases."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb

from qa_tool.ingest.core import (
    NUMERIC_TYPE_PREFIXES,
    configured_column_types,
    quote_identifier,
    required_columns,
    table_columns,
    table_exists,
)


@dataclass(frozen=True)
class DoctorFinding:
    """One actionable database-contract violation."""

    code: str
    message: str
    details: dict[str, object]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable finding."""
        return asdict(self)


@dataclass(frozen=True)
class DoctorReport:
    """Complete result of one read-only database inspection."""

    database: str
    runs_table: str
    summary_table: str
    run_count: int | None
    findings: tuple[DoctorFinding, ...]

    @property
    def passed(self) -> bool:
        """Return whether the database satisfies the configured contract."""
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        """Return the stable machine-readable report structure."""
        return {
            "status": "passed" if self.passed else "failed",
            "database": self.database,
            "runs_table": self.runs_table,
            "summary_table": self.summary_table,
            "run_count": self.run_count,
            "finding_count": len(self.findings),
            "findings": [finding.to_dict() for finding in self.findings],
        }


def _finding(code: str, message: str, **details: object) -> DoctorFinding:
    """Create a finding with consistently ordered detail fields."""
    return DoctorFinding(code=code, message=message, details=dict(sorted(details.items())))


def _missing_value_count(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    column: str,
) -> int:
    """Count null or blank values in one required column."""
    result = connection.execute(
        f"SELECT COUNT(*) FROM {quote_identifier(table_name)} "
        f"WHERE {quote_identifier(column)} IS NULL "
        f"OR TRIM(CAST({quote_identifier(column)} AS VARCHAR)) = ''"
    ).fetchone()
    return int(result[0]) if result else 0


def _summary_expectations(
    connection: duckdb.DuckDBPyConnection,
    runs_table: str,
    columns: dict[str, str],
    summary_settings: dict[str, Any],
) -> dict[str, object]:
    """Calculate the values produced by ingestion's summary refresh."""
    expressions = ["COUNT(*) AS run_count"]
    for column in summary_settings.get("distinct_columns", []):
        if column in columns:
            expressions.append(f"COUNT(DISTINCT {quote_identifier(column)}) AS {quote_identifier(f'{column}_count')}")
    for column in summary_settings.get("mean_columns", []):
        if columns.get(column, "").upper().startswith(NUMERIC_TYPE_PREFIXES):
            expressions.append(f"AVG({quote_identifier(column)}) AS {quote_identifier(f'mean_{column}')}")
    cursor = connection.execute(f"SELECT {', '.join(expressions)} FROM {quote_identifier(runs_table)}")
    values = cursor.fetchone()
    names = [description[0] for description in cursor.description]
    return dict(zip(names, values or (), strict=True))


def _values_equal(expected: object, actual: object) -> bool:
    """Compare summary values while tolerating insignificant float rounding."""
    if expected is None or actual is None:
        return expected is actual
    if isinstance(expected, int | float) and isinstance(actual, int | float):
        return math.isclose(float(expected), float(actual), rel_tol=1e-12, abs_tol=1e-12)
    return expected == actual


def _inspect_summary(
    connection: duckdb.DuckDBPyConnection,
    runs_table: str,
    summary_table: str,
    columns: dict[str, str],
    summary_settings: dict[str, Any],
) -> list[DoctorFinding]:
    """Report missing or stale precomputed summary data."""
    if not table_exists(connection, summary_table):
        return [
            _finding(
                "missing_summary_table",
                f"Configured summary table `{summary_table}` does not exist.",
                table=summary_table,
            )
        ]

    summary_columns = table_columns(connection, summary_table)
    findings: list[DoctorFinding] = []
    if "refreshed_at" not in summary_columns:
        findings.append(
            _finding(
                "missing_summary_column",
                "Summary table is missing `refreshed_at`.",
                column="refreshed_at",
                table=summary_table,
            )
        )
    row_count_result = connection.execute(f"SELECT COUNT(*) FROM {quote_identifier(summary_table)}").fetchone()
    row_count = int(row_count_result[0]) if row_count_result else 0
    if row_count != 1:
        findings.append(
            _finding(
                "invalid_summary_row_count",
                f"Summary table must contain exactly one row; found {row_count}.",
                actual=row_count,
                expected=1,
                table=summary_table,
            )
        )
        return findings

    expected = _summary_expectations(connection, runs_table, columns, summary_settings)
    for column in expected:
        if column not in summary_columns:
            findings.append(
                _finding(
                    "missing_summary_column",
                    f"Summary table is missing `{column}`.",
                    column=column,
                    table=summary_table,
                )
            )
    comparable = [column for column in expected if column in summary_columns]
    if not comparable:
        return findings
    actual_row = connection.execute(
        f"SELECT {', '.join(quote_identifier(column) for column in comparable)} FROM {quote_identifier(summary_table)}"
    ).fetchone()
    actual = dict(zip(comparable, actual_row or (), strict=True))
    for column in comparable:
        if not _values_equal(expected[column], actual[column]):
            findings.append(
                _finding(
                    "stale_summary",
                    f"Summary value `{column}` disagrees with the runs table.",
                    actual=repr(actual[column]),
                    column=column,
                    expected=repr(expected[column]),
                    table=summary_table,
                )
            )
    return findings


def inspect_database(
    database_path: str | Path,
    dashboard_settings: dict[str, Any],
    ingestion_settings: dict[str, Any],
) -> DoctorReport:
    """Inspect a DuckDB database without modifying it.

    The ingestion settings define the stored tables, required columns, declared
    types, and summary contract. Dashboard settings define the physical columns
    mapped to the canonical ``model`` and ``version`` fields.
    """
    path = Path(database_path)
    database_settings = ingestion_settings["database"]
    runs_table = str(database_settings["runs_table"])
    summary_table = str(database_settings["summary_table"])
    findings: list[DoctorFinding] = []
    report_arguments = {
        "database": str(path),
        "runs_table": runs_table,
        "summary_table": summary_table,
    }

    if path.suffix != ".duckdb":
        findings.append(
            _finding(
                "invalid_database_extension",
                "QA Tool requires a database with a `.duckdb` extension.",
                path=str(path),
            )
        )
        return DoctorReport(**report_arguments, run_count=None, findings=tuple(findings))
    if not path.exists():
        findings.append(_finding("missing_database", f"Database does not exist: {path}", path=str(path)))
        return DoctorReport(**report_arguments, run_count=None, findings=tuple(findings))

    required = required_columns(ingestion_settings)
    declared_types = configured_column_types(ingestion_settings)
    dashboard_columns = dashboard_settings.get("database", {}).get("columns", {})
    mappings = {
        "model": str(dashboard_columns.get("model", "model")),
        "version": str(dashboard_columns.get("version", "version")),
    }

    try:
        connection_context = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as error:
        findings.append(
            _finding(
                "unreadable_database",
                f"Could not open database read-only: {error}",
                path=str(path),
            )
        )
        return DoctorReport(**report_arguments, run_count=None, findings=tuple(findings))

    run_count: int | None = None
    with connection_context as connection:
        if not table_exists(connection, runs_table):
            findings.append(
                _finding(
                    "missing_runs_table",
                    f"Configured runs table `{runs_table}` does not exist.",
                    table=runs_table,
                )
            )
            return DoctorReport(**report_arguments, run_count=None, findings=tuple(findings))

        columns = table_columns(connection, runs_table)
        count_result = connection.execute(f"SELECT COUNT(*) FROM {quote_identifier(runs_table)}").fetchone()
        run_count = int(count_result[0]) if count_result else 0

        for column in required:
            if column not in columns:
                findings.append(
                    _finding(
                        "missing_required_column",
                        f"Runs table is missing required column `{column}`.",
                        column=column,
                        table=runs_table,
                    )
                )
                continue
            missing_count = _missing_value_count(connection, runs_table, column)
            if missing_count:
                findings.append(
                    _finding(
                        "missing_required_values",
                        f"Required column `{column}` has {missing_count} null or blank value(s).",
                        column=column,
                        count=missing_count,
                        table=runs_table,
                    )
                )

        for canonical, physical in mappings.items():
            if physical not in columns:
                findings.append(
                    _finding(
                        "unresolved_dashboard_mapping",
                        f"Dashboard `{canonical}` mapping refers to missing column `{physical}`.",
                        canonical=canonical,
                        column=physical,
                        table=runs_table,
                    )
                )
            elif physical != canonical and canonical in columns:
                findings.append(
                    _finding(
                        "dashboard_mapping_collision",
                        f"Cannot map `{physical}` to `{canonical}` because `{canonical}` already exists.",
                        canonical=canonical,
                        column=physical,
                        table=runs_table,
                    )
                )

        for column, expected_type in declared_types.items():
            if column not in columns:
                findings.append(
                    _finding(
                        "missing_declared_column",
                        f"Declared column `{column}` does not exist in the runs table.",
                        column=column,
                        expected_type=expected_type,
                        table=runs_table,
                    )
                )
            elif columns[column].upper() != expected_type:
                findings.append(
                    _finding(
                        "incompatible_declared_type",
                        f"Column `{column}` has type {columns[column]}, expected {expected_type}.",
                        actual_type=columns[column],
                        column=column,
                        expected_type=expected_type,
                        table=runs_table,
                    )
                )

        if "uid" in columns:
            duplicate_result = connection.execute(
                f"SELECT COUNT(*) FROM ("
                f"SELECT CAST({quote_identifier('uid')} AS VARCHAR) FROM {quote_identifier(runs_table)} "
                f"WHERE {quote_identifier('uid')} IS NOT NULL "
                f"GROUP BY CAST({quote_identifier('uid')} AS VARCHAR) HAVING COUNT(*) > 1)"
            ).fetchone()
            duplicate_count = int(duplicate_result[0]) if duplicate_result else 0
            if duplicate_count:
                findings.append(
                    _finding(
                        "duplicate_uids",
                        f"Runs table contains {duplicate_count} duplicated UID value(s).",
                        count=duplicate_count,
                        table=runs_table,
                    )
                )

        if "date" in columns:
            invalid_date_result = connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(runs_table)} "
                f"WHERE {quote_identifier('date')} IS NOT NULL "
                f"AND TRIM(CAST({quote_identifier('date')} AS VARCHAR)) <> '' "
                f"AND TRY_CAST({quote_identifier('date')} AS TIMESTAMP) IS NULL"
            ).fetchone()
            invalid_date_count = int(invalid_date_result[0]) if invalid_date_result else 0
            if invalid_date_count:
                findings.append(
                    _finding(
                        "invalid_dates",
                        f"Column `date` contains {invalid_date_count} value(s) that are not valid timestamps.",
                        column="date",
                        count=invalid_date_count,
                        table=runs_table,
                    )
                )

        findings.extend(
            _inspect_summary(
                connection,
                runs_table,
                summary_table,
                columns,
                ingestion_settings.get("summary", {}),
            )
        )

    return DoctorReport(**report_arguments, run_count=run_count, findings=tuple(findings))
