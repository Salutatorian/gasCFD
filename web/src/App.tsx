import { useEffect, useState } from "react"
import {
  fetchComparison,
  fetchMath,
  fetchExperiments,
  fetchActiveJob,
  fetchHealth,
  fetchJob,
  fetchVehicle,
  fetchWind,
  startRun,
  startWind,
  uploadGeometry,
} from "./api"
import { LiveMathPanel } from "./LiveMath"
import type { Comparison, Experiment, Health, Job, LiveMath, Vehicle, WindState } from "./types"
import { WindPanel, WindReadout } from "./WindPanel"
import { Viewer } from "./Viewer"

const INTENT_LABELS: Record<string, string> = {
  thickness_mm: "Thickness",
  coverage_pct: "Coverage",
  clearance_mm: "Clearance",
  length_mm: "Length",
  angle_deg: "Angle",
  wheels: "Wheels",
  cover: "Cover",
  kind: "Kind",
  covers: "Covers",
  skirts: "Skirts",
  coverage: "Coverage",
  surface: "Surface",
}

function blank(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return value.toFixed(digits)
}

function signed(value: number | null, digits: number, suffix = ""): string {
  if (value === null || Number.isNaN(value)) return "—"
  const text = `${value > 0 ? "+" : ""}${value.toFixed(digits)}`
  return `${text}${suffix}`
}

function tone(value: number | null, lowerIsBetter: boolean): string {
  if (value === null || value === 0) return ""
  const improved = lowerIsBetter ? value < 0 : value > 0
  return improved ? "down" : "up"
}

function intentParts(key: string, value: string | number): { label: string; text: string } {
  const label = INTENT_LABELS[key] ?? key
  if (key.endsWith("_mm")) return { label, text: `${value} mm` }
  if (key.endsWith("_pct")) return { label, text: `${value}%` }
  if (key.endsWith("_deg")) return { label, text: `${value}°` }
  return { label, text: String(value) }
}

function withUnit(value: number | null, digits: number, unit: string): string {
  const text = blank(value, digits)
  return text === "—" ? "—" : `${text} ${unit}`
}

export function App() {
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [liveMath, setLiveMath] = useState<LiveMath | null>(null)
  const [selectedId, setSelectedId] = useState("003")
  const [baselineId, setBaselineId] = useState("001")
  const [variantId, setVariantId] = useState("003")
  const [speed, setSpeed] = useState(40)
  const [yaw, setYaw] = useState(0)
  const [stage, setStage] = useState<"model" | "flow">("flow")
  const [frontWells, setFrontWells] = useState(false)
  const [rearWells, setRearWells] = useState(false)
  const [wind, setWind] = useState<WindState | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)

  async function loadCatalog() {
    const [nextVehicle, nextExperiments, nextHealth, active] = await Promise.all([
      fetchVehicle(),
      fetchExperiments(),
      fetchHealth(),
      fetchActiveJob(),
    ])
    setVehicle(nextVehicle)
    setExperiments(nextExperiments)
    setHealth(nextHealth)
    if (active) setJob(active)
  }

  useEffect(() => {
    loadCatalog().catch(() => setOffline(true))
  }, [])

  useEffect(() => {
    if (offline || stage !== "flow") return
    let stop = false
    startWind(speed, frontWells, rearWells)
      .then((state) => {
        if (!stop) setWind(state)
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Wind request failed"))
    const timer = window.setInterval(() => {
      fetchWind(speed, frontWells, rearWells)
        .then((state) => {
          if (!stop) setWind(state)
        })
        .catch(() => undefined)
    }, 800)
    return () => {
      stop = true
      window.clearInterval(timer)
    }
  }, [offline, stage, speed, frontWells, rearWells])

  useEffect(() => {
    if (offline) return
    fetchComparison(baselineId, variantId, speed, yaw)
      .then(setComparison)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Comparison failed"))
    fetchMath(baselineId, variantId, speed, yaw)
      .then(setLiveMath)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Math failed"))
  }, [baselineId, variantId, speed, yaw, offline, job?.status])

  const jobId = job?.id
  const jobStatus = job?.status
  useEffect(() => {
    if (!jobId || jobStatus !== "running") return
    const timer = window.setInterval(() => {
      fetchJob(jobId)
        .then((next) => {
          setJob(next)
          if (next.status !== "running") {
            window.clearInterval(timer)
            loadCatalog().catch(() => setOffline(true))
          }
        })
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Job status failed"))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [jobId, jobStatus])

  const selected = experiments.find((item) => item.id === selectedId) ?? null
  const stock = experiments.find((item) => item.id === "001") ?? null
  const speeds = vehicle?.speeds_mph ?? [30, 40, 45, 60, 75]
  const yaws = vehicle?.yaw_deg ?? [0, 5, 10, 15]
  const dimensions = vehicle?.dimensions_m
  const stlUrl =
    selected?.geometry_report.present && selected.geometry_report.sha256
      ? `/api/experiments/${selected.id}/geometry.stl?v=${selected.geometry_report.sha256}`
      : null
  const stockUrl =
    stock?.geometry_report.present && stock.geometry_report.sha256
      ? `/api/experiments/001/geometry.stl?v=${stock.geometry_report.sha256}`
      : null

  async function onUpload(file: File | undefined) {
    if (!file || !selected) return
    setError(null)
    try {
      await uploadGeometry(selected.id, file)
      await loadCatalog()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed")
    }
  }

  async function onRun() {
    if (!selected) return
    setError(null)
    try {
      const next = await startRun(selected.id, speed, yaw)
      setJob(next)
      if (next.status !== "running") await loadCatalog()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run failed")
    }
  }

  return (
    <div className="app">
      <header>
        <div>
          <h1>GASCFD</h1>
          <p>2004 Toyota Matrix · local wind tunnel</p>
        </div>
        <p>{vehicle?.configuration ?? "Waiting for the local API"}</p>
      </header>
      <main className="workspace">
        <aside className="rail">
          <h2>Experiments</h2>
          {stage === "flow" && (
            <p className="muted">
              The wind view uses 001 Stock. Arch covers are placed from the tires, flush with the skin, so you do not position them. Import a car here if you want a different body.
            </p>
          )}
          <div className="experiment-list">
            {experiments.map((item) => (
              <button
                key={item.id}
                className={item.id === selectedId ? "active" : ""}
                onClick={() => {
                  setSelectedId(item.id)
                  if (item.id !== baselineId) setVariantId(item.id)
                }}
              >
                <strong>
                  {item.id} {item.name}
                </strong>
                <small>{item.summary}</small>
                <span className={item.geometry_report.valid ? "badge ready" : "badge"}>
                  {item.geometry_report.valid
                    ? "STL ready"
                    : item.geometry_report.runnable
                      ? "Can run"
                      : item.geometry_report.present
                        ? "Size off"
                        : "No STL"}
                </span>
              </button>
            ))}
          </div>
          {selected && (
            <>
              <h2>Geometry</h2>
              <p className="muted">{selected.geometry_report.message}</p>
              {selected.geometry_report.issues.map((issue) => (
                <p className="muted" key={issue}>
                  {issue}
                </p>
              ))}
              {selected.intent && (
                <dl>
                  {Object.entries(selected.intent).map(([key, value]) => {
                    const part = intentParts(key, value)
                    return (
                      <div key={key}>
                        <dt>{part.label}</dt>
                        <dd>{part.text}</dd>
                      </div>
                    )
                  })}
                </dl>
              )}
              <p className="muted">These notes describe the part to build. The solver uses the STL only.</p>
              <label className="file">
                Import STL
                <input
                  type="file"
                  accept=".stl"
                  onChange={(event) => void onUpload(event.target.files?.[0])}
                />
              </label>
              <p className="muted">
                Meters. Nose toward −X. Width on Y. Up is Z. Tires on Z = 0.
                {vehicle ? ` ${vehicle.orientation.x}` : ""}
              </p>
              {stage === "model" && (
                <button
                  className="run"
                  disabled={!selected.geometry_report.runnable || job?.status === "running"}
                  onClick={() => void onRun()}
                >
                  {job?.status === "running" ? "Running CFD" : `Run ${selected.name}`}
                </button>
              )}
              {job && (
                <p className="status">
                  {job.stage}: {job.message}
                  {job.log_tail.length > 0 ? `\n${job.log_tail.slice(-6).join("\n")}` : ""}
                </p>
              )}
              {error && <p className="status">{error}</p>}
            </>
          )}
          {offline && <p className="status">The local API is not running on port 8000.</p>}
        </aside>
        <section className="viewer">
          <div className="choices stage-tabs" aria-label="Viewer">
            <button aria-pressed={stage === "flow"} onClick={() => setStage("flow")}>
              Wind
            </button>
            <button aria-pressed={stage === "model"} onClick={() => setStage("model")}>
              Solver STL
            </button>
          </div>
          {stage === "flow" ? (
            <WindPanel
              speed={speed}
              front={frontWells}
              rear={rearWells}
              onFront={setFrontWells}
              onRear={setRearWells}
              wind={wind}
              length={dimensions?.length ?? 4.35}
              width={dimensions?.width ?? 1.775}
              height={dimensions?.height ?? 1.54}
              stlUrl={stockUrl}
            />
          ) : (
            <>
              {dimensions && (
                <Viewer
                  length={dimensions.length}
                  width={dimensions.width}
                  height={dimensions.height}
                  stlUrl={stlUrl}
                />
              )}
              {!stlUrl && (
                <div className="empty-tunnel">
                  <strong>No car in the tunnel</strong>
                  <p>This experiment has no STL, so there is no body to show.</p>
                  <p>Stock Matrix is the converted CadNav mesh. The other experiments still need their own file.</p>
                </div>
              )}
              <p className="caption">
                {job?.status === "running"
                  ? "OpenFOAM is still building the mesh. Force numbers show up in the table only after that solve finishes."
                  : stlUrl && selected && !selected.geometry_report.valid
                  ? "The CadNav body as OpenFOAM meshes it. The glass in the 3DS has no panes. Force numbers stay empty until OpenFOAM finishes."
                  : stlUrl
                    ? "This STL is what OpenFOAM meshes. Force numbers stay empty until OpenFOAM finishes."
                    : dimensions
                      ? `Published envelope, ${dimensions.length} × ${dimensions.width} × ${dimensions.height} m. This box is not the car.`
                      : "Published envelope. This box is not the car."}
              </p>
            </>
          )}
        </section>
        <section className="dashboard">
          <h2>{stage === "flow" ? "Wind result" : "CFD result"}</h2>
          {stage === "flow" ? (
            <>
              <div className="choices" aria-label="Speed">
                {speeds.map((item) => (
                  <button key={item} aria-pressed={item === speed} onClick={() => setSpeed(item)}>
                    {item} mph
                  </button>
                ))}
              </div>
              <WindReadout wind={wind} front={frontWells} rear={rearWells} />
            </>
          ) : (
            <>
          <div className="pair">
            <label>
              Baseline
              <select value={baselineId} onChange={(event) => setBaselineId(event.target.value)}>
                {experiments.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id} {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Variant
              <select value={variantId} onChange={(event) => setVariantId(event.target.value)}>
                {experiments.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id} {item.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="choices" aria-label="Speed">
            {speeds.map((item) => (
              <button key={item} aria-pressed={item === speed} onClick={() => setSpeed(item)}>
                {item} mph
              </button>
            ))}
          </div>
          <div className="choices" aria-label="Yaw">
            {yaws.map((item) => (
              <button key={item} aria-pressed={item === yaw} onClick={() => setYaw(item)}>
                {item}° yaw
              </button>
            ))}
          </div>
          <p className="muted">Runs use this speed and yaw. Drag is the body-axis force, the one that costs fuel. The live math below updates when you change speed or the two experiments.</p>
          <LiveMathPanel math={liveMath} />
          {comparison && <ResultTable comparison={comparison} />}
          <section className="fuel">
            <h2>Estimated fuel impact</h2>
            <table>
              <thead>
                <tr>
                  <th>Measurement</th>
                  <th>{comparison?.baseline.name ?? "Baseline"}</th>
                  <th>{comparison?.variant.name ?? "Variant"}</th>
                  <th>Variant − baseline</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Highway MPG*</td>
                  <td className="num">{blank(comparison?.fuel.baseline_mpg, 1)}</td>
                  <td className="num">{blank(comparison?.fuel.variant_mpg, 1)}</td>
                  <td className={`num ${tone(comparison?.change.mpg ?? null, false)}`}>
                    {signed(comparison?.change.mpg ?? null, 1)}
                  </td>
                </tr>
              </tbody>
            </table>
            <p className="muted">{comparison?.fuel.note}</p>
            <p className="muted">
              Brochure highway figure: {comparison?.fuel.brochure_highway_mpg ?? "—"} mpg.{" "}
              {comparison?.fuel.brochure_mpg_source} It is not used in the calculation.
            </p>
            <ul className="assumptions">
              {(comparison?.fuel.assumptions ?? []).map((item) => (
                <li key={item.id}>
                  {item.label} Value: {item.value}.
                </li>
              ))}
              {comparison && (
                <li>
                  Vehicle mass {comparison.fuel.mass_kg.toFixed(1)} kg. {comparison.fuel.mass_source}
                </li>
              )}
            </ul>
          </section>
          <p className="muted">
            Published reference Cd {comparison?.published_cd.value ?? "0.32"}.{" "}
            {comparison?.published_cd.source ?? "Not a simulation result."}
          </p>
          <p className="muted">{health?.mesh_recipe.summary}</p>
          <details>
            <summary>Model limits</summary>
            <ul className="assumptions">
              {(comparison?.limits ?? []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </details>
          {health && !health.image_present && (
            <p className="muted">Solver image {health.image} is not pulled yet. A run will write the case and stop before OpenFOAM.</p>
          )}
            </>
          )}
        </section>
      </main>
      <footer>
        <p>
          {stage === "flow"
            ? "Drag change comes from the local lattice-Boltzmann tunnel. Miles per gallon use that change on the brochure Cd, plus assumed tires and engine."
            : "CFD numbers come from OpenFOAM. Miles per gallon do not."}
        </p>
      </footer>
    </div>
  )
}

function ResultTable({ comparison }: { comparison: Comparison }) {
  const rows = [
    {
      label: "Cd",
      base: blank(comparison.baseline.cd, 3),
      variant: blank(comparison.variant.cd, 3),
      change: signed(comparison.change.cd_percent, 1, "%"),
      tone: tone(comparison.change.cd_percent, true),
    },
    {
      label: "Drag",
      base: withUnit(comparison.baseline.drag_n, 1, "N"),
      variant: withUnit(comparison.variant.drag_n, 1, "N"),
      change: signed(comparison.change.drag_n, 1, " N"),
      tone: tone(comparison.change.drag_n, true),
    },
    {
      label: "Aero power",
      base: comparison.baseline.aero_power_w === null ? "—" : `${(comparison.baseline.aero_power_w / 1000).toFixed(2)} kW`,
      variant: comparison.variant.aero_power_w === null ? "—" : `${(comparison.variant.aero_power_w / 1000).toFixed(2)} kW`,
      change:
        comparison.change.aero_power_w === null
          ? "—"
          : signed(comparison.change.aero_power_w / 1000, 2, " kW"),
      tone: tone(comparison.change.aero_power_w, true),
    },
    {
      label: "Lift",
      base: withUnit(comparison.baseline.lift_n, 1, "N"),
      variant: withUnit(comparison.variant.lift_n, 1, "N"),
      change: signed(comparison.change.lift_n, 1, " N"),
      tone: tone(comparison.change.lift_n, true),
    },
    {
      label: "Side force",
      base: withUnit(comparison.baseline.side_n, 1, "N"),
      variant: withUnit(comparison.variant.side_n, 1, "N"),
      change: signed(comparison.change.side_n, 1, " N"),
      tone: "",
    },
    {
      label: "Yaw",
      base: `${comparison.baseline.yaw_deg}°`,
      variant: `${comparison.variant.yaw_deg}°`,
      change: "—",
      tone: "",
    },
    {
      label: "Speed",
      base: `${comparison.baseline.speed_mph} mph`,
      variant: `${comparison.variant.speed_mph} mph`,
      change: "—",
      tone: "",
    },
  ]
  return (
    <>
      <table>
        <thead>
          <tr>
            <th>Measurement</th>
            <th>{comparison.baseline.name}</th>
            <th>{comparison.variant.name}</th>
            <th>Variant − baseline</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td>
              <td className="num">{row.base}</td>
              <td className="num">{row.variant}</td>
              <td className={`num ${row.tone}`}>{row.change}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        Aerodynamic power is drag force times speed.
        {comparison.baseline.aref_m2 !== null || comparison.variant.aref_m2 !== null
          ? ` Cd uses the STL frontal area: baseline ${blank(comparison.baseline.aref_m2, 3)} m², variant ${blank(comparison.variant.aref_m2, 3)} m².`
          : " Frontal area is measured from the STL after a solved run."}
        {comparison.baseline.mesh_hit_cell_cap || comparison.variant.mesh_hit_cell_cap
          ? " The mesher hit its cell cap."
          : ""}
        {comparison.baseline.source || comparison.variant.source
          ? " Unsigned geometry is not a Matrix result."
          : ""}
      </p>
    </>
  )
}
