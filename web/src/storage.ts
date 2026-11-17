/** 界面状态的本地持久化（localStorage）：刷新页面、切页签回来都不丢。
 *
 * 只放纯前端 UI 偏好（过滤器、排序这类），业务配置仍走后端 config/。
 * localStorage 在隐私模式 / 配额满时会抛异常，统一吞掉：状态照常可用，只是不记得。
 */
import { ref, watch, type Ref } from 'vue'

const PREFIX = 'wvd.'

function readItem(key: string): string | null {
  try {
    return localStorage.getItem(PREFIX + key)
  } catch {
    return null
  }
}

function writeItem(key: string, value: string): void {
  try {
    localStorage.setItem(PREFIX + key, value)
  } catch {
    /* 写不进去就算了（隐私模式 / 配额满） */
  }
}

function persisted<T extends string>(
  key: string,
  fallback: T,
  allowed?: readonly string[],
): Ref<T> {
  const raw = readItem(key)
  const init = raw !== null && (!allowed || allowed.includes(raw)) ? (raw as T) : fallback
  const state = ref(init) as Ref<T>
  watch(state, (v) => writeItem(key, String(v)))
  return state
}

/** 任意字符串（如部位名），不做白名单校验 */
export function persistedString(key: string, fallback = ''): Ref<string> {
  return persisted<string>(key, fallback)
}

/** 枚举值：存储里是别的值（改版遗留 / 手改坏了）时回 fallback */
export function persistedEnum<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): Ref<T> {
  return persisted<T>(key, fallback, allowed)
}

/** 多选值（如星级 / 颜色 / 阶级的勾选集合），以逗号拼接存取；就地 push/splice 也会同步 */
export function persistedList(key: string): Ref<string[]> {
  const raw = readItem(key)
  const init = raw ? raw.split(',').filter(Boolean) : []
  const state = ref(init) as Ref<string[]>
  watch(state, (v) => writeItem(key, v.join(',')), { deep: true })
  return state
}
