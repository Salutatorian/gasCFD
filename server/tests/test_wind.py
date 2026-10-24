import numpy as np
from fastapi.testclient import TestClient

from app.geometry import read_triangles
from app.main import app
from app.paths import geometry_file
from app.road_load import drag_from_cd
from app.tunnel import flow_field, prepare_mask, rolling_walls, solve_mask
from app.wheel_wells import Wheel, find_wheels, skin_half_width, well_boxes
from app import wind
from app.wind import fuel_view

client = TestClient(app)


def test_cube_drag_pushes_downstream():
    mask = np.zeros((40, 24, 24), np.uint8)
    mask[:, 0, :] = 2
    mask[:, -1, :] = 2
    mask[:, :, 0] = 2
    mask[:, :, -1] = 2
    mask[14:22, 8:16, 6:14] = 1
    result = solve_mask(mask, 0.05, 10.0, reynolds=60, length_cells=8, steps=350, u_lb=0.05)
    assert not isinstance(result, tuple)
    assert result.drag_n > 0
    assert 0.4 < result.cd < 12


def test_a_moving_wall_drags_the_air_with_it():
    nx, ny, nz = 24, 8, 18
    mask = np.zeros((nx, ny, nz), np.uint8)
    mask[:, :, 0] = 2
    mask[:, :, -1] = 2
    mask[1, 1, 1] = 1
    wall = np.zeros((nx, ny, nz, 3), np.float64)
    wall[:, :, -1, 0] = 0.08
    solved = solve_mask(
        mask,
        0.05,
        10.0,
        reynolds=8,
        length_cells=float(nz - 2),
        steps=500,
        u_lb=0.02,
        keep_field=True,
        wall_u=wall,
    )
    assert isinstance(solved, tuple)
    _result, fluid = solved
    vx, _, _, _ = flow_field(fluid, 0.02, 10.0)
    top = float(vx[nx // 2, ny // 2, nz - 2])
    mid = float(vx[nx // 2, ny // 2, nz // 2])
    assert top > 0
    assert top > mid


def test_the_tire_contact_moves_with_the_road():
    mask = np.zeros((20, 12, 16), np.uint8)
    mask[:, :, 0] = 2
    mask[12, 6, 3] = 1
    wheel = Wheel("front", "left", 0.35, 0.85, -0.2, 0.2, 0.0, 0.5)
    wall = rolling_walls(mask, np.array([0.0, -0.3, -0.05]), 0.05, [wheel], 0.06)
    assert float(wall[1, 1, 0, 0]) == 0.06
    assert float(wall[12, 6, 3, 0]) > 0


def test_arch_covers_are_flush_and_leave_the_tire_bottom():
    triangles = read_triangles(geometry_file("stock/geometry.stl").read_bytes())
    wheels = find_wheels(triangles)
    assert len(wheels) == 4
    skin = skin_half_width(triangles)
    boxes = well_boxes(wheels, triangles, front=True, rear=False)
    assert len(boxes) == 2
    assert {box.axle for box in boxes} == {"front"}
    for box in boxes:
        wheel = next(item for item in wheels if item.axle == box.axle and item.side == box.side)
        face = max(abs(wheel.y0), abs(wheel.y1))
        outer = max(abs(box.y0), abs(box.y1))
        assert abs(outer - face) <= 0.03
        assert outer < skin
        assert 0.04 <= box.y1 - box.y0 <= 0.12
        assert box.x1 - box.x0 > 0.5
        assert box.z0 >= wheel.center[2] - 0.02
        assert box.z1 <= wheel.z1 + 0.05
        assert box.z0 < wheel.z1 - 0.15
    open_mask, _ = prepare_mask(triangles, [], dx=0.1)
    covered, _ = prepare_mask(triangles, boxes, dx=0.1)
    assert int((covered == 1).sum()) >= int((open_mask == 1).sum())


def test_fuel_uses_the_drag_change_not_the_tunnel_cd():
    published = {"cd": 0.32, "area_m2": 2.2, "mass_kg": 1215.0, "speed_m_s": 17.8816}
    base = drag_from_cd(0.32, published["speed_m_s"], 2.2)
    view = fuel_view(110.0, 100.0, published)
    assert view["drag_ratio"] == 1.1
    assert view["cd"] == 0.32 * 1.1
    assert abs(view["drag_n"] - base * 1.1) < 1e-6
    assert "rose" in str(view["note"])
    assert view["mpg"] is not None and view["stock_mpg"] is not None
    assert view["mpg"] < view["stock_mpg"]


def test_a_second_wind_request_does_not_stick():
    with wind._LOCK:
        wind._running = {"speed_mph": 40, "front": False, "rear": False, "message": "test"}
        wind._pending = None
    try:
        state = wind.start(40, True, False)
    finally:
        with wind._LOCK:
            wind._running = None
            wind._pending = None
    assert state["running"] is True
    assert state["job"]["front"] is False


def test_boxes_stl_is_served():
    response = client.get("/api/wind/boxes.stl?front=true&rear=true")
    assert response.status_code == 200
    assert len(response.content) > 84
    assert response.content[80:84] != b"\x00\x00\x00\x00"
