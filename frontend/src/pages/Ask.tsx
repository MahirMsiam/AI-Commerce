import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { post } from '../api'
import { BarChartBox, ForecastChart, LineChartBox, type ForecastData } from '../components/charts'
import { Card, Spinner, btnGhost, btnPrimary } from '../components/ui'
import { bdt, num } from '../format'

type AskResult = {
  answer_text: string; sql: string; columns: string[]; rows: (string | number | null)[][]
  chart: { type: string; x: string; y: string }; engine: 'llm' | 'rules' | 'cache'; lang: string
  forecast?: ForecastData; suggestions?: string[]; note?: string
}

const CHIPS = [
  'Top 5 products by revenue in Chattogram last month',
  'Which division had the highest sales this month?',
  'Compare revenue this month vs last month by division',
  'Which distributors are above 80% of their credit limit?',
  'গত মাসে কোন অঞ্চলে বিক্রি সবচেয়ে বেশি?',
  'চট্টগ্রামে শীর্ষ ৫টি পণ্য কোনগুলো?',
  'কোন ডিস্ট্রিবিউটরদের বকেয়া সবচেয়ে বেশি?',
  'আগামী ৪ সপ্তাহে রংপুরে ওরস্যালাইনের চাহিদা কত হবে?',
]
const ENGINE: Record<string, [string, string]> = {
  llm: ['AI model', 'bg-violet-50 text-violet-800'], rules: ['Rules', 'bg-stone-100 text-stone-700'], cache: ['Cached AI answer', 'bg-teal-50 text-teal-800'],
}

const cell = (col: string, v: unknown) =>
  typeof v === 'number' ? (col.endsWith('bdt') ? bdt(v) : col.endsWith('pct') || col === 'pct_of_limit' ? `${v}%` : num(v)) : String(v ?? '–')

export default function Ask() {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<AskResult | null>(null)
  const [err, setErr] = useState('')
  const [showSql, setShowSql] = useState(false)
  const [showTable, setShowTable] = useState(false)

  const [params] = useSearchParams()
  useEffect(() => { const pre = params.get('q'); if (pre) ask(pre) }, [params]) // eslint-disable-line react-hooks/exhaustive-deps

  const ask = async (question: string) => {
    if (!question.trim()) return
    setQ(question); setBusy(true); setErr(''); setShowSql(false); setShowTable(false)
    try { setRes(await post<AskResult>('/ask', { question })) } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  const data = res ? res.rows.map((r) => Object.fromEntries(res.columns.map((c, i) => [c, r[i] as string | number]))) : []
  const isMoney = res?.chart.y.endsWith('bdt') ?? false
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <form onSubmit={(e) => { e.preventDefault(); ask(q) }} className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Your question"
          placeholder="Ask about sales, stock, credit… in English or বাংলা"
          className="flex-1 rounded-xl border border-stone-300 bg-white px-4 py-3 text-lg shadow-sm" />
        <button disabled={busy} className={`${btnPrimary} px-5`}>Ask</button>
      </form>
      <div className="flex flex-wrap gap-2">
        {CHIPS.map((c) => (
          <button key={c} onClick={() => ask(c)} disabled={busy}
            className="rounded-full border border-stone-300 bg-white px-3 py-1 text-sm text-stone-700 hover:bg-stone-50">{c}</button>
        ))}
      </div>

      {busy && <Spinner label="Local AI is thinking… (usually 5–15 s)" />}
      {err && <p className="text-sm text-red-700" role="alert">{err}</p>}

      {res && !busy && (
        <Card>
          <div className="flex items-start justify-between gap-3">
            <p className="text-lg text-stone-900">{res.answer_text}</p>
            <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${ENGINE[res.engine][1]}`}>{ENGINE[res.engine][0]}</span>
          </div>
          {res.note && <p className="mt-1 text-xs text-stone-500">{res.note}</p>}
          {res.suggestions && (
            <div className="mt-3 flex flex-wrap gap-2">
              {res.suggestions.map((s) => <button key={s} onClick={() => ask(s)} className={btnGhost}>{s}</button>)}
            </div>
          )}

          <div className="mt-4">
            {res.chart.type === 'forecast' && res.forecast && <ForecastChart data={res.forecast} />}
            {res.chart.type === 'bar' && data.length > 1 && <BarChartBox data={data} x={res.chart.x} y={res.chart.y} isMoney={isMoney} height={Math.max(180, data.length * 30)} />}
            {res.chart.type === 'line' && <LineChartBox data={data} x={res.chart.x} y={res.chart.y} isMoney={isMoney} height={260} />}
            {res.chart.type === 'number' && data[0] && (
              <div className="text-4xl font-semibold">{cell(res.chart.y, data[0][res.chart.y])}</div>
            )}
          </div>

          {res.columns.length > 0 && (
            <div className="mt-4 flex gap-2">
              <button onClick={() => setShowTable(!showTable)} className={btnGhost}>{showTable || res.chart.type === 'table' ? 'Hide table' : 'Show table'}</button>
              {res.sql && <button onClick={() => setShowSql(!showSql)} className={btnGhost}>{showSql ? 'Hide query' : 'Show query'}</button>}
            </div>
          )}
          {(showTable || res.chart.type === 'table') && res.columns.length > 0 && (
            <div className="mt-3 max-h-80 overflow-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-xs text-stone-500">{res.columns.map((c) => <th key={c} className="py-1 pr-3">{c}</th>)}</tr></thead>
                <tbody>{res.rows.map((r, i) => <tr key={i} className="border-t border-stone-100">{r.map((v, j) => <td key={j} className="py-1 pr-3">{cell(res.columns[j], v)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
          {showSql && <pre className="mt-3 overflow-auto rounded-lg bg-stone-900 p-3 text-xs text-stone-100">{res.sql}</pre>}
        </Card>
      )}
    </div>
  )
}
