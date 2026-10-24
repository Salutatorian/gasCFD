import json

from fastapi.testclient import TestClient

from app.main import app


def test_finished_render_is_listed_without_history(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    folder = runs / "fluidx3d" / "60mph"
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(
        json.dumps({"cd_mean_second_half": 0.9, "cd_history": [[0.1, 1.0]], "wheels": "stationary (not rotating)"}),
        encoding="utf-8",
    )
    (folder / "vortices.mp4").write_bytes(b"mp4")
    monkeypatch.setenv("GASCFD_RUNS", str(runs))
    client = TestClient(app)
    renders = client.get("/api/fluidx3d").json()["renders"]
    assert renders == [
        {
            "experiment_id": "001",
            "speed_mph": 60,
            "videos": ["vortices"],
            "result": {"cd_mean_second_half": 0.9, "wheels": "stationary (not rotating)"},
        }
    ]
    assert client.get("/api/fluidx3d/renders/60/vortices.mp4").content == b"mp4"
    assert client.get("/api/fluidx3d/renders/60/streamlines.mp4").status_code == 404
    assert client.get("/api/fluidx3d/renders/60/secrets.mp4").status_code == 404


def test_render_without_the_build_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GASCFD_FLUIDX3D", str(tmp_path / "missing"))
    client = TestClient(app)
    response = client.post("/api/fluidx3d/renders", json={"speed_mph": 60})
    assert response.status_code == 409
    assert "build-gascfd.ps1" in response.json()["detail"]
    assert client.post("/api/fluidx3d/renders", json={"speed_mph": 55}).status_code == 422
