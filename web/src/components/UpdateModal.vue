<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import * as api from '../api'
import type { UpdateSnapshot } from '../types'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const snap = ref<UpdateSnapshot | null>(null)
const acting = ref('')
const msg = ref('')
const prepared = ref(false)
let poll: number | undefined

const st = computed(() => snap.value?.status)
const info = computed(() => snap.value?.info)

async function refresh() {
  try {
    snap.value = await api.getUpdate()
  } catch (e) {
    msg.value = String(e)
  }
}

async function doCheck() {
  acting.value = 'check'
  msg.value = ''
  try {
    const r = await api.checkUpdate()
    if (!r.ok) msg.value = r.error || '检查失败'
    await refresh()
  } catch (e) {
    msg.value = String(e)
  } finally {
    acting.value = ''
  }
}

async function doResources() {
  acting.value = 'resources'
  msg.value = ''
  try {
    const r = await api.applyResources()
    if (!r.ok) msg.value = r.error || '更新失败'
    startPoll()
  } catch (e) {
    msg.value = String(e)
    acting.value = ''
  }
}

async function doApp() {
  acting.value = 'app'
  msg.value = ''
  try {
    const r = await api.prepareApp()
    if (!r.ok) msg.value = r.error || '准备失败'
    else {
      prepared.value = true
      msg.value = `新版 ${r.version} 已就绪，点「重启完成更新」生效`
    }
    await refresh()
  } catch (e) {
    msg.value = String(e)
  } finally {
    acting.value = ''
  }
}

async function doRestart() {
  try {
    const r = await api.restartApp()
    if (!r.ok) msg.value = r.error || '重启失败'
  } catch (e) {
    msg.value = String(e)
  }
}

function startPoll() {
  if (poll) window.clearInterval(poll)
  poll = window.setInterval(async () => {
    await refresh()
    if (!st.value?.running) {
      if (poll) window.clearInterval(poll)
      poll = undefined
      acting.value = ''
      if (st.value?.error) msg.value = st.value.error
      else if (!msg.value) msg.value = '资源更新完成'
    }
  }, 500)
}

watch(() => props.open, (v) => {
  if (v) {
    prepared.value = false
    msg.value = ''
    void refresh()
    void doCheck()
  } else if (poll) {
    window.clearInterval(poll)
    poll = undefined
  }
})
onBeforeUnmount(() => {
  if (poll) window.clearInterval(poll)
})

function timeText(ts?: number) {
  return ts ? new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false }) : ''
}
function short(list?: string[]) {
  if (!list?.length) return ''
  const s = list.slice(0, 4).map((x) => x.split('/').pop()).join('、')
  return list.length > 4 ? `${s} 等 ${list.length} 项` : s
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    @click.self="emit('close')"
  >
    <div class="w-[520px] max-w-full rounded-lg border border-white/10 bg-ink-800 p-5 shadow-2xl">
      <div class="flex items-center justify-between">
        <div class="text-[15px] font-semibold text-gray-100">检查更新</div>
        <button class="text-gray-500 hover:text-gray-200" @click="emit('close')">✕</button>
      </div>

      <div v-if="!snap" class="mt-4 text-[12.5px] text-gray-400">正在读取本地版本……</div>
      <template v-else>
        <div class="mt-4 grid grid-cols-[auto_1fr_auto_1fr] items-center gap-x-3 gap-y-2 rounded border border-white/10 bg-ink-700/50 px-3 py-3 text-[12.5px]">
          <span class="text-gray-500">程序</span>
          <span class="font-mono text-gray-200">{{ info?.local_app || snap.app_version }}</span>
          <span class="text-gray-600">→</span>
          <span class="font-mono" :class="info?.app_available ? 'text-amber-300' : 'text-gray-400'">{{ info?.remote_app || '—' }}</span>
          <span class="text-gray-500">资源</span>
          <span class="font-mono text-gray-200">{{ info?.local_resource || '未记录' }}</span>
          <span class="text-gray-600">→</span>
          <span class="font-mono" :class="info?.resource_available ? 'text-amber-300' : 'text-gray-400'">{{ info?.remote_resource || '—' }}</span>
        </div>

        <div class="mt-2 text-[11px] text-gray-500">
          数据来源：{{ info?.source?.startsWith('http') ? '网络' : '本地基线' }}
          <span v-if="info?.checked_at" class="ml-2">检查于 {{ timeText(info.checked_at) }}</span>
        </div>

        <div v-if="info?.resource_available" class="mt-3 rounded border border-sky-400/25 bg-sky-400/5 px-3 py-2 text-[12px] text-sky-200">
          <div>资源有更新：新增 {{ info.to_add.length }} 个，变更 {{ info.to_update.length }} 个</div>
          <div v-if="short(info.to_add)" class="mt-1 text-[11px] opacity-80">新增 {{ short(info.to_add) }}</div>
          <div v-if="short(info.to_update)" class="mt-1 text-[11px] opacity-80">变更 {{ short(info.to_update) }}</div>
        </div>

        <div v-if="info?.app_available" class="mt-3 rounded border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[12px] text-amber-200">
          <div>程序有新版本 {{ info.remote_app }}（{{ info.asset }}）</div>
          <div v-if="info.notes" class="mt-1 text-[11px] opacity-80">{{ info.notes }}</div>
        </div>

        <div v-if="st?.running" class="mt-3">
          <div class="text-[12px] text-gray-300">{{ st.message }}（{{ st.done }}/{{ st.total }}）</div>
          <div class="mt-1 h-1.5 overflow-hidden rounded bg-white/10">
            <div class="h-full bg-gold-400 transition-all" :style="{ width: (st.total ? (st.done / st.total) * 100 : 0) + '%' }" />
          </div>
        </div>

        <div v-if="msg || st?.error" class="mt-3 rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-300">
          {{ msg || st?.error }}
        </div>

        <div class="mt-4 flex flex-wrap justify-end gap-2 text-[13px]">
          <button
            class="mr-auto rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5 disabled:opacity-40"
            :disabled="!!acting"
            @click="doCheck"
          >↻ 重新检查</button>
          <button
            v-if="info?.resource_available"
            class="rounded bg-gold-400 px-3 py-1 font-medium text-black disabled:opacity-40"
            :disabled="st?.running || acting === 'resources'"
            @click="doResources"
          >更新资源</button>
          <button
            v-if="info?.app_available && !prepared"
            class="rounded border border-white/15 px-3 py-1 text-gray-200 hover:bg-white/5 disabled:opacity-40"
            :disabled="st?.running || acting === 'app'"
            @click="doApp"
          >下载新版程序</button>
          <button
            v-if="prepared"
            class="rounded bg-amber-500 px-3 py-1 font-medium text-black"
            @click="doRestart"
          >重启完成更新</button>
          <a
            v-if="snap.github?.releases"
            :href="snap.github.releases"
            target="_blank"
            rel="noopener noreferrer"
            class="rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5"
            title="打开 GitHub Releases 页面"
          >GitHub ↗</a>
          <button class="rounded border border-white/10 px-3 py-1 text-gray-400 hover:bg-white/5" @click="emit('close')">关闭</button>
        </div>
      </template>
    </div>
  </div>
</template>
