"""策略层与执行层的路由表:**成员必须一致,顺序可以不同**。

被修的问题
----------
同一个决定("这个任务类型该按什么顺序试 provider")在仓库里有**两份真相**:

* ``config/llm_routing_policy.yaml`` 的 ``task_routing.<任务>.priorities``
  —— 策略层。经 ``UnifiedLLMRouter._resolve_provider_order()`` 在
  ``core/unified/llm_router.py:719 → 728`` **真正驱动主对话路径**的调用顺序;
* ``core.multi_llm_router.TASK_ROUTING_PREFERENCES``
  —— 执行层。驱动 ``route()`` 与 ``select_brain_for_task()``(agent 团队选脑那条路)。

两份各自演化,发现时 **8 个任务类型里 7 个不一致**,而且是实质性的:

* ``openrouter`` 在执行层表里(analysis/general),YAML 里**完全没有** ——
  它注册成功、也真配了 key,但**主对话路径永远选不到它**。全局 fallback 链
  ``[anthropic, deepseek, openai, anthropic]`` 也不含它;
* ``meta`` 同样只存在于执行层(6 个任务类型);
* ``xai`` 反方向:只在 YAML 的 reasoning 里,执行层表没有;
* ``coding`` 的顺序实质不同(YAML 把 anthropic 排第 2,执行层排第 4)。

成因很清楚:执行层表的注释写着 ``2026-07-10 新增 meta``、``2026-07-15 接入
openrouter/moonshot``,而 YAML 没跟着改。

为什么守 membership 而不守顺序
------------------------------
所有者的决定:**membership 强一致,顺序各自保留**。理由是两层的取舍本就不同 ——
策略层要考虑成本预算/SLO,执行层要考虑质量档与实测表现,它们对"谁排第二"完全可以有
不同意见。但"某个 provider 在一条路上根本不存在"不是取舍,是漏配:那把 key 白填了,
而且没有任何报错。

所以这里只断言**集合相等**,并明确允许顺序不同(还有一条测试反过来确认顺序确实允许
不同,以免有人把这条误读成"两边必须逐字相同"而去强行对齐)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "config/llm_routing_policy.yaml"


def _policy() -> dict:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


def _yaml_task_routing() -> dict:
    return _policy().get("task_routing") or {}


def _python_prefs() -> dict:
    from core.multi_llm_router import TASK_ROUTING_PREFERENCES

    return {tt.value: list(lst) for tt, lst in TASK_ROUTING_PREFERENCES.items()}


class TestBothTablesExist:
    """先证明两份表都真的在,否则下面的断言可能在空集上空转。"""

    def test_policy_file_parses(self):
        assert _policy(), "策略 YAML 解析为空"

    def test_yaml_has_task_routing(self):
        assert len(_yaml_task_routing()) >= 8

    def test_python_table_is_populated(self):
        assert len(_python_prefs()) >= 8

    def test_same_task_types_on_both_sides(self):
        y, p = set(_yaml_task_routing()), set(_python_prefs())
        assert y == p, f"任务类型本身就不一致: 仅YAML={sorted(y-p)} 仅Python={sorted(p-y)}"


class TestMembershipParity:
    """核心:每个任务类型两侧的 provider **集合**必须相等。"""

    @pytest.mark.parametrize("task", sorted(_yaml_task_routing()))
    def test_membership_matches(self, task):
        y = set(_yaml_task_routing()[task].get("priorities") or [])
        p = set(_python_prefs()[task])
        only_python = sorted(p - y)
        only_yaml = sorted(y - p)
        assert not only_python, (
            f"{task}: {only_python} 只在执行层表里,策略 YAML 没有 —— " "主对话路径永远选不到它们(即使 key 已配置)"
        )
        assert not only_yaml, f"{task}: {only_yaml} 只在策略 YAML 里,执行层表没有 —— " "agent 选脑那条路永远选不到它们"

    def test_no_provider_is_reachable_on_only_one_path(self):
        """全局版本:跨所有任务类型的并集也必须相等。

        逐任务断言已覆盖大部分情形,但这条能抓住"某 provider 在两侧都存在、
        却分别挂在不同任务类型下"这种更隐蔽的漂移。
        """
        y, p = set(), set()
        for task, rule in _yaml_task_routing().items():
            y |= set(rule.get("priorities") or [])
        for lst in _python_prefs().values():
            p |= set(lst)
        assert y == p, f"并集不一致: 仅YAML={sorted(y-p)} 仅Python={sorted(p-y)}"


class TestRegressionsPinnedExplicitly:
    """把发现时的三处实际漂移显式钉住,防止再被改回去。"""

    def test_openrouter_reachable_on_the_main_chat_path(self):
        """最要紧的一条:所有者有 OPENROUTER key,而它此前在主对话路径上不存在。"""
        tr = _yaml_task_routing()
        appears = [t for t, r in tr.items() if "openrouter" in (r.get("priorities") or [])]
        assert appears, "openrouter 在策略 YAML 里又消失了 —— 主对话路径将选不到它"

    def test_meta_present_in_policy(self):
        tr = _yaml_task_routing()
        appears = [t for t, r in tr.items() if "meta" in (r.get("priorities") or [])]
        assert appears, "meta 在策略 YAML 里又消失了"

    def test_xai_present_in_execution_table(self):
        """反方向那一处:xai 原先只在 YAML 的 reasoning 里。"""
        assert "xai" in _python_prefs()["reasoning"]


class TestOrderIsDeliberatelyAllowedToDiffer:
    """反向说明:顺序**允许**不同。

    没有这条,后人可能把上面的 membership 断言误读成"两边必须逐字相同",然后去强行对齐
    顺序 —— 那会抹掉两层各自的取舍(策略层看成本预算/SLO,执行层看质量档与实测表现)。
    """

    def test_orders_do_differ_today_and_that_is_fine(self):
        tr, py = _yaml_task_routing(), _python_prefs()
        differing = [t for t in tr if (tr[t].get("priorities") or []) != py[t]]
        assert differing, "两边顺序完全一致了 —— 若是有意统一,请连带更新本测试的说明"

    def test_local_first_still_holds_on_both_sides(self):
        """顺序可以各异,但有一条共同约束不能破:**本地主脑打头**。

        这是仓库明文的设计(YAML 里写着 LOCAL-FIRST,Python 表注释也写着"每个列表仍以
        本地 ollama 打头")。顺序自由不等于这条也自由。
        """
        tr, py = _yaml_task_routing(), _python_prefs()
        for task in sorted(tr):
            y = tr[task].get("priorities") or []
            assert y and y[0] == "ollama", f"策略 YAML 的 {task} 不再以 ollama 打头: {y[:3]}"
            assert py[task] and py[task][0] == "ollama", f"执行层 {task} 不再以 ollama 打头: {py[task][:3]}"


class TestPolicyLayerIsActuallyWired:
    """守住"策略 YAML 真的驱动主对话路径"这个前提 —— 否则上面所有断言都失去意义。"""

    def test_policy_is_loaded_by_the_unified_router(self):
        import inspect

        from core.unified import llm_router as unified

        src = inspect.getsource(unified)
        assert "_load_routing_policy()" in src
        assert "llm_routing_policy.yaml" in src

    def test_priorities_drive_the_actual_provider_order(self):
        """YAML 的 priorities 必须真的流进调用顺序,而不只是被读出来放着。"""
        import inspect

        from core.unified import llm_router as unified

        src = inspect.getsource(unified)
        assert 'rule.get("priorities"' in src, "策略里的 priorities 没有被读取"
        assert "_resolve_provider_order(" in src
        assert "provider_order" in src, "解析出来的顺序没有被使用"
