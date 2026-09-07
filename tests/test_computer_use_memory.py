"""tests/test_computer_use_memory.py
=======================================
桌面闭环的情景记忆:失败带截图写入、结局收口写入、开跑前召回一次并注入提示词。

守的是什么
----------
``core/computer_use_loop`` 是这套系统里唯一真正「看着屏幕做事」的闭环,但它此前
**一个字都不写记忆**(``grep -n "memory\\|remember\\|recall"`` 返回空)。它只有一份
``history`` 活在单次 ``run()`` 的栈上 —— 那是工作记忆,函数返回就没了。

于是同一个任务跑第二遍,智能体不知道上次在这个界面点那个按钮没有反应。综述里
Memory 那一章讲的情景记忆,在这条链路上完全不存在。

跨模态记忆的基础设施(``UnifiedMemory.remember_media`` + CLIP provider,文本与图像
同一向量空间)早就建好了,只是没人用。本文件测的是把它接上之后的行为。

全部用注入的替身,不触真实记忆后端 —— 理由见
``tests/test_computer_use_loop.py`` 里 ``_fast`` fixture 的注释。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from core.computer_use_loop import ComputerUseLoop
from core.computer_use_memory import ComputerUseEpisodicMemory, memory_enabled

# ───────────────────── 替身 ─────────────────────


@dataclass
class _FakeResp:
    content: str


@dataclass
class _ScriptedRouter:
    script: List[Dict[str, Any]] = field(default_factory=list)
    calls: List[Any] = field(default_factory=list)
    _i: int = 0

    async def chat(self, messages=None, **kw):
        self.calls.append(messages)
        step = self.script[min(self._i, len(self.script) - 1)]
        self._i += 1
        return _FakeResp(content=json.dumps(step, ensure_ascii=False))


@dataclass
class _Hit:
    """MemoryHit 的最小替身(只用到 content / modality)。"""

    content: str
    modality: str = "text"
    score: float = 1.0


class _FakeMemory:
    """记下每一次读写,不做任何真实存储。"""

    def __init__(self, *, experience: str = "", explode: bool = False) -> None:
        self.experience = experience
        self.explode = explode
        self.failures: List[Dict[str, Any]] = []
        self.outcomes: List[Dict[str, Any]] = []
        self.recalls: List[str] = []

    async def recall_experience_parts(self, instruction: str):
        """替身也走**真实契约**:返回内容部件,不是字符串。

        2026-09-07 改:``recall_experience()``(返回纯字符串那个)被
        ``recall_experience_parts()`` 取代了 —— 一次召回同时给文字和画面,
        不必为了拿文字再打一遍向量库。替身跟着改,否则闭环调到一个替身没有的
        方法上,异常会被那条"记忆坏掉不该中断闭环"的 try 吞掉,于是这个文件
        看起来全绿、而召回其实一次都没成功过。
        """
        self.recalls.append(instruction)
        if self.explode:
            raise RuntimeError("记忆后端炸了")
        return [{"type": "text", "text": self.experience}] if self.experience else []

    async def remember_failure(self, instruction: str, **kw: Any) -> None:
        if self.explode:
            raise RuntimeError("记忆后端炸了")
        self.failures.append({"instruction": instruction, **kw})

    async def remember_outcome(self, instruction: str, **kw: Any) -> None:
        if self.explode:
            raise RuntimeError("记忆后端炸了")
        self.outcomes.append({"instruction": instruction, **kw})


def _loop(script, *, memory, screen: str = "SCREEN_B64", fail_act: bool = False):
    dispatched: List[Dict] = []

    async def _perceive():
        return screen

    async def _act(action, params, node_id):
        dispatched.append({"action": action, "params": params})
        return {"success": not fail_act, "error": "act failed" if fail_act else ""}

    loop = ComputerUseLoop(
        router=_ScriptedRouter(script=script),
        perceive_fn=_perceive,
        act_fn=_act,
        memory=memory,
    )
    return loop, dispatched


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setenv("GALAXY_CU_SETTLE_S", "0")
    monkeypatch.delenv("GALAXY_COMPUTER_USE", raising=False)
    monkeypatch.delenv("GALAXY_CU_MEMORY", raising=False)


# ───────────────────── 写入:只记失败 ─────────────────────


def test_失败的步骤带着当时的截图写进记忆():
    """失败那一步是下次唯一需要知道的东西,而且必须带截图。

    带截图才能凭「这个界面」召回 —— CLIP 把文本和图像放进同一向量空间,
    下次遇到长得一样的屏幕就能命中,而不只是靠任务描述的字面相似。
    """
    mem = _FakeMemory()
    loop, _ = _loop(
        [
            {"action": "click", "x": 10, "y": 20, "reason": "点它"},
            {"action": "done", "result": "结束", "reason": "收工"},
        ],
        memory=mem,
        fail_act=True,
    )
    asyncio.run(loop.run("打开设置"))

    assert len(mem.failures) == 1, f"失败步骤没写进记忆: {mem.failures}"
    rec = mem.failures[0]
    assert rec["instruction"] == "打开设置"
    assert rec["action"] == "click"
    assert rec["params"] == {"x": 10, "y": 20}
    assert rec["error"] == "act failed"
    assert rec["screen_b64"] == "SCREEN_B64", "没带上失败那一拍的截图"


def test_成功的步骤不写记忆():
    """反向保险。

    没有这条,把写入改成"每步都写"也能让上面那条变绿,而那正是要避免的:
    顺利走过去的步骤下次也会顺利走过去,逐步全记的代价是每步一次 CLIP 编码。
    """
    mem = _FakeMemory()
    loop, _ = _loop(
        [
            {"action": "click", "x": 1, "y": 2, "reason": "a"},
            {"action": "type", "text": "hi", "reason": "b"},
            {"action": "done", "result": "ok", "reason": "c"},
        ],
        memory=mem,
    )
    asyncio.run(loop.run("随便什么任务"))
    assert mem.failures == [], f"成功的步骤不该写记忆: {mem.failures}"


# ───────────────────── 写入:结局收口 ─────────────────────


@pytest.mark.parametrize(
    "script, expect_reason",
    [
        ([{"action": "done", "result": "好了", "reason": "r"}], "done"),
        ([{"action": "fail", "result": "做不到", "reason": "r"}], "fail"),
        ([{"action": "飞天遁地", "reason": "r"}], "action_rejected"),
        (
            [
                {"action": "click", "x": 1, "y": 1, "reason": "r"},
                {"action": "click", "x": 1, "y": 1, "reason": "r"},
                {"action": "click", "x": 1, "y": 1, "reason": "r"},
                {"action": "click", "x": 1, "y": 1, "reason": "r"},
            ],
            "loop_detected",
        ),
    ],
)
def test_每条退出路径都写下结局(script, expect_reason):
    """``_run_guarded`` 有六个 return 点,逐个补写必然漏掉一个。

    所以结局写在 ``run()`` 那一层收口。这条用例把几条形状不同的退出路径都走一遍
    —— 漏掉的往往正是最少见、也最值得记的那条。
    """
    mem = _FakeMemory()
    loop, _ = _loop(script, memory=mem)
    out = asyncio.run(loop.run("测试任务"))

    assert out["stop_reason"] == expect_reason
    assert len(mem.outcomes) == 1, f"{expect_reason} 这条路径没写结局"
    assert mem.outcomes[0]["stop_reason"] == expect_reason
    assert mem.outcomes[0]["instruction"] == "测试任务"


def test_感知拿不到画面时也写下结局():
    """闭眼那条路径同样要留痕:否则"这台机器上屏幕采集没开"这件事在记忆里是空白。"""
    mem = _FakeMemory()

    async def _no_screen():
        return None

    loop = ComputerUseLoop(
        router=_ScriptedRouter(script=[{"action": "done", "reason": "r"}]),
        perceive_fn=_no_screen,
        act_fn=None,
        memory=mem,
    )
    out = asyncio.run(loop.run("看看屏幕"))
    assert out["stop_reason"] == "no_perception"
    assert len(mem.outcomes) == 1
    assert mem.outcomes[0]["stop_reason"] == "no_perception"


def test_dry_run_不写结局():
    """dry_run 没有真的操作任何东西,记进去只会污染召回。"""
    mem = _FakeMemory()
    loop, _ = _loop([{"action": "click", "x": 1, "y": 1, "reason": "r"}], memory=mem)
    out = asyncio.run(loop.run("预览一下", dry_run=True))
    assert out["stop_reason"] == "dry_run"
    assert mem.outcomes == [], "dry_run 不该写结局"


# ───────────────────── 召回与注入 ─────────────────────


def test_召回到的经验进了规划提示词():
    mem = _FakeMemory(experience="- [截图]上次在这个界面点(10,20)没反应")
    router = _ScriptedRouter(script=[{"action": "done", "result": "ok", "reason": "r"}])
    loop = ComputerUseLoop(
        router=router,
        perceive_fn=lambda: asyncio.sleep(0, result="S"),
        act_fn=None,
        memory=mem,
    )
    asyncio.run(loop.run("打开设置"))

    assert mem.recalls == ["打开设置"], "开跑前没有召回,或召回了不止一次"
    text = router.calls[0][-1]["content"][0]["text"]
    assert "过往经验" in text and "点(10,20)没反应" in text


def test_没有经验时提示词里不出现那一段():
    """空串表示"没有可用记忆或没命中",此时整段都不该出现。

    塞一句「过往经验:(无)」会让模型以为系统查过且确实没有,而实际可能是记忆层
    根本没配 —— 那是两件事,不该长得一样。
    """
    mem = _FakeMemory(experience="")
    router = _ScriptedRouter(script=[{"action": "done", "result": "ok", "reason": "r"}])
    loop = ComputerUseLoop(
        router=router,
        perceive_fn=lambda: asyncio.sleep(0, result="S"),
        act_fn=None,
        memory=mem,
    )
    asyncio.run(loop.run("打开设置"))
    assert "过往经验" not in router.calls[0][-1]["content"][0]["text"]


def test_只在开跑前召回一次_不是每步一次():
    """每步召回会把提示词撑大,也会把一次运行的延迟乘上步数。"""
    mem = _FakeMemory(experience="- 某条经验")
    loop, _ = _loop(
        [
            {"action": "click", "x": 1, "y": 1, "reason": "r"},
            {"action": "click", "x": 2, "y": 2, "reason": "r"},
            {"action": "done", "result": "ok", "reason": "r"},
        ],
        memory=mem,
    )
    asyncio.run(loop.run("多步任务"))
    assert len(mem.recalls) == 1, f"召回了 {len(mem.recalls)} 次,应该只有 1 次"


# ───────────────────── 记忆坏掉不该拖垮任务 ─────────────────────


def test_记忆层抛异常时任务照常完成():
    """取舍方向不能反:记忆是辅助设施,它坏掉不该让一个正在操作真实键鼠的闭环中断。"""
    mem = _FakeMemory(explode=True)
    loop, dispatched = _loop(
        [
            {"action": "click", "x": 1, "y": 1, "reason": "r"},
            {"action": "done", "result": "照样完成", "reason": "r"},
        ],
        memory=mem,
        fail_act=True,  # 同时触发失败写入这条路径
    )
    out = asyncio.run(loop.run("记忆坏了也要跑完"))
    assert out["success"] is True and out["stop_reason"] == "done"
    assert [d["action"] for d in dispatched] == ["click"]


# ───────────────────── 策略层本身 ─────────────────────


def test_没有后端时整体是_no_op():
    """没配记忆后端 → available 为 False → 召回返回空串、写入什么都不做。"""
    epi = ComputerUseEpisodicMemory(memory=_NullBackend())
    assert epi.available is False
    assert asyncio.run(epi.recall_experience_parts("任务")) == []
    # 不抛异常即可
    asyncio.run(epi.remember_outcome("任务", success=False, stop_reason="x", message="", step_count=0))


class _NullBackend:
    enabled = False


def test_开关可以关掉整条线(monkeypatch):
    monkeypatch.setenv("GALAXY_CU_MEMORY", "0")
    assert memory_enabled() is False
    epi = ComputerUseEpisodicMemory(memory=_LiveBackend())
    assert epi.available is False, "关掉之后不该再认为可用"


class _LiveBackend:
    enabled = True


@pytest.mark.parametrize("raw", [None, "", "1", "true", "on"])
def test_默认是开的(monkeypatch, raw):
    """与 computer_use_enabled 同型:未设置或空串都算开。

    刻意默认开,而不是又加一个"建好了、默认关着、没有文档"的开关 —— 本仓已经有
    好几个了。默认开在这里是安全的:没配记忆后端时 available 天然为 False。
    """
    if raw is None:
        monkeypatch.delenv("GALAXY_CU_MEMORY", raising=False)
    else:
        monkeypatch.setenv("GALAXY_CU_MEMORY", raw)
    assert memory_enabled() is True


def test_召回结果里的截图被标出来():
    """标出模态,让模型知道这条经验背后是一张真实截图,而不是谁写的一句话。"""
    text = ComputerUseEpisodicMemory._format_experience(
        [_Hit(content="这个界面点右上角没反应", modality="image"), _Hit(content="纯文字经验")]
    )
    assert "[截图]这个界面点右上角没反应" in text
    assert "- 纯文字经验" in text


def test_召回条数与单条长度都有上限():
    """多了会把规划提示词挤满,而排在后面的相关度已经很低。"""
    hits = [_Hit(content="x" * 500) for _ in range(10)]
    text = ComputerUseEpisodicMemory._format_experience(hits)
    lines = text.split("\n")
    assert len(lines) == 3, f"召回条数没截断: {len(lines)}"
    assert all(len(line) <= 210 for line in lines), "单条长度没截断"
