<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EquipIcon from './EquipIcon.vue'
import type { ScanItem } from '@/types'

const props = defineProps<{ items: ScanItem[] }>()
const emit = defineEmits<{ (e: 'calibrate', item: ScanItem): void }>()

type Filter = 'all' | 'todo' | 'ok'
const filter = ref<Filter>('all')

type LockFilter = 'all' | 'locked' | 'unlocked'
const lockFilter = ref<LockFilter>('all')
const lockFilters: { key: LockFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'locked', label: '锁定' },
  { key: 'unlocked', label: '未锁定' },
]

/** 大类型（= 装备部位），按此顺序排列，未列出的排在后面 */
const PART_ORDER = ['单手武器', '双手武器', '盾', '头', '胴', '脚', '饰品']
const partFilter = ref('')

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

const sortBy = ref<'idx' | 'score'>('idx')

const todoCount = computed(
  () => props.items.filter((i) => i.match_status === 'fuzzy' || i.match_status === 'none').length,
)
const lockedCount = computed(() => props.items.filter((i) => i.locked).length)

const partList = computed(() => {
  const counts = new Map<string, number>()
  for (const it of props.items) {
    if (it.part) counts.set(it.part, (counts.get(it.part) || 0) + 1)
  }
  const rank = (p: string) => {
    const n = PART_ORDER.indexOf(p)
    return n < 0 ? PART_ORDER.length : n
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name))
})

// 类型/匹配条件失效时回落到「全部」，避免筛出空列表
watch(partList, (list) => {
  if (partFilter.value && !list.some((p) => p.name === partFilter.value)) partFilter.value = ''
})
watch(todoCount, (n) => {
  if (!n && filter.value !== 'all') filter.value = 'all'
})

const rows = computed(() => {
  let list = props.items
  if (partFilter.value) list = list.filter((i) => i.part === partFilter.value)
  if (filter.value === 'todo') {
    list = list.filter((i) => i.match_status === 'fuzzy' || i.match_status === 'none')
  } else if (filter.value === 'ok') {
    list = list.filter((i) => i.match_status === 'ok' || i.match_status === 'alias')
  }
  if (lockFilter.value === 'locked') list = list.filter((i) => i.locked)
  else if (lockFilter.value === 'unlocked') list = list.filter((i) => !i.locked)
  return sortBy.value === 'score'
    ? [...list].sort((a, b) => b.score - a.score)
    : [...list].sort((a, b) => a.idx - b.idx)
})

</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2">
      <select
        v-model="partFilter"
        class="rounded-md border border-white/10 bg-ink-700 px-2 py-1 text-xs text-gray-300 outline-none focus:ring-1 focus:ring-gold-400/40"
        title="按大类型筛选"
      >
        <option value="">全部类型</option>
        <option v-for="p in partList" :key="p.name" :value="p.name">{{ p.name }}（{{ p.count }}）</option>
      </select>
      <div v-if="todoCount" class="flex overflow-hidden rounded-md border border-white/10 text-xs">
        <button
          v-for="f in ([['all', '全部'], ['todo', `待确认 ${todoCount}`], ['ok', '已匹配']] as const)"
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

    <div class="min-h-0 flex-1 overflow-auto">
      <table class="w-full border-separate border-spacing-0 text-[13px]">
        <thead class="sticky top-0 z-10 bg-ink-800 text-xs text-gray-400">
          <tr>
            <th class="w-12 border-b border-white/10 px-2 py-1.5 text-left font-normal">#</th>
            <th class="w-16 border-b border-white/10 px-2 py-1.5 text-right font-normal">评分</th>
            <th class="min-w-[180px] border-b border-white/10 px-2 py-1.5 text-left font-normal">装备</th>
            <th class="w-20 border-b border-white/10 px-2 py-1.5 text-left font-normal">星级</th>
            <th class="w-10 border-b border-white/10 px-2 py-1.5 text-left font-normal">阶</th>
            <th
              v-for="n in 4"
              :key="n"
              class="border-b border-white/10 px-2 py-1.5 text-left font-normal"
            >加护{{ n }}</th>
            <th class="w-28 border-b border-white/10 px-2 py-1.5 text-left font-normal">规则</th>
            <th class="w-14 border-b border-white/10 px-2 py-1.5"></th>
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
              :title="it.rule_id
                ? (it.base_score ? `基础分 ${it.base_score} + ` : '') +
                  `属性分 ${it.attr_score} + 组合分 ${it.combo_score}` +
                  (it.hit_combos.length ? `\n命中组合: ${it.hit_combos.join('、')}` : '')
                : '没有任何规则匹配这件装备'"
            >
              {{ it.score }}
            </td>

            <!-- 图标 + 名称合一，锁定角标叠在图标上 -->
            <td class="border-b border-white/5 px-2 py-1">
              <div class="flex items-center gap-2">
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
                      :title="it.raw_name && it.raw_name !== it.name ? `OCR: ${it.raw_name}` : ''"
                    >{{ it.name }}</span>
                    <span v-if="it.reinforce" class="shrink-0 rounded bg-white/10 px-1 text-[11px] text-gray-300">
                      +{{ it.reinforce }}
                    </span>
                    <span v-if="it.is_special" class="shrink-0 text-[11px] text-gold-400">特殊</span>
                  </span>
                </span>
              </div>
            </td>

            <td class="border-b border-white/5 px-2 py-1" :class="qualityClass(it.color)">
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
              class="border-b border-white/5 px-2 py-1 text-[11.5px]"
            >
              <span v-if="it.blessings[n - 1]" class="text-gray-300">{{ it.blessings[n - 1] }}</span>
              <span v-else class="text-gray-600">—</span>
            </td>

            <td class="border-b border-white/5 px-2 py-1 text-[11.5px]">
              <span v-if="it.rule_name" class="text-sky-300/90" :title="it.rule_name">
                {{ it.rule_name }}
              </span>
              <span v-else class="text-gray-600">未匹配</span>
            </td>

            <td class="border-b border-white/5 px-2 py-1">
              <button
                v-if="it.match_status !== 'ok'"
                class="rounded border border-white/10 px-1.5 py-0.5 text-[11px] text-gray-400 opacity-0 transition group-hover:opacity-100 hover:text-gold-300"
                @click="emit('calibrate', it)"
              >校准</button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="11" class="px-3 py-10 text-center text-gray-600">
              {{ items.length ? '当前筛选下没有记录' : '点击「开始扫描」逐件读取装备' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
