"""
Galaxy - MCP 多语言桥接层
============================

允许使用 Python 之外的语言（Node.js、Go、Rust 等）实现 MCP Server，
依然能被 core/mcp_loader.py 加载和调用。

规范：
- 子进程以标准 MCP JSON-RPC over stdio 通信
- 启动命令通过配置提供（如 "node /path/to/server.js"）
- 通过 /api/v1/mcp/load 加载后与现有系统完全兼容

使用方法：
    from mcp_bridge import MCPBridgeSpec, load_bridge_server

    # 加载 Node.js MCP 服务器
    spec = MCPBridgeSpec(
        server_id="node-demo",
        command="node /path/to/server.js",
        description="Node.js demo MCP server",
    )
    result = await load_bridge_server(spec)

桥接规范文档见：mcp_bridge/BRIDGE_SPEC.md
"""

from .bridge import MCPBridgeSpec, load_bridge_server, MCPBridgeLoader, get_bridge_loader

__all__ = ["MCPBridgeSpec", "load_bridge_server", "MCPBridgeLoader", "get_bridge_loader"]
