/** 规则默认颜色（白），与后端 rules.DEFAULT_RULE_COLOR 保持一致 */
export const DEFAULT_RULE_COLOR = '#e4e4e7'

/** 规则颜色预设：5 种稀有度 + 几个常用强调色（值直接存 hex，前后端都用它） */
export interface RuleColor {
  key: string
  label: string
  hex: string
}

export const RULE_COLORS: RuleColor[] = [
  { key: 'white', label: '普通', hex: '#e4e4e7' },
  { key: 'green', label: '优秀', hex: '#4ade80' },
  { key: 'blue', label: '精良', hex: '#60a5fa' },
  { key: 'purple', label: '史诗', hex: '#c084fc' },
  { key: 'red', label: '传说', hex: '#f87171' },
  { key: 'gold', label: '金色', hex: '#fbbf24' },
  { key: 'orange', label: '橙色', hex: '#fb923c' },
  { key: 'cyan', label: '青色', hex: '#22d3ee' },
  { key: 'pink', label: '粉色', hex: '#f472b6' },
]

/** 规则名的内联样式：空值一律回默认白 */
export function ruleColorStyle(hex?: string) {
  return { color: hex || DEFAULT_RULE_COLOR }
}
