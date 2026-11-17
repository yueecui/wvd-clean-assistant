/** 装备品质色：游戏里白 → 绿 → 蓝 → 紫 → 红 五档，规则条件里用 1~5 表示。
 *
 * 扫描结果里存的是小写英文（white / green / blue / purple / red），
 * 后端 rules.COLOR_RANK 用的是同一套映射。
 */
export interface QualityLevel {
  value: number
  key: string
  label: string
  hex: string
}

export const QUALITY_LEVELS: QualityLevel[] = [
  { value: 1, key: 'white', label: '白', hex: '#e4e4e7' },
  { value: 2, key: 'green', label: '绿', hex: '#4ade80' },
  { value: 3, key: 'blue', label: '蓝', hex: '#60a5fa' },
  { value: 4, key: 'purple', label: '紫', hex: '#c084fc' },
  { value: 5, key: 'red', label: '红', hex: '#f87171' },
]

/** 档位 → 「白 / 绿 / 蓝 / 紫 / 红」 */
export function qualityLabel(value?: number | null): string {
  return QUALITY_LEVELS.find((q) => q.value === value)?.label || String(value ?? '')
}

/** 扫描结果里的颜色键（white/green/...）→ 档位 1~5；识别不出按白（1）算，与后端同口径 */
export function qualityValue(key?: string | null): number {
  return QUALITY_LEVELS.find((q) => q.key === key)?.value || 1
}
