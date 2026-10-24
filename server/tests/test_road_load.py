import pytest

from app.catalog import load_vehicle
from app.paths import LB_TO_KG
from app.road_load import RoadLoadAssumptions, aero_power_w, estimate_mpg, worksheet


def test_brochure_mass_is_the_us_curb_weight():
    vehicle = load_vehicle()
    assert vehicle["mass_kg"] == pytest.approx(2679 * LB_TO_KG, abs=0.01)
    assert vehicle["published_cd"] == 0.32


def test_aero_power_is_drag_times_speed():
    assert aero_power_w(200, 26.8224) == pytest.approx(5364.48)


def test_mpg_uses_only_the_supplied_drag_and_assumptions():
    assumptions = RoadLoadAssumptions(
        crr=0.01,
        drivetrain_efficiency=0.5,
        engine_efficiency=0.5,
        accessory_power_w=0,
        fuel_lhv_j_per_kg=40e6,
        fuel_density_kg_per_l=0.8,
    )
    mpg = estimate_mpg(100, 10, 1000, assumptions)
    rolling = 0.01 * 1000 * 9.80665
    wheel = (100 + rolling) * 10
    crank = wheel / 0.5
    fuel_w = crank / 0.5
    litres_per_hour = (fuel_w / 40e6) / 0.8 * 3600
    gallons_per_hour = litres_per_hour / 3.785411784
    expected = (10 / 0.44704) / gallons_per_hour
    assert mpg == pytest.approx(expected, rel=1e-9)


def test_published_cd_is_not_an_input():
    with pytest.raises(TypeError):
        estimate_mpg(speed_m_s=10, mass_kg=1000)  # type: ignore[call-arg]


def test_worksheet_matches_estimate_mpg():
    sheet = worksheet(100, 10, 1000, RoadLoadAssumptions(crr=0.01, drivetrain_efficiency=0.5, engine_efficiency=0.5, accessory_power_w=0, fuel_lhv_j_per_kg=40e6, fuel_density_kg_per_l=0.8))
    assert sheet["mpg"] == pytest.approx(estimate_mpg(100, 10, 1000, RoadLoadAssumptions(crr=0.01, drivetrain_efficiency=0.5, engine_efficiency=0.5, accessory_power_w=0, fuel_lhv_j_per_kg=40e6, fuel_density_kg_per_l=0.8)))
    assert sheet["aero_power_w"] == 1000
