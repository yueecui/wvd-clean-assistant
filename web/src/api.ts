import type {
  CatalogResp,
  FilterNotes,
  ReformConfig,
  ReformConfigSave,
  ReformSnap,
  ResultFile,
  RulesResp,
  ScanSnap,
  ScoreRule,
  Settings,
} from './types'

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}`)
  return (await r.json()) as T
}

async function postJson<T>(path: string, body: unknown = {}): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const j = (await r.json()) as T & { error?: string }
  if (!r.ok) throw new Error(j?.error || `${path} -> HTTP ${r.status}`)
  return j
}

export const getSettings = () => getJson<Settings>('/api/settings')
export const saveSettings = (adb: string, serial: string) =>
  postJson<{ ok: boolean }>('/api/settings', { adb, serial })
export const setCpuMode = (mode: string) =>
  postJson<{ ok: boolean }>('/api/settings', { cpu_mode: mode })

export const pickAdb = () => postJson<{ ok: boolean; path: string }>('/api/pick-adb', {})

export const getFilterNotes = () => getJson<{ notes: FilterNotes }>('/api/filter-notes')
export const saveFilterNotes = (key: keyof FilterNotes, text: string) =>
  postJson<{ ok: boolean; notes: FilterNotes }>('/api/filter-notes', { key, text })

export const getScan = () => getJson<ScanSnap>('/api/scan/status')
export type ScanMode = 'new' | 'append'
export const startScan = (mode: ScanMode = 'new') =>
  postJson<{ ok: boolean; error?: string }>('/api/scan/start', { mode })
export const stopScan = () => postJson<{ ok: boolean }>('/api/scan/stop')
export const saveScan = () => postJson<{ ok: boolean; count: number }>('/api/scan/save')
export const clearScan = () => postJson<{ ok: boolean }>('/api/clear')

export const listResults = () => getJson<{ files: ResultFile[]; current: string }>('/api/results/list')
export const openResultsDir = () =>
  postJson<{ ok: boolean; dir: string; error?: string }>('/api/results/open-dir', {})
export const openResult = (file: string) =>
  postJson<{ ok: boolean; current: string; items: ScanSnap['items'] }>('/api/results/open', { file })

export const getCatalog = () => getJson<CatalogResp>('/api/catalog')
export const getAliases = () => getJson<{ aliases: Record<string, string> }>('/api/aliases')
export const saveAlias = (raw: string, target: string) =>
  postJson<{ ok: boolean; aliases: Record<string, string>; updated: number }>('/api/alias', { raw, target })
export const deleteAlias = (raw: string) =>
  postJson<{ ok: boolean; aliases: Record<string, string> }>('/api/alias/delete', { raw })

export const iconUrl = (icon: string) => (icon ? `/api/icons/${encodeURIComponent(icon)}` : '')

export const getRules = () => getJson<RulesResp>('/api/rules')
export const saveRule = (rule: ScoreRule) =>
  postJson<{ ok: boolean; rule: ScoreRule; rules: ScoreRule[] }>('/api/rules/save', { rule })
export const deleteRule = (id: string) =>
  postJson<{ ok: boolean; rules: ScoreRule[] }>('/api/rules/delete', { id })
export const importRules = (rule: ScoreRule | ScoreRule[]) =>
  postJson<{ ok: boolean; saved: ScoreRule[]; rules: ScoreRule[] }>('/api/rules/import', { rule })
export const rescore = () => postJson<{ ok: boolean; updated: number }>('/api/rules/rescore', {})
export const ruleFileUrl = (id: string) => `/api/rules/${encodeURIComponent(id)}.json`
export const openRulesDir = () => postJson<{ ok: boolean; dir: string }>('/api/rules/open', {})

export const getReformConfig = () => getJson<ReformConfig>('/api/reform/config')
export const saveReformConfig = (cfg: ReformConfigSave) =>
  postJson<ReformConfig>('/api/reform/config', cfg)
export type ReformScanMode = 'full' | 'flat'
export const scanReformMaterials = (mode: ReformScanMode = 'full') =>
  postJson<{ ok: boolean; error?: string }>('/api/reform/materials', { mode })
export const getReformStatus = () => getJson<ReformSnap>('/api/reform/status')
export const startReform = (cfg: ReformConfigSave) =>
  postJson<{ ok: boolean; error?: string }>('/api/reform/start', cfg)
export const stopReform = () => postJson<{ ok: boolean }>('/api/reform/stop', {})

