# gasCFD

Local wind tunnel for comparing aerodynamic changes on a 2004 Toyota Matrix.

The browser at `localhost:3000` shows the same STL the solver meshes. OpenFOAM returns forces. A separate road-load model estimates highway fuel use from that drag. The fuel number is marked as an estimate and is never taken from the solver.

## Run

```powershell
python -m venv server\.venv
server\.venv\Scripts\python -m pip install -r server\requirements.txt
server\.venv\Scripts\python -m uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000
```

```powershell
npm --prefix web install
npm --prefix web run dev
```

Open http://127.0.0.1:3000.

The OpenFOAM image is `opencfd/openfoam-run:2406`. Pull it when you want a real solve:

```powershell
docker pull opencfd/openfoam-run:2406
```

Without that image, Run writes the case under `runs/` and stops. It does not invent Cd, drag, or MPG.

`GASCFD_SOLVER=off` writes the case and skips Docker.

## Geometry

There is no Matrix mesh in this repo. Import an STL you can use, in meters:

- nose at minimum X, front pointing toward −X
- width on Y, centered on 0
- up is Z, tires on Z = 0

The file has to land near the published envelope: 4.35 m long, 1.775 m wide, 1.54 m high. A matching box is not a sign-off. Put `review.json` next to a geometry file with `{"signed_off": true}` only after the shape has been checked.

Dimensions and Cd 0.32 are from the [Toyota Canada 2004 spec sheet](https://media.toyota.ca/content/dam/media-toyota/general/specifications/04matrix_specsfeat_e.pdf). The 2,679 lb curb weight and 29/36 mpg brochure figures are from the [2004 US eBrochure](https://www.auto-brochures.com/makes/Toyota/Matrix/Toyota_US%20Matrix_2004.pdf). Published Cd is a reference. It is not fed into the results.

## Solver limits

The first recipe is steady `simpleFoam` with k-omega SST, a stationary ground, and stationary wheels. Surface cells are about 10 mm, so a 3 mm skirt is not in the mesh. There is no radiator flow and no prism layer. Yaw is a freestream angle; drag stays on the car's X axis.

Aerodynamic power is drag force times speed. Highway MPG adds assumed rolling resistance, drivetrain efficiency, accessory load, and engine efficiency. Those assumptions are listed in the fuel panel. They are not a coast-down of this car.

## Airflow videos (FluidX3D)

The Airflow tab plays GPU lattice Boltzmann renders of the stock Matrix from [FluidX3D](https://github.com/ProjectPhysX/FluidX3D) by Dr. Moritz Lehmann, forked to [Salutatorian/FluidX3D](https://github.com/Salutatorian/FluidX3D) with a Matrix wind tunnel setup in `src/setup.cpp`. FluidX3D is free for non-commercial use only; it may not be used commercially or militarily, and published results from changed source require publishing that source (the fork). The car model is from [cadnav.com](https://www.cadnav.com); the model and the STLs made from it stay out of this repository.

One-time setup (needs an OpenCL GPU, Visual Studio 2022 Build Tools, and ffmpeg on PATH):

```powershell
git clone https://github.com/Salutatorian/FluidX3D fluidx3d
fluidx3d\build-gascfd.ps1
server\.venv\Scripts\python server\tools\fluidx3d_parts.py <path to Toyota_Matrix.3ds> vehicles\toyota-matrix-2004\stock\fluidx3d
```

Render writes five videos to `runs/fluidx3d/<mph>mph/` (about 7 minutes per speed on an RX 6900 XT). Open live window starts the interactive FluidX3D window; press H in it for keys.

The ground moves at road speed. The wheels do not turn: spinning voxelized CadNav tires next to the stationary arches went unstable. The FluidX3D Cd is shown with the box blockage and is not used in the CFD table or the fuel estimate.

## Tests

```powershell
server\.venv\Scripts\python -m pytest server
```
