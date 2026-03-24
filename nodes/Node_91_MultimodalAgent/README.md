# Node_91_MultimodalAgent

多模态 Agent 推理与规划服务节点，结合视觉理解执行复杂命令规划与 MCP 工具调用。

## 端口
8091

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /execute_command` - 执行自然语言指令
- `POST /plan_actions` - 生成动作规划
- `POST /mcp/call` - 调用 MCP 工具
