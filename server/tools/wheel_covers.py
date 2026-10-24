"""Bolt flat discs onto the CadNav rims for experiments 002 and 003.

The discs sit just outboard of the spokes, inside the tire. They are derived
from the stock wheel STLs and are not committed; CadNav terms forbid
redistributing the model.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "server") not in sys.path:
    sys.path.insert(0, str(ROOT / "server"))
if str(ROOT / "server" / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "server" / "tools"))

from app.geometry import Triangle, read_triangles  # noqa: E402
from cadnav_matrix_to_stl import write_stl  # noqa: E402

VEHICLE = ROOT / "vehicles" / "toyota-matrix-2004"
STOCK_PARTS = VEHICLE / "stock" / "fluidx3d"
STOCK_GEOMETRY = VEHICLE / "stock" / "geometry.stl"
COVER_RADIUS_M = 0.215  # inside the 0.347 m tire, over the spokes
COVER_THICKNESS_M = 0.008
COVER_STANDOFF_M = 0.003
SEGMENTS = 48


def _split_wheels(triangles: list[Triangle]) -> list[list[Triangle]]:
    left = [tri for tri in triangles if sum(point[1] for point in tri) / 3.0 < 0.0]
    right = [tri for tri in triangles if sum(point[1] for point in tri) / 3.0 >= 0.0]
    return [group for group in (left, right) if group]


def _center(triangles: list[Triangle]) -> tuple[float, float, float, float, float]:
    xs = [point[0] for tri in triangles for point in tri]
    ys = [point[1] for tri in triangles for point in tri]
    zs = [point[2] for tri in triangles for point in tri]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, (min(zs) + max(zs)) / 2.0, min(ys), max(ys))


def _disc(cx: float, cy: float, cz: float, outward: float) -> list[Triangle]:
    outer_y = cy + outward * COVER_STANDOFF_M
    inner_y = outer_y - outward * COVER_THICKNESS_M
    outer: list[tuple[float, float, float]] = []
    inner: list[tuple[float, float, float]] = []
    for index in range(SEGMENTS):
        angle = 2.0 * math.pi * index / SEGMENTS
        dx = COVER_RADIUS_M * math.cos(angle)
        dz = COVER_RADIUS_M * math.sin(angle)
        outer.append((cx + dx, outer_y, cz + dz))
        inner.append((cx + dx, inner_y, cz + dz))
    hub_outer = (cx, outer_y, cz)
    hub_inner = (cx, inner_y, cz)
    faces: list[Triangle] = []
    for index in range(SEGMENTS):
        nxt = (index + 1) % SEGMENTS
        if outward > 0:
            faces.append((hub_outer, outer[index], outer[nxt]))
            faces.append((hub_inner, inner[nxt], inner[index]))
            faces.append((outer[index], inner[index], inner[nxt]))
            faces.append((outer[index], inner[nxt], outer[nxt]))
        else:
            faces.append((hub_outer, outer[nxt], outer[index]))
            faces.append((hub_inner, inner[index], inner[nxt]))
            faces.append((outer[index], inner[nxt], inner[index]))
            faces.append((outer[index], outer[nxt], inner[nxt]))
    return faces


def covers_for(path: Path) -> list[Triangle]:
    discs: list[Triangle] = []
    for wheel in _split_wheels(read_triangles(path.read_bytes())):
        cx, _cy, cz, y_min, y_max = _center(wheel)
        if abs(y_max) >= abs(y_min):
            discs.extend(_disc(cx, y_max, cz, 1.0))
        else:
            discs.extend(_disc(cx, y_min, cz, -1.0))
    return discs


def build() -> None:
    front = read_triangles((STOCK_PARTS / "front-wheels.stl").read_bytes())
    rear = read_triangles((STOCK_PARTS / "rear-wheels.stl").read_bytes())
    body = read_triangles((STOCK_PARTS / "body.stl").read_bytes())
    stock = read_triangles(STOCK_GEOMETRY.read_bytes())
    front_discs = covers_for(STOCK_PARTS / "front-wheels.stl")
    rear_discs = covers_for(STOCK_PARTS / "rear-wheels.stl")
    all_discs = front_discs + rear_discs

    front_dir = VEHICLE / "wheel-covers" / "front"
    all_dir = VEHICLE / "wheel-covers" / "all"
    write_stl(front_dir / "geometry.stl", stock + front_discs)
    write_stl(all_dir / "geometry.stl", stock + all_discs)
    write_stl(front_dir / "fluidx3d" / "body.stl", body)
    write_stl(front_dir / "fluidx3d" / "front-wheels.stl", front + front_discs)
    write_stl(front_dir / "fluidx3d" / "rear-wheels.stl", rear)
    write_stl(all_dir / "fluidx3d" / "body.stl", body)
    write_stl(all_dir / "fluidx3d" / "front-wheels.stl", front + front_discs)
    write_stl(all_dir / "fluidx3d" / "rear-wheels.stl", rear + rear_discs)
    print(f"front discs {len(front_discs)} rear discs {len(rear_discs)}")
    print(f"wrote {front_dir / 'geometry.stl'} and {all_dir / 'geometry.stl'}")


if __name__ == "__main__":
    build()
