import { useEffect, useState } from 'react'
import { get, type Alert } from '../api'
import { BarChartBox, ForecastChart, LineChartBox, type ForecastData } from '../components/charts'
import { Card, Kpi, Modal, SeverityBadge, Spinner } from '../components/ui'
import { bdt } from '../format'
import { t } from '../i18n'
import { useApp } from '../state'

type Kpis = { revenue_mtd_bdt: number; vs_last_month_pct: number | null; orders_today: number; active_distributors: number; receivables_bdt: number; overdue_bdt: number }
type Rec = { code: string; name: string; division: string; outstanding_bdt: number; overdue_bdt: number; pct_of_limit: number }
type Row = Record<string, string | number>

export default function Dashboard() {
  const { lang, resetKey } = useApp()
  const [kpis, setKpis] = useState<Kpis | null>(null)
  const [trend, setTrend] = useState<Row[]>([])
  const [divs, setDivs] = useState<Row[]>([])
  const [top, setTop] = useState<Row[]>([])
  const [rec, setRec] = useState<Rec[]>([])
  const [alerts, setAlerts] = useState<Alert[] | null>(null)
  const [open, setOpen] = useState<Alert | null>(null)

  useEffect(() => {
    const load = () => {
      get<Kpis>('/dashboard/kpis').then(setKpis)
      get<Row[]>('/dashboard/revenue-trend?weeks=26').then(setTrend)
      get<Row[]>('/dashboard/by-division?period=mtd').then(setDivs)
      get<Row[]>('/dashboard/top-products?period=mtd&limit=5').then(setTop)
      get<Rec[]>('/dashboard/receivables').then(setRec)
      get<Alert[]>('/alerts').then(setAlerts)
    }
    load()
    const id = setInterval(load, 10_000) // new portal orders appear live
    return () => clearInterval(id)
  }, [resetKey])

  const pct = kpis?.vs_last_month_pct
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label={t(lang, 'Revenue MTD')} value={bdt(kpis?.revenue_mtd_bdt)}
          sub={pct == null ? '' : <span className={pct >= 0 ? 'text-green-700' : 'text-red-700'}>{pct >= 0 ? '▲' : '▼'} {Math.abs(pct)}% vs same days last month</span>} />
        <Kpi label={t(lang, 'Orders today')} value={String(kpis?.orders_today ?? '–')} />
        <Kpi label={t(lang, 'Active distributors')} value={String(kpis?.active_distributors ?? '–')} sub="ordered in last 30 days" />
        <Kpi label={t(lang, 'Receivables')} value={bdt(kpis?.receivables_bdt)} />
        <Kpi label={t(lang, 'Overdue')} value={bdt(kpis?.overdue_bdt)} />
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_380px]">
        <div className="grid gap-4 md:grid-cols-2">
          <Card title="Weekly revenue, last 26 weeks" className="md:col-span-2">
            <LineChartBox data={trend} x="week" y="revenue_bdt" />
          </Card>
          <Card title="Revenue by division, this month">
            <BarChartBox data={divs.map((d) => ({ ...d, label: lang === 'bn' ? d.division_bn : d.division }))} x="label" y="revenue_bdt" />
          </Card>
          <Card title="Top 5 products, this month">
            <BarChartBox data={top.map((d) => ({ ...d, label: lang === 'bn' ? d.product_bn : d.product }))} x="label" y="revenue_bdt" />
          </Card>
          <Card title="Receivables risk" className="md:col-span-2">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-stone-500"><th className="py-1">Distributor</th><th>Division</th><th>Outstanding</th><th>Overdue</th><th className="w-48">% of limit</th></tr></thead>
              <tbody>
                {rec.slice(0, 8).map((r) => (
                  <tr key={r.code} className="border-t border-stone-100">
                    <td className="py-1.5"><b>{r.code}</b> <span className="text-stone-500">{r.name}</span></td><td>{r.division}</td>
                    <td>{bdt(r.outstanding_bdt)}</td><td>{bdt(r.overdue_bdt)}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="h-2 flex-1 rounded bg-stone-100"><div className="h-2 rounded" style={{ width: `${Math.min(100, r.pct_of_limit)}%`, background: r.pct_of_limit >= 90 ? '#d03b3b' : r.pct_of_limit >= 80 ? '#ec835a' : '#2a78d6' }} /></div>
                        <span className="w-10 text-right">{r.pct_of_limit}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>

        <Card title={<>{t(lang, 'Alerts')} <span className="font-normal text-stone-500">· AI forecast</span></>} className="h-fit">
          {!alerts && <Spinner label="Forecasting 432 product × distributor series…" />}
          <ul className="max-h-[70vh] space-y-2 overflow-auto pr-1">
            {alerts?.map((a, i) => (
              <li key={i}>
                <button disabled={a.type !== 'stock'} onClick={() => setOpen(a)}
                  className="w-full rounded-lg border border-stone-200 bg-white p-2.5 text-left text-sm hover:border-stone-400 disabled:cursor-default disabled:hover:border-stone-200">
                  <div className="flex items-center justify-between"><SeverityBadge severity={a.severity} />
                    <span className="text-xs text-stone-500">{a.type === 'stock' ? 'Stock' : 'Credit'} · {a.distributor_code}</span></div>
                  <div className="mt-1 text-stone-800">{a.message}</div>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {open && <ForecastModal alert={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function ForecastModal({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  const [data, setData] = useState<ForecastData | null>(null)
  useEffect(() => {
    get<ForecastData>(`/forecast?product_id=${alert.product_id}&distributor_id=${alert.distributor_id}&weeks=8`).then(setData)
  }, [alert])
  return (
    <Modal title={`${alert.product} · ${alert.distributor_code}: actual vs forecast`} onClose={onClose} wide>
      <p className="mb-2 text-sm text-stone-700">{alert.message}</p>
      {data ? <ForecastChart data={data} /> : <Spinner label="Loading forecast…" />}
      {data && <p className="mt-2 text-xs text-stone-500">Damped Holt exponential smoothing on the last 26 weeks · shaded area is the 80% range · next 8 weeks: {data.total_forecast} cartons.</p>}
    </Modal>
  )
}
