<script setup lang="ts">
import { ref, watch } from 'vue'
import FilterNote from './FilterNote.vue'

const props = defineProps<{
  open: boolean
  busy: boolean
  /** 当前日志文件名（空 = 还没有日志） */
  logFile: string
  /** 当前日志里是否已有内容可接着跑 */
  resumable: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'start', mode: 'new' | 'resume'): void
}>()

const ok = ref(false)
const noteRef = ref<InstanceType<typeof FilterNote> | null>(null)

/** 每次重新打开都要重新勾选：不允许沿用上一次的确认 */
watch(
  () => props.open,
  (v) => { if (v) ok.value = false },
)
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    @click.self="emit('close')">
    <div class="w-[500px] max-w-full rounded-lg border border-white/10 bg-ink-800 p-5 shadow-2xl">
      <div class="text-[15px] font-semibold text-gray-100">开始出售前请确认</div>

      <ol class="mt-3 space-y-1.5 text-[12.5px] leading-relaxed text-gray-300">
        <li>1. 游戏进入「道具店」 → <span class="text-red-400">「出售」</span></li>
        <li>2. 配好<span class="text-red-400 font-semibold">全部出售的过滤器</span>
          <FilterNote ref="noteRef" note-key="sell" />
        </li>
      </ol>

      <div class="mt-3 rounded border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-[12px] leading-relaxed text-rose-200">
        请务必仔细确认「全部出售」过滤器已经配置好，避免误售有用的装备
      </div>

      <div class="mt-3 rounded border border-white/10 bg-white/[0.03] px-3 py-2 text-[11.5px] leading-relaxed text-gray-400">
        当前日志：<span class="text-gray-200">{{ logFile || '无' }}</span>
        <span class="text-gray-500">（新建日志从 0 开始统计；继续加载日志沿用同一份文件与总数）</span>
      </div>

      <label class="mt-3 flex cursor-pointer items-center gap-2 rounded border border-white/10 px-3 py-2 text-[12.5px] text-gray-200 hover:bg-white/5">
        <input v-model="ok" type="checkbox" class="h-4 w-4 accent-gold-400" />
        我确认已经配置好过滤器
      </label>

      <div class="mt-4 flex justify-end gap-2 text-[13px]">
        <button class="mr-auto rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5"
          @click="noteRef?.beginEdit()">✎ 过滤器笔记</button>
        <button class="rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5"
          @click="emit('close')">取消</button>
        <button class="rounded border border-white/15 px-3 py-1 text-gray-200 hover:bg-white/5 disabled:opacity-40"
          :disabled="busy || !ok || !resumable"
          :title="resumable ? '接着当前日志继续统计' : '当前日志是空的，先跑一次或先打开一份日志'"
          @click="emit('start', 'resume')">继续加载日志</button>
        <button class="rounded bg-gold-400 px-4 py-1 font-medium text-black disabled:opacity-40"
          :disabled="busy || !ok" @click="emit('start', 'new')">新建日志</button>
      </div>
    </div>
  </div>
</template>
