"""tests/test_node_stays_up.py
==============================

**节点起来之后要一直在。**

为什么单独钉这一条
------------------
``Node_125_MediaGen`` 之前是这样的:健康服务跑在一个 **daemon 线程**上,主线程
``asyncio.run(main())`` 跑的是一段演示流程 —— 提交三个样例任务、等 10 秒、停服务、
返回。主线程一返回,daemon 线程跟着死,进程 ``exit=0``。

于是它的真实行为是:**起来几秒钟,打完「--- 演示结束 ---」就没了**。

这种失败最难查,因为它**不报错**:

* 退出码是 0 —— 任何按 returncode 判断的地方都认为它成功了；
* 端口一度真的通过 —— 抢在那几秒里探活会拿到 200；
* 日志末尾是「演示结束」这种听起来很正常的话。

启动器那边看到的是"进程起过、端口一度通、然后消失"。而 ``--group all`` 从来只起
12 个节点(见 launcher/nodes.py 的 auto_start 过滤),Node_125 不在其中,所以这件事
一直没人撞上 —— 是把 125 个节点逐个真跑一遍才露出来的。

判据
----
按启动器的真实方式起进程,等它把端口监听起来,再**多等一段**,要求进程仍然活着且
端口仍然应答。"多等"是关键:只看"起没起来"照样会被这个 bug 骗过去。
"""

from __future__ import annotations

import os
import pathlib
import re
import socket
import subprocess
import sys
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
NODES_DIR = REPO_ROOT / "nodes"

#: 起来后至少还要活这么久。演示流程是「等 10 秒然后退」,所以这个数必须**大于**它,
#: 否则测试会在它自杀之前就通过。
LINGER_S = 16.0
BOOT_TIMEOUT_S = 60.0

# 每个都要真起进程,所以按需要加,不做成全量扫描(125 个节点真跑要十几分钟)。
#
# Node_125_MediaGen —— 跑完演示就退(本文件开头讲的那个)。
# Node_25_GoogleSearch —— 入口处一句多余的 `import googlesearch` 硬检查 + exit(1)。
#   与它自己的设计矛盾:文件顶部早有 _GOOGLESEARCH_AVAILABLE 守卫,搜索实现也明写
#   「优先 Custom Search API,回退 googlesearch-python」—— 配了 API Key 的用户压根
#   不需要那个库,却被入口堵死。
# Node_33_ADB —— 宿主机没装 adb 时,start() 里的 ADBNotAvailableError 一路穿到
#   FastAPI startup,节点直接 Exiting。而它在 registry/device_node_map.yaml 里是
#   on_demand:android_phone,设计上就是「有安卓设备才拉起来」,没有 adb 时的正确
#   姿态是**起来并如实说自己不可用**,而不是消失(消失之后启动器只会报"启动超时",
#   真实原因没有任何地方说得出来)。
#
# 注:这两个在**装了** adb / googlesearch-python 的机器上走的是正常路径,测试照样
# 绿 —— 它是回归守卫,不是环境探测。真正区分两条路径的是各自的 /health 字段。
NODES_UNDER_TEST = ["Node_125_MediaGen", "Node_25_GoogleSearch", "Node_33_ADB"]


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.mark.parametrize("node_name", NODES_UNDER_TEST)
def test_node_is_still_running_well_after_it_came_up(node_name: str, tmp_path):
    from core.port_config import get_node_port

    port = get_node_port(node_name)
    if _port_open(port):
        pytest.skip(f"{port} 已被占用,无法判定")

    node_dir = NODES_DIR / node_name
    log = tmp_path / f"{node_name}.log"
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONUNBUFFERED": "1",
        "NODE_NAME": node_name,
        "NODE_PORT": str(port),
        "PORT": str(port),
        "MEDIA_OUTPUT_DIR": str(tmp_path / "media"),  # 别往仓库里写产物
    }
    with log.open("wb") as fh:
        proc = subprocess.Popen(
            [sys.executable, "main.py"], cwd=str(node_dir), stdout=fh, stderr=subprocess.STDOUT, env=env
        )
    try:
        deadline = time.time() + BOOT_TIMEOUT_S
        while time.time() < deadline and not _port_open(port):
            if proc.poll() is not None:
                pytest.fail(
                    f"{node_name} 还没监听端口就退了(exit={proc.returncode})：\n"
                    f"{log.read_text('utf-8', 'replace')[-1500:]}"
                )
            time.sleep(0.5)

        assert _port_open(port), f"{node_name} 在 {BOOT_TIMEOUT_S}s 内没把 {port} 监听起来"

        # 关键的一段:起来之后再等。演示流程正是在这段时间里跑完并退出的。
        time.sleep(LINGER_S)

        assert proc.poll() is None, (
            f"{node_name} 起来之后自己退了(exit={proc.returncode}) —— "
            "「跑完一段流程就结束」不是服务,而且退出码 0 会让所有按 returncode 判断的地方"
            "都以为它成功了。日志尾部：\n" + log.read_text("utf-8", "replace")[-1500:]
        )
        assert _port_open(port), f"{node_name} 进程还在,但 {port} 不再应答"
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_the_demo_path_is_opt_in_and_still_works():
    """演示流程本身是有用的自检 —— 保留，但必须是显式 ``--demo``，不能是默认行为。"""
    src = (NODES_DIR / "Node_125_MediaGen" / "main.py").read_text(encoding="utf-8")
    assert re.search(r'["\']--demo["\']', src), "Node_125 的演示流程没有做成显式开关"
    # 默认分支必须是起服务,不是跑演示。
    tail = src.split('if __name__ == "__main__":')[-1]
    assert "uvicorn" in tail.lower(), "Node_125 的默认入口不是起服务"
