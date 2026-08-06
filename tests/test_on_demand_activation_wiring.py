"""tests/test_on_demand_activation_wiring.py
=============================================

**会算的那个不会做，会做的那个没人叫。**

修复前这条链断在中间
--------------------
「设备插上来就把对应节点拉起来」这件事，两半都写好了::

    设备注册
      → core/unified/device_manager._feed_resolution_plane()      ← 接线了
      → core/udm_registration_hook.on_device_registered()          ← 接线了
          → DeviceNodeResolver.resolve()        算出该起哪个节点  ✓
          → ActivationPolicyEngine.evaluate()   算出 should_start ✓
          → DeviceActivationRegistry.record()   写进审计台账      ✓
          → return                              ← **就到这儿为止**

    launcher/launcher_adapter.LauncherAdapter
      → _maybe_start_node() → node_launcher.start_node()  真的能起  ✓
      → 但 start() / on_device_registered() 两个入口**零生产调用方**

也就是说：决策层完整、执行层完整、**中间那根线不存在**。台账里一条条记着
``should_start=True``，而没有任何一个节点因此被拉起来过。

这份测试钉什么
--------------
1. hook 算出 ``should_start`` 之后**真的会去调**执行器；
2. 执行器炸了不能把设备注册带走 —— 设备已经写进 UDM 了，「拉节点失败」是
   "这台设备暂时没有对应能力"，不是"这台设备没注册上"；
3. ``should_start`` 与 ``activated`` 是**两个**字段。合成一个就再也分不清
   「没登记执行器」和「执行器起失败了」；
4. 方向是 ``launcher → core`` 的单向注册 —— hook 那一侧不许反过来 import
   ``launcher``（范围只到这个文件，理由见对应用例的说明）；
5. ``ActivationDecision`` 没有 ``.decision`` 字段 —— 那个笔误在两个消费方各有一份，
   而且因为 hook 是 fire-and-forget 起的，它炸了**一行日志都没有**。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from core.udm_registration_hook import UDMRegistrationHook

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


class _FakeDevice:
    def __init__(self, device_type="android_phone", transport="usb", device_id="dev-1"):
        self.device_type = device_type
        self.transport = transport
        self.capabilities = []
        self.device_id = device_id


@pytest.fixture()
def hook():
    h = UDMRegistrationHook()
    yield h
    h.set_activation_executor(None)


# ── 1. 决定真的被交出去了 ────────────────────────────────────────────────────


async def test_should_start_actually_reaches_the_executor(hook):
    """这是修复前从未发生过的事:决定算出来之后有人去执行。"""
    calls = []

    async def _exec(*, node_name, decision, device_type, transport):
        calls.append((node_name, decision.should_start, device_type, transport))
        return node_name

    hook.set_activation_executor(_exec)
    result = await hook.on_device_registered(_FakeDevice(), source="test")

    assert result is not None, "android_phone 应该解析得到节点（registry/device_node_map.yaml）"
    assert result["should_start"] is True, f"策略没判成该起:{result}"
    assert calls, "算出了 should_start=True，却没有调用执行器 —— 这正是修复前的状态"
    assert calls[0][0] == result["resolved_node"]
    assert result["activated"] == result["resolved_node"], "起成功了却没记进 activated"


async def test_no_executor_registered_is_not_an_error(hook):
    """没登记执行器时照常返回决定，只是不执行 —— 单跑 core 的场景要能工作。"""
    result = await hook.on_device_registered(_FakeDevice(), source="test")

    assert result is not None
    assert result["should_start"] is True
    assert result["activated"] is None, "没有执行器却报告已激活"


async def test_activated_is_distinct_from_should_start(hook):
    """执行器把它挡下来时(observe_only / allowlist)，两个字段必须能分开。"""

    async def _blocked(*, node_name, decision, device_type, transport):
        return None  # 相当于 observe_only:记账不执行

    hook.set_activation_executor(_blocked)
    result = await hook.on_device_registered(_FakeDevice(), source="test")

    assert result["should_start"] is True, "该起"
    assert result["activated"] is None, "但没起 —— 这两件事必须分得开"


# ── 2. 执行失败不许影响设备注册 ──────────────────────────────────────────────


async def test_executor_failure_does_not_break_registration(hook):
    """设备已经写进 UDM 了。拉节点失败是另一件事，不能把它变成注册失败。"""

    async def _boom(*, node_name, decision, device_type, transport):
        raise RuntimeError("执行器炸了")

    hook.set_activation_executor(_boom)
    result = await hook.on_device_registered(_FakeDevice(), source="test")

    assert result is not None, "执行器异常把整条注册链带走了"
    assert result["should_start"] is True
    assert result["activated"] is None


async def test_unresolved_device_never_touches_the_executor(hook):
    """解析不到节点就不该有激活动作 —— 不然会对着一个不存在的映射瞎起节点。"""
    calls = []

    async def _exec(*, node_name, decision, device_type, transport):
        calls.append(node_name)
        return node_name

    hook.set_activation_executor(_exec)
    result = await hook.on_device_registered(
        _FakeDevice(device_type="没有人认识的设备类型", transport="没有人认识的传输"),
        source="test",
    )

    assert result is None, "认不出的设备不该解析出节点"
    assert not calls, f"解析失败却仍然调用了执行器:{calls}"


# ── 3. 方向:launcher → core 单向注册 ────────────────────────────────────────


def test_the_hook_itself_does_not_import_launcher():
    """决策这一侧不许反过来依赖执行那一侧。

    决策在 ``core/udm_registration_hook.py`` + :mod:`core.activation_policy`，
    执行在 ``launcher/launcher_adapter.py``（它握着 ``NodeSystemLauncher``）。
    接线只能由 launcher **单向注册**进来 —— 这正是
    :meth:`UDMRegistrationHook.set_activation_executor` 存在的理由。直接
    ``from launcher... import`` 会把分层倒过来，也会让 core 单独可用这件事失效。

    **范围刻意只到这个文件。** 全仓意义上 ``core/`` 目前已有两处 import
    ``launcher.node_startup``（``core/node_lifecycle_governor.py``、
    ``core/routes/projection.py``），是本次改动之前就存在的。断言一条仓库并不成立
    的规则只会立刻变红然后被人加豁免；这里只钉住"我接的这条线没有把方向搞反"，
    那是可判定也守得住的。
    """
    py = REPO_ROOT / "core" / "udm_registration_hook.py"
    tree = ast.parse(py.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        mod = None
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mod = node.module
        elif isinstance(node, ast.Import):
            mod = node.names[0].name
        if mod and mod.split(".")[0] == "launcher":
            offenders.append(f"  {py.name}:{node.lineno}  {mod}")

    assert not offenders, "udm_registration_hook 反向依赖了 launcher/:\n" + "\n".join(offenders)


def test_activation_decision_has_no_decision_attribute():
    """``ActivationDecision`` 的字段只有 node / policy / should_start / reason。

    钉这条是因为 ``decision.decision`` 这个笔误同时出现在**两个**消费方
    （``core/udm_registration_hook.py`` 与 ``launcher/launcher_adapter.py``），
    而它们都在 ``record_resolution()`` 之后才执行 —— 台账先写好，任务再炸掉。
    ``on_device_registered`` 又是 ``create_task`` 起的 fire-and-forget，异常从不
    浮出水面。结果就是：**审计台账一条条记着 should_start=True，而下游从来没被
    触发过，也没有一行错误日志。**

    有了这条，将来谁再按 ``.decision`` 写就会立刻红在这里，而不是等到线上
    "设备插上了但节点没起来，日志里什么都没有"。
    """
    import dataclasses

    from core.activation_policy import ActivationDecision

    names = {f.name for f in dataclasses.fields(ActivationDecision)}
    assert names == {"node", "policy", "should_start", "reason"}, f"字段变了:{sorted(names)}"
    assert "decision" not in names


def test_launcher_registers_itself_as_the_executor():
    """``launcher/services.py`` 必须真的把执行器登记进去。

    查的是**真的调用**，不是文中提到过这个名字 —— 这条注释里就会写到
    ``set_activation_executor``，grep 字符串会把说明也当成接线（同一个坑在
    tests/test_node_port_agreement.py 里踩过一次）。
    """
    src = (REPO_ROOT / "launcher" / "services.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "set_activation_executor"
        for n in ast.walk(tree)
    )
    assert found, "launcher/services.py 没有调用 set_activation_executor —— 那条线又断了"


# ── 6. 默认真的会执行 ────────────────────────────────────────────────────────


def test_adapter_default_mode_actually_starts_nodes():
    """默认模式必须是**会动手**的那一档。

    它曾经是 ``observe_only`` —— 分阶段上线的第一档「先记账，别动手」。问题是
    **那一档再也没往前推过**：决策链算得出 should_start、台账一条条记着，执行侧
    一次都没被调用。加上执行入口那时根本没有生产调用方，整套按需激活是死的。

    翻成 ``full`` 的前提是三件事都已成立：决策→执行的线接上了；125 个节点全部
    有档位且默认是 lazy 而不是 always_on；触发时机按档位判定（on_demand 要真实
    设备，不会被一次能力请求拽起来）。所以"会起来的"只有真插了设备的 on_demand
    节点和真被调用到的 lazy 节点 —— **不是 130 个一起起**。
    """
    from launcher.launcher_adapter import AdapterMode, LauncherAdapter

    assert LauncherAdapter.DEFAULT_MODE is AdapterMode.FULL, "默认又回到只记账了，按需激活等于没接"


def test_the_escape_hatch_still_works(monkeypatch):
    """``LAUNCHER_ADAPTER_MODE`` 必须还能把它按回去 —— 出事时要有退路。"""
    from launcher.launcher_adapter import AdapterMode, LauncherAdapter

    monkeypatch.setenv("LAUNCHER_ADAPTER_MODE", "observe_only")
    assert LauncherAdapter(node_launcher=None).mode is AdapterMode.OBSERVE_ONLY

    monkeypatch.setenv("LAUNCHER_ADAPTER_MODE", "dry_run")
    assert LauncherAdapter(node_launcher=None).mode is AdapterMode.DRY_RUN


def test_an_invalid_mode_falls_back_to_the_default_not_to_observe_only(monkeypatch):
    """环境变量写错时退回**默认**，而不是硬编码的 observe_only。

    原来的兜底写死了 ``OBSERVE_ONLY``：默认翻成 full 之后，一个拼错的环境变量
    会把系统静默按回"不执行" —— 而日志只说 "Invalid ...，using observe_only"，
    没人会把"按需激活整个不生效"和"我环境变量拼错了"联系起来。
    """
    from launcher.launcher_adapter import LauncherAdapter

    monkeypatch.setenv("LAUNCHER_ADAPTER_MODE", "这不是一个合法模式")
    assert LauncherAdapter(node_launcher=None).mode is LauncherAdapter.DEFAULT_MODE
