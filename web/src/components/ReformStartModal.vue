<script setup lang="ts">
import { ref } from 'vue'
import FilterNote from './FilterNote.vue'

defineProps<{
  open: boolean
  busy: boolean
  chosen: number
  attrs: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'start'): void
}>()

const noteRef = ref<InstanceType<typeof FilterNote> | null>(null)
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    @click.self="emit('close')">
    <div class="w-[480px] max-w-full rounded-lg border border-white/10 bg-ink-800 p-5 shadow-2xl">
      <div class="text-[15px] font-semibold text-gray-100">开始改造前请确认</div>

      <ol class="mt-3 space-y-1.5 text-[12.5px] leading-relaxed text-gray-300">
        <li>1. 游戏进入「铁匠铺」 → <span class="text-red-300">「装备改造」</span> → 「持有一览」</li>
        <li>2. 配好过滤器，让列表里只出现你要改造的<span class="text-green-400">绿色品质装备</span>
          <FilterNote ref="noteRef" note-key="reform" />
        </li>
        <li>3. 确认需要改造的属性和使用的改造石已配置好</li>
      </ol>

      <div v-if="!chosen"
        class="mt-3 rounded border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-[12px] leading-relaxed text-amber-200">
        尚未选择改造石，请先从左侧素材表添加
      </div>

      <div v-if="!attrs"
        class="mt-3 rounded border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-[12px] leading-relaxed text-amber-200">
        尚未勾选需要改造的属性，请先在上方属性表中勾选
      </div>

      <div class="mt-4 flex justify-end gap-2 text-[13px]">
        <button class="mr-auto rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5"
          @click="noteRef?.beginEdit()">✎ 过滤器笔记</button>
        <button class="rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5"
          @click="emit('close')">取消</button>
        <button class="rounded bg-gold-400 px-4 py-1 font-medium text-black disabled:opacity-40"
          :disabled="busy || !chosen || !attrs" @click="emit('start')">▶ 开始改造</button>
      </div>
    </div>
  </div>
</template>
