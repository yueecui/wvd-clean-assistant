export interface Settings {
  adb: string
  serial: string
  adb_resolved: string
  devices: string[]
  cpu_mode: string
}

/** 两个确认弹窗各自独立的过滤器笔记 */
export interface FilterNotes {
  /** 装备扫描 */
  scan: string
  /** 装备改造 */
  reform: string
}

export interface ScanStatus {
  running: boolean
  phase: 'idle' | 'start' | 'scanning' | 'stopping' | 'stopped' | 'done' | 'error'
  scanned: number
  current: string
  error: string | null
  /** 本次任务名：装备扫描 */
  task?: string
  /** 开始 / 结束时间（epoch 秒） */
  started_at?: number | null
  finished_at?: number | null
}

export type MatchStatus = 'ok' | 'alias' | 'fuzzy' | 'none'

export interface ReformStone {
  attr: string
  lo: number
  hi: number
  pct: boolean
  grade: number | null
  count: number
  text: string
  key: string
  /** 未扫描过素材、持有数量未知 */
  unscanned?: boolean
}

export interface StoneGridCell {
  grade: number
  lo: number
  hi: number
  key: string
}

export interface StoneGridRow {
  attr: string
  pct: boolean
  label: string
  cells: StoneGridCell[]
}

export interface ReformConfigSave {
  /** 需要改造的属性（勾选才改，无顺序） */
  reform_attrs: string[]
  stones: ReformStone[]
  max_try: number
}

export interface ReformConfig extends ReformConfigSave {
  /** 已持久化的素材扫描结果，刷新页面直接复用 */
  materials: ReformStone[]
  materials_at: number
  materials_mode: string
  /** 属性 × 1~5★ 的表格骨架，未扫描时也能选石头 */
  stone_grid: StoneGridRow[]
}

export interface ReformStatus {
  running: boolean
  phase: string
  total: number
  done: number
  current: string
  error: string | null
  /** 本次任务名：素材扫描 / 装备改造 */
  task?: string
  /** 开始 / 结束时间（epoch 秒） */
  started_at?: number | null
  finished_at?: number | null
}

export interface ReformResult {
  name: string
  stars: number
  blessing: string
  state: 'skip' | 'ok' | 'fail'
  note: string
}

export interface ReformSnap {
  status: ReformStatus
  logs: string[]
  results: ReformResult[]
}

export interface Candidate {
  name: string
  ratio: number
  id: number
  icon: string
  rank: number | null
}

export interface ScanItem {
  idx: number
  raw_name: string
  name: string
  reinforce: number
  stars: number
  blessings: string[]
  locked: boolean
  /** 品质色：white / green / blue / purple / red（识别不出为空串） */
  color: string
  equipment_id: number | null
  icon: string
  rank: number | null
  kind: number | null
  type_name: string
  part: string
  is_special: boolean
  match_status: MatchStatus
  candidates: Candidate[]
  score: number
  /** 可选：旧结果文件没有基础分字段 */
  base_score?: number
  attr_score: number
  combo_score: number
  hit_combos: string[]
  rule_id: string | null
  rule_name: string
  rank_in_id: number
}

export interface ScanSnap {
  status: ScanStatus
  items: ScanItem[]
  logs: string[]
  file?: string
}

export interface ResultFile {
  file: string
  title: string
  count: number
  mtime: number
}

export interface CatalogItem {
  name: string
  id: number
  icon: string
  rank: number | null
  part: string
  is_special: boolean
}

export interface CatalogResp {
  stats: { equipment: number; names: number; icons: number; master_dir: string; icon_dir: string }
  items: CatalogItem[]
}

export type ReinforceCond = 'lt20' | 'eq20'
export type TargetMode = 'types' | 'equipment'
export type RankOp = '>=' | '>' | '=' | '<' | '<='

/** 阶级条件：比较运算符 + 阶级数字，默认 >=0（不限制） */
export interface RankCond {
  op: RankOp
  value: number
}

export interface RuleTarget {
  reinforce: ReinforceCond
  rank: RankCond
  mode: TargetMode
  types: number[]
  equipment_ids: number[]
}

export interface Combo {
  attrs: string[]
  /** 满足其中几个属性就得分（≥2，≤ attrs.length） */
  need: number
  bonus: number
}

export interface ScoreRule {
  id: string
  name: string
  priority: number
  enabled: boolean
  note: string
  target: RuleTarget
  /** 命中目标装备条件即获得的基础分，默认 0 */
  base_score: number
  attr: Record<string, number>
  combos: Combo[]
}

export interface EquipType {
  id: number
  name: string
  part: number | null
  part_text: string
}

export interface AttrDef {
  key: string
  label: string
}

export interface AttrRow {
  base: string
  label: string
  key: string
  pct_key: string
}

export interface AttrGroups {
  flat: AttrDef[]
  pct: AttrDef[]
  custom: AttrDef[]
  rows?: AttrRow[]
}

export interface RulesResp {
  rules: ScoreRule[]
  attrs: string[]
  attr_groups: AttrGroups
  types: EquipType[]
}
