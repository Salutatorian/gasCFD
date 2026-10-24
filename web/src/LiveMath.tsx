import type { LiveMath, MathColumn } from "./types"

function num(value: number | null | undefined, digits: number, unit = ""): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  const text = value.toFixed(digits)
  return unit ? `${text} ${unit}` : text
}

function kw(value: number | null): string {
  if (value === null) return "—"
  return `${(value / 1000).toFixed(2)} kW`
}

function Eq({ text, value }: { text: string; value: string }) {
  return (
    <p className="eq">
      <span>{text}</span>
      <span className="num">{value}</span>
    </p>
  )
}

function mpgCell(column: MathColumn): string {
  if (column.used_for_fuel) return num(column.mpg, 1)
  if (column.mpg !== null) return `${num(column.mpg, 1)}*`
  return "—"
}

export function LiveMathPanel({ math }: { math: LiveMath | null }) {
  if (!math) {
    return (
      <section className="fuel">
        <h2>Live math</h2>
        <p className="muted">The highway-cruise equations appear here once the API answers.</p>
      </section>
    )
  }
  const v = math.speed_m_s
  const a = math.area_m2
  return (
    <section className="fuel">
      <h2>Live math · every experiment at {math.speed_mph} mph</h2>
      <Eq text={`v = ${math.speed_mph} mph`} value={num(v, 2, "m/s")} />
      <Eq text="ρ = 1.225 kg/m³" value={num(math.rho, 3)} />
      <Eq text={`A · ${math.area_source}`} value={num(a, 3, "m²")} />
      <Eq text={`R = Crr · m · g = 0.012 × ${math.mass_kg.toFixed(1)} × 9.81`} value={num(math.rolling_n, 1, "N")} />
      <Eq text="D = ½ ρ v² Cd A" value="newtons" />
      <Eq text="P_wheel = (D + R) v" value="then P_crank = P_wheel / 0.90 + 400 W" />
      <Eq text="P_fuel = P_crank / 0.25" value="MPG from gasoline 43.4 MJ/kg, 0.745 kg/L" />
      <table>
        <thead>
          <tr>
            <th>Experiment</th>
            <th>Cd</th>
            <th>Drag D</th>
            <th>Wheel power</th>
            <th>Fuel power</th>
            <th>MPG*</th>
          </tr>
        </thead>
        <tbody>
          {math.columns.map((column) => (
            <tr key={column.id}>
              <td>
                {column.name}
                <small className="muted">{column.missing ?? column.cd_label}</small>
              </td>
              <td className="num">{num(column.cd, 3)}</td>
              <td className="num">{num(column.drag_n, 1, "N")}</td>
              <td className="num">{kw(column.wheel_power_w)}</td>
              <td className="num">{kw(column.fuel_power_w)}</td>
              <td className="num">{mpgCell(column)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">{math.note} A dash means that experiment has no STL or no finished solve yet. Starred Toyota MPG is the brochure Cd through this model, not a solve. FluidX3D MPG stays blank on purpose.</p>
    </section>
  )
}
