"""core/console_prompt.py — 启动时问人话。**带上界的那一份,全仓唯一。**

为什么必须有上界
----------------
全新克隆真跑发现的:启动链上有**四处** ``input()``,全都没有上界 ——

    core/container_runtime.py  两个运行时都装了 → 用哪个
    core/container_runtime.py  都没装 → 选偏好(两处)
    core/model_selection.py    AI 主脑档位选哪一档

而它们全都排在**系统托盘之前**::

    launcher/services.py:2051  基础设施(这里问运行时)
    launcher/services.py:2110  AI 大脑(这里问档位)
                  ↓
    launcher/services.py:2308  系统托盘

于是只要没人按回车,后面**所有**步骤都不发生 —— 右下角的托盘自然也不会出现。
所有者反馈的"卡在那儿"和"托盘没显示",在全新克隆上是同一件事的两个面。

一个装完就双击图标启动的人,不会盯着控制台等着回答问题。所以:选择权保留
(到点之前任何时候按键都算数),但**走开不会把启动卡死**。

为什么是一个模块而不是各自加超时
--------------------------------
第一版只修了运行时那一处。那正是这个仓库最常犯的"改一处漏三处"——四个提示
是同一件事的四个实例,得有**一份**实现。这里就是那一份;那道门
(``tests/test_no_unbounded_prompt_on_startup_path.py``)挡住新加的裸 ``input()``。
"""

from __future__ import annotations

import os
import threading
from typing import List, Optional

__all__ = [
    "DEFAULT_PROMPT_TIMEOUT_S",
    "PROMPT_TIMEOUT_ENV",
    "ask",
    "prompt_timeout_s",
    "timed_out_notice",
]

#: 等多久(秒)。20 秒够一个正在看屏幕的人读完选项并按键,又不至于让走开的人干等。
DEFAULT_PROMPT_TIMEOUT_S = 20.0

#: 调这个上界的环境变量。设 ``0`` = 一直等(有人明确想要旧行为)。
PROMPT_TIMEOUT_ENV = "GALAXY_RUNTIME_PROMPT_TIMEOUT"


def prompt_timeout_s() -> float:
    """当前生效的上界。乱填退回默认 —— **不许退回 0**(那就又能卡死了)。"""
    raw = (os.environ.get(PROMPT_TIMEOUT_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_PROMPT_TIMEOUT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_PROMPT_TIMEOUT_S


def ask(prompt: str, timeout_s: Optional[float] = None) -> Optional[str]:
    """带上界地问一句。

    Returns:
        用户输入的字符串;``None`` 表示**没人回答**。

    ``None`` 和 ``""`` 必须分开:

    - ``""``   → 用户**按了回车**,明确选了默认项;
    - ``None`` → 没人在(到点了 / stdin 已关闭)。

    两者接下来该说的话不一样:前者不必解释,后者必须告诉人"我们替你选了哪个"。
    混成一谈的话,屏幕上会把自动选的说成是用户选的 —— 又一次说的和现实相反。

    实现上只能起一条守护线程去读:``input()`` 没有可移植的超时。到点之后那条
    线程还挂在 stdin 上,用户**后来**敲的第一下会被它吃掉 —— 这是这个做法的
    已知代价,写在这里而不是让人自己去撞。相对"永远卡住",这个代价是划算的。
    """
    limit = prompt_timeout_s() if timeout_s is None else timeout_s
    if limit <= 0:
        # 明确要求一直等。
        try:
            return input(prompt)
        except EOFError:
            return None
        except KeyboardInterrupt:
            return ""

    box: List[Optional[str]] = []

    def _read() -> None:
        try:
            box.append(input(prompt))
        except EOFError:
            # stdin 关了 —— **没有人能回答**,这和"按了回车"是两回事。
            box.append(None)
        except KeyboardInterrupt:
            # Ctrl+C:人在,而且明确表示"别问了,走吧" —— 当作选默认。
            box.append("")
        except Exception:  # noqa: BLE001 —— 读不到就是没人回答
            box.append(None)

    thread = threading.Thread(target=_read, name="GalaxyConsolePrompt", daemon=True)
    thread.start()
    thread.join(limit)
    return box[0] if box else None


def timed_out_notice(what: str, chosen: str, timeout_s: Optional[float] = None) -> str:
    """没人回答时该说的那句话。**唯一出处**。

    Args:
        what:    问的是什么(比如"运行时"、"主脑档位")。
        chosen:  替他选了哪个。
        timeout_s: 等了多久;不给就取当前上界。

    屏幕上必须能看出"这不是你选的" —— 否则人会以为自己选过,下次找不到地方改。
    """
    limit = prompt_timeout_s() if timeout_s is None else timeout_s
    return f"{limit:.0f} 秒没人选{what},按默认用 {chosen} 继续(不是你选的;想改见下一行)。"
