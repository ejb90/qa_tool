"""QA dashboard module for build dummy data."""

import datetime
import json
import random
import uuid
from pathlib import Path

import numpy as np
import polars as pl
from pydantic import BaseModel


class Run(BaseModel):
    """Represent Run."""

    name: str
    version: str
    model: str
    date: datetime.datetime
    uid: str
    modified: bool

    density: float
    velocity: float
    error: float
    metrics: dict[str, float]
    artifact: Path | None = None

    def model_post_init(self, __context: dict) -> None:
        """Handle model post init."""
        self.artifact = Path("store") / self.name
        self.build_dummy_parquets()
        self.save_json(self.artifact / "metadata.json")

    def build_dummy_parquets(self) -> None:
        """Handle build dummy parquets."""
        generate_material_parquet_files(
            self.artifact, mean_density=self.density, mean_velocity=self.velocity, seed=random.randint(0, 1000000)
        )

    def save_json(self, path: str | Path) -> None:
        """Handle save json."""
        metadata = self.model_dump(mode="json")
        metadata.update(metadata.pop("metrics"))
        Path(path).write_text(json.dumps(metadata, indent=2))


def generate_material_parquet_files(
    output_dir: str | Path,
    seed: int | None = None,
    base_rows: int = 1000,
    variation: int = 250,
    mean_density: float = 1.0,
    mean_velocity: float = 1.0,
) -> None:
    """Generate 5 parquet files containing a time column and three material columns.

    Files generated:
        density.parquet
        velocity.parquet
        pressure.parquet
        error.parquet
        memory.parquet

    Each file has columns:
        time, material_1, material_2, material_3

    The number of rows varies randomly around `base_rows`, and may be as low as 0.
    """
    rng = np.random.default_rng(seed)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    quantities = {
        "density": {
            "scale": 1.223,
            "noise": 0.05,
            "offset": 1.0,
        },
        "velocity": {
            "scale": 100.0,
            "noise": 5.0,
            "offset": 0.0,
        },
        "pressure": {
            "scale": 1.0e5,
            "noise": 2.0e3,
            "offset": 1.0e5,
        },
        "error": {
            "scale": 1.0e-3,
            "noise": 2.0e-4,
            "offset": 0.0,
        },
        "memory": {
            "scale": 500.0,
            "noise": 25.0,
            "offset": 1000.0,
        },
    }

    for quantity, params in quantities.items():
        if quantity == "density":
            params["scale"] = mean_density
        elif quantity == "velocity":
            params["scale"] = mean_velocity

        # Random row count, usually near 1000, but can occasionally be very small.
        n_rows = max(0, int(rng.normal(loc=base_rows, scale=variation)))

        # Small chance of producing a near-empty or empty file.
        if rng.random() < 0.1:
            n_rows = int(rng.integers(0, 50))

        if n_rows == 0:
            df = pl.DataFrame(
                schema={
                    "time": pl.Float64,
                    "material_1": pl.Float64,
                    "material_2": pl.Float64,
                    "material_3": pl.Float64,
                }
            )
        else:
            time = np.linspace(0.0, 1.0, n_rows)

            df = pl.DataFrame(
                {
                    "time": time,
                    "material_1": (
                        params["offset"]
                        + params["scale"] * np.sin(2 * np.pi * time)
                        + rng.normal(0.0, params["noise"], n_rows)
                    ),
                    "material_2": (
                        params["offset"]
                        + params["scale"] * np.cos(2 * np.pi * time)
                        + rng.normal(0.0, params["noise"], n_rows)
                    ),
                    "material_3": (
                        params["offset"]
                        + params["scale"] * np.sin(4 * np.pi * time)
                        + rng.normal(0.0, params["noise"], n_rows)
                    ),
                }
            )

        df.write_parquet(output_dir / f"{quantity}.parquet")


def build_data(max_runs: int = 7, major_versions: int = 10) -> list[Run]:
    """Build a randomized collection of dummy runs."""
    versions = []
    for i in range(1, major_versions + 1):
        for j in range(0, np.random.randint(0, 12)):
            for k in range(0, np.random.randint(0, 10)):
                versions.append(f"v{i}.{j}.{k}")

    gas_density_rtp_kg_m3 = {
        # Noble gases
        "He": 0.166,
        "Ne": 0.841,
        "Ar": 1.664,
        "Kr": 3.491,
        "Xe": 5.475,
        "Rn": 9.25,
        # Common atmospheric / diatomic gases
        "H2": 0.084,
        "N2": 1.165,
        "O2": 1.331,
        "F2": 1.580,
        "Cl2": 2.950,
        # Common molecular gases
        "CO": 1.165,
        "CO2": 1.831,
        "NO": 1.249,
        "NO2": 1.914,
        "N2O": 1.831,
        "SO2": 2.665,
        "H2S": 1.417,
        "NH3": 0.708,
        # Hydrocarbons / fuel gases
        "CH4": 0.667,
        "C2H2": 1.083,
        "C2H4": 1.166,
        "C2H6": 1.251,
        "C3H8": 1.834,
        "C4H10": 2.416,
        # Refrigerant / heavier gases
        "SF6": 6.080,
        "CF4": 3.663,
    }

    runs = []
    for i, version in enumerate(versions):
        date = datetime.datetime(
            2026,
            min(12, max(1, i + random.randint(-2, 2) + 1)),
            random.randint(1, 28),
            random.randint(0, 23),
            random.randint(0, 59),
            random.randint(0, 59),
            tzinfo=datetime.UTC,
        )
        for model in gas_density_rtp_kg_m3:
            for _j in range(random.randint(0, max_runs)):
                uid = str(uuid.uuid4())
                run_name = f"{model}-{version}-{uid}"
                density = gas_density_rtp_kg_m3[model] + random.uniform(-0.05, 0.05)
                velocity = 1 / gas_density_rtp_kg_m3[model] ** 2 * random.uniform(0.0, 0.1)
                error = random.uniform(0.0, 0.1)
                metrics = {
                    "sample_metric_a": max(0.1, random.gauss(5.0, 2.0)),
                    "sample_metric_b": max(4.0, random.gauss(7.0, 1.0)),
                }
                modified = random.random() < 0.30

                runs.append(
                    Run(
                        name=run_name,
                        model=model,
                        version=version,
                        date=date,
                        uid=uid,
                        density=density,
                        velocity=velocity,
                        error=error,
                        metrics=metrics,
                        modified=modified,
                    )
                )
    return runs


build_data(max_runs=5, major_versions=50)
