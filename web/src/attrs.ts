import type { AttrRow } from './types'

/**
 * 属性全表（来源 masterdata/EquipmentEffect.json，顺序与表一致）。
 * 除会心外，每种属性都有固定值和百分比两条记录；会心只有固定值。
 * 会心回避整体不使用（游戏里没有该词条），会心/会心回避的百分比版也不显示。
 *
 * 正常情况下用后端 /api/rules 返回的 attr_groups.rows，这里只做兜底。
 */
export const ATTR_ROWS: AttrRow[] = [
  { base: '攻击力', label: '攻击力（固定值 / 百分比）', key: '攻击力', pct_key: '攻击力%' },
  { base: '魔力', label: '魔力（固定值 / 百分比）', key: '魔力', pct_key: '魔力%' },
  { base: '神力', label: '神力（固定值 / 百分比）', key: '神力', pct_key: '神力%' },
  { base: '命中', label: '命中（固定值 / 百分比）', key: '命中', pct_key: '命中%' },
  { base: '回避', label: '回避（固定值 / 百分比）', key: '回避', pct_key: '回避%' },
  { base: '抵抗', label: '抵抗（固定值 / 百分比）', key: '抵抗', pct_key: '抵抗%' },
  { base: '防御力', label: '防御力（固定值 / 百分比）', key: '防御力', pct_key: '防御力%' },
  { base: '法术防御力', label: '法术防御力（固定值 / 百分比）', key: '法术防御力', pct_key: '法术防御力%' },
  { base: '会心', label: '会心（固定值，没有百分比）', key: '会心', pct_key: '' },
  { base: '行动速度', label: '行动速度（固定值 / 百分比）', key: '行动速度', pct_key: '行动速度%' },
]
