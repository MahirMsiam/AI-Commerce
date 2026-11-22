import type { ReactNode } from 'react'

export function Card({ title, children, className = '' }: { title?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-stone-200 bg-[#fcfcfb] p-4 ${className}`}>
      {title && <h2 className="mb-3 text-sm font-semibold text-stone-700">{title}</h2>}
      {children}
    </section>
  )
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}
        className={`max-h-[90vh] w-full overflow-auto rounded-xl bg-white p-5 shadow-xl ${wide ? 'max-w-4xl' : 'max-w-2xl'}`}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded px-2 text-xl text-stone-500 hover:bg-stone-100">×</button>
        </div>
        {children}
      </div>
    </div>
  )
}

const STATUS_STYLE: Record<string, string> = {
  Placed: 'bg-blue-50 text-blue-800', Approved: 'bg-teal-50 text-teal-800', Dispatched: 'bg-violet-50 text-violet-800',
  Delivered: 'bg-green-50 text-green-800', 'On hold': 'bg-amber-50 text-amber-900',
}

export const StatusChip = ({ status }: { status: string }) => (
  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status] ?? 'bg-stone-100 text-stone-700'}`}>{status}</span>
)

/** Status colours are reserved for alerts and always come with an icon + label. */
export const SEVERITY: Record<string, { color: string; icon: string; label: string }> = {
  critical: { color: '#d03b3b', icon: '⛔', label: 'Critical' },
  serious: { color: '#ec835a', icon: '▲', label: 'Serious' },
  warning: { color: '#fab219', icon: '●', label: 'Warning' },
  'slow-moving': { color: '#52514e', icon: '◆', label: 'Slow-moving' },
}

export function SeverityBadge({ severity }: { severity: string }) {
  const s = SEVERITY[severity]
  return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-stone-800">
      <span style={{ color: s.color }} aria-hidden>{s.icon}</span>{s.label}
    </span>
  )
}

export function Kpi({ label, value, sub }: { label: string; value: string; sub?: ReactNode }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-[#fcfcfb] p-4">
      <div className="text-xs text-stone-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-stone-900">{value}</div>
      {sub && <div className="mt-1 text-xs text-stone-600">{sub}</div>}
    </div>
  )
}

export const Spinner = ({ label }: { label: string }) => (
  <div className="flex items-center gap-2 text-sm text-stone-600" role="status">
    <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-300 border-t-blue-600" />{label}
  </div>
)

export const btn = 'rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50'
export const btnPrimary = `${btn} bg-[#2a78d6] text-white hover:bg-[#256abf]`
export const btnGhost = `${btn} border border-stone-300 bg-white text-stone-800 hover:bg-stone-50`
