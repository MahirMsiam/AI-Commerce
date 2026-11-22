import { createContext, useContext } from 'react'
import type { Distributor } from './api'
import type { Lang } from './i18n'

export type AppState = {
  role: 'distributor' | 'manager'
  distributor: Distributor | null
  lang: Lang
  resetKey: number // bumps after "Reset demo" so pages refetch
}

export const AppCtx = createContext<AppState>({ role: 'manager', distributor: null, lang: 'en', resetKey: 0 })
export const useApp = () => useContext(AppCtx)
