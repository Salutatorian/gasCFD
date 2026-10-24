import { useRef, useState } from "react"
import type { AirEffect } from "./AirEffects"
import type { WindResult, WindState } from "./types"
import { Viewer } from "./Viewer"

const EFFECTS: { id: AirEffect; label: string }[] = [
  { id: "all", label: "All" },
  { id: "flow", label: "Streamlines" },
  { id: "vortices", label: "Vortices" },
  { id: "slice", label: "Speed slice" },
]

export function WindPanel({
  speed,
  front,
  rear,
  onFront,
  onRear,
  wind,
  length,
  width,
  height,
  stlUrl,
}: {
  speed: number
  front: boolean
  rear: boolean
  onFront: (value: boolean) => void
  onRear: (value: boolean) => void
  wind: WindState | null
  length: number
  width: number
  height: number
  stlUrl: string | null
}) {
  const [effect, setEffect] = useState<AirEffect>(() => {
    const name = new URLSearchParams(window.location.search).get("effect")
    if (name === "flow" || name === "vortices" || name === "slice" || name === "all") return name
    return "flow"
  })
  const live = wind?.result ?? null
  const matches =
    live !== null && live.front === front && live.rear === rear && live.speed_mph === speed
  const held = useRef<WindResult | null>(null)
  if (matches && live) held.current = live
  const picture = matches ? live : held.current
  const boxes = front || rear ? `/api/wind/boxes.stl?front=${front ? 1 : 0}&rear=${rear ? 1 : 0}` : null
  const query = picture
    ? `speed_mph=${picture.speed_mph}&front=${picture.front ? 1 : 0}&rear=${picture.rear ? 1 : 0}&v=${picture.steps}&pic=11`
    : null
  const message = wind?.job?.message

  return (
    <div className="flow">
      {stlUrl ? (
        <Viewer
          length={length}
          width={width}
          height={height}
          stlUrl={stlUrl}
          extraUrl={boxes}
          airUrl={query ? `/api/wind/streamlines.bin?${query}` : null}
          vortexUrl={query ? `/api/wind/vortices.bin?${query}` : null}
          sliceUrl={query ? `/api/wind/slice.bin?${query}` : null}
          effect={effect}
          speedMph={picture?.speed_mph ?? speed}
          front={front}
          rear={rear}
        />
      ) : (
        <div className="empty-tunnel">
          <strong>No car in the tunnel</strong>
          <p>Import an STL onto 001 Stock. Nose at the low X end, tires on the ground.</p>
        </div>
      )}
      <div className="flow-bar">
        <div className="choices" aria-label="Air picture">
          {EFFECTS.map((item) => (
            <button key={item.id} aria-pressed={item.id === effect} onClick={() => setEffect(item.id)}>
              {item.label}
            </button>
          ))}
        </div>
        <div className="choices" aria-label="Wheel arch covers">
          <button aria-pressed={front} onClick={() => onFront(!front)}>
            Cover front arches
          </button>
          <button aria-pressed={rear} onClick={() => onRear(!rear)}>
            Cover rear arches
          </button>
        </div>
      </div>
      <div className="caption">
        {message && wind?.running && <p className="status">{message}</p>}
        {wind?.error && <p className="status">{wind.error}</p>}
        <p>
          {effect === "flow" && `Streamlines at ${speed} mph cover the whole car, from the tires and the underbody to above the roof. Red is fast, violet is slow. Drag to orbit.`}
          {effect === "vortices" && "Drag to orbit. The lit surface is FluidX3D's Q-criterion isosurface, colored by speed. This grid only resolves the large spinning regions."}
          {effect === "slice" && "Drag to orbit. One centerline speed cut, drawn the way FluidX3D draws a slice. The car is a hole in the sheet. Red is fast, violet is slow."}
          {effect === "all" && `Drag to orbit. Streamlines, the Q-criterion surface, and the speed slice, adapted from FluidX3D, at ${speed} mph.`}
          {" "}Covers sit flush with the body skin and close the arch. The bottom of the tire stays out.
        </p>
        <p>
          Streamlines, vortices, and speed colors are adapted from FluidX3D by Dr. Moritz Lehmann. That part is for non-commercial use. The drag numbers are still this tunnel, not FluidX3D.
        </p>
        <p>
          A cover fixed over a front wheel can block the steering, hide the brakes, or tear off. This is the shape, not a plan to build it.
        </p>
      </div>
    </div>
  )
}

export function WindReadout({ wind, front, rear }: { wind: WindState | null; front: boolean; rear: boolean }) {
  const result = wind?.result && wind.result.front === front && wind.result.rear === rear ? wind.result : null
  const fuel = result?.fuel
  const ratio = fuel?.drag_ratio ?? null
  const percent = ratio === null ? null : (ratio - 1) * 100
  const quiet = percent !== null && Math.abs(percent) < 2
  const better = percent !== null && percent <= -2
  return (
    <section className="fuel">
      <h2>This shape at the selected speed</h2>
      {!result && <p className="muted">{wind?.job?.message ?? "The air is settling."}</p>}
      {result && fuel && (
        <>
          <p className={`num ${quiet || percent === null ? "" : better ? "down" : "up"}`}>
            {percent === null
              ? "Drag change is not ready."
              : quiet
                ? front || rear
                  ? "Covers are on. Drag matches the open wheels."
                  : "Open wheels. This is the baseline."
                : `Drag ${better ? "down" : "up"} ${Math.abs(percent).toFixed(1)}% versus open wheels.`}
          </p>
          <dl>
            <div>
              <dt>Estimated mpg</dt>
              <dd className="num">{fuel.mpg === null ? "—" : fuel.mpg.toFixed(1)}</dd>
            </div>
            <div>
              <dt>Open-wheel mpg</dt>
              <dd className="num">{fuel.stock_mpg === null ? "—" : fuel.stock_mpg.toFixed(1)}</dd>
            </div>
            <div>
              <dt>Fuel drag</dt>
              <dd className="num">{fuel.drag_n === null ? "—" : `${fuel.drag_n.toFixed(0)} N`}</dd>
            </div>
            <div>
              <dt>Open-wheel fuel drag</dt>
              <dd className="num">{fuel.stock_drag_n === null ? "—" : `${fuel.stock_drag_n.toFixed(0)} N`}</dd>
            </div>
          </dl>
          <p className="muted">{fuel.note}</p>
          <p className="muted">
            This grid measured {result.stock_tunnel_drag_n?.toFixed(0) ?? "—"} N with open wheels and {result.drag_n.toFixed(0)} N for this shape, tunnel Cd {result.cd.toFixed(2)}. Cell {Math.round(result.cell_m * 1000)} mm, Reynolds {result.reynolds}, blockage {(result.blockage * 100).toFixed(0)}%. Those tunnel newtons are not the road load. Straight ahead. The road does not move.
          </p>
        </>
      )}
    </section>
  )
}
