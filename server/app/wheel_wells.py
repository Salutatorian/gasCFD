"""Flush wheel-arch covers, placed from the tires.

The panel sits on the body skin and fills the arch above the axle.
The lower part of the tire stays outside the cover.
The wheels are found from the mesh, so the cover is not positioned by hand.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from app.geometry import Triangle

Point = tuple[float, float, float]


@dataclass(frozen=True)
class Wheel:
    axle: str
    side: str
    x0: float
    x1: float
    y0: float
    y1: float
    z0: float
    z1: float

    @property
    def center(self) -> Point:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2, (self.z0 + self.z1) / 2)


@dataclass(frozen=True)
class WellBox:
    axle: str
    side: str
    x0: float
    x1: float
    y0: float
    y1: float
    z0: float
    z1: float
    seal_y0: float
    seal_y1: float


def find_wheels(triangles: list[Triangle]) -> list[Wheel]:
    """Four contact patches, then the tire mesh around each patch."""
    lows: list[Point] = []
    for tri in triangles:
        zs = (tri[0][2], tri[1][2], tri[2][2])
        if min(zs) > 0.1:
            continue
        point = (
            (tri[0][0] + tri[1][0] + tri[2][0]) / 3,
            (tri[0][1] + tri[1][1] + tri[2][1]) / 3,
            (zs[0] + zs[1] + zs[2]) / 3,
        )
        if point[2] < 0.75:
            lows.append(point)
    if len(lows) < 40:
        return []
    xs = sorted(point[0] for point in lows)
    gap_at = 0
    gap = 0.0
    for index in range(len(xs) - 1):
        span = xs[index + 1] - xs[index]
        if span > gap:
            gap = span
            gap_at = index
    if gap < 0.35:
        return []
    split = (xs[gap_at] + xs[gap_at + 1]) / 2
    wheels: list[Wheel] = []
    for axle, group in (
        ("front", [point for point in lows if point[0] < split]),
        ("rear", [point for point in lows if point[0] >= split]),
    ):
        for side, sign in (("left", -1.0), ("right", 1.0)):
            patch = [point for point in group if point[1] * sign > 0.15]
            if len(patch) < 8:
                continue
            cx = sum(point[0] for point in patch) / len(patch)
            cy = sum(point[1] for point in patch) / len(patch)
            gathered: list[Point] = []
            for tri in triangles:
                center = (
                    (tri[0][0] + tri[1][0] + tri[2][0]) / 3,
                    (tri[0][1] + tri[1][1] + tri[2][1]) / 3,
                    (tri[0][2] + tri[1][2] + tri[2][2]) / 3,
                )
                if abs(center[0] - cx) > 0.36 or abs(center[1] - cy) > 0.26 or center[2] > 0.76:
                    continue
                gathered.extend(tri)
            if len(gathered) < 12:
                continue
            xs_w = [point[0] for point in gathered]
            ys_w = [point[1] for point in gathered]
            zs_w = [point[2] for point in gathered]
            wheels.append(
                Wheel(axle, side, min(xs_w), max(xs_w), min(ys_w), max(ys_w), min(zs_w), max(zs_w))
            )
    return wheels


def _local_skin(triangles: list[Triangle], wheel: Wheel, fallback: float) -> float:
    """Body skin beside this wheel, so the cover meets the fender instead of sticking out."""
    sign = 1.0 if wheel.center[1] >= 0 else -1.0
    best = 0.0
    for tri in triangles:
        for point in tri:
            if point[0] < wheel.x0 - 0.08 or point[0] > wheel.x1 + 0.08 or point[2] < wheel.z1 - 0.02:
                continue
            if point[1] * sign <= 0:
                continue
            best = max(best, abs(point[1]))
    if best < 0.4:
        return abs(fallback)
    return best


def well_boxes(wheels: list[Wheel], triangles: list[Triangle], *, front: bool, rear: bool) -> list[WellBox]:
    chosen = {axle for axle, enabled in (("front", front), ("rear", rear)) if enabled}
    fallback = skin_half_width(triangles) if triangles else 0.0
    boxes: list[WellBox] = []
    for wheel in wheels:
        if wheel.axle not in chosen:
            continue
        sign = 1.0 if wheel.center[1] >= 0 else -1.0
        skin = _local_skin(triangles, wheel, fallback)
        # The drawn panel stays a thin skin. The seal reaches the inboard
        # side of the tire so the opening is shut and the wind has to hit it.
        outer = sign * (skin + 0.018)
        inner = sign * (skin - 0.045)
        y0, y1 = sorted((inner, outer))
        inboard = sign * min(abs(wheel.y0), abs(wheel.y1))
        seal_y0, seal_y1 = sorted((inboard, sign * skin))
        crown = wheel.z1 + 0.02
        chord = wheel.center[2]
        if crown < chord + 0.2:
            crown = chord + 0.25
        boxes.append(
            WellBox(
                wheel.axle,
                wheel.side,
                wheel.x0 - 0.02,
                wheel.x1 + 0.02,
                y0,
                y1,
                chord,
                crown,
                seal_y0,
                seal_y1,
            )
        )
    return boxes


def box_triangles(box: WellBox) -> list[Triangle]:
    """Arch panel: flat along the axle line, round over the top of the tire."""
    steps = 16
    span = box.x1 - box.x0
    arch = []
    for index in range(steps + 1):
        t = index / steps
        arch.append((box.x0 + span * t, box.z0 + (box.z1 - box.z0) * math.sin(math.pi * t)))
    triangles: list[Triangle] = []

    def quad(a: Point, b: Point, c: Point, d: Point) -> None:
        triangles.append((a, b, c))
        triangles.append((a, c, d))

    for index in range(steps):
        x0, z0 = arch[index]
        x1, z1 = arch[index + 1]
        for y in (box.y0, box.y1):
            quad((x0, y, box.z0), (x1, y, box.z0), (x1, y, z1), (x0, y, z0))
        quad((x0, box.y0, z0), (x0, box.y1, z0), (x1, box.y1, z1), (x1, box.y0, z1))
        quad((x0, box.y0, box.z0), (x1, box.y0, box.z0), (x1, box.y1, box.z0), (x0, box.y1, box.z0))
    return triangles


def boxes_stl(boxes: list[WellBox]) -> bytes:
    triangles = [tri for box in boxes for tri in box_triangles(box)]
    blob = bytearray(b"gasCFD wheel well box".ljust(80, b" "))
    blob += struct.pack("<I", len(triangles))
    for tri in triangles:
        ax, ay, az = tri[0]
        bx, by, bz = tri[1]
        cx, cy, cz = tri[2]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        blob += struct.pack(
            "<12fH",
            uy * vz - uz * vy,
            uz * vx - ux * vz,
            ux * vy - uy * vx,
            ax, ay, az, bx, by, bz, cx, cy, cz,
            0,
        )
    return bytes(blob)


def skin_half_width(triangles: list[Triangle]) -> float:
    return max(abs(point[1]) for tri in triangles for point in tri)
