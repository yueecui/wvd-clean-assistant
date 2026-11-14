<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { iconUrl } from '@/api'

const props = withDefaults(defineProps<{ icon: string; size?: number; muted?: boolean }>(), {
  size: 32,
  muted: false,
})

const failed = ref(false)
watch(() => props.icon, () => (failed.value = false))
const src = computed(() => iconUrl(props.icon))
</script>

<template>
  <img
    v-if="src && !failed"
    :src="src"
    :width="size"
    :height="size"
    :class="['shrink-0 object-contain', muted ? 'opacity-70' : '']"
    :style="{ width: size + 'px', height: size + 'px' }"
    loading="lazy"
    @error="failed = true"
  />
  <span
    v-else
    class="shrink-0 rounded bg-ink-600 text-center text-[10px] leading-none text-gray-500"
    :style="{ width: size + 'px', height: size + 'px', lineHeight: size + 'px' }"
  >?</span>
</template>
