from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from app.catalog import (
    envelope,
    experiment_by_id,
    geometry_report,
    load_experiments,
    load_vehicle,
)
from app import fluidx3d, wind
from app.compare import build_comparison, build_live_math
from app.geometry import inspect_bytes
from app.jobs import active_job, docker_ready, get_job, load_results, start_run
from app.paths import geometry_file
from app.recipe import recipe_summary

app = FastAPI(title="gasCFD")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_STL_BYTES = 200_000_000


class RunRequest(BaseModel):
    speed_mph: float
    yaw_deg: float


class FlowRequest(BaseModel):
    speed_mph: float
    experiment_id: str = "001"


class WindRequest(BaseModel):
    speed_mph: float
    front: bool = False
    rear: bool = False


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "gasCFD", "ui": "http://127.0.0.1:3000", "api": "/api/health"}


@app.get("/api/health")
def health() -> dict[str, object]:
    ready = docker_ready()
    return {"mesh_recipe": recipe_summary(), **ready}


@app.get("/api/vehicle")
def vehicle() -> dict[str, object]:
    return load_vehicle()


@app.get("/api/experiments")
def experiments() -> list[dict[str, object]]:
    return [_public_experiment(item) for item in load_experiments()]


@app.get("/api/comparison")
def comparison(
    baseline: str = "001",
    variant: str = "004",
    speed_mph: float = 60,
    yaw_deg: float = 0,
) -> dict[str, object]:
    spec = load_vehicle()
    speed = _canonical(speed_mph, spec["speeds_mph"], "Speed")
    yaw = _canonical(yaw_deg, spec["yaw_deg"], "Yaw")
    items = load_experiments()
    ids = {str(item["id"]) for item in items}
    if baseline not in ids or variant not in ids:
        raise HTTPException(status_code=404, detail="Unknown experiment.")
    return build_comparison(items, load_results(), baseline, variant, speed, yaw)


@app.get("/api/math")
def live_math(
    baseline: str = "001",
    variant: str = "003",
    speed_mph: float = 60,
    yaw_deg: float = 0,
) -> dict[str, object]:
    spec = load_vehicle()
    speed = _canonical(speed_mph, spec["speeds_mph"], "Speed")
    yaw = _canonical(yaw_deg, spec["yaw_deg"], "Yaw")
    items = load_experiments()
    ids = {str(item["id"]) for item in items}
    if baseline not in ids or variant not in ids:
        raise HTTPException(status_code=404, detail="Unknown experiment.")
    return build_live_math(items, load_results(), baseline, variant, speed, yaw)


@app.post("/api/experiments/{experiment_id}/geometry")
async def upload_geometry(experiment_id: str, file: UploadFile) -> dict[str, object]:
    experiment = _require_experiment(experiment_id)
    data = await file.read(MAX_STL_BYTES + 1)
    if len(data) > MAX_STL_BYTES:
        raise HTTPException(status_code=413, detail="STL is larger than 200 MB.")
    name = file.filename or ""
    if name and not name.lower().endswith(".stl"):
        raise HTTPException(status_code=422, detail="Only STL is accepted in this version.")
    relative = experiment["geometry"]
    if not isinstance(relative, str):
        raise HTTPException(status_code=500, detail="Experiment geometry path is missing.")
    try:
        path = geometry_file(relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Geometry path is invalid.") from exc
    report = inspect_bytes(data, envelope(), signed_off=False)
    if not report.runnable:
        raise HTTPException(status_code=422, detail=report.to_dict())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return geometry_report(experiment).to_dict()


@app.get("/api/experiments/{experiment_id}/geometry.stl")
def download_geometry(experiment_id: str) -> FileResponse:
    experiment = _require_experiment(experiment_id)
    relative = experiment["geometry"]
    if not isinstance(relative, str):
        raise HTTPException(status_code=404, detail="No geometry.stl for this experiment.")
    try:
        path = geometry_file(relative)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Geometry path is invalid.") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="No geometry.stl for this experiment.")
    return FileResponse(path, media_type="model/stl", filename="geometry.stl")


@app.post("/api/experiments/{experiment_id}/runs", status_code=202)
def run_experiment(experiment_id: str, body: RunRequest) -> dict[str, object]:
    _require_experiment(experiment_id)
    spec = load_vehicle()
    speed = _canonical(body.speed_mph, spec["speeds_mph"], "Speed")
    yaw = _canonical(body.yaw_deg, spec["yaw_deg"], "Yaw")
    try:
        return start_run(experiment_id, speed, yaw)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/jobs/active")
def job_active() -> dict[str, object]:
    return {"job": active_job()}


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict[str, object]:
    found = get_job(job_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return found


@app.post("/api/wind", status_code=202)
def wind_start(body: WindRequest) -> dict[str, object]:
    speed = _canonical(body.speed_mph, load_vehicle()["speeds_mph"], "Speed")
    try:
        state = wind.start(speed, body.front, body.rear)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**state, "result": wind.result_for(speed, body.front, body.rear)}


@app.get("/api/wind")
def wind_state(speed_mph: float = 40, front: bool = False, rear: bool = False) -> dict[str, object]:
    speed = _canonical(speed_mph, load_vehicle()["speeds_mph"], "Speed")
    return {**wind.status(), "result": wind.result_for(speed, front, rear)}


@app.get("/api/wind/boxes.stl")
def wind_boxes(front: bool = False, rear: bool = False) -> Response:
    try:
        data = wind.box_bytes(front, rear)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=data, media_type="model/stl")


def _wind_file(path: Path, missing: str) -> FileResponse:
    if not path.exists():
        raise HTTPException(status_code=404, detail=missing)
    return FileResponse(path, media_type="application/octet-stream")


@app.get("/api/wind/streamlines.bin")
def wind_lines(speed_mph: float = 40, front: bool = False, rear: bool = False) -> FileResponse:
    speed = _canonical(speed_mph, load_vehicle()["speeds_mph"], "Speed")
    return _wind_file(wind.lines_path(speed, front, rear), "The air for this shape is not ready.")


@app.get("/api/wind/vortices.bin")
def wind_vortices(speed_mph: float = 40, front: bool = False, rear: bool = False) -> FileResponse:
    speed = _canonical(speed_mph, load_vehicle()["speeds_mph"], "Speed")
    return _wind_file(wind.vortex_path(speed, front, rear), "The vortices for this shape are not ready.")


@app.get("/api/wind/slice.bin")
def wind_slice(speed_mph: float = 40, front: bool = False, rear: bool = False) -> FileResponse:
    speed = _canonical(speed_mph, load_vehicle()["speeds_mph"], "Speed")
    return _wind_file(wind.slice_path(speed, front, rear), "The speed slice for this shape is not ready.")


@app.get("/api/fluidx3d")
def fluidx3d_status() -> dict[str, object]:
    return fluidx3d.status()


@app.post("/api/fluidx3d/live", status_code=202)
def fluidx3d_live(body: FlowRequest) -> dict[str, object]:
    speed = _canonical(body.speed_mph, load_vehicle()["speeds_mph"], "Speed")
    _require_experiment(body.experiment_id)
    try:
        return fluidx3d.launch_live(speed, body.experiment_id)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/fluidx3d/renders", status_code=202)
def fluidx3d_render(body: FlowRequest) -> dict[str, object]:
    speed = _canonical(body.speed_mph, load_vehicle()["speeds_mph"], "Speed")
    _require_experiment(body.experiment_id)
    try:
        return fluidx3d.start_render(speed, body.experiment_id)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/fluidx3d/renders/{speed_mph}/{view}.mp4")
def fluidx3d_video(speed_mph: int, view: str) -> FileResponse:
    if view not in fluidx3d.VIEWS:
        raise HTTPException(status_code=404, detail="Unknown FluidX3D view.")
    path = fluidx3d.render_dir(speed_mph, "001") / f"{view}.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="That view has not been rendered at this speed.")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/fluidx3d/renders/{experiment_id}/{speed_mph}/streamlines.bin")
def fluidx3d_streamlines(experiment_id: str, speed_mph: int) -> FileResponse:
    _require_experiment(experiment_id)
    path = fluidx3d.render_dir(speed_mph, experiment_id) / "streamlines.bin"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No orbitable air at this speed. Render it first.")
    return FileResponse(path, media_type="application/octet-stream")


@app.get("/api/fluidx3d/renders/{experiment_id}/{speed_mph}/{view}.mp4")
def fluidx3d_experiment_video(experiment_id: str, speed_mph: int, view: str) -> FileResponse:
    _require_experiment(experiment_id)
    if view not in fluidx3d.VIEWS:
        raise HTTPException(status_code=404, detail="Unknown FluidX3D view.")
    path = fluidx3d.render_dir(speed_mph, experiment_id) / f"{view}.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="That view has not been rendered at this speed.")
    return FileResponse(path, media_type="video/mp4")


def _require_experiment(experiment_id: str) -> dict[str, object]:
    experiment = experiment_by_id(experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="Unknown experiment.")
    return experiment


def _public_experiment(experiment: dict[str, object]) -> dict[str, object]:
    return {
        "id": experiment["id"],
        "name": experiment["name"],
        "summary": experiment["summary"],
        "intent": experiment["intent"],
        "geometry": experiment["geometry"],
        "geometry_report": geometry_report(experiment).to_dict(),
    }


def _canonical(value: float, allowed: object, label: str) -> int:
    if not isinstance(allowed, list):
        raise HTTPException(status_code=500, detail=f"{label} options are missing.")
    for item in allowed:
        if float(item) == float(value):
            return int(item)
    raise HTTPException(status_code=422, detail=f"{label} must be one of {allowed}.")
