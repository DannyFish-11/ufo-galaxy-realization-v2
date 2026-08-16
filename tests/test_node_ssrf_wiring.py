"""tests/test_node_ssrf_wiring.py — 守卫必须真的接在抓取节点上。

为什么单开一份
--------------
``tests/test_url_guard.py`` 证明的是"守卫本身拦得住"。那不代表**它被用上了** ——
本轮排查里反复出现的正是这种情形:能力实现完整、单测全绿,而生产代码里零个调用方。
一个写好却没接上的 SSRF 守卫,和没有守卫完全一样。

所以这份测试盯的是接线:CodeQL 报过 ``py/full-ssrf`` 的那几个文件里,
构造 HTTP 客户端时用的是 ``guarded_async_client`` 而不是裸 ``httpx.AsyncClient``。

用 AST 而不是字符串:注释里出现 ``httpx.AsyncClient`` 是允许的(那些恰恰是记录
"为什么要换掉它"的地方),只有真正的调用节点才算数。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: CodeQL 的 py/full-ssrf 报到的文件 → 该文件里"用户可控 URL"所在的那些客户端。
#: 值是**该文件里仍然允许存在的裸 httpx.AsyncClient 数量** —— 这些是打固定的
#: 服务商 API(OpenAI / Azure / Discord Bot API …),URL 不由调用方决定,不构成 SSRF。
#: 把它记成数字而不是"随便多少",是为了新增一个裸客户端时有人会被迫回答一句
#: "这个的 URL 是谁给的"。
FLAGGED_FILES = {
    "nodes/Node_08_Fetch/main.py": 0,
    "nodes/Node_105_UnifiedKnowledgeBase/main.py": 1,
    "nodes/Node_119_BenchmarkEval/main.py": 1,
    "nodes/Node_121_Web/main.py": 0,
    "nodes/Node_15_OCR/main.py": 1,
    "nodes/Node_26_Discord/main.py": 1,
    "nodes/Node_76_AlertManager/main.py": 1,
    "nodes/Node_86_SpeechProcessor/main.py": 9,
    "nodes/Node_93_VideoProcessor/main.py": 2,
}


def _call_names(tree: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            out.append(func.attr)
        elif isinstance(func, ast.Name):
            out.append(func.id)
    return out


@pytest.mark.parametrize("rel", sorted(FLAGGED_FILES))
class TestGuardIsWired:
    def test_imports_the_guard(self, rel):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "guarded_async_client" in text, f"{rel} 根本没引用守卫 —— 接线断了"

    def test_uses_the_guarded_factory(self, rel):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        assert "guarded_async_client" in _call_names(tree), f"{rel} 里没有一次 guarded_async_client 调用"

    def test_bare_client_count_matches_the_recorded_budget(self, rel):
        """裸 httpx.AsyncClient 的数量必须与记录一致。

        变多了 = 新加了一个不过守卫的出站点,得说清楚它的 URL 是谁给的;
        变少了 = 又接上了一个,把数字改小即可(那是好事,但也该被看见)。
        """
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        bare = sum(
            1
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "AsyncClient"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "httpx"
        )
        assert bare == FLAGGED_FILES[rel], (
            f"{rel} 有 {bare} 个裸 httpx.AsyncClient,记录的是 {FLAGGED_FILES[rel]}。"
            "新增的那个 URL 由谁提供?调用方给的就得走 guarded_async_client。"
        )


class TestAlertManagerTrustLevels:
    """告警节点的两条分支信任级别不同 —— 这一点必须钉住。"""

    def test_request_supplied_recipient_is_not_trusted(self):
        text = (REPO_ROOT / "nodes/Node_76_AlertManager/main.py").read_text(encoding="utf-8")
        assert "operator_configured=not request.recipient" in text, (
            "请求体给的 recipient 必须按外网对待;环境变量配的才放行内网。" "整个节点统一开或统一关都是错的。"
        )
        assert "allow_internal=operator_configured" in text


class TestGuardModuleIsSelfContained:
    def test_import_does_not_require_httpx(self):
        """守卫的校验部分不该依赖 httpx。

        本仓有节点没装 httpx(靠 HTTPX_AVAILABLE 降级)。若 import 守卫就炸,
        那些节点会连带挂掉 —— 一个"为了安全反而让服务起不来"的守卫会被立刻删掉。
        """
        import importlib
        import sys

        # 重新 import 会造出**新的**模块实例。别的测试文件在导入期就绑定了旧实例
        # 里的函数,而函数查全局是按 __globals__(旧模块字典)查的 —— 不还原的话,
        # 之后任何 monkeypatch.setattr("nodes.common.url_guard.…") 都打在新实例上,
        # 对那些函数一律不生效。test_url_guard 的两条判据"单跑绿、全量红"就是这么来的:
        # 一条以为换掉了 resolved_addresses(实际走了真 DNS),另一条以为换掉了
        # assert_url_allowed(实际守卫一次都没被记录到)。
        # 还原要还两处:sys.modules 那一条,**以及父包上的属性**。
        # ``monkeypatch.setattr("nodes.common.url_guard.x", …)`` 与
        # ``import nodes.common.url_guard as m`` 走的都是 getattr(nodes.common,
        # "url_guard") —— 只还原 sys.modules 的话,父包属性仍指着新实例,补丁全部
        # 打空。少还这一处与完全不还原的结果一模一样。
        original = sys.modules.get("nodes.common.url_guard")
        parent = sys.modules.get("nodes.common")
        sys.modules.pop("nodes.common.url_guard", None)
        try:
            mod = importlib.import_module("nodes.common.url_guard")
            assert hasattr(mod, "assert_url_allowed")
        finally:
            if original is not None:
                sys.modules["nodes.common.url_guard"] = original
                if parent is not None:
                    parent.url_guard = original
        # httpx 只在 guarded_async_client 内部惰性 import
        src = (REPO_ROOT / "nodes/common/url_guard.py").read_text(encoding="utf-8")
        top_level = [ln for ln in src.splitlines() if ln.startswith("import httpx") or ln.startswith("from httpx")]
        assert not top_level, "httpx 不该在模块顶层 import"
