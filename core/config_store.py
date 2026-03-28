"""
core/config_store.py — Galaxy Unified Local Configuration Store  (PR-3)
========================================================================

Low-level I/O layer for the two canonical local persistence targets:

- ``runtime/config.json``  — non-secret system configuration
- ``runtime/secrets.env``  — secret values (API keys, tokens)

Public API
----------
ConfigStore
    The main store class.  Construct via ``get_config_store()`` for the
    global singleton or instantiate directly for testing.

get_config_store() -> ConfigStore
    Return (and lazily create) the process-level singleton.

reset_config_store()
    Reset the singleton (primarily for tests).

Design notes
------------
- Secrets (keys matching ``core.config_schema.SECRET_KEYS``) must never be
  written into ``runtime/config.json``.  ``ConfigStore.write_config()``
  enforces this by raising ``SecretInConfigError``.
- Non-secret values must not be written to ``runtime/secrets.env``.
  ``ConfigStore.write_secret()`` enforces this by raising
  ``NonSecretInSecretsError``.
- ``get_effective_config()`` merges all sources with the following priority
  (highest → lowest):
    1. Process environment variables (``os.environ``)
    2. ``runtime/secrets.env`` (secrets)
    3. ``runtime/config.json`` (non-secret config)
  This lets deployment env-vars override the local runtime files while
  still falling back to the persisted files when env-vars are absent.
- All file I/O is protected by a threading lock; the module is safe for
  concurrent use within a single process.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from core.config_schema import (
    CONFIG_SCHEMA_AUTHORITY,
    ConfigDefaults,
    SECRET_KEYS,
    classify_key,
)

logger = logging.getLogger("Galaxy.ConfigStore")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

CONFIG_STORE_AUTHORITY: str = "ConfigStore"

# ---------------------------------------------------------------------------
# Canonical paths (relative to repository root)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "runtime" / "config.json"
_DEFAULT_SECRETS_PATH = _REPO_ROOT / "runtime" / "secrets.env"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class SecretInConfigError(ValueError):
    """Raised when a caller attempts to write a secret key into config.json."""


class NonSecretInSecretsError(ValueError):
    """Raised when a caller attempts to write a non-secret key into secrets.env."""


class ConfigStoreError(RuntimeError):
    """General I/O or validation error from ConfigStore."""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ConfigStore:
    """
    Low-level read/write interface for the local configuration authority.

    Parameters
    ----------
    config_path:
        Path to ``runtime/config.json``.  Defaults to the canonical path.
    secrets_path:
        Path to ``runtime/secrets.env``.  Defaults to the canonical path.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        secrets_path: Optional[Path] = None,
    ) -> None:
        self._config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self._secrets_path = Path(secrets_path) if secrets_path else _DEFAULT_SECRETS_PATH
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_dotenv(text: str) -> Dict[str, str]:
        """Parse a .env-style file into a dict.  Ignores comments and blanks."""
        result: Dict[str, str] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Strip surrounding quotes (single or double)
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            if key:
                result[key] = val
        return result

    @staticmethod
    def _render_dotenv(data: Dict[str, str], header: str = "") -> str:
        """Serialise *data* as a .env file, prepending an optional header."""
        lines = []
        if header:
            for h_line in header.splitlines():
                lines.append(f"# {h_line}" if not h_line.startswith("#") else h_line)
            lines.append("")
        for key in sorted(data):
            lines.append(f"{key}={data[key]}")
        lines.append("")  # trailing newline
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def read_config(self) -> Dict[str, Any]:
        """
        Read and return ``runtime/config.json`` as a dict.

        Returns an empty dict (not an error) if the file does not exist.
        Falls back to ``ConfigDefaults.as_dict()`` when the file is absent so
        callers always receive a usable structure.
        """
        with self._lock:
            if not self._config_path.exists():
                logger.debug(
                    "runtime/config.json not found; returning defaults. "
                    "Copy runtime/config.example.json to runtime/config.json to customise."
                )
                return ConfigDefaults.as_dict()
            try:
                with open(self._config_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    logger.warning("runtime/config.json is not a JSON object; returning defaults.")
                    return ConfigDefaults.as_dict()
                # Strip any internal comment keys that start with "_"
                return {k: v for k, v in data.items() if not k.startswith("_")}
            except json.JSONDecodeError as exc:
                logger.error("runtime/config.json is malformed JSON: %s", exc)
                return ConfigDefaults.as_dict()
            except OSError as exc:
                logger.error("Cannot read runtime/config.json: %s", exc)
                return {}

    def read_secrets(self) -> Dict[str, str]:
        """
        Read and return ``runtime/secrets.env`` as a dict.

        Returns an empty dict (not an error) if the file does not exist.
        """
        with self._lock:
            if not self._secrets_path.exists():
                logger.debug(
                    "runtime/secrets.env not found. "
                    "Copy runtime/secrets.example.env to runtime/secrets.env to configure."
                )
                return {}
            try:
                with open(self._secrets_path, encoding="utf-8") as fh:
                    return self._parse_dotenv(fh.read())
            except OSError as exc:
                logger.error("Cannot read runtime/secrets.env: %s", exc)
                return {}

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def write_config(self, data: Dict[str, Any]) -> None:
        """
        Write *data* to ``runtime/config.json``.

        Raises
        ------
        SecretInConfigError
            If *data* contains any top-level key whose name is classified as a
            secret (e.g. ``OPENAI_API_KEY``).  Secrets belong in
            ``runtime/secrets.env``, not ``config.json``.
        """
        # Validate: reject secret keys at the top level
        for key in data:
            if classify_key(str(key)) == "secret":
                raise SecretInConfigError(
                    f"Key '{key}' is a secret and must not be stored in "
                    "runtime/config.json.  Use write_secret() instead."
                )
        with self._lock:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(self._config_path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")
                logger.info("runtime/config.json written (%d top-level keys)", len(data))
            except OSError as exc:
                raise ConfigStoreError(f"Cannot write runtime/config.json: {exc}") from exc

    def write_secret(self, key: str, value: str) -> None:
        """
        Write or update a single *key* in ``runtime/secrets.env``.

        Raises
        ------
        NonSecretInSecretsError
            If *key* is not classified as a secret.
        """
        if classify_key(key) not in ("secret", "unknown"):
            # Allow "unknown" keys so new providers don't block writes, but
            # block known non-secret config keys.
            pass  # heuristic is enough; explicit non-secret check below
        if classify_key(key) == "config":
            raise NonSecretInSecretsError(
                f"Key '{key}' is a non-secret config value and must not be "
                "stored in runtime/secrets.env.  Use write_config() instead."
            )
        with self._lock:
            self._secrets_path.parent.mkdir(parents=True, exist_ok=True)
            # Read existing
            existing: Dict[str, str] = {}
            if self._secrets_path.exists():
                try:
                    with open(self._secrets_path, encoding="utf-8") as fh:
                        existing = self._parse_dotenv(fh.read())
                except OSError:
                    pass
            existing[key] = value
            header = (
                "runtime/secrets.env — Galaxy secret configuration.\n"
                "DO NOT commit this file. Managed by core.config_store."
            )
            try:
                with open(self._secrets_path, "w", encoding="utf-8") as fh:
                    fh.write(self._render_dotenv(existing, header=header))
                logger.info("runtime/secrets.env updated (key: %s)", key)
            except OSError as exc:
                raise ConfigStoreError(f"Cannot write runtime/secrets.env: {exc}") from exc

    def write_secrets(self, data: Dict[str, str]) -> None:
        """
        Batch-write *data* to ``runtime/secrets.env``, merging with existing content.

        All keys in *data* must be classified as ``"secret"`` or ``"unknown"``.
        """
        for key in data:
            if classify_key(key) == "config":
                raise NonSecretInSecretsError(
                    f"Key '{key}' is a non-secret config value and must not be "
                    "stored in runtime/secrets.env."
                )
        with self._lock:
            self._secrets_path.parent.mkdir(parents=True, exist_ok=True)
            existing: Dict[str, str] = {}
            if self._secrets_path.exists():
                try:
                    with open(self._secrets_path, encoding="utf-8") as fh:
                        existing = self._parse_dotenv(fh.read())
                except OSError:
                    pass
            existing.update(data)
            header = (
                "runtime/secrets.env — Galaxy secret configuration.\n"
                "DO NOT commit this file. Managed by core.config_store."
            )
            try:
                with open(self._secrets_path, "w", encoding="utf-8") as fh:
                    fh.write(self._render_dotenv(existing, header=header))
                logger.info(
                    "runtime/secrets.env written (%d keys total)", len(existing)
                )
            except OSError as exc:
                raise ConfigStoreError(f"Cannot write runtime/secrets.env: {exc}") from exc

    # ------------------------------------------------------------------
    # Effective merged view
    # ------------------------------------------------------------------

    def get_effective_config(self) -> Dict[str, Any]:
        """
        Return the **effective merged configuration** for downstream consumers.

        Merge priority (highest wins):
          1. ``os.environ``                — process / deployment env vars
          2. ``runtime/secrets.env``       — persisted local secrets
          3. ``runtime/config.json``       — persisted local non-secret config

        The returned dict is a flat/nested mix:
        - The ``runtime/config.json`` structure is returned under its top-level
          keys (``providers``, ``routing``, …).
        - Secrets from ``runtime/secrets.env`` and ``os.environ`` are merged in
          at the top level under their canonical names (e.g. ``OPENAI_API_KEY``).

        Returns
        -------
        dict
            Merged configuration.  No secrets are omitted; callers should
            treat this value as sensitive.
        """
        effective: Dict[str, Any] = {}

        # Layer 1 (lowest priority): runtime/config.json
        config_data = self.read_config()
        effective.update(config_data)

        # Layer 2: runtime/secrets.env
        secrets_data = self.read_secrets()
        effective.update(secrets_data)

        # Layer 3 (highest priority): process env vars — only well-known keys
        # to avoid polluting the view with all process env.
        all_known_secret_keys = set(SECRET_KEYS)
        for key in all_known_secret_keys:
            env_val = os.environ.get(key)
            if env_val:
                effective[key] = env_val

        return effective

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def get_secret(self, key: str) -> Optional[str]:
        """
        Return the value of a secret *key*, consulting env-vars first,
        then ``runtime/secrets.env``.

        Returns ``None`` if the key is absent or empty in all sources.
        """
        # env-var wins
        env_val = os.environ.get(key)
        if env_val:
            return env_val
        # fall back to secrets.env
        secrets = self.read_secrets()
        val = secrets.get(key, "")
        return val if val else None

    def get_config_value(self, *path: str, default: Any = None) -> Any:
        """
        Read a nested value from ``runtime/config.json`` using a dot-path.

        Example::

            store.get_config_value("providers", "openai", "enabled")
        """
        data = self.read_config()
        node: Any = data
        for part in path:
            if not isinstance(node, dict):
                return default
            node = node.get(part, default)
        return node


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_singleton: Optional[ConfigStore] = None
_singleton_lock = threading.Lock()


def get_config_store() -> ConfigStore:
    """Return the process-level ``ConfigStore`` singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ConfigStore()
    return _singleton


def reset_config_store() -> None:
    """Reset the singleton (for tests)."""
    global _singleton
    with _singleton_lock:
        _singleton = None
