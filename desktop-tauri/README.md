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
`GALAXY_ELECTRON_GPU`。`launcher/services.py` 会把这些一并注入。

## 前置依赖

- **Rust**（stable，≥1.77）：<https://rustup.rs>
- **Windows**：系统自带 **WebView2 Runtime**（Win10/11 一般已内置；没有就装 Evergreen Runtime）
- macOS/Linux 仅作开发参考（产品目标是 Windows）

## 构建 & 运行

```bash
cd desktop-tauri/src-tauri

# 开发跑（带控制台日志，热连前端静态资源）
cargo run

# 出 release 二进制（launcher/services.py 会自动优先用它）
cargo build --release
#   产物：target/release/galaxy-overlay(.exe)

# 出安装包（可选，需 tauri-cli：cargo install tauri-cli）
cargo tauri build
```

构建好 `target/release/galaxy-overlay(.exe)` 后，**正常 `python main.py` 即可**——
`launcher.services.GalaxyUnified.start_tauri()` 检测到该二进制就自动优先用 Tauri，
否则回退 Electron（见下「回退/共存」）。

## 回退 / 共存

- 迁移期 **Electron 原样保留**，作为自动兜底：没构建出 Tauri 二进制时，启动器照旧拉 Electron。
- 想强制用回 Electron：设 `GALAXY_DESKTOP_SHELL=electron`。
- 想强制用 Tauri：构建出二进制即可（启动器默认优先 Tauri）。

## 前端来源说明（避免重复造）

**前端源码只有一份**，仍在 `../electron/renderer/`。`build.rs` 在每次 `cargo build` 前
把**运行期需要的那部分**镜像到 `desktop-tauri/frontend/`，`frontendDist` 指向它。
该目录是构建产物（已 gitignore、每次重建），不是第二份可编辑的源。

### 为什么要这一步

`tauri` 会把 `frontendDist` **整个目录**嵌进二进制，而 `electron/renderer/panel/node_modules`
有 68 MB，运行期一个字节都用不到（Electron 与 Tauri 都只加载 `panel/dist/`）。

查过 `tauri-codegen-2.6.3/src/embedded_assets.rs`，资产收集是
`WalkDir::new(&path).follow_links(true)` —— **没有任何过滤机制**：没有 `.taurignore`，
没有 exclude 配置项。所以只能从目录内容下手。

实测（同一台机器，只改 `frontendDist`）：

| frontendDist | 源目录 | debug 二进制 |
|---|---|---|
| `../../electron/renderer` | 87.7 MB | 349.2 MB |
| `../frontend` | 7.8 MB | **331.1 MB** |

省 **18.1 MB**。注意源目录省了 79.8 MB 却只换来二进制省 18.1 MB —— tauri 对嵌入资产
做了压缩，而 `node_modules` 全是高度可压缩的文本。**别按源目录体积推算二进制收益。**

### 排除表用黑名单

见 `build.rs` 的 `EXCLUDE`。刻意用黑名单而不是白名单：新加一个前端文件时，白名单会
**默认漏掉**它，而漏掉的后果是"覆盖层只在 Tauri 构建里坏掉"—— CI 不构建 Tauri，没人
会发现。黑名单则是新文件默认带上。失败方向要选可恢复的那个。

`tests/test_tauri_frontend_staging.py` 钉住这条链不被悄悄接回去（不需要 Rust 工具链，
因为 CI 里没有任何作业构建 Tauri）。

## 已知风险（待你机器上回归）

1. **透明 + 点击穿透 + 置顶**在 WebView2 上历史偏挑剔：若覆盖层全黑/不透明，先确认 WebView2
   Runtime 是 Evergreen 最新版；必要时试 `GALAXY_ELECTRON_GPU=0`。
2. `getUserMedia`：`--use-fake-ui-for-media-stream` 已默认放行；若仍被拦，检查 WebView2 版本。
3. 面板需要先构建：`cd electron/renderer/panel && npm install && npm run build`（出 `dist/`），
   否则 panel 窗口加载 404（覆盖层不受影响）。
