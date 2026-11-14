<script setup lang="ts">
defineProps<{
  open: boolean
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'scan', mode: 'full' | 'flat'): void
}>()
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    @click.self="emit('close')"
  >
    <div class="w-[480px] max-w-full rounded-lg border border-white/10 bg-ink-800 p-5 shadow-2xl">
      <div class="text-[15px] font-semibold text-gray-100">扫描素材前请确认</div>

      <ol class="mt-3 space-y-1.5 text-[12.5px] leading-relaxed text-gray-300">
        <li>1. 游戏进入「铁匠铺」 → <span class="text-red-300">「装备改造」</span></li>
        <li>2. 脚本按当前列表顺序逐行读取改造石数量，不会自动回顶部</li>
        <li>3. 扫描过程中可随时「停止」，已读到的素材会立即保存</li>
      </ol>

      <div class="mt-4 flex justify-end gap-2 text-[13px]">
        <button
          class="rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5"
          @click="emit('close')"
        >取消</button>
        <button
          class="rounded border border-white/15 px-3 py-1 text-gray-200 hover:bg-white/5 disabled:opacity-40"
          :disabled="busy"
          @click="emit('scan', 'flat')"
        >只扫固定值</button>
        <button
          class="rounded bg-gold-400 px-4 py-1 font-medium text-black disabled:opacity-40"
          :disabled="busy"
          @click="emit('scan', 'full')"
        >全量扫描</button>
      </div>
    </div>
  </div>
</template>
