#!/usr/bin/env node
/**
 * Galaxy - Node.js MCP Server Demo
 * ======================================
 *
 * 这是一个完全符合 MCP 标准协议（JSON-RPC over stdio）的 Node.js 演示服务器。
 * 可以直接被 core/mcp_loader.py 或 mcp_bridge/bridge.py 加载。
 *
 * 提供的工具：
 *   1. echo       - 回显输入的消息
 *   2. timestamp  - 返回当前时间戳
 *
 * 启动方式：
 *   node server.js
 *
 * 加载方式（通过 Galaxy API）：
 *   POST /api/v1/mcp/load
 *   {"server_id": "node-demo", "command": "node /path/to/server.js"}
 */

"use strict";

const readline = require("readline");

// ============================================================================
// 工具定义
// ============================================================================

const TOOLS = [
  {
    name: "echo",
    description: "回显输入的消息（Echo back the input message）",
    inputSchema: {
      type: "object",
      properties: {
        message: {
          type: "string",
          description: "要回显的消息",
        },
      },
      required: ["message"],
    },
  },
  {
    name: "timestamp",
    description: "返回当前 Unix 时间戳（Return current Unix timestamp）",
    inputSchema: {
      type: "object",
      properties: {
        format: {
          type: "string",
          description: "格式：'unix'（默认）或 'iso'",
          enum: ["unix", "iso"],
        },
      },
    },
  },
];

// ============================================================================
// 工具处理函数
// ============================================================================

function handleEcho(args) {
  const message = args.message || "";
  return {
    content: [
      {
        type: "text",
        text: `Echo: ${message}`,
      },
    ],
  };
}

function handleTimestamp(args) {
  const format = args.format || "unix";
  const now = new Date();
  const value = format === "iso" ? now.toISOString() : Math.floor(now.getTime() / 1000).toString();
  return {
    content: [
      {
        type: "text",
        text: value,
      },
    ],
  };
}

// ============================================================================
// JSON-RPC 处理
// ============================================================================

function handleMessage(line) {
  let request;
  try {
    request = JSON.parse(line);
  } catch (e) {
    return; // 忽略非 JSON 行
  }

  const { jsonrpc, id, method, params } = request;
  let response;

  try {
    if (method === "initialize") {
      response = {
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion: "2024-11-05",
          capabilities: { tools: {} },
          serverInfo: {
            name: "galaxy-node-demo",
            version: "1.0.0",
          },
        },
      };
    } else if (method === "tools/list") {
      response = {
        jsonrpc: "2.0",
        id,
        result: { tools: TOOLS },
      };
    } else if (method === "tools/call") {
      const { name, arguments: args = {} } = params || {};
      let result;
      if (name === "echo") {
        result = handleEcho(args);
      } else if (name === "timestamp") {
        result = handleTimestamp(args);
      } else {
        response = {
          jsonrpc: "2.0",
          id,
          error: { code: -32601, message: `Unknown tool: ${name}` },
        };
        sendResponse(response);
        return;
      }
      response = { jsonrpc: "2.0", id, result };
    } else if (method === "notifications/initialized") {
      // 通知，不需要响应
      return;
    } else {
      response = {
        jsonrpc: "2.0",
        id,
        error: { code: -32601, message: `Method not found: ${method}` },
      };
    }
  } catch (err) {
    response = {
      jsonrpc: "2.0",
      id,
      error: { code: -32603, message: `Internal error: ${err.message}` },
    };
  }

  sendResponse(response);
}

function sendResponse(response) {
  process.stdout.write(JSON.stringify(response) + "\n");
}

// ============================================================================
// 主循环：逐行读取 stdin
// ============================================================================

const rl = readline.createInterface({
  input: process.stdin,
  output: null,
  terminal: false,
});

rl.on("line", (line) => {
  const trimmed = line.trim();
  if (trimmed) {
    handleMessage(trimmed);
  }
});

rl.on("close", () => {
  process.exit(0);
});

// 屏蔽未处理的异常，防止进程崩溃
process.on("uncaughtException", (err) => {
  process.stderr.write(`Uncaught: ${err.message}\n`);
});
