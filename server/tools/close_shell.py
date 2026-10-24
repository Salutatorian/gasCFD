"""Close the CadNav Matrix into an outer shell OpenFOAM can mesh.

The source STL has open windows, arches, and panel gaps. Boundary loops are
capped, the volume is voxelized, and marching cubes keeps only the outside skin.
"""

import struct
import sys
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
from mcubes import marching_cubes

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.geometry import read_triangles


def _boundary_loops(triangles: list) -> list[list[tuple[float, float, float]]]:
    edges: dict[tuple, int] = defaultdict(int)
    for a, b, c in triangles:
        keys = [tuple(round(value, 5) for value in vertex) for vertex in (a, b, c)]
        for start, end in ((keys[0], keys[1]), (keys[1], keys[2]), (keys[2], keys[0])):
            edges[tuple(sorted((start, end)))] += 1
    adjacency: dict[tuple, list[tuple]] = defaultdict(list)
    for (start, end), count in edges.items():
        if count == 1:
            adjacency[start].append(end)
            adjacency[end].append(start)
    seen: set[tuple] = set()
    loops: list[list[tuple[float, float, float]]] = []
    for start in adjacency:
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        previous = None
        current = start
        for _ in range(100000):
            nxt = [point for point in adjacency[current] if point != previous and point not in seen]
            if not nxt:
                break
            previous, current = current, nxt[0]
            seen.add(current)
            loop.append(current)
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _cap(loop: list[tuple[float, float, float]]) -> list:
    count = len(loop)
    centroid = tuple(sum(point[axis] for point in loop) / count for axis in range(3))
    capped = []
    for index in range(count):
        capped.append((centroid, loop[index], loop[(index + 1) % count]))
    return capped


def _mark_triangle(grid: np.ndarray, origin: np.ndarray, pitch: float, triangle) -> None:
    points = np.asarray(triangle, dtype=np.float64)
    lengths = np.linalg.norm(points[[1, 2, 0]] - points, axis=1)
    steps = max(1, int(np.ceil(lengths.max() / pitch)))
    weights = np.linspace(0.0, 1.0, steps + 1)
    uu, vv = np.meshgrid(weights, weights, indexing="ij")
    mask = uu + vv <= 1.0
    samples = (
        points[0]
        + uu[mask, None] * (points[1] - points[0])
        + vv[mask, None] * (points[2] - points[0])
    )
    index = np.floor((samples - origin) / pitch).astype(np.int64)
    ok = np.all((index >= 0) & (index < grid.shape), axis=1)
    index = index[ok]
    grid[index[:, 0], index[:, 1], index[:, 2]] = 1


def close_shell(source: Path, destination: Path, pitch: float = 0.02) -> None:
    triangles = read_triangles(source.read_bytes())
    loops = _boundary_loops(triangles)
    capped = list(triangles)
    for loop in loops:
        capped.extend(_cap(loop))
    points = np.asarray([vertex for tri in capped for vertex in tri], dtype=np.float64)
    low = points.min(axis=0) - 3 * pitch
    high = points.max(axis=0) + 3 * pitch
    shape = tuple(int(np.ceil((high[axis] - low[axis]) / pitch)) + 1 for axis in range(3))
    grid = np.zeros(shape, dtype=np.uint8)
    for triangle in capped:
        _mark_triangle(grid, low, pitch, triangle)
    dilated = grid.copy()
    for shift in (-1, 1):
        for axis in range(3):
            dilated = np.maximum(dilated, np.roll(grid, shift, axis=axis))
    outside = np.zeros(shape, dtype=np.uint8)
    queue: deque[tuple[int, int, int]] = deque()
    nx, ny, nz = shape
    for i in range(nx):
        for j in range(ny):
            for k in (0, nz - 1):
                if dilated[i, j, k] == 0:
                    outside[i, j, k] = 1
                    queue.append((i, j, k))
    for j in range(ny):
        for k in range(nz):
            for i in (0, nx - 1):
                if dilated[i, j, k] == 0 and outside[i, j, k] == 0:
                    outside[i, j, k] = 1
                    queue.append((i, j, k))
    for i in range(nx):
        for k in range(nz):
            for j in (0, ny - 1):
                if dilated[i, j, k] == 0 and outside[i, j, k] == 0:
                    outside[i, j, k] = 1
                    queue.append((i, j, k))
    while queue:
        i, j, k = queue.popleft()
        for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            ni, nj, nk = i + di, j + dj, k + dk
            if ni < 0 or nj < 0 or nk < 0 or ni >= nx or nj >= ny or nk >= nz:
                continue
            if dilated[ni, nj, nk] or outside[ni, nj, nk]:
                continue
            outside[ni, nj, nk] = 1
            queue.append((ni, nj, nk))
    solid = outside == 0
    volume = float(solid.sum()) * pitch**3
    print(f"loops {len(loops)} grid {shape} volume_m3 {volume:.2f}")
    if not 1.5 <= volume <= 12.0:
        raise SystemExit(f"Closed volume {volume:.2f} m3 is not a car. The shell was not written.")
    vertices, faces = marching_cubes(solid.astype(np.float64), 0.5)
    vertices = vertices * pitch + low
    total = 0.0
    for face in faces:
        total += float(np.dot(vertices[face[0]], np.cross(vertices[face[1]], vertices[face[2]])))
    if total < 0:
        faces = faces[:, [0, 2, 1]]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        handle.write(b"gasCFD CadNav exterior body, windows closed".ljust(80, b" "))
        handle.write(struct.pack("<I", len(faces)))
        for face in faces:
            tri = vertices[face]
            ax, ay, az = tri[0]
            bx, by, bz = tri[1]
            cx, cy, cz = tri[2]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            normal = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
            handle.write(struct.pack("<12fH", *normal, ax, ay, az, bx, by, bz, cx, cy, cz, 0))
    span = vertices.max(axis=0) - vertices.min(axis=0)
    print(f"triangles {len(faces)} extents {span[0]:.3f} {span[1]:.3f} {span[2]:.3f}")


if __name__ == "__main__":
    close_shell(Path(sys.argv[1]), Path(sys.argv[2]))
