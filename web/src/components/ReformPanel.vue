<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as api from '../api'
import MaterialScanModal from './MaterialScanModal.vue'
import ReformStartModal from './ReformStartModal.vue'
import type { AttrRow, ReformConfigSave, ReformSnap, ReformStone, StoneGridRow } from '../types'

type ScanMode = 'full' | 'flat'
interface MatGridRow { label: string; attr: string; pct: boolean; cells: ReformStone[] }

const materials = ref<ReformStone[]>([])
const stoneGrid = ref<StoneGridRow[]>([])
const materialsAt = ref(0)
const chosenStones = ref<ReformStone[]>([])
const reformAttrs = ref<string[]>([])
const attrRows = ref<AttrRow[]>([])
const maxTry = ref(2)
/** 素材定位方式：slider=拖右侧滚动条（快），scroll=逐页滚动（老方案，可切回） */
const materialsJump = ref<'slider' | 'scroll'>('slider')
const busy = ref(false)
const errMsg = ref('')
const notice = ref('')
const showMaterialScan = ref(false)
const showReformStart = ref(false)
const pendingScanRefresh = ref(false)
const snap = ref<ReformSnap>({
  status: { running: false, phase: 'idle', total: 0, done: 0, current: '', error: null },
  logs: [], results: [],
})

const toast = ref<{ text: string; kind: 'info' | 'error' } | null>(null)
let timer: number | undefined
let toastTimer: number | undefined

function showToast(text: string, kind: 'info' | 'error' = 'info') {
  toast.value = { text, kind }
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = null }, kind === 'error' ? 4000 : 2500)
}
watch(notice, (v) => { if (v) showToast(v) })
watch(errMsg, (v) => { if (v) showToast(v, 'error') })
watch(() => snap.value.status.error, (v) => { if (v) showToast(v, 'error') })

const running = computed(() => snap.value.status.running)
const phase = computed(() => snap.value.status.phase)
const scanning = computed(() => running.value && phase.value.startsWith('scan'))
const reforming = computed(() => running.value && !scanning.value)
const scanStopping = computed(() => phase.value === 'scan_stopping')
const reformStopping = computed(() => phase.value === 'stopping')
const PHASE_TEXT: Record<string, string> = {
  idle: '空闲', start: '准备中', running: '执行中', scan: '扫描素材中',
  scan_stopping: '正在停止扫描……', stopping: '正在停止……',
  stopped: '已停止', done: '已完成', error: '出错',
}
const phaseText = computed(() => PHASE_TEXT[phase.value] || phase.value)
const stoneLabel = (m: ReformStone) => `${m.grade ? `${m.grade}★` : '?★'} ${m.pct ? '百分比' : '固定值'}`

const now = ref(Date.now())
function clockText(ts?: number | null) {
  return ts ? new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : ''
}
function durationText(sec: number) {
  const n = Math.max(0, Math.floor(sec))
  const h = Math.floor(n / 3600), m = Math.floor(n / 60) % 60, s = n % 60
  const pad = (x: number) => String(x).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}
/** 运行中显示实时持续时间，结束后固定显示总用时 */
const taskTime = computed(() => {
  const st = snap.value.status
  if (!st.started_at) return ''
  const end = st.finished_at ? st.finished_at * 1000
    : (st.running ? now.value : st.started_at * 1000)
  const used = durationText((end - st.started_at * 1000) / 1000)
  const label = st.task || '任务'
  return st.finished_at
    ? `${label} · 开始 ${clockText(st.started_at)} · 结束 ${clockText(st.finished_at)} · 总用时 ${used}`
    : `${label} · 开始 ${clockText(st.started_at)} · 已用 ${used}`
})
const chosenKeys = computed(() => chosenStones.value.map((s) => s.key))
/** 数量只认素材表（左侧列表 / 扫描结果），右侧已选石头不再单独记一份 */
const matByKey = computed(() => {
  const map = new Map<string, ReformStone>()
  materials.value.forEach((m) => map.set(m.key, m))
  return map
})
/** 该石头在素材表里的持有量；null = 表里没有（没扫到 / 还没扫过），数量未知 */
function stoneStock(s: ReformStone): number | null {
  const m = matByKey.value.get(s.key)
  return m ? (m.count || 0) : null
}
function stockText(s: ReformStone): string {
  const n = stoneStock(s)
  return n === null ? 'x?' : `x${n}`
}
/** 合计 = 已选石头在素材表里的数量之和 */
const chosenCount = computed(() => chosenStones.value.reduce((n, s) => n + (stoneStock(s) ?? 0), 0))
const hasUnknown = computed(() => chosenStones.value.some((s) => stoneStock(s) === null))

type ResultTab = 'all' | 'ok' | 'other'
const RESULT_TABS: { key: ResultTab; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'ok', label: '只看已改造' },
  { key: 'other', label: '跳过/失败' },
]
const resultTab = ref<ResultTab>('all')
const filteredResults = computed(() => {
  const list = snap.value.results
  if (resultTab.value === 'ok') return list.filter((r) => r.state === 'ok')
  if (resultTab.value === 'other') return list.filter((r) => r.state !== 'ok')
  return list
})
const okCount = computed(() => snap.value.results.filter((r) => r.state === 'ok').length)

const resultList = ref<HTMLElement | null>(null)
const logList = ref<HTMLElement | null>(null)

/** 停在底部时才自动跟随新内容；手动上翻查看历史不会被强行拉回 */
function autoFollow(el: HTMLElement | null) {
  if (!el || el.scrollHeight - el.scrollTop - el.clientHeight > 80) return
  void nextTick(() => { el.scrollTop = el.scrollHeight })
}
watch([() => filteredResults.value.length, resultTab], () => autoFollow(resultList.value))
watch(() => snap.value.logs, () => autoFollow(logList.value))

function emptyStone(): ReformStone {
  return { attr: '', lo: 0, hi: 0, pct: false, grade: null, count: 0, text: '', key: '' }
}

/** 每行 6 列：类型 + 1★~5★ 数量按钮；按数值表列全，没扫描过也能直接选石头 */
const matGrid = computed<MatGridRow[]>(() => {
  const order = new Map<string, number>()
  attrRows.value.forEach((r, i) => order.set(r.base, i))
  const byKey = new Map<string, ReformStone>()
  materials.value.forEach((m) => byKey.set(m.key, m))
  let rows: MatGridRow[]
  if (stoneGrid.value.length) {
    rows = stoneGrid.value.map((g) => ({
      label: g.label, attr: g.attr, pct: g.pct,
      cells: g.cells.map((c) => byKey.get(c.key) || ({
        attr: g.attr, lo: c.lo, hi: c.hi, pct: g.pct, grade: c.grade,
        count: 0, key: c.key, text: `${c.key}x?`, unscanned: true,
      } as ReformStone)),
    }))
  } else {
    // 兼容未返回骨架的旧后端：按已扫描素材分组
    const byLabel = new Map<string, MatGridRow>()
    for (const m of materials.value) {
      const label = `${m.attr}${m.pct ? '%' : ''}`
      let row = byLabel.get(label)
      if (!row) {
        row = {
          label, attr: m.attr, pct: m.pct,
          cells: [emptyStone(), emptyStone(), emptyStone(), emptyStone(), emptyStone()],
        }
        byLabel.set(label, row)
      }
      const g = m.grade || 0
      const old = g >= 1 && g <= 5 ? row.cells[g - 1] : emptyStone()
      if (g >= 1 && g <= 5 && (!old.count || m.count > old.count)) row.cells[g - 1] = m
    }
    rows = [...byLabel.values()]
  }
  return rows.sort((a, b) => {
    const ai = order.get(a.attr) ?? 999
    const bi = order.get(b.attr) ?? 999
    return ai - bi || Number(a.pct) - Number(b.pct) || a.label.localeCompare(b.label)
  })
})

/** 属性表分成左右两栏，一次显示全部，不出现滚动条 */
const attrColumns = computed<AttrRow[][]>(() => {
  const half = Math.ceil(attrRows.value.length / 2)
  return [attrRows.value.slice(0, half), attrRows.value.slice(half)]
})

function usable(m: ReformStone) {
  return m.grade === 1 || m.grade === 2
}

function buildConfig(): ReformConfigSave {
  return {
    reform_attrs: reformAttrs.value.slice(),
    // 石头只存身份和优先级，持有量一律由素材表提供（执行时也会到游戏列表里现找）
    stones: chosenStones.value.map((m) => ({
      attr: m.attr, lo: m.lo, hi: m.hi, pct: m.pct,
      grade: m.grade, count: 0, text: '', key: m.key,
    })),
    max_try: maxTry.value,
    materials_jump: materialsJump.value,
  }
}

async function loadAll() {
  try {
    const c = await api.getReformConfig()
    reformAttrs.value = c.reform_attrs || []
    maxTry.value = c.max_try || 2
    materialsJump.value = c.materials_jump === 'scroll' ? 'scroll' : 'slider'
    materials.value = c.materials || []
    stoneGrid.value = c.stone_grid || []
    materialsAt.value = c.materials_at || 0
    chosenStones.value = (c.stones || []).map((s) => ({ ...s }))
    const r = await api.getRules()
    attrRows.value = r.attr_groups?.rows || []
  } catch (e) {
    errMsg.value = String(e)
  }
}

async function refreshMaterials() {
  const c = await api.getReformConfig()
  // 只更新素材表：执行中后端会把沿途读到的真实数量写回这里，
  // 右侧已选石头的数量直接由它计算（见 matByKey / stoneStock），不用再同步一份
  materials.value = c.materials || []
  materialsAt.value = c.materials_at || 0
}

let pollTicks = 0

async function poll() {
  try {
    pollTicks++
    now.value = Date.now()
    snap.value = await api.getReformStatus()
    // 扫描中每轮刷新；改造中每 2 轮刷新（后端沿途把素材数量写回配置）
    if (pendingScanRefresh.value || (reforming.value && pollTicks % 2 === 0)) {
      await refreshMaterials()
    }
    if (pendingScanRefresh.value && !snap.value.status.running) {
      pendingScanRefresh.value = false
      const p = snap.value.status.phase
      // error 由 status.error 的 watch 弹红色 toast，避免重复提示
      if (p !== 'error') {
        notice.value = p === 'stopped'
          ? '扫描已停止，已保存扫到的素材'
          : '扫描完成，素材已保存（刷新页面不会丢失）'
      }
    }
  } catch (e) {
    errMsg.value = String(e)
  }
}

async function startMaterialScan(mode: ScanMode) {
  if (running.value || busy.value) return
  busy.value = true
  errMsg.value = ''
  notice.value = mode === 'flat'
    ? '正在扫描固定值素材（遇到第一个百分比石头即停止）…'
    : '正在全量扫描素材…'
  try {
    const r = await api.scanReformMaterials(mode)
    if (!r.ok) {
      errMsg.value = r.error || '扫描启动失败'
      notice.value = ''
      return
    }
    pendingScanRefresh.value = true
    await poll()
  } catch (e) {
    errMsg.value = String(e)
    notice.value = ''
  } finally {
    busy.value = false
  }
}

function onScanClick() {
  if (scanning.value) {
    if (!scanStopping.value) void requestStop('scan')
    return
  }
  if (reforming.value || busy.value) return
  showMaterialScan.value = true
}

function onMaterialScan(mode: ScanMode) {
  showMaterialScan.value = false
  void startMaterialScan(mode)
}

function onReformClick() {
  if (reforming.value) {
    if (!reformStopping.value) void requestStop('reform')
    return
  }
  if (scanning.value || busy.value) return
  showReformStart.value = true
}

function onReformStart() {
  showReformStart.value = false
  void start()
}

async function requestStop(kind: 'scan' | 'reform') {
  try {
    // 立即反馈：按钮变「停止中」并禁用，直到后台线程真正结束
    snap.value.status.phase = kind === 'scan' ? 'scan_stopping' : 'stopping'
    await api.stopReform()
    await poll()
  } catch (e) {
    errMsg.value = String(e)
  }
}

function addStone(m: ReformStone) {
  if (!usable(m) || chosenKeys.value.includes(m.key) || running.value) return
  chosenStones.value = [...chosenStones.value, { ...m }]
}

function removeStone(key: string) {
  chosenStones.value = chosenStones.value.filter((m) => m.key !== key)
}

function moveStone(key: string, delta: number) {
  const i = chosenStones.value.findIndex((m) => m.key === key)
  const j = i + delta
  if (i < 0 || j < 0 || j >= chosenStones.value.length) return
  const next = chosenStones.value.slice()
  ;[next[i], next[j]] = [next[j], next[i]]
  chosenStones.value = next
}

/** 该属性（固定值或百分比任一）是否已勾选 */
function attrChecked(row: AttrRow) {
  return reformAttrs.value.includes(row.key)
    || (!!row.pct_key && reformAttrs.value.includes(row.pct_key))
}

function toggleReform(key: string) {
  if (!key || running.value) return
  reformAttrs.value = reformAttrs.value.includes(key)
    ? reformAttrs.value.filter((k) => k !== key)
    : [...reformAttrs.value, key]
}

async function start() {
  if (running.value || busy.value) return
  if (!chosenStones.value.length) {
    errMsg.value = '请先从持有素材表添加至少一种 1★/2★ 改造石（未扫描可直接点 +）'
    return
  }
  if (!reformAttrs.value.length) {
    errMsg.value = '请先勾选需要改造的属性'
    return
  }
  busy.value = true
  errMsg.value = ''
  notice.value = ''
  try {
    const cfg = buildConfig()
    await api.saveReformConfig(cfg)
    const r = await api.startReform(cfg)
    if (!r.ok) errMsg.value = r.error || '启动失败'
    await poll()
  } catch (e) {
    errMsg.value = String(e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  await loadAll()
  await poll()
  timer = window.setInterval(() => { void poll() }, 1000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  if (toastTimer) window.clearTimeout(toastTimer)
})
</script>

<template>
  <div class="flex min-h-0 flex-1">
    <div
      v-if="toast"
      class="pointer-events-none fixed bottom-6 left-1/2 z-50 max-w-[80vw] -translate-x-1/2 rounded-md border px-4 py-1.5 text-[13px] shadow-lg backdrop-blur"
      :class="toast.kind === 'error' ? 'border-rose-400/40 bg-rose-500/15 text-rose-200' : 'border-emerald-400/40 bg-emerald-500/15 text-emerald-200'"
    >{{ toast.text }}</div>
    <MaterialScanModal
      :open="showMaterialScan"
      :busy="busy"
      @close="showMaterialScan = false"
      @scan="onMaterialScan"
    />
    <ReformStartModal
      :open="showReformStart"
      :busy="busy"
      :chosen="chosenStones.length"
      :attrs="reformAttrs.length"
      @close="showReformStart = false"
      @start="onReformStart"
    />
    <section class="flex min-w-0 flex-1 flex-col">
      <div class="relative flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
        <button
          class="rounded px-3 py-1.5 text-[13px] disabled:opacity-40"
          :class="scanning
            ? (scanStopping ? 'border border-amber-400/50 text-amber-300' : 'border border-rose-400/40 text-rose-300')
            : 'border border-white/10 text-gray-200 hover:bg-white/5'"
          :disabled="(scanning && (scanStopping || busy)) || (!scanning && (reforming || busy))"
          @click="onScanClick"
        >{{ scanning ? (scanStopping ? '停止中……' : '■ 停止扫描') : '扫描素材' }}</button>
        <button
          class="rounded px-3 py-1.5 text-[13px] font-medium disabled:opacity-40"
          :class="reforming
            ? (reformStopping ? 'border border-amber-400/50 text-amber-300' : 'border border-rose-400/40 text-rose-300')
            : 'bg-gold-400 text-black'"
          :disabled="(reforming && (reformStopping || busy)) || (!reforming && (scanning || busy))"
          @click="onReformClick"
        >{{ reforming ? (reformStopping ? '停止中……' : '■ 停止') : '▶ 开始改造' }}</button>
        <span class="ml-2 text-xs text-gray-400">
          {{ phaseText }} · {{ scanning ? '已收集' : '已处理' }} {{ snap.status.done }}
          <span v-if="snap.status.current" class="text-gray-500"> · {{ snap.status.current }}</span>
        </span>
        <span v-if="taskTime" class="ml-1 font-mono text-[11px] text-gray-500">{{ taskTime }}</span>
      </div>

      <!-- 需要改造的属性：勾选才改，无顺序 -->
      <div class="border-b border-white/10 px-3 py-2">
        <div class="mb-1 text-[12px] text-gray-400">
          需要改造的属性
          <span class="ml-2 text-gray-600">已勾选 {{ reformAttrs.length }} 项</span>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div v-for="(col, ci) in attrColumns" :key="ci" class="rounded border border-white/10">
            <div class="grid grid-cols-[1fr_64px_64px] bg-ink-800 text-[11px] text-gray-500">
              <span class="px-2 py-1">属性</span>
              <span class="px-2 py-1 text-center">固定值</span>
              <span class="px-2 py-1 text-center">百分比</span>
            </div>
            <div
              v-for="row in col"
              :key="row.base"
              class="grid grid-cols-[1fr_64px_64px] border-t border-white/5 text-[12px]"
              :class="attrChecked(row) ? 'bg-rose-400/[0.10]' : ''"
            >
              <span class="px-2 py-1" :class="attrChecked(row) ? 'text-rose-200' : 'text-gray-300'">{{ row.base }}</span>
              <label class="flex items-center justify-center">
                <input
                  v-if="row.key"
                  type="checkbox"
                  class="h-4 w-4 accent-rose-400"
                  :checked="reformAttrs.includes(row.key)"
                  :disabled="running"
                  @change="toggleReform(row.key)"
                />
                <span v-else class="text-[10px] text-gray-700">—</span>
              </label>
              <label class="flex items-center justify-center">
                <input
                  v-if="row.pct_key"
                  type="checkbox"
                  class="h-4 w-4 accent-rose-400"
                  :checked="reformAttrs.includes(row.pct_key)"
                  :disabled="running"
                  @change="toggleReform(row.pct_key)"
                />
                <span v-else class="text-[10px] text-gray-700">—</span>
              </label>
            </div>
          </div>
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-gray-500">
          单件选中重试上限
          <input
            v-model.number="maxTry"
            type="number"
            min="0"
            max="6"
            class="w-14 rounded border border-white/10 bg-ink-700 px-1.5 py-0.5 text-center text-gray-200 outline-none"
          />
          素材定位
          <select
            v-model="materialsJump"
            :disabled="running"
            class="rounded border border-white/10 bg-ink-700 px-1.5 py-0.5 text-gray-200 outline-none"
          >
            <option value="slider">拖滚动条跳转</option>
            <option value="scroll">逐页滚动</option>
          </select>
          <span class="text-gray-600">只允许 1★ / 2★ 石头；高级石头不可添加</span>
        </div>
      </div>

      <!-- 持有素材表格（每行 6 列）→ 点击 1★/2★ 加入使用列表 -->
      <div class="flex min-h-0 flex-1">
        <div class="flex min-w-0 flex-1 flex-col border-r border-white/10">
          <div class="border-b border-white/10 px-3 py-1.5 text-[12px] text-gray-400">
            持有素材（类型 + 1★~5★ 数量；点 1★/2★ 加入右侧）
          </div>
          <div class="min-h-0 flex-1 overflow-auto">
            <table class="w-full table-fixed border-collapse text-[12px]">
              <colgroup>
                <col class="w-[35%]" />
                <col v-for="g in 5" :key="g" class="w-[13%]" />
              </colgroup>
              <thead class="sticky top-0 bg-ink-800 text-[11px] text-gray-500">
                <tr>
                  <th class="px-2 py-1 text-left font-normal">类型</th>
                  <th v-for="g in 5" :key="g" class="px-2 py-1 text-center font-normal">{{ g }}★</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in matGrid" :key="row.label" class="border-t border-white/5">
                  <td class="px-2 py-1" :class="row.pct ? 'text-sky-300/80' : 'text-gray-300'">{{ row.label }}</td>
                  <td v-for="(m, i) in row.cells" :key="i" class="whitespace-nowrap px-1 py-1 text-center">
                    <button
                      v-if="m.count > 0 || (usable(m) && m.unscanned)"
                      class="w-full rounded px-1 py-0.5 tabular-nums transition disabled:cursor-not-allowed"
                      :class="!usable(m)
                        ? 'bg-white/[0.04] text-gray-300'
                        : (chosenKeys.includes(m.key) ? 'bg-emerald-400/15 text-emerald-300' : 'text-emerald-200 hover:bg-emerald-400/10')"
                      :disabled="!usable(m) || chosenKeys.includes(m.key) || running"
                      :title="m.unscanned ? (materialsAt ? '未扫到，数量未知（执行时确认）' : '未扫描，执行时自动读取数量') : m.key"
                      @click="addStone(m)"
                    >{{ m.count > 0 ? 'x' + m.count : '+' }}</button>
                    <span v-else class="text-gray-700">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="!materials.length" class="px-3 py-8 text-center text-[12px] text-gray-600">
              可点「扫描素材」读取数量，也可直接点 1★/2★ 的 + 选石头（执行时自动读取数量）
            </div>
          </div>
        </div>

        <div class="flex min-w-0 flex-1 flex-col">
          <div class="border-b border-white/10 px-3 py-1.5 text-[12px] text-gray-400">
            使用的改造石与优先级（上 = 先用；列表里没有就切下一个）
            <span class="ml-1 text-gray-500">已选 {{ chosenStones.length }} 种低级石头 · 素材表合计 {{ chosenCount }} 个</span>
            <span v-if="hasUnknown" class="ml-1 text-amber-300/80">· 有未扫到的，数量未知（执行时到游戏里现找）</span>
          </div>
          <div class="min-h-0 flex-1 overflow-auto">
            <div
              v-for="(m, i) in chosenStones"
              :key="m.key"
              class="flex items-center gap-1.5 border-b border-white/5 px-3 py-1.5 text-[12px]"
            >
              <span class="w-5 text-gray-600">{{ i + 1 }}</span>
              <span class="text-gray-500">{{ stoneLabel(m) }}</span>
              <span class="min-w-0 flex-1 truncate text-gray-200">{{ m.key }}</span>
              <span class="tabular-nums text-gray-500">{{ stockText(m) }}</span>
              <button class="px-0.5 text-gray-500 hover:text-gray-200" :disabled="running" @click="moveStone(m.key, -1)">▲</button>
              <button class="px-0.5 text-gray-500 hover:text-gray-200" :disabled="running" @click="moveStone(m.key, 1)">▼</button>
              <button class="px-0.5 text-rose-400/70 hover:text-rose-300" :disabled="running" @click="removeStone(m.key)">✕</button>
            </div>
            <div v-if="!chosenStones.length" class="px-3 py-8 text-center text-[12px] text-gray-600">从左侧表格点 1★/2★ 数量添加</div>
          </div>
        </div>
      </div>
    </section>

    <aside class="flex w-[340px] shrink-0 flex-col border-l border-white/10 bg-ink-800/40">
      <div class="border-b border-white/10 px-3 py-2 text-[13px] text-gray-200">
        执行结果
        <span class="ml-2 text-[11px] text-gray-500">
          共 {{ snap.results.length }} 条 · 已改造 {{ okCount }} 件
        </span>
      </div>
      <!-- 过滤分类：样式同评分规则的列表分页 -->
      <div class="flex items-center gap-1 border-b border-white/10 px-2 py-1.5">
        <button
          v-for="t in RESULT_TABS"
          :key="t.key"
          class="flex-1 rounded px-2 py-1 text-[11.5px] transition"
          :class="resultTab === t.key ? 'bg-white/10 text-gray-100' : 'text-gray-500 hover:bg-white/5'"
          @click="resultTab = t.key"
        >{{ t.label }}</button>
      </div>
      <div ref="resultList" class="h-[45%] shrink-0 overflow-auto border-b border-white/10">
        <div
          v-for="(r, i) in filteredResults"
          :key="i"
          class="border-b border-white/5 px-3 py-1 text-[12px]"
        >
          <span :class="r.state === 'ok' ? 'text-emerald-300' : r.state === 'fail' ? 'text-rose-300' : 'text-gray-500'">
            {{ r.state === 'ok' ? '✔' : r.state === 'fail' ? '✗' : '=' }}
          </span>
          <span class="ml-1 text-gray-300">{{ r.name }}</span>
          <span class="ml-1 text-[11px] text-gray-500">{{ r.note }}</span>
        </div>
        <div v-if="!filteredResults.length" class="px-3 py-6 text-center text-[11px] text-gray-600">
          {{ resultTab === 'ok' ? '还没有被改造的装备' : resultTab === 'other' ? '没有跳过 / 失败记录' : '暂无记录' }}
        </div>
      </div>
      <div ref="logList" class="min-h-0 flex-1 overflow-auto px-3 py-2 font-mono text-[11px] leading-relaxed text-gray-500">
        <div v-for="(l, i) in snap.logs" :key="i">{{ l }}</div>
      </div>
    </aside>
  </div>
</template>
