"""桌面脚本是**一个很小的语言**,不是 Python。

为什么这一片份量重
------------------
这条路的本质是"让模型在用户的机器上跑代码"。而且它**必须跑在真实桌面上** ——
隔离到容器里就没意义了,它要点的就是这台机器的屏幕,所以 ``core.safe_executor``
那套容器隔离在这里用不上(那是用来把代码关起来的,和这里的目的相反)。

于是唯一的防线就是这个语言本身:

* 白名单语法(不是黑名单 —— 黑名单永远漏,Python 的语法节点还在加);
* **解释执行,不 exec**。受限命名空间的 ``exec`` 是出了名的能逃:
  ``__builtins__``、属性链、``().__class__.__base__.__subclasses__()`` 那一套。
  解释器不给这些东西存在的机会 —— 属性访问在这里根本不是合法语法;
* 能调的只有桌面动作白名单里那些,每一个照样过坐标换算与派发。

这一片就是钉这三条。逃逸用例照着真实的逃逸手法写,不是随便编几个坏字符串。
"""

from __future__ import annotations

import asyncio

import pytest

from core.desktop_script import (
    MAX_ACTIONS,
    MAX_LOOP_RANGE,
    SCRIPT_API,
    TERMINAL_ACTIONS,
    check_script,
    run_script,
    script_api_prompt,
)


def _run(source, dispatch=None):
    calls = []

    async def default_dispatch(action, params):
        calls.append((action, dict(params)))
        return {"success": True, "error": ""}

    result = asyncio.run(run_script(source, dispatch or default_dispatch))
    return result, calls


# --------------------------------------------------------------------------
# 逃逸:照着真实手法写
# --------------------------------------------------------------------------


class TestItCannotEscape:
    @pytest.mark.parametrize(
        "source,what",
        [
            ("import os", "import"),
            ("from os import system", "from-import"),
            ("os.system('rm -rf /')", "属性调用"),
            ("__import__('os').system('x')", "__import__"),
            ("().__class__.__base__.__subclasses__()", "subclasses 逃逸"),
            ("eval('1+1')", "eval"),
            ("exec('x=1')", "exec"),
            ("open('/etc/passwd')", "open"),
            ("globals()", "globals"),
            ("f = lambda: 1", "lambda"),
            ("def f(): pass", "定义函数"),
            ("class C: pass", "定义类"),
            ("[x for x in range(3)]", "推导式"),
            ("with open('x') as f: pass", "with"),
            ("try:\n    click(1,2)\nexcept: pass", "try"),
            ("global x", "global"),
            ("assert False", "assert"),
            ("del x", "del"),
            ("yield 1", "yield"),
            ("click.__globals__", "属性访问"),
            ("click(1,2); print('x')", "print"),
        ],
    )
    def test_escape_attempts_are_refused(self, source, what):
        check = check_script(source)
        assert not check.ok, f"{what} 被放行了 —— 这条路是在用户机器上跑代码,不能有例外"
        assert check.why, f"{what} 拒了却说不出为什么"

    def test_a_refused_script_executes_nothing(self):
        """先拒绝,再执行 —— 拒了就**一个动作都不做**,不是跑到一半才发现。"""
        result, calls = _run("click(1, 2)\nimport os")
        assert not result.ok
        assert result.executed == 0
        assert calls == []

    def test_the_interpreter_never_uses_exec_or_eval(self):
        """这一条盯的是实现手法本身:改成 exec 就等于把防线拆了。"""
        import inspect
        import re

        import core.desktop_script as m

        code = [ln for ln in inspect.getsource(m).splitlines() if not ln.lstrip().startswith("#") and '"""' not in ln]
        joined = "\n".join(code)
        # 只找**内建**的 exec / eval:前面不能是 "." 或 "_" ——
        # 解释器自己的 ``self._eval`` / ``_exec_stmt`` 是它的方法名,不是那两个内建。
        # (这条断言的第一版就没排除,自己把自己判红了。)
        builtin_calls = re.findall(r"(?<![.\w])(exec|eval)\s*\(", joined)
        assert not builtin_calls, f"用上了内建 {set(builtin_calls)} —— 那等于把防线拆了"

    def test_ast_parse_is_the_only_thing_that_sees_exec_mode(self):
        """``ast.parse(..., mode="exec")`` 只是**解析**成语法树,不执行任何东西。
        这条把它和真的 exec 区分开,免得上一条被人误解成"这里根本不该出现 exec 这个词"。"""
        import inspect

        import core.desktop_script as m

        src = inspect.getsource(m)
        assert 'mode="exec"' in src
        assert "ast.parse" in src

    def test_syntax_allowlist_not_denylist(self):
        """白名单:没登记过的节点类型一律拒。黑名单永远漏。"""
        import core.desktop_script as m

        assert isinstance(m._ALLOWED_NODES, tuple)
        assert m.ast.Import not in m._ALLOWED_NODES
        assert m.ast.Attribute not in m._ALLOWED_NODES


# --------------------------------------------------------------------------
# 循环:必须静态看得出跑多少轮
# --------------------------------------------------------------------------


class TestLoopsAreBounded:
    def test_a_literal_range_is_fine(self):
        result, calls = _run("for i in range(3):\n    click(1, 2)")
        assert result.ok
        assert len(calls) == 3

    def test_while_is_not_a_thing_here(self):
        assert not check_script("while True:\n    click(1,2)").ok

    def test_a_variable_bound_is_refused(self):
        """写成变量就静态看不出会跑多少轮。"""
        check = check_script("n = 5\nfor i in range(n):\n    click(1,2)")
        assert not check.ok
        assert "字面量" in check.why

    def test_too_many_iterations_are_refused(self):
        check = check_script(f"for i in range(  {MAX_LOOP_RANGE + 1}  ):\n    click(1,2)")
        assert not check.ok
        assert str(MAX_LOOP_RANGE) in check.why

    def test_the_loop_variable_is_usable(self):
        result, calls = _run("for i in range(3):\n    click(i * 10, 5)")
        assert result.ok
        assert [p["x"] for _a, p in calls] == [0, 10, 20]

    def test_total_actions_are_capped(self):
        """嵌套循环能绕过单个 range 的上界 —— 所以总数也要有闸。"""
        src = f"for i in range({MAX_LOOP_RANGE}):\n    for j in range({MAX_LOOP_RANGE}):\n        click(1,2)"
        result, calls = _run(src)
        assert not result.ok
        assert str(MAX_ACTIONS) in result.error
        assert len(calls) <= MAX_ACTIONS


# --------------------------------------------------------------------------
# 能调什么 —— 和逐步规划走同一张白名单
# --------------------------------------------------------------------------


class TestTheApiIsTheSameAllowlist:
    def test_every_script_function_maps_to_an_allowed_action(self):
        from core.computer_use_loop import ALLOWED_ACTIONS

        for fn, (action, _args) in SCRIPT_API.items():
            assert action in ALLOWED_ACTIONS, f"{fn}() 映射到 {action},但它不在动作白名单里"

    def test_an_unknown_function_is_refused(self):
        check = check_script("teleport(1, 2)")
        assert not check.ok
        assert "teleport" in check.why

    def test_missing_arguments_are_refused_not_defaulted(self):
        """少参数就不执行 —— 替它补一个默认坐标等于替它决定点哪。"""
        result, calls = _run("click(100)")
        assert not result.ok
        assert "少了参数" in result.error
        assert calls == []

    def test_keyword_arguments_work(self):
        result, calls = _run("click(x=1, y=2)")
        assert result.ok
        assert calls[0][1] == {"x": 1, "y": 2}

    def test_a_script_with_no_action_is_refused(self):
        """全是赋值和循环、一个动作都没有 —— 那不是这条路要的东西。"""
        assert not check_script("n = 1\nfor i in range(2):\n    n = n + 1").ok

    def test_the_prompt_is_generated_from_the_table(self):
        """手写第二份的话,加了新动作却忘改提示词,模型永远不会用它。"""
        prompt = script_api_prompt()
        for fn in SCRIPT_API:
            assert fn in prompt


# --------------------------------------------------------------------------
# 失败与收尾
# --------------------------------------------------------------------------


class TestFailureStopsTheWholeScript:
    def test_one_failed_step_stops_the_rest(self):
        """后面几步是按"前面成功了"写的。接着跑等于在错误的界面状态上继续操作。"""
        calls = []

        async def dispatch(action, params):
            calls.append(action)
            return {"success": False, "error": "越界"}

        result, _ = _run("click(1,2)\nclick(3,4)\nclick(5,6)", dispatch)
        assert not result.ok
        assert len(calls) == 1
        assert "第 1 步" in result.error

    def test_the_failure_says_which_step(self):
        async def dispatch(action, params):
            return {"success": action != "type", "error": "输入法挡住了"}

        result, _ = _run("click(1,2)\ntype_text('hi')\nclick(3,4)", dispatch)
        assert "第 2 步" in result.error
        assert "输入法挡住了" in result.error

    def test_a_node_that_says_nothing_still_gets_reported(self):
        async def dispatch(action, params):
            return {"success": False}

        result, _ = _run("click(1,2)", dispatch)
        assert not result.ok
        assert result.error


class TestTerminating:
    @pytest.mark.parametrize("word", sorted(TERMINAL_ACTIONS))
    def test_the_script_can_end_itself(self, word):
        result, _ = _run(f"click(1,2)\n{word}()")
        assert result.terminal == word
        assert result.ok, "收尾是正常结束,不是错误"

    def test_nothing_after_the_terminal_runs(self):
        result, calls = _run("click(1,2)\ndone()\nclick(3,4)")
        assert result.terminal == "done"
        assert len(calls) == 1

    def test_finishing_without_a_terminal_is_not_a_failure(self):
        """跑完这一段但没收尾 = "这段做完了,任务还没完",不是失败。
        混起来会让上层把没跑完的当成做不到。"""
        result, _ = _run("click(1,2)")
        assert result.ok
        assert result.terminal == ""


class TestItRecordsWhatItDid:
    def test_every_action_is_recorded(self):
        result, _ = _run("click(1,2)\ntype_text('hi')")
        assert [a["action"] for a in result.actions] == ["click", "type"]

    def test_the_count_matches(self):
        result, calls = _run("for i in range(4):\n    click(1,2)")
        assert result.executed == len(calls) == 4

    def test_actions_up_to_the_failure_are_kept(self):
        """失败时前面做过的必须留着 —— 界面已经被改了,记录里没有等于查不了。"""
        state = {"n": 0}

        async def dispatch(action, params):
            state["n"] += 1
            return {"success": state["n"] < 3, "error": "到此为止"}

        result, _ = _run("click(1,2)\nclick(3,4)\nclick(5,6)", dispatch)
        assert not result.ok
        assert len(result.actions) == 3
