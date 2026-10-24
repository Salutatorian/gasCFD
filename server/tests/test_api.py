import shutil

from fastapi.testclient import TestClient

from app.catalog import envelope
from app.geometry import write_box_stl
from app.main import app
from app.paths import vehicle_dir


def test_comparison_does_not_invent_coefficients():
    client = TestClient(app)
    response = client.get(
        "/api/comparison",
        params={"baseline": "001", "variant": "004", "speed_mph": 60, "yaw_deg": 0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["baseline"]["cd"] is None
    assert body["baseline"]["drag_n"] is None
    assert body["variant"]["aero_power_w"] is None
    assert body["fuel"]["baseline_mpg"] is None
    assert body["fuel"]["variant_mpg"] is None
    assert body["fuel"]["uses_published_cd"] is False
    assert body["fuel"]["brochure_highway_mpg"] == 36
    assert body["published_cd"]["value"] == 0.32
    assert body["published_cd"]["used_in_results"] is False


def test_live_math_shows_formulas_without_inventing_cover_cd(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    folder = runs / "fluidx3d" / "60mph"
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(
        '{"cd_mean_second_half": 0.93, "frontal_area_m2": 2.42, "blockage_ratio": 0.137}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GASCFD_RUNS", str(runs))
    client = TestClient(app)
    body = client.get(
        "/api/math",
        params={"baseline": "001", "variant": "003", "speed_mph": 60, "yaw_deg": 0},
    ).json()
    kinds = [column["kind"] for column in body["columns"]]
    assert kinds[0] == "published"
    assert kinds.count("openfoam") == 7
    assert "fluidx3d" in kinds
    published = body["columns"][0]
    covers = next(column for column in body["columns"] if column["id"] == "openfoam-003")
    skirts = next(column for column in body["columns"] if column["id"] == "openfoam-004")
    fluid = next(column for column in body["columns"] if column["kind"] == "fluidx3d")
    assert published["cd"] == 0.32
    assert published["mpg"] is not None
    assert published["used_for_fuel"] is False
    assert covers["cd"] is None
    assert covers["mpg"] is None
    assert covers["missing"] is not None and "OpenFOAM" in covers["missing"]
    assert skirts["missing"] is not None and "No STL" in skirts["missing"]
    assert fluid["cd"] == 0.93
    assert fluid["mpg"] is None
    assert fluid["used_for_fuel"] is False
    assert body["rolling_n"] > 0


def test_run_without_geometry_is_rejected():
    client = TestClient(app)
    response = client.post("/api/experiments/004/runs", json={"speed_mph": 60, "yaw_deg": 0})
    assert response.status_code == 409
    assert "geometry" in response.json()["detail"].lower()


def test_forty_mph_is_allowed():
    client = TestClient(app)
    assert client.get("/api/math", params={"speed_mph": 40, "yaw_deg": 0}).status_code == 200
    assert client.get("/api/comparison", params={"speed_mph": 40, "yaw_deg": 0}).status_code == 200


def test_speed_outside_the_plan_is_rejected():
    client = TestClient(app)
    response = client.post("/api/experiments/001/runs", json={"speed_mph": 55, "yaw_deg": 0})
    assert response.status_code == 422


def test_experiments_match_the_plan():
    client = TestClient(app)
    payload = client.get("/api/experiments").json()
    assert [item["id"] for item in payload] == ["001", "002", "003", "004", "005", "006", "007"]
    assert payload[0]["geometry_report"]["present"] is True
    assert payload[0]["geometry_report"]["valid"] is False
    assert payload[0]["geometry_report"]["runnable"] is True
    assert payload[1]["geometry_report"]["present"] is True
    assert payload[2]["geometry_report"]["present"] is True
    assert all(item["geometry_report"]["present"] is False for item in payload[3:])


def test_upload_and_disabled_solver_do_not_create_a_result(tmp_path, monkeypatch):
    vehicle = tmp_path / "vehicle"
    runs = tmp_path / "runs"
    shutil.copytree(vehicle_dir(), vehicle)
    monkeypatch.setenv("GASCFD_VEHICLE_DIR", str(vehicle))
    monkeypatch.setenv("GASCFD_RUNS", str(runs))
    monkeypatch.setenv("GASCFD_SOLVER", "off")
    spec = envelope()
    stl = tmp_path / "box.stl"
    write_box_stl(stl, spec.length, spec.width, spec.height)
    client = TestClient(app)
    uploaded = client.post(
        "/api/experiments/001/geometry",
        files={"file": ("geometry.stl", stl.read_bytes(), "model/stl")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["valid"] is True
    assert uploaded.json()["signed_off"] is False
    started = client.post("/api/experiments/001/runs", json={"speed_mph": 60, "yaw_deg": 0})
    assert started.status_code == 202
    job = started.json()
    assert job["status"] == "error"
    assert "no forces" in job["message"].lower()
    assert not (runs / "results.json").exists()
    comparison = client.get("/api/comparison", params={"speed_mph": 60, "yaw_deg": 0}).json()
    assert comparison["baseline"]["cd"] is None
    assert comparison["fuel"]["baseline_mpg"] is None
