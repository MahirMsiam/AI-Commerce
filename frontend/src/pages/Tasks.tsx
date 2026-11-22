import { useEffect, useState } from 'react'
import { get, patch } from '../api'
import { useApp } from '../state'

type Task = { id: number; title: string; description: string; assignee: string; due_date: string; priority: string; status: string; created_by: string }
const COLS = ['To do', 'In progress', 'Done']
const PRIO: Record<string, string> = { high: 'text-red-700', medium: 'text-amber-800', low: 'text-stone-600' }

// shortcut: move buttons instead of drag-and-drop (Plan.md §13 cut list item 1).
export default function Tasks() {
  const { resetKey } = useApp()
  const [tasks, setTasks] = useState<Task[]>([])
  const load = () => get<Task[]>('/tasks').then(setTasks)
  useEffect(() => { load() }, [resetKey])
  const move = async (t: Task, dir: number) => { await patch(`/tasks/${t.id}`, { status: COLS[COLS.indexOf(t.status) + dir] }); load() }

  return (
    <div className="grid gap-4 md:grid-cols-3">
      {COLS.map((col, ci) => (
        <section key={col} className="rounded-xl bg-stone-100 p-3">
          <h2 className="mb-3 text-sm font-semibold">{col} <span className="text-stone-500">{tasks.filter((t) => t.status === col).length}</span></h2>
          <ul className="space-y-2">
            {tasks.filter((t) => t.status === col).map((t) => (
              <li key={t.id} className="rounded-lg border border-stone-200 bg-white p-3 text-sm">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium">{t.title}</span>
                  {t.created_by === 'agent' && <span className="shrink-0 rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-800">🤖 Agent</span>}
                </div>
                <p className="mt-1 text-stone-700">{t.description}</p>
                <div className="mt-2 flex items-center justify-between text-xs text-stone-600">
                  <span>{t.assignee} · due {t.due_date} · <span className={PRIO[t.priority]}>{t.priority}</span></span>
                  <span className="flex gap-1">
                    {ci > 0 && <button onClick={() => move(t, -1)} aria-label="Move left" className="rounded border px-1.5 hover:bg-stone-50">←</button>}
                    {ci < 2 && <button onClick={() => move(t, 1)} aria-label="Move right" className="rounded border px-1.5 hover:bg-stone-50">→</button>}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
