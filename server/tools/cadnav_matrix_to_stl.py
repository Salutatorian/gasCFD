"""Turn the CadNav Toyota Matrix .3ds into an OpenFOAM-oriented binary STL.

The download has no STL. Vertices in this file are already in world space:
X is width, Y is length, Z is up. The wipers sit at the negative-Y end, so
that end is the nose. Wheelbase is scaled to the published 2.6 m.
"""

import struct
import sys
from pathlib import Path

WHEELBASE_M = 2.6
WHEEL_NAMES = {"Toyota_Ma6", "Toyota_Ma7", "Toyota_Ma8", "Toyota_Ma9"}


def _cstr(buf: bytes, index: int) -> tuple[str, int]:
    end = buf.index(b"\x00", index)
    return buf[index:end].decode("latin1", "replace"), end + 1


def read_objects(path: Path) -> list[dict]:
    data = path.read_bytes()
    objects: list[dict] = []

    def walk(start: int, end: int, mesh: dict | None) -> None:
        index = start
        while index + 6 <= end:
            chunk_id, length = struct.unpack_from("<HI", data, index)
            if length < 6:
                return
            chunk_end = index + length
            if chunk_end > end:
                return
            if chunk_id == 0x4000:
                name, name_end = _cstr(data, index + 6)
                mesh = {"name": name, "verts": [], "faces": []}
                objects.append(mesh)
                walk(name_end, chunk_end, mesh)
            elif chunk_id == 0x4110 and mesh is not None:
                count = struct.unpack_from("<H", data, index + 6)[0]
                cursor = index + 8
                verts = mesh["verts"]
                for _ in range(count):
                    verts.append(struct.unpack_from("<3f", data, cursor))
                    cursor += 12
            elif chunk_id == 0x4120 and mesh is not None:
                count = struct.unpack_from("<H", data, index + 6)[0]
                cursor = index + 8
                faces = mesh["faces"]
                for _ in range(count):
                    a, b, c, _flags = struct.unpack_from("<4H", data, cursor)
                    faces.append((a, b, c))
                    cursor += 8
            elif chunk_id in (0x4D4D, 0x3D3D, 0x4100):
                walk(index + 6, chunk_end, mesh)
            index = chunk_end

    walk(0, len(data), None)
    return objects


def _to_body_axes(point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (y, x, z)


def placed_objects(source: Path) -> list[tuple[str, list]]:
    """Return (object name, triangles) in meters, nose at x=0, centered in y, ground at z=0."""
    objects = read_objects(source)
    wheels: list[tuple[float, float, float]] = []
    named: list[tuple[str, list]] = []
    for obj in objects:
        verts = [_to_body_axes(vertex) for vertex in obj["verts"]]
        if obj["name"] in WHEEL_NAMES and verts:
            count = len(verts)
            wheels.append(
                (
                    sum(vertex[0] for vertex in verts) / count,
                    sum(vertex[1] for vertex in verts) / count,
                    sum(vertex[2] for vertex in verts) / count,
                )
            )
        tris = [
            (verts[a], verts[b], verts[c])
            for a, b, c in obj["faces"]
            if max(a, b, c) < len(verts)
        ]
        named.append((obj["name"], tris))
    triangles = [tri for _, tris in named for tri in tris]

    if len(wheels) != 4:
        raise SystemExit(f"Expected 4 wheel meshes, found {len(wheels)}")
    wheels.sort(key=lambda center: center[0])
    front = wheels[:2]
    rear = wheels[2:]
    wheelbase_units = (rear[0][0] + rear[1][0]) / 2 - (front[0][0] + front[1][0]) / 2
    if wheelbase_units <= 0:
        raise SystemExit("Wheelbase came out backwards.")
    scale = WHEELBASE_M / wheelbase_units

    xs = [vertex[0] * scale for tri in triangles for vertex in tri]
    ys = [vertex[1] * scale for tri in triangles for vertex in tri]
    zs = [vertex[2] * scale for tri in triangles for vertex in tri]
    shift = (-min(xs), -0.5 * (min(ys) + max(ys)), -min(zs))
    print(f"objects {len(objects)} triangles {len(triangles)}")
    print(f"wheelbase_units {wheelbase_units:.3f} scale_m {scale:.6f}")
    print(f"extents {max(xs) - min(xs):.3f} {max(ys) - min(ys):.3f} {max(zs) - min(zs):.3f}")
    return [
        (
            name,
            [
                tuple(
                    (v[0] * scale + shift[0], v[1] * scale + shift[1], v[2] * scale + shift[2])
                    for v in tri
                )
                for tri in tris
            ],
        )
        for name, tris in named
    ]


def write_stl(destination: Path, triangles: list) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        handle.write(b"gasCFD CadNav Matrix C0817078".ljust(80, b" "))
        handle.write(struct.pack("<I", len(triangles)))
        for tri in triangles:
            ax, ay, az = tri[0]
            bx, by, bz = tri[1]
            cx, cy, cz = tri[2]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            handle.write(struct.pack("<12fH", nx, ny, nz, ax, ay, az, bx, by, bz, cx, cy, cz, 0))


def convert(source: Path, destination: Path) -> None:
    write_stl(destination, [tri for _, tris in placed_objects(source) for tri in tris])


if __name__ == "__main__":
    convert(Path(sys.argv[1]), Path(sys.argv[2]))

