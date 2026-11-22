import { useEffect, useState } from 'react'
import { get, post } from '../api'
import { Card, Spinner, btnGhost, btnPrimary } from '../components/ui'
import { bdt } from '../format'
import { useApp } from '../state'

type Email = { id: string; from: string; subject: string; body: string; lang: string; received_at: string; status: string; run_id: number | null }
type Step = { step: number; type: string; name: string; input: unknown; output: unknown; ms: number }
type Task = { title: string; description: string; assignee: string; due_date: string; priority: string }
type Run = {
  run_id: number; intent: string; status: string; trace: Step[]
  draft: { to: string; subject: string; body: string; lang: string; writer: string } | null
  task: Task | null; order: { lines: { product: string; cartons: number }[]; total_bdt: number } | null
}

const STATUS: Record<string, string> = {
  new: 'bg-blue-50 text-blue-800', awaiting_approval: 'bg-amber-50 text-amber-900', approved: 'bg-green-50 text-green-800',
  discarded: 'bg-stone-100 text-stone-600', no_action: 'bg-stone-100 text-stone-600',
}
const STEP_ICON: Record<string, string> = { tool_call: '🔧', tool_result: '📥', thought: '💭', draft: '✉️', task: '📋' }

export default function Agent() {
  const { resetKey } = useApp()
  const [emails, setEmails] = useState<Email[]>([])
  const [sel, setSel] = useState<Email | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [shown, setShown] = useState(0) // trace steps revealed so far
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState('')

  const loadInbox = () => get<Email[]>('/agent/inbox').then((e) => { setEmails(e); return e })
  useEffect(() => {
    loadInbox().then((e) => setSel(e.find((x) => x.id === 'e1') ?? e[0])); setRun(null)
  }, [resetKey])
  useEffect(() => { // reveal the trace one step at a time
    if (!run || shown >= run.trace.length) return
    const id = setTimeout(() => setShown(shown + 1), 450)
    return () => clearTimeout(id)
  }, [run, shown])

  const pick = (e: Email) => { setSel(e); setRun(null); setDone('') }
  const runAgent = async () => {
    if (!sel) return
    setBusy(true); setDone(''); setRun(null)
    try {
      const r = await post<Run>(`/agent/run/${sel.id}`)
      setRun(r); setShown(0); setBody(r.draft?.body ?? ''); loadInbox()
    } finally { setBusy(false) }
  }
  const approve = async () => {
    if (!run) return
    const r = await post<{ task_id: number; order: { id: number } | null }>(`/agent/approve/${run.run_id}`, { body })
    setDone(`Reply sent (simulated). Task #${r.task_id} created${r.order ? `, draft order #${r.order.id} On hold` : ''}.`)
    setRun({ ...run, status: 'approved' }); loadInbox()
  }
  const discard = async () => {
    if (!run) return
    await post(`/agent/discard/${run.run_id}`); setDone('Discarded. Nothing was sent.'); setRun({ ...run, status: 'discarded' }); loadInbox()
  }
  const traceDone = run && shown >= run.trace.length

  return (
    <div className="grid gap-4 xl:grid-cols-[280px_1fr_360px]">
      <Card title="Inbox (sample)">
        <ul className="space-y-1">
          {emails.map((e) => (
            <li key={e.id}>
              <button onClick={() => pick(e)} className={`w-full rounded-lg p-2 text-left text-sm ${sel?.id === e.id ? 'bg-blue-50' : 'hover:bg-stone-50'}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium">{e.from}</span>
                  <span className={`shrink-0 rounded-full px-1.5 text-[10px] ${STATUS[e.status]}`}>{e.status.replace('_', ' ')}</span>
                </div>
                <div className="truncate text-stone-700">{e.subject}</div>
              </button>
            </li>
          ))}
        </ul>
      </Card>

      <div className="space-y-4">
        {sel && (
          <Card>
            <div className="text-xs text-stone-500">From {sel.from} · {sel.received_at.replace('T', ' ').slice(0, 16)}</div>
            <h2 className="mt-1 text-lg font-semibold">{sel.subject}</h2>
            <p className="mt-3 whitespace-pre-wrap text-stone-800">{sel.body}</p>
            <button onClick={runAgent} disabled={busy} className={`${btnPrimary} mt-4`}>▶ Run agent</button>
            {busy && <div className="mt-3"><Spinner label="Agent working… (local AI can take 10–30 s)" /></div>}
          </Card>
        )}
        {run && traceDone && run.draft && (
          <Card title={<>Draft reply <span className="font-normal text-stone-500">· {run.draft.writer === 'llm' ? 'written by local AI' : 'template'} · {run.draft.lang === 'bn' ? 'বাংলা' : 'English'}</span></>}>
            <div className="mb-2 text-sm text-stone-600">To {run.draft.to} · {run.draft.subject}</div>
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={10} aria-label="Draft reply"
              disabled={run.status !== 'awaiting_approval'}
              className="w-full rounded-lg border border-stone-300 p-3 text-sm leading-relaxed" />
            {run.task && (
              <div className="mt-3 rounded-lg border border-stone-200 bg-white p-3 text-sm">
                <div className="text-xs font-semibold text-stone-500">PROPOSED TASK</div>
                <div className="font-medium">{run.task.title}</div>
                <div className="text-stone-700">{run.task.description}</div>
                <div className="mt-1 text-xs text-stone-600">{run.task.assignee} · due {run.task.due_date} · {run.task.priority} priority</div>
              </div>
            )}
            {run.order && (
              <div className="mt-2 rounded-lg border border-stone-200 bg-white p-3 text-sm">
                <div className="text-xs font-semibold text-stone-500">PROPOSED DRAFT ORDER (On hold)</div>
                {run.order.lines.map((l) => `${l.cartons} × ${l.product}`).join(', ')} · {bdt(run.order.total_bdt)}
              </div>
            )}
            {run.status === 'awaiting_approval' && (
              <div className="mt-4 flex gap-2">
                <button onClick={approve} className={btnPrimary}>Approve &amp; send (simulated)</button>
                <button onClick={discard} className={btnGhost}>Discard</button>
              </div>
            )}
            <p className="mt-2 text-xs text-stone-500">Nothing is sent, saved or ordered until you approve.</p>
          </Card>
        )}
        {run && traceDone && run.intent === 'no_action' && <Card><p className="text-sm">No action needed: this is not a customer request.</p></Card>}
        {done && <p className="rounded-lg border border-green-300 bg-green-50 p-3 text-sm" role="status">{done}</p>}
      </div>

      <Card title="Agent trace" className="h-fit">
        {!run && <p className="text-sm text-stone-500">Run the agent to see each step: understand, ERP tool calls, draft, task.</p>}
        <ol className="relative space-y-3 border-l border-stone-200 pl-4">
          {run?.trace.slice(0, shown).map((s) => (
            <li key={s.step} className="text-sm">
              <span className="absolute -left-2.5 rounded-full bg-white text-sm">{STEP_ICON[s.type] ?? '•'}</span>
              <div className="flex justify-between"><b>{s.name}</b><span className="text-xs text-stone-400">{s.ms ? `${s.ms} ms` : ''}</span></div>
              <div className="text-xs text-stone-500">{s.type.replace('_', ' ')}</div>
              {s.input != null && <pre className="mt-1 overflow-auto rounded bg-stone-50 p-1.5 text-[11px]">→ {JSON.stringify(s.input)}</pre>}
              {s.output != null && <pre className="mt-1 max-h-40 overflow-auto rounded bg-stone-50 p-1.5 text-[11px]">{typeof s.output === 'string' ? s.output : JSON.stringify(s.output, null, 1)}</pre>}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  )
}
