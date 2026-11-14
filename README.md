# WVD 装备扫描（截图 + masterdata 校验 + 规则评分）

截屏 + OCR 采集装备，用 masterdata 校验名称与阶数，按**自定义规则**打分。
只读屏幕，不注入、不挂钩、不碰网络。

## 采集字段

| 字段 | 来源 |
|---|---|
| 名称 | 详情标题，剥离 `+N` 后用 masterdata（855 个中文名）校验 |
| 阶（rank） | masterdata `Equipment.rank`，实测 1～6（0 为特殊条目） |
| 类型 | masterdata `EquipmentType`（34 种，短剑/单手剑/双手斧…不同武器分开） |
| 强化 | 名称末尾 `+N`（如「水零轻斧+10」→ 名称「水零轻斧」+ 强化 10） |
| 星级 | 详情名称下方白色星星聚类（1～5 星） |
| 附加加护 | 详情 `附加加护` 区**仅已解锁**词条 |
| 锁定 | 米黄挂锁：列表行图标右上角 / 详情名称下方，任一命中 |

## 评分规则系统

规则 = `rules/<规则名>.json`（文件名即规则名，目录运行时按需创建）。匹配时
**按特定装备的规则总是先于按装备类型的规则**（与 priority 无关），同一范围内按
**priority 降序**取第一个匹配的（数值大的先）。

```jsonc
{
  "id": "r_weapon_low",
  "name": "武器 · 强化<20",
  "priority": 10,
  "enabled": true,
  "note": "",
  "target": {
    "reinforce": "lt20",          // "lt20" 强化<20 | "gte20" 强化≥20（必选二选一）
    "rank": { "op": ">=", "value": 0 },  // 阶级条件：op 取 >= > = < <=，value 为阶级数字，默认 >=0 不限制
    "mode": "types",              // "types" 按类型 | "equipment" 按指定装备（互斥）
    "types": [101, 103, 200],     // EquipmentType.id，可多选
    "equipment_ids": []           // Equipment.id，可多选
  },
  "base_score": 30,                              // 命中 target 就先加的基础分，默认 0
  "attr": { "攻击力": 1.0, "会心": 0.6 },        // 属性 → 权重
  "combos": [ { "attrs": ["攻击力", "会心"], "bonus": 30 } ]   // 2/3/4 个属性同时出现给额外分
}
```

```
评分 = 基础分 + Σ(词条数值 × 该属性权重) + Σ(命中组合的额外分)
```

- **基础分**：只要装备符合该规则的 `target` 条件就先加上，默认 `0`；即使一条词条都没配上，
  也能让特定装备稳定大于 0 分。老规则文件没有这个字段时按 0 处理。
- 词条数值：`魔力+3`→3；`抵抗+15%`→15（百分比按数值算）
- 未配置权重的属性按 0 计；非数值词条（如套装技能）忽略
- 没有任何规则匹配 → 0 分（也不会有基础分），列表显示「未匹配」

界面「评分规则」页：左侧规则列表（点卡片直接编辑 / 启用开关 / 复制 / 导出 / 删除），
右侧表单（基础分、强化条件、阶级条件、范围模式、类型多选、权重表、组合编辑器）。改动即时重算全部结果。
优先级直接改表单里的数字（同范围内数值大的先匹配），文件名与规则名一致。

## 使用

```
python app\main.py     # 源码（开发环境）：http://127.0.0.1:23456/，可先 pnpm dev 起前端(5173) 走代理
wvd-scan.exe           # 绿色版（23333）：dist\WvdScan\ 整个目录拷走
```

### 开发模式（前后端分开，改前端不用重新打包）

```
# 终端 1：后端（源码默认 23456，不自动开浏览器）
$env:WVD_NO_BROWSER=1; python app\main.py

# 终端 2：前端（5173，热更新，/api 自动代理到 23456）
cd web; pnpm dev
```

- 平时只要**改前端**：开着 `pnpm dev`，浏览器用 http://127.0.0.1:5173，保存即生效。
- 后端换了端口：`$env:WVD_BACKEND="http://127.0.0.1:8766"; pnpm dev`；后端也可用 `$env:WVD_SCAN_PORT=...` 覆盖。
- 只有要在后端端口直接访问或打绿色版时，才需要 `cd web; pnpm build`。

1. MuMu 进入带装备列表的界面（如铁匠铺「装备强化」）。
2. **▶ 开始扫描**：自动回列表顶部 → 逐件点击读详情 → 向下滚动 → 到底自动停。
3. 「待确认」页签集中处理识别不准的条目（校准一次，永久生效）。
4. 配好规则后按评分排序挑装备；**导出 CSV**（utf-8-sig）。

实测 458 件全流程通过，1.5～2.5 秒/件（系统负载高时 7～9 秒/件）。

### CPU 占用

`rapidocr_onnxruntime` 不接受 `intra_op_num_threads` 参数，默认会让 ONNX Runtime 按 CPU
核心数开满线程，扫描时把 CPU 占满、抢卡前台。现在改为在创建会话前替换它的
`SessionOptions` 工厂真正限线程，并在任务运行期间把进程优先级降到「低于正常」。
界面右上角可切换档位：

| 档位 | OCR 线程 | 任务优先级 | 说明 |
|---|---|---|---|
| 全速 `fast` | 不限 | 正常 | 旧行为，最快，会抢前台 |
| 均衡 `balanced` | 2 | 低于正常 | 默认 |
| 省资源 `quiet` | 1 | 低于正常 | 每件之间额外让出 0.15s，最慢 |

档位存在 `config/settings.json` 的 `cpu_mode`，切换后对下一次 OCR 会话生效（会重建会话）。
另外扫描时改为**增量评分**（只给新条目打分、重算同装备名内排名），不再每件重算全表。

## 名称校验与校准

- **已匹配**：masterdata 里有 → 显示图标、id、阶、类型。
- **待确认 / 未匹配**：给出 `difflib` 相似候选（≥0.45，前 6），点「校准」选正确装备，
  映射写入 `config/aliases.json`，**之后同样的 OCR 名自动纠正**，并回填已扫条目。
- 例：游戏里是「踉跄凉鞋」，OCR 读成「跟跑凉鞋」——校准一次全程生效。

## 自动扫描原理

- **逐件点击**：按行坐标 `tap` → 等 0.45s → 截屏 → OCR 详情（名称区放大 2× + 加护区拼成
  **一张图单次 OCR**；每次调用有 1～2s 固定开销，拆成多次小图会慢数倍）。
- **滚动定位**：swipe 距离不可控，用**选中行高亮**当视觉锚点：滚前点最后一行，滚后看高亮
  落在第几行 → 反推整屏全局索引。锚点丢失时退回「名称+星+角标」序列匹配。
- **去重**：全局索引去重。**到底判断**：滚动前后列表内容与坐标完全一致。

## 识别要点（踩过的坑）

| 项 | 结论 |
|---|---|
| 星级 | 白色像素按列聚类，米黄锁被 `b > 0.85r` 自然排除 |
| 锁图标 | 米黄挂锁 `r>150,g>125,r-b>40,g-b>25`；有锁 ~90 像素、无锁 0 |
| 单数字 OCR | 不可用（检测器丢弃窄框），角标只能模板匹配 |
| OCR 线程 | 固定 `intra_op_num_threads=4`，默认 20 线程与模拟器抢 CPU 抖动到 9s |
| ADB 截图 | PowerShell `>` 重定向会损坏二进制，必须 subprocess `capture_output` |
| 名称误判 | 靠 masterdata 校验 + 人工校准，不要只调 OCR |

## 目录

```
app/    main.py(HTTP) parse.py(OCR/像素) scan.py(扫描引擎) rules.py(规则评分)
        master.py(主数据) match.py(校验/校准) capture.py(ADB)
web/    Vue3 + TS + TailwindCSS4 + Vite8
        components/ ResultTable CalibrateModal RulesPanel RuleEditor LogPanel EquipIcon
config/  settings.json aliases.json current.json reform.json filter_notes.json port.txt
rules/   评分规则 <规则名>.json（运行时按需创建）
result/  扫描结果 <名字>.json（运行时按需创建，每次扫描一份）
build.bat  前端构建 → PyInstaller → 组装 dist\WvdScan
           绿色版随包子目录只有 icons / masterdata / web；
           config / rules / result 全部运行时按需创建，升级替换 exe / web 不覆盖用户配置。

`config/port.txt` 只是每次启动写入的实际端口记录（被占用会自动顺延），无人读取；
目录或文件缺失会在下次启动自动重建，手动改它不会改变监听端口（用 `WVD_SCAN_PORT`）。
```

环境变量：`WVD_MASTER`、`WVD_ICONS`、`WVD_SCAN_PORT`、`WVD_SCAN_DATA`（数据根目录）、
`WVD_SCAN_STATIC`、`WVD_BACKEND`（vite 代理目标）。

## 待办

- 加护词条与 `EquipmentEffect` 精度对齐（目前直接读 OCR 文本）。
- 自动切换装备分类/翻页（目前只扫当前列表）。
