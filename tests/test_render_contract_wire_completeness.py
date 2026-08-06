"""tests/test_render_contract_wire_completeness.py
===================================================

渲染契约有**四个副本**，它们必须永远说同一件事。

链路
----
::

    core/phase_contract.RenderPosture          ← Python 权威定义
        ↓ resolve_render_posture()
    core/lumiv_websocket_bridge._render_payload()   ← 实际发上线的载荷
        ↓ WebSocket  payload.render
    types/phase_contract.gen.ts  RenderPosture ← scripts/gen_ts_types.py 生成
        ↓
    hooks/useRenderPosture.RENDER_POSTURE_FIELDS ← 前端对契约的期望

四处任何一处漂了,面板就会静默地少画一维 —— **不会报错**,只会看起来"少了点什么",
而没人能说出少了什么。生成机制挡得住 Python → TS 那一段,挡不住另外两段:
线上载荷真发了没有、前端真按这些字段读没有。

这条测试把四份对齐做成机器判据。

为什么值得单独一条
------------------
这套契约的后端半边(算、发)早就做完了,前端半边**一行没接**:``payload.render``
零读取、``RenderPosture`` 零 import。接上之后,前端第一次真的依赖这些字段 ——
从此后端少发一个字段就是**前端的缺陷**,而不再是"反正没人读"。
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from typing import List, Set

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PANEL_SRC = REPO_ROOT / "electron" / "renderer" / "panel" / "src"
GEN_TS = PANEL_SRC / "types" / "phase_contract.gen.ts"
HOOK_TS = PANEL_SRC / "hooks" / "useRenderPosture.ts"
APP_CSS = PANEL_SRC / "App.css"
TOKENS_CSS = PANEL_SRC / "styles" / "tokens.css"


def _python_fields() -> Set[str]:
    from core.phase_contract import RenderPosture

    return {f.name for f in dataclasses.fields(RenderPosture)}


def _generated_ts_fields() -> Set[str]:
    src = GEN_TS.read_text(encoding="utf-8")
    body = src.split("export interface RenderPosture {")[1].split("\n}")[0]
    return set(re.findall(r"^\s{2}(\w+):", body, re.M))


def _hook_expected_fields() -> Set[str]:
    src = HOOK_TS.read_text(encoding="utf-8")
    body = src.split("export const RENDER_POSTURE_FIELDS = [")[1].split("] as const;")[0]
    return set(re.findall(r"'([\w_]+)'", body))


def _wire_fields() -> Set[str]:
    """真发上线的那份载荷有哪些键。"""
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge

    GalaxyPresenceBridge._instance = None
    bridge = GalaxyPresenceBridge.get_instance()
    try:
        return set(bridge._render_payload("liminal").keys())
    finally:
        GalaxyPresenceBridge._instance = None


# ── 1. 四份定义必须一致 ──────────────────────────────────────────────────────


def test_generated_ts_matches_the_python_contract():
    """生成文件与 Python 权威定义对齐 —— 没重新生成就会红。"""
    py, ts = _python_fields(), _generated_ts_fields()
    assert ts == py, (
        f"生成的 TS 与 Python 契约不一致。TS 多出:{sorted(ts - py)};TS 缺少:{sorted(py - ts)}。"
        f"请重跑 python scripts/gen_ts_types.py"
    )


def test_frontend_expectation_matches_the_generated_contract():
    """前端手写的期望字段表与生成契约对齐。

    ``RENDER_POSTURE_FIELDS`` 是有意手写的:它代表**前端这一侧的期望**,少一个
    字段时 ``missingFields`` 才报得出来。但它不能与契约漂移,所以在这里对齐。
    """
    hook, ts = _hook_expected_fields(), _generated_ts_fields()
    assert hook == ts, f"前端期望与契约不一致。多出:{sorted(hook - ts)};缺少:{sorted(ts - hook)}"


def test_the_wire_payload_carries_every_contract_field():
    """**真发上线的**载荷一个字段都不能少。

    这是四段里唯一"生成机制管不到"的一段:``gen_ts_types.py`` 保证 Python → TS,
    但保证不了 ``_render_payload()`` 真的把每个字段都放进广播里。少一个,前端就会
    在 ``missingFields`` 里看到它 —— 但那是运行时才发现,这条让它在 CI 就红。
    """
    wire, py = _wire_fields(), _python_fields()
    assert py - wire == set(), f"这些契约字段没有发上线:{sorted(py - wire)}"


@pytest.mark.parametrize("phase", ["static", "liminal", "manifest"])
def test_wire_payload_is_complete_in_every_phase(phase: str):
    """三个相位都要发完整的契约 —— 不能只在某一相完整。

    分相位跑是因为 ``_render_payload`` 里有按相位分支的逻辑(比如阈限活动只在
    阈限相位里成立),分支写漏一个字段是很容易发生的事。
    """
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge

    GalaxyPresenceBridge._instance = None
    bridge = GalaxyPresenceBridge.get_instance()
    try:
        payload = bridge._render_payload(phase)
    finally:
        GalaxyPresenceBridge._instance = None

    missing = _python_fields() - set(payload.keys())
    assert not missing, f"{phase} 相位下缺字段:{sorted(missing)}"


# ── 2. 前端真的在读 ──────────────────────────────────────────────────────────


def test_the_panel_actually_imports_the_generated_render_contract():
    """``RenderPosture`` 必须真的被 import。

    这正是接入之前的状态:生成文件在、类型齐全、**零 import** —— 一份没人看的文档。
    ``types/phase.ts`` 当时只取了遗留的 ``PhasePosture``,而连它也没有任何组件读。

    查的是**真的 import 语句**,不是文中提到过这个名字 —— 早一版这里只 grep 字符串
    "RenderPosture",于是把类型改名、注释里还留着旧名字时它照样绿。变异验证出来的。
    """
    # 形如:import type { RenderPosture } from '@/types/phase_contract.gen';
    import_re = re.compile(
        r"import\s+(?:type\s+)?\{[^}]*\bRenderPosture\b[^}]*\}\s*from\s*['\"][^'\"]*phase_contract\.gen['\"]"
    )
    importers: List[str] = []
    for path in PANEL_SRC.rglob("*.ts*"):
        if path.name.endswith(".gen.ts"):
            continue
        if import_re.search(path.read_text(encoding="utf-8")):
            importers.append(str(path.relative_to(PANEL_SRC)))
    assert importers, "没有任何前端文件 import RenderPosture —— 生成的类型又变回没人看的文档了"


def test_the_panel_actually_reads_payload_render():
    """必须真的读 ``payload.render`` —— 后端就挂在那儿。"""
    src = HOOK_TS.read_text(encoding="utf-8")
    assert "render?" in src or "payload?.render" in src, "前端没有读 payload.render"


# ── 3. 骨架就是骨架:不许偷偷改观感 ───────────────────────────────────────────


def test_exposed_contract_hooks_are_not_consumed_by_any_stylesheet():
    """暴露到 DOM 上的那些钩子,**当前不能有任何样式规则消费**。

    这一版是有意只接骨架、不接观感:契约完整到达渲染层是个可以机器验证的事实,
    而"动效好不好看"要人眼确认。两件事分开做,才能说清楚哪一半已经确定。

    这条测试就是那句"面板逐像素不变"的机器判据 —— 将来真要做视觉时它会红,
    那时候删掉它并附上人眼确认的说明,是个显式的决定,而不是悄悄溜进去的改动。
    """
    hooks = ["--rp-", "continuum-", "liminal-understanding", "liminal-thinking", "liminal-rehearsing", "is-returning"]
    offenders = []
    for css in (APP_CSS, TOKENS_CSS):
        if not css.exists():
            continue
        text = css.read_text(encoding="utf-8")
        for hook in hooks:
            if hook in text:
                offenders.append(f"{css.name} 里出现了 {hook}")
    assert not offenders, "骨架被接上观感了(这一版不该有):" + "; ".join(offenders)
