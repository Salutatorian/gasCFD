from dataclasses import dataclass

from app.paths import MPH_TO_MPS
from app.recipe import RHO

G = 9.80665
L_PER_GAL = 3.785411784


@dataclass(frozen=True)
class RoadLoadAssumptions:
    """Highway cruise inputs that are not CFD outputs.

    None of these were measured on a Matrix. They stay visible beside any MPG
    number so the fuel section cannot be mistaken for a solver result.
    """

    crr: float = 0.012
    drivetrain_efficiency: float = 0.90
    engine_efficiency: float = 0.25
    accessory_power_w: float = 400.0
    fuel_lhv_j_per_kg: float = 43.4e6
    fuel_density_kg_per_l: float = 0.745

    def describe(self) -> list[dict[str, object]]:
        return [
            {
                "id": "crr",
                "value": self.crr,
                "label": "Rolling-resistance coefficient. Assumed, not a Matrix coast-down.",
            },
            {
                "id": "drivetrain_efficiency",
                "value": self.drivetrain_efficiency,
                "label": "Drivetrain efficiency, wheel power to crankshaft. Assumed for a manual transaxle.",
            },
            {
                "id": "engine_efficiency",
                "value": self.engine_efficiency,
                "label": "Brake thermal efficiency at cruise. Assumed, not an engine map.",
            },
            {
                "id": "accessory_power_w",
                "value": self.accessory_power_w,
                "label": "Accessory load at the crankshaft, watts. Assumed.",
            },
            {
                "id": "fuel_lhv_j_per_kg",
                "value": self.fuel_lhv_j_per_kg,
                "label": "Gasoline lower heating value, J/kg. Assumed fuel, not a sample.",
            },
            {
                "id": "fuel_density_kg_per_l",
                "value": self.fuel_density_kg_per_l,
                "label": "Gasoline density, kg/L. Assumed fuel, not a sample.",
            },
        ]


def aero_power_w(drag_n: float, speed_m_s: float) -> float:
    return drag_n * speed_m_s


def drag_from_cd(cd: float, speed_m_s: float, area_m2: float, rho: float = RHO) -> float:
    return 0.5 * rho * speed_m_s * speed_m_s * cd * area_m2


def worksheet(
    drag_n: float | None,
    speed_m_s: float,
    mass_kg: float,
    assumptions: RoadLoadAssumptions | None = None,
    cd: float | None = None,
) -> dict[str, float | None]:
    """Every term in the highway-cruise model, or None where a solver number is missing."""
    model = assumptions or RoadLoadAssumptions()
    _require_model(model, speed_m_s)
    rolling = model.crr * mass_kg * G
    if drag_n is None:
        return {
            "cd": cd,
            "drag_n": None,
            "rolling_n": rolling,
            "aero_power_w": None,
            "wheel_power_w": None,
            "crank_power_w": None,
            "fuel_power_w": None,
            "mpg": None,
        }
    aero = aero_power_w(drag_n, speed_m_s)
    wheel_w = (drag_n + rolling) * speed_m_s
    crank_w = wheel_w / model.drivetrain_efficiency + model.accessory_power_w
    fuel_w = crank_w / model.engine_efficiency if crank_w > 0 else None
    mpg = None
    if fuel_w is not None and fuel_w > 0:
        litres_per_hour = (fuel_w / model.fuel_lhv_j_per_kg) / model.fuel_density_kg_per_l * 3600.0
        gallons_per_hour = litres_per_hour / L_PER_GAL
        if gallons_per_hour > 0:
            mpg = (speed_m_s / MPH_TO_MPS) / gallons_per_hour
    return {
        "cd": cd,
        "drag_n": drag_n,
        "rolling_n": rolling,
        "aero_power_w": aero,
        "wheel_power_w": wheel_w,
        "crank_power_w": crank_w,
        "fuel_power_w": fuel_w,
        "mpg": mpg,
    }


def estimate_mpg(
    drag_n: float,
    speed_m_s: float,
    mass_kg: float,
    assumptions: RoadLoadAssumptions | None = None,
) -> float | None:
    return worksheet(drag_n, speed_m_s, mass_kg, assumptions)["mpg"]


def _require_model(model: RoadLoadAssumptions, speed_m_s: float) -> None:
    if speed_m_s <= 0:
        raise ValueError("Speed must be positive.")
    if not 0 < model.drivetrain_efficiency <= 1:
        raise ValueError("Drivetrain efficiency must be between 0 and 1.")
    if not 0 < model.engine_efficiency <= 1:
        raise ValueError("Engine efficiency must be between 0 and 1.")
