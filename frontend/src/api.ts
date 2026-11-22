/** Tiny fetch helpers. All routes live under /api (Vite proxies them in dev). */
async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const get = <T,>(path: string) => fetch(`/api${path}`).then((r) => handle<T>(r))

export const post = <T,>(path: string, body?: unknown) =>
  fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => handle<T>(r))

export const patch = <T,>(path: string, body: unknown) =>
  fetch(`/api${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r))

export type Distributor = {
  id: number; code: string; name: string; division: string; division_bn: string
  division_id: number; credit_limit_bdt: number; lang_pref: string
}
export type Alert = {
  type: 'stock' | 'credit'; severity: 'critical' | 'serious' | 'warning' | 'slow-moving'; message: string
  product_id?: number; product?: string; distributor_id: number; distributor_code: string
}
