"""
仓库写入隔离守卫
================

跑测试不该改写【被 git 跟踪的文件】。这里守两条曾经真实发生过的回归：

  1. ``CapabilityManager`` 每次 ``register_capability()`` 都会把能力表落盘到
     ``config/capabilities.json``。它的默认目录基于 ``__file__`` 计算,是仓库
     绝对路径 —— 换工作目录躲不掉,只能靠 ``GALAXY_CONFIG_DIR`` 引开。

  2. ``KnowledgeBaseSystem`` 默认持久化到 CWD 相对的 ``./knowledge_db``,而测试
     从仓库根启动。``knowledge_db/knowledge_entries.json`` 就是这么被提交进仓库的
     —— 里面躺着的正是 ``test_vector_backend.py`` 写出的 "Python is a programming
     language."。该文件已取消跟踪,这里防止它再被提交回来。

隔离本身在 ``tests/conftest.py`` 模块级完成（必须在模块级：CapabilityManager 是
进程单例,config_dir 在第一次构造时就定死了,等 fixture 跑就晚了）。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()


def _is_inside(path: Path, parent: Path) -> bool:
    """path 是否落在 parent 之内（两边都先解析成绝对真实路径）。"""
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def test_capability_manager_writes_outside_repo():
    """能力表的落盘目标必须在仓库之外。"""
    from core.capability_manager import get_capability_manager

    manager = get_capability_manager()

    assert not _is_inside(manager.config_file, PROJECT_ROOT), (
        f"CapabilityManager 会把能力表写到仓库内的 {manager.config_file}；"
        "跑一次测试就会改写被 git 跟踪的 config/capabilities.json。"
        "应由 conftest 设置 GALAXY_CONFIG_DIR 引到临时目录。"
    )


def test_capability_seed_content_preserved():
    """引开写入的同时,读到的能力表内容必须和仓库里的一致。

    conftest 把真实的 capabilities.json 拷进了临时目录。若漏拷,能力表会从空开始 ——
    测试仍然"绿"，但跑的已经不是生产行为了。这里把那个静默失效钉死。
    """
    from core.capability_manager import get_capability_manager

    manager = get_capability_manager()
    real_file = PROJECT_ROOT / "config" / "capabilities.json"

    if not real_file.is_file():
        pytest.skip("仓库内没有 config/capabilities.json,无从比对")

    assert Path(manager.config_file).is_file(), (
        f"临时配置目录里没有 capabilities.json（{manager.config_file}）——"
        "conftest 的种子拷贝没生效,能力表会从空开始。"
    )

    real_names = {c.get("name") for c in json.loads(real_file.read_text(encoding="utf-8")).get("capabilities", [])}
    seeded = json.loads(Path(manager.config_file).read_text(encoding="utf-8")).get("capabilities", [])
    seeded_names = {c.get("name") for c in seeded}

    # 用子集而非相等：能力表在测试期间只会被【追加】(其他测试注册的能力也会落到这个
    # 临时文件里),但仓库里那份的条目一个都不能少。
    missing = real_names - seeded_names
    assert not missing, f"种子能力在临时配置里丢失: {sorted(missing)[:10]}"


def test_knowledge_base_default_persists_outside_repo():
    """不传参的 KnowledgeBaseSystem 不能落到仓库里。"""
    from nodes.Node_72_KnowledgeBase.knowledge_base_system import KnowledgeBaseSystem

    kb = KnowledgeBaseSystem()

    assert not _is_inside(Path(kb.persist_directory), PROJECT_ROOT), (
        f"KnowledgeBaseSystem 默认写到仓库内的 {kb.persist_directory}；"
        "应由 conftest 设置 GALAXY_KNOWLEDGE_DIR 引到临时目录。"
    )


def test_knowledge_base_honors_explicit_directory(tmp_path):
    """显式参数优先级高于环境变量 —— 否则测试无法各自独立。"""
    from nodes.Node_72_KnowledgeBase.knowledge_base_system import KnowledgeBaseSystem

    target = tmp_path / "explicit_kb"
    kb = KnowledgeBaseSystem(persist_directory=str(target))

    assert Path(kb.persist_directory).resolve() == target.resolve()

    kb.add_knowledge("isolation probe", {"category": "test"})
    assert (target / "knowledge_entries.json").is_file(), "显式目录下应当真的落盘"


def test_knowledge_entries_json_not_tracked_by_git():
    """防止测试残渣再被提交回仓库。"""
    if shutil.which("git") is None or not (PROJECT_ROOT / ".git").exists():
        pytest.skip("没有 git 或不在工作副本中")

    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "knowledge_db/knowledge_entries.json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, (
        "knowledge_db/knowledge_entries.json 又被提交进仓库了。"
        "它是跑测试产生的残渣（knowledge_db/ 已在 .gitignore 中,但 gitignore 对"
        "已跟踪文件无效）。用 `git rm --cached knowledge_db/knowledge_entries.json` 取消跟踪。"
    )
