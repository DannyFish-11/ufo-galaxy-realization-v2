"""持久化状态一律随数据总目录(``GALAXY_DATA_DIR``)走 —— 不许把仓库根 ``data/`` 写死在模块里。

全面排查真跑:设了独立数据目录,启动日志里「Session truth 快照存储已挂载: path=<仓库>/data/
session_truth_snapshot.json restored=200」—— 从仓库里读回了别处留下的 200 条会话真相。同样写死的还有
会话(``sessions.json`` 与证据链目录)、生成的 MCP 工具目录。AGENTS.md:「**所有**持久化状态都认它」。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: ``os.path.join(<仓库根>, "data", …)`` 这个写法 —— 根由 ``__file__`` 往上推出来。
_HARDCODED = re.compile(r"abspath\(__file__\)\)+,\s*\n?\s*\"data\",", re.M)

#: 刻意保留的:只是兜底重导出,真正用的那份(core.durable_result_idempotency)认数据目录。
_ALLOWED = {"core/unified/idempotency.py"}


def test_no_module_hardcodes_the_repo_data_directory():
    offenders = []
    for path in (ROOT / "core").rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel in _ALLOWED:
            continue
        src = path.read_text(encoding="utf-8", errors="ignore")
        for m in _HARDCODED.finditer(src):
            line = src.count("\n", 0, m.start()) + 1
            window = src[max(0, m.start() - 400) : m.end() + 200]
            if "data_path_or_legacy" in window:  # 仓库 data/ 只当「旧位置」兜底
                continue
            offenders.append(f"{rel}:{line}")
    assert not offenders, "写死了仓库 data/(用 core.data_paths.data_path / data_path_or_legacy):" + ", ".join(offenders)


def test_the_session_truth_snapshot_lands_in_the_data_dir(tmp_path, monkeypatch):
    import core.session_truth_snapshot as sts

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sts, "_DEFAULT_SESSION_TRUTH_SNAPSHOT_PATH", str(tmp_path / "nowhere" / "legacy.json"))
    store = sts.SessionTruthSnapshotStore()
    assert Path(store._store_path) == tmp_path / "session_truth_snapshot.json"


#: 原先写死在仓库 ``runtime/`` 下的状态 —— 容器里只有 ``/app/data`` 在持久卷上,重建一次就丢。
_RUNTIME_STATE = {
    "core.user_providers": "STORE_FILE",
    "core.oauth_connectors": "_STORE",
    "core.model_catalog": "_STATE_FILE",
    "core.speculative_draft": "_STATE_FILE",
    "core.context_measurements": "_FILE",
    "core.context_archive": "_ROOT",
    "core.agent_supply": "DIVERGENCE_LOG",
    "core.meta.store": "DEFAULT_STORE_ROOT",
}


def test_machine_state_that_used_to_live_in_runtime_follows_the_data_dir():
    """测试会话里数据目录是 conftest 的临时目录,仓库自己的旧位置不算 —— 这些路径都该落进去。"""
    import importlib
    import os

    data_dir = Path(os.environ["GALAXY_DATA_DIR"]).resolve()
    stray = {}
    for module, attr in _RUNTIME_STATE.items():
        where = Path(getattr(importlib.import_module(module), attr)).resolve()
        if not where.is_relative_to(data_dir):
            stray[f"{module}.{attr}"] = str(where)
    assert not stray, f"这些状态没跟数据目录走: {stray}"


def test_select_model_clears_the_same_record_the_catalog_reads():
    """``--select-model`` 清的那份记录,得是 model_catalog 真正读写的那份(原先 main.py 自己拼了 runtime/ 路径)。"""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"runtime" / "model_state.json"' not in src
    assert "from core.model_catalog import _STATE_FILE" in src
