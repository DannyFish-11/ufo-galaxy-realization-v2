# UI 资产来源与入口路径说明

> 本文档说明 Galaxy 系统中各前端 UI 的风格来源、设计理念及入口路径，
> 以便开发者快速定位正确的 UI 入口，避免命名/路径混乱。

---

## ~~1. Web Dashboard UI（浏览器访问，9000 端口）~~ — RETIRED (PR-1)

> **⚠️ RETIRED — `dashboard/frontend/` 已在 PR-1 中完全删除。**
> 不再存在任何面向运维人员的 Web 管理界面。
> `dashboard/backend/main.py` 以无头（headless）模式保留用于兼容性迁移，不提供任何 UI。
>
> 运维入口请使用：`windows_client/status_board_v2/`

---

## 1. Desktop Status Board（桌面状态板，唯一运维界面）

| 属性 | 详情 |
| ---- | ---- |
| **模块路径** | `windows_client/status_board_v2/` |
| **类型** | 桌面原生拓扑状态板 |
| **定位** | **唯一支持的运维人员操作界面** |

---

## 2. Windows 客户端 UI（桌面原生，PyQt5）

| 属性 | 详情 |
| ---- | ---- |
| **主入口文件** | `windows_client/main.py` |
| **UI 核心实现** | `windows_client/ui/galaxy_client_ui.py` |
| **侧边栏变体** | `windows_client/ui/sidebar_ui.py`（F12 呼出侧栏模式） |
| **兼容旧入口** | `enhancements/clients/windows_client/run_ui.py`（已废弃，自动重定向到 `windows_client/main.py`） |
| **启动方式** | ⚠️ **RETIRED** — `main.py` is hard-disabled; use `python unified_launcher.py` or `start.bat` |
| **UI 风格** | **OPPO 光场（Light Field）设计风格** |
| **设计灵感** | OPPO ColorOS 光场美学（ColorOS 14+） |
| **主要设计元素** | 流光渐变背景 + 径向光晕、磨砂半透明面板、圆角 + 柔阴影、流体动画、F12 快速唤出侧边栏 |
| **配色方案** | 纯黑/白/灰梯度（`COLORS["bg_dark"]="#000000"`），光场效果色（蓝 `#4FC3F7`、紫 `#B39DDB` 等） |
| **框架** | PyQt5 |

> ⚠️ **RETIRED (PR-8):** `START_CLIENT.bat` and `start_galaxy_client.bat` have been fully
> deleted. Use `start.bat` (Windows) or `python unified_launcher.py` as the canonical startup.

**Canonical startup:**

```bash
# Windows (canonical)
start.bat

# Cross-platform
python unified_launcher.py
```

---

## 3. 入口路径总结与修复说明

| 入口 | 状态 | 正确目标 |
| ---- | ---- | -------- |
| `python main.py` | ✅ **推荐** | 委托到 `unified_launcher.py`（权威启动路径） |
| `python unified_launcher.py` | ✅ 权威入口 | 完整系统启动，含 L4 模块 |
| `python windows_client/main.py` | ⚠️ **已停用** | 原桌面原生 UI — hard-disabled；使用 `windows_client/status_board_v2/` |
| `python enhancements/clients/windows_client/run_ui.py` | ❌ **已停用** | hard-disabled；使用 `unified_launcher.py` |
| `python start_galaxy.py` | ❌ **已删除** | 已从仓库中移除；使用 `main.py` |
| `python start_l4.py` | ❌ **已删除** | 已从仓库中移除；使用 `main.py` |
| `http://localhost:9000` (Web Dashboard) | ❌ **已停用** | Dashboard 前端已删除 |

> **注意**：`start_galaxy.py` 和 `start_l4.py` 已在 post-PR-10 清理中完全删除。
> 任何现有脚本中对这两个文件的调用都需要改为 `python main.py` 或
> `python unified_launcher.py`。

---

## 4. 风格来源声明

- **Windows 客户端 UI（OPPO 光场）**：设计灵感来源于 OPPO ColorOS 光场美学（公开设计语言），代码为项目团队基于 PyQt5 自主实现，未使用 OPPO 官方代码或专有资源。字体、图标均来自系统自带或开源资源。

---

## 5. 如何运行安全扫描

详见 `.github/workflows/codeql.yml`，CodeQL 分析会在每次推送 `main` 分支、
PR 以及每周一自动触发。也可在 GitHub Actions 页面手动触发（`workflow_dispatch`）。

本地静态检查：

```bash
# 安装开发依赖
pip install -r requirements-dev.txt

# Flake8 静态检查
flake8 core/ --max-line-length=120

# 格式化检查
black --check core/ tests/

# 导入顺序检查
isort --check-only core/ tests/
```

---

## 6. Windows 客户端 — OpenClawd 端口配置

`windows_client/ui/sidebar_ui.py` 中的 `SidebarUI` 通过 `_build_openclawd_api_base()`
自动确定 OpenClawd API 的地址，无需硬编码端口。优先级如下：

| 优先级 | 方式 | 示例 |
| ------ | ---- | ---- |
| 1 | `GALAXY_API_BASE` 环境变量（完整覆盖） | `GALAXY_API_BASE=http://10.0.0.5:9000` |
| 2 | `OPENCLAWD_HOST` + `OPENCLAWD_PORT` 环境变量 | `OPENCLAWD_PORT=9000` |
| 3 | `API_PORT` 环境变量（与服务端 `API_PORT` 保持一致） | `API_PORT=9000` |
| 4 | `unified_config.web_ui_port`（`config.json` / `.env` 中的值） | `web_ui_port: 9000` |
| 5 | 硬编码默认值（向后兼容） | `http://localhost:9000` |

**常见场景：**

```bash
# 服务端运行在非默认端口 9000
export OPENCLAWD_PORT=9000
python windows_client/main.py

# 或通过完整覆盖
export GALAXY_API_BASE=http://192.168.1.100:9000
python windows_client/main.py
```

> 若所有环境变量均未设置，且 `config.json` 中未指定 `web_ui_port`，
> 则自动回退到 `http://localhost:9000`（单一 API 入口端口）。
