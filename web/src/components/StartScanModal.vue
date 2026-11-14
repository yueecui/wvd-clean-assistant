<script setup lang="ts">
import { ref } from 'vue'
import FilterNote from './FilterNote.vue'

defineProps<{
  open: boolean
  count: number
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'start', mode: 'new' | 'append'): void
}>()

const noteRef = ref<InstanceType<typeof FilterNote> | null>(null)
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    @click.self="emit('close')"
  >
    <div class="w-[480px] max-w-full rounded-lg border border-white/10 bg-ink-800 p-5 shadow-2xl">
      <div class="text-[15px] font-semibold text-gray-100">开始扫描前请确认</div>

      <ol class="mt-3 space-y-1.5 text-[12.5px] leading-relaxed text-gray-300">
        <li>1. 进入「铁匠铺」 → <span class="text-amber-300">「装备强化」</span> → 「持有一览」</li>
        <li>
          2. 配好过滤器，让列表里只出现你要扫描的装备
          <FilterNote ref="noteRef" note-key="scan" />
        </li>
        <li>3. 扫描会从<b class="text-gray-100">当前列表位置</b>开始，逐件点开详情读取，不会自动回顶部。</li>
      </ol>

      <div
        v-if="count"
        class="mt-3 rounded border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-[12px] leading-relaxed text-amber-200"
      >
        当前列表已有 <b>{{ count }}</b> 条数据
      </div>

      <div class="mt-4 flex justify-end gap-2 text-[13px]">
        <button
          class="mr-auto rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5"
          @click="noteRef?.beginEdit()"
        >✎ 过滤器笔记</button>
        <button
          class="rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5"
          @click="emit('close')"
        >取消</button>
        <template v-if="count">
          <button
            class="rounded border border-white/15 px-3 py-1 text-gray-200 hover:bg-white/5 disabled:opacity-40"
            :disabled="busy"
            @click="emit('start', 'append')"
          >继续累加</button>
          <button
            class="rounded bg-gold-400 px-3 py-1 font-medium text-black disabled:opacity-40"
            :disabled="busy"
            @click="emit('start', 'new')"
          >新建扫描</button>
        </template>
        <button
          v-else
          class="rounded bg-gold-400 px-4 py-1 font-medium text-black disabled:opacity-40"
          :disabled="busy"
          @click="emit('start', 'new')"
        >开始扫描</button>
      </div>
    </div>
  </div>
</template>
