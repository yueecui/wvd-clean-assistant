# 版本更新操作手册

这里记录**维护者**在版本更新时需要做的操作。功能实现细节见 `docs/IMPLEMENTATION.md`。

程序版本与游戏资源版本是**两条独立通道**，互不牵连：

| 更新类型 | 什么时候做 | 用户怎么拿到 |
|---|---|---|
| 游戏资源（icon / masterdata） | 游戏客户端更新、解包出新数据 | 界面点「更新资源」，或双击 `update_resources.bat` |
| 程序（exe / web） | 改了后端/前端代码 | 界面点「下载新版程序」→「重启完成更新」 |

---

## 一、更新游戏资源（不动程序、不发 Release）

游戏更新后，icon 和 masterdata 来自解包目录，走这一步。

### 操作

1. **解包游戏客户端**，确保 out 目录里有 `masterdata/` 和 `assets.lib/sprite/ListIcon/`。
   当前配置的是 `D:\WizardyDaphne\WizardyDaphneUnpack\out`（见 `update_resources.bat` 顶部 `WVD_UNPACK`）。

2. **双击项目根目录 `update_resources.bat`**。它会：
   - 从解包目录增量比对 796 个文件（792 图标 + 4 主数据），只覆盖内容不同的；
   - 有变化才重算 `manifest.json` 的 resources 段（版本用当天日期，基址用当前 git HEAD）；
   - 在屏幕上打印出接下来要执行的 git 命令。

3. **把变化推到仓库**（脚本有变化时会打印这三行，照做即可）：

   ```bash
   git add masterdata icons manifest.json
   git commit -m "chore: update game resources"
   git push
   ```

4. **确认 CI 完成**：push 后 `.github/workflows/resources.yml` 会自动触发，用**新的 commit**
   重写 `manifest.json` 的 `resources.base`（指向刚推上去的资源快照）。到 GitHub 上看一眼
   `manifest.json`，确认 `resources.version` 是当天、`base` 里是最新的 commit sha。

5. **用户侧生效**：绿色版用户打开「更新」窗口点「更新资源」即可增量拉取新 icon / 主数据，
   不用换 exe、不用重启。

### 注意

- bat 顶部 `WVD_UNPACK` 留空时，模式会切到"从 GitHub 增量下载"（给最终用户用的），维护者更新仓库资源时**不要留空**。
- 图标只增改、不删本地多余的；游戏里彻底移除的图标若要从仓库清掉，需手动删除 `icons/` 下对应文件再提交。
- `manifest.json` 由脚本生成，不要手改哈希。
- 游戏只更新了主数据、图标没变时，脚本照样能识别（按内容比对），无需特殊处理。

---

## 二、发布新版程序（改了代码）

改了后端或前端、需要用户换 exe 时走这一步。

### 操作

1. **本地改完代码并验证**：
   - 后端改动：重启 python 进程（窗口要保持可见），确认 `/api/update/*` 等接口正常；
   - 前端改动：`cd web && pnpm build`（会先跑类型检查，再产出 `web/dist`）。
     **注意**：只改源码不 build 的话，后端 serve 的还是旧 `web/dist`，页面上看不到新功能。

2. **升级版本号**：改 `app/version.py` 里的 `VERSION`，按语义化版本递增（如 `1.0.0` → `1.1.0`）。
   发版 workflow 会用 tag 名覆盖它，但本地保持同步可避免混淆。

3. **提交并推送代码**：

   ```bash
   git add -A
   git commit -m "feat: 你的改动说明"
   git push
   ```

4. **打 tag 并推送**（tag 名必须以 `v` 开头，且和版本号一致）：

   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```

5. **CI 自动发版**：push tag 触发 `.github/workflows/release.yml`，依次：
   - 写版本号 → 装依赖 → `pnpm build` → PyInstaller 打包 → 组装 `dist\WvdClean`（含资源与 manifest）；
   - 压缩成 zip、算 sha256；
   - 生成 `manifest.json` 的 `app` 段（版本、下载地址、校验和、更新说明）；
   - 把 manifest 推回 `main`，并发布 GitHub Release（zip 作为附件）。

6. **验收**：
   - GitHub Release 页出现 `v1.1.0` 和 zip 附件；
   - `main` 上的 `manifest.json` 里 `app.version` / `app.url` / `app.sha256` 正确；
   - 用旧版绿色版点「更新」→「下载新版程序」→「重启完成更新」，确认版本号升级、
     且 `config/ rules/ result/ log/` 里的数据都还在。

### 注意

- **tag 名必须与版本号一致**：`v1.1.0` 对应 `VERSION = "1.1.0"`，否则 manifest 里的版本号会和 exe 里的对不上。
- 仓库需要开启 Actions 的写权限（Settings → Actions → General → Workflow permissions → Read and write），
  否则 workflow 推不回 manifest、发不了 Release。
- tag 打错可以删了重打（本地 `git tag -d v1.1.0`，远端 `git push origin :refs/tags/v1.1.0`），
  但已经发布的 Release 要在网页上手动删除。
- `release.yml` 推回 manifest 时带 `[skip ci]`，不会触发资源 workflow 的循环。

---

## 三、资源和代码同时更新

游戏和资源、代码都要改时：**先做第一步（更新资源并 push，等 CI 刷完 manifest），再做第二步（发版 tag）**。
这样 release 打包出来的绿色版里，资源基线也是最新的。

---

## 四、快速对照表

| 我改了什么 | 要做什么 |
|---|---|
| 解包出新的 icon / 主数据 | 双击 `update_resources.bat` → 按提示 git add/commit/push → 等 CI 刷 manifest |
| 后端代码 | 重启后端验证 → 升版本号 → commit/push → 打 tag 推送 |
| 前端代码 | `pnpm build` → （同上）升版本号、打 tag |
| 只改了仓库文档 | 直接 commit/push，不需要发版 |
| 只想本地验证更新功能 | 设 `WVD_UPDATE_MANIFEST` / `WVD_UPDATE_BASE` 指向本地文件，见 `docs/IMPLEMENTATION.md` |
