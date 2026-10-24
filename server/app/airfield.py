"""Altered visualization, not the solver.

Streamlines, the Q-criterion isosurface, and the rainbow speed colors are
adapted from FluidX3D (graphics_streamline, interpolate_u, graphics_q,
graphics_field_slice, colorscale_rainbow). The car tracer follows the
trilinear midpoint steps in fluidx3d/src/setup.cpp.

Original work: Copyright (c) 2022-2026 Dr. Moritz Lehmann
https://github.com/ProjectPhysX/FluidX3D

This file is an altered version. It is not the original FluidX3D, and gasCFD
did not write that original. The lattice-Boltzmann collide and stream kernels
are not included. Use is limited to non-commercial, public-research, education,
and personal purposes, the same as the FluidX3D license in fluidx3d/LICENSE.md.
"""

from __future__ import annotations

import math

import numpy as np
import mcubes
from numba import njit
from scipy.ndimage import gaussian_filter, zoom


def q_criterion(vx: np.ndarray, vy: np.ndarray, vz: np.ndarray, dx: float) -> np.ndarray:
    """Positive where the air is spinning harder than it is stretching."""
    dux_dx, dux_dy, dux_dz = np.gradient(vx, dx, edge_order=1)
    duy_dx, duy_dy, duy_dz = np.gradient(vy, dx, edge_order=1)
    duz_dx, duz_dy, duz_dz = np.gradient(vz, dx, edge_order=1)
    return (
        -0.5 * (dux_dx * dux_dx + duy_dy * duy_dy + duz_dz * duz_dz)
        - dux_dy * duy_dx
        - dux_dz * duz_dx
        - duy_dz * duz_dy
    ).astype(np.float64)


# FluidX3D GRAPHICS_U_MAX and def_scale_u = 1 / (c * U_MAX), c = 1/sqrt(3).
SCALE_U = 1.0 / (0.57735027 * 0.18)
# FluidX3D GRAPHICS_Q_CRITERION. Q here is in lattice cells, the same units.
# Their published cutoff is 0.0001 on a fine lattice. This tunnel's cells are 10 cm
# and the Reynolds number is low, so the same cutoff only keeps two blobs.
# 0.00002 still uses their Q formula and stays under a readable triangle count.
# FluidX3D marches Q at 0.0001 on its own lattice. These cells are 5 cm after
# the 2x upsample, so the shell that wraps the car (and does not fill the
# tunnel) sits a little lower.
Q_MIN = 0.00006

def rainbow(x: np.ndarray) -> np.ndarray:
    """FluidX3D colorscale_rainbow. Fast air is red, slow air falls toward violet."""
    t = np.clip(6.0 * (1.0 - x), 0.0, 6.0)
    red = np.zeros_like(t)
    green = np.zeros_like(t)
    blue = np.zeros_like(t)
    a = t < 1.2
    b = (t >= 1.2) & (t < 2.0)
    c = (t >= 2.0) & (t < 3.0)
    d = (t >= 3.0) & (t < 4.0)
    e = (t >= 4.0) & (t < 5.0)
    f = t >= 5.0
    red[a] = 1.0
    green[a] = t[a] * 0.83333333
    red[b] = 2.5 - t[b] * 1.25
    green[b] = 1.0
    green[c] = 1.0
    blue[c] = t[c] - 2.0
    green[d] = 4.0 - t[d]
    blue[d] = 1.0
    red[e] = t[e] * 0.4 - 1.6
    blue[e] = 3.0 - t[e] * 0.5
    red[f] = 2.4 - t[f] * 0.4
    blue[f] = 3.0 - t[f] * 0.5
    return np.stack((red, green, blue), axis=1).astype(np.float32)


def q_fluidx(vx: np.ndarray, vy: np.ndarray, vz: np.ndarray) -> np.ndarray:
    """FluidX3D calculate_Q_cached, one lattice cell wide."""
    def span(field: np.ndarray, axis: int) -> np.ndarray:
        return np.roll(field, -1, axis) - np.roll(field, 1, axis)

    s_xx2, duydx, duzdx = span(vx, 0), span(vy, 0), span(vz, 0)
    duxdy, s_yy2, duzdy = span(vx, 1), span(vy, 1), span(vz, 1)
    duxdz, duydz, s_zz2 = span(vx, 2), span(vy, 2), span(vz, 2)
    omega2 = (duxdy - duydx) ** 2 + (duxdz - duzdx) ** 2 + (duydz - duzdy) ** 2
    strain2 = 2.0 * (s_xx2**2 + s_yy2**2 + s_zz2**2) + (duxdy + duydx) ** 2 + (duxdz + duzdx) ** 2 + (duydz + duzdy) ** 2
    return (0.25 * (omega2 - strain2)).astype(np.float64)


@njit
def _air(mask: np.ndarray, x: float, y: float, z: float) -> bool:
    ix = int(math.floor(x + 0.5))
    iy = int(math.floor(y + 0.5))
    iz = int(math.floor(z + 0.5))
    nx, ny, nz = mask.shape
    if ix < 0 or iy < 0 or iz < 0 or ix >= nx or iy >= ny or iz >= nz:
        return False
    return mask[ix, iy, iz] == 0


@njit
def _trilin(
    mask: np.ndarray,
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
    x: float,
    y: float,
    z: float,
) -> tuple[float, float, float]:
    """FluidX3D interpolate_u. Solid corners contribute no wind."""
    x0 = int(math.floor(x))
    y0 = int(math.floor(y))
    z0 = int(math.floor(z))
    fx = x - x0
    fy = y - y0
    fz = z - z0
    sx = 0.0
    sy = 0.0
    sz = 0.0
    nx, ny, nz = mask.shape
    for corner in range(8):
        ox = corner & 1
        oy = (corner >> 1) & 1
        oz = corner >> 2
        ix = x0 + ox
        iy = y0 + oy
        iz = z0 + oz
        if ix < 0 or iy < 0 or iz < 0 or ix >= nx or iy >= ny or iz >= nz:
            continue
        if mask[ix, iy, iz] != 0:
            continue
        weight = (fx if ox else 1.0 - fx) * (fy if oy else 1.0 - fy) * (fz if oz else 1.0 - fz)
        sx += weight * vx[ix, iy, iz]
        sy += weight * vy[ix, iy, iz]
        sz += weight * vz[ix, iy, iz]
    return sx, sy, sz


@njit
def _step_line(
    mask: np.ndarray,
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
    x: float,
    y: float,
    z: float,
    direction: float,
    steps: int,
    scale_u: float,
    buf: np.ndarray,
) -> int:
    """One way along a streamline. Half-cell midpoint steps, their car tracer."""
    count = 0
    for _ in range(steps):
        if not _air(mask, x, y, z):
            break
        sx, sy, sz = _trilin(mask, vx, vy, vz, x, y, z)
        speed = math.sqrt(sx * sx + sy * sy + sz * sz)
        if speed < 1e-8 or scale_u * speed < 0.1:
            break
        buf[count, 0] = x
        buf[count, 1] = y
        buf[count, 2] = z
        buf[count, 3] = scale_u * speed
        count += 1
        mx = x + direction * 0.25 * sx / speed
        my = y + direction * 0.25 * sy / speed
        mz = z + direction * 0.25 * sz / speed
        if not _air(mask, mx, my, mz):
            break
        tx, ty, tz = _trilin(mask, vx, vy, vz, mx, my, mz)
        mid = math.sqrt(tx * tx + ty * ty + tz * tz)
        if mid < 1e-8:
            break
        x = x + direction * 0.5 * tx / mid
        y = y + direction * 0.5 * ty / mid
        z = z + direction * 0.5 * tz / mid
    return count


@njit
def _trace_seeds(
    mask: np.ndarray,
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
    seeds: np.ndarray,
    steps: int,
    scale_u: float,
) -> tuple[np.ndarray, np.ndarray]:
    nseeds = seeds.shape[0]
    out = np.zeros((nseeds, steps * 2, 4), dtype=np.float64)
    counts = np.zeros(nseeds, dtype=np.int32)
    back = np.zeros((steps, 4), dtype=np.float64)
    fore = np.zeros((steps, 4), dtype=np.float64)
    for i in range(nseeds):
        x = seeds[i, 0]
        y = seeds[i, 1]
        z = seeds[i, 2]
        both = seeds[i, 3] > 0.5
        nb = 0
        if both:
            nb = _step_line(mask, vx, vy, vz, x, y, z, -1.0, steps, scale_u, back)
        nf = _step_line(mask, vx, vy, vz, x, y, z, 1.0, steps, scale_u, fore)
        count = 0
        for k in range(nb - 1, -1, -1):
            out[i, count, 0] = back[k, 0]
            out[i, count, 1] = back[k, 1]
            out[i, count, 2] = back[k, 2]
            out[i, count, 3] = back[k, 3]
            count += 1
        start = 1 if nb > 0 and nf > 0 else 0
        for k in range(start, nf):
            out[i, count, 0] = fore[k, 0]
            out[i, count, 1] = fore[k, 1]
            out[i, count, 2] = fore[k, 2]
            out[i, count, 3] = fore[k, 3]
            count += 1
        counts[i] = count
    return out, counts


def fluidx_lines(
    mask: np.ndarray,
    origin: np.ndarray,
    dx: float,
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
) -> list[list[tuple[float, float, float, float]]]:
    """FluidX3D streamlines on this tunnel's air.

    Seeds are one rake ahead of the nose, covering the whole car: both sides,
    the tires, the gap under the body, and the air above the roof. The empty
    tunnel outside that silhouette is left alone so the car stays visible.
    Each step is a smooth half-cell move through trilinear wind. A line stops
    when it enters the car or the air gets slow, which is their cutoff.
    """
    _nx, ny, nz = mask.shape
    body = np.argwhere(mask == 1)
    if len(body) == 0:
        return []
    nose = int(body[:, 0].min())
    rake = max(1, nose - 4)
    span = origin[1] + (body[:, 1] + 0.5) * dx
    y_min, y_max = (float(v) for v in np.percentile(span, [2, 98]))
    # Even rows from the tire up through the roof. The antenna is one cell and
    # must not pull the rake into the empty air above the car.
    heights = (0.18, 0.40, 0.62, 0.85, 1.08, 1.30, 1.52, 1.72)
    seeds: list[tuple[float, float, float, float]] = []
    seen: set[tuple[int, int]] = set()
    for y in np.linspace(y_min - 0.3, y_max + 0.3, 11):
        for z in heights:
            iy = int(round((y - origin[1]) / dx - 0.5))
            iz = int(round((z - origin[2]) / dx - 0.5))
            if iy < 1 or iz < 1 or iy > ny - 2 or iz > nz - 2:
                continue
            if (iy, iz) in seen or mask[rake, iy, iz] != 0:
                continue
            seen.add((iy, iz))
            seeds.append((float(rake), float(iy), float(iz), 0.0))
    if not seeds:
        return []
    raw, counts = _trace_seeds(
        np.ascontiguousarray(mask),
        np.ascontiguousarray(vx, dtype=np.float64),
        np.ascontiguousarray(vy, dtype=np.float64),
        np.ascontiguousarray(vz, dtype=np.float64),
        np.asarray(seeds, dtype=np.float64),
        180,
        SCALE_U,
    )
    lines: list[list[tuple[float, float, float, float]]] = []
    for i, count in enumerate(counts):
        n = int(count)
        if n < 2:
            continue
        pts = raw[i, :n]
        world = origin + (pts[:, :3] + 0.5) * dx
        lines.append(
            [
                (float(world[k, 0]), float(world[k, 1]), float(world[k, 2]), float(pts[k, 3]))
                for k in range(n)
            ]
        )
    return lines


def color_field(mask: np.ndarray, vx: np.ndarray, vy: np.ndarray, vz: np.ndarray) -> np.ndarray:
    """Rainbow input. Solid cells are 0 so the speed cut has a hole for the car."""
    pace = SCALE_U * np.sqrt(vx * vx + vy * vy + vz * vz)
    pace = pace.astype(np.float32)
    pace[mask != 0] = 0.0
    return pace


def _march(volume: np.ndarray, level: float) -> tuple[np.ndarray, np.ndarray]:
    try:
        verts, tris = mcubes.marching_cubes(np.ascontiguousarray(volume, dtype=np.float64), level)
    except (ValueError, RuntimeError):
        return np.zeros((0, 3)), np.zeros((0, 3), np.int32)
    return verts, tris


def _vortex_surface(spinning: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """March the FluidX3D Q threshold. Raise it only if the shell hides the car."""
    level = Q_MIN
    peak = float(spinning.max()) if spinning.size else 0.0
    if peak <= level:
        return None
    chosen: tuple[np.ndarray, np.ndarray] | None = None
    while level < peak:
        verts, tris = _march(spinning, level)
        if 0 < len(tris) <= 18000:
            return verts, tris
        if len(tris) > 14000:
            chosen = (verts, tris)
        level *= 4.0
    return chosen


def vortex_bytes(
    mask: np.ndarray,
    origin: np.ndarray,
    dx: float,
    vx: np.ndarray,
    vy: np.ndarray,
    vz: np.ndarray,
    _speed: np.ndarray,
    _freestream: float,
) -> bytes:
    """FluidX3D graphics_q: marching cubes of Q, colored by speed.

    The velocity is drawn on a 2x grid first so the shell is round instead of
    a few 10 cm lumps. Solid cells stay empty, the same as their kernel.
    """
    fine = 2
    vx_f, vy_f, vz_f = (zoom(part, fine, order=1) for part in (vx, vy, vz))
    solid = zoom((mask != 0).astype(np.float32), fine, order=0) > 0.5
    spinning = q_fluidx(vx_f, vy_f, vz_f)
    spinning[solid] = 0.0
    spinning = gaussian_filter(spinning, 0.45)
    spinning[solid] = 0.0
    found = _vortex_surface(spinning)
    if found is None:
        return _pack_mesh(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint32))
    verts, tris = found
    nx, ny, nz = vx_f.shape
    ix = np.clip(np.rint(verts[:, 0]).astype(np.int32), 0, nx - 1)
    iy = np.clip(np.rint(verts[:, 1]).astype(np.int32), 0, ny - 1)
    iz = np.clip(np.rint(verts[:, 2]).astype(np.int32), 0, nz - 1)
    ul = np.sqrt(vx_f[ix, iy, iz] ** 2 + vy_f[ix, iy, iz] ** 2 + vz_f[ix, iy, iz] ** 2)
    colors = rainbow(SCALE_U * ul)
    points = (origin + (verts + 0.5) * (dx / fine)).astype(np.float32)
    return _pack_mesh(points, colors, tris.astype(np.uint32))


def slice_bytes(
    origin: np.ndarray,
    dx: float,
    speed: np.ndarray,
    mask: np.ndarray | None = None,
) -> bytes:
    """One centerline cut, the FluidX3D velocity slice.

    Colors are blended across each cell (their graphics_field_slice draws the
    same blend). The car stays a hole.
    """
    _nx, ny, _nz = speed.shape
    ys = origin[1] + (np.arange(ny) + 0.5) * dx
    iy = int(np.argmin(np.abs(ys)))
    fine = 4
    grid = zoom(np.asarray(speed[:, iy, :], dtype=np.float32), fine, order=3)
    if mask is not None:
        solid = zoom((mask[:, iy, :] != 0).astype(np.float32), fine, order=0) > 0.5
        grid[solid] = 0.0
    grid = np.clip(grid, 0.0, None).astype(np.float32)
    planes = (
        (0, float(ys[iy]), float(origin[0] + 0.5 * dx), float(origin[2] + 0.5 * dx), dx / fine, grid),
    )
    blob = bytearray()
    blob += np.uint32(len(planes)).tobytes()
    for axis, coord, u0, v0, spacing, grid in planes:
        nu, nv = grid.shape
        blob += np.uint32(axis).tobytes()
        blob += np.asarray([coord, u0, v0, spacing], dtype=np.float32).tobytes()
        blob += np.asarray([nu, nv], dtype=np.uint32).tobytes()
        blob += np.ascontiguousarray(grid, dtype=np.float32).tobytes()
    return bytes(blob)


def _pack_mesh(points: np.ndarray, colors: np.ndarray, triangles: np.ndarray) -> bytes:
    blob = bytearray()
    blob += np.uint32(len(points)).tobytes()
    blob += np.uint32(len(triangles)).tobytes()
    blob += np.ascontiguousarray(points, dtype=np.float32).tobytes()
    blob += np.ascontiguousarray(colors, dtype=np.float32).tobytes()
    blob += np.ascontiguousarray(triangles, dtype=np.uint32).tobytes()
    return bytes(blob)
