# windows_client/status_board.py — LEGACY STATUS BOARD (retired PR-2)
#
# .. deprecated:: PR-8 / PR-2  LEGACY STATUS BOARD
#    This module is a **legacy status board** superseded by
#    ``windows_client/status_board_v2/`` (PR-8) and **retired** (hard-disabled)
#    in PR-2.
#
#    It previously polled ``/api/v1/continuum/state`` (ad-hoc, non-projection).
#    The canonical replacement, ``status_board_v2/``, consumes the official
#    projection contract from::
#
#        GET /api/v1/projection/runtime
#        contract: contracts.desktop_status_projection.DesktopStatusProjection
#
# The canonical desktop status surface is:
#   python -m windows_client.status_board_v2
#
# See docs/WINDOWS_STATUS_BOARD.md for current launch instructions.

import warnings

warnings.warn(
    "windows_client/status_board.py is a LEGACY STATUS BOARD and has been "
    "retired (PR-2).  Use the canonical desktop status surface instead:\n"
    "  python -m windows_client.status_board_v2\n"
    "See docs/WINDOWS_STATUS_BOARD.md.",
    DeprecationWarning,
    stacklevel=1,
)

raise RuntimeError(
    "windows_client/status_board.py is retired (PR-2).  "
    "This legacy status board polled /api/v1/continuum/state "
    "(ad-hoc, non-projection endpoint).  "
    "The canonical replacement is status_board_v2 which consumes "
    "the RuntimeProjection contract:\n"
    "  python -m windows_client.status_board_v2\n"
    "See docs/WINDOWS_STATUS_BOARD.md."
)
