"""
core/audit_layer — Narrative audit, review, and reassessment modules.

This sub-package contains pure inspection and narrative-audit modules that
are NOT part of the V2 runtime production path.  They are kept here rather
than in the runtime namespace (``core/``) so that the runtime core is more
clearly runtime-focused.

All public symbols are re-exported from their original ``core.*`` stub
modules for full backward compatibility with existing callers and tests.

Modules in this package
-----------------------
These modules perform architectural analysis, code audits, and system
review.  They produce structured reports but do not alter system state.

Backward compatibility
----------------------
All original ``core.X`` import paths continue to work via stub modules
that simply re-export from ``core.audit_layer.X``.
"""
