"""桌面结构化派发只在「服务端就是那台机器」时成立。

`PLATFORM_GROUNDING_OWNER` 里 `windows: SERVER` 没错,但它**默认了**能走到这条路的
windows 就是本机。那个前提此前既没写下来,也没有任何东西挡住有人拿远端 device_id
调进来 —— 于是会发生:服务端隔着网络解析一张几百毫秒前的控件图,算出一个坐标,
派下去盲点。看起来"派发成功",实际点中的是什么不可知。

跨设备的正路是 agent_deploy + agent_execute(`requires_agent_deploy` 对所有物理设备
都返回 True):把 Agent 派过去,由它在对端本机用自己的仲裁器执行。

这组测试把那个前提钉成代码。
"""

from __future__ import annotations

import core.routes.ui_act as ui_act
from core.agent_card import local_device_id


def test_empty_device_id_means_this_machine():
    # 缺省就是本机 —— 仲裁器全程用 device_id="local" 操作本机,这是既有约定
    assert ui_act.targets_this_machine("") is True


def test_local_aliases_mean_this_machine():
    for alias in ("local", "LOCAL", "localhost", "self", "this", "  local  "):
        assert ui_act.targets_this_machine(alias) is True, alias


def test_own_device_id_means_this_machine():
    assert ui_act.targets_this_machine(local_device_id()) is True


def test_another_device_is_not_this_machine():
    assert ui_act.targets_this_machine("desktop-in-the-other-room") is False
    assert ui_act.targets_this_machine("win-7f3a") is False


def test_a_device_id_that_merely_contains_local_is_not_this_machine():
    # 子串匹配会把 "local-office-pc" 误判成本机 —— 那是另一台机器。
    assert ui_act.targets_this_machine("local-office-pc") is False
    assert ui_act.targets_this_machine("my-localhost-2") is False
