"""Small SQLAlchemy store for Run instances from build_dummy_data.py."""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Index, String, create_engine, func, select, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

try:
    from qa_tool.build_dummy_data import Run, build_data
except ModuleNotFoundError:
    from build_dummy_data import Run, build_data


class Base(DeclarativeBase):
    pass


class RunRecord(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("idx_runs_model_version", "model", "version"),
        Index("idx_runs_version", "version"),
        Index("idx_runs_date", "date"),
    )

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    modified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    density: Mapped[float] = mapped_column(Float, nullable=False)
    velocity: Mapped[float] = mapped_column(Float, nullable=False)
    error: Mapped[float] = mapped_column(Float, nullable=False)
    runtime: Mapped[float] = mapped_column(Float, nullable=False)
    memory_hwm: Mapped[float] = mapped_column(Float, nullable=False)


def model_from_run(run: Run) -> str:
    return run.name.split("-", maxsplit=1)[0]


def run_to_dict(run: Run) -> dict[str, object]:
    return {
        "uid": run.uid,
        "name": run.name,
        "model": model_from_run(run),
        "version": run.version,
        "date": run.date,
        "density": run.density,
        "velocity": run.velocity,
        "error": run.error,
        "runtime": run.runtime,
        "memory_hwm": run.memory_hwm,
        "modified": run.modified,
    }


def make_engine(db_path: str | Path = "runs.db"):
    return create_engine(f"sqlite:///{Path(db_path)}")


def write_runs(runs: Iterable[Run], db_path: str | Path = "runs.db") -> int:
    rows = [run_to_dict(run) for run in runs]
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)

    if rows:
        statement = insert(RunRecord).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=[RunRecord.uid],
            set_={
                column.name: statement.excluded[column.name]
                for column in RunRecord.__table__.columns
                if column.name != "uid"
            },
        )
        with Session(engine) as session:
            session.execute(statement)
            session.commit()

    return len(rows)


def normalize_run_dates(db_path: str | Path = "runs.db") -> None:
    """Normalize legacy ISO datetime strings to SQLAlchemy's SQLite format."""
    engine = make_engine(db_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE runs
                SET date = replace(date, 'T', ' ') || '.000000'
                WHERE instr(date, 'T') > 0
                  AND instr(date, '.') = 0
                """
            )
        )


def fetch_metric_averages(
    db_path: str | Path = "runs.db",
) -> list[tuple[str, str, float, float, float, float, float, int]]:
    engine = make_engine(db_path)
    statement = (
        select(
            RunRecord.model,
            RunRecord.version,
            func.avg(RunRecord.density),
            func.avg(RunRecord.velocity),
            func.avg(RunRecord.error),
            func.avg(RunRecord.runtime),
            func.avg(RunRecord.memory_hwm),
            func.count(),
        )
        .group_by(RunRecord.model, RunRecord.version)
        .order_by(RunRecord.model, RunRecord.version)
    )
    with Session(engine) as session:
        return list(session.execute(statement).all())


if __name__ == "__main__":
    row_count = write_runs(build_data())
    print(f"Wrote {row_count} runs to runs.db")
