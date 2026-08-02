"""
文档快捷键与实际注册值的一致性门（B21）
=====================================

审查发现的真实症状：``docs/CLONE_TO_USE_DESKTOP.md`` 与
``docs/OFFICIAL_DOCUMENTATION.md`` 长期写着 ``Ctrl+Space`` 唤醒覆盖层，而
``electron/main.js`` 里那段注释白纸黑字写着：

    之前没有任何唤醒快捷键被真正注册（启动横幅写的 Ctrl+Space 是假的），而且
    Ctrl+Space 在中文 Windows 会被输入法抢去切换中英文 → 用户「按不开」。

也就是说：**照文档按永远唤不出覆盖层**。这类漂移靠人工 review 抓不住，
只能用门挡住。

本测试做两件事：

1. 从 ``electron/main.js`` 解析出真实注册的 ``WAKE_SHORTCUTS`` / ``HIDE_SHORTCUTS``；
2. 断言文档里出现的快捷键都在这个集合内，且不再出现裸 ``Ctrl+Space``。

只读 ``electron/main.js``、不修改它 —— 解析用正则而非执行 JS，因此不需要 node。
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ELECTRON_MAIN = PROJECT_ROOT / "electron" / "main.js"

# 检查这些文档里的唤醒/隐藏快捷键描述
DOCS_TO_CHECK = (
    PROJECT_ROOT / "docs" / "CLONE_TO_USE_DESKTOP.md",
    PROJECT_ROOT / "docs" / "OFFICIAL_DOCUMENTATION.md",
)

# 文档里用 Ctrl 书写，代码里是 Electron 的 CommandOrControl（跨平台别名）
_ACCEL_ALIAS = {"commandorcontrol": "ctrl", "cmdorctrl": "ctrl", "command": "ctrl", "cmd": "ctrl"}


def _normalize(accel: str) -> str:
    """把加速键字符串归一：小写、去空格、CommandOrControl→Ctrl、修饰键排序。"""
    parts = [p.strip().lower() for p in accel.split("+") if p.strip()]
    parts = [_ACCEL_ALIAS.get(p, p) for p in parts]
    if not parts:
        return ""
    *mods, key = parts
    return "+".join(sorted(mods) + [key])


def _is_explanatory(line: str) -> bool:
    """判断某行是"解释"而非"操作指引"。

    判据是 Markdown 引用块（``>`` 开头）—— 本仓的约定是把"为什么不是 X"这类
    背景说明放进引用块，给用户照做的指引写在正文/表格里。用结构信号而不是
    关键词匹配，因为解释往往跨多行，逐行找否定词会漏掉续行
    （本测试第一版就是这么漏的）。
    """
    return line.lstrip().startswith(">")


def _extract_js_array(source: str, name: str) -> list[str]:
    """从 JS 源码里抠出 ``const <name> = [ '...', '...' ];`` 的字符串字面量。"""
    m = re.search(rf"const\s+{re.escape(name)}\s*=\s*\[(.*?)\]", source, re.DOTALL)
    if not m:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))


@pytest.fixture(scope="module")
def registered_accelerators() -> set[str]:
    if not ELECTRON_MAIN.is_file():
        pytest.skip("electron/main.js 不存在")
    source = ELECTRON_MAIN.read_text(encoding="utf-8", errors="replace")
    wake = _extract_js_array(source, "WAKE_SHORTCUTS")
    hide = _extract_js_array(source, "HIDE_SHORTCUTS")
    if not wake:
        pytest.skip("未能从 electron/main.js 解析出 WAKE_SHORTCUTS（该常量可能已改名）")
    return {_normalize(a) for a in (*wake, *hide)}


def test_wake_shortcuts_are_declared_in_code(registered_accelerators):
    """前置条件：确实解析到了一组注册值，否则后面的断言都是空转。"""
    assert registered_accelerators, "WAKE_SHORTCUTS/HIDE_SHORTCUTS 解析结果为空"
    # 主唤醒键必须在其中 —— 文档以它为准
    assert _normalize("Ctrl+Alt+Space") in registered_accelerators


def test_docs_do_not_advertise_bare_ctrl_space():
    """文档不得再出现裸 ``Ctrl+Space`` 作为唤醒键。

    允许在"为什么不是 Ctrl+Space"这类解释里提到它 —— 判据见 :func:`_is_explanatory`
    （Markdown 引用块视为解释，正文/表格视为指引）。
    """
    offenders: list[str] = []
    for doc in DOCS_TO_CHECK:
        if not doc.is_file():
            continue
        for lineno, line in enumerate(doc.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _is_explanatory(line):
                continue
            # 去掉合法的组合键后，再看还有没有孤立的 Ctrl+Space
            stripped = line.replace("Ctrl+Alt+Space", "").replace("Ctrl+Shift+Space", "")
            if "Ctrl+Space" not in stripped:
                continue
            offenders.append(f"{doc.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()}")

    assert not offenders, "文档仍把 Ctrl+Space 当作唤醒键（该键从未被注册）:\n" + "\n".join(offenders)


def test_documented_shortcuts_are_all_actually_registered(registered_accelerators):
    """文档中出现的每个 Ctrl 组合键都必须真的注册过。

    只校验唤醒/隐藏这类全局加速键；F12 / Esc 是窗口级绑定，不在 WAKE/HIDE 里，
    因此排除掉。
    """
    window_level = {_normalize(x) for x in ("F12", "F10", "Esc", "Escape")}
    pattern = re.compile(r"\bCtrl\+(?:[A-Za-z]+\+)*[A-Za-z0-9]+\b")

    offenders: list[str] = []
    for doc in DOCS_TO_CHECK:
        if not doc.is_file():
            continue
        for lineno, line in enumerate(doc.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _is_explanatory(line):
                continue  # 解释性说明（blockquote），不是给用户的操作指引
            for accel in pattern.findall(line):
                norm = _normalize(accel)
                if norm in window_level or norm in registered_accelerators:
                    continue
                offenders.append(f"{doc.relative_to(PROJECT_ROOT)}:{lineno}: {accel}")

    assert (
        not offenders
    ), "文档写了未注册的快捷键（以 electron/main.js 的 WAKE_SHORTCUTS/HIDE_SHORTCUTS 为准）:\n" + "\n".join(offenders)
