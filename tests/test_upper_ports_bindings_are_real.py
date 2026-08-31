"""``core/upper_ports`` —— 绑定表里的每一条都必须指向真实存在的东西。

把 ``from galaxy_gateway.X import Y`` 换成 ``resolve("gateway.X.Y")``,等于把一个
**导入期就会报错**的写法,换成一个**只在跑到那一行才报错**的写法。少了编译期检查,
就得用测试把它补回来 —— 否则一个拼错的端口名可以一直躺到线上。

这里守三件事:

1. **表里每条都解析得出来** —— 模块导得进、属性取得到;
2. **代码里用到的端口都登记过** —— 不许出现表里没有的端口名;
3. **表里没有用不到的条目** —— 死绑定和死代码一样,该删。

另外还守一条边界:``core/`` 里不许再出现上层模块名(否则这次改造会慢慢退回去)。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from core import upper_ports

REPO = Path(__file__).resolve().parent.parent
UPPER_LAYERS = ("galaxy_gateway", "enhancements", "dashboard")


def _core_files():
    for path in sorted((REPO / "core").rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


def _ports_used_in_core() -> dict[str, list[str]]:
    """扫出 ``core/`` 里所有 ``upper_ports.resolve("...")`` 用到的端口名。"""
    used: dict[str, list[str]] = {}
    pattern = re.compile(r'upper_ports\.(?:resolve|is_available)\(\s*"([^"]+)"')
    for path in _core_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            used.setdefault(match.group(1), []).append(str(path.relative_to(REPO)))
    return used


# 本仓当前**确实取不到**的端口,以及原因。写在这里而不是跳过,是为了让它可审;
# 下面 test_the_exemptions_have_not_quietly_started_working 会在它们能取到时发红,
# 免得这份名单烂在这儿。
KNOWN_UNRESOLVABLE = {
    "enhancements.agent_factory.twin_model.CouplingMode": "enhancements/agent_factory/__init__.py 引用了不存在的 dynamic_factory 与 llm_provider,整个包导不进来",
    "enhancements.agent_factory.twin_model.TwinModelManager": "同上",
    "enhancements.agent_factory.twin_model.TwinState": "同上",
    "enhancements.agent_factory.twin_model.twin_manager": "同上",
}


@pytest.mark.parametrize("port", sorted(upper_ports.declared_ports()))
def test_every_declared_port_resolves(port):
    """表里每一条都要真的取得到。

    这条替代的是原先 ``import`` 语句自带的检查 —— 上层把某个符号改名或删掉时,
    以前 import 会立刻炸,现在得靠这条测试来炸。

    注意**不**断言解析结果非 ``None``:有的端口(如 ``gateway.app.websocket_manager``)
    在导入期就是 ``None``,启动时才被赋上。这也正是 :func:`resolve` 每次重新
    ``getattr`` 而不是缓存属性的原因 —— 与 ``from X import Y`` 的语义一致。
    """
    if port in KNOWN_UNRESOLVABLE:
        pytest.skip(f"已知取不到:{KNOWN_UNRESOLVABLE[port]}")
    target = upper_ports.binding_of(port)
    try:
        upper_ports.resolve(port)
    except upper_ports.PortUnavailable as exc:
        pytest.fail(f"端口 '{port}' → '{target}' 解析失败:{exc}")


def test_the_exemptions_have_not_quietly_started_working():
    """豁免名单不许烂掉 —— 哪条能取到了,就该把它从名单里删掉。"""
    fixed = [port for port in KNOWN_UNRESOLVABLE if upper_ports.is_available(port)]
    assert not fixed, "这些端口已经能取到了,请从 KNOWN_UNRESOLVABLE 里删掉:\n" + "\n".join(
        f"  {p}" for p in sorted(fixed)
    )


def test_every_port_used_in_core_is_declared():
    undeclared = {port: files for port, files in _ports_used_in_core().items() if upper_ports.binding_of(port) is None}
    assert not undeclared, "这些端口在 core/ 里用到了但没登记在绑定表里:\n" + "\n".join(
        f"  {port}  ←  {', '.join(files)}" for port, files in sorted(undeclared.items())
    )


def test_no_declared_port_is_unused():
    """表里不许留没人用的条目 —— 死绑定和死代码一样该删。"""
    used = set(_ports_used_in_core())
    orphans = sorted(set(upper_ports.declared_ports()) - used)
    assert not orphans, "绑定表里这些端口没有任何调用方,请删掉:\n" + "\n".join(f"  {p}" for p in orphans)


def test_core_source_no_longer_names_the_upper_layers():
    """回归守卫:``core/`` 里不许再出现 ``galaxy_gateway`` / ``enhancements`` 的 import。

    ``scripts/check_import_boundaries.py --strict`` 也查这个;这里再查一遍,是为了
    让"改回去"在**单测**里就红,而不是等到 CI 那一步。
    """
    offenders = []
    for path in _core_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                head = node.module.split(".")[0]
                if head in UPPER_LAYERS:
                    offenders.append(f"{path.relative_to(REPO)}:{node.lineno}: from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in UPPER_LAYERS:
                        offenders.append(f"{path.relative_to(REPO)}:{node.lineno}: import {alias.name}")
    assert not offenders, "core/ 又直接 import 上层了,请改走 upper_ports:\n" + "\n".join(offenders)


def test_port_unavailable_is_an_import_error():
    """降级分支靠这条继承关系原样生效 —— 断言它,免得哪天有人把基类改了。"""
    assert issubclass(upper_ports.PortUnavailable, ImportError)
    with pytest.raises(ImportError):
        upper_ports.resolve("根本没有这个端口")


def test_register_overrides_the_table():
    """真正的倒置接口:上层(或测试)可以把实现装进来,core 侧代码一个字不改。"""
    port = next(p for p in sorted(upper_ports.declared_ports()) if p not in KNOWN_UNRESOLVABLE)
    sentinel = object()
    upper_ports.register(port, sentinel)
    try:
        assert upper_ports.resolve(port) is sentinel
    finally:
        upper_ports.unregister(port)
    assert upper_ports.resolve(port) is not sentinel, "unregister 之后应当回到绑定表"
