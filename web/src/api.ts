import type { Comparison, Experiment, FlowStatus, GeometryReport, Health, Job, LiveMath, Vehicle, WindState } from "./types"

async function errorMessage(response: Response): Promise<string> {
  const payload: unknown = await response.json().catch(() => null)
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail: unknown }).detail
      : payload
  if (typeof detail === "string") return detail
  if (detail && typeof detail === "object") {
    const report = detail as Partial<GeometryReport>
    const issues = Array.isArray(report.issues) ? report.issues.join(" ") : ""
    return [report.message, issues].filter(Boolean).join(" ")
  }
  return response.statusText
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<T>
}

export function fetchVehicle(): Promise<Vehicle> {
  return getJson("/api/vehicle")
}

export function fetchExperiments(): Promise<Experiment[]> {
  return getJson("/api/experiments")
}

export async function fetchActiveJob(): Promise<Job | null> {
  const payload = await getJson<{ job: Job | null }>("/api/jobs/active")
  return payload.job
}

export function fetchHealth(): Promise<Health> {
  return getJson("/api/health")
}

export function fetchMath(
  baseline: string,
  variant: string,
  speedMph: number,
  yawDeg: number,
): Promise<LiveMath> {
  const params = new URLSearchParams({
    baseline,
    variant,
    speed_mph: String(speedMph),
    yaw_deg: String(yawDeg),
  })
  return getJson(`/api/math?${params}`)
}

export function fetchComparison(
  baseline: string,
  variant: string,
  speedMph: number,
  yawDeg: number,
): Promise<Comparison> {
  const params = new URLSearchParams({
    baseline,
    variant,
    speed_mph: String(speedMph),
    yaw_deg: String(yawDeg),
  })
  return getJson(`/api/comparison?${params}`)
}

export async function uploadGeometry(experimentId: string, file: File): Promise<GeometryReport> {
  const body = new FormData()
  body.append("file", file)
  const response = await fetch(`/api/experiments/${experimentId}/geometry`, {
    method: "POST",
    body,
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload
    if (typeof detail === "string") throw new Error(detail)
    if (detail && typeof detail === "object") {
      const report = detail as GeometryReport
      throw new Error([report.message, ...(report.issues ?? [])].filter(Boolean).join(" "))
    }
    throw new Error(response.statusText)
  }
  return payload as GeometryReport
}

export async function startRun(experimentId: string, speedMph: number, yawDeg: number): Promise<Job> {
  const response = await fetch(`/api/experiments/${experimentId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speed_mph: speedMph, yaw_deg: yawDeg }),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<Job>
}

export function fetchJob(jobId: string): Promise<Job> {
  return getJson(`/api/jobs/${jobId}`)
}

export function fetchFlow(): Promise<FlowStatus> {
  return getJson("/api/fluidx3d")
}

async function postFlow(path: string, speedMph: number, experimentId: string): Promise<FlowStatus> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speed_mph: speedMph, experiment_id: experimentId }),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<FlowStatus>
}

export function startFlowRender(speedMph: number, experimentId = "001"): Promise<FlowStatus> {
  return postFlow("/api/fluidx3d/renders", speedMph, experimentId)
}

export function openFlowLive(speedMph: number, experimentId = "001"): Promise<FlowStatus> {
  return postFlow("/api/fluidx3d/live", speedMph, experimentId)
}

export function fetchWind(speedMph: number, front: boolean, rear: boolean): Promise<WindState> {
  const params = new URLSearchParams({
    speed_mph: String(speedMph),
    front: String(front),
    rear: String(rear),
  })
  return getJson(`/api/wind?${params}`)
}

export async function startWind(speedMph: number, front: boolean, rear: boolean): Promise<WindState> {
  const response = await fetch("/api/wind", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speed_mph: speedMph, front, rear }),
  })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<WindState>
}
