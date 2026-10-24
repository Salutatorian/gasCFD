import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from app.catalog import experiment_by_id
from app.paths import ROOT, runs_dir, vehicle_dir

VIEWS = ("streamlines", "vortices", "velocity-slice", "side-streamlines", "top-streamlines")
SIM_SECONDS = 0.6
VRAM_MB = 2000  # 6 GB currently fails to allocate on this GPU; 2 GB still shows the covers
VIDEO_SECONDS = 5  # FluidX3D paces frames for 60 fps, so this is 300 frames per view
VIDEO_FPS = 30

_LOCK = threading.Lock()
_render: dict[str, object] | None = None
_live: subprocess.Popen[bytes] | None = None


def fluidx3d_dir() -> Path:
    override = os.environ.get("GASCFD_FLUIDX3D")
    if override:
        return Path(override)
    return ROOT / "fluidx3d"


def live_exe() -> Path:
    return fluidx3d_dir() / "bin" / "FluidX3D.exe"


def render_exe() -> Path:
    return fluidx3d_dir() / "bin-export" / "FluidX3D.exe"


def parts_dir(experiment_id: str = "001") -> Path:
    experiment = experiment_by_id(experiment_id)
    if experiment is None:
        raise FileNotFoundError(f"Unknown experiment {experiment_id}.")
    relative = experiment["geometry"]
    if not isinstance(relative, str):
        raise FileNotFoundError(f"Experiment {experiment_id} has no geometry path.")
    folder = vehicle_dir() / Path(relative).parent / "fluidx3d"
    if (folder / "body.stl").exists():
        return folder
    if experiment_id == "001":
        return vehicle_dir() / "stock" / "fluidx3d"
    raise FileNotFoundError(
        f"No FluidX3D parts for {experiment_id}. Stock uses stock/fluidx3d; wheel covers need wheel-covers/all/fluidx3d."
    )


def render_dir(speed_mph: int, experiment_id: str = "001") -> Path:
    if experiment_id == "001":
        return runs_dir() / "fluidx3d" / f"{speed_mph}mph"
    return runs_dir() / "fluidx3d" / experiment_id / f"{speed_mph}mph"


def status() -> dict[str, object]:
    with _LOCK:
        render = dict(_render) if _render is not None else None
        live_running = _live is not None and _live.poll() is None
    return {
        "live_ready": live_exe().exists(),
        "render_ready": render_exe().exists(),
        "parts_ready": (parts_dir("001") / "body.stl").exists(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "live_running": live_running,
        "render": render,
        "renders": _finished_renders(),
    }


def launch_live(speed_mph: int, experiment_id: str = "001") -> dict[str, object]:
    global _live
    _require(live_exe(), "The FluidX3D live build is missing. Run fluidx3d\\build-gascfd.ps1.")
    parts = parts_dir(experiment_id)
    _require(parts / "body.stl", "The FluidX3D parts are missing. Run server\\tools\\fluidx3d_parts.py.")
    with _LOCK:
        if _render is not None and _render.get("status") == "running":
            raise RuntimeError("A FluidX3D render is using the GPU. Open the live window after it finishes.")
        if _live is None or _live.poll() is not None:
            _live = subprocess.Popen(
                [str(live_exe()), str(parts), str(speed_mph)],
                cwd=live_exe().parent,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
    return status()


def start_render(speed_mph: int, experiment_id: str = "001") -> dict[str, object]:
    global _render
    _require(render_exe(), "The FluidX3D render build is missing. Run fluidx3d\\build-gascfd.ps1.")
    parts = parts_dir(experiment_id)
    _require(parts / "body.stl", "The FluidX3D parts are missing. Run server\\tools\\fluidx3d_parts.py.")
    if shutil.which("ffmpeg") is None:
        raise FileNotFoundError("ffmpeg is not on PATH, so the frames cannot become videos.")
    with _LOCK:
        if _render is not None and _render.get("status") == "running":
            return status()
        if _live is not None and _live.poll() is None:
            raise RuntimeError("The FluidX3D live window is using the GPU. Close it before rendering.")
        _render = {
            "speed_mph": speed_mph,
            "experiment_id": experiment_id,
            "status": "running",
            "message": f"Starting FluidX3D for {experiment_id}.",
        }
    threading.Thread(target=_run_render, args=(speed_mph, experiment_id), daemon=True).start()
    return status()


def encode_videos(folder: Path) -> list[str]:
    encoded = []
    for view in VIEWS:
        frames_dir = folder / view
        frames = sorted(frames_dir.glob("image-*.png"))
        if not frames:
            continue
        for index, frame in enumerate(frames):  # FluidX3D names frames by time step, ffmpeg wants a dense sequence
            frame.rename(frames_dir / f"frame-{index:05d}.png")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-framerate", str(VIDEO_FPS), "-i", str(frames_dir / "frame-%05d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart",
                str(folder / f"{view}.mp4"),
            ],
            check=True,
        )
        shutil.rmtree(frames_dir)
        encoded.append(view)
    return encoded


def _run_render(speed_mph: int, experiment_id: str = "001") -> None:
    out = render_dir(speed_mph, experiment_id)
    shutil.rmtree(out, ignore_errors=True)
    command = [
        str(render_exe()), str(parts_dir(experiment_id)), str(speed_mph), str(SIM_SECONDS), str(out), str(VRAM_MB), str(VIDEO_SECONDS),
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=render_exe().parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            text = line.strip(" |\r\n")
            if text:
                _update(message=text)
        code = process.wait()
    except OSError as exc:
        _update(status="error", message=f"Could not start FluidX3D: {exc}")
        return
    if code != 0 or not (out / "result.json").exists():
        _update(status="error", message=f"FluidX3D exited with status {code} and wrote no result.")
        return
    _update(message="Encoding the frames into videos.")
    try:
        encode_videos(out)
    except (OSError, subprocess.CalledProcessError) as exc:
        _update(status="error", message=f"ffmpeg failed: {exc}")
        return
    _update(status="done", message="FluidX3D render finished.")


def _finished_renders() -> list[dict[str, object]]:
    base = runs_dir() / "fluidx3d"
    if not base.exists():
        return []
    renders = []
    for folder in sorted(base.glob("*mph")):
        result_path = folder / "result.json"
        if not result_path.exists() or not folder.name[:-3].isdigit():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result.pop("cd_history", None)
        renders.append({
            "experiment_id": "001",
            "speed_mph": int(folder.name[:-3]),
            "videos": [view for view in VIEWS if (folder / f"{view}.mp4").exists()],
            "result": result,
        })
    for experiment_dir in sorted(path for path in base.iterdir() if path.is_dir() and not path.name.endswith("mph")):
        for folder in sorted(experiment_dir.glob("*mph")):
            result_path = folder / "result.json"
            if not result_path.exists() or not folder.name[:-3].isdigit():
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result.pop("cd_history", None)
            renders.append({
                "experiment_id": experiment_dir.name,
                "speed_mph": int(folder.name[:-3]),
                "videos": [view for view in VIEWS if (folder / f"{view}.mp4").exists()],
                "result": result,
            })
    return renders


def _require(path: Path, message: str) -> None:
    if not path.exists():
        raise FileNotFoundError(message)


def _update(**fields: object) -> None:
    with _LOCK:
        if _render is not None:
            _render.update(fields)
