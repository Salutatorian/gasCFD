"""Build a closed body from the CadNav Matrix panels.

Keeps the real exterior triangles. Drops the cabin (Toyota_Ma4).
Welds panel gaps, then caps the remaining openings so the windows are filled
and the solver has one solid skin.
"""

import struct
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.cadnav_matrix_to_stl import WHEEL_NAMES, WHEELBASE_M, _to_body_axes, read_objects

BODY_NAMES = {"Toyota_Ma1", "Toyota_Ma2", "Toyota_Ma3", "Toyota_Ma5", *WHEEL_NAMES}
SOURCE = Path(r"C:\Users\JW\Downloads\cadnav-160Z5200547\cadnav.com_model\Model_C0817078\Toyota_Matrix.3ds")


def placed_triangles(source: Path) -> list[tuple]:
    objects = read_objects(source)
    raw: list[tuple] = []
    wheels: list[float] = []
    for obj in objects:
        if obj["name"] not in BODY_NAMES:
            continue
        verts = [_to_body_axes(vertex) for vertex in obj["verts"]]
        if obj["name"] in WHEEL_NAMES and verts:
            wheels.append(sum(vertex[0] for vertex in verts) / len(verts))
        for a, b, c in obj["faces"]:
            if max(a, b, c) >= len(verts):
                continue
            raw.append((verts[a], verts[b], verts[c]))
    wheels.sort()
    if len(wheels) != 4:
        raise SystemExit(f"Expected 4 wheels, found {len(wheels)}")
    scale = WHEELBASE_M / ((wheels[2] + wheels[3]) / 2 - (wheels[0] + wheels[1]) / 2)
    scaled = [
        tuple(tuple(coord * scale for coord in vertex) for vertex in tri)
        for tri in raw
    ]
    xs = [vertex[0] for tri in scaled for vertex in tri]
    ys = [vertex[1] for tri in scaled for vertex in tri]
    zs = [vertex[2] for tri in scaled for vertex in tri]
    shift = (-min(xs), -0.5 * (min(ys) + max(ys)), -min(zs))
    return [
        tuple(tuple(vertex[axis] + shift[axis] for axis in range(3)) for vertex in tri)
        for tri in scaled
    ]


def weld(triangles: list[tuple], tolerance: float) -> tuple[list[tuple], list[tuple[int, int, int]]]:
    index: dict[tuple[int, int, int], int] = {}
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    def vid(point: tuple[float, float, float]) -> int:
        key = tuple(int(round(point[axis] / tolerance)) for axis in range(3))
        found = index.get(key)
        if found is None:
            found = len(verts)
            index[key] = found
            verts.append(point)
        return found

    for tri in triangles:
        ids = tuple(vid(vertex) for vertex in tri)
        if len(set(ids)) == 3:
            faces.append(ids)  # type: ignore[arg-type]
    return verts, faces


def boundary_loops(verts: list[tuple], faces: list[tuple[int, int, int]]) -> list[list[int]]:
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for a, b, c in faces:
        for start, end in ((a, b), (b, c), (c, a)):
            counts[tuple(sorted((start, end)))] += 1
    adjacency: dict[int, list[int]] = defaultdict(list)
    for (start, end), count in counts.items():
        if count == 1:
            adjacency[start].append(end)
            adjacency[end].append(start)
    seen: set[int] = set()
    loops: list[list[int]] = []
    for start in list(adjacency):
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        previous = None
        current = start
        for _ in range(len(adjacency) + 1):
            nxt = [point for point in adjacency[current] if point != previous and point not in seen]
            if not nxt:
                break
            previous, current = current, nxt[0]
            seen.add(current)
            loop.append(current)
        if len(loop) >= 3 and start in adjacency[loop[-1]]:
            loops.append(loop)
    return loops


def cap(verts: list[tuple], faces: list[tuple[int, int, int]], loop: list[int]) -> None:
    points = [verts[index] for index in loop]
    count = len(points)
    centroid = tuple(sum(point[axis] for point in points) / count for axis in range(3))
    center = len(verts)
    verts.append(centroid)
    for index in range(count):
        faces.append((center, loop[index], loop[(index + 1) % count]))


def edge_counts(faces: list[tuple[int, int, int]]) -> dict[int, int]:
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for a, b, c in faces:
        for start, end in ((a, b), (b, c), (c, a)):
            counts[tuple(sorted((start, end)))] += 1
    histogram: dict[int, int] = defaultdict(int)
    for count in counts.values():
        histogram[count] += 1
    return histogram


def signed_volume(verts: list[tuple], faces: list[tuple[int, int, int]]) -> float:
    total = 0.0
    for a, b, c in faces:
        ax, ay, az = verts[a]
        bx, by, bz = verts[b]
        cx, cy, cz = verts[c]
        total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
    return total / 6.0


def write_stl(path: Path, verts: list[tuple], faces: list[tuple[int, int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(b"gasCFD CadNav body panels, windows filled".ljust(80, b" "))
        handle.write(struct.pack("<I", len(faces)))
        for a, b, c in faces:
            ax, ay, az = verts[a]
            bx, by, bz = verts[b]
            cx, cy, cz = verts[c]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            handle.write(
                struct.pack(
                    "<12fH",
                    uy * vz - uz * vy,
                    uz * vx - ux * vz,
                    ux * vy - uy * vx,
                    ax, ay, az, bx, by, bz, cx, cy, cz,
                    0,
                )
            )


def merge_close_boundary(verts: list[tuple], faces: list[tuple[int, int, int]], tolerance: float) -> list[tuple[int, int, int]]:
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for a, b, c in faces:
        for start, end in ((a, b), (b, c), (c, a)):
            counts[tuple(sorted((start, end)))] += 1
    boundary = [index for edge, count in counts.items() if count == 1 for index in edge]
    parent = {index: index for index in set(boundary)}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    unique = list(parent)
    for left in range(len(unique)):
        a = verts[unique[left]]
        for right in range(left + 1, len(unique)):
            b = verts[unique[right]]
            if (
                abs(a[0] - b[0]) <= tolerance
                and abs(a[1] - b[1]) <= tolerance
                and abs(a[2] - b[2]) <= tolerance
            ):
                parent[find(unique[right])] = find(unique[left])
    merged: list[tuple[int, int, int]] = []
    for a, b, c in faces:
        ids = tuple(find(index) if index in parent else index for index in (a, b, c))
        if len(set(ids)) == 3:
            merged.append(ids)  # type: ignore[arg-type]
    return merged


def split_slits(verts: list[tuple], faces: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    for _ in range(6):
        counts: dict[tuple[int, int], int] = defaultdict(int)
        owner: dict[tuple[int, int], tuple[int, int, int]] = {}
        for face in faces:
            a, b, c = face
            for start, end in ((a, b), (b, c), (c, a)):
                edge = tuple(sorted((start, end)))
                counts[edge] += 1
                owner[edge] = face
        changed = False
        extra: list[tuple[int, int, int]] = []
        removed: set[tuple[int, int, int]] = set()
        for edge, count in counts.items():
            if count != 1 or edge not in owner:
                continue
            first, second = edge
            start = verts[first]
            end = verts[second]
            span = [end[axis] - start[axis] for axis in range(3)]
            length2 = sum(value * value for value in span)
            if length2 < 1e-8:
                continue
            nearest = None
            nearest_dist = 0.004
            for index, point in enumerate(verts):
                if index in (first, second):
                    continue
                offset = [point[axis] - start[axis] for axis in range(3)]
                along = sum(offset[axis] * span[axis] for axis in range(3)) / length2
                if along <= 0.05 or along >= 0.95:
                    continue
                closest = [start[axis] + along * span[axis] for axis in range(3)]
                gap = sum((point[axis] - closest[axis]) ** 2 for axis in range(3)) ** 0.5
                if gap < nearest_dist:
                    nearest = index
                    nearest_dist = gap
            if nearest is None:
                continue
            face = owner[edge]
            third = next(index for index in face if index not in edge)
            removed.add(face)
            extra.append((first, nearest, third))
            extra.append((nearest, second, third))
            changed = True
        if not changed:
            break
        faces = [face for face in faces if face not in removed]
        faces.extend(extra)
    return faces


def seal(verts: list[tuple], faces: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    for _ in range(8):
        loops = boundary_loops(verts, faces)
        if not loops:
            break
        for loop in loops:
            cap(verts, faces, loop)
        faces = merge_close_boundary(verts, faces, 0.012)
    return split_slits(verts, faces)


def build(destination: Path) -> None:
    triangles = placed_triangles(SOURCE)
    print(f"exterior triangles {len(triangles)}")
    verts, faces = weld(triangles, 0.004)
    print("after 4 mm weld", dict(sorted(edge_counts(faces).items())))
    faces = seal(verts, faces)
    print("after seal", dict(sorted(edge_counts(faces).items())))
    volume = signed_volume(verts, faces)
    if volume < 0:
        faces = [(a, c, b) for a, b, c in faces]
        volume = -volume
    histogram = edge_counts(faces)
    if histogram.get(1, 0) != 0:
        counts: dict[tuple[int, int], int] = defaultdict(int)
        for a, b, c in faces:
            for start, end in ((a, b), (b, c), (c, a)):
                counts[tuple(sorted((start, end)))] += 1
        for start, end in counts:
            if counts[(start, end)] != 1:
                continue
            gap = sum((verts[start][axis] - verts[end][axis]) ** 2 for axis in range(3)) ** 0.5
            mid = tuple((verts[start][axis] + verts[end][axis]) / 2 for axis in range(3))
            nearest = min(
                sum((point[axis] - mid[axis]) ** 2 for axis in range(3)) ** 0.5
                for index, point in enumerate(verts)
                if index not in (start, end)
            )
            print(f"open {gap:.3f} m nearest {nearest:.3f} at {mid[0]:.2f} {mid[1]:.2f} {mid[2]:.2f}")
        raise SystemExit(f"Body still has {histogram[1]} open edges. Not written.")
    xs = [point[0] for point in verts]
    ys = [point[1] for point in verts]
    zs = [point[2] for point in verts]
    print(
        f"triangles {len(faces)} volume_m3 {volume:.2f} "
        f"extents {max(xs) - min(xs):.3f} {max(ys) - min(ys):.3f} {max(zs) - min(zs):.3f}"
    )
    write_stl(destination, verts, faces)


if __name__ == "__main__":
    build(Path(sys.argv[1]))
