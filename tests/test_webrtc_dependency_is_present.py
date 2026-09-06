"""aiortc 必须真的装上 —— 否则真 WebRTC 回环测试会静默跳过。

为什么单独一个文件
------------------
``test_voice_call_bridge_real_webrtc`` 整个模块挂着 ``pytestmark = skipif(...)``,
因为没有 aiortc 时那十九条断言一条也跑不了。代价是:依赖一旦掉了,整组测试**静默
跳过**,CI 照样全绿 —— 而那正是最该报警的时刻。

本文件不挂任何 skip,所以它永远会跑。守卫和被守卫的东西不能共用同一个 skip 条件,
否则守卫会跟着一起消失 —— 这是我把守卫写进那个文件里之后当场撞上的:它自己被跳过了。

本仓已经吃过一次同型的亏:shared-transport 模块的单测从来没被 CI 跑过,因为工作流
只跑 :app 那个模块。绿了很久,什么都没验证。
"""

from __future__ import annotations

from core.voice_call_bridge import webrtc_available


def test_aiortc_is_installed_so_the_real_loopback_suite_actually_runs():
    reason = webrtc_available()
    assert reason is None, (
        f"aiortc 不可用({reason})。真 WebRTC 回环测试会被静默跳过 —— "
        "它已写进 requirements-dev.txt,CI 装 dev 依赖时应当有它;"
        "本机开发请 pip install aiortc。"
    )
