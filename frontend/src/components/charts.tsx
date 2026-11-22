import {
  Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { bdt, shortDate } from '../format'

const BLUE = '#2a78d6'
const ORANGE = '#eb6834'
const GRID = '#e7e6e2'
const AXIS = { fontSize: 11, fill: '#52514e' }

const money = (v: unknown) => bdt(Number(v))
const compactMoney = (v: number) => (v >= 1e7 ? `${(v / 1e7).toFixed(1)}cr` : v >= 1e5 ? `${(v / 1e5).toFixed(0)}L` : `${v}`)

type Row = Record<string, string | number>

/** Single-series line: no legend, the card title names it. */
export function LineChartBox({ data, x, y, isMoney = true, height = 220 }: { data: Row[]; x: string; y: string; isMoney?: boolean; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey={x} tick={AXIS} tickFormatter={(v) => (/^\d{4}-\d\d-\d\d/.test(String(v)) ? shortDate(String(v)) : String(v))} />
        <YAxis tick={AXIS} tickFormatter={isMoney ? compactMoney : undefined} width={48} />
        <Tooltip formatter={isMoney ? money : undefined} labelFormatter={(v) => String(v)} />
        <Line type="monotone" dataKey={y} stroke={BLUE} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

/** Single-series bar, horizontal by default (long category names). */
export function BarChartBox({ data, x, y, isMoney = true, horizontal = true, height = 240 }: { data: Row[]; x: string; y: string; isMoney?: boolean; horizontal?: boolean; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      {horizontal ? (
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 8 }} barCategoryGap={4}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" tick={AXIS} tickFormatter={isMoney ? compactMoney : undefined} />
          <YAxis type="category" dataKey={x} tick={AXIS} width={140} />
          <Tooltip formatter={isMoney ? money : undefined} cursor={{ fill: '#f3f2ef' }} />
          <Bar dataKey={y} fill={BLUE} radius={[0, 4, 4, 0]} isAnimationActive={false} />
        </BarChart>
      ) : (
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey={x} tick={AXIS} />
          <YAxis tick={AXIS} tickFormatter={isMoney ? compactMoney : undefined} width={48} />
          <Tooltip formatter={isMoney ? money : undefined} cursor={{ fill: '#f3f2ef' }} />
          <Bar dataKey={y} fill={BLUE} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      )}
    </ResponsiveContainer>
  )
}

export type ForecastData = {
  product: string; scope: string; total_forecast: number
  actual: { week: string; cartons: number }[]
  forecast: { week: string; forecast: number; lower: number; upper: number }[]
}

/** Actual = solid blue, forecast = dashed orange, 80% band = light fill, with a legend. */
export function ForecastChart({ data, height = 280 }: { data: ForecastData; height?: number }) {
  const last = data.actual[data.actual.length - 1]
  const rows: Row[] = [
    ...data.actual.map((a) => ({ week: a.week, actual: a.cartons })),
    // Join the dashed line to the last actual point.
    ...data.forecast.map((f) => ({ week: f.week, forecast: f.forecast, band: [f.lower, f.upper] as unknown as number })),
  ]
  const joinIdx = data.actual.length - 1
  rows[joinIdx] = { ...rows[joinIdx], forecast: last.cartons }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="week" tick={AXIS} tickFormatter={(v) => shortDate(String(v))} minTickGap={24} />
        <YAxis tick={AXIS} width={40} />
        <Tooltip formatter={(v) => (Array.isArray(v) ? `${v[0]} – ${v[1]}` : `${v} cartons`)} labelFormatter={(v) => `Week of ${shortDate(String(v))}`} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Area dataKey="band" name="80% range" fill={ORANGE} fillOpacity={0.12} stroke="none" isAnimationActive={false} />
        <Line dataKey="actual" name="Actual" stroke={BLUE} strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line dataKey="forecast" name="Forecast" stroke={ORANGE} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
