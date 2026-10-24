"""Our wind tunnel: a D3Q19 lattice-Boltzmann solver.

Air sits on a grid. Each step it streams into the next cell and collides.
Solid cells bounce it back. The ground moves with the air and the tires roll,
so an open arch can catch the spinning wheel. Drag is the momentum that bounce
hands to the body. The method is the lattice-Boltzmann idea used by wind-tunnel
codes. This file is ours; it does not contain FluidX3D.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numba import njit, prange
from scipy.ndimage import binary_closing

from app.geometry import Triangle
from app.recipe import RHO
from app.wheel_wells import WellBox, Wheel

_C = np.array(
    [
        (0, 0, 0),
        (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1),
        (1, 1, 0), (-1, -1, 0), (1, -1, 0), (-1, 1, 0),
        (1, 0, 1), (-1, 0, -1), (1, 0, -1), (-1, 0, 1),
        (0, 1, 1), (0, -1, -1), (0, 1, -1), (0, -1, 1),
    ],
    dtype=np.int64,
)
_OPP = np.empty(19, dtype=np.int64)
for _i, _vector in enumerate(_C):
    _OPP[_i] = int(np.where((_C == -_vector).all(axis=1))[0][0])
_W = np.array(
    [1 / 3, *([1 / 18] * 6), *([1 / 36] * 12)],
    dtype=np.float64,
)


@dataclass(frozen=True)
class TunnelResult:
    drag_n: float
    lift_n: float
    cd: float
    area_m2: float
    cell_m: float
    reynolds: float
    steps: int
    blockage: float
    speed_m_s: float


class TunnelError(RuntimeError):
    pass


@njit(cache=True, parallel=True)
def _stream(f, out, mask, wall, cx, cy, cz, opp, weights, inlet, omega):
    nx, ny, nz, _ = f.shape
    fx = 0.0
    fy = 0.0
    fz = 0.0
    max_rho = 1.0
    for x in prange(1, nx - 1):
        pop = np.empty(19, np.float64)
        for y in range(ny):
            for z in range(nz):
                if mask[x, y, z] != 0:
                    continue
                rho = 0.0
                ux = 0.0
                uy = 0.0
                uz = 0.0
                for i in range(19):
                    sx = x - cx[i]
                    sy = y - cy[i]
                    sz = z - cz[i]
                    if sx < 0:
                        val = inlet[i]
                    elif sy < 0 or sz < 0 or sx >= nx or sy >= ny or sz >= nz:
                        val = f[x, y, z, opp[i]]
                    else:
                        neighbor = mask[sx, sy, sz]
                        if neighbor == 0:
                            val = f[sx, sy, sz, i]
                        else:
                            reflected = f[x, y, z, opp[i]]
                            wx = wall[sx, sy, sz, 0]
                            wy = wall[sx, sy, sz, 1]
                            wz = wall[sx, sy, sz, 2]
                            cu = cx[i] * wx + cy[i] * wy + cz[i] * wz
                            val = reflected + 6.0 * weights[i] * cu
                            if neighbor == 1:
                                fx += -(val + reflected) * cx[i]
                                fy += -(val + reflected) * cy[i]
                                fz += -(val + reflected) * cz[i]
                    pop[i] = val
                    rho += val
                    ux += val * cx[i]
                    uy += val * cy[i]
                    uz += val * cz[i]
                if rho > max_rho:
                    max_rho = rho
                if not (0.05 < rho < 5.0):
                    max_rho = 99.0
                    continue
                inv = 1.0 / rho
                ux *= inv
                uy *= inv
                uz *= inv
                usq = ux * ux + uy * uy + uz * uz
                for i in range(19):
                    cu = cx[i] * ux + cy[i] * uy + cz[i] * uz
                    feq = weights[i] * rho * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * usq)
                    out[x, y, z, i] = pop[i] - omega * (pop[i] - feq)
    return fx, fy, fz, max_rho


@njit(cache=True)
def _ends(out, inlet):
    nx, ny, nz, _ = out.shape
    last = nx - 1
    prev = nx - 2
    for y in range(ny):
        for z in range(nz):
            for i in range(19):
                out[0, y, z, i] = inlet[i]
                out[last, y, z, i] = out[prev, y, z, i]


def _inlet(u_lb: float) -> np.ndarray:
    inlet = np.empty(19, dtype=np.float64)
    usq = u_lb * u_lb
    for index, vector in enumerate(_C):
        cu = vector[0] * u_lb
        inlet[index] = _W[index] * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * usq)
    return inlet


def _omega(u_lb: float, length_cells: float, reynolds: float) -> float:
    nu = u_lb * max(length_cells, 1.0) / reynolds
    tau = 3.0 * nu + 0.5
    if tau <= 0.51:
        raise TunnelError("Reynolds number is too high for this grid.")
    return 1.0 / tau


def rolling_walls(
    mask: np.ndarray,
    origin: np.ndarray,
    dx: float,
    wheels: list[Wheel],
    u_lb: float,
    tire: np.ndarray | None = None,
) -> np.ndarray:
    """Road speed on the ground, and a rolling speed on each tire.

    The car is held still and the air moves downstream. The ground moves with
    that air, and each tire rolls so its contact patch matches the ground.
    Cover cells are not tires: pass the open-wheel body as ``tire``.
    """
    wall = np.zeros((*mask.shape, 3), dtype=np.float64)
    ground = mask[:, :, 0] == 2
    wall[:, :, 0, 0] = np.where(ground, u_lb, 0.0)
    if u_lb == 0.0 or dx <= 0.0:
        return wall
    xs = origin[0] + (np.arange(mask.shape[0]) + 0.5) * dx
    ys = origin[1] + (np.arange(mask.shape[1]) + 0.5) * dx
    zs = origin[2] + (np.arange(mask.shape[2]) + 0.5) * dx
    body = mask == 1 if tire is None else (tire == 1) & (mask == 1)
    xx = xs[:, None, None]
    yy = ys[None, :, None]
    zz = zs[None, None, :]
    for wheel in wheels:
        radius = 0.5 * max(wheel.x1 - wheel.x0, wheel.z1 - wheel.z0)
        if radius < 0.05:
            continue
        center_x = 0.5 * (wheel.x0 + wheel.x1)
        center_z = 0.5 * (wheel.z0 + wheel.z1)
        limit = (0.98 * radius) ** 2
        spin = -u_lb / radius
        rx = xx - center_x
        rz = zz - center_z
        inside = body & (rx * rx + rz * rz <= limit) & (yy >= wheel.y0) & (yy <= wheel.y1)
        wall[..., 0] = np.where(inside, spin * rz, wall[..., 0])
        wall[..., 2] = np.where(inside, -spin * rx, wall[..., 2])
    return wall


def solve_mask(
    mask: np.ndarray,
    dx: float,
    u_si: float,
    *,
    reynolds: float,
    length_cells: float,
    steps: int,
    u_lb: float = 0.06,
    keep_field: bool = False,
    progress: Callable[[int, int], None] | None = None,
    wall_u: np.ndarray | None = None,
) -> TunnelResult | tuple[TunnelResult, np.ndarray]:
    if u_si <= 0 or dx <= 0:
        raise TunnelError("Speed and cell size must be positive.")
    if wall_u is None:
        wall = np.zeros((*mask.shape, 3), dtype=np.float64)
    else:
        wall = np.ascontiguousarray(wall_u, dtype=np.float64)
        if wall.shape != (*mask.shape, 3):
            raise TunnelError("Wall velocity does not match the grid.")
    inlet = _inlet(u_lb)
    omega = _omega(u_lb, length_cells, reynolds)
    fluid = np.broadcast_to(inlet, (*mask.shape, 19)).copy()
    other = np.empty_like(fluid)
    body = mask == 1
    area = float(body.any(axis=0).sum()) * dx * dx
    if area <= 0:
        raise TunnelError("The body has no frontal area.")
    face = float(np.logical_or(mask[1] == 0, mask[1] == 1).sum()) * dx * dx
    drag_sum = 0.0
    lift_sum = 0.0
    samples = 0
    start = int(steps * 0.65)
    for step in range(steps):
        if progress is not None and step % 500 == 0:
            progress(step, steps)
        fx, _fy, fz, max_rho = _stream(
            fluid, other, mask, wall, _C[:, 0], _C[:, 1], _C[:, 2], _OPP, _W, inlet, omega
        )
        if max_rho > 8.0:
            raise TunnelError("The wind became unstable. Try again at a coarser setting.")
        _ends(other, inlet)
        fluid, other = other, fluid
        if step >= start:
            drag_sum += fx
            lift_sum += fz
            samples += 1
    if samples == 0:
        raise TunnelError("The tunnel did not sample any drag.")
    dt = u_lb * dx / u_si
    scale = RHO * dx**4 / dt**2
    drag = (drag_sum / samples) * scale
    lift = (lift_sum / samples) * scale
    cd = drag / (0.5 * RHO * u_si * u_si * area)
    result = TunnelResult(
        drag_n=float(drag),
        lift_n=float(lift),
        cd=float(cd),
        area_m2=float(area),
        cell_m=dx,
        reynolds=reynolds,
        steps=steps,
        blockage=float(area / face) if face > 0 else 1.0,
        speed_m_s=u_si,
    )
    if keep_field:
        return result, fluid
    return result


def prepare_mask(
    triangles: list[Triangle],
    boxes: list[WellBox],
    *,
    dx: float = 0.08,
) -> tuple[np.ndarray, np.ndarray]:
    points = [point for tri in triangles for point in tri]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    origin = np.array([min(xs) - 1.25, -(max(abs(min(ys)), abs(max(ys))) + 1.35), -dx], dtype=np.float64)
    extent = np.array(
        [max(xs) + 3.4, max(abs(min(ys)), abs(max(ys))) + 1.35, max(zs) + 1.35],
        dtype=np.float64,
    )
    counts = np.maximum(np.ceil((extent - origin) / dx).astype(np.int64) + 1, 8)
    mask = np.zeros((int(counts[0]), int(counts[1]), int(counts[2])), dtype=np.uint8)
    mask[:, 0, :] = 2
    mask[:, -1, :] = 2
    mask[:, :, 0] = 2
    mask[:, :, -1] = 2
    _raster(np.asarray(triangles, dtype=np.float64), origin, dx, mask)
    body = mask == 1
    closed = binary_closing(body, iterations=1)
    mask[(closed) & (mask != 2)] = 1
    _stamp_boxes(mask, origin, dx, boxes)
    _fill_enclosed(mask)
    return mask, origin


@njit(cache=True)
def _raster(tris, origin, dx, mask):
    nx, ny, nz = mask.shape
    step = dx * 0.5
    for t in range(tris.shape[0]):
        ax = tris[t, 0, 0]
        ay = tris[t, 0, 1]
        az = tris[t, 0, 2]
        bx = tris[t, 1, 0] - ax
        by = tris[t, 1, 1] - ay
        bz = tris[t, 1, 2] - az
        cx = tris[t, 2, 0] - ax
        cy = tris[t, 2, 1] - ay
        cz = tris[t, 2, 2] - az
        nu = max(1, int(math.sqrt(bx * bx + by * by + bz * bz) / step))
        nv = max(1, int(math.sqrt(cx * cx + cy * cy + cz * cz) / step))
        for i in range(nu + 1):
            u = i / nu
            for j in range(nv + 1):
                v = j / nv
                if u + v > 1.0:
                    continue
                px = ax + u * bx + v * cx
                py = ay + u * by + v * cy
                pz = az + u * bz + v * cz
                ix = int((px - origin[0]) / dx)
                iy = int((py - origin[1]) / dx)
                iz = int((pz - origin[2]) / dx)
                if 0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz and mask[ix, iy, iz] == 0:
                    mask[ix, iy, iz] = 1


def _stamp_boxes(mask: np.ndarray, origin: np.ndarray, dx: float, boxes: list[WellBox]) -> None:
    nx, ny, nz = mask.shape
    xs = origin[0] + (np.arange(nx) + 0.5) * dx
    ys = origin[1] + (np.arange(ny) + 0.5) * dx
    zs = origin[2] + (np.arange(nz) + 0.5) * dx
    for box in boxes:
        span = box.x1 - box.x0
        if span <= 1e-6:
            continue
        tx = (xs - box.x0) / span
        crown = box.z0 + (box.z1 - box.z0) * np.sin(np.pi * np.clip(tx, 0.0, 1.0))
        sel = (
            (tx[:, None, None] >= 0.0)
            & (tx[:, None, None] <= 1.0)
            & (ys[None, :, None] >= box.seal_y0)
            & (ys[None, :, None] <= box.seal_y1)
            & (zs[None, None, :] >= box.z0)
            & (zs[None, None, :] <= crown[:, None, None])
        )
        mask[sel & (mask == 0)] = 1


def _fill_enclosed(mask: np.ndarray) -> None:
    air = np.zeros(mask.shape, dtype=np.uint8)
    nx, ny, nz = mask.shape
    queue: list[tuple[int, int, int]] = []
    for y in range(ny):
        for z in range(nz):
            if mask[0, y, z] == 0:
                air[0, y, z] = 1
                queue.append((0, y, z))
    head = 0
    while head < len(queue):
        x, y, z = queue[head]
        head += 1
        for sx, sy, sz in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z), (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)):
            if sx < 0 or sy < 0 or sz < 0 or sx >= nx or sy >= ny or sz >= nz:
                continue
            if mask[sx, sy, sz] != 0 or air[sx, sy, sz]:
                continue
            air[sx, sy, sz] = 1
            queue.append((sx, sy, sz))
    mask[(mask == 0) & (air == 0)] = 1


def flow_field(
    fluid: np.ndarray,
    u_lb: float,
    u_si: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    velocity_x = np.einsum("xyzi,i->xyz", fluid, _C[:, 0].astype(np.float64))
    velocity_y = np.einsum("xyzi,i->xyz", fluid, _C[:, 1].astype(np.float64))
    velocity_z = np.einsum("xyzi,i->xyz", fluid, _C[:, 2].astype(np.float64))
    rho = np.maximum(fluid.sum(axis=3), 1e-6)
    speed = np.sqrt(velocity_x**2 + velocity_y**2 + velocity_z**2) / rho / u_lb * u_si
    return velocity_x / rho, velocity_y / rho, velocity_z / rho, speed


def trace_lines(
    mask: np.ndarray,
    origin: np.ndarray,
    dx: float,
    speed: np.ndarray,
    velocity_x: np.ndarray,
    velocity_y: np.ndarray,
    velocity_z: np.ndarray,
    seeds: list[tuple[float, float, float]],
) -> list[list[tuple[float, float, float, float]]]:
    lines: list[list[tuple[float, float, float, float]]] = []
    nx, ny, nz = mask.shape
    for seed in seeds:
        line: list[tuple[float, float, float, float]] = []
        point = seed
        for _ in range(180):
            ix = int((point[0] - origin[0]) / dx)
            iy = int((point[1] - origin[1]) / dx)
            iz = int((point[2] - origin[2]) / dx)
            if ix < 1 or iy < 1 or iz < 1 or ix >= nx - 1 or iy >= ny - 1 or iz >= nz - 1:
                break
            if mask[ix, iy, iz] != 0:
                break
            vx = float(velocity_x[ix, iy, iz])
            vy = float(velocity_y[ix, iy, iz])
            vz = float(velocity_z[ix, iy, iz])
            mag = math.sqrt(vx * vx + vy * vy + vz * vz)
            if mag < 1e-4:
                break
            line.append((point[0], point[1], point[2], float(speed[ix, iy, iz])))
            point = (point[0] + 0.45 * dx * vx / mag, point[1] + 0.45 * dx * vy / mag, point[2] + 0.45 * dx * vz / mag)
        if len(line) >= 4:
            lines.append(line)
    return lines


def seed_curtain(mask: np.ndarray, origin: np.ndarray, dx: float) -> list[tuple[float, float, float]]:
    body = np.argwhere(mask == 1)
    if len(body) == 0:
        return []
    xs = origin[0] + (body[:, 0] + 0.5) * dx
    ys = origin[1] + (body[:, 1] + 0.5) * dx
    zs = origin[2] + (body[:, 2] + 0.5) * dx
    nose = float(xs.min())
    y0, y1 = float(np.percentile(ys, 3)), float(np.percentile(ys, 97))
    z1 = float(np.percentile(zs, 96))
    seeds: list[tuple[float, float, float]] = []
    for y in np.linspace(y0, y1, 16):
        for z in np.linspace(0.08, max(0.5, z1), 11):
            seeds.append((nose - 0.4, float(y), float(z)))
    return seeds


def pack_lines(lines: list[list[tuple[float, float, float, float]]]) -> bytes:
    counts = [len(line) for line in lines]
    blob = bytearray()
    blob += np.uint32(len(counts)).tobytes()
    blob += np.asarray(counts, dtype=np.uint32).tobytes()
    for line in lines:
        blob += np.asarray(line, dtype=np.float32).tobytes()
    return bytes(blob)
