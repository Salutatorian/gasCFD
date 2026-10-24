import json

from app.geometry import Envelope, GeometryReport, inspect_path, missing_report
from app.paths import LB_TO_KG, geometry_file, vehicle_dir


def load_vehicle() -> dict[str, object]:
    payload = json.loads((vehicle_dir() / "vehicle.json").read_text(encoding="utf-8"))
    payload["mass_kg"] = float(payload["curb_weight_lb"]) * LB_TO_KG
    return payload


def load_experiments() -> list[dict[str, object]]:
    return json.loads((vehicle_dir() / "experiments.json").read_text(encoding="utf-8"))


def envelope() -> Envelope:
    vehicle = load_vehicle()
    dimensions = vehicle["dimensions_m"]
    tolerances = vehicle["tolerances_m"]
    if not isinstance(dimensions, dict) or not isinstance(tolerances, dict):
        raise ValueError("Vehicle dimensions are missing.")
    return Envelope(
        length=float(dimensions["length"]),
        width=float(dimensions["width"]),
        height=float(dimensions["height"]),
        length_tol=float(tolerances["length"]),
        width_tol=float(tolerances["width"]),
        height_tol=float(tolerances["height"]),
    )


def wheelbase_m() -> float:
    vehicle = load_vehicle()
    dimensions = vehicle["dimensions_m"]
    if not isinstance(dimensions, dict):
        raise ValueError("Vehicle dimensions are missing.")
    return float(dimensions["wheelbase"])


def experiment_by_id(experiment_id: str) -> dict[str, object] | None:
    for experiment in load_experiments():
        if experiment["id"] == experiment_id:
            return experiment
    return None


def geometry_report(experiment: dict[str, object]) -> GeometryReport:
    relative = experiment["geometry"]
    if not isinstance(relative, str):
        return missing_report()
    try:
        path = geometry_file(relative)
    except ValueError:
        report = missing_report()
        report.message = "Geometry path escapes the vehicle directory."
        return report
    return inspect_path(path, envelope())
