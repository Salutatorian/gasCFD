from pathlib import Path

from app.geometry import read_triangles
from app.paths import vehicle_dir


def test_all_four_covers_sit_outboard_of_the_rims():
    root = vehicle_dir()
    geometry = root / "wheel-covers" / "all" / "geometry.stl"
    assert geometry.exists()
    stock_front = read_triangles((root / "stock" / "fluidx3d" / "front-wheels.stl").read_bytes())
    covered_front = read_triangles((root / "wheel-covers" / "all" / "fluidx3d" / "front-wheels.stl").read_bytes())
    assert len(covered_front) > len(stock_front)
    stock_y = [abs(point[1]) for tri in stock_front for point in tri]
    covered_y = [abs(point[1]) for tri in covered_front for point in tri]
    assert max(covered_y) > max(stock_y)
    parts = root / "wheel-covers" / "all" / "fluidx3d"
    assert (parts / "body.stl").exists()
    assert (parts / "front-wheels.stl").exists()
    assert (parts / "rear-wheels.stl").exists()
    assert Path(__file__).resolve().parents[2] / "server" / "tools" / "wheel_covers.py"
