# Node 107 — FunctionCalling

> **Port:** 8107  
> **Purpose:** OpenAI function-calling dispatcher with a dynamic tool registry.

## Overview

Node_107 maintains a registry of callable tools (built-in and external HTTP), accepts natural language prompts, leverages OpenAI's function-calling API to select the right tool, executes it, and returns structured results. External nodes or services can register themselves as callable tools at runtime.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model to use for function-calling |
| `NODE_107_PORT` | `8107` | Override the listening port |

## Built-in Tools

| Tool | Description |
|---|---|
| `get_current_time` | Returns current UTC time |
| `calculate` | Safe arithmetic evaluator (supports Python `math` functions) |
| `search_web` | Web search stub (configure an API for live results) |
| `get_node_status` | Calls `/health` on any Galaxy node URL |

## API Endpoints

### `GET /health`
Returns service health, OpenAI configuration status, and total tool count.

### `GET /status`
Detailed status including all registered tools.

### `GET /tools`
List all registered tools with their JSON schemas.

### `POST /call`
Send a natural language prompt; OpenAI picks the right tool and executes it.

**Request:**
```json
{
  "prompt": "What is the square root of 1764?",
  "tools": ["calculate"]
}
```
Omit `tools` to make all registered tools available.

**Response:**
```json
{
  "success": true,
  "tool_called": "calculate",
  "arguments": {"expression": "sqrt(1764)"},
  "result": {"expression": "sqrt(1764)", "result": 42.0}
}
```

### `POST /register_tool`
Register an external HTTP tool dynamically.

**Request:**
```json
{
  "name": "send_email",
  "description": "Send an email via the mail gateway",
  "parameters": {
    "type": "object",
    "properties": {
      "to": {"type": "string"},
      "subject": {"type": "string"},
      "body": {"type": "string"}
    },
    "required": ["to", "subject", "body"]
  },
  "handler_url": "http://localhost:8025/send"
}
```

When invoked, the node will `POST` the tool's `arguments` as JSON to `handler_url`.

### `DELETE /tools/{tool_name}`
Remove a tool from the registry.

### `POST /mcp/call`
MCP-compatible dispatcher. Set `"tool"` to one of: `call`, `register_tool`, `list_tools`, `health`.

## Docker

```bash
docker build -t node_107_functioncalling .
docker run -e OPENAI_API_KEY=sk-... -p 8107:8107 node_107_functioncalling
```

## Security Notes

- The `calculate` tool uses a sandboxed `eval` restricted to `math` module functions and basic arithmetic — no arbitrary code execution.
- External `handler_url` values are called with the arguments provided by OpenAI. Validate/sanitise handler endpoints before registering untrusted URLs.

## Related Nodes

- **Node_00_StateMachine** — can trigger function calls as part of state transitions
- **Node_02_Tasker** — orchestrates multi-step tasks using this node as a tool dispatcher
- **Node_109_ProactiveSensing** — can register event-driven callbacks as tools
