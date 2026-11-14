<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ATTR_ROWS } from '@/attrs'
import type { AttrGroups, AttrRow, CatalogItem, EquipType, RankOp, RuleTarget, ScoreRule } from '@/types'

const props = defineProps<{
  rule: ScoreRule
  types: EquipType[]
  attrs: string[]
  attrGroups: AttrGroups
  catalog: CatalogItem[]
  isNew: boolean
}>()

const emit = defineEmits<{
  (e: 'save', rule: ScoreRule): void
  (e: 'cancel'): void
}>()

const BLANK_TARGET: RuleTarget = {
  reinforce: 'lt20',
  rank: { op: '>=', value: 0 },
  mode: 'types',
  types: [],
  equipment_ids: [],
}

/** 老数据可能没有阶级条件，统一补成默认 >=0 */
function withRank(r: ScoreRule): ScoreRule {
  const copy = JSON.parse(JSON.stringify(r)) as ScoreRule
  if (!copy.target) copy.target = { ...BLANK_TARGET }
  if (!copy.target.rank) copy.target.rank = { op: '>=', value: 0 }
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

const typeGroups = computed(() => {
  const g: Record<string, EquipType[]> = {}
  for (const t of props.types) {
    const k = t.part_text || '其他'
    ;(g[k] ||= []).push(t)
  }
  return Object.entries(g)
})

const equipHits = computed(() => {
  const q = equipQuery.value.trim()
  if (!q) return []
  return props.catalog.filter((c) => c.name.includes(q) || String(c.id).includes(q)).slice(0, 12)
})

const pickedEquips = computed(() =>
  draft.target.equipment_ids.map((id) => ({
    id,
    name: props.catalog.find((c) => c.id === id)?.name || String(id),
    icon: props.catalog.find((c) => c.id === id)?.icon || '',
  })),
)

const rankText = computed(() => {
  const c = draft.target.rank
  if (!c) return '阶级≥0'
  const sym = RANK_OPS.find((o) => o.op === c.op)?.label || '≥'
  return `阶级${sym}${c.value ?? 0}`
})

const targetSummary = computed(() => {
  const reinf = draft.target.reinforce === 'eq20' ? '强化=20' : '强化<20'
  const base = `${reinf} · ${rankText.value}`
  if (draft.target.mode === 'types') {
    const names = draft.target.types
      .map((id) => props.types.find((t) => t.id === id)?.name || id)
      .slice(0, 4)
    const more = draft.target.types.length > 4 ? ` 等${draft.target.types.length}种` : ''
    return `${base} · ${names.join('/') || '未选类型'}${more}`
  }
  return `${base} · ${draft.target.equipment_ids.length} 件指定装备`
})

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

function addCombo() {
  draft.combos.push({ attrs: ['', ''], need: 2, bonus: 10 })
}

function removeCombo(i: number) {
  draft.combos.splice(i, 1)
}

/** 加一个属性：先填掉「未选」占位；没有空位时才新增，need 自动 +1（不超过属性个数） */
function addComboAttr(ci: number, value: string) {
  const combo = draft.combos[ci]
  if (!value || combo.attrs.includes(value)) return
  const blank = combo.attrs.indexOf('')
  if (blank >= 0) {
    combo.attrs[blank] = value
    return
  }
  combo.attrs.push(value)
  combo.need = Math.min(combo.attrs.length, (combo.need || 0) + 1)
}

/** 删一个属性：need 自动 -1（最小 2）；属性总数最少留 2 个 */
function removeComboAttr(ci: number, ai: number) {
  const combo = draft.combos[ci]
  if (combo.attrs.length <= 2) return // 至少保留 2 个属性
  combo.attrs.splice(ai, 1)
  combo.need = Math.max(2, Math.min(combo.attrs.length, (combo.need || 2) - 1))
}

/** need 选择框的可选值：2 ~ 属性个数 */
function needOptions(ci: number): number[] {
  const n = draft.combos[ci].attrs.length
  const out: number[] = []
  for (let i = 2; i <= Math.max(2, n); i++) out.push(i)
  return out
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
    .filter((c) => c.attrs.length >= 2)
    .map((c) => ({
      ...c,
      need: Math.max(2, Math.min(c.need || c.attrs.length, c.attrs.length)),
    }))
  draft.attr = Object.fromEntries(Object.entries(draft.attr).filter(([, v]) => Number(v)))
  // 阶级：运算符非法回退 >=，数值取整
  const rank = draft.target.rank || { op: '>=', value: 0 }
  draft.target.rank = {
    op: RANK_OPS.some((o) => o.op === rank.op) ? rank.op : '>=',
    value: Math.trunc(Number(rank.value) || 0),
  }
  emit('save', JSON.parse(JSON.stringify(draft)))
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div class="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
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

    <div class="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-4 text-[13px]">
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
      </section>

      <!-- 目标装备 -->
      <section class="rounded border border-white/10 p-3">
        <div class="mb-2 text-[12px] text-gray-400">目标装备</div>

        <label class="mb-3 flex items-center gap-2">
          <span class="text-[11px] text-gray-500">基础分</span>
          <input
            v-model.number="draft.base_score"
            type="number"
            step="1"
            class="w-24 rounded border border-white/10 bg-ink-700 px-2 py-1 outline-none"
          />
          <span class="text-[10.5px] text-gray-600">默认 0；符合下面目标条件就先加这个分</span>
        </label>

        <div class="mb-3 flex items-center gap-4">
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
        <div class="mb-3 flex items-center gap-2">
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
          <span class="text-[10.5px] text-gray-600">默认 ≥0（不限制阶级）</span>
        </div>

        <div class="mb-3 flex items-center gap-4">
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
          <input
            v-model="equipQuery"
            placeholder="搜索装备名或 id…"
            class="w-full rounded border border-white/10 bg-ink-700 px-2 py-1 outline-none"
          />
          <div v-if="equipHits.length" class="max-h-40 overflow-auto rounded border border-white/10">
            <button
              v-for="c in equipHits"
              :key="c.id"
              class="flex w-full items-center gap-2 px-2 py-1 text-left text-[12px] hover:bg-white/5"
              :class="draft.target.equipment_ids.includes(c.id) ? 'text-gold-300' : 'text-gray-300'"
              @click="toggleEquip(c.id)"
            >
              <span class="flex-1">{{ c.name }}</span>
              <span class="text-[10.5px] text-gray-500">{{ c.part }} · {{ c.rank }}阶</span>
            </button>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="e in pickedEquips"
              :key="e.id"
              class="flex items-center gap-1 rounded border border-gold-400/40 bg-gold-400/10 px-1.5 py-0.5 text-[11.5px] text-gold-300"
            >
              {{ e.name }}
              <button class="text-gray-400 hover:text-rose-300" @click="toggleEquip(e.id)">✕</button>
            </span>
            <span v-if="!pickedEquips.length" class="text-[11px] text-gray-600">尚未选择装备</span>
          </div>
        </div>

        <div class="mt-2 text-[11px] text-gray-500">当前范围：{{ targetSummary }}</div>
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

      <!-- 组合分：按钮各自独立，有组合时上一个下一个，没有时只留下面那个 -->
      <section class="rounded border border-white/10 p-3">
        <div class="mb-2 text-[12px] text-gray-400">组合分</div>
        <div class="space-y-2">
          <button
            v-if="draft.combos.length"
            class="w-[92px] rounded border border-white/10 px-2 py-1 text-[11px] text-gray-300 hover:bg-white/5"
            @click="addCombo"
          >＋ 添加组合</button>
          <div
            v-for="(c, ci) in draft.combos"
            :key="ci"
            class="space-y-1.5 rounded bg-ink-700 px-2 py-1.5"
          >
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

            <!-- 满足 X 个 / 分数 / 删除组合 -->
            <div class="flex flex-wrap items-center gap-1.5 text-[11px] text-gray-400">
              <span>满足</span>
              <select
                v-model.number="c.need"
                class="rounded border border-white/10 bg-ink-800 px-1 py-0.5 text-[11.5px]"
              >
                <option v-for="n in needOptions(ci)" :key="n" :value="n">{{ n }}</option>
              </select>
              <span>个</span>
              <span class="ml-1">分数</span>
              <input
                v-model.number="c.bonus"
                type="number"
                class="w-14 rounded border border-white/10 bg-ink-800 px-1.5 py-0.5 text-right tabular-nums outline-none"
              />
              <button class="ml-auto text-gray-500 hover:text-rose-300" title="删除这个组合" @click="removeCombo(ci)">✕</button>
            </div>
          </div>
          <div v-if="!draft.combos.length" class="text-[11px] text-gray-600">还没有组合规则</div>
          <button
            class="w-[92px] rounded border border-white/10 px-2 py-1 text-[11px] text-gray-300 hover:bg-white/5"
            @click="addCombo"
          >＋ 添加组合</button>
        </div>
      </section>
      </div>
    </div>
  </div>
</template>
