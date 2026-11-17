/** 装备部位（大类型）的展示顺序。
 *
 * 扫描列表的类型筛选、规则编辑器的类型分组都按这个顺序排；
 * 后端 master.types() 用的是同一套顺序（part 编号顺序不同）。
 * 注意「胴」就是身体（游戏里的写法），历史结果文件里存的也是「胴」，不要改名。
 */
export const PART_ORDER = ['单手武器', '双手武器', '头', '手', '胴', '盾', '脚', '饰品']

/** 部位排序权重：未列出的排最后 */
export function partRank(part: string): number {
  const i = PART_ORDER.indexOf(part)
  return i < 0 ? PART_ORDER.length : i
}
