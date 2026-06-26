import datetime
import random
import uuid

from pydantic import BaseModel


class Run(BaseModel):
    name: str
    version: str
    date: datetime.datetime
    uid: str
    modified: bool

    density: float
    velocity: float
    error: float
    runtime: float
    memory_hwm: float


def build_data() -> list[Run]:
    """"""
    versions = ["v1.0.0", "v1.1.0", "v1.2.0", "v1.2.1", "v1.2.2", "v1.3.0", "v1.4.0", "v2.0.0", "v2.1.0", "v2.2.0", "v3.0.0", "v3.1.0", "v3.2.0", "v3.3.0", "v4.0.0", "v4.1.0", "v4.2.0", "v5.0.0", "v5.1.0", "v5.2.0", "v6.0.0", "v6.1.0", "v6.2.0"]
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
            random.randint(0, 59)
        )
        for model in gas_density_rtp_kg_m3:
            for j in range(random.randint(0, 7)):
                uid = str(uuid.uuid4())
                run_name = f"{model}-{version}-{uid}"
                density = gas_density_rtp_kg_m3[model] + random.uniform(-0.05, 0.05)
                velocity = 1/gas_density_rtp_kg_m3[model]**2 * random.uniform(0.0, 0.1)
                error = random.uniform(0.0, 0.1)
                runtime = max(0.1, random.gauss(5.0, 2.0))
                memory_hwm = max(4.0, random.gauss(7.0, 1.0))
                modified = random.random() < 0.30

                runs.append(
                    Run(
                    name=run_name,
                    version=version,
                    date=date,
                    uid=uid,
                    density=density,
                    velocity=velocity,
                    error=error,
                    runtime=runtime,
                    memory_hwm=memory_hwm,
                    modified=modified,
                    )
                )
    return runs

