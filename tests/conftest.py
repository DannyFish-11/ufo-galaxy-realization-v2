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
