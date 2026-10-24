"""Split the CadNav Matrix into body, front wheels, and rear wheels for FluidX3D.

The three files hold exactly the triangles of the stock geometry.stl, in the
same frame, so FluidX3D can spin the wheels while solving the same car.

Usage: python fluidx3d_parts.py <Toyota_Matrix.3ds> <output dir>
"""

import sys
from pathlib import Path

from cadnav_matrix_to_stl import WHEEL_NAMES, placed_objects, write_stl


def split(source: Path, destination: Path) -> None:
    objects = placed_objects(source)
    wheels = [(name, tris) for name, tris in objects if name in WHEEL_NAMES]
    wheels.sort(key=lambda item: sum(v[0] for tri in item[1] for v in tri) / (3 * len(item[1])))
    body = [tri for name, tris in objects if name not in WHEEL_NAMES for tri in tris]
    front = [tri for _, tris in wheels[:2] for tri in tris]
    rear = [tri for _, tris in wheels[2:] for tri in tris]
    write_stl(destination / "body.stl", body)
    write_stl(destination / "front-wheels.stl", front)
    write_stl(destination / "rear-wheels.stl", rear)
    print(f"body {len(body)} front {len(front)} rear {len(rear)} total {len(body) + len(front) + len(rear)}")


if __name__ == "__main__":
    split(Path(sys.argv[1]), Path(sys.argv[2]))
