import hashlib
import json
import math
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path

Triangle = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


@dataclass
class Envelope:
    length: float
    width: float
    height: float
    length_tol: float
    width_tol: float
    height_tol: float


@dataclass
class GeometryReport:
    present: bool
    valid: bool
    signed_off: bool
    message: str
    triangles: int | None = None
    bbox_min_m: list[float] | None = None
    bbox_max_m: list[float] | None = None
    extents_m: dict[str, float] | None = None
    projected_area_m2: float | None = None
    area_pitch_m: float | None = None
    sha256: str | None = None
    issues: list[str] = field(default_factory=list)
    runnable: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_INSPECT_CACHE: dict[tuple[str, bool], GeometryReport] = {}


def _remember(report: GeometryReport) -> GeometryReport:
    if report.sha256 is not None:
        _INSPECT_CACHE[(report.sha256, report.signed_off)] = report
    return report


def missing_report() -> GeometryReport:
    return GeometryReport(
        present=False,
        valid=False,
        signed_off=False,
        message="No geometry.stl for this experiment.",
    )


def box_triangles(length: float, width: float, height: float) -> list[Triangle]:
    x0, x1 = 0.0, length
    y0, y1 = -width / 2.0, width / 2.0
    z0, z1 = 0.0, height
    corners = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    faces = (
        (0, 4, 7),
        (0, 7, 3),
        (1, 2, 6),
        (1, 6, 5),
        (0, 3, 2),
        (0, 2, 1),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (3, 7, 6),
        (3, 6, 2),
    )
    return [(corners[i], corners[j], corners[k]) for i, j, k in faces]


def write_box_stl(
    path: Path,
    length: float,
    width: float,
    height: float,
    *,
    binary: bool = False,
) -> None:
    triangles = box_triangles(length, width, height)
    if binary:
        blob = bytearray(b"\0" * 80)
        blob += struct.pack("<I", len(triangles))
        for tri in triangles:
            flat = [0.0, 0.0, 0.0]
            for vertex in tri:
                flat.extend(vertex)
            blob += struct.pack("<12fH", *flat, 0)
        path.write_bytes(blob)
        return
    lines = ["solid gascfd-box"]
    for tri in triangles:
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        for vertex in tri:
            lines.append(f"      vertex {vertex[0]} {vertex[1]} {vertex[2]}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid gascfd-box")
    path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")


def read_triangles(data: bytes) -> list[Triangle]:
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        expected = 84 + count * 50
        if 0 < count < 50_000_000 and len(data) == expected:
            return _read_binary(data, count)
    return _read_ascii(data)


def _read_binary(data: bytes, count: int) -> list[Triangle]:
    triangles: list[Triangle] = []
    for index in range(count):
        offset = 84 + index * 50
        nums = struct.unpack_from("<12f", data, offset)
        triangles.append(
            (
                (nums[3], nums[4], nums[5]),
                (nums[6], nums[7], nums[8]),
                (nums[9], nums[10], nums[11]),
            )
        )
    return triangles


def _read_ascii(data: bytes) -> list[Triangle]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("STL is neither a binary STL nor UTF-8 text.") from exc
    vertices: list[tuple[float, float, float]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "vertex":
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
    if len(vertices) < 3 or len(vertices) % 3 != 0:
        raise ValueError("STL text does not contain complete triangles.")
    return list(zip(vertices[0::3], vertices[1::3], vertices[2::3]))


def bounds(
    triangles: list[Triangle],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = [vertex[0] for tri in triangles for vertex in tri]
    ys = [vertex[1] for tri in triangles for vertex in tri]
    zs = [vertex[2] for tri in triangles for vertex in tri]
    if not xs or not all(math.isfinite(value) for value in xs + ys + zs):
        raise ValueError("STL coordinates are missing or not finite.")
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def projected_area_yz(triangles: list[Triangle], pitch: float = 0.005) -> tuple[float, float]:
    ys = [vertex[1] for tri in triangles for vertex in tri]
    zs = [vertex[2] for tri in triangles for vertex in tri]
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)
    span_y = max(ymax - ymin, pitch)
    span_z = max(zmax - zmin, pitch)
    while math.ceil(span_y / pitch) * math.ceil(span_z / pitch) > 4_000_000:
        pitch *= 2
    ny = max(1, int(math.ceil(span_y / pitch)))
    nz = max(1, int(math.ceil(span_z / pitch)))
    occupied = bytearray(ny * nz)

    def mark_triangle(tri: Triangle) -> None:
        points = ((tri[0][1], tri[0][2]), (tri[1][1], tri[1][2]), (tri[2][1], tri[2][2]))
        min_y = min(point[0] for point in points)
        max_y = max(point[0] for point in points)
        min_z = min(point[1] for point in points)
        max_z = max(point[1] for point in points)
        iy0 = max(0, int((min_y - ymin) / pitch) - 1)
        iy1 = min(ny - 1, int((max_y - ymin) / pitch) + 1)
        iz0 = max(0, int((min_z - zmin) / pitch) - 1)
        iz1 = min(nz - 1, int((max_z - zmin) / pitch) + 1)
        for iy in range(iy0, iy1 + 1):
            cy = ymin + (iy + 0.5) * pitch
            for iz in range(iz0, iz1 + 1):
                cz = zmin + (iz + 0.5) * pitch
                if _inside(cy, cz, points):
                    occupied[iy * nz + iz] = 1

    for tri in triangles:
        mark_triangle(tri)
    area = occupied.count(1) * pitch * pitch
    return area, pitch


def _inside(
    px: float,
    py: float,
    points: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> bool:
    (ax, ay), (bx, by), (cx, cy) = points
    denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denominator) < 1e-14:
        return False
    w1 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
    w2 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
    w3 = 1.0 - w1 - w2
    return w1 >= -1e-6 and w2 >= -1e-6 and w3 >= -1e-6


def inspect_bytes(data: bytes, envelope: Envelope, *, signed_off: bool) -> GeometryReport:
    digest = hashlib.sha256(data).hexdigest()
    cached = _INSPECT_CACHE.get((digest, signed_off))
    if cached is not None:
        return cached
    try:
        triangles = read_triangles(data)
        low, high = bounds(triangles)
    except ValueError as exc:
        return _remember(GeometryReport(
            present=True,
            valid=False,
            signed_off=signed_off,
            message=str(exc),
            sha256=digest,
            issues=[str(exc)],
        ))
    dx = high[0] - low[0]
    dy = high[1] - low[1]
    dz = high[2] - low[2]
    extents = {"length_x": dx, "width_y": dy, "height_z": dz}
    report = GeometryReport(
        present=True,
        valid=False,
        signed_off=signed_off,
        message="",
        triangles=len(triangles),
        bbox_min_m=[low[0], low[1], low[2]],
        bbox_max_m=[high[0], high[1], high[2]],
        extents_m=extents,
        sha256=digest,
    )
    largest = max(dx, dy, dz)
    if largest > 20:
        report.issues.append(
            f"Largest dimension is {largest:.1f} m. Export meters. "
            "The Matrix is 4.35 m long, so an inch or millimetre file will fail this check."
        )
    elif largest < 0.5:
        report.issues.append(
            f"Largest dimension is {largest:.3f} m. The Matrix envelope is 4.35 m long."
        )
    else:
        _check_axis(report, "Length (x)", dx, envelope.length, envelope.length_tol)
        _check_axis(report, "Width (y)", dy, envelope.width, envelope.width_tol)
        _check_axis(report, "Height (z)", dz, envelope.height, envelope.height_tol)
        if abs(dy - envelope.height) <= envelope.height_tol and abs(dz - envelope.width) <= envelope.width_tol:
            report.issues.append(
                "Y and Z look swapped. Export Z-up, with width on Y and height on Z."
            )
    swapped = any("Z-up" in issue for issue in report.issues)
    report.runnable = largest <= 20 and largest >= 0.5 and not swapped
    if report.runnable:
        pitch = 0.02 if len(triangles) > 20000 else 0.005
        area, pitch = projected_area_yz(triangles, pitch)
        report.projected_area_m2 = area
        report.area_pitch_m = pitch
    if report.issues:
        if report.runnable:
            report.message = (
                "Size is outside the brochure envelope. "
                "This file can still be solved. The result belongs to this mesh, not a signed-off Matrix."
            )
        else:
            report.message = report.issues[0]
        return _remember(report)
    report.valid = True
    if signed_off:
        report.message = "Bounding box matches the published envelope, and this file is signed off."
    else:
        report.message = (
            "Bounding box matches the published envelope. "
            "The shape is not signed off as a Matrix."
        )
    return _remember(report)


def _check_axis(
    report: GeometryReport,
    label: str,
    measured: float,
    expected: float,
    tolerance: float,
) -> None:
    if abs(measured - expected) > tolerance:
        report.issues.append(
            f"{label} is {measured:.3f} m. Expected {expected:.3f} m, tolerance {tolerance:.3f} m."
        )


def read_signoff(stl_path: Path) -> bool:
    review = stl_path.with_name("review.json")
    if not review.exists():
        return False
    try:
        payload = json.loads(review.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return payload.get("signed_off") is True


def inspect_path(path: Path, envelope: Envelope) -> GeometryReport:
    if not path.exists():
        return missing_report()
    return inspect_bytes(path.read_bytes(), envelope, signed_off=read_signoff(path))
