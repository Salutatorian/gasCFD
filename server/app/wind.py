"""On-the-fly tunnel runs: open wheels versus flush arch covers."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from app.catalog import experiment_by_id, geometry_report, load_vehicle
from app.geometry import read_triangles
from app.paths import MPH_TO_MPS, geometry_file, runs_dir
from app.recipe import RHO
from app.road_load import RoadLoadAssumptions, drag_from_cd, worksheet
from app.airfield import color_field, fluidx_lines, slice_bytes, vortex_bytes
from app.tunnel import (
    TunnelError,
    flow_field,
    pack_lines,
    prepare_mask,
    solve_mask,
)
from app.wheel_wells import boxes_stl, find_wheels, well_boxes

DX = 0.1
U_LB = 0.06
REYNOLDS = 80
_LOCK = threading.Lock()
_running: dict[str, object] | None = None
_pending: tuple[int, bool, bool] | None = None
_error: str | None = None


def stock_path() -> Path:
    experiment = experiment_by_id("001")
    if experiment is None:
        raise FileNotFoundError("Stock experiment 001 is missing.")
    relative = experiment["geometry"]
    if not isinstance(relative, str):
        raise FileNotFoundError("Stock geometry path is missing.")
    return geometry_file(relative)


def box_bytes(front: bool, rear: bool) -> bytes:
    if not front and not rear:
        return boxes_stl([])
    triangles = read_triangles(stock_path().read_bytes())
    wheels = find_wheels(triangles)
    boxes = well_boxes(wheels, triangles, front=front, rear=rear)
    if not boxes:
        raise FileNotFoundError("No wheels were found on this car, so there is nowhere to put a box.")
    return boxes_stl(boxes)


def start(speed_mph: int, front: bool, rear: bool) -> dict[str, object]:
    global _pending
    with _LOCK:
        if _running is not None:
            _pending = (speed_mph, front, rear)
        else:
            _launch(speed_mph, front, rear)
    return status()


def status() -> dict[str, object]:
    with _LOCK:
        running = dict(_running) if _running is not None else None
    return {"running": running is not None, "job": running, "error": _error, "cached": _cached_speeds()}


def result_for(speed_mph: int, front: bool, rear: bool) -> dict[str, object] | None:
    path = _folder(speed_mph, front, rear) / "result.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    stock = payload
    stock_path = _folder(speed_mph, False, False) / "result.json"
    if stock_path.exists():
        stock = json.loads(stock_path.read_text(encoding="utf-8"))
    published = _published()
    published["speed_m_s"] = speed_mph * MPH_TO_MPS
    payload["stock_tunnel_drag_n"] = float(stock["drag_n"])
    payload["fuel"] = fuel_view(
        float(payload["drag_n"]),
        float(stock["drag_n"]),
        published,
        covered=bool(payload["front"] or payload["rear"]),
    )
    return payload


def lines_path(speed_mph: int, front: bool, rear: bool) -> Path:
    return _folder(speed_mph, front, rear) / "streamlines.bin"


def vortex_path(speed_mph: int, front: bool, rear: bool) -> Path:
    return _folder(speed_mph, front, rear) / "vortices.bin"


def slice_path(speed_mph: int, front: bool, rear: bool) -> Path:
    return _folder(speed_mph, front, rear) / "slice.bin"


def fuel_view(
    tunnel_drag_n: float,
    stock_drag_n: float,
    published: dict[str, float],
    *,
    covered: bool = False,
) -> dict[str, float | None | str]:
    """Scale the brochure drag by the tunnel's drag ratio.

    The tunnel's own Cd is several times the brochure because the grid is
    coarse. Fuel uses the change, not that Cd.
    """
    if stock_drag_n <= 0 or published["area_m2"] <= 0:
        return {"drag_n": None, "cd": None, "mpg": None, "stock_mpg": None, "drag_ratio": None, "note": "No stock drag yet."}
    ratio = tunnel_drag_n / stock_drag_n
    speed = published["speed_m_s"]
    base = drag_from_cd(published["cd"], speed, published["area_m2"], RHO)
    shaped = base * ratio
    assumptions = RoadLoadAssumptions()
    mass = published["mass_kg"]
    sheet = worksheet(shaped, speed, mass, assumptions, published["cd"] * ratio)
    stock_sheet = worksheet(base, speed, mass, assumptions, published["cd"])
    change = abs(ratio - 1.0)
    if change < 1e-9:
        trust = (
            "The cover is flush with the skin. On this grid it does not reach new air, so the drag stays put."
            if covered
            else "Open wheels are the baseline."
        )
    elif change < 0.02:
        trust = "Under 2% on this grid. Treat it as no clear change."
    elif ratio < 1:
        trust = "Drag fell in this tunnel, so this shape should use less fuel than the open wheels."
    else:
        trust = "Drag rose in this tunnel, so this shape should use more fuel than the open wheels."
    return {
        "drag_n": shaped,
        "cd": published["cd"] * ratio,
        "mpg": sheet["mpg"],
        "stock_mpg": stock_sheet["mpg"],
        "stock_drag_n": base,
        "drag_ratio": ratio,
        "aero_power_w": sheet["aero_power_w"],
        "stock_aero_power_w": stock_sheet["aero_power_w"],
        "note": (
            f"Fuel starts from brochure Cd {published['cd']:.2f} and the stock silhouette, "
            f"then multiplies drag by {ratio:.3f}, the change measured in this tunnel. "
            "The tunnel's own Cd is not used. " + trust
        ),
    }


def _published() -> dict[str, float]:
    vehicle = load_vehicle()
    experiment = experiment_by_id("001")
    report = geometry_report(experiment) if experiment is not None else None
    area = report.projected_area_m2 if report is not None and report.projected_area_m2 else 0.0
    return {
        "cd": float(vehicle["published_cd"]),
        "area_m2": float(area),
        "mass_kg": float(vehicle["mass_kg"]),
        "speed_m_s": 0.0,
    }


_DIGEST: tuple[int, str] | None = None


def _mesh_digest() -> str:
    global _DIGEST
    path = stock_path()
    stamp = path.stat().st_mtime_ns
    if _DIGEST is not None and _DIGEST[0] == stamp:
        return _DIGEST[1]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    _DIGEST = (stamp, digest)
    return digest


def _folder(speed_mph: int, front: bool, rear: bool) -> Path:
    digest = _mesh_digest()
    name = f"w11-{digest}-{speed_mph}-{'f' if front else 'o'}{'r' if rear else 'o'}"
    return runs_dir() / "wind" / name


def _cached_speeds() -> list[dict[str, object]]:
    root = runs_dir() / "wind"
    if not root.exists():
        return []
    found = []
    for folder in root.glob("w11-*"):
        path = folder / "result.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            found.append(
                {
                    "speed_mph": payload["speed_mph"],
                    "front": payload["front"],
                    "rear": payload["rear"],
                }
            )
    return found


def _launch(speed_mph: int, front: bool, rear: bool) -> None:
    global _running, _error
    _error = None
    _running = {
        "speed_mph": speed_mph,
        "front": front,
        "rear": rear,
        "message": "Starting the tunnel.",
    }
    threading.Thread(target=_work, args=(speed_mph, front, rear), daemon=True).start()


def _work(speed_mph: int, front: bool, rear: bool) -> None:
    global _pending, _running
    try:
        if front or rear:
            _message("Settling the open wheels first, so the covers have something to beat.")
            _ensure(speed_mph, False, False)
        label = "open wheels" if not (front or rear) else "arch covers"
        _message(f"Blowing {speed_mph} mph at the {label}.")
        _ensure(speed_mph, front, rear)
        _message("The air has settled.")
    except (OSError, TunnelError, FileNotFoundError, ValueError) as exc:
        global _error
        _error = str(exc)
        _message(str(exc), failed=True)
    finally:
        with _LOCK:
            _running = None
            pending = _pending
            _pending = None
            if pending is not None:
                _launch(*pending)


def _message(text: str, failed: bool = False) -> None:
    with _LOCK:
        if _running is None:
            return
        _running["message"] = text
        if failed:
            _running["error"] = text


def _ensure(speed_mph: int, front: bool, rear: bool) -> None:
    folder = _folder(speed_mph, front, rear)
    ready = ("result.json", "streamlines.bin", "vortices.bin", "slice.bin")
    if all((folder / name).exists() for name in ready):
        return
    path = stock_path()
    if not path.exists():
        raise FileNotFoundError("Stock STL is missing. Import a car onto 001.")
    triangles = read_triangles(path.read_bytes())
    wheels = find_wheels(triangles)
    boxes = well_boxes(wheels, triangles, front=front, rear=rear)
    if (front or rear) and len(boxes) < 2:
        raise TunnelError("Could not find the wheels, so the covers were not built.")
    mask, origin = prepare_mask(triangles, boxes, dx=DX)
    steps = int(2.2 * mask.shape[0] / U_LB)
    u_si = speed_mph * MPH_TO_MPS
    height_cells = max(8.0, float(mask.shape[2] - 4))

    def progress(step: int, total: int) -> None:
        _message(f"Air step {step} of {total}.")

    solved, fluid = solve_mask(
        mask,
        DX,
        u_si,
        reynolds=REYNOLDS,
        length_cells=height_cells,
        steps=steps,
        u_lb=U_LB,
        keep_field=True,
        progress=progress,
    )
    vx, vy, vz, _speed = flow_field(fluid, U_LB, u_si)
    lines = fluidx_lines(mask, origin, DX, vx, vy, vz)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "streamlines.bin").write_bytes(pack_lines(lines))
    (folder / "vortices.bin").write_bytes(vortex_bytes(mask, origin, DX, vx, vy, vz, _speed, u_si))
    (folder / "slice.bin").write_bytes(slice_bytes(origin, DX, color_field(mask, vx, vy, vz), mask))
    payload = {
        "solver": "gasCFD lattice Boltzmann D3Q19",
        "speed_mph": speed_mph,
        "front": front,
        "rear": rear,
        "drag_n": solved.drag_n,
        "lift_n": solved.lift_n,
        "cd": solved.cd,
        "area_m2": solved.area_m2,
        "blockage": solved.blockage,
        "cell_m": solved.cell_m,
        "reynolds": solved.reynolds,
        "steps": solved.steps,
        "lines": len(lines),
        "wheels": len(wheels),
    }
    (folder / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
