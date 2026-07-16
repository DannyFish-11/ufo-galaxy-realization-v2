"""
core/agent/policy_loader.py
==============================

Policy loader for the ReAct agent -- responsible for:
- Loading & caching policy files
- Coordinating with JIT policy delivery
- Detecting stale policies at conversation start

This module contains Bug fixes for P11 (ReAct policy loader).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Final, Optional, Set

from core.errors import PolicyLoadError, ReActError

logger = logging.getLogger("Galaxy.Agent.PolicyLoader")

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

# Supported policy file extensions
POLICY_EXTENSIONS: Final = frozenset({".yaml", ".yml", ".json"})

# Policy cache TTL in seconds (5 minutes)
POLICY_CACHE_TTL: Final = 300

# Default policy directory
DEFAULT_POLICY_DIR: Final = Path("policies")

# Maximum recursion depth for policy includes
MAX_INCLUDE_DEPTH: Final = 10

# ──────────────────────────────────────────────────────────────────────────────
# Exception hierarchy
# ──────────────────────────────────────────────────────────────────────────────


class PolicyFileError(ReActError):
    """Raised when a policy file cannot be loaded or parsed."""

    pass


class PolicyCacheError(ReActError):
    """Raised when the policy cache is corrupted or inaccessible."""

    pass


class PolicyIncludeError(ReActError):
    """Raised when a policy include directive fails."""

    pass


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _find_policy_files(
    directory: Path, *, seen: Optional[Set[Path]] = None
) -> list[Path]:
    """Recursively find policy files in *directory*.

    Args:
        directory: Root directory to search.
        seen: Set of already-seen paths (for circular-include detection).

    Returns:
        List of policy file paths.

    Raises:
        PolicyFileError: If *directory* does not exist or is not a directory.
    """
    if seen is None:
        seen = set()

    if not directory.exists():
        raise PolicyFileError(f"Policy directory does not exist: {directory}")
    if not directory.is_dir():
        raise PolicyFileError(f"Policy path is not a directory: {directory}")

    policy_files: list[Path] = []
    for item in sorted(directory.iterdir()):
        if item.is_file() and item.suffix.lower() in POLICY_EXTENSIONS:
            if item.resolve() not in seen:
                seen.add(item.resolve())
                policy_files.append(item)
        elif item.is_dir():
            # Recurse into subdirectories
            policy_files.extend(_find_policy_files(item, seen=seen))

    return policy_files


def _parse_policy_file(path: Path) -> dict[str, Any]:
    """Parse a single policy file (YAML or JSON).

    Args:
        path: Path to the policy file.

    Returns:
        Parsed policy as a dict.

    Raises:
        PolicyFileError: If the file cannot be read or parsed.
    """
    import yaml

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyFileError(f"Cannot read policy file {path}: {exc}") from exc

    try:
        if path.suffix.lower() == ".json":
            import json

            return json.loads(text)
        return yaml.safe_load(text) or {}
    except Exception as exc:
        raise PolicyFileError(f"Cannot parse policy file {path}: {exc}") from exc


# ──────────────────────────────────────────────────────────────────────────────
# Cache management
# ──────────────────────────────────────────────────────────────────────────────

# In-memory cache: policy_id -> (timestamp, policy_dict)
_policy_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _is_cache_valid(policy_id: str) -> bool:
    """Check if a cached policy is still valid.

    Args:
        policy_id: Unique identifier for the policy.

    Returns:
        True if the policy is in cache and not expired.
    """
    if policy_id not in _policy_cache:
        return False
    timestamp, _ = _policy_cache[policy_id]
    return (time.monotonic() - timestamp) < POLICY_CACHE_TTL


def _get_cached_policy(policy_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a policy from cache if valid.

    Args:
        policy_id: Unique identifier for the policy.

    Returns:
        Cached policy dict, or None if not found or expired.
    """
    if _is_cache_valid(policy_id):
        return _policy_cache[policy_id][1]
    return None


def _cache_policy(policy_id: str, policy: dict[str, Any]) -> None:
    """Store a policy in the cache.

    Args:
        policy_id: Unique identifier for the policy.
        policy: Policy dict to cache.
    """
    _policy_cache[policy_id] = (time.monotonic(), policy)


def _invalidate_cache(policy_id: str) -> None:
    """Remove a policy from the cache.

    Args:
        policy_id: Unique identifier for the policy.
    """
    _policy_cache.pop(policy_id, None)


def _clear_cache() -> None:
    """Clear the entire policy cache."""
    _policy_cache.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Staleness detection
# ──────────────────────────────────────────────────────────────────────────────


def is_policy_stale(
    policy_id: str, *, last_loaded_at: Optional[float] = None
) -> bool:
    """Detect if a policy has become stale since it was last loaded.

    A policy is stale if:
    1. It is not in the cache, or
    2. The cache entry has expired, or
    3. The file modification time is newer than *last_loaded_at*.

    Args:
        policy_id: Unique identifier for the policy.
        last_loaded_at: Optional timestamp of when the policy was last loaded.

    Returns:
        True if the policy should be reloaded.
    """
    if not _is_cache_valid(policy_id):
        return True

    if last_loaded_at is not None:
        policy_file = _get_policy_file_path(policy_id)
        if policy_file and policy_file.exists():
            mtime = policy_file.stat().st_mtime
            if mtime > last_loaded_at:
                logger.info(
                    "Policy %s is stale: file modified at %s, last loaded at %s",
                    policy_id,
                    mtime,
                    last_loaded_at,
                )
                return True

    return False


def _get_policy_file_path(policy_id: str) -> Optional[Path]:
    """Resolve a policy ID to a file path.

    Searches the default policy directory and common locations.

    Args:
        policy_id: Policy identifier (may include subpath).

    Returns:
        Path to the policy file, or None if not found.
    """
    # Try direct path first
    direct = Path(policy_id)
    if direct.exists() and direct.suffix.lower() in POLICY_EXTENSIONS:
        return direct

    # Try in default policy directory
    in_dir = DEFAULT_POLICY_DIR / policy_id
    if in_dir.exists():
        return in_dir

    # Try with extensions
    for ext in POLICY_EXTENSIONS:
        candidate = DEFAULT_POLICY_DIR / f"{policy_id}{ext}"
        if candidate.exists():
            return candidate

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────


def load_policy(
    policy_id: str,
    *,
    directory: Optional[Path] = None,
    force_reload: bool = False,
) -> dict[str, Any]:
    """Load a policy by ID, with caching and staleness detection.

    This is the primary entry point for policy loading.

    Args:
        policy_id: Unique identifier for the policy.
        directory: Optional override for the policy directory.
        force_reload: If True, bypass cache and reload from disk.

    Returns:
        The loaded policy as a dict.

    Raises:
        PolicyLoadError: If the policy cannot be found or loaded.
    """
    if not force_reload:
        cached = _get_cached_policy(policy_id)
        if cached is not None:
            logger.debug("Policy %s loaded from cache", policy_id)
            return cached

    search_dir = directory or DEFAULT_POLICY_DIR
    policy_file = _get_policy_file_path(policy_id)

    if policy_file is None:
        # Try to find it in the search directory
        policy_files = _find_policy_files(search_dir)
        for pf in policy_files:
            if pf.stem == policy_id or str(pf) == policy_id:
                policy_file = pf
                break

    if policy_file is None or not policy_file.exists():
        raise PolicyLoadError(f"Policy not found: {policy_id}")

    try:
        policy = _parse_policy_file(policy_file)
    except PolicyFileError as exc:
        raise PolicyLoadError(f"Failed to load policy {policy_id}: {exc}") from exc

    _cache_policy(policy_id, policy)
    logger.info("Policy %s loaded from %s", policy_id, policy_file)
    return policy


def load_all_policies(
    directory: Optional[Path] = None,
) -> dict[str, dict[str, Any]]:
    """Load all policies from a directory.

    Args:
        directory: Directory to search for policies. Defaults to ``policies/``.

    Returns:
        Mapping of policy IDs to policy dicts.
    """
    search_dir = directory or DEFAULT_POLICY_DIR
    policies: dict[str, dict[str, Any]] = {}

    try:
        policy_files = _find_policy_files(search_dir)
    except PolicyFileError:
        return policies

    for pf in policy_files:
        policy_id = pf.stem
        try:
            policies[policy_id] = _parse_policy_file(pf)
            _cache_policy(policy_id, policies[policy_id])
        except PolicyFileError as exc:
            logger.warning("Skipping policy %s: %s", policy_id, exc)

    logger.info("Loaded %d policies from %s", len(policies), search_dir)
    return policies


def reload_policy(policy_id: str) -> dict[str, Any]:
    """Force-reload a policy, clearing its cache entry.

    Args:
        policy_id: Unique identifier for the policy.

    Returns:
        The reloaded policy.

    Raises:
        PolicyLoadError: If the policy cannot be reloaded.
    """
    _invalidate_cache(policy_id)
    return load_policy(policy_id, force_reload=True)


def get_policy_cache_info() -> dict[str, dict[str, Any]]:
    """Return information about the current policy cache.

    Returns:
        Dict mapping policy IDs to cache metadata.
    """
    now = time.monotonic()
    return {
        pid: {
            "age_seconds": now - ts,
            "valid": _is_cache_valid(pid),
            "policy_keys": list(policy.keys()),
        }
        for pid, (ts, policy) in _policy_cache.items()
    }
