# Node_36_UIAWindows

## 简介

Windows 桌面自动化节点，使用 pyautogui/pygetwindow 实现 GUI 自动化操作

## 端口

默认端口：**8036**（可通过 `PORT` 环境变量覆盖）

## 依赖

```
fastapi>=0.109.0, uvicorn>=0.27.0, pydantic>=2.5.3, pyautogui, Pillow, pygetwindow, pyperclip
```

安装依赖：
```bash
pip install -r requirements.txt
```

## 环境变量

```
  PORT=8036
```

## 主要 API

此前这份清单和真实路由对不上（写了不存在的 `POST /double_click`，`/screenshot`
写成了 POST 而实际是 GET）。按代码核对后如下。

**每一个会动手的路由都要过动作权限闸**（`core.node_action_permissions`），
动作名取自 `config/node_catalog.json` 里本节点的 `permissions.actions`。
路由名和动作名**不是一回事**，所以下表把两边都列出来：

| 路由 | 过闸用的动作名 |
|---|---|
| `POST /click` | `click` |
| `POST /type` | `type_text` |
| `POST /hotkey` | `hotkey` |
| `POST /move` | `move_mouse` |
| `POST /drag` | `drag` |
| `GET /screenshot` | `screenshot` |
| `GET /mouse_position` | `get_mouse_position` |
| `GET /screen_size` | `get_screen_size` |
| `GET /windows` | `list_windows` |
| `POST /window` | `window_action` |

`POST /mcp/call` 的动作名由请求里的 `tool` 字段指定 —— 它是唯一能指名调用任意
动作的入口，因此更要过闸。

不过闸的两个，都只报告不动手：

- `GET /health` —— 容器存活探针（`deploy/compose/full.yml` 用它做 healthcheck）。
  把存活探针挂在另一个子系统上，子系统一坏就是重启循环。
- `GET /tools` —— 列出工具清单。

### 收紧这个节点

把动作从 `config/node_catalog.json` 的 `permissions.actions` 里删掉，对应的 HTTP
路由就会返回 403。**在加上这道闸之前，删了也没用** —— 统一执行器会拒绝，
而 HTTP 照常执行。

### 仍然没有的：身份认证

这道闸回答的是「这个动作被声明允许了吗」，**不是**「调用方是谁」。本节点的 HTTP
面没有任何认证，且和仓里另外 122 个节点一样绑在 `0.0.0.0`。在一个能操作桌面的
节点上这是个更大的问题，但它是全仓性的约定，不是本节点单独的缺陷 —— 只改这一个
既解决不了问题，又会和其余节点不一致。**部署时请确保 8036 不暴露到可信网络之外。**

## 启动

```bash
python main.py
```

## 健康检查

```bash
curl http://localhost:8036/health
```
