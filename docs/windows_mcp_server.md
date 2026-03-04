# Windows MCP Server & AIP 客户端 使用说明

本文档说明如何启动 **Windows 本地 MCP Server** 并将 Windows 主机注册到
UFO Galaxy 服务端，使大模型（ReAct Agent）可以直接调用 Windows UI 自动化能力。

---

## 一、Windows MCP Server

### 功能

将 `windows_client/autonomy/` 的本地能力暴露为标准 MCP 工具，工具列表：

| 工具名 | 说明 |
|--------|------|
| `get_screen_state` | 获取前台窗口 UI 树（可操作元素层级） |
| `click` | 鼠标点击（坐标） |
| `type` | 键入文本 |
| `press_key` | 按单个键（enter / escape / f5 …） |
| `press_keys` | 按组合键（['ctrl','c'] …） |
| `scroll` | 滚动鼠标滚轮 |
| `find_and_click` | 按 UI 元素名/AutomationId 查找并点击 |
| `find_and_type` | 按 UI 元素名/AutomationId 查找并输入 |
| `screenshot` | 截屏并返回 base64 PNG |

### 依赖

```bash
pip install pillow   # 截屏支持（可选，也可用 pyautogui）
# Windows 下 autonomy/ 还需要 comtypes（UI Automation）
pip install comtypes
```

### 启动命令

```bash
# 在 Windows 上，从仓库根目录执行
python windows_client/windows_mcp_server.py
```

MCP Server 通过 **stdio** 通信（JSON-RPC 2.0），由 `core/mcp_loader.py` 子进程启动。

---

## 二、通过 API 加载 Windows MCP Server

服务端启动后，通过 REST API 加载 Windows MCP Server：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/mcp/load \
  -H "Content-Type: application/json" \
  -d '{
    "name": "windows-local",
    "command": "python windows_client/windows_mcp_server.py"
  }'
```

响应示例：
```json
{
  "success": true,
  "server_id": "a1b2c3d4",
  "name": "windows-local",
  "status": "running"
}
```

加载成功后，工具将自动通过 `scheduler.inject_mcp_tools()` 注入到 ReAct Agent
可调用列表，工具名格式为 `mcp_{server_id}_{tool_name}`。

### 验证工具已加载

```bash
curl http://127.0.0.1:8000/api/v1/mcp/{server_id}/tools
```

---

## 三、Windows AIP 设备注册

让 Windows 主机作为设备加入 AIP 网络，与 Android 端一致被调度器识别：

```bash
# 在 Windows 上执行（需要安装 websockets）
pip install websockets
python windows_client/windows_aip_client.py --host 127.0.0.1 --port 8000
```

参数说明：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `127.0.0.1` | 服务端地址 |
| `--port` | `8000` | 服务端端口 |
| `--device-id` | 自动生成 | 自定义设备 ID |

客户端启动后会：
1. 连接 `ws://{host}:{port}/ws/device/{device_id}`
2. 发送 `device_register`（AIP v3.0 握手）
3. 发送 `capability_report`（上报 `supported_actions` 列表）
4. 维持心跳（每 30 秒）
5. 接收并执行服务端下发的任务命令

---

## 四、推荐工作流

```
1. 启动服务端:       python main.py  (或 uvicorn ...)
2. 加载 MCP Server:  POST /api/v1/mcp/load {"name":"windows-local","command":"python windows_client/windows_mcp_server.py"}
3. 注册 Windows 设备: python windows_client/windows_aip_client.py
4. 发起 Agent 任务:  POST /api/v1/agent/autonomous {"instruction":"截取当前屏幕截图"}
```

ReAct Agent 会自动选择 `mcp_*_screenshot` 工具执行截屏并返回结果。
