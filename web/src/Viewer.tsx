import { Edges, OrbitControls } from "@react-three/drei"
import { Canvas, useLoader, useThree } from "@react-three/fiber"
import { Component, Suspense, useEffect, type ReactNode } from "react"
import { DoubleSide } from "three"
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js"
import { AirScene, type AirEffect } from "./AirEffects"

type ViewerProps = {
  length: number
  width: number
  height: number
  stlUrl: string | null
  airUrl?: string | null
  vortexUrl?: string | null
  sliceUrl?: string | null
  extraUrl?: string | null
  speedMph?: number
  effect?: AirEffect
  front?: boolean
  rear?: boolean
}

function Envelope({ length, width, height }: { length: number; width: number; height: number }) {
  return (
    <mesh position={[length / 2, height / 2, 0]}>
      <boxGeometry args={[length, height, width]} />
      <meshStandardMaterial color="#c4b48a" transparent opacity={0.45} />
      <Edges color="#f2ead8" />
    </mesh>
  )
}

function Cardboard({ url }: { url: string }) {
  const geometry = useLoader(STLLoader, url)
  return (
    <mesh geometry={geometry} renderOrder={3}>
      <meshBasicMaterial
        color="#e87820"
        side={DoubleSide}
        toneMapped={false}
        polygonOffset
        polygonOffsetFactor={-2}
      />
    </mesh>
  )
}

function FrameWheels({ length, front, rear }: { length: number; front: boolean; rear: boolean }) {
  const camera = useThree((state) => state.camera)
  const controls = useThree((state) => state.controls) as {
    target: { set: (x: number, y: number, z: number) => void }
    update: () => void
  } | null
  useEffect(() => {
    if (!front && !rear) return
    if (!controls) return
    const x = front && rear ? length * 0.5 : front ? length * 0.22 : length * 0.8
    const z = front && rear ? 8.2 : 2.6
    camera.position.set(x, 0.62, z)
    controls.target.set(x, 0.5, 0)
    controls.update()
  }, [camera, controls, front, length, rear])
  return null
}

function Body({
  url,
  extraUrl,
  airUrl,
  vortexUrl,
  sliceUrl,
  speedMph,
  effect,
}: {
  url: string
  extraUrl: string | null
  airUrl: string | null
  vortexUrl: string | null
  sliceUrl: string | null
  speedMph: number
  effect: AirEffect
}) {
  const geometry = useLoader(STLLoader, url)
  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      <mesh geometry={geometry}>
        <meshStandardMaterial color="#d7d2c8" metalness={0.12} roughness={0.45} side={DoubleSide} />
      </mesh>
      {extraUrl && (
        <Suspense fallback={null}>
          <Cardboard url={extraUrl} />
        </Suspense>
      )}
      <AirScene effect={effect} airUrl={airUrl} vortexUrl={vortexUrl} sliceUrl={sliceUrl} speedMph={speedMph} />
    </group>
  )
}

class CanvasError extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  render() {
    if (this.state.failed) {
      return <p className="viewer-note">The STL could not be displayed.</p>
    }
    return this.props.children
  }
}

export function Viewer({
  length,
  width,
  height,
  stlUrl,
  airUrl = null,
  vortexUrl = null,
  sliceUrl = null,
  extraUrl = null,
  speedMph = 40,
  effect = "all",
  front = false,
  rear = false,
}: ViewerProps) {
  return (
    <CanvasError key={stlUrl ?? "envelope"}>
      <Canvas
        camera={{ position: [length * 0.35, height + 1.4, width + 4.2], fov: 32 }}
        style={{ height: "100%", width: "100%" }}
      >
        <color attach="background" args={["#121512"]} />
        <ambientLight intensity={0.55} />
        <directionalLight position={[5, 8, 3]} intensity={1.4} />
        <gridHelper args={[24, 24, "#3c463f", "#242824"]} position={[length / 2, 0, 0]} />
        {stlUrl ? (
          <Suspense fallback={null}>
            <Body
              url={stlUrl}
              extraUrl={extraUrl}
              airUrl={airUrl}
              vortexUrl={vortexUrl}
              sliceUrl={sliceUrl}
              speedMph={speedMph}
              effect={effect}
            />
          </Suspense>
        ) : (
          <Envelope length={length} width={width} height={height} />
        )}
        <OrbitControls target={[length / 2, height / 2, 0]} makeDefault enableDamping dampingFactor={0.08} />
        <FrameWheels length={length} front={front} rear={rear} />
      </Canvas>
    </CanvasError>
  )
}
