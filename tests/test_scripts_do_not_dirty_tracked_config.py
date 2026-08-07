"""tests/test_scripts_do_not_dirty_tracked_config.py
=====================================================

**跑一个"验证"脚本，不许把它验证的东西改掉。**

怎么发现的
----------
清 ``config/capabilities.json`` 里的幽灵条目时，顶层 ``timestamp`` 莫名其妙变成了
当天的时间。逐条隔离下来是这样::

    A. 只 import + get_capability_manager()        → 文件没动
    B. 跑 scripts/verify_capability_registry.py    → **文件被改写**
    C. GALAXY_CONFIG_DIR="" 再加载一次             → 文件没动

原因
----
那个脚本会 ``register_capability("test_capability", node_id="test_node")`` 往真实
注册表里写东西。而 :class:`core.capability_manager.CapabilityManager` 的默认
``config_dir`` 是**仓库内的绝对路径**（基于 ``__file__``，换 CWD 也躲不掉），
``register_capability()`` 又会同步落盘 —— 于是跑一次"验证"就改写一次 git 跟踪文件。

pytest 那边早就用 conftest 里的 ``GALAXY_CONFIG_DIR`` 指到临时目录堵上了
（见 ``core/capability_manager.py`` 里那段注释）。**但脚本不走 conftest**，
所以那个洞对脚本一直是开着的。

为什么这值得钉一条
------------------
实测那个脚本会把测试能力注销掉，所以**不会**留下垃圾条目 —— 只有 ``timestamp``
每跑一次变一次。危害看着很小，但性质不对：

* 一个**验证**脚本修改它要验证的对象，等于观测行为本身改变了被观测者；
* 它会让 ``git status`` 无缘无故变脏，而这个仓库的日常判据里就有一条
  "跑完测试 git 得是干净的" —— 多一个会自己变脏的入口，那条判据就开始失效。

顺带说清楚一件事：本轮从 ``capabilities.json`` 里删掉的那 7 条垃圾
（``node_x`` / ``node_meta`` / ``node_sink`` / ``node_local`` / ``node_42`` /
``node_55`` / ``119``，时间戳挤在 2026-07-27 12:17–12:18）**不是**这个脚本写的
—— 它写的是 ``test_capability`` / ``test_node``，名字对不上。那 7 条来自
conftest 堵上之前的 pytest。两个入口，同一个洞。
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 脚本 → 它绝对不许改动的仓库内文件。再发现一个，往这里加一行即可。
SCRIPTS_UNDER_TEST = [
    (
        "scripts/verify_capability_registry.py",
        ["config/capabilities.json"],
    ),
]


def _digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("script,protected", SCRIPTS_UNDER_TEST, ids=[s for s, _ in SCRIPTS_UNDER_TEST])
def test_script_leaves_tracked_config_untouched(script: str, protected: list):
    """真跑一遍脚本，前后逐字节比对。

    判据是**行为的**，不是"源码里有没有设 GALAXY_CONFIG_DIR"。后者换个写法就能
    绕过去，而且也拦不住别的写盘路径。
    """
    script_path = REPO_ROOT / script
    if not script_path.exists():
        pytest.skip(f"{script} 不存在")

    targets = [REPO_ROOT / p for p in protected]
    for t in targets:
        if not t.exists():
            pytest.skip(f"{t.relative_to(REPO_ROOT)} 不存在")

    before = {t: _digest(t) for t in targets}

    # ⚠️ 必须**摘掉** GALAXY_CONFIG_DIR 再跑。
    #
    # ``tests/conftest.py:232`` 会把这个变量塞进 ``os.environ``，而 subprocess 默认
    # 继承父进程环境 —— 第一版就是这么写的，结果：把脚本里的沙箱那段整个换成
    # ``if False:``，这条测试**照样绿**。因为子进程拿到的是 pytest 设的那个临时目录，
    # 保护它的是 conftest，不是脚本自己。
    #
    # 变异不红的时候，先确认变异真的落地了 —— 落地了还不红，那就是判据本身不成立。
    # 这里正是后者。摘掉之后才复现出真实条件：有人在 shell 里直接
    # ``python scripts/verify_capability_registry.py``。
    env = {k: v for k, v in os.environ.items() if k != "GALAXY_CONFIG_DIR"}

    proc = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )

    changed = [t.relative_to(REPO_ROOT).as_posix() for t in targets if _digest(t) != before[t]]
    assert not changed, (
        f"{script} 跑完之后改写了这些 git 跟踪文件：{changed}\n"
        "验证脚本不该修改它验证的对象。修法见该脚本顶部：在 import core.* 之前把 "
        "GALAXY_CONFIG_DIR 指到临时目录，并把真实配置拷贝进去。"
    )

    # 顺带确认它是真的跑通了 —— 否则"没改动"可能只是因为它一开始就崩了。
    assert proc.returncode == 0, f"{script} 退出码 {proc.returncode}\nstdout:\n{proc.stdout[-2000:]}"
