<script setup lang="ts">
import { onMounted, ref } from 'vue'
import * as api from '../api'
import type { FilterNotes } from '../types'

const props = defineProps<{ noteKey: keyof FilterNotes }>()

const note = ref('')
const draft = ref('')
const editing = ref(false)
const busy = ref(false)
const err = ref('')

async function load() {
  try {
    const r = await api.getFilterNotes()
    note.value = r.notes?.[props.noteKey] || ''
  } catch (e) {
    err.value = String(e)
  }
}

onMounted(load)

function beginEdit() {
  if (editing.value) return
  draft.value = note.value
  err.value = ''
  editing.value = true
}

async function save() {
  busy.value = true
  err.value = ''
  try {
    const r = await api.saveFilterNotes(props.noteKey, draft.value)
    note.value = r.notes?.[props.noteKey] || ''
    editing.value = false
  } catch (e) {
    err.value = String(e)
  } finally {
    busy.value = false
  }
}

function cancel() {
  err.value = ''
  editing.value = false
}

defineExpose({ beginEdit })
</script>

<template>
  <div v-if="editing" class="mt-1.5 rounded border border-white/15 bg-ink-900/60 p-2">
    <textarea
      v-model="draft"
      rows="4"
      placeholder="写下你常用的过滤器配置…"
      class="w-full resize-y rounded border border-white/10 bg-ink-800 px-2 py-1.5 text-[12px] leading-relaxed text-gray-200 outline-none focus:ring-1 focus:ring-gold-400/40"
    ></textarea>
    <div class="mt-1.5 flex items-center gap-2 text-[11px]">
      <button
        class="rounded bg-gold-400 px-2 py-0.5 font-medium text-black disabled:opacity-40"
        :disabled="busy"
        @click="save"
      >保存</button>
      <button class="rounded border border-white/10 px-2 py-0.5 text-gray-400 hover:bg-white/5" @click="cancel">取消</button>
      <span v-if="err" class="text-rose-300">{{ err }}</span>
    </div>
  </div>
  <blockquote
    v-else-if="note"
    class="mt-1.5 rounded border-l-2 border-gold-400/50 bg-white/[0.03] px-2.5 py-1.5"
  >
    <div class="mb-0.5 text-[10.5px] tracking-wide text-gray-500">过滤器笔记</div>
    <div class="whitespace-pre-wrap text-[12px] leading-relaxed text-gray-300">{{ note }}</div>
  </blockquote>
</template>
