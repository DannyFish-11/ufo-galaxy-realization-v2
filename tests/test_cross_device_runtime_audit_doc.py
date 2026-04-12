from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_cross_device_runtime_audit_doc_exists_with_required_sections() -> None:
    content = _read("docs/CROSS_DEVICE_RUNTIME_AUDIT.md")
    assert "## A) Cross-device / multi-device audit" in content
    assert "## B) Dispatch / routing / execution authority audit" in content
    assert "## C) Agent/runtime stack audit" in content
    assert "## D) End-to-end completeness assessment" in content
    assert "## E) Desktop status board readiness as operator-facing interface" in content


def test_cross_device_runtime_audit_contains_matrix_and_readiness_conclusion() -> None:
    content = _read("docs/CROSS_DEVICE_RUNTIME_AUDIT.md")
    assert "## Completeness matrix (truthful classification)" in content
    assert "| Subsystem | Classification | Evidence | Reality |" in content
    assert "Suitable for bounded/local operations only" in content
    assert "not yet at a level where the desktop status board can honestly be presented as the full-system operator interface" in content


def test_cross_device_runtime_audit_contains_future_readiness_checklist() -> None:
    content = _read("docs/CROSS_DEVICE_RUNTIME_AUDIT.md")
    assert "## Future-readiness checklist" in content
    assert "- [ ] Board exposes canonical, authenticated command ingress for task dispatch" in content
    assert "- [ ] Multi-device target selection, authority, confirmation, and rollback semantics are productized and tested with real devices." in content
