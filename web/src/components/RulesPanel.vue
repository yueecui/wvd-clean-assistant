<script setup lang="ts">
import { computed, ref } from 'vue'
import RuleEditor from './RuleEditor.vue'
import * as api from '@/api'
import { qualityLabel } from '@/quality'
import { DEFAULT_RULE_COLOR, RULE_COLORS } from '@/rule-colors'
import { persistedEnum } from '@/storage'
import type { AttrGroups, CatalogItem, EquipType, ScoreRule } from '@/types'

const props = defineProps<{
  rules: ScoreRule[]
  types: EquipType[]
  attrs: string[]
  attrGroups: AttrGroups
  catalog: CatalogItem[]
}>()

const emit = defineEmits<{ (e: 'changed'): void }>()

/** 项目里所有规则用过的、不在预设中的颜色（去重，按出现顺序），编辑器里可直接复用 */
const extraColors = computed(() => {
  const preset = new Set(RULE_COLORS.map((c) => c.hex.toLowerCase()))
  const out: string[] = []
  for (const r of props.rules) {
    const c = (r.color || '').toLowerCase()
    if (/^#[0-9a-f]{6}$/.test(c) && !preset.has(c) && !out.includes(c)) out.push(c)
  }
  return out
})

const editing = ref<ScoreRule | null>(null)
const isNew = ref(false)

const PAGE_TABS = [
  { key: 'all', label: '全部' },
  { key: 'lt20', label: '强化<20' },
  { key: 'eq20', label: '强化=20' },
] as const
type PageKey = (typeof PAGE_TABS)[number]['key']

/** 分类分页：记住上次停在哪一页（localStorage，键 wvd.rules.page） */
const page = persistedEnum<PageKey>(
  'rules.page',
  PAGE_TABS.map((t) => t.key),
  'all',
)

/** 与后端匹配顺序一致：按特定装备的规则始终在前，同组内优先级从大到小 */
const sorted = computed(() =>
  [...props.rules].sort((a, b) => {
    const ka = a.target.mode === 'equipment' ? 0 : 1
    const kb = b.target.mode === 'equipment' ? 0 : 1
    return ka - kb || b.priority - a.priority
  }),
)
const paged = computed(() =>
  page.value === 'all' ? sorted.value : sorted.value.filter((r) => r.target.reinforce === page.value),
)

const toast = ref('')
let toastTimer: number | undefined

function showToast(msg: string) {
  toast.value = msg
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => (toast.value = ''), 1600)
}

function blank(): ScoreRule {
  return {
    id: 'r_' + Math.random().toString(16).slice(2, 10),
    name: '新规则',
    priority: 100,
    enabled: true,
    note: '',
    color: DEFAULT_RULE_COLOR,
    target: {
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
    },
    base_score: 0,
    attr: {},
    combos: [],
    rank_scores: {},
    star_scores: {},
  }
}

function create() {
  editing.value = blank()
  isNew.value = true
}

function edit(rule: ScoreRule) {
  editing.value = JSON.parse(JSON.stringify(rule))
  isNew.value = false
}

function duplicate(rule: ScoreRule) {
  const copy = JSON.parse(JSON.stringify(rule)) as ScoreRule
  copy.id = 'r_' + Math.random().toString(16).slice(2, 10)
  copy.name = rule.name + '（副本）'
  editing.value = copy
  isNew.value = true
}

async function save(rule: ScoreRule) {
  try {
    const r = await api.saveRule(rule)
    editing.value = r.rule // 保存后保持展示
    isNew.value = false
    showToast('已保存')
    emit('changed')
  } catch (e) {
    alert(String(e).replace(/^Error:\s*/, ''))
  }
}

async function openDir() {
  try {
    await api.openRulesDir()
  } catch (e) {
    alert(String(e).replace(/^Error:\s*/, ''))
  }
}

async function remove(rule: ScoreRule) {
  if (!confirm(`删除规则「${rule.name}」？`)) return
  await api.deleteRule(rule.id)
  if (editing.value?.id === rule.id) editing.value = null
  showToast('已删除')
  emit('changed')
}

async function toggle(rule: ScoreRule) {
  try {
    await api.saveRule({ ...rule, enabled: !rule.enabled })
    emit('changed')
  } catch (e) {
    alert(String(e).replace(/^Error:\s*/, ''))
  }
}

const RANK_OP_TEXT: Record<string, string> = { '>=': '≥', '>': '>', '=': '=', '<': '<', '<=': '≤' }

/** 分数设定摘要：基础分 + 阶级分 + 星级分 + 属性权重数 + 类型分；为 0 / 空的项不显示 */
function scoreText(r: ScoreRule) {
  const parts: string[] = []
  const base = Number(r.base_score) || 0
  if (base) parts.push(`基础 ${base}`)
  const fmt = (m?: Record<string, number>) => {
    const keys = Object.keys(m || {})
      .filter((k) => Number((m as Record<string, number>)[k]))
      .sort((a, b) => Number(a) - Number(b))
    if (!keys.length) return ''
    const shown = keys.slice(0, 3).map((k) => `${k}→${(m as Record<string, number>)[k]}`)
    return shown.join(' ') + (keys.length > 3 ? ` 等${keys.length}档` : '')
  }
  const rk = fmt(r.rank_scores)
  if (rk) parts.push(`阶级 ${rk}`)
  const st = fmt(r.star_scores)
  if (st) parts.push(`星级 ${st}`)
  const attrN = Object.keys(r.attr || {}).length
  if (attrN) parts.push(`${attrN} 属性`)
  const comboN = (r.combos || []).length
  if (comboN) parts.push(`${comboN} 类型分`)
  return parts.join(' · ')
}

function targetText(r: ScoreRule) {
  const reinf = r.target.reinforce === 'eq20' ? '=20' : '<20'
  const rk = r.target.rank || { op: '>=', value: 0 }
  const rank = rk.value === 0 && rk.op === '>=' ? '' : ` · 阶级${RANK_OP_TEXT[rk.op] || '≥'}${rk.value}`
  const st = r.target.stars || { op: '>=', value: 1 }
  const star = st.value === 1 && st.op === '>=' ? '' : ` · 星级${RANK_OP_TEXT[st.op] || '≥'}${st.value}`
  const cl = r.target.color || { op: '>=', value: 1 }
  const color = cl.value === 1 && cl.op === '>=' ? '' : ` · 颜色${RANK_OP_TEXT[cl.op] || '≥'}${qualityLabel(cl.value)}`
  const brief = (list: string[]) =>
    `${list.slice(0, 2).join('/')}${list.length > 2 ? '等' : ''}`
  const must = r.target.attrs || []
  const opt = r.target.attrs_opt || []
  const want =
    (must.length ? ` · 必有 ${brief(must)}` : '') +
    (opt.length ? ` · 可选${r.target.attr_need || 1}项(${brief(opt)})` : '')
  if (r.target.mode === 'types') {
    const names = r.target.types
      .map((id) => props.types.find((t) => t.id === id)?.name)
      .filter(Boolean) as string[]
    return `强化${reinf}${rank}${star}${color}${want} · ${names.slice(0, 3).join('/') || '无类型'}${names.length > 3 ? ` 等${names.length}种` : ''}`
  }
  return `强化${reinf}${rank}${star}${color}${want} · ${r.target.equipment_ids.length} 件指定装备`
}


</script>

<template>
  <div class="flex min-h-0 flex-1">
    <!-- 列表 -->
    <div class="flex w-[340px] shrink-0 flex-col border-r border-white/10">
      <div class="flex items-center gap-2 border-b border-white/10 px-3 py-2">
        <span class="text-[13px] text-gray-300">规则（{{ paged.length }}/{{ rules.length }}）</span>
        <div class="ml-auto flex gap-1.5 text-[11.5px]">
          <button class="rounded bg-gold-400 px-2 py-1 font-medium text-black" @click="create">+ 新建</button>
          <button class="rounded border border-white/10 px-2 py-1 text-gray-300 hover:bg-white/5" @click="openDir">
            打开规则目录
          </button>
        </div>
      </div>

      <!-- 分页（分类） -->
      <div class="flex items-center gap-1 border-b border-white/10 px-2 py-1.5">
        <button
          v-for="p in PAGE_TABS"
          :key="p.key"
          class="flex-1 rounded px-2 py-1 text-[11.5px] transition"
          :class="page === p.key ? 'bg-white/10 text-gray-100' : 'text-gray-500 hover:bg-white/5'"
          @click="page = p.key"
        >{{ p.label }}</button>
      </div>

      <div class="min-h-0 flex-1 overflow-auto p-2">
        <div
          v-for="r in paged"
          :key="r.id"
          class="mb-1.5 cursor-pointer rounded border px-2.5 py-2 transition"
          :class="editing?.id === r.id ? 'border-gold-400/50 bg-gold-400/5' : 'border-white/10 hover:border-white/20'"
          @click="edit(r)"
        >
          <div class="flex items-center gap-2">
            <input
              type="checkbox"
              :checked="r.enabled"
              class="accent-gold-400"
              :title="r.enabled ? '已启用' : '已停用'"
              @click.stop
              @change="toggle(r)"
            />
            <span
              class="flex-1 truncate text-[13px]"
              :style="{ color: r.color || DEFAULT_RULE_COLOR, opacity: r.enabled ? 1 : 0.5 }"
            >{{ r.name }}</span>
            <span class="rounded bg-white/5 px-1 text-[10.5px] tabular-nums text-gray-400">P{{ r.priority }}</span>
          </div>
          <div class="mt-1 text-[11px] text-gray-500">{{ targetText(r) }}</div>
          <div class="mt-1 flex items-center gap-2 text-[11px] text-gray-600">
            <span class="truncate" :title="scoreText(r)">{{ scoreText(r) || '未设分数' }}</span>
            <div class="ml-auto flex shrink-0 gap-1.5">
              <button class="hover:text-sky-300" @click.stop="duplicate(r)">复制</button>
              <button class="hover:text-rose-300" @click.stop="remove(r)">删除</button>
            </div>
          </div>
        </div>
        <div v-if="!paged.length" class="px-2 py-8 text-center text-[12px] text-gray-600">
          {{ rules.length ? '这一分类下还没有规则' : '还没有规则，点「+ 新建」开始' }}
        </div>
      </div>
    </div>

    <!-- 编辑区 -->
    <div class="flex min-w-0 flex-1 flex-col">
      <RuleEditor
        v-if="editing"
        :key="editing.id"
        :rule="editing"
        :is-new="isNew"
        :types="types"
        :attrs="attrs"
        :attr-groups="attrGroups"
        :catalog="catalog"
        :extra-colors="extraColors"
        @save="save"
        @cancel="editing = null"
      />
      <div v-else class="flex h-full flex-col items-center justify-center gap-2 text-[12px] text-gray-600">
        <div>选择左侧规则编辑，或新建一条</div>
      </div>
    </div>

    <!-- toast -->
    <div
      v-if="toast"
      class="pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-md border border-emerald-400/40 bg-emerald-500/15 px-4 py-1.5 text-[13px] text-emerald-200 shadow-lg backdrop-blur"
    >{{ toast }}</div>
  </div>
</template>
