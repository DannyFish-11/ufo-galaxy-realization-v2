"""
顶层模块名劫持守卫
==================

姊妹篇：``test_no_test_hijacks_a_singleton.py`` 守的是"进程级单例被某个用例改写
后不还原"，本文件守的是同一类问题的另一种形态 —— **顶层模块名被劫持**。

背景（CI 实证，test-shard (4)）
------------------------------
本仓有 128 个 ``nodes/*/main.py``。任何一个测试只要把某个节点目录插进
``sys.path`` 首位——

    tests/integration/test_node108_metacognition.py:22   sys.path.insert(0, str(_NODE_DIR))
    tests/test_pr_a_multi_device_runtime_wiring.py:801   sys.path.insert(1, _NODE71_DIR)

——此后全进程的 ``import main`` 就可能解析到那个节点的 ``main.py``，而且一旦被
``sys.modules`` 缓存，同一分片里后续所有用例都跟着中招：

    FAILED tests/test_phase0_env_check_secrets_banner.py::... - AttributeError:
    <module 'main' from '.../nodes/Node_113_AndroidVLM/main.py'> has no attribute 'ENV_FILE'
    FAILED tests/test_setup_wizard_container_runtime.py::... - AttributeError:
    <module 'main' from '.../nodes/Node_113_AndroidVLM/main.py'> has no attribute 'PROJECT_ROOT'

受害者本身完全正确、单独跑必过，只有在分片里排到污染者之后才挂 —— 典型的
测试顺序污染。

防护在哪
--------
``tests/conftest.py`` 的 ``_guard_top_level_module_hijack`` autouse fixture：
每个用例前后各校正一次，(1) 把 ``PROJECT_ROOT`` 拉回 ``sys.path`` 首位，
(2) 逐出 ``sys.modules`` 里指向仓库外文件的顶层模块，让下次 import 重新解析。

本文件验证这道防护**真的拦得住**：先人为制造与 CI 完全相同的劫持，再确认下一个
用例仍能拿到仓库根的 ``main``。测试顺序有意义 —— pytest 在单个文件内按定义顺序
执行，``test_a_*`` 必须排在 ``test_b_*`` 前面。
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 用哪个节点来制造劫持并不重要，重要的是它有 main.py 且不是仓库根那个。
# 选 Node_113_AndroidVLM 是因为 CI 里真实中招的就是它。
_HIJACKER_NODE = PROJECT_ROOT / "nodes" / "Node_113_AndroidVLM"


def test_a_hijack_top_level_main_like_ci_does():
    """人为复现 CI 中的劫持：节点目录进 sys.path，``main`` 被解析成节点的。

    这一步**必须成功制造出污染**，否则 ``test_b`` 就是在验证一个不存在的威胁。
    """
    if not (_HIJACKER_NODE / "main.py").is_file():
        pytest.skip(f"{_HIJACKER_NODE.name}/main.py 不存在，无法制造劫持")

    sys.path.insert(0, str(_HIJACKER_NODE))
    sys.modules.pop("main", None)

    import main as hijacked

    assert "Node_113_AndroidVLM" in str(
        hijacked.__file__
    ), "未能制造出劫持，本守卫失去意义 —— 说明 import 解析行为已变，请重写本测试"


def test_b_next_test_still_gets_repo_root_main():
    """紧跟在污染者之后的用例，仍必须拿到仓库根的 ``main.py``。

    断言用 ``ENV_FILE`` / ``PROJECT_ROOT`` 两个属性，正是 CI 里真实报缺的那两个。
    """
    import main

    assert hasattr(main, "ENV_FILE"), f"main 仍被劫持: {main.__file__}"
    assert hasattr(main, "PROJECT_ROOT"), f"main 仍被劫持: {main.__file__}"
    assert (
        Path(main.__file__).resolve() == (PROJECT_ROOT / "main.py").resolve()
    ), f"main 解析到了错误的文件: {main.__file__}"


def test_c_project_root_stays_first_on_sys_path():
    """污染者往 sys.path[0] 塞了东西后，守卫应把 PROJECT_ROOT 拉回首位。"""
    assert sys.path[0] == str(
        PROJECT_ROOT
    ), f"PROJECT_ROOT 不在 sys.path 首位，顶层 import 随时可能再被劫持: sys.path[0]={sys.path[0]!r}"
