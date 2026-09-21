"""
Unit tests for GitHub MCP/Skill Auto-Installer
================================================

Covers:
  - URL validation (valid, invalid, allowlist, blocklist)
  - Manifest store (put/get/remove)
  - Dry-run install
  - MCP tool registration (mocked)
  - Skill registration (mocked)
  - Uninstall (mocked)
  - list_installed / get_status
  - OpenClawd github__ tool dispatch
  - REST routes (mocked installer)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# 1. URL Validation
# ===========================================================================


class TestParseGitHubUrl:
    def test_simple_url(self):
        from core.github_installer import parse_github_url

        r = parse_github_url("https://github.com/owner/repo")
        assert r is not None
        assert r["owner"] == "owner"
        assert r["repo"] == "repo"
        assert r["ref"] == "HEAD"

    def test_url_with_git_suffix(self):
        from core.github_installer import parse_github_url

        r = parse_github_url("https://github.com/owner/repo.git")
        assert r is not None
        assert r["repo"] == "repo"

    def test_url_with_tree_ref(self):
        from core.github_installer import parse_github_url

        r = parse_github_url("https://github.com/owner/repo/tree/feature-branch")
        assert r is not None
        assert r["ref"] == "feature-branch"

    def test_invalid_url_ssh(self):
        from core.github_installer import parse_github_url

        assert parse_github_url("git@github.com:owner/repo.git") is None

    def test_invalid_url_http(self):
        from core.github_installer import parse_github_url

        assert parse_github_url("http://github.com/owner/repo") is None

    def test_invalid_url_random(self):
        from core.github_installer import parse_github_url

        assert parse_github_url("not-a-url") is None

    def test_url_with_trailing_slash(self):
        from core.github_installer import parse_github_url

        r = parse_github_url("https://github.com/owner/repo/")
        assert r is not None
        assert r["owner"] == "owner"


class TestValidateRepoUrl:
    def test_valid_no_lists(self):
        from core.github_installer import validate_repo_url

        with patch.dict(os.environ, {"GITHUB_ALLOWLIST": "", "GITHUB_BLOCKLIST": ""}):
            r = validate_repo_url("https://github.com/owner/repo")
        assert r["valid"] is True

    def test_allowlist_pass(self):
        from core.github_installer import validate_repo_url

        with patch.dict(os.environ, {"GITHUB_ALLOWLIST": "owner/*", "GITHUB_BLOCKLIST": ""}):
            r = validate_repo_url("https://github.com/owner/repo")
        assert r["valid"] is True

    def test_allowlist_fail(self):
        from core.github_installer import validate_repo_url

        with patch.dict(os.environ, {"GITHUB_ALLOWLIST": "other-org/*", "GITHUB_BLOCKLIST": ""}):
            r = validate_repo_url("https://github.com/owner/repo")
        assert r["valid"] is False
        assert "GITHUB_ALLOWLIST" in r["error"]

    def test_blocklist_blocks(self):
        from core.github_installer import validate_repo_url

        with patch.dict(os.environ, {"GITHUB_ALLOWLIST": "", "GITHUB_BLOCKLIST": "owner/repo"}):
            r = validate_repo_url("https://github.com/owner/repo")
        assert r["valid"] is False
        assert "GITHUB_BLOCKLIST" in r["error"]

    def test_blocklist_with_wildcard(self):
        from core.github_installer import validate_repo_url

        with patch.dict(os.environ, {"GITHUB_ALLOWLIST": "", "GITHUB_BLOCKLIST": "bad-actor/*"}):
            r = validate_repo_url("https://github.com/bad-actor/evil-tool")
        assert r["valid"] is False

    def test_invalid_url_returns_valid_false(self):
        from core.github_installer import validate_repo_url

        r = validate_repo_url("not-a-url")
        assert r["valid"] is False


# ===========================================================================
# 2. Manifest Store
# ===========================================================================


class TestManifestStore:
    def _make_store(self, tmp_dir: Path):
        from core.github_installer import _ManifestStore

        return _ManifestStore(tmp_dir)

    def test_put_and_get(self, tmp_path):
        store = self._make_store(tmp_path)
        store.put("my-tool", {"name": "my-tool", "type": "mcp"})
        r = store.get("my-tool")
        assert r is not None
        assert r["name"] == "my-tool"

    def test_remove(self, tmp_path):
        store = self._make_store(tmp_path)
        store.put("my-tool", {"name": "my-tool"})
        store.remove("my-tool")
        assert store.get("my-tool") is None

    def test_get_all(self, tmp_path):
        store = self._make_store(tmp_path)
        store.put("tool-a", {"name": "tool-a"})
        store.put("tool-b", {"name": "tool-b"})
        all_ = store.get_all()
        assert len(all_) == 2
        assert "tool-a" in all_
        assert "tool-b" in all_

    def test_get_missing_returns_none(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.get("nonexistent") is None

    def test_load_empty_dir(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.get_all() == {}


# ===========================================================================
# 3. GitHubInstaller — dry-run
# ===========================================================================


class TestGitHubInstallerDryRun:
    def _make_installer(self, tmp_path):
        from core.github_installer import GitHubInstaller

        inst = GitHubInstaller.__new__(GitHubInstaller)
        from core.github_installer import _ManifestStore

        inst._install_dir = tmp_path
        inst._manifest = _ManifestStore(tmp_path)
        return inst

    def test_dry_run_valid_url(self, tmp_path):
        inst = self._make_installer(tmp_path)
        result = _run(
            inst.install(
                url="https://github.com/owner/repo",
                dry_run=True,
            )
        )
        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["owner"] == "owner"
        assert result["repo"] == "repo"

    def test_dry_run_invalid_url(self, tmp_path):
        inst = self._make_installer(tmp_path)
        result = _run(
            inst.install(
                url="not-a-url",
                dry_run=True,
            )
        )
        assert result["success"] is False
        assert "error" in result

    def test_dry_run_blocklisted(self, tmp_path):
        inst = self._make_installer(tmp_path)
        with patch.dict(os.environ, {"GITHUB_ALLOWLIST": "", "GITHUB_BLOCKLIST": "owner/*"}):
            result = _run(
                inst.install(
                    url="https://github.com/owner/repo",
                    dry_run=True,
                )
            )
        assert result["success"] is False

    def test_dry_run_ref_override(self, tmp_path):
        inst = self._make_installer(tmp_path)
        result = _run(
            inst.install(
                url="https://github.com/owner/repo",
                ref="v2.0.0",
                dry_run=True,
            )
        )
        assert result["success"] is True
        assert result["ref"] == "v2.0.0"


# ===========================================================================
# 4. GitHubInstaller — install (mocked fetch)
# ===========================================================================


class TestGitHubInstallerInstall:
    @pytest.fixture(autouse=True)
    def _repo_is_pre_approved(self, monkeypatch):
        """把被测仓库放进 ``GITHUB_ALLOWLIST``。

        安装现在有一道准入闸(``core/github_addon_admission.py``):
        ``GITHUB_ALLOWLIST`` 为空时每次安装都要人确认,而测试环境没有设备可问 → 拒绝。
        本类 8 条用例会全红,**而且它们要验的东西一条都没验到**(克隆、检测类型、
        契约校验、manifest 落盘,全都在闸后面)。

        **用 allowlist 而不是 ``GALAXY_ADDON_UNATTENDED=1``。** 后者是"把闸关掉",
        那样这些用例会在一个生产里不存在的形态下跑,"某次安装忘了过闸"这类回归将
        不再有测试发现 —— 正是这道闸要消除的盲区,不该在测试侧原样重建一遍。
        前者是"这个仓库已获批准":闸照常判定、照常放行,被测的安装机制一点没少。

        这条区分在 ``test_invalid_skill_contract_rejected_before_deps`` 上最要命:
        不放进名单它照样 ``success=False``(**测试还是绿的**),但契约校验那一段
        一行都没跑到,用例形同虚设。
        """
        monkeypatch.setenv("GITHUB_ALLOWLIST", "owner/*")
        monkeypatch.delenv("GITHUB_BLOCKLIST", raising=False)

    def _make_installer(self, tmp_path, mcp_manifest=None, skill_manifest=None):
        """Return an installer with a mocked fetch that writes manifest files."""
        from core.github_installer import GitHubInstaller, _ManifestStore

        inst = GitHubInstaller.__new__(GitHubInstaller)
        inst._install_dir = tmp_path
        inst._manifest = _ManifestStore(tmp_path)
        return inst

    def _patch_fetch(self, dest_path, mcp_manifest=None, skill_manifest=None):
        """Create a side-effect function that writes manifest files to dest."""

        def _fake_fetch(owner, repo, ref, dest):
            dest.mkdir(parents=True, exist_ok=True)
            if mcp_manifest:
                (dest / "mcp_tool.json").write_text(json.dumps(mcp_manifest), encoding="utf-8")
            if skill_manifest:
                (dest / "skill.json").write_text(json.dumps(skill_manifest), encoding="utf-8")
            return "abc123deadbeef"

        return _fake_fetch

    @patch("core.github_installer._verify_mcp_install")
    @patch("core.github_installer._register_mcp_tool")
    @patch("core.github_installer._fetch_repo")
    def test_install_mcp_tool(self, mock_fetch, mock_register, mock_verify, tmp_path):
        mcp_manifest = {
            "name": "test-mcp",
            "entrypoint": "server.py",
            "description": "Test MCP",
        }
        mock_fetch.side_effect = self._patch_fetch(tmp_path, mcp_manifest=mcp_manifest)
        mock_register.return_value = {
            "success": True,
            "type": "mcp",
            "name": "test-mcp",
            "server_id": "mcp-server-1",
        }
        mock_verify.return_value = {"success": True}

        inst = self._make_installer(tmp_path)
        result = _run(inst.install("https://github.com/owner/repo"))

        assert result["success"] is True
        assert result["type"] == "mcp"
        assert result["name"] == "test-mcp"
        assert result["commit"] == "abc123deadbeef"
        mock_register.assert_called_once()

    @patch("core.github_installer._verify_callable_skill_install")
    @patch("core.github_installer._register_skill")
    @patch("core.github_installer._fetch_repo")
    def test_install_skill(self, mock_fetch, mock_register, mock_verify, tmp_path):
        skill_manifest = {
            "id": "test-skill",
            "name": "test-skill",
            "description": "Test Skill",
            "handler_file": "handler.py",
            "handler_function": "execute",
        }
        mock_fetch.side_effect = self._patch_fetch(tmp_path, skill_manifest=skill_manifest)
        mock_register.return_value = {
            "success": True,
            "type": "skill",
            "name": "test-skill",
            "skill_id": "test-skill",
        }
        mock_verify.return_value = {"success": True}

        inst = self._make_installer(tmp_path)
        result = _run(inst.install("https://github.com/owner/repo"))

        assert result["success"] is True
        assert result["type"] == "skill"
        assert result["name"] == "test-skill"
        mock_register.assert_called_once()

    @patch("core.github_installer.install_addon_deps")
    @patch("core.github_installer._register_skill")
    @patch("core.github_installer._fetch_repo")
    def test_invalid_skill_contract_rejected_before_deps(self, mock_fetch, mock_register, mock_install_deps, tmp_path):
        skill_manifest = {
            "id": "broken-skill",
            "name": "Broken Skill",
            "dependencies": ["example-dependency"],
        }
        mock_fetch.side_effect = self._patch_fetch(tmp_path, skill_manifest=skill_manifest)

        inst = self._make_installer(tmp_path)
        result = _run(inst.install("https://github.com/owner/broken-skill"))

        assert result["success"] is False
        assert "skill.json contract validation failed" in result["error"]
        assert result["violations"]
        mock_install_deps.assert_not_called()
        mock_register.assert_not_called()

    @pytest.mark.parametrize(
        ("missing_field", "expected_fragment"),
        [
            ("handler_file", "'handler_file' is required"),
            ("handler_function", "'handler_function' is required"),
        ],
    )
    @patch("core.github_installer.install_addon_deps")
    @patch("core.github_installer._register_skill")
    @patch("core.github_installer._fetch_repo")
    def test_skill_contract_reports_specific_missing_handler_fields(
        self,
        mock_fetch,
        mock_register,
        mock_install_deps,
        tmp_path,
        missing_field,
        expected_fragment,
    ):
        skill_manifest = {
            "id": "broken-skill",
            "name": "Broken Skill",
            "handler_file": "handler.py",
            "handler_function": "execute",
            "dependencies": ["example-dependency"],
        }
        skill_manifest.pop(missing_field)
        mock_fetch.side_effect = self._patch_fetch(tmp_path, skill_manifest=skill_manifest)

        inst = self._make_installer(tmp_path)
        result = _run(inst.install("https://github.com/owner/broken-skill"))

        assert result["success"] is False
        assert any(expected_fragment in violation for violation in result["violations"])
        mock_install_deps.assert_not_called()
        mock_register.assert_not_called()

    @patch("core.github_installer._fetch_repo")
    def test_install_no_manifest_is_a_success_not_a_failure(self, mock_fetch, tmp_path):
        """没有契约 = **以项目完整形式接入**，是一种成功的接法，不是一次失败。

        这条用例的断言是**故意改掉的**（原先断言 `success is False` + 有
        `failure_reason`）。改的理由不是为了让它变绿——改之前这条链是对的、
        断言也如实描述了当时的行为。是那个行为本身错了：

        `install_success` 对所有类型一律看 `registration && verification`，而普通
        仓库那条路的 `registration` 被写死成 `success: False`。于是接一个普通项目
        **永远**返回 success=False + HTTP 400，面板上只能显示成一次失败——而
        MCP / Skill 是 GitHub 项目的交集，不是它的定义：接一个仓库可能是为了拿它
        跑实验、读它、拿它当素材。

        变的只有"成没成"这个判定。**"它没成为一个可调用工具"这句话一个字都没少**：
        `install_state` 仍然是 `cloned_only`，`classification.integrable` 仍然是
        False，`integration.form` 是 `project`——下面逐条钉住，免得哪天有人把
        success 改对了却顺手把这几句删了，那才是真的把失败说成成功。
        """
        mock_fetch.side_effect = self._patch_fetch(tmp_path)

        inst = self._make_installer(tmp_path)
        result = _run(inst.install("https://github.com/owner/repo"))

        assert result["success"] is True, "接一个普通项目被判成了失败"
        assert result["type"] == "ordinary_tool_repo"
        assert result["install_state"] == "cloned_only", "落点状态被 success 带成了 verified"
        assert result["integration"]["form"] == "project"
        assert result["integration"]["ok"] is True
        assert result["classification"]["integrable"] is False, "没说清它不是一个可调用工具"
        assert "failure_reason" not in result, "成功的一次接入却带着失败原因"
        # 代码真的落盘了——"成功"不能只是一个布尔值。
        assert (tmp_path / result["install_path"].split(str(tmp_path))[-1].lstrip("/")).exists() or Path(
            result["install_path"]
        ).exists()

    @patch("core.github_installer._verify_skill_md_install")
    @patch("core.github_installer._register_skill_md")
    @patch("core.github_installer._fetch_repo")
    def test_install_skill_md(self, mock_fetch, mock_register, mock_verify, tmp_path):
        skill_md = (
            "---\n"
            "name: shell-skill\n"
            "description: shell command skill\n"
            "---\n\n"
            "```bash\n"
            "python --version\n"
            "```\n"
        )

        def _fake_fetch(owner, repo, ref, dest):
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "SKILL.md").write_text(skill_md, encoding="utf-8")
            return "abc123deadbeef"

        mock_fetch.side_effect = _fake_fetch
        mock_register.return_value = {
            "success": True,
            "type": "skill_md",
            "name": "shell-skill",
            "skill_id": "shell-skill",
        }
        mock_verify.return_value = {"success": True}

        inst = self._make_installer(tmp_path)
        result = _run(inst.install("https://github.com/owner/repo"))

        assert result["success"] is True
        assert result["type"] == "skill_md"
        assert result["name"] == "shell-skill"
        mock_register.assert_called_once()

    @patch("core.github_installer._register_mcp_tool")
    @patch("core.github_installer._fetch_repo")
    def test_install_records_manifest(self, mock_fetch, mock_register, tmp_path):
        mcp_manifest = {"name": "recorded-tool", "entrypoint": "s.py"}
        mock_fetch.side_effect = self._patch_fetch(tmp_path, mcp_manifest=mcp_manifest)
        mock_register.return_value = {"success": True}

        inst = self._make_installer(tmp_path)
        _run(inst.install("https://github.com/owner/recorded-tool"))

        stored = inst._manifest.get("recorded-tool")
        assert stored is not None
        assert stored["owner"] == "owner"
        assert stored["type"] == "mcp"
        assert "checksum" in stored
        assert "installed_at" in stored


# ===========================================================================
# 5. GitHubInstaller — uninstall
# ===========================================================================


class TestGitHubInstallerUninstall:
    def _make_installer(self, tmp_path):
        from core.github_installer import GitHubInstaller, _ManifestStore

        inst = GitHubInstaller.__new__(GitHubInstaller)
        inst._install_dir = tmp_path
        inst._manifest = _ManifestStore(tmp_path)
        return inst

    @patch("core.github_installer._unregister_mcp_tool")
    def test_uninstall_mcp(self, mock_unreg, tmp_path):
        addon_dir = tmp_path / "owner" / "repo" / "main"
        addon_dir.mkdir(parents=True)
        (addon_dir / "server.py").write_text("# test")

        inst = self._make_installer(tmp_path)
        inst._manifest.put(
            "my-tool",
            {
                "name": "my-tool",
                "type": "mcp",
                "install_path": str(addon_dir),
            },
        )

        result = _run(inst.uninstall("my-tool"))
        assert result["success"] is True
        assert result["name"] == "my-tool"
        mock_unreg.assert_called_once_with("my-tool")
        assert not addon_dir.exists()

    def test_uninstall_missing(self, tmp_path):
        inst = self._make_installer(tmp_path)
        result = _run(inst.uninstall("nonexistent"))
        assert result["success"] is False
        assert "not found" in result["error"]


# ===========================================================================
# 6. list_installed / get_status
# ===========================================================================


class TestGitHubInstallerStatus:
    def _make_installer(self, tmp_path):
        from core.github_installer import GitHubInstaller, _ManifestStore

        inst = GitHubInstaller.__new__(GitHubInstaller)
        inst._install_dir = tmp_path
        inst._manifest = _ManifestStore(tmp_path)
        return inst

    def test_list_empty(self, tmp_path):
        inst = self._make_installer(tmp_path)
        result = inst.list_installed()
        assert result["success"] is True
        assert result["count"] == 0
        assert result["addons"] == []

    def test_list_with_addons(self, tmp_path):
        inst = self._make_installer(tmp_path)
        inst._manifest.put("tool-a", {"name": "tool-a", "type": "mcp"})
        inst._manifest.put("skill-b", {"name": "skill-b", "type": "skill"})
        result = inst.list_installed()
        assert result["count"] == 2

    def test_get_status(self, tmp_path):
        inst = self._make_installer(tmp_path)
        inst._manifest.put("tool-a", {"name": "tool-a", "type": "mcp"})
        inst._manifest.put("skill-b", {"name": "skill-b", "type": "skill"})

        with patch.dict(
            os.environ,
            {
                "GITHUB_TOKEN": "fake-token",
                "GITHUB_INSTALL_DIR": str(tmp_path),
                "GITHUB_ALLOWLIST": "myorg/*",
                "GITHUB_BLOCKLIST": "",
            },
        ):
            result = inst.get_status()

        assert result["success"] is True
        assert result["token_configured"] is True
        assert result["mcp_tools"] == 1
        assert result["skills"] == 1
        assert "myorg/*" in result["allowlist"]

    def test_get_status_no_token(self, tmp_path):
        inst = self._make_installer(tmp_path)
        with patch.dict(os.environ, {"GITHUB_TOKEN": ""}):
            result = inst.get_status()
        assert result["token_configured"] is False


# ===========================================================================
# 7. OpenClawd github__ tool dispatch
# ===========================================================================


class TestOpenClawdGitHubDispatch:
    """Test the _dispatch_github_tool method of OpenClawd."""

    def _make_clawd(self):
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        return clawd

    @patch("core.github_installer.get_github_installer")
    def test_dispatch_list(self, mock_get_inst):
        mock_inst = MagicMock()
        mock_inst.list_installed.return_value = {"success": True, "count": 0, "addons": []}
        mock_get_inst.return_value = mock_inst

        clawd = self._make_clawd()
        result = _run(clawd._dispatch_github_tool("list", {}))
        assert result["success"] is True
        mock_inst.list_installed.assert_called_once()

    @patch("core.github_installer.get_github_installer")
    def test_dispatch_status(self, mock_get_inst):
        mock_inst = MagicMock()
        mock_inst.get_status.return_value = {"success": True, "token_configured": False}
        mock_get_inst.return_value = mock_inst

        clawd = self._make_clawd()
        result = _run(clawd._dispatch_github_tool("status", {}))
        assert result["success"] is True

    @patch("core.github_installer.get_github_installer")
    def test_dispatch_install(self, mock_get_inst):
        mock_inst = MagicMock()
        mock_inst.install = AsyncMock(return_value={"success": True, "name": "test-tool", "type": "mcp"})
        mock_get_inst.return_value = mock_inst

        clawd = self._make_clawd()
        result = _run(
            clawd._dispatch_github_tool(
                "install",
                {"url": "https://github.com/owner/repo"},
            )
        )
        assert result["success"] is True
        mock_inst.install.assert_awaited_once()

    @patch("core.github_installer.get_github_installer")
    def test_dispatch_install_missing_url(self, mock_get_inst):
        clawd = self._make_clawd()
        result = _run(clawd._dispatch_github_tool("install", {}))
        assert result["success"] is False
        assert "url" in result["error"]

    @patch("core.github_installer.get_github_installer")
    def test_dispatch_uninstall(self, mock_get_inst):
        mock_inst = MagicMock()
        mock_inst.uninstall = AsyncMock(return_value={"success": True, "name": "my-tool"})
        mock_get_inst.return_value = mock_inst

        clawd = self._make_clawd()
        result = _run(clawd._dispatch_github_tool("uninstall", {"name": "my-tool"}))
        assert result["success"] is True

    @patch("core.github_installer.get_github_installer")
    def test_dispatch_uninstall_missing_name(self, mock_get_inst):
        clawd = self._make_clawd()
        result = _run(clawd._dispatch_github_tool("uninstall", {}))
        assert result["success"] is False
        assert "name" in result["error"]

    def test_dispatch_unknown_action(self):
        clawd = self._make_clawd()
        result = _run(clawd._dispatch_github_tool("invalid_action", {}))
        assert result["success"] is False
        assert "Unknown github action" in result["error"]


# ===========================================================================
# 8. OpenClawd built-in tool schema presence
# ===========================================================================


class TestOpenClawdToolSchema:
    def test_github_tools_in_collect(self):
        """Verify _GITHUB_BUILTIN_TOOLS are defined and correctly structured."""
        from core.openclawd import _GITHUB_BUILTIN_TOOLS

        names = {t["function"]["name"] for t in _GITHUB_BUILTIN_TOOLS}
        assert "github__install" in names
        assert "github__uninstall" in names
        assert "github__list" in names
        assert "github__status" in names

    def test_github_install_schema_has_required_url(self):
        from core.openclawd import _GITHUB_BUILTIN_TOOLS

        install_tool = next(t for t in _GITHUB_BUILTIN_TOOLS if t["function"]["name"] == "github__install")
        params = install_tool["function"]["parameters"]
        assert "url" in params["properties"]
        assert "url" in params.get("required", [])


# ===========================================================================
# 9. REST Routes (minimal smoke tests using starlette TestClient)
# ===========================================================================


class TestGitHubRoutes:
    def _make_app(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            from core.routes.github import create_router

            app = FastAPI()
            app.include_router(create_router())
            return TestClient(app)
        except ImportError:
            return None

    @patch("core.github_installer.get_github_installer")
    def test_status_endpoint(self, mock_get_inst):
        client = self._make_app()
        if client is None:
            pytest.skip("fastapi[testclient] not installed")

        mock_inst = MagicMock()
        mock_inst.get_status.return_value = {
            "success": True,
            "token_configured": False,
            "install_dir": "/tmp",
            "allowlist": [],
            "blocklist": [],
            "total_installed": 0,
            "mcp_tools": 0,
            "skills": 0,
        }
        mock_get_inst.return_value = mock_inst

        resp = client.get("/api/v1/github/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    @patch("core.github_installer.get_github_installer")
    def test_list_endpoint(self, mock_get_inst):
        client = self._make_app()
        if client is None:
            pytest.skip("fastapi[testclient] not installed")

        mock_inst = MagicMock()
        mock_inst.list_installed.return_value = {"success": True, "count": 0, "addons": []}
        mock_get_inst.return_value = mock_inst

        resp = client.get("/api/v1/github/list")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch("core.github_installer.get_github_installer")
    def test_install_dry_run_endpoint(self, mock_get_inst):
        client = self._make_app()
        if client is None:
            pytest.skip("fastapi[testclient] not installed")

        mock_inst = MagicMock()
        mock_inst.install = AsyncMock(
            return_value={
                "success": True,
                "dry_run": True,
                "owner": "owner",
                "repo": "repo",
                "ref": "HEAD",
                "message": "Dry-run: URL is valid and would be installed.",
            }
        )
        mock_get_inst.return_value = mock_inst

        resp = client.post(
            "/api/v1/github/install",
            json={
                "url": "https://github.com/owner/repo",
                "dry_run": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is True

    @patch("core.github_installer.get_github_installer")
    def test_install_invalid_url_returns_400(self, mock_get_inst):
        client = self._make_app()
        if client is None:
            pytest.skip("fastapi[testclient] not installed")

        mock_inst = MagicMock()
        mock_inst.install = AsyncMock(
            return_value={
                "success": False,
                "error": "Invalid GitHub HTTPS URL",
            }
        )
        mock_get_inst.return_value = mock_inst

        resp = client.post(
            "/api/v1/github/install",
            json={
                "url": "not-a-url",
            },
        )
        assert resp.status_code == 400

    @patch("core.github_installer.get_github_installer")
    def test_uninstall_missing_name_returns_404(self, mock_get_inst):
        client = self._make_app()
        if client is None:
            pytest.skip("fastapi[testclient] not installed")

        mock_inst = MagicMock()
        mock_inst.uninstall = AsyncMock(
            return_value={
                "success": False,
                "error": "Addon 'unknown' not found in manifest.",
            }
        )
        mock_get_inst.return_value = mock_inst

        resp = client.post("/api/v1/github/uninstall", json={"name": "unknown"})
        assert resp.status_code == 404


# ===========================================================================
# 10. SHA256 checksum helper
# ===========================================================================


class TestSha256Dir:
    def test_deterministic(self, tmp_path):
        from core.github_installer import _sha256_dir

        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        h1 = _sha256_dir(tmp_path)
        h2 = _sha256_dir(tmp_path)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_different_content_different_hash(self, tmp_path):
        from core.github_installer import _sha256_dir

        (tmp_path / "a.txt").write_text("hello")
        h1 = _sha256_dir(tmp_path)
        (tmp_path / "a.txt").write_text("world")
        h2 = _sha256_dir(tmp_path)
        assert h1 != h2

    def test_empty_dir(self, tmp_path):
        from core.github_installer import _sha256_dir

        h = _sha256_dir(tmp_path)
        assert isinstance(h, str)
        assert len(h) == 64
