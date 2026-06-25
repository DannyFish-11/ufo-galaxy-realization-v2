# Galaxy 桌面壳 — Tauri 版（替代 Electron）

把三态桌面覆盖层从 **Electron（背 Chromium，常驻几百 MB）** 迁到 **Tauri（系统 WebView2，几十 MB、几 MB 安装包）**。

**前端完全复用 `../electron/renderer/`**（lumiv 着色器、三态、感知、WebSocket、React 面板都不动）——
Tauri 只把 Electron 的主进程 `main.js` 用 Rust 重写为 `src-tauri/src/main.rs`，并复刻了它的全部契约：

| Electron 侧 | Tauri 侧（本项目） |
|---|---|
| `preload.js` 的 `window.galaxyAPI`（11 方法） | `main.rs` 的注入脚本 + `#[tauri::command]` 复刻 |
| overlay 窗口（透明/置顶/点击穿透/主屏 bounds） | `build_overlay` + `position_overlay_to_primary` + `set_ignore_cursor_events` |
| panel 窗口（热键开关，加载 `panel/dist`） | `build_panel` / `toggle_panel` |
| IPC HTTP 接收端 `:9231`（`/ipc/presence-state\|wake\|toggle-panel\|toggle-overlay`） | `start_ipc_http`（`tiny_http`）——**托盘/后端 bridge 无需改动** |
| 全局快捷键（唤醒/隐藏/面板，同一组候选键） | `tauri-plugin-global-shortcut` |
| 摄像头/麦克风 → 网关 `/api/perception/desktop/*` | `send_desktop_perception` 命令 |
| 首启感知授权弹框 + 持久化 | `resolve_perception_consent`（`tauri-plugin-dialog`） |
| 配置读写 `/api/config` + 广播 | `get_config`/`set_config`/`save_config` |
| `getUserMedia` 媒体授权 | WebView2 `--use-fake-ui-for-media-stream`（App 层用感知开关把关） |
| `GALAXY_ELECTRON_GPU=0` 软件渲染兜底 | 同名 env → WebView2 `--disable-gpu` |

读取的环境变量与 Electron 完全一致：`GALAXY_GATEWAY_PORT` / `PORT` / `GALAXY_IPC_PORT`
（默认 9231）/ `GALAXY_DESKTOP_PERCEPTION` / `GALAXY_DESKTOP_PERCEPTION_INTERVAL_MS` /
`GALAXY_ELECTRON_GPU`。unified_launcher 会把这些一并注入。

## 前置依赖

- **Rust**（stable，≥1.77）：<https://rustup.rs>
- **Windows**：系统自带 **WebView2 Runtime**（Win10/11 一般已内置；没有就装 Evergreen Runtime）
- macOS/Linux 仅作开发参考（产品目标是 Windows）

## 构建 & 运行

```bash
cd desktop-tauri/src-tauri

# 开发跑（带控制台日志，热连前端静态资源）
cargo run

# 出 release 二进制（unified_launcher 会自动优先用它）
cargo build --release
#   产物：target/release/galaxy-overlay(.exe)

# 出安装包（可选，需 tauri-cli：cargo install tauri-cli）
cargo tauri build
```

构建好 `target/release/galaxy-overlay(.exe)` 后，**正常 `python main.py` 即可**——
`unified_launcher.start_tauri()` 检测到该二进制就自动优先用 Tauri，
否则回退 Electron（见下「回退/共存」）。

## 回退 / 共存

- 迁移期 **Electron 原样保留**，作为自动兜底：没构建出 Tauri 二进制时，启动器照旧拉 Electron。
- 想强制用回 Electron：设 `GALAXY_DESKTOP_SHELL=electron`。
- 想强制用 Tauri：构建出二进制即可（启动器默认优先 Tauri）。

## 前端来源说明（避免重复造）

`tauri.conf.json` 的 `frontendDist` 直接指向 `../../electron/renderer`，**不复制前端**、单一真相来源。

> 注意：`cargo build` 会把 `frontendDist` 整个目录嵌进二进制。`electron/renderer/panel/`
> 里的 `node_modules` 与 `src` **运行期用不到**（只用 `panel/dist`）。想要更精简的二进制，
> 构建前可先删掉 `electron/renderer/panel/node_modules`（不影响运行，要改面板再 `npm i` 装回）。

## 已知风险（待你机器上回归）

1. **透明 + 点击穿透 + 置顶**在 WebView2 上历史偏挑剔：若覆盖层全黑/不透明，先确认 WebView2
   Runtime 是 Evergreen 最新版；必要时试 `GALAXY_ELECTRON_GPU=0`。
2. `getUserMedia`：`--use-fake-ui-for-media-stream` 已默认放行；若仍被拦，检查 WebView2 版本。
3. 面板需要先构建：`cd electron/renderer/panel && npm install && npm run build`（出 `dist/`），
   否则 panel 窗口加载 404（覆盖层不受影响）。
