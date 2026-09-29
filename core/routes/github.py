"""
Galaxy — GitHub System Resource REST Routes
============================================

Routes:
  POST /api/v1/github/install     — Install MCP tool or Skill from GitHub (API auth)
  GET  /api/v1/github/install/check — Validate URL / allowlist / ref without installing
  POST /api/v1/github/uninstall   — Uninstall an addon by name (API auth)
  GET  /api/v1/github/tools       — Tools the MCP gateway generated from GitHub installs
  GET  /api/v1/github/list        — List all installed GitHub addons
  GET  /api/v1/github/status      — Installer status (token, counts, dirs)
  POST /api/v1/github/ingest      — Ingest a GitHub repo into the Knowledge Core (API auth)
  POST /api/v1/github/context     — Retrieve engineering context from a GitHub repo

Token configuration:
  Set GITHUB_TOKEN in .env or via the Dashboard config page.
  The token is *never* accepted from chat input.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.auth import require_auth

logger = logging.getLogger("Galaxy.API")


# ── Request Models ────────────────────────────────────────────────────────────


class GitHubInstallRequest(BaseModel):
    """Request body for POST /api/v1/github/install."""

    url: str = Field(..., description="GitHub HTTPS repository URL")
    ref: Optional[str] = Field(None, description="Branch, tag, or commit SHA (overrides URL /tree/ ref)")
    type: Optional[str] = Field(
        None,
        description='Addon type: "mcp" | "skill" | "skill_md" | null (auto-detect from manifest)',
    )
    dry_run: bool = Field(False, description="Validate URL without actually installing")


class GitHubUninstallRequest(BaseModel):
    """Request body for POST /api/v1/github/uninstall."""

    name: str = Field(..., description="Addon name as recorded in the manifest")


class GitHubIngestRequest(BaseModel):
    """Request body for POST /api/v1/github/ingest."""

    url: str = Field(..., description="GitHub HTTPS repository URL")
    ref: Optional[str] = Field(None, description="Branch, tag, or commit SHA (optional)")
    include_code: bool = Field(False, description="Also ingest root-level source code files")


class GitHubContextRequest(BaseModel):
    """Request body for POST /api/v1/github/context."""

    url: str = Field(..., description="GitHub HTTPS repository URL")
    ref: Optional[str] = Field(None, description="Branch, tag, or commit SHA (optional)")


# ── Router Factory ─────────────────────────────────────────────────────────────


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create the GitHub addon routes router."""
    router = APIRouter()

    # ── POST /api/v1/github/install ─────────────────────────────────────────

    @router.post("/api/v1/github/install", dependencies=[Depends(require_auth)])
    async def github_install(req: GitHubInstallRequest):
        """Install an MCP tool or Skill from a GitHub repository.

        The repository must contain either ``mcp_tool.json`` (MCP tool) or
        ``skill.json`` (Skill) at its root unless ``type`` is forced.

        Requires ``GITHUB_TOKEN`` to be configured for private repos or to
        avoid GitHub API rate limits.
        """
        try:
            from core.github_installer import get_github_installer

            installer = get_github_installer()
            result = await installer.install(
                url=req.url,
                ref=req.ref,
                addon_type=req.type,
                dry_run=req.dry_run,
            )
            status_code = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status_code)
        except Exception as exc:
            logger.exception("github/install error")
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    # ── GET /api/v1/github/install/check ────────────────────────────────────

    @router.get("/api/v1/github/install/check")
    async def github_install_check(url: str = Query(..., max_length=512), ref: Optional[str] = None):
        """装之前先检查：只校验 URL / 白名单 / ref，不下载、不写盘。"""
        from core.github_installer import get_github_installer

        result = await get_github_installer().install_dry_run(url, ref=ref)
        return JSONResponse(result, status_code=200 if result.get("success") else 400)

    # ── POST /api/v1/github/uninstall ───────────────────────────────────────

    @router.post("/api/v1/github/uninstall", dependencies=[Depends(require_auth)])
    async def github_uninstall(req: GitHubUninstallRequest):
        """Uninstall a previously installed GitHub addon by name."""
        try:
            from core.github_installer import get_github_installer

            installer = get_github_installer()
            result = await installer.uninstall(req.name)
            status_code = 200 if result.get("success") else 404
            return JSONResponse(result, status_code=status_code)
        except Exception as exc:
            logger.exception("github/uninstall error")
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    # ── GET /api/v1/github/list ─────────────────────────────────────────────

    @router.get("/api/v1/github/list")
    async def github_list():
        """List all GitHub addons installed in this Galaxy instance."""
        try:
            from core.github_installer import get_github_installer

            installer = get_github_installer()
            return JSONResponse(installer.list_installed())
        except Exception as exc:
            logger.warning("github/list error: %s", exc)
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    # ── GET /api/v1/github/tools ────────────────────────────────────────────

    @router.get("/api/v1/github/tools")
    async def github_tools():
        """经 GitHub 装进 MCP 网关、已生成的工具。"""
        from core.mcp_gateway import get_mcp_gateway

        return JSONResponse({"tools": get_mcp_gateway().list_github_tools()})

    # ── GET /api/v1/github/status ───────────────────────────────────────────

    @router.get("/api/v1/github/status")
    async def github_status():
        """Return GitHub installer status.

        Indicates whether GITHUB_TOKEN is configured, the install directory,
        allowlist/blocklist settings, and installed counts.
        """
        try:
            from core.github_installer import get_github_installer

            installer = get_github_installer()
            return JSONResponse(installer.get_status())
        except Exception as exc:
            logger.warning("github/status error: %s", exc)
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    # ── POST /api/v1/github/ingest ──────────────────────────────────────────

    @router.post("/api/v1/github/ingest", dependencies=[Depends(require_auth)])
    async def github_ingest(req: GitHubIngestRequest):
        """Ingest a GitHub repository into the unified Knowledge Core.

        Fetches README, documentation, and manifest files from the
        repository and writes them into the Knowledge Core via
        ``RAGMemory.ingest_knowledge()``.  Every ingested chunk carries
        ``source_type="github_repo"`` and ``source="github://{owner}/{repo}"``
        for clear attribution.

        This route does **not** install the repository as an addon; use
        ``/api/v1/github/install`` for that.
        """
        try:
            from core.github_installer import get_github_ingester

            ingester = get_github_ingester()
            result = await ingester.ingest_repo(
                url=req.url,
                ref=req.ref,
                include_code=req.include_code,
            )
            status_code = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status_code)
        except Exception as exc:
            logger.exception("github/ingest error")
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    # ── POST /api/v1/github/context ─────────────────────────────────────────

    @router.post("/api/v1/github/context")
    async def github_context(req: GitHubContextRequest):
        """Retrieve structured engineering context from a GitHub repository.

        Returns README, description, topics, and manifests as a structured
        context dict.  The content is **not** persisted to the Knowledge
        Core; use ``/api/v1/github/ingest`` for persistent ingestion.

        Useful for injecting GitHub repository context into planning,
        coding, or debugging flows.
        """
        try:
            from core.github_installer import get_github_ingester

            ingester = get_github_ingester()
            result = ingester.get_repo_context(url=req.url, ref=req.ref)
            status_code = 200 if result.get("success") else 400
            return JSONResponse(result, status_code=status_code)
        except Exception as exc:
            logger.exception("github/context error")
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    return router
