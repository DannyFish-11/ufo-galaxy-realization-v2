"""
协议路由 (MCP / Skill) 单元测试
"""

import pytest
from pydantic import ValidationError

from core.routes.protocols import (
    MCPLoadRequest,
    MCPToolCallRequest,
    SkillLoadRequest,
    SkillExecuteRequest,
    create_router,
)


class TestMCPLoadRequestValidation:
    """MCPLoadRequest 命令验证测试"""

    def test_valid_node_command(self):
        req = MCPLoadRequest(name="test-mcp", command="node /path/to/server.js")
        assert req.command == "node /path/to/server.js"

    def test_valid_python_command(self):
        req = MCPLoadRequest(name="test-mcp", command="python3 server.py")
        assert req.command == "python3 server.py"

    def test_valid_npx_command(self):
        req = MCPLoadRequest(name="test-mcp", command="npx @modelcontextprotocol/server")
        assert req.command == "npx @modelcontextprotocol/server"

    def test_valid_deno_command(self):
        req = MCPLoadRequest(name="test-mcp", command="deno run server.ts")
        assert req.command == "deno run server.ts"

    def test_reject_rm_command(self):
        with pytest.raises(ValidationError) as exc_info:
            MCPLoadRequest(name="bad", command="rm -rf /")
        assert "allowlist" in str(exc_info.value).lower() or "not in" in str(exc_info.value).lower()

    def test_reject_shell_pipe(self):
        with pytest.raises(ValidationError):
            MCPLoadRequest(name="bad", command="node server.js | cat")

    def test_reject_shell_semicolon(self):
        with pytest.raises(ValidationError):
            MCPLoadRequest(name="bad", command="node server.js; rm -rf /")

    def test_reject_shell_backtick(self):
        with pytest.raises(ValidationError):
            MCPLoadRequest(name="bad", command="node `whoami`")

    def test_reject_shell_dollar_paren(self):
        with pytest.raises(ValidationError):
            MCPLoadRequest(name="bad", command="node $(cat /etc/passwd)")

    def test_reject_empty_command(self):
        with pytest.raises(ValidationError):
            MCPLoadRequest(name="bad", command="   ")

    def test_reject_unknown_executable(self):
        with pytest.raises(ValidationError):
            MCPLoadRequest(name="bad", command="bash -c 'echo hello'")


class TestMCPToolCallRequest:
    """MCPToolCallRequest 验证测试"""

    def test_valid_tool_call(self):
        req = MCPToolCallRequest(tool_name="read_file", arguments={"path": "/tmp/a.txt"})
        assert req.tool_name == "read_file"
        assert req.arguments["path"] == "/tmp/a.txt"

    def test_empty_arguments(self):
        req = MCPToolCallRequest(tool_name="list_tools")
        assert req.arguments == {}


class TestSkillLoadRequest:
    """SkillLoadRequest 验证测试"""

    def test_valid_skill_load(self):
        req = SkillLoadRequest(name="web_search", path="/skills/web_search")
        assert req.name == "web_search"

    def test_defaults(self):
        req = SkillLoadRequest()
        assert req.name == ""
        assert req.path == ""
        assert req.config == {}


class TestSkillExecuteRequest:
    """SkillExecuteRequest 验证测试"""

    def test_valid_execute(self):
        req = SkillExecuteRequest(
            input={"query": "test"},
            context={"session_id": "s1"},
        )
        assert req.input["query"] == "test"


class TestCreateRouter:
    """create_router() 测试"""

    def test_returns_api_router(self):
        from fastapi import APIRouter
        router = create_router()
        assert isinstance(router, APIRouter)

    def test_router_has_routes(self):
        router = create_router()
        # 应至少有 10 个路由
        assert len(router.routes) >= 10
