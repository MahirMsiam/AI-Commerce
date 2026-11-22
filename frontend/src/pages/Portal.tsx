import { useEffect, useMemo, useState } from 'react'
import { get, post } from '../api'
import { Card, Modal, StatusChip, btnGhost, btnPrimary } from '../components/ui'
import { bdt, num, shortDate } from '../format'
import { t } from '../i18n'
import { useApp } from '../state'

type Product = { id: number; name: string; name_bn: string; category: string; pack: string; price_per_carton_bdt: number; cartons_on_hand: number | null; is_rx_restricted: number }
type SuggestLine = { product_id: number; product: string; cartons: number; reason: string; price_per_carton_bdt: number }
type Order = { id: number; created_at: string; status: string; total_bdt: number; lines: number; source: string }
type CreditWarning = { credit_limit_bdt: number; outstanding_bdt: number; overdue_bdt: number; order_total_bdt: number; projected_bdt: number; over_by_bdt: number }

export default function Portal() {
  const { distributor, lang, resetKey } = useApp()
  const [products, setProducts] = useState<Product[]>([])
  const [suggest, setSuggest] = useState<SuggestLine[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [cart, setCart] = useState<Record<number, number>>({})
  const [fromSuggestion, setFromSuggestion] = useState(false)
  const [showSuggest, setShowSuggest] = useState(false)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('All')
  const [warning, setWarning] = useState<CreditWarning | null>(null)
  const [placed, setPlaced] = useState<{ id: number; status: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const did = distributor?.id
  const reload = () => {
    if (!did) return
    get<Product[]>(`/products?distributor_id=${did}`).then(setProducts)
    get<{ lines: SuggestLine[] }>(`/distributors/${did}/suggested-order`).then((r) => setSuggest(r.lines))
    get<Order[]>(`/orders?distributor_id=${did}&limit=15`).then(setOrders)
  }
  useEffect(() => {
    setCart({}); setWarning(null); setPlaced(null); reload()
  }, [did, resetKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const byId = useMemo(() => Object.fromEntries(products.map((p) => [p.id, p])), [products])
  const categories = ['All', ...new Set(products.map((p) => p.category))]
  const shown = products.filter((p) => (category === 'All' || p.category === category) &&
    (p.name + p.name_bn).toLowerCase().includes(search.toLowerCase()))
  const cartLines = Object.entries(cart).filter(([, c]) => c > 0).map(([id, c]) => ({ product_id: Number(id), cartons: c }))
  const total = cartLines.reduce((s, l) => s + (byId[l.product_id]?.price_per_carton_bdt ?? 0) * l.cartons, 0)

  const submit = async (onHold = false) => {
    if (!did || !cartLines.length) return
    setBusy(true)
    try {
      const r = await post<{ order?: { id: number; status: string }; credit_warning?: CreditWarning }>('/orders', {
        distributor_id: did, lines: cartLines, submit_on_hold: onHold, source: fromSuggestion ? 'ai_suggested' : 'portal',
      })
      if (r.credit_warning) { setWarning(r.credit_warning); return }
      setPlaced(r.order!); setWarning(null); setCart({}); setFromSuggestion(false); reload()
    } finally { setBusy(false) }
  }

  if (!distributor) return <p className="text-stone-600">Pick a distributor in the top bar.</p>

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
      <div className="space-y-4">
        {suggest.length > 0 && (
          <button onClick={() => setShowSuggest(true)}
            className="flex w-full items-center justify-between rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-left hover:bg-blue-100">
            <span><span className="mr-2">✨</span><b>AI suggested order ready</b> · {suggest.length} products based on your demand forecast</span>
            <span className="text-sm font-medium text-blue-800">Review →</span>
          </button>
        )}

        <Card title={t(lang, 'Catalogue')}>
          <div className="mb-3 flex flex-wrap gap-2">
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search products…" aria-label="Search products"
              className="min-w-48 flex-1 rounded-lg border border-stone-300 px-3 py-1.5 text-sm" />
            <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category"
              className="rounded-lg border border-stone-300 px-2 py-1.5 text-sm">
              {categories.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {shown.map((p) => (
              <div key={p.id} className="flex flex-col rounded-lg border border-stone-200 bg-white p-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-medium">{lang === 'bn' ? p.name_bn : p.name}</div>
                    <div className="text-xs text-stone-500">{p.category} · {p.pack}</div>
                  </div>
                  {p.is_rx_restricted ? <span className="rounded bg-rose-50 px-1.5 py-0.5 text-[11px] font-medium text-rose-800">Restricted</span> : null}
                </div>
                <div className="mt-2 text-sm">{bdt(p.price_per_carton_bdt)} <span className="text-stone-500">/ carton</span></div>
                <div className="mt-1 text-xs text-stone-600">Your stock: <b>{p.cartons_on_hand ?? 0}</b> cartons</div>
                <div className="mt-3 flex items-center gap-2">
                  <input type="number" min={0} value={cart[p.id] ?? ''} placeholder="0" aria-label={`Cartons of ${p.name}`}
                    onChange={(e) => setCart({ ...cart, [p.id]: Math.max(0, Number(e.target.value)) })}
                    className="w-20 rounded border border-stone-300 px-2 py-1 text-sm" />
                  <span className="text-xs text-stone-500">cartons</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title={t(lang, 'Order history')}>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-stone-500"><th className="py-1">Order</th><th>Date</th><th>Lines</th><th>Total</th><th>Source</th><th>Status</th></tr></thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id} className="border-t border-stone-100">
                  <td className="py-1.5 font-medium">#{o.id}</td><td>{shortDate(o.created_at)}</td><td>{o.lines}</td>
                  <td>{bdt(o.total_bdt)}</td><td className="text-xs text-stone-600">{o.source.replace('_', ' ')}</td><td><StatusChip status={o.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <aside className="h-fit space-y-3 rounded-xl border border-stone-200 bg-white p-4 xl:sticky xl:top-4">
        <h2 className="font-semibold">{t(lang, 'Cart')}</h2>
        {cartLines.length === 0 && <p className="text-sm text-stone-500">Empty. Add cartons from the catalogue or the AI suggestion.</p>}
        {cartLines.map((l) => (
          <div key={l.product_id} className="flex justify-between text-sm">
            <span>{num(l.cartons)} × {byId[l.product_id]?.name}</span>
            <span>{bdt(l.cartons * (byId[l.product_id]?.price_per_carton_bdt ?? 0))}</span>
          </div>
        ))}
        <div className="flex justify-between border-t pt-2 font-semibold"><span>Total</span><span>{bdt(total)}</span></div>
        <button disabled={!cartLines.length || busy} onClick={() => submit()} className={`${btnPrimary} w-full`}>Submit order</button>

        {warning && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm" role="alert">
            <div className="font-semibold text-amber-900">⚠ Credit warning</div>
            <dl className="mt-2 grid grid-cols-2 gap-y-1">
              <dt>Credit limit</dt><dd className="text-right">{bdt(warning.credit_limit_bdt)}</dd>
              <dt>Outstanding</dt><dd className="text-right">{bdt(warning.outstanding_bdt)}</dd>
              <dt>Overdue</dt><dd className="text-right">{bdt(warning.overdue_bdt)}</dd>
              <dt>This order</dt><dd className="text-right">{bdt(warning.order_total_bdt)}</dd>
              <dt className="font-semibold">Over limit by</dt><dd className="text-right font-semibold">{bdt(warning.over_by_bdt)}</dd>
            </dl>
            <p className="mt-2 text-amber-900">Please clear {bdt(warning.overdue_bdt)} overdue, or submit for credit approval.</p>
            <button disabled={busy} onClick={() => submit(true)} className={`${btnGhost} mt-2 w-full`}>Submit for approval (On hold)</button>
          </div>
        )}
        {placed && (
          <div className="rounded-lg border border-green-300 bg-green-50 p-3 text-sm" role="status">
            Order <b>#{placed.id}</b> created · <StatusChip status={placed.status} />
          </div>
        )}
      </aside>

      {showSuggest && (
        <SuggestModal lines={suggest} onClose={() => setShowSuggest(false)} onAdd={(q) => {
          setCart({ ...cart, ...q }); setFromSuggestion(true); setShowSuggest(false); setPlaced(null)
        }} />
      )}
    </div>
  )
}

function SuggestModal({ lines, onClose, onAdd }: { lines: SuggestLine[]; onClose: () => void; onAdd: (q: Record<number, number>) => void }) {
  const [qty, setQty] = useState<Record<number, number>>(Object.fromEntries(lines.map((l) => [l.product_id, l.cartons])))
  return (
    <Modal title="AI suggested order" onClose={onClose} wide>
      <p className="mb-3 text-sm text-stone-600">Based on your sales history, a demand forecast for the next 2 weeks, your stock on hand and a safety buffer.</p>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-stone-500"><th className="py-1">Product</th><th>Why</th><th className="w-24">Cartons</th></tr></thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.product_id} className="border-t border-stone-100 align-top">
              <td className="py-2 font-medium">{l.product}</td>
              <td className="py-2 pr-3 text-stone-700">{l.reason}</td>
              <td className="py-2"><input type="number" min={0} value={qty[l.product_id]} aria-label={`Cartons of ${l.product}`}
                onChange={(e) => setQty({ ...qty, [l.product_id]: Math.max(0, Number(e.target.value)) })}
                className="w-20 rounded border border-stone-300 px-2 py-1" /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} className={btnGhost}>Cancel</button>
        <button onClick={() => onAdd(qty)} className={btnPrimary}>Add all to cart</button>
      </div>
    </Modal>
  )
}
