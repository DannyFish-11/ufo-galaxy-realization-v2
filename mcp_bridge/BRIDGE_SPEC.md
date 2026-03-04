# MCP Bridge 多语言桥接规范

> 版本：1.0  
> 日期：2026-03-04

## 概述

MCP Bridge 允许用任意语言（Node.js、Go、Rust、Java 等）实现 MCP Server，
只要该 Server 遵循本规范，就能被 UFO Galaxy 的 `mcp_bridge/bridge.py` 加载和调用。

## 协议

- **传输层**：标准输入/输出（stdin/stdout），每条消息占一行（`\n` 分隔）
- **编码**：UTF-8 JSON
- **格式**：JSON-RPC 2.0

## 必须实现的方法

### `initialize`

客户端在连接后发送，服务器必须返回能力声明。

请求：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "ufo-galaxy", "version": "2.0"}
  }
}
```

响应：
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "my-server", "version": "1.0.0"}
  }
}
```

### `tools/list`

列出服务器提供的所有工具。

请求：
```json
{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
```

响应：
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "my_tool",
        "description": "工具描述",
        "inputSchema": {
          "type": "object",
          "properties": {
            "param1": {"type": "string", "description": "参数说明"}
          },
          "required": ["param1"]
        }
      }
    ]
  }
}
```

### `tools/call`

调用指定工具。

请求：
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "my_tool",
    "arguments": {"param1": "value1"}
  }
}
```

成功响应：
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {"type": "text", "text": "工具执行结果"}
    ]
  }
}
```

错误响应：
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": {"code": -32601, "message": "Unknown tool: my_tool"}
}
```

## 注意事项

1. **每行一个 JSON 对象**，不要跨行
2. **stdout 只输出 JSON**，调试信息写到 stderr
3. 服务器进程在收到 stdin EOF 时应优雅退出
4. `notifications/initialized` 等通知消息无需响应

## 示例实现

参见 `mcp_bridge/examples/node_demo/server.js`（Node.js 纯 JS，无需安装依赖）。
