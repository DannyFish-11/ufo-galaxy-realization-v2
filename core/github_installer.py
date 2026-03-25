"""
Galaxy — GitHub System Resource Integration
============================================

GitHub is a **first-class system resource** with three roles:

1. **Addon source** — install MCP tools and Skills from GitHub repositories
   (original responsibility, fully preserved via ``GitHubInstaller``).
2. **Knowledge source** — ingest README/docs/manifests from GitHub repos into
   the unified Knowledge Core via ``RAGMemory.ingest_knowledge()``.
3. **Engineering context source** — extract structured repo context for
   planning, coding, and debugging flows via ``GitHubRepoIngester``.

Token is read from the ``GITHUB_TOKEN`` environment variable (or Dashboard
config); it is *never* accepted from chat input.

Key features
------------
* Validate GitHub HTTPS URL, extract owner/repo/ref.
* Shallow-clone or archive-download into
  ``data/github_addons/{owner}/{repo}/{ref}/``.
* Record install metadata (repo, ref, commit, timestamp, sha256) to
  ``data/github_addons/manifest.json``.
* Detect addon type (``mcp_tool.json`` → MCP, ``skill.json`` → Skill).
* Install Python dependencies into a per-addon venv (optional).
* Register MCP tools into ``MCPDynamicGateway`` / ``MCPLoader``.
* Register Skills into ``SkillLoader``.
* Uninstall and clean up.
* Dry-run mode.
* **Ingest repo content** (README/docs/manifests) into the unified Knowledge
  Core via ``GitHubRepoIngester.ingest_repo()``.
* **Extract engineering context** from GitHub repos via
  ``GitHubRepoIngester.get_repo_context()``.

Environment Variables
---------------------
``GITHUB_TOKEN``         — GitHub personal access token (optional, raises
                           rate-limit to 5000 req/h).
``GITHUB_INSTALL_DIR``   — Override default install root (default:
                           ``<project_root>/data/github_addons``).
``GITHUB_ALLOWLIST``     — Comma-separated owner/repo patterns that are
                           allowed (e.g. ``myorg/*,trusteduser/mcp-*``).
                           Empty means all allowed.
``GITHUB_BLOCKLIST``     — Comma-separated owner/repo patterns that are
                           blocked. Applied after allowlist check.

Constraints
-----------
* C1  — module-level singletons ``github_installer`` and ``github_ingester``.
* C7  — all public methods return ``{"success": bool, ...}``.
* C11 — uses stdlib ``logging``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.GitHubInstaller")

# ── Constants ─────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
_DEFAULT_INSTALL_DIR = _PROJECT_ROOT / "data" / "github_addons"
_MANIFEST_FILENAME = "manifest.json"
_MCP_TOOL_MANIFEST = "mcp_tool.json"
_SKILL_MANIFEST = "skill.json"

# Ingestion size limits — keep chunks small enough for the knowledge store
# while preserving meaningful context.  These are intentionally conservative.
_MAX_INGEST_FILE_SIZE = 8000    # bytes per file written to Knowledge Core
_MAX_CONTEXT_README_SIZE = 4096  # bytes of README returned by get_repo_context
_MAX_MANIFEST_SIZE = 2000        # bytes per manifest file in context result

# GitHub archive download URL template (no git required)
_ARCHIVE_URL_TMPL = (
    "https://api.github.com/repos/{owner}/{repo}/zipball/{ref}"
)
_GITHUB_API_BASE = "https://api.github.com"

# Regex for HTTPS GitHub URLs:
#   https://github.com/owner/repo
#   https://github.com/owner/repo.git
#   https://github.com/owner/repo/tree/branch-or-tag
_GH_URL_RE = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?"
    r"(?:/tree/(?P<ref>[^/?#]+))?"
    r"(?:[/?#].*)?$"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_token() -> str:
    """Return GITHUB_TOKEN from env (or empty string)."""
    return os.environ.get("GITHUB_TOKEN", "").strip()


def _get_install_dir() -> Path:
    raw = os.environ.get("GITHUB_INSTALL_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_INSTALL_DIR


def _get_allowlist() -> List[str]:
    raw = os.environ.get("GITHUB_ALLOWLIST", "").strip()
    return [p.strip() for p in raw.split(",") if p.strip()] if raw else []


def _get_blocklist() -> List[str]:
    raw = os.environ.get("GITHUB_BLOCKLIST", "").strip()
    return [p.strip() for p in raw.split(",") if p.strip()] if raw else []


def _match_pattern(owner: str, repo: str, patterns: List[str]) -> bool:
    """Return True if owner/repo matches any of the glob patterns."""
    slug = f"{owner}/{repo}"
    for pat in patterns:
        if fnmatch.fnmatch(slug, pat):
            return True
    return False


def _sha256_dir(directory: Path) -> str:
    """Compute a deterministic SHA-256 of all file contents under *directory*."""
    h = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(directory))
            h.update(rel.encode())
            h.update(path.read_bytes())
    return h.hexdigest()


def _http_get(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, bytes]:
    """Minimal HTTP GET using urllib (no third-party deps)."""
    import urllib.request

    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode(), resp.read()
    except Exception as exc:
        logger.debug("HTTP GET %s failed: %s", url, exc)
        raise


def _build_gh_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ── URL Validation ────────────────────────────────────────────────────────────

def parse_github_url(url: str) -> Optional[Dict[str, str]]:
    """Parse a GitHub HTTPS URL and return ``{owner, repo, ref}`` or ``None``."""
    m = _GH_URL_RE.match(url.strip())
    if not m:
        return None
    return {
        "owner": m.group("owner"),
        "repo": m.group("repo").removesuffix(".git"),
        "ref": m.group("ref") or "HEAD",
    }


def validate_repo_url(url: str) -> Dict[str, Any]:
    """Validate a GitHub repo URL and apply allowlist/blocklist rules.

    Returns:
        ``{"valid": True, "owner": ..., "repo": ..., "ref": ...}``
        or ``{"valid": False, "error": ...}``
    """
    parsed = parse_github_url(url)
    if not parsed:
        return {"valid": False, "error": f"Invalid GitHub HTTPS URL: {url!r}"}

    owner, repo = parsed["owner"], parsed["repo"]
    allowlist = _get_allowlist()
    blocklist = _get_blocklist()

    if allowlist and not _match_pattern(owner, repo, allowlist):
        return {
            "valid": False,
            "error": (
                f"Repository {owner}/{repo} is not in GITHUB_ALLOWLIST. "
                "Add it or leave GITHUB_ALLOWLIST empty to allow all."
            ),
        }

    if blocklist and _match_pattern(owner, repo, blocklist):
        return {
            "valid": False,
            "error": f"Repository {owner}/{repo} is blocked by GITHUB_BLOCKLIST.",
        }

    return {"valid": True, **parsed}


# ── Manifest Persistence ──────────────────────────────────────────────────────

class _ManifestStore:
    """Simple JSON manifest for installed addons."""

    def __init__(self, install_dir: Path) -> None:
        self._path = install_dir / _MANIFEST_FILENAME
        self._install_dir = install_dir

    def _load(self) -> Dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"addons": {}}

    def _save(self, data: Dict[str, Any]) -> None:
        self._install_dir.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get_all(self) -> Dict[str, Any]:
        return self._load().get("addons", {})

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._load().get("addons", {}).get(name)

    def put(self, name: str, record: Dict[str, Any]) -> None:
        data = self._load()
        data.setdefault("addons", {})[name] = record
        self._save(data)

    def remove(self, name: str) -> None:
        data = self._load()
        data.get("addons", {}).pop(name, None)
        self._save(data)


# ── Downloader ────────────────────────────────────────────────────────────────

def _resolve_ref(owner: str, repo: str, ref: str) -> Optional[str]:
    """Resolve a ref/branch/tag to a commit SHA via GitHub API."""
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/commits/{ref}"
    try:
        status, body = _http_get(url, _build_gh_headers())
        if status == 200:
            data = json.loads(body)
            return data.get("sha", "")
    except Exception as exc:
        logger.debug("resolve_ref %s/%s@%s failed: %s", owner, repo, ref, exc)
    return None


def _download_and_extract(
    owner: str, repo: str, ref: str, dest: Path
) -> Optional[str]:
    """Download a ZIP archive of the repo and extract to *dest*.

    Returns the resolved commit SHA if successful, else ``None``.
    """
    import zipfile
    import io

    # Resolve commit SHA first
    commit_sha = _resolve_ref(owner, repo, ref)

    archive_url = _ARCHIVE_URL_TMPL.format(owner=owner, repo=repo, ref=ref)
    headers = _build_gh_headers()
    headers["Accept"] = "application/vnd.github+json"

    logger.info("Downloading %s/%s@%s from %s", owner, repo, ref, archive_url)
    try:
        status, body = _http_get(archive_url, headers)
        if status not in (200, 302):
            logger.error("Download failed (status=%s)", status)
            return None
    except Exception as exc:
        logger.error("Download error: %s", exc)
        return None

    # Extract ZIP (GitHub sends application/zip)
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            # GitHub zips have a top-level dir like "{owner}-{repo}-{sha}/"
            members = zf.namelist()
            top_dir = members[0].split("/")[0] if members else ""

            dest.mkdir(parents=True, exist_ok=True)
            zf.extractall(dest.parent)

            # Move contents from the top-level dir to dest
            extracted = dest.parent / top_dir
            if extracted.exists() and extracted != dest:
                if dest.exists():
                    shutil.rmtree(dest)
                extracted.rename(dest)
    except Exception as exc:
        logger.error("Extract error: %s", exc)
        return None

    return commit_sha


def _clone_shallow(owner: str, repo: str, ref: str, dest: Path) -> Optional[str]:
    """Shallow-clone the repo using git (if available).

    Returns the HEAD commit SHA, or ``None`` on failure.
    """
    if shutil.which("git") is None:
        return None

    dest.parent.mkdir(parents=True, exist_ok=True)
    token = _get_token()
    if token:
        clone_url = f"https://{token}@github.com/{owner}/{repo}.git"
    else:
        clone_url = f"https://github.com/{owner}/{repo}.git"

    cmd = ["git", "clone", "--depth", "1", "--branch", ref, clone_url, str(dest)]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            logger.debug("git clone failed: %s", result.stderr)
            return None

        # Get commit SHA
        rev = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return rev.stdout.strip() if rev.returncode == 0 else None
    except Exception as exc:
        logger.debug("clone error: %s", exc)
        return None


def _fetch_repo(owner: str, repo: str, ref: str, dest: Path) -> Optional[str]:
    """Fetch repo using git-clone (preferred) or archive download.

    Returns resolved commit SHA on success, None on failure.
    """
    # Try git first (works well with tags/branches)
    sha = _clone_shallow(owner, repo, ref, dest)
    if sha:
        return sha

    # Fall back to archive download
    sha = _download_and_extract(owner, repo, ref, dest)
    return sha


# ── Dependency Installation ───────────────────────────────────────────────────

def _install_deps(addon_dir: Path, deps: List[str]) -> bool:
    """Install Python dependencies for an addon.

    Uses the current Python environment (pip install --target is avoided to
    keep things simple; a venv per addon would be safer but heavier).
    Deps may be package names or paths relative to addon_dir.
    """
    if not deps:
        return True

    pip_cmd = [sys.executable, "-m", "pip", "install", "--quiet"]
    for dep in deps:
        dep = dep.strip()
        if not dep:
            continue
        # Relative paths (e.g. ".") resolved against addon_dir
        if dep.startswith(".") or dep.startswith("/"):
            dep_path = str((addon_dir / dep).resolve())
            pip_cmd.append(dep_path)
        else:
            pip_cmd.append(dep)

    req_file = addon_dir / "requirements.txt"
    if req_file.exists():
        pip_cmd += ["-r", str(req_file)]

    logger.info("Installing dependencies: %s", pip_cmd[3:])  # skip ['python', '-m', 'pip']
    try:
        result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.warning("Dependency install warnings/errors: %s", result.stderr[:500])
        return result.returncode == 0
    except Exception as exc:
        logger.warning("Dependency install failed: %s", exc)
        return False


# ── Registration Helpers ──────────────────────────────────────────────────────

def _build_mcp_command(addon_dir: Path, entrypoint: Any) -> List[str]:
    """Resolve an entrypoint value to a launch command list."""
    if isinstance(entrypoint, list):
        # Last element is treated as the script path relative to addon_dir
        return [
            str(addon_dir / part) if i == len(entrypoint) - 1 else part
            for i, part in enumerate(entrypoint)
        ]
    entrypoint_str = str(entrypoint)
    if entrypoint_str.endswith(".py"):
        return [sys.executable, str(addon_dir / entrypoint_str)]
    if entrypoint_str.endswith(".js"):
        node_exec = shutil.which("node") or "node"
        return [node_exec, str(addon_dir / entrypoint_str)]
    return [str(addon_dir / entrypoint_str)]


def _register_mcp_tool(addon_dir: Path, tool_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate *tool_manifest* against the MCP addon contract and register it.

    Validation is performed via :func:`~core.mcp_addon_contract.validate_mcp_addon_contract`
    before any registration attempt.  Invalid manifests are rejected with a
    structured error dict (``{"success": False, "error": ..., "violations": [...]}``)
    without touching MCPLoader or the capability registry.

    Registration order:
    1. ``MCPLoader.load()`` (primary path).
    2. ``MCPDynamicGateway.register_external_tool()`` (fallback, only when
       MCPLoader.load() explicitly signals failure).

    After a successful primary-path registration the capability registry is
    refreshed automatically by MCPLoader's ``_refresh_capability_registry``.
    """
    # ── Contract validation ──────────────────────────────────────────────────
    try:
        from core.mcp_addon_contract import validate_mcp_addon_contract, MCPAddonContractError
        contract = validate_mcp_addon_contract(tool_manifest)
    except ImportError:
        # Graceful degradation: fall back to minimal field checks if the
        # contract module is unavailable (should never happen in production).
        logger.warning(
            "core.mcp_addon_contract not available; falling back to minimal validation"
        )
        name = tool_manifest.get("name", "")
        if not name:
            return {"success": False, "error": "mcp_tool.json missing 'name' field"}
        entrypoint = tool_manifest.get("entrypoint")
        if not entrypoint:
            return {"success": False, "error": "mcp_tool.json missing 'entrypoint' field"}
        contract = None  # type: ignore[assignment]
    except Exception as exc:  # MCPAddonContractError or TypeError
        violations = getattr(exc, "violations", [str(exc)])
        addon_name = tool_manifest.get("name", "")
        logger.warning(
            "MCP addon contract validation failed for '%s': %s", addon_name, violations
        )
        return {
            "success": False,
            "error": f"mcp_tool.json contract validation failed: {exc}",
            "violations": violations,
        }

    # Use normalised values from validated contract when available.
    if contract is not None:
        name = contract.name
        entrypoint = contract.entrypoint
        env_vars: Dict[str, str] = contract.env
    else:
        name = str(tool_manifest.get("name", ""))
        entrypoint = tool_manifest.get("entrypoint")
        env_vars = tool_manifest.get("env", {})

    # Build command
    command = _build_mcp_command(addon_dir, entrypoint)

    try:
        from core.mcp_loader import mcp_loader
        import asyncio

        async def _do_load():
            return await mcp_loader.load(
                server_id=name,
                command=command,
                env=env_vars if env_vars else None,
            )

        try:
            loop = asyncio.get_running_loop()
            # There is a running loop — schedule as a task and block via
            # run_coroutine_threadsafe from a fresh thread to avoid deadlock.
            future = asyncio.run_coroutine_threadsafe(_do_load(), loop)
            result = future.result(timeout=60)
        except RuntimeError:
            # No running loop — create a fresh one.
            result = asyncio.run(_do_load())

        if not result.get("success", False):
            # Try MCPDynamicGateway as fallback
            from core.mcp_gateway import get_mcp_gateway
            gw = get_mcp_gateway()
            gw_result = gw.register_external_tool(name, command, tool_manifest)
            return gw_result

        logger.info("MCP tool '%s' registered via MCPLoader", name)
        reg_info: Dict[str, Any] = {"success": True, "type": "mcp", "name": name, "loader": "MCPLoader"}
        if contract is not None:
            reg_info["schema_version"] = contract.schema_version
            reg_info["protocol"] = contract.protocol
            reg_info["transport"] = contract.transport
        return reg_info

    except Exception as exc:
        logger.warning("MCP registration failed for '%s': %s", name, exc)
        return {"success": False, "error": str(exc)}


def _register_skill(addon_dir: Path, skill_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Register a Skill addon into SkillLoader.

    Validates the manifest against :class:`~core.skill_package_contract.SkillPackageContract`
    (PR-005) before delegating to :class:`~core.skill_loader.SkillLoader`.
    Returns a structured error dict when the contract is violated.
    """
    # ── Contract validation (PR-005) ────────────────────────────────────────
    try:
        from core.skill_package_contract import (
            validate_skill_package_contract,
            SkillPackageContractError,
            build_skill_package_contract_summary,
        )
        contract = validate_skill_package_contract(skill_manifest)
        logger.debug(
            "skill.json contract validated: %s",
            build_skill_package_contract_summary(contract),
        )
    except SkillPackageContractError as exc:
        logger.warning(
            "Skill install rejected — skill.json contract invalid: %s",
            exc.violations,
        )
        return {
            "success": False,
            "error": f"skill.json contract validation failed: {exc.violations}",
            "violations": exc.violations,
            "error_code": exc.error_code,
        }
    except TypeError as exc:
        return {"success": False, "error": str(exc)}

    # Contract validation guarantees 'name' is non-empty; prefer it over 'id' for display.
    name = skill_manifest.get("name") or skill_manifest.get("id", "")

    try:
        from core.skill_loader import skill_loader
        import asyncio

        async def _do_load():
            return await skill_loader.load(str(addon_dir))

        try:
            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(_do_load(), loop)
            result = future.result(timeout=60)
        except RuntimeError:
            result = asyncio.run(_do_load())

        if result.get("success", False):
            logger.info("Skill '%s' registered via SkillLoader", name)
            return {
                "success": True,
                "type": "skill",
                "name": name,
                "schema_version": skill_manifest.get("schema_version", "1"),
            }
        return {"success": False, "error": result.get("error", "SkillLoader.load failed")}

    except Exception as exc:
        logger.warning("Skill registration failed for '%s': %s", name, exc)
        return {"success": False, "error": str(exc)}


def _unregister_mcp_tool(name: str) -> bool:
    try:
        from core.mcp_loader import mcp_loader
        import asyncio

        async def _do_unload():
            return await mcp_loader.unload(name)

        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(_do_unload(), loop).result(timeout=30)
        except RuntimeError:
            asyncio.run(_do_unload())
        return True
    except Exception as exc:
        logger.debug("MCP unregister '%s': %s", name, exc)
        return False


def _unregister_skill(name: str) -> bool:
    try:
        from core.skill_loader import skill_loader
        import asyncio

        async def _do_unload():
            return await skill_loader.unload(name)

        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(_do_unload(), loop).result(timeout=30)
        except RuntimeError:
            asyncio.run(_do_unload())
        return True
    except Exception as exc:
        logger.debug("Skill unregister '%s': %s", name, exc)
        return False


# ── Main Installer Class ───────────────────────────────────────────────────────

class GitHubInstaller:
    """Singleton installer for GitHub-sourced MCP tools and Skills.

    Usage::

        from core.github_installer import github_installer
        result = await github_installer.install("https://github.com/owner/repo")
    """

    _instance: Optional[GitHubInstaller] = None

    def __init__(self) -> None:
        self._install_dir = _get_install_dir()
        self._manifest = _ManifestStore(self._install_dir)
        logger.debug("GitHubInstaller initialised, install_dir=%s", self._install_dir)

    @classmethod
    def get_instance(cls) -> "GitHubInstaller":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public API ────────────────────────────────────────────────────────

    async def install(
        self,
        url: str,
        ref: Optional[str] = None,
        addon_type: Optional[str] = None,  # "mcp" | "skill" | None (auto-detect)
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Install a GitHub repo as an MCP tool or Skill.

        Args:
            url: GitHub HTTPS URL (with optional /tree/<ref>).
            ref: Override branch/tag/commit (takes precedence over URL).
            addon_type: Force type ("mcp" | "skill"). Auto-detected otherwise.
            dry_run: Validate and preview without actually installing.

        Returns:
            ``{"success": bool, "name": str, "type": str, ...}``
        """
        # 1. Validate URL
        validation = validate_repo_url(url)
        if not validation["valid"]:
            return {"success": False, "error": validation["error"]}

        owner = validation["owner"]
        repo = validation["repo"]
        effective_ref = ref or validation["ref"]

        logger.info(
            "install | owner=%s repo=%s ref=%s dry_run=%s",
            owner, repo, effective_ref, dry_run,
        )

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "owner": owner,
                "repo": repo,
                "ref": effective_ref,
                "message": "Dry-run: URL is valid and would be installed.",
            }

        # 2. Prepare destination directory
        safe_ref = re.sub(r"[^A-Za-z0-9._-]", "_", effective_ref)
        dest = self._install_dir / owner / repo / safe_ref
        dest.mkdir(parents=True, exist_ok=True)

        # 3. Fetch repo
        commit_sha = _fetch_repo(owner, repo, effective_ref, dest)
        if not commit_sha:
            # Non-fatal: download may succeed without a resolvable SHA
            commit_sha = "unknown"
            logger.warning(
                "Could not resolve commit SHA for %s/%s@%s",
                owner, repo, effective_ref,
            )

        # 4. Detect addon type
        mcp_manifest_path = dest / _MCP_TOOL_MANIFEST
        skill_manifest_path = dest / _SKILL_MANIFEST

        if addon_type == "mcp" or (addon_type is None and mcp_manifest_path.exists()):
            detected_type = "mcp"
        elif addon_type == "skill" or (addon_type is None and skill_manifest_path.exists()):
            detected_type = "skill"
        else:
            # Check if there's a requirements.txt / setup.py for skill guess
            detected_type = "skill" if (dest / "requirements.txt").exists() else "unknown"

        # 5. Read manifest
        tool_manifest: Dict[str, Any] = {}
        if detected_type == "mcp" and mcp_manifest_path.exists():
            tool_manifest = json.loads(mcp_manifest_path.read_text(encoding="utf-8"))
        elif detected_type == "skill" and skill_manifest_path.exists():
            tool_manifest = json.loads(skill_manifest_path.read_text(encoding="utf-8"))

        # 5a. Early contract validation for MCP addons — reject before installing deps
        if detected_type == "mcp" and tool_manifest:
            try:
                from core.mcp_addon_contract import validate_mcp_addon_contract, MCPAddonContractError
                validate_mcp_addon_contract(tool_manifest)
            except Exception as contract_exc:
                violations = getattr(contract_exc, "violations", [str(contract_exc)])
                logger.warning(
                    "MCP addon contract validation failed for %s/%s: %s",
                    owner, repo, violations,
                )
                return {
                    "success": False,
                    "error": f"mcp_tool.json contract validation failed: {contract_exc}",
                    "violations": violations,
                    "owner": owner,
                    "repo": repo,
                    "ref": effective_ref,
                }

        addon_name = tool_manifest.get("name") or repo

        # 6. Install dependencies
        deps = tool_manifest.get("dependencies", [])
        if deps:
            _install_deps(dest, deps)

        # 7. Register
        if detected_type == "mcp":
            reg_result = _register_mcp_tool(dest, tool_manifest)
        elif detected_type == "skill":
            reg_result = _register_skill(dest, tool_manifest)
        else:
            reg_result = {
                "success": True,
                "warning": (
                    "Neither mcp_tool.json nor skill.json found. "
                    "Repo downloaded but not registered. "
                    "You may register it manually."
                ),
            }

        # 8. Compute checksum
        checksum = _sha256_dir(dest)

        # 9. Record in manifest
        record: Dict[str, Any] = {
            "name": addon_name,
            "type": detected_type,
            "owner": owner,
            "repo": repo,
            "ref": effective_ref,
            "commit": commit_sha,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "install_path": str(dest),
            "checksum": checksum,
            "tool_manifest": tool_manifest,
        }
        self._manifest.put(addon_name, record)

        logger.info(
            "install done | name=%s type=%s commit=%.8s checksum=%.8s",
            addon_name, detected_type, commit_sha, checksum,
        )

        return {
            "success": reg_result.get("success", True),
            "name": addon_name,
            "type": detected_type,
            "owner": owner,
            "repo": repo,
            "ref": effective_ref,
            "commit": commit_sha,
            "install_path": str(dest),
            "checksum": checksum,
            "registration": reg_result,
        }

    async def uninstall(self, name: str) -> Dict[str, Any]:
        """Uninstall an addon by name.

        Returns:
            ``{"success": bool, "name": str, ...}``
        """
        record = self._manifest.get(name)
        if not record:
            return {"success": False, "error": f"Addon '{name}' not found in manifest."}

        addon_type = record.get("type", "unknown")

        # Unregister
        if addon_type == "mcp":
            _unregister_mcp_tool(name)
        elif addon_type == "skill":
            _unregister_skill(name)

        # Remove files
        install_path = record.get("install_path", "")
        if install_path and Path(install_path).exists():
            try:
                shutil.rmtree(install_path)
            except Exception as exc:
                logger.warning("Could not remove %s: %s", install_path, exc)

        # Remove from manifest
        self._manifest.remove(name)

        logger.info("uninstall done | name=%s type=%s", name, addon_type)
        return {"success": True, "name": name, "type": addon_type}

    def list_installed(self) -> Dict[str, Any]:
        """Return all installed addons from the manifest.

        Returns:
            ``{"success": True, "addons": [...]}``
        """
        addons = self._manifest.get_all()
        return {
            "success": True,
            "count": len(addons),
            "addons": list(addons.values()),
        }

    def get_status(self) -> Dict[str, Any]:
        """Return installer status (token configured, install dir, counts).

        Returns:
            ``{"success": True, "token_configured": bool, "install_dir": str, ...}``
        """
        addons = self._manifest.get_all()
        mcp_count = sum(1 for a in addons.values() if a.get("type") == "mcp")
        skill_count = sum(1 for a in addons.values() if a.get("type") == "skill")
        return {
            "success": True,
            "token_configured": bool(_get_token()),
            "install_dir": str(_get_install_dir()),
            "allowlist": _get_allowlist(),
            "blocklist": _get_blocklist(),
            "total_installed": len(addons),
            "mcp_tools": mcp_count,
            "skills": skill_count,
        }

    async def install_dry_run(self, url: str, ref: Optional[str] = None) -> Dict[str, Any]:
        """Validate a URL for installation without actually installing."""
        return await self.install(url, ref=ref, dry_run=True)


# ── Singleton (installer) ──────────────────────────────────────────────────────

github_installer = GitHubInstaller.get_instance()


def get_github_installer() -> GitHubInstaller:
    """Return the module-level installer singleton."""
    return github_installer


# ── GitHub API helpers for ingestion ──────────────────────────────────────────

# Candidate files fetched during repo ingestion (in priority order)
_INGEST_CANDIDATES: List[str] = [
    "README.md",
    "README.rst",
    "README.txt",
    "README",
    "docs/index.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "mcp_tool.json",
    "skill.json",
    "package.json",
    "pyproject.toml",
    "setup.cfg",
]

# File extensions considered "code" for include_code=True ingestion
_CODE_EXTENSIONS: List[str] = [".py", ".ts", ".js", ".go", ".rs", ".java"]


def _fetch_file_content_api(
    owner: str, repo: str, path: str, ref: str = "HEAD"
) -> Optional[str]:
    """Fetch a single file's decoded text content via the GitHub contents API.

    Returns the UTF-8 decoded file content, or ``None`` if the request
    fails or the file is not found.
    """
    import base64

    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    if ref and ref != "HEAD":
        url += f"?ref={ref}"
    try:
        status, body = _http_get(url, _build_gh_headers())
        if status != 200:
            return None
        data = json.loads(body)
        # GitHub returns base64-encoded content with newlines
        encoded = data.get("content", "")
        if not encoded:
            return None
        return base64.b64decode(encoded.replace("\n", "")).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("_fetch_file_content_api %s/%s/%s failed: %s", owner, repo, path, exc)
        return None


def _fetch_repo_metadata_api(owner: str, repo: str) -> Dict[str, Any]:
    """Fetch repository metadata from the GitHub repos API.

    Returns a dict with ``description``, ``topics``, ``language``,
    ``default_branch``, ``stargazers_count``, and ``html_url`` keys.
    Returns an empty dict on failure.
    """
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}"
    try:
        status, body = _http_get(url, _build_gh_headers())
        if status != 200:
            return {}
        data = json.loads(body)
        return {
            "description": data.get("description") or "",
            "topics": data.get("topics") or [],
            "language": data.get("language") or "",
            "default_branch": data.get("default_branch") or "main",
            "stargazers_count": data.get("stargazers_count", 0),
            "html_url": data.get("html_url") or f"https://github.com/{owner}/{repo}",
        }
    except Exception as exc:
        logger.debug("_fetch_repo_metadata_api %s/%s failed: %s", owner, repo, exc)
        return {}


# ── Knowledge Resource: GitHubRepoIngester ────────────────────────────────────

class GitHubRepoIngester:
    """GitHub repository knowledge and engineering context resource.

    This class elevates GitHub from an addon installer path to a first-class
    system resource with two additional roles:

    * **Knowledge source** — ingest README/docs/manifests from GitHub
      repositories into the unified Knowledge Core via
      ``RAGMemory.ingest_knowledge()``.  Source attribution is always
      ``github://{owner}/{repo}`` so consumers can identify GitHub-origin
      knowledge.

    * **Engineering context source** — retrieve structured repo context
      (README, description, topics, manifests) for use by planning, coding,
      and debugging flows.

    Addon installation remains the responsibility of :class:`GitHubInstaller`.
    This class does **not** duplicate that path.

    Usage::

        from core.github_installer import get_github_ingester
        result = await ingester.ingest_repo("https://github.com/owner/repo")
        ctx    = ingester.get_repo_context("https://github.com/owner/repo")
    """

    _instance: Optional["GitHubRepoIngester"] = None

    def __init__(self) -> None:
        logger.debug("GitHubRepoIngester initialised")

    @classmethod
    def get_instance(cls) -> "GitHubRepoIngester":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Public API ─────────────────────────────────────────────────────────

    async def ingest_repo(
        self,
        url: str,
        ref: Optional[str] = None,
        include_code: bool = False,
    ) -> Dict[str, Any]:
        """Ingest a GitHub repository into the unified Knowledge Core.

        Fetches README, key docs, and manifest files from the repository
        and writes each piece of content into the unified Knowledge Core
        via ``RAGMemory.ingest_knowledge()``.  Source attribution is set
        to ``github://{owner}/{repo}`` on every ingested chunk so that
        downstream consumers can identify GitHub-origin knowledge.

        Does **not** install the repository as an addon; that path belongs
        to :class:`GitHubInstaller`.

        Args:
            url:          GitHub HTTPS repository URL.
            ref:          Branch, tag, or commit SHA (optional).
            include_code: If ``True``, also ingest ``*.py``/``*.ts`` etc.
                          source files found in the repo root.  Default is
                          ``False`` because code files can be very large.

        Returns:
            ``{"success": bool, "owner": str, "repo": str, "ref": str,
               "ingested_count": int, "entry_ids": [...], "source": str}``
        """
        # 1. Validate URL
        validation = validate_repo_url(url)
        if not validation["valid"]:
            return {"success": False, "error": validation["error"]}

        owner = validation["owner"]
        repo = validation["repo"]
        effective_ref = ref or validation["ref"]
        source_label = f"github://{owner}/{repo}"

        # 2. Fetch repo metadata for enriched context
        meta = _fetch_repo_metadata_api(owner, repo)

        entry_ids: List[str] = []
        ingested_files: List[str] = []

        # 3. Build the list of files to fetch
        candidates = list(_INGEST_CANDIDATES)
        if include_code:
            # Add code files from root listing (best-effort via API)
            try:
                root_url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/contents/"
                status, body = _http_get(root_url, _build_gh_headers())
                if status == 200:
                    items = json.loads(body)
                    for item in items:
                        if item.get("type") == "file":
                            name = item.get("name", "")
                            if any(name.endswith(ext) for ext in _CODE_EXTENSIONS):
                                if name not in candidates:
                                    candidates.append(name)
            except Exception as exc:
                logger.debug("ingest_repo root listing failed: %s", exc)

        # 4. Fetch and ingest each candidate file
        try:
            from core.rag_memory import RAGMemory
            rag = RAGMemory()
        except Exception as exc:
            logger.warning("ingest_repo: RAGMemory unavailable: %s", exc)
            rag = None

        for path in candidates:
            content = _fetch_file_content_api(owner, repo, path, effective_ref)
            if not content:
                continue
            # Truncate very large files to avoid overwhelming the knowledge store
            if len(content) > _MAX_INGEST_FILE_SIZE:
                content = content[:_MAX_INGEST_FILE_SIZE] + "\n...[truncated]"

            tags = ["github", f"github_repo:{owner}/{repo}", f"file:{path}"]
            if meta.get("topics"):
                tags += [f"topic:{t}" for t in meta["topics"][:5]]

            chunk_text = (
                f"# GitHub Repository: {owner}/{repo}\n"
                f"File: {path}\n"
                f"Source: {source_label}\n\n"
                f"{content}"
            )
            metadata = {
                "owner": owner,
                "repo": repo,
                "ref": effective_ref,
                "file": path,
                "html_url": f"https://github.com/{owner}/{repo}/blob/{effective_ref}/{path}",
                "description": meta.get("description", ""),
                "language": meta.get("language", ""),
            }

            if rag is not None:
                try:
                    entry_id = rag.ingest_knowledge(
                        content=chunk_text,
                        source=source_label,
                        source_type="github_repo",
                        tags=tags,
                        metadata=metadata,
                    )
                    entry_ids.append(entry_id)
                    ingested_files.append(path)
                except Exception as exc:
                    logger.warning(
                        "ingest_repo: failed to ingest %s/%s/%s: %s",
                        owner, repo, path, exc,
                    )
            else:
                ingested_files.append(path)

        logger.info(
            "ingest_repo done | %s/%s ref=%s files=%d",
            owner, repo, effective_ref, len(ingested_files),
        )
        return {
            "success": True,
            "owner": owner,
            "repo": repo,
            "ref": effective_ref,
            "source": source_label,
            "source_type": "github_repo",
            "ingested_count": len(ingested_files),
            "ingested_files": ingested_files,
            "entry_ids": entry_ids,
            "description": meta.get("description", ""),
            "language": meta.get("language", ""),
            "topics": meta.get("topics", []),
        }

    def get_repo_context(
        self,
        url: str,
        ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract structured engineering context from a GitHub repository.

        Fetches the README and key manifest files via the GitHub API and
        returns them as a structured context dict that can be injected into
        planning, coding, or debugging flows.  No content is persisted to
        the Knowledge Core; for persistent ingestion use :meth:`ingest_repo`.

        Args:
            url: GitHub HTTPS repository URL.
            ref: Branch, tag, or commit SHA (optional).

        Returns:
            ``{"success": bool, "owner": str, "repo": str, "ref": str,
               "source": str, "source_type": str, "context": {...}}``

            The ``context`` dict contains:
            * ``readme``       — README text (first 4 KB) or empty string.
            * ``description``  — repository description from GitHub.
            * ``language``     — primary language.
            * ``topics``       — list of repository topic strings.
            * ``default_branch`` — default branch name.
            * ``manifests``    — dict of {filename: parsed_json_or_text} for
                                 ``mcp_tool.json``, ``skill.json``,
                                 ``package.json``, ``pyproject.toml``.
            * ``html_url``     — canonical GitHub URL for the repo.
        """
        # 1. Validate URL
        validation = validate_repo_url(url)
        if not validation["valid"]:
            return {"success": False, "error": validation["error"]}

        owner = validation["owner"]
        repo = validation["repo"]
        effective_ref = ref or validation["ref"]
        source_label = f"github://{owner}/{repo}"

        # 2. Repo metadata
        meta = _fetch_repo_metadata_api(owner, repo)

        # 3. README
        readme_content = ""
        for readme_path in ("README.md", "README.rst", "README.txt", "README"):
            text = _fetch_file_content_api(owner, repo, readme_path, effective_ref)
            if text:
                readme_content = text[:_MAX_CONTEXT_README_SIZE]
                break

        # 4. Manifests
        manifests: Dict[str, Any] = {}
        for mfile in ("mcp_tool.json", "skill.json", "package.json"):
            text = _fetch_file_content_api(owner, repo, mfile, effective_ref)
            if text:
                try:
                    manifests[mfile] = json.loads(text)
                except Exception:
                    manifests[mfile] = text
        for mfile in ("pyproject.toml", "setup.cfg"):
            text = _fetch_file_content_api(owner, repo, mfile, effective_ref)
            if text:
                manifests[mfile] = text[:_MAX_MANIFEST_SIZE]

        context: Dict[str, Any] = {
            "readme": readme_content,
            "description": meta.get("description", ""),
            "language": meta.get("language", ""),
            "topics": meta.get("topics", []),
            "default_branch": meta.get("default_branch", "main"),
            "manifests": manifests,
            "html_url": meta.get("html_url", f"https://github.com/{owner}/{repo}"),
        }

        logger.info(
            "get_repo_context done | %s/%s ref=%s manifests=%d readme_len=%d",
            owner, repo, effective_ref, len(manifests), len(readme_content),
        )
        return {
            "success": True,
            "owner": owner,
            "repo": repo,
            "ref": effective_ref,
            "source": source_label,
            "source_type": "github_repo",
            "context": context,
        }


# ── Singleton (ingester) ───────────────────────────────────────────────────────

github_ingester = GitHubRepoIngester.get_instance()


def get_github_ingester() -> GitHubRepoIngester:
    """Return the module-level ingester singleton."""
    return github_ingester
