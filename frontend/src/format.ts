/** Money in lakh/crore with ৳ (Plan.md §10). */
export function bdt(n: number | null | undefined): string {
  if (n == null) return '–'
  const a = Math.abs(n)
  if (a >= 1e7) return `৳ ${(n / 1e7).toFixed(2)} crore`
  if (a >= 1e5) return `৳ ${(n / 1e5).toFixed(1)} lakh`
  return `৳ ${Math.round(n).toLocaleString('en-IN')}`
}

export const num = (n: number) => Math.round(n).toLocaleString('en-IN')

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
