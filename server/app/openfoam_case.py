import json
import math
import shutil
from pathlib import Path

from app.geometry import bounds, read_triangles
from app.recipe import (
    ABOVE_HEIGHTS,
    BASE_CELL_M,
    DOWNSTREAM_LENGTHS,
    END_TIME,
    MAX_GLOBAL_CELLS,
    NU,
    RECIPE_ID,
    RHO,
    SIDE_WIDTHS,
    SURFACE_LEVEL,
    UPSTREAM_LENGTHS,
    WAKE_LEVEL,
)


def write_case(
    dest: Path,
    stl_path: Path,
    *,
    experiment_id: str,
    speed_m_s: float,
    speed_mph: float,
    yaw_deg: float,
    aref_m2: float,
    wheelbase_m: float,
    geometry_sha256: str,
    geometry_signed_off: bool,
) -> dict[str, object]:
    if dest.exists():
        shutil.rmtree(dest)
    triangles = read_triangles(stl_path.read_bytes())
    low, high = bounds(triangles)
    length = high[0] - low[0]
    width = high[1] - low[1]
    height = high[2] - low[2]
    x0 = low[0] - UPSTREAM_LENGTHS * length
    x1 = high[0] + DOWNSTREAM_LENGTHS * length
    y0 = low[1] - SIDE_WIDTHS * width
    y1 = high[1] + SIDE_WIDTHS * width
    z0 = low[2]
    z1 = high[2] + ABOVE_HEIGHTS * height
    nx = _cells(x1 - x0)
    ny = _cells(y1 - y0)
    nz = _cells(z1 - z0)
    location = (low[0] - 0.5 * length, (low[1] + high[1]) / 2.0, low[2] + 0.5 * height)
    cof_r = ((low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0, (low[2] + high[2]) / 2.0)
    velocity = _freestream(speed_m_s, yaw_deg)
    k, omega, nut = _inlet_turbulence(speed_m_s, length)
    wake_min = (high[0], low[1] - 0.2 * width, low[2])
    wake_max = (high[0] + 2.0 * length, high[1] + 0.2 * width, low[2] + 1.2 * height)

    (dest / "0").mkdir(parents=True)
    (dest / "constant" / "triSurface").mkdir(parents=True)
    (dest / "system").mkdir(parents=True)
    shutil.copyfile(stl_path, dest / "constant" / "triSurface" / "vehicle.stl")

    meta = {
        "recipe": RECIPE_ID,
        "experiment_id": experiment_id,
        "speed_mph": speed_mph,
        "speed_m_s": speed_m_s,
        "yaw_deg": yaw_deg,
        "aref_m2": aref_m2,
        "rho": RHO,
        "lref_m": wheelbase_m,
        "geometry_sha256": geometry_sha256,
        "geometry_signed_off": geometry_signed_off,
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "background_cells": nx * ny * nz,
        "location_in_mesh": list(location),
        "moving_ground": False,
        "rotating_wheels": False,
    }
    _write(dest / "gascfd.json", json.dumps(meta, indent=2) + "\n")
    _write(dest / "run.sh", _run_script())
    _write(dest / "system" / "blockMeshDict", _block_mesh(x0, y0, z0, x1, y1, z1, nx, ny, nz))
    _write(dest / "system" / "surfaceFeatureExtractDict", _features())
    _write(
        dest / "system" / "snappyHexMeshDict",
        _snappy(location, wake_min, wake_max),
    )
    _write(
        dest / "system" / "controlDict",
        _control(cof_r, aref_m2, wheelbase_m, speed_m_s),
    )
    _write(dest / "system" / "fvSchemes", _fv_schemes())
    _write(dest / "system" / "fvSolution", _fv_solution())
    _write(dest / "constant" / "transportProperties", _transport())
    _write(dest / "constant" / "turbulenceProperties", _turbulence())
    _write(dest / "0" / "U", _u_field(velocity))
    _write(dest / "0" / "p", _scalar_field("p", "[0 2 -2 0 0 0 0]", 0.0, _pressure_boundaries()))
    _write(dest / "0" / "k", _scalar_field("k", "[0 2 -2 0 0 0 0]", k, _turb_boundaries(k, "kqRWallFunction")))
    _write(
        dest / "0" / "omega",
        _scalar_field("omega", "[0 0 -1 0 0 0 0]", omega, _turb_boundaries(omega, "omegaWallFunction")),
    )
    _write(dest / "0" / "nut", _scalar_field("nut", "[0 2 -1 0 0 0 0]", nut, _nut_boundaries(nut)))
    return meta


def _freestream(speed_m_s: float, yaw_deg: float) -> tuple[float, float, float]:
    yaw = math.radians(yaw_deg)
    return (speed_m_s * math.cos(yaw), speed_m_s * math.sin(yaw), 0.0)


def _inlet_turbulence(speed_m_s: float, length: float) -> tuple[float, float, float]:
    k = 1.5 * (0.01 * speed_m_s) ** 2
    length_scale = max(0.07 * length, 1e-3)
    omega = math.sqrt(k) / ((0.09 ** 0.25) * length_scale)
    return k, omega, k / omega


def _cells(span: float) -> int:
    return max(8, int(round(span / BASE_CELL_M)))


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _run_script() -> str:
    return "\n".join(
        [
            "#!/bin/bash",
            "set -eu",
            "cd /case",
            "echo STAGE blockMesh",
            "blockMesh",
            "echo STAGE surfaceFeatureExtract",
            "surfaceFeatureExtract",
            "echo STAGE snappyHexMesh",
            "snappyHexMesh -overwrite",
            "echo STAGE checkMesh",
            "checkMesh || true",
            "echo STAGE simpleFoam",
            "simpleFoam",
            "echo STAGE done",
            "",
        ]
    )


def _header(object_name: str, class_name: str = "dictionary") -> str:
    return (
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        "    class       " + class_name + ";\n"
        "    object      " + object_name + ";\n"
        "}\n"
    )


def _block_mesh(
    x0: float,
    y0: float,
    z0: float,
    x1: float,
    y1: float,
    z1: float,
    nx: int,
    ny: int,
    nz: int,
) -> str:
    return (
        _header("blockMeshDict")
        + "convertToMeters 1;\n"
        + "vertices\n(\n"
        + f"    ({x0:.8g} {y0:.8g} {z0:.8g})\n"
        + f"    ({x1:.8g} {y0:.8g} {z0:.8g})\n"
        + f"    ({x1:.8g} {y1:.8g} {z0:.8g})\n"
        + f"    ({x0:.8g} {y1:.8g} {z0:.8g})\n"
        + f"    ({x0:.8g} {y0:.8g} {z1:.8g})\n"
        + f"    ({x1:.8g} {y0:.8g} {z1:.8g})\n"
        + f"    ({x1:.8g} {y1:.8g} {z1:.8g})\n"
        + f"    ({x0:.8g} {y1:.8g} {z1:.8g})\n"
        + ");\n"
        + "blocks\n(\n"
        + f"    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)\n"
        + ");\n"
        + "edges\n(\n);\n"
        + "boundary\n(\n"
        + "    inlet { type patch; faces ((0 4 7 3)); }\n"
        + "    outlet { type patch; faces ((1 2 6 5)); }\n"
        + "    ground { type wall; faces ((0 3 2 1)); }\n"
        + "    top { type patch; faces ((4 5 6 7)); }\n"
        + "    sides { type patch; faces ((0 1 5 4) (3 7 6 2)); }\n"
        + ");\n"
    )


def _features() -> str:
    return (
        _header("surfaceFeatureExtractDict")
        + "vehicle.stl\n"
        + "{\n"
        + "    extractionMethod    extractFromSurface;\n"
        + "    includedAngle       150;\n"
        + "}\n"
    )


def _snappy(
    location: tuple[float, float, float],
    wake_min: tuple[float, float, float],
    wake_max: tuple[float, float, float],
) -> str:
    loc = " ".join(f"{value:.8g}" for value in location)
    w0 = " ".join(f"{value:.8g}" for value in wake_min)
    w1 = " ".join(f"{value:.8g}" for value in wake_max)
    return (
        _header("snappyHexMeshDict")
        + "castellatedMesh true;\n"
        + "snap            true;\n"
        + "addLayers       false;\n"
        + "geometry\n"
        + "{\n"
        + "    vehicle.stl { type triSurfaceMesh; name vehicle; }\n"
        + "    wake { type searchableBox; min (" + w0 + "); max (" + w1 + "); }\n"
        + "}\n"
        + "castellatedMeshControls\n"
        + "{\n"
        + "    maxLocalCells  " + str(MAX_GLOBAL_CELLS) + ";\n"
        + "    maxGlobalCells " + str(MAX_GLOBAL_CELLS) + ";\n"
        + "    minRefinementCells 10;\n"
        + "    nCellsBetweenLevels 3;\n"
        + "    features\n"
        + "    (\n"
        + "        { file \"vehicle.eMesh\"; level " + str(SURFACE_LEVEL[1]) + "; }\n"
        + "    );\n"
        + "    refinementSurfaces { vehicle { level (" + str(SURFACE_LEVEL[0]) + " " + str(SURFACE_LEVEL[1]) + "); } }\n"
        + "    resolveFeatureAngle 30;\n"
        + "    refinementRegions { wake { mode inside; levels ((1e15 " + str(WAKE_LEVEL) + ")); } }\n"
        + "    locationInMesh (" + loc + ");\n"
        + "    allowFreeStandingZoneFaces true;\n"
        + "}\n"
        + "snapControls\n"
        + "{\n"
        + "    nSmoothPatch 3;\n"
        + "    tolerance 2.0;\n"
        + "    nSolveIter 30;\n"
        + "    nRelaxIter 5;\n"
        + "}\n"
        + "addLayersControls\n"
        + "{\n"
        + "    relativeSizes true;\n"
        + "    layers { }\n"
        + "    expansionRatio 1.2;\n"
        + "    finalLayerThickness 0.3;\n"
        + "    minThickness 0.1;\n"
        + "    nGrow 0;\n"
        + "    featureAngle 60;\n"
        + "    nRelaxIter 3;\n"
        + "    nSmoothSurfaceNormals 1;\n"
        + "    nSmoothNormals 3;\n"
        + "    nSmoothThickness 10;\n"
        + "    maxFaceThicknessRatio 0.5;\n"
        + "    maxThicknessToMedialRatio 0.3;\n"
        + "    minMedialAxisAngle 90;\n"
        + "    nBufferCellsNoExtrude 0;\n"
        + "    nLayerIter 50;\n"
        + "}\n"
        + "meshQualityControls\n"
        + "{\n"
        + "    maxNonOrtho 65;\n"
        + "    maxBoundarySkewness 20;\n"
        + "    maxInternalSkewness 4;\n"
        + "    maxConcave 80;\n"
        + "    minVol 1e-13;\n"
        + "    minTetQuality 1e-15;\n"
        + "    minArea -1;\n"
        + "    minTwist 0.02;\n"
        + "    minDeterminant 0.001;\n"
        + "    minFaceWeight 0.05;\n"
        + "    minVolRatio 0.01;\n"
        + "    minTriangleTwist -1;\n"
        + "    nSmoothScale 4;\n"
        + "    errorReduction 0.75;\n"
        + "}\n"
        + "mergeTolerance 1e-6;\n"
    )


def _control(
    cof_r: tuple[float, float, float],
    aref_m2: float,
    lref_m: float,
    speed_m_s: float,
) -> str:
    center = " ".join(f"{value:.8g}" for value in cof_r)
    return (
        _header("controlDict")
        + "application     simpleFoam;\n"
        + "startFrom       startTime;\n"
        + "startTime       0;\n"
        + "stopAt          endTime;\n"
        + "endTime         " + str(END_TIME) + ";\n"
        + "deltaT          1;\n"
        + "writeControl    timeStep;\n"
        + "writeInterval   100;\n"
        + "purgeWrite      2;\n"
        + "writeFormat     ascii;\n"
        + "writePrecision  8;\n"
        + "writeCompression off;\n"
        + "timeFormat      general;\n"
        + "timePrecision   6;\n"
        + "runTimeModifiable true;\n"
        + "functions\n"
        + "{\n"
        + "    forceCoeffs1\n"
        + "    {\n"
        + "        type            forceCoeffs;\n"
        + "        libs            (forces);\n"
        + "        writeControl    timeStep;\n"
        + "        writeInterval   1;\n"
        + "        patches         (vehicle);\n"
        + "        rho             rhoInf;\n"
        + "        rhoInf          " + f"{RHO:.8g}" + ";\n"
        + "        liftDir         (0 0 1);\n"
        + "        dragDir         (1 0 0);\n"
        + "        CofR            (" + center + ");\n"
        + "        pitchAxis       (0 1 0);\n"
        + "        magUInf         " + f"{speed_m_s:.8g}" + ";\n"
        + "        lRef            " + f"{lref_m:.8g}" + ";\n"
        + "        Aref            " + f"{aref_m2:.8g}" + ";\n"
        + "    }\n"
        + "    forces1\n"
        + "    {\n"
        + "        type            forces;\n"
        + "        libs            (forces);\n"
        + "        writeControl    timeStep;\n"
        + "        writeInterval   1;\n"
        + "        patches         (vehicle);\n"
        + "        rho             rhoInf;\n"
        + "        rhoInf          " + f"{RHO:.8g}" + ";\n"
        + "        CofR            (" + center + ");\n"
        + "    }\n"
        + "}\n"
    )


def _fv_schemes() -> str:
    return (
        _header("fvSchemes")
        + "ddtSchemes { default steadyState; }\n"
        + "gradSchemes { default Gauss linear; grad(U) cellLimited Gauss linear 1; }\n"
        + "divSchemes\n"
        + "{\n"
        + "    default none;\n"
        + "    div(phi,U) bounded Gauss linearUpwindV grad(U);\n"
        + "    div(phi,k) bounded Gauss limitedLinear 1;\n"
        + "    div(phi,omega) bounded Gauss limitedLinear 1;\n"
        + "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n"
        + "}\n"
        + "laplacianSchemes { default Gauss linear limited corrected 0.5; }\n"
        + "interpolationSchemes { default linear; }\n"
        + "snGradSchemes { default limited corrected 0.5; }\n"
        + "wallDist { method meshWave; }\n"
    )


def _fv_solution() -> str:
    return (
        _header("fvSolution")
        + "solvers\n"
        + "{\n"
        + "    p { solver GAMG; tolerance 1e-7; relTol 0.01; smoother GaussSeidel; }\n"
        + "    \"(U|k|omega)\" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.1; }\n"
        + "}\n"
        + "SIMPLE\n"
        + "{\n"
        + "    nNonOrthogonalCorrectors 1;\n"
        + "    consistent yes;\n"
        + "    residualControl { p 1e-4; U 1e-4; \"(k|omega)\" 1e-4; }\n"
        + "}\n"
        + "relaxationFactors\n"
        + "{\n"
        + "    equations { U 0.6; k 0.5; omega 0.5; p 0.3; }\n"
        + "}\n"
    )


def _transport() -> str:
    return (
        _header("transportProperties")
        + "transportModel  Newtonian;\n"
        + f"nu              {NU:.8g};\n"
    )


def _turbulence() -> str:
    return (
        _header("turbulenceProperties")
        + "simulationType  RAS;\n"
        + "RAS\n"
        + "{\n"
        + "    RASModel    kOmegaSST;\n"
        + "    turbulence  on;\n"
        + "    printCoeffs on;\n"
        + "}\n"
    )


def _u_field(velocity: tuple[float, float, float]) -> str:
    wind = " ".join(f"{value:.8g}" for value in velocity)
    boundary = (
        "    inlet { type fixedValue; value uniform (" + wind + "); }\n"
        + "    outlet { type inletOutlet; inletValue uniform (0 0 0); value uniform (" + wind + "); }\n"
        + "    ground { type noSlip; }\n"
        + "    top { type slip; }\n"
        + "    sides { type slip; }\n"
        + "    vehicle { type noSlip; }\n"
    )
    return _vector_field("U", "[0 1 -1 0 0 0 0]", wind, boundary)


def _pressure_boundaries() -> str:
    return (
        "    inlet { type zeroGradient; }\n"
        + "    outlet { type fixedValue; value uniform 0; }\n"
        + "    ground { type zeroGradient; }\n"
        + "    top { type zeroGradient; }\n"
        + "    sides { type zeroGradient; }\n"
        + "    vehicle { type zeroGradient; }\n"
    )


def _turb_boundaries(value: float, wall: str) -> str:
    text = f"{value:.8g}"
    return (
        "    inlet { type fixedValue; value uniform " + text + "; }\n"
        + "    outlet { type inletOutlet; inletValue uniform " + text + "; value uniform " + text + "; }\n"
        + "    ground { type " + wall + "; value uniform " + text + "; }\n"
        + "    top { type zeroGradient; }\n"
        + "    sides { type zeroGradient; }\n"
        + "    vehicle { type " + wall + "; value uniform " + text + "; }\n"
    )


def _nut_boundaries(value: float) -> str:
    text = f"{value:.8g}"
    return (
        "    inlet { type calculated; value uniform " + text + "; }\n"
        + "    outlet { type calculated; value uniform " + text + "; }\n"
        + "    ground { type nutkWallFunction; value uniform 0; }\n"
        + "    top { type zeroGradient; }\n"
        + "    sides { type zeroGradient; }\n"
        + "    vehicle { type nutkWallFunction; value uniform 0; }\n"
    )


def _vector_field(name: str, dimensions: str, internal: str, boundary: str) -> str:
    return (
        _header(name, "volVectorField")
        + "dimensions      " + dimensions + ";\n"
        + "internalField   uniform (" + internal + ");\n"
        + "boundaryField\n{\n"
        + boundary
        + "}\n"
    )


def _scalar_field(name: str, dimensions: str, internal: float, boundary: str) -> str:
    return (
        _header(name, "volScalarField")
        + "dimensions      " + dimensions + ";\n"
        + f"internalField   uniform {internal:.8g};\n"
        + "boundaryField\n{\n"
        + boundary
        + "}\n"
    )
