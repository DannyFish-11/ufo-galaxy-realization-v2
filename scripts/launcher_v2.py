#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/launcher_v2.py — legacy V2 launcher shim (compat surface)
=================================================================

This launcher is retained only for backwards compatibility with older
deployment scripts. It is NOT a startup authority.

- **Canonical startup authority**: ``main.py``
- **Canonical subordinate launcher**: ``unified_launcher.py``

Invoking this script simply delegates to ``python main.py`` so that the
single-main-entrypoint contract (PR-01, see ``entrypoint_role_contract.py``)
is preserved.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    print(
        "scripts/launcher_v2.py is a legacy compatibility shim.\n"
        "Authoritative startup path: python main.py\n"
        "Direct advanced invocation: python unified_launcher.py\n"
        "Delegating to main.py ...",
        file=sys.stderr,
    )
    return subprocess.call(
        [sys.executable, str(PROJECT_ROOT / "main.py"), *sys.argv[1:]]
    )


if __name__ == "__main__":
    sys.exit(main())
