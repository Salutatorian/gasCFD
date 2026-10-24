from app.catalog import envelope
from app.geometry import inspect_bytes, projected_area_yz, read_triangles, write_box_stl


def test_meter_box_matches_matrix_envelope(tmp_path):
    path = tmp_path / "box.stl"
    spec = envelope()
    write_box_stl(path, spec.length, spec.width, spec.height)
    report = inspect_bytes(path.read_bytes(), spec, signed_off=False)
    assert report.valid
    assert report.signed_off is False
    assert report.projected_area_m2 == pytest_area(spec.width, spec.height)


def test_binary_box_has_the_same_extents(tmp_path):
    path = tmp_path / "box.stl"
    spec = envelope()
    write_box_stl(path, spec.length, spec.width, spec.height, binary=True)
    report = inspect_bytes(path.read_bytes(), spec, signed_off=False)
    assert report.valid
    assert report.triangles == 12


def test_millimetre_export_is_rejected(tmp_path):
    path = tmp_path / "box.stl"
    spec = envelope()
    write_box_stl(path, spec.length * 1000, spec.width * 1000, spec.height * 1000)
    report = inspect_bytes(path.read_bytes(), spec, signed_off=False)
    assert not report.valid
    assert not report.runnable
    assert "meters" in report.message


def test_y_up_export_is_rejected(tmp_path):
    path = tmp_path / "box.stl"
    spec = envelope()
    write_box_stl(path, spec.length, spec.height, spec.width)
    report = inspect_bytes(path.read_bytes(), spec, signed_off=False)
    assert not report.valid
    assert not report.runnable
    assert any("Z-up" in issue for issue in report.issues)


def test_off_brochure_meter_mesh_can_still_run(tmp_path):
    path = tmp_path / "tall.stl"
    spec = envelope()
    write_box_stl(path, spec.length, spec.width, spec.height + 0.3)
    report = inspect_bytes(path.read_bytes(), spec, signed_off=False)
    assert not report.valid
    assert report.runnable
    assert report.projected_area_m2 is not None


def test_projected_area_of_the_nose(tmp_path):
    path = tmp_path / "box.stl"
    write_box_stl(path, 4.35, 1.775, 1.54)
    area, _pitch = projected_area_yz(read_triangles(path.read_bytes()))
    assert area == pytest_area(1.775, 1.54)


def pytest_area(width: float, height: float) -> float:
    from pytest import approx

    return approx(width * height, rel=0.03)
