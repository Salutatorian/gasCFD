import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LB_TO_KG = 0.45359237
MPH_TO_MPS = 0.44704


def vehicle_dir() -> Path:
    override = os.environ.get("GASCFD_VEHICLE_DIR")
    if override:
        return Path(override)
    return ROOT / "vehicles" / "toyota-matrix-2004"


def runs_dir() -> Path:
    override = os.environ.get("GASCFD_RUNS")
    if override:
        return Path(override)
    return ROOT / "runs"


def geometry_file(relative: str) -> Path:
    root = vehicle_dir().resolve()
    path = (root / relative).resolve()
    path.relative_to(root)
    return path
