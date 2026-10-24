import os

RECIPE_ID = "coarse-stationary-v1"
IMAGE = "opencfd/openfoam-run:2406"
BASE_CELL_M = 0.16
SURFACE_LEVEL = (3, 4)
WAKE_LEVEL = 2
MAX_GLOBAL_CELLS = 4_000_000
RHO = 1.225
NU = 1.5e-5
UPSTREAM_LENGTHS = 3.0
DOWNSTREAM_LENGTHS = 8.0
SIDE_WIDTHS = 2.0
ABOVE_HEIGHTS = 4.0
END_TIME = 400


def solver_image() -> str:
    return os.environ.get("GASCFD_OPENFOAM_IMAGE", IMAGE)


def surface_cell_m() -> float:
    return BASE_CELL_M / (2 ** SURFACE_LEVEL[1])


def limits() -> list[str]:
    millimetres = surface_cell_m() * 1000
    return [
        "Stationary ground. A moving belt is not modeled.",
        "Stationary wheels. Wheel rotation is not modeled.",
        "Cooling airflow through the radiator is not modeled.",
        "No prism boundary layer. Skin friction uses wall functions on a coarse mesh.",
        (
            f"Surface cells are about {millimetres:.0f} mm. "
            "A 3 mm skirt is not resolved."
        ),
        "Single-core steady RANS (simpleFoam, k-omega SST).",
        "The STL is not checked for a closed surface. snappyHexMesh needs one.",
        (
            "A matching bounding box does not make the file a Matrix. "
            "Drag from an unsigned geometry file is not a Matrix result."
        ),
    ]


def recipe_summary() -> dict[str, object]:
    return {
        "id": RECIPE_ID,
        "image": solver_image(),
        "solver": "simpleFoam",
        "turbulence": "kOmegaSST",
        "base_cell_m": BASE_CELL_M,
        "surface_level": list(SURFACE_LEVEL),
        "surface_cell_mm": round(surface_cell_m() * 1000, 2),
        "max_global_cells": MAX_GLOBAL_CELLS,
        "moving_ground": False,
        "rotating_wheels": False,
        "summary": (
            f"Coarse steady RANS. Stationary ground and wheels. "
            f"Surface cells about {surface_cell_m() * 1000:.0f} mm."
        ),
        "limits": limits(),
    }
