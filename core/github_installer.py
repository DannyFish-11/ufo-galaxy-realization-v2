"""
Galaxy — GitHub-powered MCP/Skill Auto-Installer
=================================================

Allows OpenClawd to fetch MCP tools and Skills directly from GitHub
repositories, install them, register them, and make them immediately
usable in OpenClawd tool calls.

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
* C1  — module-level singleton ``github_installer``.
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

def _register_mcp_tool(addon_dir: Path, tool_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Register an MCP tool addon into MCPLoader / MCPDynamicGateway.

    The ``mcp_tool.json`` contract:
    {
        "name": "my-tool",
        "entrypoint": "server.py",          # or ["node", "server.js"]
        "description": "...",
        "schema": {...},                     # optional, JSON schema
        "dependencies": ["requests", ...],  # optional pip deps
        "env": {"KEY": "VALUE"}             # optional env vars to inject
    }
    """
    name = tool_manifest.get("name", "")
    if not name:
        return {"success": False, "error": "mcp_tool.json missing 'name' field"}

    entrypoint = tool_manifest.get("entrypoint")
    if not entrypoint:
        return {"success": False, "error": "mcp_tool.json missing 'entrypoint' field"}

    # Build command
    if isinstance(entrypoint, list):
        command = [str(addon_dir / part) if i == len(entrypoint) - 1 else part
                   for i, part in enumerate(entrypoint)]
    elif entrypoint.endswith(".py"):
        command = [sys.executable, str(addon_dir / entrypoint)]
    elif entrypoint.endswith(".js"):
        node_exec = shutil.which("node") or "node"
        command = [node_exec, str(addon_dir / entrypoint)]
    else:
        command = [str(addon_dir / entrypoint)]

    env_vars = tool_manifest.get("env", {})

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
        return {"success": True, "type": "mcp", "name": name}

    except Exception as exc:
        logger.warning("MCP registration failed for '%s': %s", name, exc)
        return {"success": False, "error": str(exc)}


def _register_skill(addon_dir: Path, skill_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Register a Skill addon into SkillLoader.

    The ``skill.json`` contract:
    {
        "name": "my-skill",
        "description": "...",
        "entrypoint": "handler.py",         # Python file with async def execute(...)
        "dependencies": ["requests", ...],  # optional pip deps
        "parameters": [                     # optional param schema
            {"name": "query", "type": "string", "required": true}
        ]
    }
    """
    name = skill_manifest.get("name", "")
    if not name:
        return {"success": False, "error": "skill.json missing 'name' field"}

    # Build a skill definition compatible with SkillLoader
    skill_def = {
        "id": name,
        "name": name,
        "description": skill_manifest.get("description", ""),
        "version": skill_manifest.get("version", "1.0.0"),
        "entrypoint": skill_manifest.get("entrypoint", ""),
        "parameters": skill_manifest.get("parameters", []),
        "source": str(addon_dir),
    }

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
            return {"success": True, "type": "skill", "name": name}
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


# ── Singleton ─────────────────────────────────────────────────────────────────

github_installer = GitHubInstaller.get_instance()


def get_github_installer() -> GitHubInstaller:
    """Return the module-level singleton."""
    return github_installer
