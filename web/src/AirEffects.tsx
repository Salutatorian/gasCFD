import { useFrame } from "@react-three/fiber"
import { useEffect, useMemo, useState } from "react"
import { BufferGeometry, DoubleSide, Float32BufferAttribute, Uint32BufferAttribute } from "three"

export type AirEffect = "flow" | "vortices" | "slice" | "all"

function rainbow(value: number): [number, number, number] {
  const x = Math.min(6, Math.max(0, 6 * (1 - value)))
  if (x < 1.2) return [1, x * 0.83333333, 0]
  if (x < 2) return [2.5 - x * 1.25, 1, 0]
  if (x < 3) return [0, 1, x - 2]
  if (x < 4) return [0, 4 - x, 1]
  if (x < 5) return [x * 0.4 - 1.6, 0, 3 - x * 0.5]
  return [2.4 - x * 0.4, 0, 3 - x * 0.5]
}

type Trail = {
  xyz: Float32Array
  speed: Float32Array
  dist: Float32Array
  total: number
}

function flowMesh(trails: Trail[]): BufferGeometry {
  const positions: number[] = []
  const colors: number[] = []
  for (const trail of trails) {
    const count = trail.dist.length
    for (let index = 1; index < count; index += 1) {
      positions.push(
        trail.xyz[(index - 1) * 3],
        trail.xyz[(index - 1) * 3 + 1],
        trail.xyz[(index - 1) * 3 + 2],
        trail.xyz[index * 3],
        trail.xyz[index * 3 + 1],
        trail.xyz[index * 3 + 2],
      )
      const start = rainbow(trail.speed[index - 1])
      const end = rainbow(trail.speed[index])
      colors.push(start[0], start[1], start[2], end[0], end[1], end[2])
    }
  }
  const geometry = new BufferGeometry()
  geometry.setAttribute("position", new Float32BufferAttribute(positions, 3))
  geometry.setAttribute("color", new Float32BufferAttribute(colors, 3))
  return geometry
}

function readStreamlines(buffer: ArrayBuffer): { geometry: BufferGeometry; trails: Trail[] } {
  const view = new DataView(buffer)
  let offset = 0
  const lineCount = view.getUint32(offset, true)
  offset += 4
  const counts: number[] = []
  for (let i = 0; i < lineCount; i += 1) {
    counts.push(view.getUint32(offset, true))
    offset += 4
  }
  const trails: Trail[] = []
  for (const count of counts) {
    const xyz = new Float32Array(count * 3)
    const speed = new Float32Array(count)
    const dist = new Float32Array(count)
    let traveled = 0
    for (let i = 0; i < count; i += 1) {
      const x = view.getFloat32(offset, true)
      const y = view.getFloat32(offset + 4, true)
      const z = view.getFloat32(offset + 8, true)
      const pace = view.getFloat32(offset + 12, true)
      offset += 16
      xyz[i * 3] = x
      xyz[i * 3 + 1] = y
      xyz[i * 3 + 2] = z
      speed[i] = pace
      if (i > 0) {
        const dx = x - xyz[(i - 1) * 3]
        const dy = y - xyz[(i - 1) * 3 + 1]
        const dz = z - xyz[(i - 1) * 3 + 2]
        traveled += Math.hypot(dx, dy, dz)
      }
      dist[i] = traveled
    }
    if (count >= 2 && traveled > 0) trails.push({ xyz, speed, dist, total: traveled })
  }
  return { geometry: flowMesh(trails), trails }
}

function sample(trail: Trail, distance: number): [number, number, number, number] {
  const wrapped = ((distance % trail.total) + trail.total) % trail.total
  let hi = 1
  while (hi < trail.dist.length && trail.dist[hi] < wrapped) hi += 1
  const lo = hi - 1
  const span = trail.dist[hi] - trail.dist[lo] || 1
  const mix = (wrapped - trail.dist[lo]) / span
  const ax = trail.xyz[lo * 3]
  const ay = trail.xyz[lo * 3 + 1]
  const az = trail.xyz[lo * 3 + 2]
  return [
    ax + (trail.xyz[hi * 3] - ax) * mix,
    ay + (trail.xyz[hi * 3 + 1] - ay) * mix,
    az + (trail.xyz[hi * 3 + 2] - az) * mix,
    trail.speed[lo] + (trail.speed[hi] - trail.speed[lo]) * mix,
  ]
}

function FlowDots({ trails, scale }: { trails: Trail[]; scale: number }) {
  const dots = 4
  const geometry = useMemo(() => {
    const geometry = new BufferGeometry()
    geometry.setAttribute("position", new Float32BufferAttribute(trails.length * dots * 3, 3))
    geometry.setAttribute("color", new Float32BufferAttribute(trails.length * dots * 3, 3))
    return geometry
  }, [trails])
  useEffect(() => () => geometry.dispose(), [geometry])
  useFrame(({ clock }) => {
    const position = geometry.getAttribute("position")
    const color = geometry.getAttribute("color")
    const time = clock.elapsedTime
    let slot = 0
    for (const trail of trails) {
      for (let dot = 0; dot < dots; dot += 1) {
        const along = ((time * (0.12 * scale / 24) + dot / dots) % 1) * trail.total
        const [x, y, z, pace] = sample(trail, along)
        position.setXYZ(slot, x, y, z)
        const tint = rainbow(pace)
        color.setXYZ(slot, tint[0], tint[1], tint[2])
        slot += 1
      }
    }
    position.needsUpdate = true
    color.needsUpdate = true
  })
  return (
    <points geometry={geometry}>
      <pointsMaterial size={0.045} vertexColors sizeAttenuation depthWrite={false} toneMapped={false} />
    </points>
  )
}

function Streamlines({ url, scale }: { url: string; scale: number }) {
  const [drawn, setDrawn] = useState<{ geometry: BufferGeometry; trails: Trail[] } | null>(null)
  useEffect(() => {
    let cancel = false
    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error("no streamlines")
        return response.arrayBuffer()
      })
      .then((buffer) => {
        if (!cancel) setDrawn(readStreamlines(buffer))
      })
      .catch(() => {
        // A new speed or cover is still solving. Keep the lines already on screen.
      })
    return () => {
      cancel = true
    }
  }, [url])
  useEffect(() => () => drawn?.geometry.dispose(), [drawn])
  if (!drawn) return null
  return (
    <>
      <lineSegments geometry={drawn.geometry}>
        <lineBasicMaterial vertexColors toneMapped={false} />
      </lineSegments>
      <FlowDots trails={drawn.trails} scale={scale} />
    </>
  )
}

function Vortices({ url, soft }: { url: string; soft: boolean }) {
  const [geometry, setGeometry] = useState<BufferGeometry | null>(null)
  useEffect(() => {
    let cancel = false
    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error("no vortices")
        return response.arrayBuffer()
      })
      .then((buffer) => {
        if (cancel) return
        const view = new DataView(buffer)
        const vertices = view.getUint32(0, true)
        const triangles = view.getUint32(4, true)
        if (vertices === 0 || triangles === 0) {
          setGeometry(null)
          return
        }
        const positions = new Float32Array(buffer, 8, vertices * 3)
        const colors = new Float32Array(buffer, 8 + vertices * 12, vertices * 3)
        const indices = new Uint32Array(buffer, 8 + vertices * 24, triangles * 3)
        const next = new BufferGeometry()
        next.setAttribute("position", new Float32BufferAttribute(positions, 3))
        next.setAttribute("color", new Float32BufferAttribute(colors, 3))
        next.setIndex(new Uint32BufferAttribute(indices, 1))
        next.computeVertexNormals()
        setGeometry((current) => {
          current?.dispose()
          return next
        })
      })
      .catch(() => {
        // Keep the surface already on screen while the next wind field is still solving.
      })
    return () => {
      cancel = true
    }
  }, [url])
  useEffect(() => () => geometry?.dispose(), [geometry])
  if (!geometry) return null
  return (
    <mesh geometry={geometry}>
      <meshLambertMaterial vertexColors transparent opacity={soft ? 0.78 : 0.94} depthWrite side={DoubleSide} toneMapped={false} />
    </mesh>
  )
}

function SpeedSlice({ url, strong }: { url: string; strong: boolean }) {
  const [geometry, setGeometry] = useState<BufferGeometry | null>(null)
  useEffect(() => {
    let cancel = false
    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error("no slice")
        return response.arrayBuffer()
      })
      .then((buffer) => {
        if (cancel) return
        const view = new DataView(buffer)
        let offset = 0
        const planes = view.getUint32(offset, true)
        offset += 4
        const positions: number[] = []
        const colors: number[] = []
        for (let plane = 0; plane < planes; plane += 1) {
          const axis = view.getUint32(offset, true)
          offset += 4
          const coord = view.getFloat32(offset, true)
          const u0 = view.getFloat32(offset + 4, true)
          const v0 = view.getFloat32(offset + 8, true)
          const du = view.getFloat32(offset + 12, true)
          offset += 16
          const nu = view.getUint32(offset, true)
          const nv = view.getUint32(offset + 4, true)
          offset += 8
          const speeds: number[] = []
          for (let i = 0; i < nu * nv; i += 1) {
            speeds.push(view.getFloat32(offset, true))
            offset += 4
          }
          if (!strong && axis !== 0) continue
          const place = (iu: number, iv: number): [number, number, number] => {
            const u = u0 + iu * du
            const v = v0 + iv * du
            return axis === 0 ? [u, coord, v] : [u, v, coord]
          }
          for (let iv = 0; iv < nv - 1; iv += 1) {
            for (let iu = 0; iu < nu - 1; iu += 1) {
              const corners = [
                [iu, iv],
                [iu + 1, iv],
                [iu + 1, iv + 1],
                [iu, iv + 1],
              ] as const
              const live = corners.filter(([iuu, ivv]) => speeds[iuu * nv + ivv] >= 0.1).length
              if (live < 3) continue
              const push = (iuu: number, ivv: number) => {
                const at = place(iuu, ivv)
                positions.push(at[0], at[1], at[2])
                const tint = rainbow(speeds[iuu * nv + ivv])
                colors.push(tint[0], tint[1], tint[2])
              }
              for (const [iuu, ivv] of [corners[0], corners[1], corners[2], corners[0], corners[2], corners[3]]) {
                push(iuu, ivv)
              }
            }
          }
        }
        const next = new BufferGeometry()
        next.setAttribute("position", new Float32BufferAttribute(positions, 3))
        next.setAttribute("color", new Float32BufferAttribute(colors, 3))
        setGeometry((current) => {
          current?.dispose()
          return next
        })
      })
      .catch(() => {
        // Keep the surface already on screen while the next wind field is still solving.
      })
    return () => {
      cancel = true
    }
  }, [url, strong])
  useEffect(() => () => geometry?.dispose(), [geometry])
  if (!geometry) return null
  return (
    <mesh geometry={geometry}>
      <meshBasicMaterial
        vertexColors
        transparent
        opacity={strong ? 0.95 : 0.55}
        depthWrite={strong}
        side={DoubleSide}
        toneMapped={false}
      />
    </mesh>
  )
}

export function AirScene({
  effect,
  airUrl,
  vortexUrl,
  sliceUrl,
  speedMph,
}: {
  effect: AirEffect
  airUrl: string | null
  vortexUrl: string | null
  sliceUrl: string | null
  speedMph: number
}) {
  const flow = effect === "flow" || effect === "all"
  const vortices = effect === "vortices" || effect === "all"
  const slice = effect === "slice" || effect === "all"
  const scale = Math.max(speedMph * 0.44704 * 1.35, 1)
  return (
    <>
      {flow && airUrl && <Streamlines url={airUrl} scale={scale} />}
      {vortices && vortexUrl && <Vortices url={vortexUrl} soft={effect === "all"} />}
      {slice && sliceUrl && <SpeedSlice url={sliceUrl} strong={effect === "slice"} />}
    </>
  )
}
