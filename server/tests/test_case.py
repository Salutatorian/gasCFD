import math

from app.catalog import envelope, wheelbase_m
from app.geometry import write_box_stl
from app.openfoam_case import write_case
from app.paths import MPH_TO_MPS


def test_case_keeps_body_axis_drag_and_a_bounded_mesh(tmp_path):
    spec = envelope()
    stl = tmp_path / "geometry.stl"
    write_box_stl(stl, spec.length, spec.width, spec.height)
    case = tmp_path / "case"
    meta = write_case(
        case,
        stl,
        experiment_id="001",
        speed_m_s=60 * MPH_TO_MPS,
        speed_mph=60,
        yaw_deg=0,
        aref_m2=2.2,
        wheelbase_m=wheelbase_m(),
        geometry_sha256="abc",
        geometry_signed_off=False,
    )
    control = (case / "system" / "controlDict").read_text(encoding="utf-8")
    assert "dragDir         (1 0 0);" in control
    assert "simpleFoam" in control
    assert meta["background_cells"] < 2_000_000
    block = (case / "system" / "blockMeshDict").read_text(encoding="utf-8")
    assert f"({meta['nx']} {meta['ny']} {meta['nz']})" in block
    assert meta["location_in_mesh"][0] < 0
    script = (case / "run.sh").read_bytes()
    assert b"\r" not in script
    assert b"snappyHexMesh -overwrite" in script
    velocity = (case / "0" / "U").read_text(encoding="utf-8")
    assert f"{60 * MPH_TO_MPS:.8g}" in velocity


def test_yaw_changes_the_inlet_and_not_the_drag_axis(tmp_path):
    spec = envelope()
    stl = tmp_path / "geometry.stl"
    write_box_stl(stl, spec.length, spec.width, spec.height)
    case = tmp_path / "case"
    speed = 60 * MPH_TO_MPS
    write_case(
        case,
        stl,
        experiment_id="001",
        speed_m_s=speed,
        speed_mph=60,
        yaw_deg=15,
        aref_m2=2.2,
        wheelbase_m=wheelbase_m(),
        geometry_sha256="abc",
        geometry_signed_off=False,
    )
    velocity = (case / "0" / "U").read_text(encoding="utf-8")
    assert f"{speed * math.cos(math.radians(15)):.8g}" in velocity
    assert f"{speed * math.sin(math.radians(15)):.8g}" in velocity
    control = (case / "system" / "controlDict").read_text(encoding="utf-8")
    assert "dragDir         (1 0 0);" in control
