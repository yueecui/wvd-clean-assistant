<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{ logs: string[] }>()
const box = ref<HTMLElement | null>(null)
const follow = ref(true)

watch(
  () => props.logs.length,
  async () => {
    if (!follow.value) return
    await nextTick()
    if (box.value) box.value.scrollTop = box.value.scrollHeight
  },
)

function onScroll() {
  const el = box.value
  if (!el) return
  follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 30
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col">
    <div class="flex items-center justify-between px-3 py-2 text-xs text-gray-400">
      <span>运行日志</span>
      <label class="flex cursor-pointer items-center gap-1">
        <input v-model="follow" type="checkbox" class="accent-gold-400" />跟随
      </label>
    </div>
    <div
      ref="box"
      class="min-h-0 flex-1 overflow-auto border-t border-white/5 px-3 py-2 font-mono text-[11.5px] leading-relaxed text-gray-400"
      @scroll="onScroll"
    >
      <div v-for="(l, i) in logs" :key="i" :class="l.includes('✗') || l.includes('⚠') ? 'text-amber-400/90' : ''">
        {{ l }}
      </div>
      <div v-if="!logs.length" class="text-gray-600">等待开始…</div>
    </div>
  </div>
</template>
