"""
Galaxy - Test Configuration
================================

Shared fixtures and configuration for all tests.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Set test environment variables
os.environ.setdefault("GALAXY_MODE", "test")
os.environ.setdefault("GALAXY_DEV_MODE", "1")
os.environ.setdefault("PYTHONPATH", str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def nodes_dir():
    """Return the nodes directory."""
    return PROJECT_ROOT / "nodes"


@pytest.fixture
def config_dir():
    """Return the config directory."""
    return PROJECT_ROOT / "config"


# PR-18: Reset the recovery-readiness guard runtime before every test so that
# tests using the global singleton (ingest_delegated_execution_signal without
# guard_runtime) always start with a clean ring buffer.  Tests that need
# cross-call guard state (i.e. the PR-18 integration tests) use an explicit
# RecoveryReadinessRuntime() instance via the guard_runtime parameter and are
# unaffected by this reset.
@pytest.fixture(autouse=True)
def _reset_recovery_guard_runtime():
    """Auto-use: reset the global recovery-readiness runtime before each test."""
    try:
        from core.attached_runtime_recovery_readiness import (
            reset_recovery_readiness_runtime,
        )
        reset_recovery_readiness_runtime()
    except ImportError:
        pass
    yield


# PR-19: Reset the attached runtime session registry before every test so that
# tests using the global singleton always start with a clean registry.  Tests
# that need cross-call registry state use an explicit AttachedSessionRegistry()
# instance via the registry parameter and are unaffected by this reset.
@pytest.fixture(autouse=True)
def _reset_session_registry():
    """Auto-use: reset the global attached runtime session registry before each test."""
    try:
        from core.attached_runtime_session_registry import reset_session_registry

        reset_session_registry()
    except ImportError:
        pass
    yield
