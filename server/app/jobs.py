import json
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.catalog import experiment_by_id, geometry_report, wheelbase_m
from app.openfoam_case import write_case
from app.paths import MPH_TO_MPS, geometry_file, runs_dir
from app.recipe import solver_image
from app.results import parse_case

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, object]] = {}


def result_key(experiment_id: str, speed_mph: float, yaw_deg: float, recipe: str) -> str:
    return f"{experiment_id}|{int(speed_mph)}|{int(yaw_deg)}|{recipe}"


def load_results() -> dict[str, dict[str, object]]:
    path = runs_dir() / "results.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload


def save_result(result: dict[str, object]) -> None:
    path = runs_dir() / "results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        current = {}
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
        key = result_key(
            str(result["experiment_id"]),
            float(result["speed_mph"]),
            float(result["yaw_deg"]),
            str(result["recipe"]),
        )
        current[key] = result
        path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


def get_job(job_id: str) -> dict[str, object] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job is not None else None


def active_job() -> dict[str, object] | None:
    with _LOCK:
        for job in _JOBS.values():
            if job.get("status") == "running":
                return dict(job)
    return None


def start_run(experiment_id: str, speed_mph: float, yaw_deg: float) -> dict[str, object]:
    existing = active_job()
    if existing is not None:
        return existing
    experiment = experiment_by_id(experiment_id)
    if experiment is None:
        raise KeyError(experiment_id)
    report = geometry_report(experiment)
    if not report.runnable or report.projected_area_m2 is None or report.sha256 is None:
        raise FileNotFoundError(report.message)
    relative = experiment["geometry"]
    if not isinstance(relative, str):
        raise FileNotFoundError("Experiment geometry path is missing.")
    stl_path = geometry_file(relative)
    job_id = uuid.uuid4().hex[:12]
    case_dir = runs_dir() / job_id
    job: dict[str, object] = {
        "id": job_id,
        "experiment_id": experiment_id,
        "speed_mph": speed_mph,
        "yaw_deg": yaw_deg,
        "status": "running",
        "stage": "writing-case",
        "message": "Writing the OpenFOAM case.",
        "log_tail": [],
        "case_dir": str(case_dir),
    }
    with _LOCK:
        _JOBS[job_id] = job
    try:
        meta = write_case(
            case_dir,
            stl_path,
            experiment_id=experiment_id,
            speed_m_s=speed_mph * MPH_TO_MPS,
            speed_mph=speed_mph,
            yaw_deg=yaw_deg,
            aref_m2=float(report.projected_area_m2),
            wheelbase_m=wheelbase_m(),
            geometry_sha256=str(report.sha256),
            geometry_signed_off=report.signed_off,
        )
    except OSError as exc:
        _fail(job_id, f"Could not write the OpenFOAM case: {exc}")
        return _must(job_id)
    _update(job_id, stage="case-ready", message=f"Case written ({meta['background_cells']} background cells).")
    if os.environ.get("GASCFD_SOLVER") == "off":
        _fail(job_id, "Case written. Solver execution is off, so there are no forces.")
        return _must(job_id)
    if shutil.which("docker") is None:
        _fail(job_id, "Docker is not on PATH. The case is on disk, and no forces were calculated.")
        return _must(job_id)
    image = solver_image()
    if not _image_present(image):
        _fail(
            job_id,
            f"OpenFOAM image {image} is not present. "
            f"Pull it with: docker pull {image}. The case is on disk, and no forces were calculated.",
        )
        return _must(job_id)
    thread = threading.Thread(target=_run_docker, args=(job_id, case_dir, image), daemon=True)
    thread.start()
    return _must(job_id)


def docker_ready() -> dict[str, object]:
    image = solver_image()
    available = shutil.which("docker") is not None
    return {
        "docker": available,
        "image": image,
        "image_present": _image_present(image) if available else False,
    }


def _run_docker(job_id: str, case_dir: Path, image: str) -> None:
    source = str(case_dir.resolve()).replace("\\", "/")
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{source}:/case",
        "-w",
        "/case",
        image,
        "bash",
        "/case/run.sh",
    ]
    log_path = case_dir / "log.txt"
    _update(job_id, stage="starting", message="Starting OpenFOAM in Docker.")
    try:
        with log_path.open("w", encoding="utf-8", newline="\n") as log:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                _append_log(job_id, line.rstrip())
                if line.startswith("STAGE "):
                    _update(job_id, stage=line.removeprefix("STAGE ").strip())
            code = process.wait()
    except OSError as exc:
        _fail(job_id, f"Could not start Docker: {exc}")
        return
    if code != 0:
        _fail(job_id, f"OpenFOAM exited with status {code}. See the case log.")
        return
    try:
        result = parse_case(case_dir)
    except ValueError as exc:
        _fail(job_id, str(exc))
        return
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_result(result)
    signed = "Geometry is not signed off as a Matrix." if not result["geometry_signed_off"] else "Geometry is signed off."
    _update(
        job_id,
        status="done",
        stage="done",
        message=f"Force samples read from OpenFOAM. {signed}",
    )


def _image_present(image: str) -> bool:
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _append_log(job_id: str, line: str) -> None:
    with _LOCK:
        job = _JOBS[job_id]
        tail = job["log_tail"]
        if isinstance(tail, list):
            tail.append(line)
            if len(tail) > 40:
                del tail[:-40]


def _update(job_id: str, **fields: object) -> None:
    with _LOCK:
        _JOBS[job_id].update(fields)


def _fail(job_id: str, message: str) -> None:
    _update(job_id, status="error", stage="error", message=message)


def _must(job_id: str) -> dict[str, object]:
    job = get_job(job_id)
    if job is None:
        raise RuntimeError("Job disappeared.")
    return job
