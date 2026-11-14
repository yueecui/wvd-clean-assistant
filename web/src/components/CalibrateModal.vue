<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EquipIcon from './EquipIcon.vue'
import type { CatalogItem, ScanItem } from '@/types'

const props = defineProps<{ open: boolean; item: ScanItem | null; catalog: CatalogItem[] }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm', payload: { raw: string; target: string }): void
}>()

const q = ref('')
const picked = ref<CatalogItem | null>(null)

watch(
  () => props.item,
  (it) => {
    q.value = ''
    picked.value = null
    if (it) {
      const top = it.candidates?.[0]
      if (top) {
        const found = props.catalog.find((c) => c.name === top.name)
        if (found) picked.value = found
      }
    }
  },
)

const filtered = computed(() => {
  const key = q.value.trim()
  if (!key) return props.catalog.slice(0, 60)
  return props.catalog.filter((c) => c.name.includes(key)).slice(0, 80)
})

const suggestions = computed(() =>
  (props.item?.candidates || [])
    .map((c) => ({ cand: c, full: props.catalog.find((x) => x.name === c.name) }))
    .filter((x): x is { cand: (typeof x)['cand']; full: CatalogItem } => !!x.full),
)

function confirm() {
  if (!props.item || !picked.value) return
  emit('confirm', { raw: props.item.raw_name || props.item.name, target: picked.value.name })
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open && item" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" @click.self="emit('close')">
      <div class="flex h-[min(680px,88vh)] w-[min(880px,94vw)] flex-col overflow-hidden rounded-lg border border-white/10 bg-ink-800 shadow-2xl">
        <div class="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <div>
            <div class="text-sm text-gray-200">校准装备名称</div>
            <div class="mt-1 text-xs text-gray-500">
              OCR 原文：<span class="text-amber-300">{{ item.raw_name || item.name }}</span>
              <span class="ml-3">第 {{ item.idx }} 行 · {{ '★'.repeat(item.stars) }}</span>
            </div>
          </div>
          <button class="text-gray-500 hover:text-gray-200" @click="emit('close')">✕</button>
        </div>

        <div class="grid min-h-0 flex-1 grid-cols-2 divide-x divide-white/10">
          <!-- 左：候选 + 搜索 -->
          <div class="flex min-h-0 flex-col">
            <div v-if="suggestions.length" class="border-b border-white/5 px-3 py-2">
              <div class="mb-1 text-[11px] text-gray-500">近似候选</div>
              <div class="flex flex-wrap gap-1.5">
                <button
                  v-for="s in suggestions"
                  :key="s.cand.name"
                  class="flex items-center gap-1.5 rounded border px-1.5 py-1 text-[12px] transition"
                  :class="picked?.name === s.cand.name
                    ? 'border-gold-400/60 bg-gold-400/10 text-gold-300'
                    : 'border-white/10 text-gray-300 hover:border-white/25'"
                  @click="picked = s.full"
                >
                  <EquipIcon :icon="s.cand.icon" :size="20" />
                  {{ s.cand.name }}
                  <span class="text-[10px] text-gray-500">{{ Math.round(s.cand.ratio * 100) }}%</span>
                </button>
              </div>
            </div>
            <div class="px-3 py-2">
              <input
                v-model="q"
                placeholder="搜索装备名称…"
                class="w-full rounded border border-white/10 bg-ink-700 px-2 py-1.5 text-[13px] outline-none focus:ring-1 focus:ring-gold-400/40"
              />
            </div>
            <div class="min-h-0 flex-1 overflow-auto px-2 pb-2">
              <button
                v-for="c in filtered"
                :key="c.name + c.id"
                class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[13px] transition"
                :class="picked?.name === c.name ? 'bg-gold-400/10 text-gold-300' : 'text-gray-300 hover:bg-white/5'"
                @click="picked = c"
              >
                <EquipIcon :icon="c.icon" :size="22" />
                <span class="flex-1">{{ c.name }}</span>
                <span class="text-[10.5px] text-gray-500">{{ c.part }} · {{ c.rank }}阶</span>
              </button>
              <div v-if="!filtered.length" class="px-2 py-6 text-center text-xs text-gray-600">无匹配</div>
            </div>
          </div>

          <!-- 右：确认 -->
          <div class="flex min-h-0 flex-col p-4">
            <div class="text-[11px] text-gray-500">映射到</div>
            <div v-if="picked" class="mt-2 flex items-center gap-3 rounded border border-gold-400/30 bg-gold-400/5 p-3">
              <EquipIcon :icon="picked.icon" :size="48" />
              <div>
                <div class="text-gold-300">{{ picked.name }}</div>
                <div class="text-[11px] text-gray-500">{{ picked.part }} · {{ picked.rank }}阶 · id {{ picked.id }}</div>
              </div>
            </div>
            <div v-else class="mt-2 rounded border border-dashed border-white/10 p-6 text-center text-xs text-gray-600">
              从左侧选择一件正确的装备
            </div>

            <div class="mt-4 rounded bg-ink-700 p-3 text-[11.5px] leading-relaxed text-gray-400">
              确认后会把这个 OCR 名称
              <span class="text-amber-300">「{{ item.raw_name || item.name }}」</span>
              永久映射到所选装备，之后扫描到同样的名称将自动采用正确结果，
              并立刻更新本次已扫出的 {{ item.idx > 0 ? '同名条目' : '条目' }}。
            </div>

            <div class="mt-auto flex justify-end gap-2 pt-4">
              <button class="rounded border border-white/10 px-3 py-1.5 text-[13px] text-gray-300 hover:bg-white/5" @click="emit('close')">
                取消
              </button>
              <button
                class="rounded bg-gold-400 px-4 py-1.5 text-[13px] font-medium text-black disabled:opacity-40"
                :disabled="!picked"
                @click="confirm"
              >
                保存映射
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
