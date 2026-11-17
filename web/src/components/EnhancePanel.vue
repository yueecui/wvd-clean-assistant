<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as api from '../api'
import EnhanceStartModal from './EnhanceStartModal.vue'
import type { EnhanceSnap } from '../types'

const snap = ref<EnhanceSnap>({
  status: {
    running: false, phase: 'idle', done: 0, failed: 0, skipped: 0,
    current: '', error: null,
  },
  logs: [], results: [],
})
const busy = ref(false)
const errMsg = ref('')
const showStart = ref(false)

const toast = ref<{ text: string; kind: 'info' | 'error' } | null>(null)
let timer: number | undefined
let toastTimer: number | undefined

function showToast(text: string, kind: 'info' | 'error' = 'info') {
  toast.value = { text, kind }
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = null }, kind === 'error' ? 4000 : 2500)
}
watch(errMsg, (v) => { if (v) showToast(v, 'error') })
watch(() => snap.value.status.error, (v) => { if (v) showToast(v, 'error') })

const running = computed(() => snap.value.status.running)
const phase = computed(() => snap.value.status.phase)
const stopping = computed(() => phase.value === 'stopping')
const PHASE_TEXT: Record<string, string> = {
  idle: '空闲', start: '准备中', running: '执行中', scrolling: '翻页中',
  stopping: '正在停止……', stopped: '已停止', done: '已完成', error: '出错',
}
const phaseText = computed(() => PHASE_TEXT[phase.value] || phase.value)

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
const taskTime = computed(() => {
  const st = snap.value.status
  if (!st.started_at) return ''
  const used = durationText(runUsed(st))
  const label = st.task || '任务'
  return st.finished_at
    ? `${label} · 开始 ${clockText(st.started_at)} · 结束 ${clockText(st.finished_at)} · 运行 ${used}`
    : `${label} · 开始 ${clockText(st.started_at)} · 运行 ${used}`
})

const logList = ref<HTMLElement | null>(null)

/** 停在底部时才自动跟随新内容 */
function autoFollow(el: HTMLElement | null) {
  if (!el || el.scrollHeight - el.scrollTop - el.clientHeight > 80) return
  void nextTick(() => { el.scrollTop = el.scrollHeight })
}
watch(() => snap.value.logs, () => autoFollow(logList.value))

async function poll() {
  try {
    now.value = Date.now()
    snap.value = await api.getEnhanceStatus()
  } catch (e) {
    errMsg.value = String(e)
  }
}

function onStartClick() {
  if (running.value) {
    if (!stopping.value) void stop()
    return
  }
  if (busy.value) return
  showStart.value = true      // 先弹确认，和提炼 / 出售 / 改造一致
}

function onStart() {
  showStart.value = false
  void start()
}

async function start() {
  if (running.value || busy.value) return
  busy.value = true
  errMsg.value = ''
  try {
    const r = await api.startEnhance()
    if (!r.ok) errMsg.value = r.error || '启动失败'
    await poll()
  } catch (e) {
    errMsg.value = String(e)
  } finally {
    busy.value = false
  }
}

async function stop() {
  try {
    snap.value.status.phase = 'stopping'
    await api.stopEnhance()
    await poll()
  } catch (e) {
    errMsg.value = String(e)
  }
}

onMounted(async () => {
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

    <EnhanceStartModal
      :open="showStart"
      :busy="busy"
      @close="showStart = false"
      @start="onStart"
    />

    <section class="flex min-w-0 flex-1 flex-col">
      <div class="relative flex flex-wrap items-center gap-2 border-b border-white/10 px-3 py-2">
        <button
          class="rounded px-3 py-1.5 text-[13px] font-medium disabled:opacity-40"
          :class="running
            ? (stopping ? 'border border-amber-400/50 text-amber-300' : 'border border-rose-400/40 text-rose-300')
            : 'bg-gold-400 text-black'"
          :disabled="(running && (stopping || busy)) || (!running && busy)"
          @click="onStartClick"
        >{{ running ? (stopping ? '停止中……' : '■ 停止') : '▶ 开始强化' }}</button>
        <span class="ml-2 text-xs text-gray-400">
          {{ phaseText }} · 已强化 {{ snap.status.done }} 件 · 失败 {{ snap.status.failed }}
          <span class="text-gray-600">· 跳过 {{ snap.status.skipped }}</span>
          <span v-if="snap.status.current" class="text-gray-500"> · {{ snap.status.current }}</span>
        </span>
        <span v-if="taskTime" class="ml-1 font-mono text-[11px] text-gray-500">{{ taskTime }}</span>
      </div>

      <div class="min-h-0 flex-1 overflow-auto px-2 py-1.5">
        <table class="border-collapse text-[11.5px] leading-tight">
          <thead class="sticky top-0 bg-ink-800 text-[10.5px] text-gray-500">
            <tr>
              <th class="whitespace-nowrap py-0.5 pr-3 text-left font-normal">装备</th>
              <th class="whitespace-nowrap py-0.5 pr-3 text-left font-normal">星级</th>
              <th class="whitespace-nowrap py-0.5 pr-3 text-left font-normal">强化</th>
              <th class="whitespace-nowrap py-0.5 text-left font-normal">时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in snap.results" :key="i" class="border-t border-white/5">
              <td class="whitespace-nowrap py-0.5 pr-3 text-gray-300">{{ r.name }}</td>
              <td class="whitespace-nowrap py-0.5 pr-3 text-gray-400">{{ r.stars }}★</td>
              <td class="whitespace-nowrap py-0.5 pr-3 tabular-nums">
                <span class="text-gray-500">+{{ r.before }}</span>
                <span class="text-gray-600"> → </span>
                <span class="text-emerald-300">+{{ r.after }}</span>
              </td>
              <td class="whitespace-nowrap py-0.5 font-mono text-[10.5px] text-gray-500">{{ clockText(r.at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!snap.results.length" class="py-6 text-left text-[12px] text-gray-600">
          还没有强化记录
        </div>
      </div>
    </section>

    <aside class="flex w-[340px] shrink-0 flex-col border-l border-white/10 bg-ink-800/40">
      <div class="border-b border-white/10 px-3 py-2 text-[13px] text-gray-200">运行日志</div>
      <div ref="logList" class="min-h-0 flex-1 overflow-auto px-3 py-2 font-mono text-[11px] leading-relaxed text-gray-500">
        <div
          v-for="(l, i) in snap.logs"
          :key="i"
          :class="l.includes('⚠') || l.includes('✗') ? 'text-amber-400/90' : ''"
        >{{ l }}</div>
        <div v-if="!snap.logs.length" class="text-gray-600">等待开始…</div>
      </div>
    </aside>
  </div>
</template>
