<script setup lang="ts">
import type { LogFile } from '../types'

defineProps<{
  open: boolean
  /** 标题：打开提炼日志 / 打开出售日志 */
  title: string
  files: LogFile[]
  current: string
  busy: boolean
  /** 没有任何日志时的提示 */
  emptyHint: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'pick', file: string): void
}>()

function fmt(ts?: number | null) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

function durationText(sec: number) {
  const n = Math.max(0, Math.floor(sec))
  const h = Math.floor(n / 3600), m = Math.floor(n / 60) % 60, s = n % 60
  const pad = (x: number) => String(x).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

function span(f: LogFile) {
  const a = fmt(f.started_at)
  const b = fmt(f.finished_at)
  const dur = f.elapsed ? ` · 运行 ${durationText(f.elapsed)}` : ''
  if (a && b) return `${a} → ${b.slice(11)}${dur}`
  if (a) return `${a} 开始${dur}`
  return fmt(f.mtime)
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    @click.self="emit('close')"
  >
    <div class="flex max-h-[80vh] w-[560px] max-w-full flex-col rounded-lg border border-white/10 bg-ink-800 shadow-2xl">
      <div class="flex items-center justify-between border-b border-white/10 px-4 py-2.5">
        <span class="text-[14px] font-semibold text-gray-100">{{ title }}</span>
        <button class="text-[13px] text-gray-500 hover:text-gray-300" @click="emit('close')">✕</button>
      </div>

      <div class="min-h-0 flex-1 overflow-auto p-3">
        <button
          v-for="f in files"
          :key="f.file"
          class="mb-1.5 flex w-full items-center gap-3 rounded border px-3 py-2 text-left transition disabled:opacity-40"
          :class="f.file === current
            ? 'border-gold-400/50 bg-gold-400/5'
            : 'border-white/10 hover:border-white/25 hover:bg-white/5'"
          :disabled="busy"
          @click="emit('pick', f.file)"
        >
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[13px] text-gray-200">{{ f.title }}</span>
            <span class="text-[11px] text-gray-500">{{ span(f) }}</span>
          </span>
          <span class="shrink-0 text-[12px] tabular-nums text-gray-400">{{ f.batches }} 批</span>
          <span v-if="f.file === current" class="shrink-0 text-[11px] text-gold-300">当前</span>
        </button>

        <div v-if="!files.length" class="py-10 text-center text-[12px] text-gray-600">
          {{ emptyHint }}
        </div>
      </div>
    </div>
  </div>
</template>
