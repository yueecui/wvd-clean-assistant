export interface Settings {
  adb: string
  serial: string
  adb_resolved: string
  devices: string[]
  cpu_mode: string
  /** 截图/OCR 流水线队列上限（1~8） */
  ocr_queue: number
}

/** 各确认弹窗独立的过滤器笔记 */
export interface FilterNotes {
  /** 装备扫描 */
  scan: string
  /** 强化白装 */
  enhance: string
  /** 装备改造 */
  reform: string
  /** 自动提炼 */
  refine: string
  /** 自动出售 */
  sell: string
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
  /** 累计运行秒数（停着的时间不算），运行中不含当前这一轮 */
  elapsed?: number
  /** 本轮开始时间（只有运行中有值） */
  run_started_at?: number | null
  /** 结束后：本次新增的平均每件秒数（没有新增时为 null） */
  per_item?: number | null
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
  /** 素材定位方式：slider=拖右侧滚动条跳转，scroll=逐页滚动（老方案） */
  materials_jump?: 'slider' | 'scroll'
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

/** log/ 下的一份自动任务日志 */
export interface LogFile {
  file: string
  title: string
  /** 已完成批次数 */
  batches: number
  mtime: number
  started_at?: number | null
  finished_at?: number | null
  /** 累计运行秒数（老日志没有这个字段） */
  elapsed?: number | null
}

export interface RefineStatus {
  running: boolean
  phase: string
  /** 已执行的批次数（每批最多 100 件） */
  batch: number
  /** 已参与提炼的装备数（= Σ 结果面板的 成功/总数 的总数） */
  items: number
  /** 提炼成功数 */
  success: number
  /** 累计挖到的下级全改造石 */
  lower: number
  /** 累计挖到的全改造石 */
  full: number
  current: string
  error: string | null
  task?: string
  started_at?: number | null
  finished_at?: number | null
  /** 累计运行秒数（停着的时间不算），运行中不含当前这一轮 */
  elapsed?: number
  /** 本轮开始时间（只有运行中有值） */
  run_started_at?: number | null
  /** 当前日志文件名（log/ 下的文件名） */
  log_file?: string
}

/** 单批提炼结果 */
export interface RefineBatch {
  batch: number
  success: number
  total: number
  /** 本批挖到的下级全改造石 / 全改造石（旧数据没有，按 0 兜底） */
  lower?: number
  full?: number
  at: number
}

export interface RefineSnap {
  status: RefineStatus
  logs: string[]
  results: RefineBatch[]
}

export interface SellStatus {
  running: boolean
  phase: string
  /** 已执行的批次数（每批最多 300 种） */
  batch: number
  /** 累计获得金币 */
  gold: number
  current: string
  error: string | null
  task?: string
  started_at?: number | null
  finished_at?: number | null
  /** 累计运行秒数（停着的时间不算），运行中不含当前这一轮 */
  elapsed?: number
  /** 本轮开始时间（只有运行中有值） */
  run_started_at?: number | null
  /** 当前日志文件名（log/ 下的文件名） */
  log_file?: string
}

/** 单批出售结果（gold 为读不到时的 0） */
export interface SellBatch {
  batch: number
  gold: number
  at: number
}

export interface SellSnap {
  status: SellStatus
  logs: string[]
  results: SellBatch[]
}

/** 强化白装（白装 4~5★ 全强化到 +5） */
export interface EnhanceStatus {
  running: boolean
  phase: string
  /** 已强化到 +5 的件数 */
  done: number
  /** 失败的件数 */
  failed: number
  /** 跳过（已是绿装 / 已满）的件数 */
  skipped: number
  current: string
  error: string | null
  task?: string
  started_at?: number | null
  finished_at?: number | null
  /** 累计运行秒数（停着的时间不算） */
  elapsed?: number
  /** 本轮开始时间（只有运行中有值） */
  run_started_at?: number | null
}

/** 单件强化结果 */
export interface EnhanceItem {
  name: string
  stars: number
  /** 强化前 / 强化后的强化值 */
  before: number
  after: number
  at: number
}

export interface EnhanceSnap {
  status: EnhanceStatus
  logs: string[]
  results: EnhanceItem[]
}

export interface Candidate {
  name: string
  ratio: number
  id: number
  icon: string
  rank: number | null
}

/** 单条加护的计分明细（数值 × 权重 = 分） */
export interface AttrDetail {
  text: string
  /** 评分用的键：固定值『攻击力』/ 百分比『攻击力%』 */
  key: string
  value: number
  weight: number
  pts: number
  /** 该词条属于本次命中组合的需求项（浮层里高亮） */
  combo: boolean
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
  /** 可选：旧结果文件没有阶级分字段 */
  rank_score?: number
  /** 可选：旧结果文件没有星级分字段 */
  star_score?: number
  attr_score: number
  combo_score: number
  hit_combos: string[]
  /** 可选：旧结果文件没有逐条明细 */
  attr_details?: AttrDetail[]
  rule_id: string | null
  rule_name: string
  /** 规则颜色 #rrggbb，空 = 默认灰 */
  rule_color?: string
  /** 手工分组标记：可同时属于 1~3 组 */
  marks?: string[]
  /** √ = 已处理（点 √ 会清掉 1~3 组） */
  done?: boolean
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
  /** 星级条件：比较运算符 + 星级数字（1~5），默认 >=1（不限制） */
  stars: RankCond
  /** 品质色条件：1=白 2=绿 3=蓝 4=紫 5=红，默认 >=1（不限制） */
  color: RankCond
  mode: TargetMode
  types: number[]
  equipment_ids: number[]
  /** 必有属性：全部命中才算命中这条规则；空数组 = 不限制 */
  attrs: string[]
  /** 可选属性：从中至少命中 attr_need 个；空数组 = 不限制 */
  attrs_opt: string[]
  /** 可选属性至少命中几个（1 ~ min(可选属性数, 4)） */
  attr_need: number
}

export interface Combo {
  attrs: string[]
  /** 阶梯分：键为满足个数（2 ~ min(属性数, 4)），取实际满足个数可达的最高档 */
  tiers: Record<string, number>
}

export interface ScoreRule {
  id: string
  name: string
  priority: number
  enabled: boolean
  note: string
  /** 规则颜色 #rrggbb：规则名在列表 / 结果 / hover 里都按它上色，空 = 默认灰 */
  color?: string
  target: RuleTarget
  /** 命中目标装备条件即获得的基础分，默认 0 */
  base_score: number
  attr: Record<string, number>
  combos: Combo[]
  /** 阶级分：{阶级(0~6): 分数}，命中规则后按装备阶级加 */
  rank_scores?: Record<string, number>
  /** 星级分：{星级(1~5): 分数}，命中规则后按装备星级加 */
  star_scores?: Record<string, number>
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

export interface UpdateStatus {
  running: boolean
  phase: string
  message: string
  done: number
  total: number
  error: string | null
}

export interface UpdateInfo {
  checked_at: number
  /** 本次数据来自远端 manifest 还是本地基线 */
  source: string
  local_app: string
  local_resource: string
  remote_app: string
  remote_resource: string
  app_available: boolean
  resource_available: boolean
  to_add: string[]
  to_update: string[]
  notes: string
  asset: string
  error?: string
}

export interface UpdateSnapshot {
  status: UpdateStatus
  info: UpdateInfo
  app_version: string
  state: { resource_version?: string; resources_at?: number }
  manifest: string
}

/** 启动时静默探测结果：失败也返回 ok=false，一律不打扰用户 */
export interface SilentCheck {
  ok: boolean
  available: boolean
  remote: string
  local: string
  notes: string
  source: string
}
