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


def test_windows_status_board_doc_matches_v2_runtime_path() -> None:
    content = _read("docs/WINDOWS_STATUS_BOARD.md")
    assert "python -m windows_client.status_board_v2" in content
    assert "/api/v1/projection/runtime" in content
    assert "read-only" in content.lower()


def test_status_board_v2_default_port_aligned_with_main_runtime() -> None:
    app_content = _read("windows_client/status_board_v2/app.py")
    reader_content = _read("windows_client/status_board_v2/projection_reader.py")
    assert "default=8299" in app_content
    assert "http://127.0.0.1:8299" in reader_content
