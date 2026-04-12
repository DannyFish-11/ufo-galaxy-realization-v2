from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_clone_to_use_reality_doc_exists_and_covers_core_questions() -> None:
    content = _read("docs/CLONE_TO_USE_REALITY.md")
    assert "python main.py" in content
    assert "python -m windows_client.status_board_v2" in content
    assert "/api/v1/chat" in content
    assert "/api/v1/projection/runtime" in content
    assert "cross-device" in content.lower()
    assert "read-only" in content.lower()
    assert "partial operator surface" in content.lower()
    assert "DESKTOP_STATUS_BOARD_READINESS_AUDIT.md" in content


def test_windows_status_board_doc_matches_v2_runtime_path() -> None:
    content = _read("docs/WINDOWS_STATUS_BOARD.md")
    assert "python -m windows_client.status_board_v2" in content
    assert "/api/v1/projection/runtime" in content
    assert "read-only" in content.lower()
    assert "partial operator surface" in content.lower()
    assert "--apply-toggle" in content
    assert "--apply-routing-policy" in content


def test_desktop_status_board_readiness_audit_doc_exists_with_verdict() -> None:
    content = _read("docs/DESKTOP_STATUS_BOARD_READINESS_AUDIT.md")
    assert "not yet" in content.lower()
    assert "partial operator surface" in content.lower()
    assert "presentable control plane" in content.lower()
    assert "readiness checklist" in content.lower()


def test_status_board_v2_default_port_aligned_with_main_runtime() -> None:
    app_content = _read("windows_client/status_board_v2/app.py")
    reader_content = _read("windows_client/status_board_v2/projection_reader.py")
    assert "default=8299" in app_content
    assert "http://127.0.0.1:8299" in reader_content


def test_top_level_docs_link_readiness_audit() -> None:
    readme = _read("README.md")
    quickstart = _read("QUICKSTART.md")
    l4_quickstart = _read("L4_QUICK_START_GUIDE.md")
    marker = "docs/DESKTOP_STATUS_BOARD_READINESS_AUDIT.md"
    assert marker in readme
    assert marker in quickstart
    assert marker in l4_quickstart
