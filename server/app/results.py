import json
import re
from pathlib import Path

from app.road_load import aero_power_w

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_FORCE_LINE = re.compile(
    rf"({_NUMBER})\s+\(\(\s*({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s*\)\s+"
    rf"\(\s*({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s*\)\s+"
    rf"\(\s*({_NUMBER})\s+({_NUMBER})\s+({_NUMBER})\s*\)\s*\)"
)
_CAP_MARKERS = ("cell limit", "maximum number of cells", "maxglobalcells")


def parse_case(case_dir: Path) -> dict[str, object]:
    meta_path = case_dir / "gascfd.json"
    if not meta_path.exists():
        raise ValueError("The OpenFOAM case has no gascfd.json metadata.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    forces = _find(case_dir, "forces.dat")
    coefficients = _find(case_dir, "coefficient.dat") or _find(case_dir, "forceCoeffs.dat")
    speed = float(meta["speed_m_s"])
    rho = float(meta["rho"])
    aref = float(meta["aref_m2"])
    dynamic = 0.5 * rho * speed * speed

    drag_n: float | None = None
    lift_n: float | None = None
    side_n: float | None = None
    samples = 0
    source = ""
    cd: float | None = None
    cl: float | None = None

    if forces is not None:
        parsed = _parse_forces(forces)
        if parsed is not None:
            drag_n, side_n, lift_n, samples = parsed
            source = "openfoam-forces"
            if dynamic > 0 and aref > 0:
                cd = drag_n / (dynamic * aref)
                cl = lift_n / (dynamic * aref)
    if drag_n is None and coefficients is not None:
        parsed_coeffs = _parse_coefficients(coefficients)
        if parsed_coeffs is not None:
            cd, cl, samples = parsed_coeffs
            source = "openfoam-forceCoeffs"
            if dynamic > 0 and aref > 0:
                drag_n = cd * dynamic * aref
                lift_n = cl * dynamic * aref
    if drag_n is None or lift_n is None or cd is None or cl is None:
        raise ValueError("OpenFOAM finished without force samples.")

    log_text = ""
    log_path = case_dir / "log.txt"
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace").lower()
    return {
        "experiment_id": meta["experiment_id"],
        "speed_mph": meta["speed_mph"],
        "speed_m_s": meta["speed_m_s"],
        "yaw_deg": meta["yaw_deg"],
        "recipe": meta["recipe"],
        "cd": cd,
        "cl": cl,
        "drag_n": drag_n,
        "lift_n": lift_n,
        "side_n": side_n,
        "aero_power_w": aero_power_w(drag_n, speed),
        "aero_power_from": "drag_n * speed_m_s",
        "aref_m2": aref,
        "rho": rho,
        "samples": samples,
        "geometry_sha256": meta["geometry_sha256"],
        "geometry_signed_off": meta["geometry_signed_off"],
        "mesh_hit_cell_cap": any(marker in log_text for marker in _CAP_MARKERS),
        "source": source,
        "moving_ground": False,
        "rotating_wheels": False,
    }


def _find(case_dir: Path, name: str) -> Path | None:
    matches = sorted(case_dir.glob(f"postProcessing/**/{name}"))
    if not matches:
        return None
    return matches[-1]


def _tail(values: list[float]) -> tuple[float, int]:
    start = int(len(values) * 0.8)
    if start >= len(values):
        start = len(values) - 1
    sample = values[start:]
    return sum(sample) / len(sample), len(sample)


def _parse_forces(path: Path) -> tuple[float, float, float, int] | None:
    drag: list[float] = []
    side: list[float] = []
    lift: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _FORCE_LINE.search(line)
        if not match:
            continue
        drag.append(float(match.group(2)) + float(match.group(5)) + float(match.group(8)))
        side.append(float(match.group(3)) + float(match.group(6)) + float(match.group(9)))
        lift.append(float(match.group(4)) + float(match.group(7)) + float(match.group(10)))
    if not drag:
        return None
    drag_n, samples = _tail(drag)
    side_n, _ = _tail(side)
    lift_n, _ = _tail(lift)
    return drag_n, side_n, lift_n, samples


def _parse_coefficients(path: Path) -> tuple[float, float, int] | None:
    header: list[str] | None = None
    rows: list[list[float]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if "Cd" in line and "Time" in line:
                header = line.lstrip("#").split()
            continue
        try:
            rows.append([float(part) for part in line.split()])
        except ValueError:
            continue
    if not rows or not header or "Cd" not in header or "Cl" not in header:
        return None
    cd_index = header.index("Cd")
    cl_index = header.index("Cl")
    cd, samples = _tail([row[cd_index] for row in rows])
    cl, _ = _tail([row[cl_index] for row in rows])
    return cd, cl, samples
