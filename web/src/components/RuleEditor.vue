<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ATTR_ROWS } from '@/attrs'
import EquipIcon from '@/components/EquipIcon.vue'
import { partRank } from '@/parts'
import { QUALITY_LEVELS, qualityLabel } from '@/quality'
import { DEFAULT_RULE_COLOR, RULE_COLORS } from '@/rule-colors'
import type { AttrGroups, AttrRow, CatalogItem, EquipType, RankOp, RuleTarget, ScoreRule } from '@/types'

const props = defineProps<{
  rule: ScoreRule
  types: EquipType[]
  attrs: string[]
  attrGroups: AttrGroups
  catalog: CatalogItem[]
  isNew: boolean
  /** 全项目里其他规则用过的非预设颜色，方便一键复用 */
  extraColors?: string[]
}>()

const emit = defineEmits<{
  (e: 'save', rule: ScoreRule): void
  (e: 'cancel'): void
}>()

const BLANK_TARGET: RuleTarget = {
  reinforce: 'lt20',
  rank: { op: '>=', value: 0 },
  stars: { op: '>=', value: 1 },
  color: { op: '>=', value: 1 },
  mode: 'types',
  types: [],
  equipment_ids: [],
  attrs: [],
  attrs_opt: [],
  attr_need: 1,
}

/** 老数据可能没有阶级 / 星级 / 目标属性条件，统一补成默认值 */
function withRank(r: ScoreRule): ScoreRule {
  const copy = JSON.parse(JSON.stringify(r)) as ScoreRule
  if (!copy.target) copy.target = JSON.parse(JSON.stringify(BLANK_TARGET)) as RuleTarget
  if (!copy.target.rank) copy.target.rank = { op: '>=', value: 0 }
  if (!copy.target.stars) copy.target.stars = { op: '>=', value: 1 }
  if (!copy.target.color) copy.target.color = { op: '>=', value: 1 }
  if (!Array.isArray(copy.target.attrs)) copy.target.attrs = []
  if (!Array.isArray(copy.target.attrs_opt)) {
    // 老规则只有一段「从这些属性里至少命中 N 个」，语义就等于可选属性
    copy.target.attrs_opt = copy.target.attrs.slice()
    copy.target.attrs = []
  }
  if (!copy.target.attr_need) copy.target.attr_need = 1
  if (typeof copy.color !== 'string' || !copy.color) copy.color = DEFAULT_RULE_COLOR
  if (!copy.rank_scores || typeof copy.rank_scores !== 'object') copy.rank_scores = {}
  if (!copy.star_scores || typeof copy.star_scores !== 'object') copy.star_scores = {}
  return copy
}

const draft = reactive<ScoreRule>(withRank(props.rule))
const equipQuery = ref('')

const RANK_OPS: { op: RankOp; label: string }[] = [
  { op: '>=', label: '≥' },
  { op: '>', label: '>' },
  { op: '=', label: '=' },
  { op: '<', label: '<' },
  { op: '<=', label: '≤' },
]

// 规则名 = 文件名，非法文件名字符不允许输入
const ILLEGAL_NAME = /[\\/:*?"<>|\u0000-\u001f]/g
const nameError = computed(() => {
  const s = (draft.name || '').trim()
  if (!s) return '规则名称不能为空'
  if (/[\\/:*?"<>|]/.test(s)) return '不能包含 \\ / : * ? " < > |'
  return ''
})

function onNameInput(e: Event) {
  const el = e.target as HTMLInputElement
  const cleaned = el.value.replace(ILLEGAL_NAME, '')
  if (cleaned !== el.value) el.value = cleaned
  draft.name = cleaned
}

watch(
  () => props.rule,
  (r) => {
    Object.assign(draft, withRank(r))
    equipQuery.value = ''
  },
)

// 属性全表：固定值 / 百分比分开，key 即评分权重键（百分比带 % 后缀）
const groups = computed<AttrGroups>(() => ({
  flat: props.attrGroups?.flat || [],
  pct: props.attrGroups?.pct || [],
  custom: props.attrGroups?.custom || [],
}))

// 权重区：每个属性一张卡，固定值/百分比成对排列；顺序沿用 masterdata 表
const weightRows = computed<AttrRow[]>(() => {
  const fromApi = props.attrGroups?.rows
  if (fromApi?.length) return fromApi
  const fromTable = ATTR_ROWS
  if (fromTable.length) return fromTable
  // 最后兜底：known_attrs
  const set = new Set(props.attrs)
  const out: AttrRow[] = []
  const done = new Set<string>()
  for (const k of props.attrs) {
    if (k.endsWith('%') || done.has(k)) continue
    done.add(k)
    out.push({ base: k, label: k, key: k, pct_key: set.has(k + '%') ? k + '%' : '' })
  }
  return out
})

const knownKeys = computed(() => {
  const s = new Set<string>()
  for (const r of weightRows.value) {
    if (r.key) s.add(r.key)
    if (r.pct_key) s.add(r.pct_key)
  }
  for (const a of groups.value.custom) s.add(a.key)
  return s
})

const allFlatKeys = computed(() => weightRows.value.map((r) => r.key).filter(Boolean))
const allPctKeys = computed(() => weightRows.value.map((r) => r.pct_key).filter(Boolean))

// 自定义属性 = 全表里的自定义项 + 规则里已存在但全表没有的
const customRows = computed(() => {
  const out = groups.value.custom.map((a) => a.key)
  for (const k of Object.keys(draft.attr)) {
    if (k && !knownKeys.value.has(k) && !out.includes(k)) out.push(k)
  }
  return out
})

// 组合里可选属性（分组）
const comboGroups = computed(() => {
  const out = [
    { label: '固定值', list: allFlatKeys.value },
    { label: '百分比', list: allPctKeys.value },
  ].filter((g) => g.list.length)
  if (customRows.value.length) out.push({ label: '其他', list: customRows.value })
  return out
})

/** 按部位分组（顺序见 @/parts：单手武器 → 双手武器 → 头 → 手 → 胴 → 盾 → 脚 → 饰品） */
const typeGroups = computed(() => {
  const g = new Map<string, EquipType[]>()
  for (const t of props.types) {
    const k = t.part_text || '其他'
    const list = g.get(k)
    if (list) list.push(t)
    else g.set(k, [t])
  }
  return [...g.entries()].sort((a, b) => partRank(a[0]) - partRank(b[0]))
})

/** 搜索命中的全部装备（一键添加用，不截断） */
const equipHitsAll = computed(() => {
  const q = equipQuery.value.trim()
  if (!q) return []
  return props.catalog.filter((c) => c.name.includes(q) || String(c.id).includes(q))
})

/** 列表只显示前 12 条 */
const equipHits = computed(() => equipHitsAll.value.slice(0, 12))

/** 命中项里还没被选中的件数（0 时「全部添加」无需再点） */
const equipHitNew = computed(
  () => equipHitsAll.value.filter((c) => !draft.target.equipment_ids.includes(c.id)).length,
)

/** 一键添加：把当前搜索命中的同类装备一次性全部加入 */
function addAllEquipHits() {
  for (const c of equipHitsAll.value) {
    if (!draft.target.equipment_ids.includes(c.id)) draft.target.equipment_ids.push(c.id)
  }
}

const catalogById = computed(() => new Map(props.catalog.map((c) => [c.id, c])))

const pickedEquips = computed(() =>
  draft.target.equipment_ids.map((id) => {
    const c = catalogById.value.get(id)
    return { id, name: c?.name || String(id), icon: c?.icon || '' }
  }),
)

const rankText = computed(() => {
  const c = draft.target.rank
  if (!c) return '阶级≥0'
  const sym = RANK_OPS.find((o) => o.op === c.op)?.label || '≥'
  return `阶级${sym}${c.value ?? 0}`
})

const starText = computed(() => {
  const c = draft.target.stars
  if (!c) return '星级≥1'
  const sym = RANK_OPS.find((o) => o.op === c.op)?.label || '≥'
  return `星级${sym}${c.value ?? 1}`
})

const colorText = computed(() => {
  const c = draft.target.color
  if (!c) return '颜色≥白'
  const sym = RANK_OPS.find((o) => o.op === c.op)?.label || '≥'
  return `颜色${sym}${qualityLabel(c.value)}`
})

const targetSummary = computed(() => {
  const reinf = draft.target.reinforce === 'eq20' ? '强化=20' : '强化<20'
  const brief = (list: string[]) =>
    `${list.slice(0, 3).join('/')}${list.length > 3 ? ' 等' : ''}`
  const want =
    (draft.target.attrs.length ? ` · 必有 ${brief(draft.target.attrs)}` : '') +
    (draft.target.attrs_opt.length
      ? ` · 可选${draft.target.attr_need}项(${brief(draft.target.attrs_opt)})`
      : '')
  const base = `${reinf} · ${rankText.value} · ${starText.value} · ${colorText.value}${want}`
  if (draft.target.mode === 'types') {
    const names = draft.target.types
      .map((id) => props.types.find((t) => t.id === id)?.name || id)
      .slice(0, 4)
    const more = draft.target.types.length > 4 ? ` 等${draft.target.types.length}种` : ''
    return `${base} · ${names.join('/') || '未选类型'}${more}`
  }
  return `${base} · ${draft.target.equipment_ids.length} 件指定装备`
})

// ---------- 阶级分 ----------

/** 装备阶级范围（masterdata 里 rank 只有 0~6），每阶一个分数框 */
const RANK_LEVELS = [0, 1, 2, 3, 4, 5, 6]

function rankScoreOf(r: number): number {
  return (draft.rank_scores || {})[String(r)] ?? 0
}

function setRankScore(r: number, raw: string) {
  if (!draft.rank_scores) draft.rank_scores = {}
  const key = String(r)
  const s = raw.trim()
  const n = Number(s)
  if (s === '' || !Number.isFinite(n) || !n) delete draft.rank_scores[key]
  else draft.rank_scores[key] = n
}

// ---------- 星级分 ----------

/** 装备星级 1~5，每星一个分数框 */
const STAR_LEVELS = [1, 2, 3, 4, 5]

function starScoreOf(s: number): number {
  return (draft.star_scores || {})[String(s)] ?? 0
}

function setStarScore(s: number, raw: string) {
  if (!draft.star_scores) draft.star_scores = {}
  const key = String(s)
  const text = raw.trim()
  const n = Number(text)
  if (text === '' || !Number.isFinite(n) || !n) delete draft.star_scores[key]
  else draft.star_scores[key] = n
}

// ---------- 规则颜色 ----------

/** 调色盘的值必须是合法色号，否则回默认白 */
const colorPickerValue = computed(() => {
  const c = draft.color || ''
  return /^#[0-9a-f]{6}$/i.test(c) ? c : DEFAULT_RULE_COLOR
})

/** 预设外的颜色：来自项目里其他规则用过的自选色（含当前规则），方便直接复用 */
const extraColors = computed(() => (props.extraColors || []).map((c) => c.toLowerCase()))

/** 手输色号：自动补 #，过滤非法字符，最多 6 位 */
function onColorInput(e: Event) {
  const el = e.target as HTMLInputElement
  const digits = el.value.replace(/[^0-9a-fA-F]/g, '').slice(0, 6)
  draft.color = digits ? '#' + digits.toLowerCase() : ''
  el.value = draft.color
}

function onColorPick(e: Event) {
  draft.color = (e.target as HTMLInputElement).value.toLowerCase()
}

/** 可选属性：至少满足 need 个（1 ~ min(可选属性数, 4)） */
const targetNeedOptions = computed(() => {
  const top = Math.max(1, Math.min(draft.target.attrs_opt.length, 4))
  const out: number[] = []
  for (let i = 1; i <= top; i++) out.push(i)
  return out
})

type AttrKind = 'must' | 'opt'

const attrList = (kind: AttrKind) =>
  kind === 'must' ? draft.target.attrs : draft.target.attrs_opt

function addTargetAttr(value: string, kind: AttrKind) {
  if (!value) return
  const list = attrList(kind)
  if (list.includes(value)) return
  // 同一属性只在一边：加进必有就从可选挪走，反之亦然
  const other = attrList(kind === 'must' ? 'opt' : 'must')
  const i = other.indexOf(value)
  if (i >= 0) other.splice(i, 1)
  list.push(value)
}

function removeTargetAttr(i: number, kind: AttrKind) {
  attrList(kind).splice(i, 1)
  const top = Math.max(1, Math.min(draft.target.attrs_opt.length, 4))
  if (draft.target.attr_need > top) draft.target.attr_need = top
}

function toggleType(id: number) {
  const i = draft.target.types.indexOf(id)
  if (i >= 0) draft.target.types.splice(i, 1)
  else draft.target.types.push(id)
}

function toggleEquip(id: number) {
  const i = draft.target.equipment_ids.indexOf(id)
  if (i >= 0) draft.target.equipment_ids.splice(i, 1)
  else draft.target.equipment_ids.push(id)
}

function selectAllTypes() {
  draft.target.types = props.types.map((t) => t.id)
}

/** 点分组名：整行批量开关（全选则全取消，否则全选） */
function toggleTypeGroup(list: EquipType[]) {
  const all = list.every((t) => draft.target.types.includes(t.id))
  for (const t of list) {
    const i = draft.target.types.indexOf(t.id)
    if (all && i >= 0) draft.target.types.splice(i, 1)
    else if (!all && i < 0) draft.target.types.push(t.id)
  }
}

function resetWeights() {
  if (!confirm('确认把全部属性权重清零？')) return
  draft.attr = {}
}

function removeAttr(k: string) {
  delete draft.attr[k]
}

function weightOf(k: string): number {
  return draft.attr[k] ?? 0
}

function setWeight(k: string, raw: string) {
  const s = raw.trim()
  if (s === '') {
    delete draft.attr[k]
    return
  }
  const n = Number(s)
  if (Number.isFinite(n)) draft.attr[k] = n
}

// 组合阶梯：满足 1 ~ min(属性数, 4) 个，各一档分数
const MIN_TIER = 1
const MAX_TIER = 4

function addCombo() {
  draft.combos.push({ attrs: [], tiers: { '1': 10 } })
}

function removeCombo(i: number) {
  draft.combos.splice(i, 1)
}

/** 组合顺序可调：判定从上到下，第一组命中就取它的分 */
function moveCombo(i: number, delta: number) {
  const j = i + delta
  if (j < 0 || j >= draft.combos.length) return
  const [c] = draft.combos.splice(i, 1)
  draft.combos.splice(j, 0, c)
}

/** 档位：1 ~ min(有效属性数, 4)，至少 1 档 */
function tierKeys(ci: number): number[] {
  const n = draft.combos[ci].attrs.filter(Boolean).length
  const top = Math.max(MIN_TIER, Math.min(n, MAX_TIER))
  const out: number[] = []
  for (let k = MIN_TIER; k <= top; k++) out.push(k)
  return out
}

function tierValue(ci: number, k: number): number {
  return draft.combos[ci].tiers?.[String(k)] ?? 0
}

function setTier(ci: number, k: number, raw: string) {
  const c = draft.combos[ci]
  if (!c.tiers) c.tiers = {}
  const key = String(k)
  const s = raw.trim()
  if (s === '') {
    delete c.tiers[key]
    return
  }
  const n = Number(s)
  if (Number.isFinite(n)) c.tiers[key] = n
  else delete c.tiers[key]
}

/** 属性删掉后档位会变少：把超出范围的档位分数一并丢掉 */
function trimTiers(ci: number) {
  const c = draft.combos[ci]
  if (!c.tiers) c.tiers = {}
  const keep = new Set(tierKeys(ci).map(String))
  for (const k of Object.keys(c.tiers)) if (!keep.has(k)) delete c.tiers[k]
}

/** 加一个属性：先填掉「未选」占位；没有空位时才新增 */
function addComboAttr(ci: number, value: string) {
  const combo = draft.combos[ci]
  if (!value || combo.attrs.includes(value)) return
  const blank = combo.attrs.indexOf('')
  if (blank >= 0) combo.attrs[blank] = value
  else combo.attrs.push(value)
  trimTiers(ci)
}

/** 删一个属性：随便删，删空了保存时这条组合会被丢掉 */
function removeComboAttr(ci: number, ai: number) {
  const combo = draft.combos[ci]
  combo.attrs.splice(ai, 1)
  trimTiers(ci)
}

function save() {
  if (nameError.value) {
    alert(nameError.value)
    return
  }
  if (!draft.target.types.length && draft.target.mode === 'types') {
    alert('请至少选择一种装备类型')
    return
  }
  if (!draft.target.equipment_ids.length && draft.target.mode === 'equipment') {
    alert('请至少选择一件指定装备')
    return
  }
  draft.combos = draft.combos
    .map((c) => ({ ...c, attrs: c.attrs.filter(Boolean) }))
    .filter((c) => c.attrs.length >= 1)
    .map((c) => {
      const top = Math.max(MIN_TIER, Math.min(c.attrs.length, MAX_TIER))
      const tiers: Record<string, number> = {}
      for (let k = MIN_TIER; k <= top; k++) {
        const v = Number(c.tiers?.[String(k)] ?? 0)
        if (Number.isFinite(v) && v) tiers[String(k)] = v
      }
      return { attrs: c.attrs, tiers }
    })
  draft.attr = Object.fromEntries(Object.entries(draft.attr).filter(([, v]) => Number(v)))
  draft.rank_scores = Object.fromEntries(
    Object.entries(draft.rank_scores || {}).filter(([k, v]) => {
      const n = Number(k)
      return Number(v) && n >= 0 && n <= 6
    }),
  )
  draft.star_scores = Object.fromEntries(
    Object.entries(draft.star_scores || {}).filter(([k, v]) => {
      const n = Number(k)
      return Number(v) && n >= 1 && n <= 5
    }),
  )
  // 阶级：运算符非法回退 >=，数值取整
  const rank = draft.target.rank || { op: '>=', value: 0 }
  draft.target.rank = {
    op: RANK_OPS.some((o) => o.op === rank.op) ? rank.op : '>=',
    value: Math.trunc(Number(rank.value) || 0),
  }
  // 星级：运算符非法回退 >=，数值取整并夹在 1~5
  const star = draft.target.stars || { op: '>=', value: 1 }
  draft.target.stars = {
    op: RANK_OPS.some((o) => o.op === star.op) ? star.op : '>=',
    value: Math.min(5, Math.max(1, Math.trunc(Number(star.value) || 1))),
  }
  // 品质色：1~5 = 白/绿/蓝/紫/红，同样是运算符 + 夹紧
  const col = draft.target.color || { op: '>=', value: 1 }
  draft.target.color = {
    op: RANK_OPS.some((o) => o.op === col.op) ? col.op : '>=',
    value: Math.min(5, Math.max(1, Math.trunc(Number(col.value) || 1))),
  }
  // 目标拥有属性：两段各自去空去重，可选属性的 need 收在 1 ~ min(可选个数, 4)
  const uniq = (list: string[]) => [...new Set(list.filter(Boolean))]
  draft.target.attrs = uniq(draft.target.attrs)
  draft.target.attrs_opt = uniq(draft.target.attrs_opt).filter((a) => !draft.target.attrs.includes(a))
  const needTop = Math.max(1, Math.min(draft.target.attrs_opt.length, 4))
  draft.target.attr_need = Math.max(1, Math.min(Math.trunc(Number(draft.target.attr_need) || 1), needTop))
  emit('save', JSON.parse(JSON.stringify(draft)))
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div class="flex items-center gap-3 border-b border-white/10 px-4 py-2.5">
      <div class="text-sm text-gray-200">{{ isNew ? '新建规则' : '编辑规则' }}</div>
      <div class="flex gap-2">
        <button class="rounded border border-white/10 px-3 py-1 text-[13px] text-gray-400 hover:bg-white/5" @click="emit('cancel')">
          取消
        </button>
        <button class="rounded bg-gold-400 px-4 py-1 text-[13px] font-medium text-black" @click="save">
          保存
        </button>
      </div>
    </div>

    <!-- 滚动条留在窗口右侧，内容限宽左对齐：带鱼屏下两列不会被拉到几米宽 -->
    <div class="min-h-0 flex-1 overflow-auto px-4 py-4 text-[13px]">
    <div class="w-full max-w-[1360px] space-y-3">
      <!-- 基本信息 -->
      <section class="grid grid-cols-12 gap-3">
        <label class="col-span-6 flex flex-col gap-1">
          <span class="text-[11px] text-gray-500">规则名称（同时作为文件名，不能含 \ / : * ? " &lt; &gt; |）</span>
          <input
            :value="draft.name"
            class="rounded border bg-ink-700 px-2 py-1 outline-none"
            :class="nameError ? 'border-rose-400/60' : 'border-white/10'"
            @input="onNameInput"
          />
          <span v-if="nameError" class="text-[10.5px] text-rose-300">{{ nameError }}</span>
        </label>
        <label class="col-span-2 flex flex-col gap-1">
          <span class="text-[11px] text-gray-500">优先级（大的先）</span>
          <input v-model.number="draft.priority" type="number" class="rounded border border-white/10 bg-ink-700 px-2 py-1 outline-none" />
        </label>
        <label class="col-span-2 flex flex-col gap-1">
          <span class="text-[11px] text-gray-500">启用</span>
          <label class="flex h-[30px] items-center gap-2 text-[12px] text-gray-300">
            <input v-model="draft.enabled" type="checkbox" class="accent-gold-400" />生效
          </label>
        </label>
        <label class="col-span-2 flex flex-col gap-1">
          <span class="text-[11px] text-gray-500">备注</span>
          <input v-model="draft.note" class="rounded border border-white/10 bg-ink-700 px-2 py-1 outline-none" />
        </label>

        <!-- 规则颜色：规则名在规则列表 / 结果列表 / hover 里都用它 -->
        <div class="col-span-12 flex flex-wrap items-center gap-2">
          <span class="text-[11px] text-gray-500">颜色</span>
          <!-- 手输色号（放最前） -->
          <input
            :value="draft.color"
            class="w-[86px] rounded border border-white/10 bg-ink-700 px-1.5 py-0.5 text-[11.5px] tabular-nums outline-none focus:ring-1 focus:ring-gold-400/40"
            maxlength="7"
            :placeholder="DEFAULT_RULE_COLOR"
            title="直接输入色号，如 #60a5fa"
            @input="onColorInput"
          />
          <input
            type="color"
            :value="colorPickerValue"
            class="h-6 w-9 cursor-pointer rounded border border-white/10 bg-ink-700 p-0.5"
            title="调色盘选色"
            @input="onColorPick"
          />
          <button
            v-for="c in RULE_COLORS"
            :key="c.key"
            class="h-5 w-5 rounded-full border transition"
            :class="(draft.color || '').toLowerCase() === c.hex
              ? 'border-white ring-2 ring-white/40'
              : 'border-black/50 hover:scale-110'"
            :style="{ background: c.hex }"
            :title="`${c.label}  ${c.hex}`"
            @click="draft.color = c.hex"
          />
          <!-- 预设外颜色：项目里其他规则用过的自选色，用竖线隔开后平铺，点一下就复用 -->
          <template v-if="extraColors.length">
            <span class="mx-0.5 h-4 w-px bg-white/20" />
            <button
              v-for="c in extraColors"
              :key="c"
              class="h-5 w-5 rounded-full border transition"
              :class="(draft.color || '').toLowerCase() === c
                ? 'border-white ring-2 ring-white/40'
                : 'border-black/50 hover:scale-110'"
              :style="{ background: c }"
              :title="`自定义  ${c}`"
              @click="draft.color = c"
            />
          </template>
        </div>
      </section>

      <!-- 目标装备 -->
      <section class="rounded border border-white/10 p-3">
        <div class="mb-2 text-[12px] text-gray-400">目标装备</div>

        <!-- 左：基础分 / 强化 / 阶级 / 星级 / 目标属性　右：范围 -->
        <div class="grid items-start gap-3 lg:grid-cols-2">
        <div class="space-y-3">
        <label class="flex items-center gap-2">
          <span class="text-[11px] text-gray-500">基础分</span>
          <input
            v-model.number="draft.base_score"
            type="number"
            step="1"
            class="w-24 rounded border border-white/10 bg-ink-700 px-2 py-1 outline-none"
          />
          <span class="text-[10.5px] text-gray-600">符合下面目标条件就先加这个分</span>
        </label>

        <div class="flex items-center gap-4">
          <span class="text-[11px] text-gray-500">强化</span>
          <label class="flex items-center gap-1.5">
            <input v-model="draft.target.reinforce" type="radio" value="lt20" class="accent-gold-400" />
            <span class="text-gray-300">强化 &lt; 20</span>
          </label>
          <label class="flex items-center gap-1.5">
            <input v-model="draft.target.reinforce" type="radio" value="eq20" class="accent-gold-400" />
            <span class="text-gray-300">强化 = 20</span>
          </label>
        </div>

        <!-- 阶级：比较运算符 + 阶级数字 -->
        <div class="flex items-center gap-2">
          <span class="text-[11px] text-gray-500">阶级</span>
          <select
            v-model="draft.target.rank.op"
            class="w-[64px] rounded border border-white/10 bg-ink-700 px-1.5 py-1 text-[12.5px] outline-none"
          >
            <option v-for="o in RANK_OPS" :key="o.op" :value="o.op">{{ o.label }}</option>
          </select>
          <input
            v-model.number="draft.target.rank.value"
            type="number"
            step="1"
            class="w-[80px] rounded border border-white/10 bg-ink-700 px-2 py-1 text-right tabular-nums outline-none focus:ring-1 focus:ring-gold-400/40"
          />
        </div>

        <!-- 星级：比较运算符 + 星级数字（1~5） -->
        <div class="flex items-center gap-2">
          <span class="text-[11px] text-gray-500">星级</span>
          <select
            v-model="draft.target.stars.op"
            class="w-[64px] rounded border border-white/10 bg-ink-700 px-1.5 py-1 text-[12.5px] outline-none"
          >
            <option v-for="o in RANK_OPS" :key="o.op" :value="o.op">{{ o.label }}</option>
          </select>
          <input
            v-model.number="draft.target.stars.value"
            type="number"
            step="1"
            min="1"
            max="5"
            class="w-[80px] rounded border border-white/10 bg-ink-700 px-2 py-1 text-right tabular-nums outline-none focus:ring-1 focus:ring-gold-400/40"
          />
        </div>

        <!-- 品质色：比较运算符 + 白/绿/蓝/紫/红（1~5） -->
        <div class="flex items-center gap-2">
          <span class="text-[11px] text-gray-500">颜色</span>
          <select
            v-model="draft.target.color.op"
            class="w-[64px] rounded border border-white/10 bg-ink-700 px-1.5 py-1 text-[12.5px] outline-none"
          >
            <option v-for="o in RANK_OPS" :key="o.op" :value="o.op">{{ o.label }}</option>
          </select>
          <select
            v-model.number="draft.target.color.value"
            class="w-[80px] rounded border border-white/10 bg-ink-700 px-1.5 py-1 text-[12.5px] outline-none"
          >
            <option v-for="q in QUALITY_LEVELS" :key="q.value" :value="q.value">
              {{ q.label }}（{{ q.value }}）
            </option>
          </select>
        </div>

        <!-- 必有属性：全部命中才认这条规则 -->
        <div class="rounded border border-white/10 bg-ink-800/50 p-2">
          <div class="mb-1.5 flex items-baseline gap-2">
            <span class="text-[11px] text-gray-400">必有属性</span>
            <span class="text-[10.5px] text-gray-600">全部命中才算命中这条规则</span>
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <span
              v-for="(a, i) in draft.target.attrs"
              :key="a"
              class="flex items-center gap-1 rounded border border-gold-400/30 bg-gold-400/10 px-1.5 py-0.5 text-[11.5px] text-gold-200"
            >
              {{ a }}
              <button class="text-gray-400 hover:text-rose-300" title="移除该属性" @click="removeTargetAttr(i, 'must')">✕</button>
            </span>
            <select
              :value="''"
              class="rounded border border-white/10 bg-ink-700 px-1.5 py-0.5 text-[11.5px]"
              @change="(e) => { const el = e.target as HTMLSelectElement; addTargetAttr(el.value, 'must'); el.value = '' }"
            >
              <option value="">+ 添加必有属性</option>
              <optgroup v-for="grp in comboGroups" :key="grp.label" :label="grp.label">
                <option
                  v-for="o in grp.list"
                  :key="o"
                  :value="o"
                  :disabled="draft.target.attrs.includes(o)"
                >{{ o }}</option>
              </optgroup>
            </select>
          </div>
        </div>

        <!-- 可选属性：至少命中 1~4 个才认这条规则 -->
        <div class="rounded border border-white/10 bg-ink-800/50 p-2">
          <div class="mb-1.5 flex items-baseline gap-2">
            <span class="text-[11px] text-gray-400">可选属性</span>
            <span class="text-[10.5px] text-gray-600">从这里至少命中 N 个即可</span>
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <span
              v-for="(a, i) in draft.target.attrs_opt"
              :key="a"
              class="flex items-center gap-1 rounded border border-emerald-400/30 bg-emerald-400/10 px-1.5 py-0.5 text-[11.5px] text-emerald-200"
            >
              {{ a }}
              <button class="text-gray-400 hover:text-rose-300" title="移除该属性" @click="removeTargetAttr(i, 'opt')">✕</button>
            </span>
            <select
              :value="''"
              class="rounded border border-white/10 bg-ink-700 px-1.5 py-0.5 text-[11.5px]"
              @change="(e) => { const el = e.target as HTMLSelectElement; addTargetAttr(el.value, 'opt'); el.value = '' }"
            >
              <option value="">+ 添加可选属性</option>
              <optgroup v-for="grp in comboGroups" :key="grp.label" :label="grp.label">
                <option
                  v-for="o in grp.list"
                  :key="o"
                  :value="o"
                  :disabled="draft.target.attrs_opt.includes(o)"
                >{{ o }}</option>
              </optgroup>
            </select>
          </div>
          <div class="mt-1.5 flex items-center gap-1.5 text-[11px] text-gray-400">
            <span>至少满足</span>
            <select
              v-model.number="draft.target.attr_need"
              class="rounded border border-white/10 bg-ink-700 px-1 py-0.5 text-[11.5px]"
            >
              <option v-for="n in targetNeedOptions" :key="n" :value="n">{{ n }}</option>
            </select>
            <span>个</span>
          </div>
        </div>

        </div><!-- /左列 -->

        <!-- 右侧：范围 -->
        <div class="space-y-2">
        <div class="flex flex-wrap items-center gap-4">
          <span class="text-[11px] text-gray-500">范围</span>
          <label class="flex items-center gap-1.5">
            <input v-model="draft.target.mode" type="radio" value="types" class="accent-gold-400" />
            <span class="text-gray-300">按装备类型</span>
          </label>
          <label class="flex items-center gap-1.5">
            <input v-model="draft.target.mode" type="radio" value="equipment" class="accent-gold-400" />
            <span class="text-gray-300">按特定装备</span>
          </label>
          <span class="text-[10.5px] text-gray-600">特定装备的规则总是先于按类型</span>
        </div>

        <!-- 类型多选 -->
        <div v-if="draft.target.mode === 'types'" class="space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-[11px] text-gray-500">
              已选 {{ draft.target.types.length }} 种
            </span>
            <div class="flex gap-2 text-[11px]">
              <button class="text-gray-400 hover:text-gold-300" @click="selectAllTypes">全选</button>
              <button class="text-gray-400 hover:text-gold-300" @click="draft.target.types = []">清空</button>
            </div>
          </div>
          <div v-for="[group, list] in typeGroups" :key="group" class="flex flex-wrap items-center gap-1.5">
            <button
              class="w-[62px] shrink-0 rounded border px-1 py-0.5 text-[11px] transition"
              :class="list.every((t) => draft.target.types.includes(t.id))
                ? 'border-sky-400/60 bg-sky-400/15 text-sky-300'
                : 'border-sky-400/20 bg-sky-400/5 text-gray-500 hover:text-sky-200'"
              :title="'点一下批量开关「' + group + '」整行'"
              @click="toggleTypeGroup(list)"
            >{{ group }}</button>
            <button
              v-for="t in list"
              :key="t.id"
              class="rounded border px-1.5 py-0.5 text-[11.5px] transition"
              :class="draft.target.types.includes(t.id)
                ? 'border-gold-400/60 bg-gold-400/10 text-gold-300'
                : 'border-white/10 text-gray-400 hover:border-white/25'"
              @click="toggleType(t.id)"
            >{{ t.name }}</button>
          </div>
        </div>

        <!-- 指定装备多选 -->
        <div v-else class="space-y-2">
          <div class="max-w-[440px] space-y-2">
            <input
              v-model="equipQuery"
              placeholder="搜索装备名或 id…"
              class="w-full rounded border border-white/10 bg-ink-700 px-2 py-1 outline-none"
            />
            <div v-if="equipHits.length" class="space-y-1">
              <div class="flex items-center gap-2 text-[11px]">
                <button
                  class="shrink-0 rounded border px-2 py-1 transition"
                  :class="equipHitNew
                    ? 'border-gold-400/40 text-gold-300 hover:bg-gold-400/10'
                    : 'cursor-not-allowed border-white/10 text-gray-600'"
                  :disabled="!equipHitNew"
                  title="把当前搜索命中的装备一次性全部加入"
                  @click="addAllEquipHits"
                >＋ 全部添加{{ equipHitNew ? `（${equipHitNew}）` : '' }}</button>
                <span class="min-w-0 flex-1 text-gray-500">
                  命中 {{ equipHitsAll.length }} 件{{ equipHitsAll.length > equipHits.length ? '（只列出前 12 条）' : '' }}
                </span>
              </div>
              <div class="max-h-40 overflow-auto rounded border border-white/10">
                <button
                  v-for="c in equipHits"
                  :key="c.id"
                  class="flex w-full items-center gap-2 px-2 py-1 text-left text-[12px] hover:bg-white/5"
                  :class="draft.target.equipment_ids.includes(c.id) ? 'text-gold-300' : 'text-gray-300'"
                  @click="toggleEquip(c.id)"
                >
                  <span class="min-w-0 flex-1 truncate">{{ c.name }}</span>
                  <span class="shrink-0 text-[10.5px] text-gray-500">{{ c.part }} · {{ c.rank }}阶</span>
                </button>
              </div>
            </div>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="e in pickedEquips"
              :key="e.id"
              class="flex items-center gap-1 rounded border border-gold-400/40 bg-gold-400/10 py-0.5 pl-1 pr-1.5 text-[11.5px] text-gold-300"
            >
              <EquipIcon :icon="e.icon" :size="18" />
              {{ e.name }}
              <button class="text-gray-400 hover:text-rose-300" @click="toggleEquip(e.id)">✕</button>
            </span>
            <span v-if="!pickedEquips.length" class="text-[11px] text-gray-600">尚未选择装备</span>
          </div>
        </div>

        <div class="text-[11px] text-gray-500">当前范围：{{ targetSummary }}</div>
        </div><!-- /范围 -->
        </div><!-- /目标属性 + 范围 -->
      </section>

      <!-- 属性权重 + 组合分：宽屏左右排列，窄屏自动上下 -->
      <div class="grid items-start gap-3 lg:grid-cols-2">
      <!-- 单属性权重 -->
      <section class="rounded border border-white/10 p-3">
        <div class="mb-2 flex items-center justify-between">
          <span class="text-[12px] text-gray-400">属性权重</span>
          <button
            class="rounded border border-white/10 px-2 py-0.5 text-[11px] text-gray-400 hover:border-rose-400/40 hover:text-rose-300"
            title="确认后把全部权重改为 0"
            @click="resetWeights"
          >重置</button>
        </div>

        <div class="grid grid-cols-2 gap-1.5">
          <template v-for="r in weightRows" :key="r.base">
            <label
              class="flex min-w-0 items-center gap-2 rounded-md border px-2.5 py-1.5"
              :class="draft.attr[r.key] ? 'border-gold-400/40 bg-gold-400/5' : 'border-white/5 bg-ink-700'"
              :title="r.label"
            >
              <span class="flex-1 truncate text-[12.5px] text-gray-200">{{ r.base }}</span>
              <input
                v-if="r.key"
                :value="weightOf(r.key)"
                type="number"
                step="0.1"
                class="w-16 rounded border border-white/10 bg-ink-800 px-1.5 py-0.5 text-right tabular-nums outline-none focus:ring-1 focus:ring-gold-400/40"
                @input="setWeight(r.key, ($event.target as HTMLInputElement).value)"
              />
              <span v-else class="w-16 text-center text-[11px] text-gray-600">—</span>
            </label>
            <label
              v-if="r.pct_key"
              class="flex min-w-0 items-center gap-2 rounded-md border px-2.5 py-1.5"
              :class="draft.attr[r.pct_key] ? 'border-gold-400/40 bg-gold-400/5' : 'border-white/5 bg-ink-700'"
              :title="r.label"
            >
              <span class="flex-1 truncate text-[12.5px] text-gray-200">{{ r.base }}%</span>
              <input
                :value="weightOf(r.pct_key)"
                type="number"
                step="0.1"
                class="w-16 rounded border border-white/10 bg-ink-800 px-1.5 py-0.5 text-right tabular-nums outline-none focus:ring-1 focus:ring-gold-400/40"
                @input="setWeight(r.pct_key, ($event.target as HTMLInputElement).value)"
              />
            </label>
            <div v-else class="invisible rounded-md border border-white/5" />
          </template>
        </div>

        <div v-if="customRows.length" class="my-2">
          <div class="mb-1 text-[11px] text-gray-500">其他（自定义）</div>
          <div class="grid grid-cols-4 gap-1.5">
            <div
              v-for="k in customRows"
              :key="k"
              class="flex items-center gap-1.5 rounded bg-ink-700 px-2 py-1"
            >
              <span class="w-16 shrink-0 truncate text-[11.5px] text-gray-300">{{ k }}</span>
              <input
                :value="weightOf(k)"
                type="number"
                step="0.1"
                class="w-14 rounded border border-white/10 bg-ink-800 px-1.5 py-0.5 text-right tabular-nums outline-none"
                @input="setWeight(k, ($event.target as HTMLInputElement).value)"
              />
              <button class="ml-auto text-gray-500 hover:text-rose-300" @click="removeAttr(k)">✕</button>
            </div>
          </div>
        </div>

      </section>

      <!-- 右列：阶级分 + 星级分 + 类型分（上下排列） -->
      <div class="space-y-3">
      <!-- 阶级分：命中规则后按装备阶级加分 -->
      <section class="rounded border border-white/10 p-3">
        <div class="mb-2 flex items-baseline gap-2">
          <span class="text-[12px] text-gray-400">阶级分</span>
          <span class="text-[10.5px] text-gray-600">命中规则后按装备阶级加分，0 = 不加</span>
        </div>
        <div class="flex flex-wrap items-end gap-2">
          <label v-for="r in RANK_LEVELS" :key="r" class="flex flex-col items-center gap-0.5">
            <input
              :value="rankScoreOf(r)"
              type="number"
              step="1"
              class="w-14 rounded border border-white/10 bg-ink-700 px-1.5 py-0.5 text-right tabular-nums outline-none focus:ring-1 focus:ring-gold-400/40"
              @input="setRankScore(r, ($event.target as HTMLInputElement).value)"
            />
            <span class="text-[10px] text-gray-500">{{ r }} 阶</span>
          </label>
        </div>
      </section>

      <!-- 星级分：命中规则后按装备星级加分 -->
      <section class="rounded border border-white/10 p-3">
        <div class="mb-2 flex items-baseline gap-2">
          <span class="text-[12px] text-gray-400">星级分</span>
          <span class="text-[10.5px] text-gray-600">命中规则后按装备星级加分，0 = 不加</span>
        </div>
        <div class="flex flex-wrap items-end gap-2">
          <label v-for="s in STAR_LEVELS" :key="s" class="flex flex-col items-center gap-0.5">
            <input
              :value="starScoreOf(s)"
              type="number"
              step="1"
              class="w-14 rounded border border-white/10 bg-ink-700 px-1.5 py-0.5 text-right tabular-nums outline-none focus:ring-1 focus:ring-gold-400/40"
              @input="setStarScore(s, ($event.target as HTMLInputElement).value)"
            />
            <span class="text-[10px] text-gray-500">{{ s }} 星</span>
          </label>
        </div>
      </section>

      <!-- 类型分：按钮各自独立，有组合时上一个下一个，没有时只留下面那个 -->
      <section class="rounded border border-white/10 p-3">
        <div class="mb-2 flex items-baseline gap-2">
          <span class="text-[12px] text-gray-400">类型分</span>
          <span class="text-[10.5px] text-gray-600">从上到下判定，取最先命中的组的配置</span>
        </div>
        <div class="space-y-2">
          <button
            v-if="draft.combos.length"
            class="w-[92px] rounded border border-white/10 px-2 py-1 text-[11px] text-gray-300 hover:bg-white/5"
            @click="addCombo"
          >＋ 添加类型分</button>
          <div
            v-for="(c, ci) in draft.combos"
            :key="ci"
            class="space-y-1.5 rounded bg-ink-700 px-2 py-1.5"
          >
            <!-- 序号 / 调整顺序 / 删除（放在区块最上方） -->
            <div class="flex items-center gap-1 text-[11px] text-gray-500">
              <span class="tabular-nums">#{{ ci + 1 }}</span>
              <button
                class="rounded border border-white/10 px-1 leading-4 disabled:opacity-30"
                :disabled="ci === 0"
                title="上移（更优先判定）"
                @click="moveCombo(ci, -1)"
              >↑</button>
              <button
                class="rounded border border-white/10 px-1 leading-4 disabled:opacity-30"
                :disabled="ci === draft.combos.length - 1"
                title="下移"
                @click="moveCombo(ci, 1)"
              >↓</button>
              <button class="ml-auto text-gray-500 hover:text-rose-300" title="删除这个组合" @click="removeCombo(ci)">✕</button>
            </div>

            <!-- 属性标签 + 一个添加下拉 -->
            <div class="flex flex-wrap items-center gap-1.5">
              <span
                v-for="(a, ai) in c.attrs"
                :key="ai"
                class="flex items-center gap-1 rounded border border-gold-400/30 bg-gold-400/10 px-1.5 py-0.5 text-[11.5px] text-gold-200"
              >
                {{ a || '未选' }}
                <button
                  class="text-gray-400 hover:text-rose-300"
                  title="移除该属性"
                  @click="removeComboAttr(ci, ai)"
                >✕</button>
              </span>
              <select
                :value="''"
                class="rounded border border-white/10 bg-ink-800 px-1.5 py-0.5 text-[11.5px]"
                @change="(e) => { const el = e.target as HTMLSelectElement; addComboAttr(ci, el.value); el.value = '' }"
              >
                <option value="">+ 添加属性</option>
                <optgroup v-for="grp in comboGroups" :key="grp.label" :label="grp.label">
                  <option
                    v-for="o in grp.list"
                    :key="o"
                    :value="o"
                    :disabled="c.attrs.includes(o)"
                  >{{ o }}</option>
                </optgroup>
              </select>
            </div>

            <!-- 满足 1/2/3/4 个各一档分数 -->
            <div class="flex flex-wrap items-center gap-1.5 text-[11px] text-gray-400">
              <template v-for="k in tierKeys(ci)" :key="k">
                <span>满足 {{ k }} 个</span>
                <input
                  :value="tierValue(ci, k)"
                  type="number"
                  step="1"
                  class="w-14 rounded border border-white/10 bg-ink-800 px-1.5 py-0.5 text-right tabular-nums outline-none focus:ring-1 focus:ring-gold-400/40"
                  @input="setTier(ci, k, ($event.target as HTMLInputElement).value)"
                />
                <span>分</span>
              </template>
            </div>
          </div>
          <div v-if="!draft.combos.length" class="text-[11px] text-gray-600">还没有类型分规则</div>
          <button
            class="w-[92px] rounded border border-white/10 px-2 py-1 text-[11px] text-gray-300 hover:bg-white/5"
            @click="addCombo"
          >＋ 添加类型分</button>
        </div>
      </section>
      </div><!-- /右列 -->
      </div>
    </div><!-- /限宽内容 -->
    </div><!-- /滚动容器 -->
  </div>
</template>
