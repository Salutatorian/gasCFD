import { useEffect, useState } from "react"
import { fetchFlow, openFlowLive, startFlowRender } from "./api"
import type { FlowStatus, FlowView } from "./types"
import { Viewer } from "./Viewer"

const VIEW_LABELS: Record<FlowView, string> = {
  orbit: "Orbit air",
  streamlines: "Streamlines",
  vortices: "Vortices",
  "velocity-slice": "Speed slice",
  "side-streamlines": "Side",
  "top-streamlines": "Top",
}

const VIEWS = Object.keys(VIEW_LABELS) as FlowView[]

export function FlowPanel({
  speed,
  experimentId,
  experimentName,
  length,
  width,
  height,
  stlUrl,
}: {
  speed: number
  experimentId: string
  experimentName: string
  length: number
  width: number
  height: number
  stlUrl: string | null
}) {
  const [flow, setFlow] = useState<FlowStatus | null>(null)
  const [view, setView] = useState<FlowView>("orbit")
  const [error, setError] = useState<string | null>(null)

  const rendering = flow?.render?.status === "running"
  useEffect(() => {
    fetchFlow()
      .then(setFlow)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "FluidX3D status failed"))
  }, [])
  useEffect(() => {
    if (!rendering) return
    const timer = window.setInterval(() => {
      fetchFlow()
        .then(setFlow)
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "FluidX3D status failed"))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [rendering])

  async function act(action: (speedMph: number, experimentId: string) => Promise<FlowStatus>) {
    setError(null)
    try {
      setFlow(await action(speed, experimentId))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "FluidX3D request failed")
    }
  }

  const render =
    flow?.renders.find((item) => item.speed_mph === speed && (item.experiment_id ?? "001") === experimentId) ?? null
  const result = render?.result
  const playable = view !== "orbit" && (render?.videos.includes(view) ?? false)

  return (
    <div className="flow">
      {view === "orbit" ? (
        <Viewer
          length={length}
          width={width}
          height={height}
          stlUrl={stlUrl}
          speedMph={speed}
          airUrl={`/api/fluidx3d/renders/${experimentId}/${speed}/streamlines.bin`}
        />
      ) : playable ? (
        <video
          key={`${experimentId}-${speed}-${view}`}
          src={`/api/fluidx3d/renders/${experimentId}/${speed}/${view}.mp4`}
          autoPlay
          loop
          muted
          playsInline
        />
      ) : (
        <div className="empty-tunnel">
          <strong>No FluidX3D render of {experimentName} at {speed} mph</strong>
          <p>Render takes about 7 minutes on the GPU. Select this experiment, then render, to see its airflow.</p>
        </div>
      )}
      <div className="flow-bar">
        <div className="choices" aria-label="FluidX3D view">
          {VIEWS.map((item) => (
            <button key={item} aria-pressed={item === view} onClick={() => setView(item)}>
              {VIEW_LABELS[item]}
            </button>
          ))}
        </div>
        <div className="choices">
          <button disabled={!flow?.render_ready || rendering || flow.live_running} onClick={() => void act(startFlowRender)}>
            {rendering ? `Rendering ${flow?.render?.experiment_id ?? ""} ${flow?.render?.speed_mph} mph` : `Render ${experimentId} at ${speed} mph`}
          </button>
          <button disabled={!flow?.live_ready || rendering} onClick={() => void act(openFlowLive)}>
            {flow?.live_running ? "Live window open · look around in it" : "Orbit in live air"}
          </button>
        </div>
      </div>
      <div className="caption">
        {flow?.render && flow.render.status !== "done" && <p className="status">{flow.render.message}</p>}
        {error && <p className="status">{error}</p>}
        {view === "orbit" && (
          <p>
            Drag to orbit {experimentName} at {speed} mph. Scroll zooms. Colored lines are the FluidX3D air for this speed, blue slow and red fast, so the same flow moves with the camera. The other buttons stay locked to one filmed angle. Live window: drag orbits, F flies.
          </p>
        )}
        {view !== "orbit" && result && (
          <p>
            FluidX3D lattice Boltzmann, {result.cell_mm.toFixed(1)} mm cells, {result.simulated_seconds} s of air. Ground{" "}
            {result.ground}, wheels {result.wheels}. FluidX3D Cd {result.cd_mean_second_half.toFixed(2)} is unvalidated: the
            car blocks {(100 * result.blockage_ratio).toFixed(0)}% of this box, so it is not the OpenFOAM table and is not used for fuel.
          </p>
        )}
        <p className="muted">
          Flow by <a href="https://github.com/ProjectPhysX/FluidX3D">FluidX3D</a>, © Dr. Moritz Lehmann, free for non-commercial use
          only. Car model from cadnav.com.
        </p>
      </div>
    </div>
  )
}
