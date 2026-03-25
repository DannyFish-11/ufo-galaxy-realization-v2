"""
tests/test_pr4_github_resource_integration.py
===============================================
PR-4 "GitHub System Resource Integration" 测试套件

验收标准覆盖:
  a) 现有 GitHub addon 安装行为保持不变 (installer path preserved)
  b) GitHub 仓库摄取可向统一知识流写入 (ingest_repo → Knowledge Core)
  c) 检索到的 GitHub 派生知识/上下文包含明确的来源标注
     (source_type="github_repo", source="github://owner/repo")
  d) 不引入孤立的平行 GitHub 专用知识权威
     (ingest uses RAGMemory.ingest_knowledge, not a competing store)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously in an isolated event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_installer(tmp_path):
    """Create a GitHubInstaller instance with an isolated install dir."""
    from core.github_installer import GitHubInstaller, _ManifestStore
    inst = GitHubInstaller.__new__(GitHubInstaller)
    inst._install_dir = tmp_path
    inst._manifest = _ManifestStore(tmp_path)
    return inst


def _make_ingester():
    """Create a fresh GitHubRepoIngester instance."""
    from core.github_installer import GitHubRepoIngester
    return GitHubRepoIngester.__new__(GitHubRepoIngester)


# ===========================================================================
# 1. Existing addon installation behavior (acceptance criterion a)
# ===========================================================================

class TestAddonInstallPreserved:
    """Verify that GitHub addon installation still works after PR-4 changes."""

    def test_dry_run_valid_url_still_works(self, tmp_path):
        """Dry-run install returns success for a valid URL."""
        inst = _make_installer(tmp_path)
        result = _run(inst.install("https://github.com/owner/repo", dry_run=True))
        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["owner"] == "owner"
        assert result["repo"] == "repo"

    def test_dry_run_invalid_url_still_fails(self, tmp_path):
        inst = _make_installer(tmp_path)
        result = _run(inst.install("not-a-url", dry_run=True))
        assert result["success"] is False
        assert "error" in result

    @patch("core.github_installer._register_mcp_tool")
    @patch("core.github_installer._fetch_repo")
    def test_install_mcp_tool_still_works(self, mock_fetch, mock_register, tmp_path):
        """MCP tool installation still registers and records manifest."""
        mcp_manifest = {"name": "pr4-test-mcp", "entrypoint": "server.py"}

        def _fake_fetch(owner, repo, ref, dest):
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "mcp_tool.json").write_text(json.dumps(mcp_manifest), encoding="utf-8")
            return "deadbeef01234567"

        mock_fetch.side_effect = _fake_fetch
        mock_register.return_value = {"success": True}

        inst = _make_installer(tmp_path)
        result = _run(inst.install("https://github.com/owner/repo"))

        assert result["success"] is True
        assert result["type"] == "mcp"
        assert result["name"] == "pr4-test-mcp"
        mock_register.assert_called_once()

    @patch("core.github_installer._register_skill")
    @patch("core.github_installer._fetch_repo")
    def test_install_skill_still_works(self, mock_fetch, mock_register, tmp_path):
        """Skill installation still registers and records manifest."""
        skill_manifest = {"name": "pr4-test-skill", "entrypoint": "handler.py"}

        def _fake_fetch(owner, repo, ref, dest):
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "skill.json").write_text(json.dumps(skill_manifest), encoding="utf-8")
            return "cafebabe01234567"

        mock_fetch.side_effect = _fake_fetch
        mock_register.return_value = {"success": True}

        inst = _make_installer(tmp_path)
        result = _run(inst.install("https://github.com/owner/skill-repo"))

        assert result["success"] is True
        assert result["type"] == "skill"
        mock_register.assert_called_once()

    @patch("core.github_installer._unregister_mcp_tool")
    def test_uninstall_still_works(self, mock_unreg, tmp_path):
        """Uninstall still removes files and manifest entry."""
        addon_dir = tmp_path / "owner" / "mcp-tool" / "main"
        addon_dir.mkdir(parents=True)
        (addon_dir / "server.py").write_text("# test", encoding="utf-8")

        inst = _make_installer(tmp_path)
        inst._manifest.put("mcp-tool", {
            "name": "mcp-tool",
            "type": "mcp",
            "install_path": str(addon_dir),
        })

        result = _run(inst.uninstall("mcp-tool"))
        assert result["success"] is True
        assert not addon_dir.exists()

    def test_list_installed_still_works(self, tmp_path):
        """list_installed returns correct addons."""
        inst = _make_installer(tmp_path)
        inst._manifest.put("tool-a", {"name": "tool-a", "type": "mcp"})
        result = inst.list_installed()
        assert result["success"] is True
        assert result["count"] == 1

    def test_get_status_still_works(self, tmp_path):
        """get_status returns token_configured, install_dir, etc."""
        inst = _make_installer(tmp_path)
        with patch.dict(os.environ, {"GITHUB_TOKEN": ""}):
            status = inst.get_status()
        assert status["success"] is True
        assert "token_configured" in status
        assert "total_installed" in status

    def test_get_github_installer_singleton(self):
        """get_github_installer() returns a GitHubInstaller singleton."""
        from core.github_installer import get_github_installer, GitHubInstaller
        inst = get_github_installer()
        assert isinstance(inst, GitHubInstaller)
        # Calling again returns the same object
        assert get_github_installer() is inst


# ===========================================================================
# 2. GitHub ingester — module-level availability
# ===========================================================================

class TestGitHubIngesterAvailability:
    """GitHubRepoIngester is available and accessible via singleton."""

    def test_ingester_class_exists(self):
        from core.github_installer import GitHubRepoIngester
        assert GitHubRepoIngester is not None

    def test_get_github_ingester_returns_instance(self):
        from core.github_installer import get_github_ingester, GitHubRepoIngester
        ingester = get_github_ingester()
        assert isinstance(ingester, GitHubRepoIngester)

    def test_get_github_ingester_is_singleton(self):
        from core.github_installer import get_github_ingester
        assert get_github_ingester() is get_github_ingester()

    def test_installer_and_ingester_are_separate_objects(self):
        """Installer and ingester are distinct classes (separate concerns)."""
        from core.github_installer import (
            get_github_installer,
            get_github_ingester,
            GitHubInstaller,
            GitHubRepoIngester,
        )
        assert not isinstance(get_github_ingester(), GitHubInstaller)
        assert not isinstance(get_github_installer(), GitHubRepoIngester)


# ===========================================================================
# 3. ingest_repo — URL validation
# ===========================================================================

class TestIngestRepoUrlValidation:
    """ingest_repo validates GitHub URLs via shared validate_repo_url."""

    def test_invalid_url_returns_failure(self):
        ingester = _make_ingester()
        result = _run(ingester.ingest_repo("not-a-url"))
        assert result["success"] is False
        assert "error" in result

    def test_blocklisted_url_returns_failure(self):
        ingester = _make_ingester()
        with patch.dict(os.environ, {"GITHUB_ALLOWLIST": "", "GITHUB_BLOCKLIST": "owner/*"}):
            result = _run(ingester.ingest_repo("https://github.com/owner/repo"))
        assert result["success"] is False

    def test_valid_url_passes_validation(self):
        """Valid URL passes validation even if API calls fail (network mocked)."""
        ingester = _make_ingester()
        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api", return_value=None),
        ):
            result = _run(ingester.ingest_repo("https://github.com/owner/repo"))
        assert result["success"] is True
        assert result["owner"] == "owner"
        assert result["repo"] == "repo"


# ===========================================================================
# 4. ingest_repo — Knowledge Core integration (acceptance criterion b)
# ===========================================================================

class TestIngestRepoKnowledgeCore:
    """ingest_repo feeds content into RAGMemory.ingest_knowledge()."""

    def test_readme_is_ingested_via_rag_memory(self, tmp_path):
        """README content is passed to RAGMemory.ingest_knowledge()."""
        ingester = _make_ingester()

        readme_text = "# My Project\n\nThis is the README for testing."
        ingested_calls = []

        def _fake_ingest_knowledge(content, source, source_type, tags, metadata):
            ingested_calls.append({
                "content": content,
                "source": source,
                "source_type": source_type,
                "tags": tags,
                "metadata": metadata,
            })
            return "entry-001"

        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.side_effect = _fake_ingest_knowledge

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api",
                  side_effect=lambda owner, repo, path, ref: readme_text if path == "README.md" else None),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            result = _run(ingester.ingest_repo("https://github.com/myorg/myrepo"))

        assert result["success"] is True
        assert result["ingested_count"] >= 1
        assert len(ingested_calls) >= 1
        # README body text should appear in the ingested content
        assert any("This is the README for testing." in c["content"] for c in ingested_calls)

    def test_ingest_returns_entry_ids(self):
        """ingest_repo returns non-empty entry_ids list on success."""
        ingester = _make_ingester()

        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "entry-xyz"

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api",
                  side_effect=lambda owner, repo, path, ref: "# content" if path == "README.md" else None),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            result = _run(ingester.ingest_repo("https://github.com/owner/repo"))

        assert result["success"] is True
        assert isinstance(result["entry_ids"], list)

    def test_ingest_multiple_files(self):
        """Multiple candidate files are each ingested separately."""
        ingester = _make_ingester()

        ingested_calls = []

        def _fake_ingest(content, source, source_type, tags, metadata):
            ingested_calls.append(metadata.get("file", ""))
            return f"entry-{len(ingested_calls)}"

        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.side_effect = _fake_ingest

        def _fake_fetch_file(owner, repo, path, ref):
            if path in ("README.md", "mcp_tool.json"):
                return f"# content for {path}"
            return None

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api", side_effect=_fake_fetch_file),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            result = _run(ingester.ingest_repo("https://github.com/owner/repo"))

        assert result["success"] is True
        assert result["ingested_count"] >= 2
        assert "README.md" in result["ingested_files"]
        assert "mcp_tool.json" in result["ingested_files"]

    def test_ingest_succeeds_when_rag_memory_unavailable(self):
        """ingest_repo succeeds even if RAGMemory cannot be imported."""
        ingester = _make_ingester()

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _selective_import(name, *args, **kwargs):
            if name == "core.rag_memory":
                raise ImportError("no rag")
            return original_import(name, *args, **kwargs)

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api",
                  side_effect=lambda owner, repo, path, ref: "content" if path == "README.md" else None),
            patch("builtins.__import__", side_effect=_selective_import),
        ):
            result = _run(ingester.ingest_repo("https://github.com/owner/repo"))

        assert result["success"] is True

    def test_ingest_zero_files_when_all_fetch_fail(self):
        """ingest_repo returns zero ingested files when API returns nothing."""
        ingester = _make_ingester()

        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "entry-0"

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api", return_value=None),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            result = _run(ingester.ingest_repo("https://github.com/owner/empty-repo"))

        assert result["success"] is True
        assert result["ingested_count"] == 0
        assert result["ingested_files"] == []
        # No ingest calls when no files were fetched
        mock_rag.ingest_knowledge.assert_not_called()


# ===========================================================================
# 5. Source attribution (acceptance criterion c)
# ===========================================================================

class TestSourceAttribution:
    """GitHub-derived knowledge/context carries clear source attribution."""

    def test_ingest_repo_source_label(self):
        """ingest_repo sets source='github://owner/repo' on every chunk."""
        ingester = _make_ingester()
        sources_seen = []

        def _fake_ingest(content, source, source_type, tags, metadata):
            sources_seen.append(source)
            return "eid"

        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.side_effect = _fake_ingest

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api",
                  side_effect=lambda o, r, p, ref: "content" if p == "README.md" else None),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            result = _run(ingester.ingest_repo("https://github.com/myorg/myrepo"))

        assert result["source"] == "github://myorg/myrepo"
        for src in sources_seen:
            assert src == "github://myorg/myrepo"

    def test_ingest_repo_source_type(self):
        """ingest_repo sets source_type='github_repo' on every chunk."""
        ingester = _make_ingester()
        source_types_seen = []

        def _fake_ingest(content, source, source_type, tags, metadata):
            source_types_seen.append(source_type)
            return "eid"

        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.side_effect = _fake_ingest

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api",
                  side_effect=lambda o, r, p, ref: "content" if p == "README.md" else None),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            _run(ingester.ingest_repo("https://github.com/myorg/myrepo"))

        for st in source_types_seen:
            assert st == "github_repo"

    def test_ingest_repo_tags_include_github_marker(self):
        """Ingested chunks have 'github' tag and 'github_repo:owner/repo' tag."""
        ingester = _make_ingester()
        tags_seen = []

        def _fake_ingest(content, source, source_type, tags, metadata):
            tags_seen.extend(tags)
            return "eid"

        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.side_effect = _fake_ingest

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api",
                  side_effect=lambda o, r, p, ref: "content" if p == "README.md" else None),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            _run(ingester.ingest_repo("https://github.com/myorg/myrepo"))

        assert "github" in tags_seen
        assert "github_repo:myorg/myrepo" in tags_seen

    def test_ingest_result_has_source_fields(self):
        """ingest_repo result dict exposes source and source_type."""
        ingester = _make_ingester()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "eid"

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api", return_value=None),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            result = _run(ingester.ingest_repo("https://github.com/org/prj"))

        assert result["source"] == "github://org/prj"
        assert result["source_type"] == "github_repo"

    def test_get_repo_context_source_fields(self):
        """get_repo_context result exposes source and source_type."""
        ingester = _make_ingester()

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={
                "description": "A test repo",
                "topics": ["testing"],
                "language": "Python",
                "default_branch": "main",
                "html_url": "https://github.com/org/prj",
            }),
            patch("core.github_installer._fetch_file_content_api", return_value=None),
        ):
            result = ingester.get_repo_context("https://github.com/org/prj")

        assert result["success"] is True
        assert result["source"] == "github://org/prj"
        assert result["source_type"] == "github_repo"

    def test_get_repo_context_metadata_ingested(self):
        """get_repo_context includes description, topics, language."""
        ingester = _make_ingester()

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={
                "description": "Galaxy test repo",
                "topics": ["ai", "galaxy"],
                "language": "Python",
                "default_branch": "main",
                "html_url": "https://github.com/org/prj",
            }),
            patch("core.github_installer._fetch_file_content_api",
                  side_effect=lambda o, r, p, ref: "# README content" if p == "README.md" else None),
        ):
            result = ingester.get_repo_context("https://github.com/org/prj")

        ctx = result["context"]
        assert ctx["description"] == "Galaxy test repo"
        assert "ai" in ctx["topics"]
        assert ctx["language"] == "Python"
        assert ctx["readme"].startswith("# README content")


# ===========================================================================
# 6. No parallel knowledge authority (acceptance criterion d)
# ===========================================================================

class TestNoParallelKnowledgeAuthority:
    """ingest_repo uses RAGMemory.ingest_knowledge(), not a competing store."""

    def test_ingest_calls_rag_memory_ingest_knowledge(self):
        """Knowledge is written through RAGMemory, not a private store."""
        ingester = _make_ingester()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "eid"

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api",
                  side_effect=lambda o, r, p, ref: "content" if p == "README.md" else None),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            result = _run(ingester.ingest_repo("https://github.com/owner/repo"))

        # Verify the canonical ingest path was called
        assert mock_rag.ingest_knowledge.called
        assert result["success"] is True

    def test_ingester_has_no_private_knowledge_store(self):
        """GitHubRepoIngester has no '_knowledge' or '_memory' private attr."""
        from core.github_installer import GitHubRepoIngester
        ingester = GitHubRepoIngester.__new__(GitHubRepoIngester)
        # The ingester should not own its own knowledge store
        assert not hasattr(ingester, "_knowledge_store")
        assert not hasattr(ingester, "_private_kb")
        assert not hasattr(ingester, "_github_memory")

    def test_ingest_result_does_not_expose_private_store(self):
        """ingest_repo result does not include a parallel knowledge dict."""
        ingester = _make_ingester()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "eid"

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api", return_value=None),
            patch("core.rag_memory.RAGMemory", return_value=mock_rag),
        ):
            result = _run(ingester.ingest_repo("https://github.com/owner/repo"))

        # Result must not expose a private knowledge authority
        assert "knowledge_store" not in result
        assert "private_kb" not in result
        assert "github_memory" not in result


# ===========================================================================
# 7. get_repo_context
# ===========================================================================

class TestGetRepoContext:
    """get_repo_context extracts engineering context without persisting."""

    def test_invalid_url(self):
        ingester = _make_ingester()
        result = ingester.get_repo_context("not-a-url")
        assert result["success"] is False

    def test_context_keys_present(self):
        ingester = _make_ingester()
        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api", return_value=None),
        ):
            result = ingester.get_repo_context("https://github.com/owner/repo")

        assert result["success"] is True
        ctx = result["context"]
        assert "readme" in ctx
        assert "description" in ctx
        assert "topics" in ctx
        assert "manifests" in ctx
        assert "html_url" in ctx

    def test_readme_truncated_to_4096(self):
        """README longer than 4096 chars is truncated."""
        ingester = _make_ingester()
        long_readme = "x" * 8000

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api",
                  side_effect=lambda o, r, p, ref: long_readme if p == "README.md" else None),
        ):
            result = ingester.get_repo_context("https://github.com/owner/repo")

        assert len(result["context"]["readme"]) == 4096

    def test_manifests_are_parsed_json(self):
        """JSON manifests in context are parsed, not raw strings."""
        ingester = _make_ingester()
        mcp_data = {"name": "test-tool", "version": "1.0.0"}

        def _fake_fetch(owner, repo, path, ref):
            if path == "mcp_tool.json":
                return json.dumps(mcp_data)
            return None

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api", side_effect=_fake_fetch),
        ):
            result = ingester.get_repo_context("https://github.com/owner/repo")

        manifests = result["context"]["manifests"]
        assert "mcp_tool.json" in manifests
        assert manifests["mcp_tool.json"]["name"] == "test-tool"

    def test_ref_override(self):
        """ref parameter is passed through to file fetches."""
        ingester = _make_ingester()
        refs_seen = []

        def _fake_fetch(owner, repo, path, ref):
            refs_seen.append(ref)
            return None

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api", side_effect=_fake_fetch),
        ):
            ingester.get_repo_context("https://github.com/owner/repo", ref="v2.0")

        assert all(r == "v2.0" for r in refs_seen)

    def test_does_not_call_rag_memory(self):
        """get_repo_context does NOT write to the Knowledge Core."""
        ingester = _make_ingester()

        with (
            patch("core.github_installer._fetch_repo_metadata_api", return_value={}),
            patch("core.github_installer._fetch_file_content_api", return_value=None),
            patch("core.rag_memory.RAGMemory") as mock_rag_cls,
        ):
            ingester.get_repo_context("https://github.com/owner/repo")

        # RAGMemory should not be instantiated by get_repo_context
        mock_rag_cls.assert_not_called()


# ===========================================================================
# 8. OpenClawd _dispatch_github_tool — new actions
# ===========================================================================

class TestOpenClawdGitHubDispatch:
    """OpenClawd dispatches github__ingest and github__context correctly."""

    def _make_openclawd_stub(self):
        """Create a minimal OpenClawd stub with _dispatch_github_tool."""
        from core.openclawd import OpenClawd
        oc = OpenClawd.__new__(OpenClawd)
        return oc

    def test_dispatch_ingest_missing_url(self):
        oc = self._make_openclawd_stub()
        result = _run(oc._dispatch_github_tool("ingest", {}))
        assert result["success"] is False
        assert "url" in result["error"]

    def test_dispatch_context_missing_url(self):
        oc = self._make_openclawd_stub()
        result = _run(oc._dispatch_github_tool("context", {}))
        assert result["success"] is False
        assert "url" in result["error"]

    def test_dispatch_unknown_action(self):
        oc = self._make_openclawd_stub()
        result = _run(oc._dispatch_github_tool("no_such_action", {}))
        assert result["success"] is False
        assert "no_such_action" in result["error"]

    def test_dispatch_ingest_delegates_to_ingester(self):
        """github__ingest delegates to GitHubRepoIngester.ingest_repo()."""
        oc = self._make_openclawd_stub()

        mock_ingester = MagicMock()
        mock_ingester.ingest_repo = AsyncMock(return_value={
            "success": True, "owner": "owner", "repo": "repo",
            "ingested_count": 1, "source": "github://owner/repo",
        })

        with patch("core.github_installer.get_github_ingester", return_value=mock_ingester):
            result = _run(oc._dispatch_github_tool(
                "ingest", {"url": "https://github.com/owner/repo"}
            ))

        assert result["success"] is True
        mock_ingester.ingest_repo.assert_called_once()
        call_kwargs = mock_ingester.ingest_repo.call_args
        assert call_kwargs.kwargs.get("url") == "https://github.com/owner/repo"

    def test_dispatch_context_delegates_to_ingester(self):
        """github__context delegates to GitHubRepoIngester.get_repo_context()."""
        oc = self._make_openclawd_stub()

        mock_ingester = MagicMock()
        mock_ingester.get_repo_context.return_value = {
            "success": True, "source": "github://owner/repo",
            "context": {"readme": "", "description": ""},
        }

        with patch("core.github_installer.get_github_ingester", return_value=mock_ingester):
            result = _run(oc._dispatch_github_tool(
                "context", {"url": "https://github.com/owner/repo"}
            ))

        assert result["success"] is True
        mock_ingester.get_repo_context.assert_called_once()

    def test_dispatch_install_still_routed_correctly(self):
        """github__install still routes to GitHubInstaller (not ingester)."""
        oc = self._make_openclawd_stub()

        mock_installer = MagicMock()
        mock_installer.install = AsyncMock(return_value={
            "success": True, "type": "mcp", "name": "my-tool",
        })

        with patch("core.github_installer.get_github_installer", return_value=mock_installer):
            result = _run(oc._dispatch_github_tool(
                "install", {"url": "https://github.com/owner/repo", "dry_run": True}
            ))

        assert result["success"] is True
        mock_installer.install.assert_called_once()

    def test_github_builtin_tools_include_ingest_and_context(self):
        """_GITHUB_BUILTIN_TOOLS contains github__ingest and github__context."""
        from core.openclawd import _GITHUB_BUILTIN_TOOLS

        tool_names = {t["function"]["name"] for t in _GITHUB_BUILTIN_TOOLS}
        assert "github__ingest" in tool_names
        assert "github__context" in tool_names

    def test_github_builtin_tools_preserve_existing_tools(self):
        """_GITHUB_BUILTIN_TOOLS still contains all pre-PR-4 tool definitions."""
        from core.openclawd import _GITHUB_BUILTIN_TOOLS

        tool_names = {t["function"]["name"] for t in _GITHUB_BUILTIN_TOOLS}
        assert "github__install" in tool_names
        assert "github__uninstall" in tool_names
        assert "github__list" in tool_names
        assert "github__status" in tool_names


# ===========================================================================
# 9. REST routes — new endpoints present
# ===========================================================================

class TestGitHubRoutes:
    """Verify new REST routes are registered in the router factory."""

    def _make_router(self):
        try:
            from core.routes.github import create_router
            return create_router()
        except ImportError:
            pytest.skip("fastapi not installed")

    def test_ingest_route_registered(self):
        router = self._make_router()
        paths = [r.path for r in router.routes]
        assert "/api/v1/github/ingest" in paths

    def test_context_route_registered(self):
        router = self._make_router()
        paths = [r.path for r in router.routes]
        assert "/api/v1/github/context" in paths

    def test_existing_routes_preserved(self):
        """All pre-PR-4 routes are still registered."""
        router = self._make_router()
        paths = [r.path for r in router.routes]
        assert "/api/v1/github/install" in paths
        assert "/api/v1/github/uninstall" in paths
        assert "/api/v1/github/list" in paths
        assert "/api/v1/github/status" in paths

    def test_ingest_route_is_post(self):
        router = self._make_router()
        ingest_routes = [r for r in router.routes if r.path == "/api/v1/github/ingest"]
        assert ingest_routes
        assert "POST" in ingest_routes[0].methods

    def test_context_route_is_post(self):
        router = self._make_router()
        ctx_routes = [r for r in router.routes if r.path == "/api/v1/github/context"]
        assert ctx_routes
        assert "POST" in ctx_routes[0].methods


# ===========================================================================
# 10. _fetch_file_content_api helper
# ===========================================================================

class TestFetchFileContentApi:
    """Unit tests for the _fetch_file_content_api helper."""

    def test_returns_decoded_content(self):
        import base64
        from core.github_installer import _fetch_file_content_api

        encoded = base64.b64encode(b"# Hello World\n").decode()
        api_response = json.dumps({"content": encoded + "\n"}).encode()

        with patch("core.github_installer._http_get", return_value=(200, api_response)):
            result = _fetch_file_content_api("owner", "repo", "README.md")

        assert result == "# Hello World\n"

    def test_returns_none_on_404(self):
        from core.github_installer import _fetch_file_content_api
        with patch("core.github_installer._http_get", return_value=(404, b"{}")):
            result = _fetch_file_content_api("owner", "repo", "MISSING.md")
        assert result is None

    def test_returns_none_on_exception(self):
        from core.github_installer import _fetch_file_content_api
        with patch("core.github_installer._http_get", side_effect=OSError("timeout")):
            result = _fetch_file_content_api("owner", "repo", "README.md")
        assert result is None


# ===========================================================================
# 11. _fetch_repo_metadata_api helper
# ===========================================================================

class TestFetchRepoMetadataApi:
    """Unit tests for the _fetch_repo_metadata_api helper."""

    def test_returns_parsed_metadata(self):
        from core.github_installer import _fetch_repo_metadata_api

        api_data = {
            "description": "A cool project",
            "topics": ["ai", "python"],
            "language": "Python",
            "default_branch": "main",
            "stargazers_count": 42,
            "html_url": "https://github.com/owner/repo",
        }

        with patch("core.github_installer._http_get",
                   return_value=(200, json.dumps(api_data).encode())):
            result = _fetch_repo_metadata_api("owner", "repo")

        assert result["description"] == "A cool project"
        assert result["topics"] == ["ai", "python"]
        assert result["language"] == "Python"
        assert result["stargazers_count"] == 42

    def test_returns_empty_dict_on_error(self):
        from core.github_installer import _fetch_repo_metadata_api
        with patch("core.github_installer._http_get", return_value=(404, b"{}")):
            result = _fetch_repo_metadata_api("owner", "repo")
        assert result == {}

    def test_returns_empty_dict_on_exception(self):
        from core.github_installer import _fetch_repo_metadata_api
        with patch("core.github_installer._http_get", side_effect=OSError("no net")):
            result = _fetch_repo_metadata_api("owner", "repo")
        assert result == {}
