<script setup lang="ts">
import type { ResultFile } from '@/types'

defineProps<{
  open: boolean
  files: ResultFile[]
  current: string
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'pick', file: string): void
}>()

function fmt(ts: number) {
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
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
        <span class="text-[14px] font-semibold text-gray-100">打开扫描数据</span>
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
            <span class="text-[11px] text-gray-500">{{ fmt(f.mtime) }}</span>
          </span>
          <span class="shrink-0 text-[12px] tabular-nums text-gray-400">{{ f.count }} 件</span>
          <span v-if="f.file === current" class="shrink-0 text-[11px] text-gold-300">当前</span>
        </button>

        <div v-if="!files.length" class="py-10 text-center text-[12px] text-gray-600">
          还没有扫描数据，先跑一次扫描吧
        </div>
      </div>
    </div>
  </div>
</template>
