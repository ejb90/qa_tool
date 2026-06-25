import datetime
import random
import uuid

from pydantic import BaseModel


class Run(BaseModel):
    name: str
    version: str
    date: datetime.datetime
    uid: str

    density: float
    velocity: float
    error: float
    runtime: float
    memory_hwm: float


def build_data() -> list[Run]:
    """"""
    versions = ["v1.0.0", "v1.1.0", "v1.2.0", "v1.2.1", "v1.2.2", "v1.3.0", "v1.4.0", "v2.0.0", "v2.1.0", "v2.2.0", "v3.0.0"]
    models = ["He", "Ne", "Xe", "Ar", "Kr", "Rn"]
    ref_density_rtp_kg_m3 = {
        "He": 0.166,
        "Ne": 0.841,
        "Ar": 1.664,
        "Kr": 3.491,
        "Xe": 5.475,
        "Rn": 9.25,
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
        for model in models:
            for j in range(random.randint(0, 3)):
                uid = str(uuid.uuid4())
                run_name = f"{model}-{version}-{uid}"
                density = ref_density_rtp_kg_m3[model] + random.uniform(-0.05, 0.05)
                velocity = 1/ref_density_rtp_kg_m3[model] * random.uniform(0.0, 0.1)
                error = random.uniform(0.0, 0.1)
                runtime = max(0.1, random.gauss(5.0, 2.0))
                memory_hwm = max(4.0, random.gauss(7.0, 1.0))

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
                    )
                )
    return runs

