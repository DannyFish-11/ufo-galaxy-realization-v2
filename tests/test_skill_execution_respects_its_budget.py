"""一条技能挂住时，它必须在**自己的预算内**把结果交回来。

## 真实案发

CI 上 `tests/test_skill_md.py::test_skill_md_loader` 连续两次被 pytest-timeout
在 120 秒砍掉，GitHub 在清理阶段还打出 `Terminate orphan process: (curl)`。

查出来是两个叠在一起的缺陷：

1. **内层时限比外层预算大。** 示例技能有 6 条 `curl wttr.in/...`，`execute()`
   给每条 60 秒、且**没有总上限** —— 6 × 60 = 360 秒。调用方(判据 120 秒)只能
   被硬杀掉，拿不到"哪几条跑了、哪几条超时"这份结果。**优雅降级那条路永远
   走不到**，因为它在外层预算之外。

   这跟仓库里记过的那条是同一个形状：*Phase 6 内层 timeout 不小于外层，
   优雅降级永远到不了*。同一个错犯第二次，所以这次钉住。

2. **超时之后子进程没被收掉。** `asyncio.wait_for` 取消的只是这边的等待，
   `curl` 照样活着 —— 那些 orphan 就是这么来的。

## 钉住的是什么

* 挂住的技能必须在预算内返回，而不是把调用方拖死；
* 超时之后不许留下活着的子进程；
* 没轮到跑的命令要**说自己没轮到** —— 它既不是成功也不是失败。
  标成失败会让人去查一条根本没跑过的命令；不记则等于假装整条跑完了。
"""

from __future__ import annotations

import asyncio
import os
import random
import subprocess
import time

import pytest

from core.skill_md_loader import DEFAULT_EXECUTE_BUDGET_S, SkillMD, SkillMDLoader


def _mark() -> str:
    """一个**数字**标记。

    它要出现在孙子进程(`sleep`)自己的 argv 里,pgrep 才找得到。第一版把标记
    写成了 shell 注释(`sleep 999 # tag`)—— 那个注释被 sh 吃掉了,压根没传给
    `sleep`,于是那条"有没有留下孤儿"的判据**永远找不到东西,永远绿**。
    """
    return str(random.randint(70000, 99999))


def _hanging_skill(n_commands: int, mark: str) -> SkillMD:
    """n 条永远不返回的命令。

    用 `sh -c 'sleep N'`:sh 会 fork 出 `sleep` 当孙子(实测如此)。只杀直接的
    子进程,`sleep` 会活下来并且攥着管道 —— 那正是要验的那个形状。
    """
    skill = SkillMD(name="hang", description="挂住不返回")
    skill.commands = [{"command": f"sh -c 'sleep {mark}'"} for _ in range(n_commands)]
    return skill


def _alive(mark: str) -> str:
    """系统里还挂着这个标记的进程,没有就返回空串。"""
    found = subprocess.run(["pgrep", "-f", f"sleep {mark}"], capture_output=True, text=True)
    return found.stdout.strip() if found.returncode == 0 else ""


async def _bounded(coro, what: str):
    """给 execute() 套一层硬上限。

    **判据自己不许挂住。** 直接 await 的话,总预算一旦失效,判据就跟着一起吊死,
    只能等 pytest-timeout 在 120 秒砍它 —— 那正是我们要治的病,判据不该是同一个
    病的又一个病例。(第一版就是直接 await 的,自证时整条 pytest 被 Terminated。)
    """
    try:
        return await asyncio.wait_for(coro, timeout=15)
    except asyncio.TimeoutError:
        pytest.fail(f"{what} 15 秒还没回来 —— 总预算没起作用,每条命令还是各算各的")


class TestTheBudgetIsForTheWholeSkill:
    @pytest.mark.asyncio
    async def test_six_hanging_commands_still_return_within_budget(self) -> None:
        """六条都挂住，整条仍然要在预算内回来。

        这正是 CI 上炸掉的那个形状：6 条 curl × 每条 60 秒。
        """
        mark = _mark()
        loader = SkillMDLoader()
        loader.skills["hang"] = _hanging_skill(6, mark)

        started = time.monotonic()
        result = await _bounded(loader.execute("hang", budget_s=2.0), "六条挂住的命令")
        elapsed = time.monotonic() - started

        assert elapsed < 8.0, f"六条挂住的命令花了 {elapsed:.1f} 秒才回来，预算只有 2 秒"
        assert result["success"] is False
        assert len(result["results"]) == 6, "没轮到的那几条也得出现在结果里"

    @pytest.mark.asyncio
    async def test_commands_that_never_ran_say_so(self) -> None:
        """没轮到 ≠ 失败。**空和未知必须分得开。**"""
        loader = SkillMDLoader()
        loader.skills["hang"] = _hanging_skill(4, _mark())

        result = await _bounded(loader.execute("hang", budget_s=1.5), "四条挂住的命令")
        not_attempted = [r for r in result["results"] if r.get("attempted") is False]

        assert not_attempted, "预算用完之后那几条没有说自己「没轮到」"
        for r in not_attempted:
            assert "没轮到" in r["error"], r
            assert "超时" not in r["error"], "把没跑过的命令说成超时 —— 人会去查一条根本没执行过的命令"

    @pytest.mark.skipif(os.name == "nt", reason="按进程组收是 POSIX 那一支；Windows 走另一条")
    @pytest.mark.asyncio
    async def test_a_timed_out_child_is_reaped_not_left_running(self) -> None:
        """超时之后不许在系统里留下活着的进程。

        CI 上 GitHub 替我们收的那两个 `curl` 孤儿，就是这条没做到。

        **这条判据第一版是空的。** 它当时查的是"事件循环里还挂没挂着 communicate
        任务" —— 我把 `_kill_process_tree` 整个删掉，它照样绿。一条删掉被测代码还能
        过的判据，等于没有判据。现在改成去**系统里数**那个进程还在不在。

        标记串带一个随机数，免得跟机器上别的 sleep 撞上，把别人的进程当成自己的孤儿。
        """
        mark = _mark()
        loader = SkillMDLoader()
        loader.skills["hang"] = _hanging_skill(1, mark)

        await _bounded(loader.execute("hang", budget_s=1.0), "一条挂住的命令")
        await asyncio.sleep(0.4)  # 给信号一点送达的时间

        still = _alive(mark)
        if still:  # 别把孤儿留给下一条判据
            subprocess.run(["pkill", "-9", "-f", f"sleep {mark}"], capture_output=True)
        assert not still, (
            f"超时之后系统里还活着这些进程：{still} —— " f"只杀了直接的子进程，孙子还攥着管道。要按进程组收。"
        )


class TestTheDefaultFitsInsideItsCallers:
    def test_the_default_budget_is_smaller_than_the_test_budget(self) -> None:
        """默认预算必须小于调用方的预算，否则降级路径够不着。

        判据那边是 120 秒(pytest.ini)。默认值只要 ≥ 它，这个缺陷就会原样回来。
        """
        assert DEFAULT_EXECUTE_BUDGET_S < 120, (
            f"默认总预算 {DEFAULT_EXECUTE_BUDGET_S} 秒 ≥ 判据的 120 秒 —— " f"内层又比外层大了，优雅降级还是走不到"
        )


class TestTheExampleSkillPointsAtARealHost:
    def test_no_typoed_hostname(self) -> None:
        """`wtt.in` 少了一个 r。它既不是 wttr.in，也正好是最容易挂住而不是
        快速失败的那一种 —— 一个没人认领的域名可能直接把连接黑洞掉。"""
        from pathlib import Path

        md = Path(__file__).resolve().parents[1] / "skills/examples/weather/SKILL.md"
        text = md.read_text(encoding="utf-8")
        assert "wtt.in" not in text.replace("wttr.in", ""), "SKILL.md 里还有 wtt.in 这个拼错的域名"


class TestTheCleanupCannotKillItsCaller:
    """清理动作**绝不许**把调用方自己打死。

    自证这个修法时撞出来的:把起进程时的 `start_new_session` 删掉,孩子就落在
    调用方同一个进程组里,`killpg` 于是把**整个 pytest** 打死了 —— 连一行失败
    信息都没留下,只有一个 `Killed`。

    一个"清理"动作能把调用方打死,比它要治的那个泄漏坏得多。所以钉住:
    发组信号之前必须先问一句"这是不是我自己的组"。
    """

    @pytest.mark.skipif(os.name == "nt", reason="进程组是 POSIX 那一支")
    def test_it_refuses_to_signal_its_own_process_group(self) -> None:
        from core.skill_md_loader import _kill_process_tree

        class _SameGroup:
            """一个假进程,pid 就是本进程 —— 也就是"和我同组"的最极端情形。"""

            pid = os.getpid()

            def __init__(self) -> None:
                self.killed = False

            def kill(self) -> None:
                self.killed = True

        fake = _SameGroup()
        # 活着从这句里出来,本身就是判据的一半:它没给自己所在的组发 SIGKILL。
        _kill_process_tree(fake)
        assert fake.killed, "同组时应当退回到只杀那一个进程，而不是整组"
