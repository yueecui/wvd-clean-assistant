<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import EquipIcon from './EquipIcon.vue'
import * as api from '@/api'
import { partRank } from '@/parts'
import { QUALITY_LEVELS, qualityLabel, qualityValue } from '@/quality'
import { DEFAULT_RULE_COLOR, ruleColorStyle } from '@/rule-colors'
import { persistedEnum, persistedList, persistedString } from '@/storage'
import type { EquipType, ScanItem } from '@/types'

const props = defineProps<{
  items: ScanItem[]
  types?: EquipType[]
  /** 规则 id 的排列顺序（= 规则列表的判定优先级），规则筛选菜单按它排 */
  ruleOrder?: string[]
}>()
const emit = defineEmits<{ (e: 'calibrate', item: ScanItem): void }>()

// 过滤 / 排序都存 localStorage：刷新页面、切页签回来保持一致

/** 匹配状态过滤：只关心「全部」和「待匹配」（需要手工校准的） */
type Filter = 'all' | 'todo'
const filter = persistedEnum<Filter>('result.filter', ['all', 'todo'], 'all')

type LockFilter = 'all' | 'locked' | 'unlocked'
const lockFilter = persistedEnum<LockFilter>('result.lock', ['all', 'locked', 'unlocked'], 'all')
const lockFilters: { key: LockFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'locked', label: '锁定' },
  { key: 'unlocked', label: '未锁定' },
]

/** 大类型（= 装备部位）：顺序见 @/parts，未列出的排在后面 */
const partFilter = persistedString('result.part')
/** 装备名搜索（OCR 原名也参与匹配），会记到 localStorage，✕ 清空 */
const nameQuery = persistedString('result.query')

/** 命中规则过滤：'' = 全部；'__none__' = 一条规则都没命中；其它是 rule_id */
const RULE_NONE = '__none__'
const ruleFilter = persistedString('result.rule')

/** 星级 / 颜色 / 阶级：三组各自多选，空数组 = 不限 */
const starFilter = persistedList('result.star')
const colorFilter = persistedList('result.color')
const rankFilter = persistedList('result.rank')

/** 品质色（白绿蓝紫红）→ 文字颜色，配色沿用旧项目 feasibility/EquipmentView */
const QUALITY_CLASS: Record<string, string> = {
  white: 'text-zinc-100',
  green: 'text-green-400',
  blue: 'text-blue-400',
  purple: 'text-purple-400',
  red: 'text-red-400',
}
const qualityClass = (color: string | undefined, fallback = 'text-zinc-400') =>
  QUALITY_CLASS[color || ''] || fallback

/** 排序方式：切到规则页再切回来（组件已卸载重建）不会重置 */
const sortBy = persistedEnum<'idx' | 'score'>('result.sort', ['idx', 'score'], 'idx')

/** 评分明细浮层：挂在装备列上，自己画卡片（原生 title 有 1s 延迟） */
const TIP_W = 340
const scoreTip = ref<{
  item: ScanItem
  left: number
  top: number
  right: boolean
  /** 上方空间更足时翻上来显示（贴屏幕底部） */
  above: boolean
} | null>(null)

function showScoreTip(e: MouseEvent, item: ScanItem) {
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  // 贴近屏幕底部时翻到上方显示（高度按加护条数粗估即可）
  const est = 96 + (item.attr_details?.length || 0) * 19
  const above = r.bottom + 6 + est > window.innerHeight - 8
  scoreTip.value = {
    item,
    left: r.left,
    top: above ? r.top - 6 : r.bottom + 6,
    right: r.left + TIP_W > window.innerWidth - 8, // 靠近右边缘时改为右对齐
    above,
  }
}

function hideScoreTip() {
  scoreTip.value = null
}

/** 浮层里的数字：最多两位小数，去掉多余的 .0 */
function num(v: number | undefined | null): string {
  const n = Math.round((Number(v) || 0) * 100) / 100
  return String(n)
}

/** 手工分组：1~3 可多选，√ = 已处理（点 √ 会清掉 1~3）；none = 既没分组也没 √ */
const MARK_KEYS = ['1', '2', '3'] as const
type MarkKey = (typeof MARK_KEYS)[number]
type MarkFilterKey = '' | MarkKey | 'none' | 'done'
const markFilter = persistedEnum<MarkFilterKey>(
  'result.mark',
  ['', 'none', '1', '2', '3', 'done'],
  '',
)

/** 未分组 = 没有 1/2/3 标记、也没有 √ */
const isUngrouped = (it: ScanItem) => !it.done && !(it.marks || []).length

const markCounts = computed(() => {
  const counts: Record<MarkKey | 'none' | 'done', number> = { '1': 0, '2': 0, '3': 0, none: 0, done: 0 }
  for (const it of props.items) {
    for (const m of it.marks || []) {
      if (m === '1' || m === '2' || m === '3') counts[m] += 1
    }
    if (it.done) counts.done += 1
    else if (!(it.marks || []).length) counts.none += 1
  }
  return counts
})

/** 组号在界面上用罗马数字，底层仍存 "1"/"2"/"3" */
const MARK_LABELS: Record<MarkKey, string> = { '1': 'Ⅰ', '2': 'Ⅱ', '3': 'Ⅲ' }
const markLabel = (m: string) => MARK_LABELS[m as MarkKey] || m

const MARK_FILTERS: { key: MarkFilterKey; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'none', label: '未分组' },
  { key: '1', label: MARK_LABELS['1'] },
  { key: '2', label: MARK_LABELS['2'] },
  { key: '3', label: MARK_LABELS['3'] },
  { key: 'done', label: '√' },
]

const markFilterCount = (key: MarkFilterKey) =>
  key === ''
    ? props.items.length
    : key === 'done'
      ? markCounts.value.done
      : key === 'none'
        ? markCounts.value.none
        : markCounts.value[key]

function persistMark(it: ScanItem) {
  void api.markItem(it.idx, it.marks || [], !!it.done).catch(() => {
    /* 落盘失败只影响持久化，界面标记仍保留 */
  })
}

function toggleMark(it: ScanItem, m: MarkKey) {
  const set = new Set(it.marks || [])
  if (set.has(m)) set.delete(m)
  else set.add(m)
  it.marks = [...set].sort()
  it.done = false // 重新分组说明还没处理完
  persistMark(it)
}

function toggleDone(it: ScanItem) {
  if (it.done) {
    it.done = false
  } else {
    it.done = true
    it.marks = [] // √ 与 1~3 组互斥
  }
  persistMark(it)
}

const todoCount = computed(
  () => props.items.filter((i) => i.match_status === 'fuzzy' || i.match_status === 'none').length,
)
const lockedCount = computed(() => props.items.filter((i) => i.locked).length)

const partList = computed(() => {
  const counts = new Map<string, number>()
  for (const it of props.items) {
    if (it.part) counts.set(it.part, (counts.get(it.part) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => partRank(a.name) - partRank(b.name) || a.name.localeCompare(b.name))
})

/** 武器大类：这两个下面还要展开具体武器类型（短剑 / 刀 / 忍者刀 …） */
const WEAPON_PARTS = ['单手武器', '双手武器']

/** 具体类型的件数（按 kind 统计） */
const kindCounts = computed(() => {
  const m = new Map<number, number>()
  for (const it of props.items) {
    if (typeof it.kind === 'number') m.set(it.kind, (m.get(it.kind) || 0) + 1)
  }
  return m
})

/** 武器大类 → 具体类型选项；value 用 "k:<kind>"，和大类名（部位名）区分开 */
const weaponGroups = computed(() =>
  WEAPON_PARTS.map((part) => ({
    part,
    count: partList.value.find((p) => p.name === part)?.count || 0,
    options: (props.types || [])
      .filter((t) => t.part_text === part)
      .map((t) => ({ value: `k:${t.id}`, label: t.name, count: kindCounts.value.get(t.id) || 0 })),
  })),
)

/** 其余部位本身就是具体类型，不用再展开 */
const otherParts = computed(() => partList.value.filter((p) => !WEAPON_PARTS.includes(p.name)))

/** 命中过的规则（按件数降序）+ 未命中条数；颜色取结果里的 rule_color */
const ruleOptions = computed(() => {
  const m = new Map<string, { id: string; name: string; color: string; count: number }>()
  let none = 0
  for (const it of props.items) {
    if (!it.rule_id) {
      none += 1
      continue
    }
    const cur = m.get(it.rule_id)
    if (cur) cur.count += 1
    else {
      m.set(it.rule_id, {
        id: it.rule_id,
        name: it.rule_name || it.rule_id,
        color: it.rule_color || '',
        count: 1,
      })
    }
  }
  const order = new Map((props.ruleOrder || []).map((id, i) => [id, i]))
  const rules = [...m.values()].sort((a, b) => {
    const ia = order.get(a.id)
    const ib = order.get(b.id)
    // 跟规则列表同序（= 判定优先级）；结果里有、规则已被删的排最后，按件数
    if (ia !== undefined && ib !== undefined) return ia - ib
    if (ia !== undefined) return -1
    if (ib !== undefined) return 1
    return b.count - a.count || a.name.localeCompare(b.name)
  })
  return { rules, none }
})

/** 规则被删/改名后条件失效，回落到「全部」 */
watch(ruleOptions, (v) => {
  const cur = ruleFilter.value
  if (!cur) return
  if (cur === RULE_NONE ? !v.none : !v.rules.some((r) => r.id === cur)) ruleFilter.value = ''
})

const currentRule = computed(
  () => ruleOptions.value.rules.find((r) => r.id === ruleFilter.value) || null,
)

// ---------- 星级 / 颜色 / 阶级 过滤（三组各自单选） ----------

/** 每组候选项：星级固定 1~5、颜色固定白绿蓝紫红、阶级按结果里实际出现的；带件数 */
const capGroups = computed(() => {
  const starCounts = new Map<string, number>()
  const colorCounts = new Map<string, number>()
  const rankCounts = new Map<string, number>()
  for (const it of props.items) {
    const s = String(it.stars ?? '')
    if (s) starCounts.set(s, (starCounts.get(s) || 0) + 1)
    const c = String(qualityValue(it.color))
    colorCounts.set(c, (colorCounts.get(c) || 0) + 1)
    const r = String(it.rank ?? '')
    if (r) rankCounts.set(r, (rankCounts.get(r) || 0) + 1)
  }
  const ranks = [...rankCounts.keys()].sort((a, b) => Number(a) - Number(b))
  return [
    {
      key: 'star' as const,
      label: '星级',
      options: [1, 2, 3, 4, 5].map((n) => ({
        value: String(n),
        label: `${n} 星`,
        count: starCounts.get(String(n)) || 0,
        hex: '',
      })),
    },
    {
      key: 'color' as const,
      label: '颜色',
      options: QUALITY_LEVELS.map((q) => ({
        value: String(q.value),
        label: q.label,
        count: colorCounts.get(String(q.value)) || 0,
        hex: q.hex,
      })),
    },
    {
      key: 'rank' as const,
      label: '阶级',
      options: ranks.map((r) => ({
        value: r,
        label: `${r} 阶`,
        count: rankCounts.get(r) || 0,
        hex: '',
      })),
    },
  ]
})

/** 按钮上的摘要：星3,4 · 紫/红 · 阶5,6 */
const capSummary = computed(() => {
  const parts: string[] = []
  if (starFilter.value.length) {
    parts.push(`星${[...starFilter.value].sort((a, b) => Number(a) - Number(b)).join(',')}`)
  }
  if (colorFilter.value.length) {
    parts.push(colorFilter.value.map((v) => qualityLabel(Number(v))).join('/'))
  }
  if (rankFilter.value.length) {
    parts.push(`阶${[...rankFilter.value].sort((a, b) => Number(a) - Number(b)).join(',')}`)
  }
  return parts.join(' · ')
})

const currentCap = (kind: 'star' | 'color' | 'rank') =>
  kind === 'star' ? starFilter.value : kind === 'color' ? colorFilter.value : rankFilter.value

/** 多选：点一下切换该值；点已选中的项 = 取消它 */
function toggleCap(kind: 'star' | 'color' | 'rank', value: string) {
  const list = currentCap(kind)
  const i = list.indexOf(value)
  if (i >= 0) list.splice(i, 1)
  else list.push(value)
}

/** 单独重置某一组 */
function resetCap(kind: 'star' | 'color' | 'rank') {
  currentCap(kind).splice(0)
}

function clearCaps() {
  resetCap('star')
  resetCap('color')
  resetCap('rank')
}

/** 星级/颜色/阶级 菜单：与规则菜单共用一套开关逻辑 */
const capMenu = ref<{ left: number; top: number } | null>(null)
const capPanel = ref<HTMLElement | null>(null)

// ---------- 浮层菜单的开关 ----------

/** 规则菜单：fixed 定位，避免被表格的滚动容器裁掉 */
const ruleMenu = ref<{ left: number; top: number } | null>(null)
const rulePanel = ref<HTMLElement | null>(null)
const ruleQuery = ref('')

const ruleMatches = computed(() => {
  const q = ruleQuery.value.trim().toLowerCase()
  const list = ruleOptions.value.rules
  return q ? list.filter((r) => r.name.toLowerCase().includes(q)) : list
})

function closeMenus() {
  ruleMenu.value = null
  capMenu.value = null
}

function toggleRuleMenu(e: MouseEvent) {
  const wasOpen = !!ruleMenu.value
  closeMenus()
  if (wasOpen) return
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  ruleMenu.value = {
    left: Math.min(r.left, window.innerWidth - 252),
    top: r.bottom + 4,
  }
  ruleQuery.value = ''
}

function toggleCapMenu(e: MouseEvent) {
  const wasOpen = !!capMenu.value
  closeMenus()
  if (wasOpen) return
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
  capMenu.value = {
    left: Math.min(r.left, window.innerWidth - 252),
    top: r.bottom + 4,
  }
}

function pickRule(id: string) {
  ruleFilter.value = id
  closeMenus()
}

/** 页面别处滚动就关掉菜单；菜单自己内部的滚动不算 */
function onMenuScroll(e: Event) {
  for (const el of [rulePanel.value, capPanel.value]) {
    if (el && e.target instanceof Node && el.contains(e.target)) return
  }
  closeMenus()
}

onMounted(() => {
  document.addEventListener('mousedown', closeMenus)
  window.addEventListener('resize', closeMenus)
  window.addEventListener('scroll', onMenuScroll, true)
})
onUnmounted(() => {
  document.removeEventListener('mousedown', closeMenus)
  window.removeEventListener('resize', closeMenus)
  window.removeEventListener('scroll', onMenuScroll, true)
})

// 类型/匹配条件失效时回落到「全部」，避免筛出空列表
watch([partList, weaponGroups], () => {
  const v = partFilter.value
  if (!v) return
  if (v.startsWith('k:')) {
    if (!weaponGroups.value.some((g) => g.options.some((o) => o.value === v))) partFilter.value = ''
  } else if (!partList.value.some((p) => p.name === v)) {
    partFilter.value = ''
  }
})
watch(todoCount, (n) => {
  if (!n && filter.value !== 'all') filter.value = 'all'
})

const rows = computed(() => {
  let list = props.items
  const pf = partFilter.value
  if (pf.startsWith('k:')) {
    const kind = Number(pf.slice(2))
    list = list.filter((i) => i.kind === kind)
  } else if (pf) {
    list = list.filter((i) => i.part === pf)
  }
  // 星级 / 颜色 / 阶级：三组各自多选，空 = 不限
  if (starFilter.value.length)
    list = list.filter((i) => starFilter.value.includes(String(i.stars ?? '')))
  if (colorFilter.value.length)
    list = list.filter((i) => colorFilter.value.includes(String(qualityValue(i.color))))
  if (rankFilter.value.length)
    list = list.filter((i) => rankFilter.value.includes(String(i.rank ?? '')))
  const q = nameQuery.value.trim().toLowerCase()
  if (q) {
    // 校准后的名字和 OCR 原名都参与匹配：识别错了也能照着屏幕上看到的字搜到
    list = list.filter(
      (i) => (i.name || '').toLowerCase().includes(q) || (i.raw_name || '').toLowerCase().includes(q),
    )
  }
  if (filter.value === 'todo') {
    list = list.filter((i) => i.match_status === 'fuzzy' || i.match_status === 'none')
  }
  if (ruleFilter.value === RULE_NONE) list = list.filter((i) => !i.rule_id)
  else if (ruleFilter.value) list = list.filter((i) => i.rule_id === ruleFilter.value)
  if (lockFilter.value === 'locked') list = list.filter((i) => i.locked)
  else if (lockFilter.value === 'unlocked') list = list.filter((i) => !i.locked)
  if (markFilter.value === 'done') list = list.filter((i) => i.done)
  else if (markFilter.value === 'none') list = list.filter(isUngrouped)
  else if (markFilter.value) list = list.filter((i) => (i.marks || []).includes(markFilter.value))
  return sortBy.value === 'score'
    ? [...list].sort((a, b) => b.score - a.score)
    : [...list].sort((a, b) => a.idx - b.idx)
})

// 行被过滤掉（例如点分组把装备挪到别的组、当前筛选下本行消失）时，
// 鼠标离开事件不会再触发，这里兜底把评分浮层关掉，否则它会一直挂在那里
watch(rows, (list) => {
  const tip = scoreTip.value
  if (tip && !list.includes(tip.item)) scoreTip.value = null
})

</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2">
      <!-- 装备名搜索：记住上次输入（localStorage），✕ 一键清空 -->
      <div class="relative flex items-center">
        <input
          v-model="nameQuery"
          placeholder="搜索装备名…"
          class="w-[150px] rounded-md border border-white/10 bg-ink-700 py-1 pl-2 pr-6 text-xs text-gray-200 outline-none focus:ring-1 focus:ring-gold-400/40"
          title="按装备名过滤（校准后的名字和 OCR 原名都能搜到）"
        />
        <button
          v-if="nameQuery"
          class="absolute right-1 leading-none text-gray-500 hover:text-rose-300"
          title="清空搜索"
          @click="nameQuery = ''"
        >✕</button>
      </div>
      <select
        v-model="partFilter"
        class="rounded-md border border-white/10 bg-ink-700 px-2 py-1 text-xs text-gray-300 outline-none focus:ring-1 focus:ring-gold-400/40"
        title="按类型筛选：单手 / 双手武器可选到具体武器类型，其余部位本身就是具体类型"
      >
        <option value="">全部类型（{{ items.length }}）</option>
        <optgroup
          v-for="g in weaponGroups"
          :key="g.part"
          :label="`${g.part}（${g.count}）`"
        >
          <option :value="g.part">全部（{{ g.count }}）</option>
          <option v-for="o in g.options" :key="o.value" :value="o.value">
            {{ o.label }}（{{ o.count }}）
          </option>
        </optgroup>
        <optgroup label="其他部位">
          <option v-for="p in otherParts" :key="p.name" :value="p.name">
            {{ p.name }}（{{ p.count }}）
          </option>
        </optgroup>
      </select>
      <!-- 星级 / 颜色 / 阶级：一个按钮 + 浮层，三组各自单选 -->
      <button
        class="flex min-w-[128px] items-center justify-center gap-1.5 rounded-md border border-white/10 px-2 py-1 text-xs transition hover:bg-white/5"
        :class="capSummary ? 'text-gray-200' : 'text-gray-400'"
        title="按星级 / 颜色 / 阶级过滤（三组各选一个）"
        @mousedown.stop
        @click="toggleCapMenu"
      >
        <span class="truncate">{{ capSummary || '星级/颜色/阶级' }}</span>
        <span
          v-if="capSummary"
          class="ml-0.5 shrink-0 text-gray-500 hover:text-rose-300"
          title="清除该过滤"
          @mousedown.stop
          @click.stop="clearCaps"
        >✕</span>
      </button>
      <!-- 命中规则过滤：点开是浮层菜单（可搜索规则名，名字带规则颜色） -->
      <button
        class="flex min-w-[80px] items-center justify-center gap-1.5 rounded-md border border-white/10 px-2 py-1 text-xs transition hover:bg-white/5"
        title="按命中规则过滤（点开可搜索规则名）"
        @mousedown.stop
        @click="toggleRuleMenu"
      >
        <span
          v-if="currentRule"
          class="inline-block h-2 w-2 rounded-full"
          :style="{ background: currentRule.color || DEFAULT_RULE_COLOR }"
        ></span>
        <span
          :class="ruleFilter ? 'text-gray-200' : 'text-gray-400'"
          :style="currentRule ? ruleColorStyle(currentRule.color) : undefined"
        >{{
          currentRule ? currentRule.name : ruleFilter === RULE_NONE ? '未命中规则' : '规则'
        }}</span>
        <span
          v-if="ruleFilter"
          class="ml-0.5 text-gray-500 hover:text-rose-300"
          title="清除规则过滤"
          @mousedown.stop
          @click.stop="ruleFilter = ''"
        >✕</span>
      </button>
      <div v-if="todoCount" class="flex overflow-hidden rounded-md border border-white/10 text-xs">
        <button
          v-for="f in ([['all', '全部'], ['todo', `待匹配 ${todoCount}`]] as const)"
          :key="f[0]"
          class="px-2.5 py-1 transition"
          :class="filter === f[0] ? 'bg-gold-400/90 text-black' : 'text-gray-400 hover:bg-white/5'"
          @click="filter = f[0]"
        >
          {{ f[1] }}
        </button>
      </div>
      <div class="flex overflow-hidden rounded-md border border-white/10 text-xs">
        <button
          v-for="lf in lockFilters"
          :key="lf.key"
          class="px-2.5 py-1 transition"
          :class="lockFilter === lf.key ? 'bg-amber-300/90 text-black' : 'text-gray-400 hover:bg-white/5'"
          @click="lockFilter = lf.key"
        >
          {{ lf.label }}<span
            v-if="lf.key !== 'all'"
            class="ml-1 text-[10px] opacity-60"
          >{{ lf.key === 'locked' ? lockedCount : items.length - lockedCount }}</span>
        </button>
      </div>
      <!-- 手工分组过滤（1/2/3 + √） -->
      <div class="flex overflow-hidden rounded-md border border-white/10 text-xs">
        <button
          v-for="g in MARK_FILTERS"
          :key="g.key"
          class="px-2.5 py-1 transition"
          :class="markFilter === g.key ? 'bg-emerald-400/90 text-black' : 'text-gray-400 hover:bg-white/5'"
          @click="markFilter = g.key"
        >
          {{ g.label }}<span
            v-if="g.key"
            class="ml-1 text-[10px] opacity-60"
          >{{ markFilterCount(g.key) }}</span>
        </button>
      </div>
      <div class="flex overflow-hidden rounded-md border border-white/10 text-xs">
        <button
          v-for="s in ([['idx', '按序号'], ['score', '按评分']] as const)"
          :key="s[0]"
          class="px-2.5 py-1 transition"
          :class="sortBy === s[0] ? 'bg-white/10 text-gray-100' : 'text-gray-500 hover:bg-white/5'"
          @click="sortBy = s[0]"
        >
          {{ s[1] }}
        </button>
      </div>
      <span class="ml-auto text-xs text-gray-500">
        共 {{ rows.length }} 件<span v-if="rows.length !== items.length" class="text-gray-600"> / {{ items.length }}</span>
      </span>
    </div>

    <!-- 规则筛选浮层：fixed 定位，搜索框 + 规则列表（名字带规则颜色） -->
    <div
      v-if="ruleMenu"
      ref="rulePanel"
      class="fixed z-40 w-[248px] rounded-md border border-white/10 bg-ink-800 p-2 shadow-xl shadow-black/60"
      :style="{ left: ruleMenu.left + 'px', top: ruleMenu.top + 'px' }"
      @mousedown.stop
    >
      <input
        v-model="ruleQuery"
        placeholder="搜索规则名…"
        class="w-full rounded border border-white/10 bg-ink-700 px-2 py-1 text-xs text-gray-200 outline-none focus:ring-1 focus:ring-gold-400/40"
      />
      <div class="mt-1 max-h-[280px] overflow-auto overscroll-contain">
        <button
          class="block w-full rounded px-2 py-1 text-left text-xs text-gray-300 hover:bg-white/10"
          :class="ruleFilter === '' ? 'bg-white/10' : ''"
          @click="pickRule('')"
        >
          全部规则
          <span class="float-right text-[10px] text-gray-500">{{ items.length }}</span>
        </button>
        <button
          v-if="ruleOptions.none"
          class="block w-full rounded px-2 py-1 text-left text-xs text-gray-300 hover:bg-white/10"
          :class="ruleFilter === RULE_NONE ? 'bg-white/10' : ''"
          @click="pickRule(RULE_NONE)"
        >
          未命中规则
          <span class="float-right text-[10px] text-gray-500">{{ ruleOptions.none }}</span>
        </button>
        <button
          v-for="r in ruleMatches"
          :key="r.id"
          class="block w-full rounded px-2 py-1 text-left text-xs hover:bg-white/10"
          :class="ruleFilter === r.id ? 'bg-white/10' : ''"
          @click="pickRule(r.id)"
        >
          <span
            class="mr-1.5 inline-block h-2 w-2 rounded-full align-middle"
            :style="{ background: r.color || DEFAULT_RULE_COLOR }"
          ></span>
          <span :style="ruleColorStyle(r.color)">{{ r.name }}</span>
          <span class="float-right text-[10px] text-gray-500">{{ r.count }}</span>
        </button>
        <div v-if="!ruleMatches.length" class="px-2 py-1.5 text-[11px] text-gray-600">
          没有匹配的规则
        </div>
      </div>
    </div>

    <!-- 星级 / 颜色 / 阶级 浮层：三组各自多选，标题右侧可单独重置 -->
    <div
      v-if="capMenu"
      ref="capPanel"
      class="fixed z-40 w-[248px] rounded-md border border-white/10 bg-ink-800 p-2 shadow-xl shadow-black/60"
      :style="{ left: capMenu.left + 'px', top: capMenu.top + 'px' }"
      @mousedown.stop
    >
      <div v-for="g in capGroups" :key="g.key" class="mb-2">
        <div class="mb-1 flex items-center justify-between">
          <span class="text-[11px] text-gray-500">{{ g.label }}</span>
          <button
            class="text-[10.5px] text-gray-500 transition hover:text-gold-300"
            :class="currentCap(g.key).length ? 'text-gray-400' : 'opacity-40'"
            title="清空这一组"
            @click="resetCap(g.key)"
          >重置</button>
        </div>
        <div class="flex flex-wrap gap-1">
          <button
            v-for="o in g.options"
            :key="o.value"
            class="rounded border px-1.5 py-0.5 text-[11.5px] transition"
            :class="currentCap(g.key).includes(o.value)
              ? 'border-gold-400/50 bg-gold-400/15 text-gold-200'
              : 'border-white/10 text-gray-300 hover:bg-white/10'"
            @click="toggleCap(g.key, o.value)"
          >
            <span
              v-if="o.hex"
              class="mr-1 inline-block h-2 w-2 rounded-full align-middle"
              :style="{ background: o.hex }"
            ></span>
            {{ o.label }}
            <span class="ml-0.5 text-[10px] text-gray-500">{{ o.count }}</span>
          </button>
        </div>
      </div>
    </div>

    <div class="min-h-0 flex-1 overflow-auto" @mouseleave="hideScoreTip" @scroll="hideScoreTip">
      <table class="w-full min-w-[1108px] table-fixed border-separate border-spacing-0 text-[13px]">
        <thead class="sticky top-0 z-10 bg-ink-800 text-xs text-gray-400">
          <tr>
            <th class="w-[52px] border-b border-white/10 px-2 py-1.5 text-left font-normal">#</th>
            <th class="w-[64px] border-b border-white/10 px-2 py-1.5 text-right font-normal">评分</th>
            <th class="w-[280px] border-b border-white/10 px-2 py-1.5 text-left font-normal">装备</th>
            <th class="w-[88px] border-b border-white/10 px-2 py-1.5 text-left font-normal">星级</th>
            <th class="w-[44px] border-b border-white/10 px-2 py-1.5 text-left font-normal">阶</th>
            <th
              v-for="n in 4"
              :key="n"
              class="w-[112px] border-b border-white/10 px-2 py-1.5 text-left font-normal"
            >加护{{ n }}</th>
            <th class="w-[132px] border-b border-white/10 px-2 py-1.5 text-left font-normal">规则</th>
            <!-- 占位列：table-fixed 下没有宽度，自动吸收剩余空间 -->
            <th class="border-b border-white/10"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(it, ri) in rows"
            :key="ri + ':' + it.idx"
            class="group hover:bg-white/[0.03]"
            :class="it.match_status === 'fuzzy' || it.match_status === 'none' ? 'bg-amber-500/[0.04]' : ''"
          >
            <td class="border-b border-white/5 px-2 py-1 tabular-nums text-gray-500">{{ it.idx }}</td>

            <td
              class="border-b border-white/5 px-2 py-1 text-right tabular-nums"
              :class="it.rule_id ? 'text-gray-100' : 'text-gray-600'"
            >
              {{ it.score }}
            </td>

            <!-- 图标 + 名称合一，锁定角标叠在图标上；悬停出评分明细与右侧操作按钮 -->
            <td
              class="relative w-[280px] cursor-help border-b border-white/5 px-2 py-1"
              @mouseenter="showScoreTip($event, it)"
              @mouseleave="hideScoreTip"
            >
              <div class="flex items-center gap-2 pr-[92px]">
                <span class="relative inline-flex shrink-0">
                  <EquipIcon :icon="it.icon" :size="30" :muted="!it.icon" />
                  <span
                    v-if="it.locked"
                    class="absolute -right-1 -top-1 rounded bg-black/75 px-0.5 text-[10px] leading-[14px] text-amber-300"
                    title="已锁定"
                  >🔒</span>
                </span>
                <span class="min-w-0">
                  <span class="flex items-center gap-1.5">
                    <span
                      class="truncate"
                      :class="it.match_status === 'fuzzy' || it.match_status === 'none'
                        ? 'text-amber-200'
                        : qualityClass(it.color)"
                    >{{ it.name }}</span>
                    <span v-if="it.reinforce" class="shrink-0 rounded bg-white/10 px-1 text-[11px] text-gray-300">
                      +{{ it.reinforce }}
                    </span>
                  </span>
                </span>
              </div>

              <!-- 未 hover 时显示已有分组；hover 后同一位置换成操作按钮 -->
              <div
                v-if="it.done || (it.marks && it.marks.length)"
                class="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-1 group-hover:hidden"
              >
                <span
                  v-for="m in it.marks || []"
                  :key="m"
                  class="rounded border border-gold-400/50 bg-gold-400/15 px-1 text-[10px] leading-[16px] text-gold-200"
                >{{ markLabel(m) }}</span>
                <span
                  v-if="it.done"
                  class="rounded border border-emerald-400/50 bg-emerald-400/15 px-1 text-[10px] leading-[16px] text-emerald-200"
                >✓</span>
              </div>

              <!-- hover 时在列右侧冒出操作按钮：未匹配 → 校准；已匹配 → Ⅰ/Ⅱ/Ⅲ + ✓ 分组 -->
              <div
                class="absolute right-1 top-1/2 hidden -translate-y-1/2 items-center gap-1 rounded bg-ink-800/95 px-1 py-0.5 shadow ring-1 ring-white/10 group-hover:flex"
              >
                <template v-if="it.match_status === 'fuzzy' || it.match_status === 'none'">
                  <button
                    class="rounded border border-white/10 px-1.5 py-0.5 text-[11px] text-gray-400 hover:text-gold-300"
                    @click.stop="emit('calibrate', it)"
                  >校准</button>
                </template>
                <template v-else>
                  <button
                    v-for="m in MARK_KEYS"
                    :key="m"
                    class="h-[18px] w-[18px] rounded border text-[11px] leading-none transition"
                    :class="(it.marks || []).includes(m)
                      ? 'border-gold-400 bg-gold-400/20 text-gold-200'
                      : 'border-white/15 text-gray-400 hover:border-gold-400/50 hover:text-gold-200'"
                    :title="`标记到第 ${m} 组`"
                    @click.stop="toggleMark(it, m)"
                  >{{ MARK_LABELS[m] }}</button>
                  <button
                    class="h-[18px] w-[18px] rounded border text-[11px] leading-none transition"
                    :class="it.done
                      ? 'border-emerald-400 bg-emerald-400/20 text-emerald-200'
                      : 'border-white/15 text-gray-400 hover:border-emerald-400/50 hover:text-emerald-200'"
                    title="已处理（会清掉 1~3 组）"
                    @click.stop="toggleDone(it)"
                  >✓</button>
                </template>
              </div>
            </td>

            <td class="whitespace-nowrap border-b border-white/5 px-2 py-1" :class="qualityClass(it.color)">
              {{ '★'.repeat(it.stars) || '—' }}
            </td>

            <td class="border-b border-white/5 px-2 py-1 text-gray-400">
              <span v-if="it.rank" class="rounded bg-white/5 px-1.5 py-0.5 text-[11.5px] tabular-nums">
                {{ it.rank }}
              </span>
              <span v-else class="text-gray-600">—</span>
            </td>

            <td
              v-for="n in 4"
              :key="n"
              class="whitespace-nowrap border-b border-white/5 px-2 py-1 text-[11.5px]"
            >
              <span v-if="it.blessings[n - 1]" class="text-gray-300">{{ it.blessings[n - 1] }}</span>
              <span v-else class="text-gray-600">—</span>
            </td>

            <td class="border-b border-white/5 px-2 py-1 text-[11.5px]">
              <span
                v-if="it.rule_name"
                class="block truncate"
                :style="ruleColorStyle(it.rule_color)"
                :title="it.rule_name"
              >{{ it.rule_name }}</span>
              <span v-else class="text-gray-600">未匹配</span>
            </td>

            <td class="border-b border-white/5"></td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="11" class="px-3 py-10 text-center text-gray-600">
              {{ items.length ? '当前筛选下没有记录' : '点击「开始扫描」逐件读取装备' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 评分明细：挂在装备列上，逐条加护列出「数值 × 权重 = 分」 -->
    <Teleport to="body">
      <div
        v-if="scoreTip"
        class="pointer-events-none fixed z-50 rounded-md border border-white/15 bg-ink-800/95 px-2.5 py-2 text-[11.5px] leading-relaxed text-gray-400 shadow-xl ring-1 ring-black/50"
        :style="{
          width: TIP_W + 'px',
          left: scoreTip.left + 'px',
          top: scoreTip.top + 'px',
          transform: `translate(${scoreTip.right ? '-100%' : '0'}, ${scoreTip.above ? '-100%' : '0'})`,
        }"
      >
        <template v-if="scoreTip.item.rule_id">
          <!-- 命中的规则（按规则颜色上色，右侧是基础分） -->
          <div class="flex items-baseline gap-2">
            <span class="shrink-0 text-[10.5px] text-gray-500">规则</span>
            <span
              class="min-w-0 flex-1 truncate"
              :style="ruleColorStyle(scoreTip.item.rule_color)"
              :title="scoreTip.item.rule_name"
            >{{ scoreTip.item.rule_name }}</span>
            <span class="shrink-0 text-[10.5px] text-gray-500">
              基础 <span class="tabular-nums text-gray-100">{{ num(scoreTip.item.base_score) }}</span>
            </span>
          </div>
          <div
            v-if="scoreTip.item.raw_name && scoreTip.item.raw_name !== scoreTip.item.name"
            class="truncate text-[10.5px] text-gray-600"
          >OCR: {{ scoreTip.item.raw_name }}</div>

          <!-- 加护明细：命中组合的那几条高亮 -->
          <div class="mt-1.5 space-y-0.5 border-t border-white/10 pt-1.5">
            <div class="flex items-baseline gap-2 text-[10.5px] text-gray-500">
              <span class="min-w-0 flex-1">加护</span>
              <span class="shrink-0">权重 × 数值 = 分</span>
            </div>
            <div
              v-for="(d, i) in scoreTip.item.attr_details || []"
              :key="i"
              class="flex items-baseline gap-2"
            >
              <span
                class="min-w-0 flex-1 truncate"
                :class="d.combo ? 'text-gold-300' : 'text-gray-300'"
                :title="d.text"
              >{{ d.text }}</span>
              <span class="shrink-0 tabular-nums text-gray-100">
                {{ d.weight ? `${num(d.weight)} × ${num(d.value)} = ${num(d.pts)}` : '0' }}
              </span>
            </div>
            <div v-if="!(scoreTip.item.attr_details || []).length" class="text-gray-600">
              没有可计分的加护
            </div>
          </div>

          <!-- 阶级分 -->
          <div class="mt-1.5 flex items-baseline gap-2 border-t border-white/10 pt-1.5">
            <span class="shrink-0 text-[10.5px] text-gray-500">阶级分</span>
            <span class="min-w-0 flex-1 truncate text-gray-400">
              {{ scoreTip.item.rank ?? '?' }} 阶{{ scoreTip.item.rank_score ? '' : '（该阶未设分）' }}
            </span>
            <span class="shrink-0 tabular-nums text-gray-100">{{ num(scoreTip.item.rank_score) }}</span>
          </div>

          <!-- 星级分 -->
          <div class="mt-1.5 flex items-baseline gap-2 border-t border-white/10 pt-1.5">
            <span class="shrink-0 text-[10.5px] text-gray-500">星级分</span>
            <span class="min-w-0 flex-1 truncate text-gray-400">
              {{ scoreTip.item.stars }} 星{{ scoreTip.item.star_score ? '' : '（该星级未设分）' }}
            </span>
            <span class="shrink-0 tabular-nums text-gray-100">{{ num(scoreTip.item.star_score) }}</span>
          </div>

          <!-- 类型分 -->
          <div class="mt-1.5 flex items-baseline gap-2 border-t border-white/10 pt-1.5">
            <span class="shrink-0 text-[10.5px] text-gray-500">类型分</span>
            <span
              class="min-w-0 flex-1 truncate"
              :class="scoreTip.item.hit_combos.length ? 'text-gold-300' : 'text-gray-600'"
              :title="scoreTip.item.hit_combos.join('、')"
            >{{ scoreTip.item.hit_combos.length ? scoreTip.item.hit_combos.join('、') : '未命中类型分' }}</span>
            <span class="shrink-0 tabular-nums text-gray-100">{{ num(scoreTip.item.combo_score) }}</span>
          </div>

          <!-- 总分算式 -->
          <div class="mt-1.5 flex items-baseline gap-1 border-t border-white/10 pt-1.5 text-gray-300">
            <span class="shrink-0">总分 =</span>
            <span class="min-w-0 flex-1 truncate tabular-nums text-gray-100">
              基础 {{ num(scoreTip.item.base_score) }} + 阶级 {{ num(scoreTip.item.rank_score) }} + 星级 {{ num(scoreTip.item.star_score) }} + 属性 {{ num(scoreTip.item.attr_score) }} + 类型 {{ num(scoreTip.item.combo_score) }}
            </span>
            <span class="shrink-0 tabular-nums text-gold-300">{{ num(scoreTip.item.score) }}</span>
          </div>
        </template>
        <div v-else class="text-gray-500">没有任何规则匹配这件装备</div>
      </div>
    </Teleport>
  </div>
</template>
