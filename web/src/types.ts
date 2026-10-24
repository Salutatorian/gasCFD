export type GeometryReport = {
  present: boolean
  valid: boolean
  signed_off: boolean
  message: string
  triangles: number | null
  extents_m: { length_x: number; width_y: number; height_z: number } | null
  projected_area_m2: number | null
  sha256: string | null
  issues: string[]
  runnable: boolean
}

export type Experiment = {
  id: string
  name: string
  summary: string
  intent: Record<string, string | number> | null
  geometry: string
  geometry_report: GeometryReport
}

export type Vehicle = {
  name: string
  year: number
  configuration: string
  dimensions_m: { length: number; width: number; height: number; wheelbase: number }
  speeds_mph: number[]
  yaw_deg: number[]
  orientation: { x: string; y: string; z: string; units: string }
}

export type Column = {
  id: string
  name: string
  speed_mph: number
  yaw_deg: number
  cd: number | null
  drag_n: number | null
  lift_n: number | null
  side_n: number | null
  aero_power_w: number | null
  aref_m2: number | null
  geometry_signed_off: boolean
  mesh_hit_cell_cap: boolean
  source: string | null
}

export type Comparison = {
  speed_mph: number
  yaw_deg: number
  baseline: Column
  variant: Column
  change: {
    cd_percent: number | null
    drag_n: number | null
    lift_n: number | null
    side_n: number | null
    aero_power_w: number | null
    mpg: number | null
    mpg_percent: number | null
  }
  fuel: {
    baseline_mpg: number | null
    variant_mpg: number | null
    assumptions: { id: string; value: number; label: string }[]
    mass_kg: number
    mass_source: string
    uses_published_cd: boolean
    brochure_highway_mpg: number
    brochure_mpg_source: string
    note: string
  }
  published_cd: { value: number; source: string; used_in_results: boolean }
  limits: string[]
}

export type Job = {
  id: string
  status: "running" | "done" | "error"
  stage: string
  message: string
  log_tail: string[]
}

export type MathColumn = {
  id: string
  name: string
  kind: "published" | "openfoam" | "fluidx3d"
  cd: number | null
  cd_label: string
  drag_n: number | null
  rolling_n: number
  aero_power_w: number | null
  wheel_power_w: number | null
  crank_power_w: number | null
  fuel_power_w: number | null
  mpg: number | null
  used_for_fuel: boolean
  missing: string | null
}

export type LiveMath = {
  speed_mph: number
  speed_m_s: number
  rho: number
  mass_kg: number
  area_m2: number | null
  area_source: string
  rolling_n: number
  assumptions: { id: string; value: number; label: string }[]
  columns: MathColumn[]
  note: string
}

export type FlowView = "orbit" | "streamlines" | "vortices" | "velocity-slice" | "side-streamlines" | "top-streamlines"

export type FlowRender = {
  experiment_id: string
  speed_mph: number
  videos: FlowView[]
  result: {
    solver: string
    simulated_seconds: number
    cell_mm: number
    frontal_area_m2: number
    blockage_ratio: number
    cd_mean_second_half: number
    ground: string
    wheels: string
  }
}

export type FlowStatus = {
  live_ready: boolean
  render_ready: boolean
  parts_ready: boolean
  ffmpeg: boolean
  live_running: boolean
  render: { speed_mph: number; experiment_id?: string; status: "running" | "done" | "error"; message: string } | null
  renders: FlowRender[]
}

export type WindFuel = {
  drag_n: number | null
  cd: number | null
  mpg: number | null
  stock_mpg: number | null
  stock_drag_n: number | null
  drag_ratio: number | null
  aero_power_w: number | null
  stock_aero_power_w: number | null
  note: string
}

export type WindResult = {
  speed_mph: number
  front: boolean
  rear: boolean
  drag_n: number
  cd: number
  area_m2: number
  blockage: number
  cell_m: number
  reynolds: number
  steps: number
  lines: number
  stock_tunnel_drag_n?: number
  fuel: WindFuel
}

export type WindState = {
  running: boolean
  job: { speed_mph: number; front: boolean; rear: boolean; message: string; error?: string } | null
  error: string | null
  result: WindResult | null
}

export type Health = {
  docker: boolean
  image: string
  image_present: boolean
  mesh_recipe: { id: string; summary: string }
}
