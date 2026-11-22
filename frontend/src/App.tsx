import { useEffect, useState } from 'react'
import { HashRouter, NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { get, post, type Distributor } from './api'
import { btnGhost } from './components/ui'
import { t, type Lang } from './i18n'
import Agent from './pages/Agent'
import Architecture from './pages/Architecture'
import Ask from './pages/Ask'
import Dashboard from './pages/Dashboard'
import Portal from './pages/Portal'
import Tasks from './pages/Tasks'
import { AppCtx, type AppState } from './state'

const NAV = [
  ['/portal', 'Portal'], ['/dashboard', 'Dashboard'], ['/ask', 'Ask'], ['/agent', 'Agent Inbox'], ['/tasks', 'Tasks'], ['/architecture', 'Architecture'],
] as const

function Shell() {
  const navigate = useNavigate()
  const [distributors, setDistributors] = useState<Distributor[]>([])
  const [state, setState] = useState<AppState>({ role: 'manager', distributor: null, lang: 'en', resetKey: 0 })
  const [ollama, setOllama] = useState(false)
  const [offline, setOffline] = useState(false)
  const [resetting, setResetting] = useState(false)
  const { lang, role } = state

  useEffect(() => {
    get<Distributor[]>('/distributors').then((d) => {
      setDistributors(d)
      setState((s) => ({ ...s, distributor: s.distributor ?? d.find((x) => x.code === 'RNG-01') ?? d[0] }))
    })
  }, [state.resetKey])
  useEffect(() => {
    const check = () => get<{ ollama: string }>('/health')
      .then((h) => { setOllama(h.ollama === 'ok'); setOffline(false) })
      .catch(() => { setOllama(false); setOffline(true) })
    check()
    const id = setInterval(check, 15_000)
    return () => clearInterval(id)
  }, [])

  const setRole = (r: AppState['role']) => { setState({ ...state, role: r }); navigate(r === 'manager' ? '/dashboard' : '/portal') }
  const reset = async () => {
    if (!confirm('Reset all demo data?')) return
    setResetting(true)
    try { await post('/admin/reset'); setState((s) => ({ ...s, resetKey: s.resetKey + 1 })) } finally { setResetting(false) }
  }

  return (
    <AppCtx.Provider value={state}>
      <div className="flex min-h-screen bg-[#f9f9f7] text-stone-900">
        <nav className="w-52 shrink-0 border-r border-stone-200 bg-white p-4" aria-label="Main">
          <div className="mb-6 text-sm font-semibold leading-tight">AI Commerce &amp; Insights<div className="font-normal text-stone-500">Prototype</div></div>
          <ul className="space-y-1">
            {NAV.map(([to, label]) => (
              <li key={to}><NavLink to={to} className={({ isActive }) => `block rounded-lg px-3 py-2 text-sm ${isActive ? 'bg-blue-50 font-medium text-blue-800' : 'text-stone-700 hover:bg-stone-50'}`}>{t(lang, label)}</NavLink></li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 flex-1">
          <header className="flex flex-wrap items-center gap-3 border-b border-stone-200 bg-white px-5 py-3">
            <div className="flex rounded-lg border border-stone-300 p-0.5 text-sm" role="group" aria-label="Role">
              {(['distributor', 'manager'] as const).map((r) => (
                <button key={r} onClick={() => setRole(r)} aria-pressed={role === r}
                  className={`rounded-md px-3 py-1 ${role === r ? 'bg-stone-900 text-white' : 'text-stone-700'}`}>{t(lang, r === 'manager' ? 'Manager' : 'Distributor')}</button>
              ))}
            </div>
            {role === 'distributor' && (
              <select aria-label="Distributor" value={state.distributor?.id ?? ''} className="rounded-lg border border-stone-300 px-2 py-1 text-sm"
                onChange={(e) => setState({ ...state, distributor: distributors.find((d) => d.id === Number(e.target.value)) ?? null })}>
                {distributors.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.code})</option>)}
              </select>
            )}
            <div className="ml-auto flex items-center gap-3">
              <span className="rounded bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-900">{t(lang, 'Prototype · sample data')}</span>
              <span className="flex items-center gap-1.5 text-xs text-stone-700" title={ollama ? 'Ollama is running on this machine' : 'Ollama not reachable: rule-based engine answers'}>
                <span className={`h-2.5 w-2.5 rounded-full ${ollama ? 'bg-green-600' : 'bg-stone-400'}`} />{t(lang, ollama ? 'Local AI on' : 'Rules mode')}
              </span>
              <button onClick={() => setState({ ...state, lang: (lang === 'en' ? 'bn' : 'en') as Lang })} className={btnGhost} aria-label="Toggle language">
                {lang === 'en' ? 'বাংলা' : 'EN'}
              </button>
              <button onClick={reset} disabled={resetting} className={btnGhost}>{resetting ? '…' : t(lang, 'Reset demo')}</button>
            </div>
          </header>
          <main className="p-5">
            {offline && <p role="alert" className="mb-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">Backend not reachable. Start it with run.ps1 (or run.sh) and reload.</p>}
            <Routes>
              <Route path="/portal" element={<Portal />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/ask" element={<Ask />} />
              <Route path="/agent" element={<Agent />} />
              <Route path="/tasks" element={<Tasks />} />
              <Route path="/architecture" element={<Architecture />} />
              <Route path="*" element={<Navigate to="/dashboard" />} />
            </Routes>
          </main>
        </div>
      </div>
    </AppCtx.Provider>
  )
}

export default function App() {
  return <HashRouter><Shell /></HashRouter>
}
