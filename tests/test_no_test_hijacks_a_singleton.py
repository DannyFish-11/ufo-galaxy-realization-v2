"""测试不得用 ``Cls.__new__(Cls)`` 去"造一个新实例" —— 单例类会把真身交给你。

被修的问题
----------
仓库里有一批类用 ``__new__`` 实现进程级单例::

    class UnifiedLLMRouter:
        _instance: Optional["UnifiedLLMRouter"] = None

        def __new__(cls) -> "UnifiedLLMRouter":
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

于是 ``UnifiedLLMRouter.__new__(UnifiedLLMRouter)`` **返回的是那个单例本身**,不是新
对象。测试里这么写通常带着"绕开 ``__init__`` 的后端加载/网络探测,造一个只挂了必要桩
的实例"的注释 —— 意图是对的,手段拿错了:接下来给它挂的每一个桩,都**永久改写了整个
进程的单例**,而且从不还原。

实测到的两处真实后果(都在 CI 的 `test` 作业里红过):

* ``tests/test_llm_tools_failover.py`` 给单例挂上 ``_FakeTelemetry`` 与桩掉的
  ``_get_provider_order``。此后 ``GET /api/v1/operator/llm`` 走到
  ``UnifiedLLMRouter.get_status()`` 里的 ``self._telemetry.get_metrics()``,
  ``_FakeTelemetry`` 没有这个方法 → 500。三条 operator 用例一起红,而它们自己毫无问题;
* ``UnifiedConfig`` 同款:``cfg = UnifiedConfig.__new__(UnifiedConfig)`` 拿到真单例后
  一句 ``cfg._config = {}`` 就把**真实配置整个清空**,再灌进一套假 API Key。此后
  ``_get_key()`` 第 1 层查到的全是假值,别的文件里"占位符不该被当成真密钥"之类的断言
  随之假红(单跑绿、合并跑红)。

正确写法是 ``object.__new__(Cls)`` —— 它跳过类自己的 ``__new__``,给出一个货真价实的
新实例,既避开了 ``__init__``,又碰不到 ``_instance``。

为什么要有这条测试
------------------
这类污染的症状**永远出现在别人身上**:报错的是 operator/panel 的用例,根因却在一个
名字毫不相干的文件里,而且单跑一律全绿。排查成本极高。与其等下一次再花几小时,不如
在写下的那一刻就拦住。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

#: 扫这些目录找单例类定义。
_SOURCE_DIRS = ("core", "galaxy_gateway", "enhancements", "contracts")


def _singleton_classes() -> Dict[str, str]:
    """返回 ``{类名: 定义它的文件}``,只收「自定义 ``__new__`` 且缓存实例」的类。

    判据刻意保守:必须**自己**定义了 ``__new__``,且函数体里出现 ``_instance`` /
    ``_singleton``。这样不会把普通类误伤成单例。
    """
    found: Dict[str, str] = {}
    paths: List[Path] = [p for d in _SOURCE_DIRS for p in (REPO_ROOT / d).rglob("*.py")]
    paths += list(REPO_ROOT.glob("*.py"))
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__new__":
                    body = ast.unparse(item)
                    if "_instance" in body or "_singleton" in body:
                        found.setdefault(node.name, str(path.relative_to(REPO_ROOT)))
    return found


#: ``X.__new__(`` 或 ``mod.X.__new__(``,但不含 ``object.__new__(``(那正是正确写法)。
_NEW_CALL = re.compile(r"(?<![\w.])(?:\w+\.)?([A-Z]\w*)\.__new__\(")


def _offending_sites() -> List[Tuple[str, int, str]]:
    singles = _singleton_classes()
    hits: List[Tuple[str, int, str]] = []
    for path in TESTS_DIR.rglob("*.py"):
        if path.name == Path(__file__).name:
            continue  # 本文件自己会提到这些名字
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in _NEW_CALL.finditer(text):
            cls = m.group(1)
            if cls in singles:
                line = text[: m.start()].count("\n") + 1
                hits.append((str(path.relative_to(REPO_ROOT)), line, cls))
    return hits


class TestNoSingletonHijack:
    def test_detector_actually_finds_the_known_singletons(self):
        """先证明探测器本身有效 —— 否则下面那条可以靠"什么都没找到"轻松通过。"""
        singles = _singleton_classes()
        for expected in ("UnifiedLLMRouter", "UnifiedConfig", "RoutingTelemetry"):
            assert expected in singles, f"探测器没认出已知的单例类 {expected!r},它的判据已经失效"

    def test_detector_recognises_the_offending_pattern(self):
        """再证明匹配规则确实抓得住那个写法,且**不会**误伤正确写法。"""
        assert _NEW_CALL.search("r = UnifiedLLMRouter.__new__(UnifiedLLMRouter)")
        assert _NEW_CALL.search("cfg = uc.UnifiedConfig.__new__(uc.UnifiedConfig)")
        assert not _NEW_CALL.search("r = object.__new__(UnifiedLLMRouter)"), "正确写法被误判成违规"

    def test_no_test_bypasses_a_singleton_new(self):
        sites = _offending_sites()
        assert (
            not sites
        ), "这些测试用 Cls.__new__(Cls) 拿到的是**进程级单例本身**,给它挂的桩会污染整个测试会话;" "改用 object.__new__(Cls):\n" + "\n".join(
            f"    {p}:{ln}  ->  {cls}.__new__({cls})" for p, ln, cls in sites
        )
