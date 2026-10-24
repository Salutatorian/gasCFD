import json

from app.results import parse_case


def test_forces_override_coefficients(tmp_path):
    forces = tmp_path / "postProcessing" / "forces1" / "0"
    forces.mkdir(parents=True)
    lines = ["# Time forces"]
    for step in range(10):
        drag = 10 + step
        lines.append(
            f"{step} (({drag} 1 4) (0 0 1) (0 0 0)) ((0 0 0) (0 0 0) (0 0 0))"
        )
    (forces / "forces.dat").write_text("\n".join(lines) + "\n", encoding="utf-8")
    coeffs = tmp_path / "postProcessing" / "forceCoeffs1" / "0"
    coeffs.mkdir(parents=True)
    (coeffs / "coefficient.dat").write_text(
        "# Time Cd Cl\n0 0.1 0.2\n",
        encoding="utf-8",
    )
    (tmp_path / "gascfd.json").write_text(
        json.dumps(
            {
                "experiment_id": "001",
                "speed_mph": 60,
                "speed_m_s": 26.8224,
                "yaw_deg": 0,
                "recipe": "coarse-stationary-v1",
                "aref_m2": 2.0,
                "rho": 1.225,
                "geometry_sha256": "abc",
                "geometry_signed_off": False,
            }
        ),
        encoding="utf-8",
    )
    result = parse_case(tmp_path)
    assert result["source"] == "openfoam-forces"
    assert result["drag_n"] == (18 + 19) / 2
    assert result["lift_n"] == 5
    assert result["aero_power_w"] == result["drag_n"] * 26.8224
    assert result["cd"] != 0.1


def test_coefficients_are_used_when_forces_are_absent(tmp_path):
    coeffs = tmp_path / "postProcessing" / "forceCoeffs1" / "0"
    coeffs.mkdir(parents=True)
    rows = ["# Time Cd Cl"]
    for step in range(10):
        rows.append(f"{step} {0.30 + step * 0.01} {-0.10}")
    (coeffs / "coefficient.dat").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (tmp_path / "gascfd.json").write_text(
        json.dumps(
            {
                "experiment_id": "004",
                "speed_mph": 30,
                "speed_m_s": 13.4112,
                "yaw_deg": 0,
                "recipe": "coarse-stationary-v1",
                "aref_m2": 2.5,
                "rho": 1.225,
                "geometry_sha256": "def",
                "geometry_signed_off": False,
            }
        ),
        encoding="utf-8",
    )
    result = parse_case(tmp_path)
    assert result["source"] == "openfoam-forceCoeffs"
    assert result["cd"] == (0.38 + 0.39) / 2
    dynamic = 0.5 * 1.225 * 13.4112**2
    assert result["drag_n"] == result["cd"] * dynamic * 2.5
