from app.catalog import experiment_by_id, geometry_report, load_vehicle
from app import fluidx3d
from app.paths import MPH_TO_MPS
from app.recipe import RECIPE_ID, RHO, limits
from app.road_load import G, RoadLoadAssumptions, drag_from_cd, estimate_mpg, worksheet

FUEL_NOTE = (
    "Miles per gallon are estimated from the OpenFOAM longitudinal drag "
    "plus the assumptions below. The brochure figure is not an input. "
    "OpenFOAM does not calculate fuel use."
)


def build_comparison(
    experiments: list[dict[str, object]],
    results: dict[str, dict[str, object]],
    baseline_id: str,
    variant_id: str,
    speed_mph: float,
    yaw_deg: float,
) -> dict[str, object]:
    by_id = {str(item["id"]): item for item in experiments}
    baseline = by_id[baseline_id]
    variant = by_id[variant_id]
    baseline_result = _match(results, baseline_id, speed_mph, yaw_deg)
    variant_result = _match(results, variant_id, speed_mph, yaw_deg)
    vehicle = load_vehicle()
    assumptions = RoadLoadAssumptions()
    baseline_mpg = _mpg(baseline_result, assumptions, float(vehicle["mass_kg"]))
    variant_mpg = _mpg(variant_result, assumptions, float(vehicle["mass_kg"]))
    return {
        "speed_mph": speed_mph,
        "yaw_deg": yaw_deg,
        "recipe": RECIPE_ID,
        "baseline": _column(baseline, baseline_result, speed_mph, yaw_deg),
        "variant": _column(variant, variant_result, speed_mph, yaw_deg),
        "change": {
            "cd_percent": _percent(_value(baseline_result, "cd"), _value(variant_result, "cd")),
            "drag_n": _difference(_value(baseline_result, "drag_n"), _value(variant_result, "drag_n")),
            "lift_n": _difference(_value(baseline_result, "lift_n"), _value(variant_result, "lift_n")),
            "side_n": _difference(_value(baseline_result, "side_n"), _value(variant_result, "side_n")),
            "aero_power_w": _difference(
                _value(baseline_result, "aero_power_w"),
                _value(variant_result, "aero_power_w"),
            ),
            "mpg": _difference(baseline_mpg, variant_mpg),
            "mpg_percent": _percent(baseline_mpg, variant_mpg),
        },
        "fuel": {
            "baseline_mpg": baseline_mpg,
            "variant_mpg": variant_mpg,
            "assumptions": assumptions.describe(),
            "mass_kg": vehicle["mass_kg"],
            "mass_source": vehicle["curb_weight_source"],
            "uses_cfd_drag": True,
            "uses_published_cd": False,
            "brochure_highway_mpg": vehicle["brochure_highway_mpg"],
            "brochure_mpg_source": vehicle["brochure_mpg_source"],
            "note": FUEL_NOTE,
        },
        "published_cd": {
            "value": vehicle["published_cd"],
            "source": vehicle["published_cd_source"],
            "used_in_results": False,
        },
        "limits": limits(),
    }


def build_live_math(
    experiments: list[dict[str, object]],
    results: dict[str, dict[str, object]],
    baseline_id: str,
    variant_id: str,
    speed_mph: float,
    yaw_deg: float,
) -> dict[str, object]:
    vehicle = load_vehicle()
    assumptions = RoadLoadAssumptions()
    speed_m_s = speed_mph * MPH_TO_MPS
    mass_kg = float(vehicle["mass_kg"])
    area_m2, area_source = _frontal_area()
    published_cd = float(vehicle["published_cd"])
    published_drag = drag_from_cd(published_cd, speed_m_s, area_m2) if area_m2 is not None else None
    columns = [
        _math_column(
            "published-stock",
            "Stock · Toyota Cd*",
            "published",
            worksheet(published_drag, speed_m_s, mass_kg, assumptions, published_cd),
            cd_label=str(vehicle["published_cd_source"]),
            used_for_fuel=False,
            missing=None if area_m2 is not None else "Need the stock STL frontal area.",
        )
    ]
    for experiment in experiments:
        columns.append(_openfoam_column(experiment, results, speed_mph, yaw_deg, speed_m_s, mass_kg, assumptions))
    columns.extend(_fluidx3d_columns(experiments, speed_mph, speed_m_s, mass_kg, assumptions))
    rolling = assumptions.crr * mass_kg * G
    return {
        "speed_mph": speed_mph,
        "speed_m_s": speed_m_s,
        "rho": RHO,
        "mass_kg": mass_kg,
        "area_m2": area_m2,
        "area_source": area_source,
        "rolling_n": rolling,
        "assumptions": assumptions.describe(),
        "columns": columns,
        "note": (
            "The starred Toyota Cd is a brochure reference. OpenFOAM MPG uses solved drag only. "
            "FluidX3D Cd is shown when a render exists and is not used for fuel."
        ),
    }


def _frontal_area() -> tuple[float | None, str]:
    stock = experiment_by_id("001")
    if stock is not None:
        report = geometry_report(stock)
        if report.projected_area_m2 is not None:
            return report.projected_area_m2, "Stock STL frontal silhouette."
    return None, "Frontal area is measured from the stock STL."


def _openfoam_column(
    experiment: dict[str, object],
    results: dict[str, dict[str, object]],
    speed_mph: float,
    yaw_deg: float,
    speed_m_s: float,
    mass_kg: float,
    assumptions: RoadLoadAssumptions,
) -> dict[str, object]:
    result = _match(results, str(experiment["id"]), speed_mph, yaw_deg)
    cd = _value(result, "cd")
    drag = _value(result, "drag_n")
    missing = None if drag is not None else "No OpenFOAM result at this speed and yaw."
    if result is None and not _has_geometry(experiment):
        missing = "No STL yet, so there is nothing to solve."
    return _math_column(
        f"openfoam-{experiment['id']}",
        f"{experiment['id']} {experiment['name']}",
        "openfoam",
        worksheet(drag, speed_m_s, mass_kg, assumptions, cd),
        cd_label="OpenFOAM body-axis Cd." if cd is not None else "Waiting on OpenFOAM.",
        used_for_fuel=drag is not None,
        missing=missing,
    )


def _has_geometry(experiment: dict[str, object]) -> bool:
    report = geometry_report(experiment)
    return report.present


def _fluidx3d_columns(
    experiments: list[dict[str, object]],
    speed_mph: float,
    speed_m_s: float,
    mass_kg: float,
    assumptions: RoadLoadAssumptions,
) -> list[dict[str, object]]:
    names = {str(item["id"]): str(item["name"]) for item in experiments}
    columns: list[dict[str, object]] = []
    for found in fluidx3d.status()["renders"]:
        if found.get("speed_mph") != int(speed_mph):
            continue
        result = found.get("result")
        if not isinstance(result, dict):
            continue
        cd = result.get("cd_mean_second_half")
        area = result.get("frontal_area_m2")
        if not isinstance(cd, (int, float)) or not isinstance(area, (int, float)):
            continue
        experiment_id = str(found.get("experiment_id") or "001")
        drag = drag_from_cd(float(cd), speed_m_s, float(area))
        sheet = worksheet(drag, speed_m_s, mass_kg, assumptions, float(cd))
        sheet["mpg"] = None
        blockage = result.get("blockage_ratio")
        block_text = f"{100 * float(blockage):.0f}%" if isinstance(blockage, (int, float)) else "unknown"
        columns.append(
            _math_column(
                f"fluidx3d-{experiment_id}",
                f"{experiment_id} {names.get(experiment_id, experiment_id)} · FluidX3D",
                "fluidx3d",
                sheet,
                cd_label=f"Unvalidated. The car blocks {block_text} of the box. Not used for fuel.",
                used_for_fuel=False,
                missing=None,
            )
        )
    return columns


def _math_column(
    column_id: str,
    name: str,
    kind: str,
    sheet: dict[str, float | None],
    cd_label: str,
    used_for_fuel: bool,
    missing: str | None,
) -> dict[str, object]:
    return {
        "id": column_id,
        "name": name,
        "kind": kind,
        "cd_label": cd_label,
        "used_for_fuel": used_for_fuel,
        "missing": missing,
        **sheet,
    }


def _match(
    results: dict[str, dict[str, object]],
    experiment_id: str,
    speed_mph: float,
    yaw_deg: float,
) -> dict[str, object] | None:
    key = f"{experiment_id}|{int(speed_mph)}|{int(yaw_deg)}|{RECIPE_ID}"
    found = results.get(key)
    if found is None:
        return None
    if found.get("recipe") != RECIPE_ID:
        return None
    return found


def _column(
    experiment: dict[str, object],
    result: dict[str, object] | None,
    speed_mph: float,
    yaw_deg: float,
) -> dict[str, object]:
    column: dict[str, object] = {
        "id": experiment["id"],
        "name": experiment["name"],
        "speed_mph": speed_mph,
        "yaw_deg": yaw_deg,
        "cd": None,
        "cl": None,
        "drag_n": None,
        "lift_n": None,
        "side_n": None,
        "aero_power_w": None,
        "aref_m2": None,
        "geometry_signed_off": False,
        "mesh_hit_cell_cap": False,
        "source": None,
    }
    if result is None:
        return column
    for key in ("cd", "cl", "drag_n", "lift_n", "side_n", "aero_power_w", "aref_m2", "source"):
        column[key] = result.get(key)
    column["geometry_signed_off"] = bool(result.get("geometry_signed_off"))
    column["mesh_hit_cell_cap"] = bool(result.get("mesh_hit_cell_cap"))
    return column


def _value(result: dict[str, object] | None, key: str) -> float | None:
    if result is None or result.get(key) is None:
        return None
    return float(result[key])


def _difference(baseline: float | None, variant: float | None) -> float | None:
    if baseline is None or variant is None:
        return None
    return variant - baseline


def _percent(baseline: float | None, variant: float | None) -> float | None:
    if baseline is None or variant is None or baseline == 0:
        return None
    return (variant - baseline) / baseline * 100.0


def _mpg(
    result: dict[str, object] | None,
    assumptions: RoadLoadAssumptions,
    mass_kg: float,
) -> float | None:
    drag = _value(result, "drag_n")
    if drag is None or result is None:
        return None
    if result.get("speed_m_s") is not None:
        speed_m_s = float(result["speed_m_s"])
    elif result.get("speed_mph") is not None:
        speed_m_s = float(result["speed_mph"]) * MPH_TO_MPS
    else:
        return None
    return estimate_mpg(drag, speed_m_s, mass_kg, assumptions)
