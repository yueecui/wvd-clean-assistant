<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import CalibrateModal from './components/CalibrateModal.vue'
import EnhancePanel from './components/EnhancePanel.vue'
import LogPanel from './components/LogPanel.vue'
import OpenResultModal from './components/OpenResultModal.vue'
import RefinePanel from './components/RefinePanel.vue'
import ReformPanel from './components/ReformPanel.vue'
import SellPanel from './components/SellPanel.vue'
import ResultTable from './components/ResultTable.vue'
import RulesPanel from './components/RulesPanel.vue'
import StartScanModal from './components/StartScanModal.vue'
import UpdateModal from './components/UpdateModal.vue'
import * as api from './api'
import type {
  AttrGroups,
  CatalogItem,
  EquipType,
  ResultFile,
  ScanItem,
  ScanSnap,
  ScoreRule,
} from './types'

const snap = ref<ScanSnap>({
  status: { running: false, phase: 'idle', scanned: 0, current: '', error: null },
  items: [],
  logs: [],
})
const catalog = ref<CatalogItem[]>([])
const tab = ref<'scan' | 'rules' | 'enhance' | 'reform' | 'refine' | 'sell'>('scan')
/** 顶部页签分两组：装备梳理（扫描 / 规则）· 自动处理（强化白装 / 改造绿装 / 自动提炼 / 自动出售） */
const TABS_MAIN = computed(() => [
  { key: 'scan' as const, label: '扫描' },
  { key: 'rules' as const, label: `评分规则 ${rules.value.length}` },
])
const TABS_AUTO = [
  { key: 'enhance' as const, label: '强化白装' },
  { key: 'reform' as const, label: '改造绿装' },
  { key: 'refine' as const, label: '自动提炼' },
  { key: 'sell' as const, label: '自动出售' },
]
const rules = ref<ScoreRule[]>([])
/** 规则列表顺序（= 判定优先级），结果表的规则筛选菜单按它排 */
const ruleOrder = computed(() => rules.value.map((r) => r.id))
const types = ref<EquipType[]>([])
const attrs = ref<string[]>([])
const attrGroups = ref<AttrGroups>({ flat: [], pct: [], custom: [] })
const adbPath = ref('')
const serial = ref('')
const devices = ref<string[]>([])
const adbResolved = ref('')
const cpuMode = ref('balanced')
const ocrQueue = ref(4)
const busy = ref(false)
const errMsg = ref('')
const calibrating = ref<ScanItem | null>(null)
const showStart = ref(false)
const showOpen = ref(false)
const showUpdate = ref(false)
const resultFiles = ref<ResultFile[]>([])
const currentFile = ref('')

const items = computed<ScanItem[]>(() => snap.value.items || [])
const running = computed(() => snap.value.status.running)
const phaseText = computed(() => {
  const p = snap.value.status.phase
  return { idle: '空闲', start: '回列表顶部', scanning: '扫描中', stopping: '正在停止……',
           stopped: '已停止', done: '已完成', error: '出错' }[p] || p
})
const stopping = computed(() => snap.value.status.phase === 'stopping')

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
/** 运行时间：后端 elapsed（已跑完的轮次）+ 本轮已跑的时间，停着的时间不算 */
function runUsed(st: { elapsed?: number; run_started_at?: number | null }) {
  const base = st.elapsed || 0
  const live = st.run_started_at ? now.value / 1000 - st.run_started_at : 0
  return base + Math.max(0, live)
}
/** 运行中显示实时运行时间，结束后固定显示；顺带给出平均每件用时 */
const scanTime = computed(() => {
  const st = snap.value.status
  if (!st.started_at) return ''
  const used = durationText(runUsed(st))
  const label = st.task || '任务'
  const per = st.per_item ? ` · 平均 ${st.per_item.toFixed(1)} 秒/件` : ''
  return st.finished_at
    ? `${label} · 开始 ${clockText(st.started_at)} · 结束 ${clockText(st.finished_at)} · 运行 ${used}${per}`
    : `${label} · 开始 ${clockText(st.started_at)} · 运行 ${used}`
})

let timer: number | undefined

async function refreshSettings() {
  const s = await api.getSettings()
  adbPath.value = s.adb || ''
  adbResolved.value = s.adb_resolved
  devices.value = s.devices || []
  serial.value = s.serial || devices.value[0] || ''
  cpuMode.value = s.cpu_mode || 'balanced'
  ocrQueue.value = s.ocr_queue || 4
}

async function saveCpuMode() {
  try {
    await api.setCpuMode(cpuMode.value)
  } catch (e) {
    errMsg.value = String(e)
  }
}

/** 队列上限 1~8：只影响下一次扫描（队列在开始扫描时按上限新建） */
async function saveOcrQueue() {
  try {
    const n = Math.max(1, Math.min(8, Math.round(Number(ocrQueue.value) || 4)))
    ocrQueue.value = n
    await api.setOcrQueue(n)
  } catch (e) {
    errMsg.value = String(e)
  }
}

async function browseAdb() {
  try {
    const r = await api.pickAdb()
    if (r.path) adbPath.value = r.path
  } catch (e) {
    errMsg.value = String(e)
  }
}

async function pull() {
  try {
    now.value = Date.now()
    snap.value = await api.getScan()
    if (snap.value.file) currentFile.value = snap.value.file
  } catch (e) {
    errMsg.value = String(e)
  }
}

/** mode=new：新建结果文件从头扫；append：累加到当前结果 */
async function start(mode: api.ScanMode = 'new') {
  errMsg.value = ''
  busy.value = true
  try {
    await api.saveSettings(adbPath.value, serial.value)
    const r = await api.startScan(mode)
    if (!r.ok) errMsg.value = r.error || '启动失败'
    showStart.value = false
    await pull()
  } catch (e) {
    errMsg.value = String(e)
  } finally {
    busy.value = false
  }
}

async function openResults() {
  try {
    const r = await api.listResults()
    resultFiles.value = r.files
    currentFile.value = r.current || currentFile.value
    showOpen.value = true
  } catch (e) {
    errMsg.value = String(e)
  }
}

async function pickResult(file: string) {
  busy.value = true
  try {
    await api.openResult(file)
    currentFile.value = file
    showOpen.value = false
    await pull()
  } catch (e) {
    errMsg.value = String(e)
  } finally {
    busy.value = false
  }
}

async function stop() {
  busy.value = true
  try {
    await api.stopScan()
    await pull()
  } finally {
    busy.value = false
  }
}

/** 在文件管理器里打开结果数据目录 */
async function openDataDir() {
  try {
    const r = await api.openResultsDir()
    if (!r.ok) errMsg.value = r.error || '打开目录失败'
  } catch (e) {
    errMsg.value = String(e)
  }
}

async function loadRules() {
  try {
    const r = await api.getRules()
    rules.value = r.rules
    types.value = r.types
    attrs.value = r.attrs
    attrGroups.value = r.attr_groups || { flat: [], pct: [], custom: [] }
  } catch (e) {
    errMsg.value = String(e)
  }
}

/** 规则改动 → 重算分数 → 重新拉结果 */
async function onRulesChanged() {
  await loadRules()
  await api.rescore()
  await pull()
}

async function onCalibrate(payload: { raw: string; target: string }) {
  try {
    await api.saveAlias(payload.raw, payload.target)
    calibrating.value = null
    await pull()
  } catch (e) {
    errMsg.value = String(e)
  }
}

// 扫描结束（正常结束或被停止）→ 自动落盘
watch(
  () => snap.value.status.phase,
  (p, prev) => {
    const ends = p === 'done' || p === 'stopped'
    if (ends && prev !== p && items.value.length) void api.saveScan()
  },
)

onMounted(async () => {
  await refreshSettings()
  await pull()
  await loadRules()
  try {
    const c = await api.getCatalog()
    catalog.value = c.items
  } catch {
    /* 目录拉不到不影响扫描 */
  }
  timer = window.setInterval(() => {
    if (running.value) pull()
  }, 900)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="flex h-full flex-col">
    <header class="flex flex-wrap items-center gap-3 border-b border-white/10 bg-ink-800 px-4 py-2.5">
      <div class="flex items-baseline gap-2">
        <h1 class="text-[15px] font-semibold text-gray-100">WVD 装备清理助手</h1>
      </div>

      <div class="flex overflow-hidden rounded-md border border-white/10 text-[12.5px]">
        <button
          v-for="t in TABS_MAIN"
          :key="t.key"
          class="px-3 py-1 transition"
          :class="tab === t.key ? 'bg-white/10 text-gray-100' : 'text-gray-500 hover:bg-white/5'"
          @click="tab = t.key"
        >{{ t.label }}</button>
      </div>

      <div class="flex overflow-hidden rounded-md border border-white/10 text-[12.5px]">
        <button
          v-for="t in TABS_AUTO"
          :key="t.key"
          class="px-3 py-1 transition"
          :class="tab === t.key ? 'bg-white/10 text-gray-100' : 'text-gray-500 hover:bg-white/5'"
          @click="tab = t.key"
        >{{ t.label }}</button>
      </div>

      <div class="ml-auto flex items-center gap-2 text-xs">
        <input
          v-model="adbPath"
          placeholder="adb.exe 路径（留空自动探测）"
          class="w-64 rounded border border-white/10 bg-ink-700 px-2 py-1 text-[12px] outline-none focus:ring-1 focus:ring-gold-400/40"
        />
        <button
          class="rounded border border-white/10 px-2 py-1 text-gray-400 hover:bg-white/5"
          title="选择 adb.exe"
          @click="browseAdb"
        >浏览</button>
        <select
          v-model="serial"
          class="rounded border border-white/10 bg-ink-700 px-2 py-1 text-[12px] outline-none"
        >
          <option v-for="d in devices" :key="d" :value="d">{{ d }}</option>
          <option v-if="!devices.length" value="">未发现设备</option>
        </select>
        <button class="rounded border border-white/10 px-2 py-1 text-gray-400 hover:bg-white/5" @click="refreshSettings">
          ↻
        </button>
        <span class="ml-1 whitespace-nowrap text-gray-500">CPU</span>
        <select
          v-model="cpuMode"
          class="rounded border border-white/10 bg-ink-700 px-2 py-1 text-[12px] outline-none"
          title="CPU 占用档位：均衡（2 线程，默认）/ 省资源（1 线程，更不抢前台）。切换后对下一次 OCR 会话生效"
          @change="saveCpuMode"
        >
          <option value="balanced">均衡</option>
          <option value="quiet">省资源</option>
        </select>
        <span class="ml-1 whitespace-nowrap text-gray-500">队列</span>
        <select
          v-model.number="ocrQueue"
          class="rounded border border-white/10 bg-ink-700 px-2 py-1 text-[12px] outline-none"
          title="截图与 OCR 流水线队列上限（1~8）：越大截图越能提前、也越吃内存；改动对下一次扫描生效"
          @change="saveOcrQueue"
        >
          <option v-for="n in 8" :key="n" :value="n">{{ n }}</option>
        </select>
        <span :class="devices.length ? 'text-emerald-400' : 'text-rose-400'">
          {{ devices.length ? '已连接' : '未连接' }}
        </span>
        <button
          class="ml-1 rounded border border-gold-400/30 px-2 py-1 text-gold-300/90 hover:bg-gold-400/10"
          title="检查程序与游戏资源更新"
          @click="showUpdate = true"
        >更新</button>
      </div>
    </header>

    <div v-if="tab === 'scan'" class="flex items-center gap-2 border-b border-white/10 bg-ink-800/60 px-4 py-2">
      <button
        class="rounded px-3 py-1.5 text-[13px] font-medium disabled:opacity-40"
        :class="running
          ? (stopping
            ? 'border border-amber-400/50 text-amber-300'
            : 'border border-rose-400/40 text-rose-300')
          : 'bg-gold-400 text-black'"
        :disabled="(running && (stopping || busy)) || (!running && (busy || !devices.length))"
        @click="running ? stop() : (showStart = true)"
      >
        {{ running ? (stopping ? '正在停止……' : '■ 停止') : '▶ 开始扫描' }}
      </button>
      <button
        class="rounded border border-white/10 px-3 py-1.5 text-[13px] text-gray-300 hover:bg-white/5 disabled:opacity-40"
        :disabled="running || busy"
        @click="openResults"
      >
        打开数据
      </button>
      <button
        class="rounded border border-white/10 px-3 py-1.5 text-[13px] text-gray-300 hover:bg-white/5 disabled:opacity-40"
        :disabled="busy"
        title="在文件管理器中打开结果数据目录"
        @click="openDataDir"
      >
        打开数据目录
      </button>
      <a
        href="/api/export.csv"
        class="rounded border border-white/10 px-3 py-1.5 text-[13px] text-gray-300 hover:bg-white/5"
        download="wvd_equipment.csv"
      >导出 CSV</a>

      <div class="ml-3 flex min-w-0 flex-1 items-center gap-2">
        <span class="whitespace-nowrap text-xs text-gray-400">
          {{ phaseText }} · {{ snap.status.scanned }} 件
          <span v-if="snap.status.current" class="text-gray-500"> · {{ snap.status.current }}</span>
        </span>
        <span v-if="scanTime" class="ml-1 whitespace-nowrap font-mono text-[11px] text-gray-500">{{ scanTime }}</span>
      </div>
      <span
        v-if="currentFile"
        class="max-w-[200px] truncate text-[11px] text-gray-500"
        :title="'当前结果文件：' + currentFile"
      >当前：{{ currentFile.replace(/\.json$/, '') }}</span>
    </div>

    <div v-if="errMsg || snap.status.error" class="border-b border-rose-500/30 bg-rose-500/10 px-4 py-1.5 text-xs text-rose-300">
      {{ errMsg || snap.status.error }}
    </div>

    <main v-if="tab === 'scan'" class="flex min-h-0 flex-1">
      <section class="flex min-w-0 flex-1 flex-col">
        <ResultTable
          :items="items"
          :types="types"
          :rule-order="ruleOrder"
          @calibrate="calibrating = $event"
        />
      </section>
      <aside class="hidden w-[340px] flex-col border-l border-white/10 bg-ink-800/40 lg:flex">
        <LogPanel :logs="snap.logs || []" />
      </aside>
    </main>

    <main v-else-if="tab === 'rules'" class="flex min-h-0 flex-1">
      <RulesPanel
        :rules="rules"
        :types="types"
        :attrs="attrs"
        :attr-groups="attrGroups"
        :catalog="catalog"
        @changed="onRulesChanged"
      />
    </main>

    <main v-else-if="tab === 'enhance'" class="flex min-h-0 flex-1">
      <EnhancePanel />
    </main>

    <main v-else-if="tab === 'reform'" class="flex min-h-0 flex-1">
      <ReformPanel />
    </main>

    <main v-else-if="tab === 'refine'" class="flex min-h-0 flex-1">
      <RefinePanel />
    </main>

    <main v-else class="flex min-h-0 flex-1">
      <SellPanel />
    </main>

    <CalibrateModal
      :open="!!calibrating"
      :item="calibrating"
      :catalog="catalog"
      @close="calibrating = null"
      @confirm="onCalibrate"
    />

    <StartScanModal
      :open="showStart"
      :count="items.length"
      :busy="busy"
      @close="showStart = false"
      @start="start"
    />

    <OpenResultModal
      :open="showOpen"
      :files="resultFiles"
      :current="currentFile"
      :busy="busy"
      @close="showOpen = false"
      @pick="pickResult"
    />

    <UpdateModal :open="showUpdate" @close="showUpdate = false" />
  </div>
</template>
