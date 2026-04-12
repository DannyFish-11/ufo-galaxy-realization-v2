from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_audit_doc_has_required_sections() -> None:
    content = _read("docs/CROSS_DEVICE_RUNTIME_AUDIT.md")

    assert "## A) Cross-device / multi-device runtime reality" in content
    assert "## B) Dispatch / routing / execution authority audit" in content
    assert "## C) Agent/runtime stack audit" in content
    assert "## D) End-to-end completeness assessment" in content
    assert "## E) Desktop status board as operator interface" in content


def test_audit_doc_has_matrix_and_checklist() -> None:
    content = _read("docs/CROSS_DEVICE_RUNTIME_AUDIT.md")

    assert "## Completeness matrix" in content
    assert (
        "| Subsystem | Current state | Classification | Evidence anchor |"
        in content
    )
    assert "## Future-readiness checklist" in content
    assert "- [ ]" in content


def test_audit_doc_states_status_board_readiness() -> None:
    content = _read("docs/CROSS_DEVICE_RUNTIME_AUDIT.md").lower()

    assert "not yet suitable" in content or "not suitable" in content
    assert "status board" in content
    assert "bounded/local" in content
