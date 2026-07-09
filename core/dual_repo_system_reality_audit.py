"""
core/dual_repo_system_reality_audit.py — backward-compatibility stub.

This module has been relocated to ``core.audit_layer`` to keep the runtime
core namespace free of narrative audit artifacts.  All public symbols remain
importable from this path for backward compatibility.
"""
# noqa: F401,F403
from core.audit_layer.dual_repo_system_reality_audit import *  # noqa: F401,F403
# `import *` 不会把源模块的 __all__ 也带到本 shim 上;显式再导出,让
# `core.dual_repo_system_reality_audit.__all__` 与源模块一致(公开 API 声明)。
from core.audit_layer.dual_repo_system_reality_audit import __all__  # noqa: F401
