"""桌面节点的错误:说清楚是什么失败,但不把内部细节送出网。

这是同一类问题的第三轮
----------------------
第一轮修的是"装了却说没装",第二轮 CodeQL 报 ``py/stack-trace-exposure``,
在 ``drag`` 上单独修了一处。第三轮(本片)是我新加六个端点时又原样写了
``return {"success": False, "error": str(e)}`` —— CodeQL 一次报了六条。

逐个端点修就是修一个漏一堆,所以收成一处 ``_safe_error``,并用这一片钉住:
**任何端点都不许把 str(e) 回给调用方**。下次再有人手写一个,这里当场红。

为什么不干脆回一句"失败了"
--------------------------
computer use 闭环是靠这句话决定下一步怎么走的。含糊的错误会让模型原样重试
一遍,白烧一步预算。所以带上**异常类名** —— ``ValueError`` 跟 ``OSError``
指向的下一步完全不同 —— 而内容留在日志里。
"""

from __future__ import annotations

import re

import pytest

NODE = "nodes/Node_45_DesktopAuto/main.py"


@pytest.fixture(scope="module")
def src() -> str:
    return open(NODE, encoding="utf-8").read()


def _code_lines(src: str):
    """只看代码行 —— 注释和文档串里出现 ``str(e)`` 是在**说明**这件事,不是在犯它。"""
    return [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]


class TestNoRawExceptionReachesTheCaller:
    def test_no_endpoint_returns_str_of_the_exception(self, src):
        offenders = [ln.strip() for ln in _code_lines(src) if re.search(r'"error":\s*str\(e', ln)]
        assert not offenders, f"这些地方会把异常原文送出网: {offenders}"

    def test_no_endpoint_returns_a_traceback(self, src):
        offenders = [ln.strip() for ln in _code_lines(src) if "format_exc" in ln or "print_exc" in ln]
        assert not offenders, f"栈信息不能出网: {offenders}"

    def test_there_is_one_place_that_owns_this(self, src):
        """一处权威。散着写就是修一个漏一堆 —— 前两轮就是这么漏的。"""
        assert "def _safe_error(" in src

    def test_every_handler_goes_through_it(self, src):
        """``except Exception`` 的分支要么走 _safe_error,要么自己给一句安全的话。"""
        assert src.count('_safe_error("') >= 15


class TestTheErrorStillSaysSomethingUseful:
    def test_it_carries_the_exception_class_name(self, src):
        """光说"失败了"会让模型原样重试。类名指向不同的下一步。"""
        body = src[src.index("def _safe_error(") : src.index("def _safe_error(") + 1200]
        assert "type(exc).__name__" in body

    def test_it_does_not_carry_the_exception_message(self, src):
        body = src[src.index("def _safe_error(") : src.index("def _safe_error(") + 1200]
        assert "str(exc)" not in body

    def test_it_names_which_action_failed(self, src):
        body = src[src.index("def _safe_error(") : src.index("def _safe_error(") + 1200]
        assert "action" in body

    def test_the_full_detail_goes_to_the_log(self, src):
        """出网的少了,日志里就必须有 —— 否则这个错就彻底查不了了。"""
        body = src[src.index("def _safe_error(") : src.index("def _safe_error(") + 1200]
        assert "logger.exception" in body

    def test_it_points_at_where_to_look(self, src):
        body = src[src.index("def _safe_error(") : src.index("def _safe_error(") + 1200]
        assert "日志" in body


class TestItActuallyBehavesThatWay:
    """看源码还不够 —— 真调一次,看回出去的到底是什么。"""

    @staticmethod
    def _safe_error():
        import importlib.util

        spec = importlib.util.spec_from_file_location("_n45_probe", NODE)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:  # pragma: no cover - 环境缺依赖时跳过
            pytest.skip(f"节点模块导入不了(缺依赖): {exc}")
        return mod._safe_error

    def test_the_secret_in_the_message_does_not_come_back(self):
        fn = self._safe_error()
        out = fn("click", ValueError("/home/someone/.env 里的口令是 hunter2"))
        assert "hunter2" not in out["error"]
        assert "/home/someone" not in out["error"]

    def test_the_class_name_does_come_back(self):
        fn = self._safe_error()
        assert "ValueError" in fn("click", ValueError("x"))["error"]

    def test_the_action_name_comes_back(self):
        fn = self._safe_error()
        assert "middle_click" in fn("middle_click", OSError("x"))["error"]

    def test_it_reports_failure(self):
        fn = self._safe_error()
        assert fn("click", OSError("x"))["success"] is False

    def test_different_exception_kinds_read_differently(self):
        """模型要能据此改变下一步,所以两类错不能长得一样。"""
        fn = self._safe_error()
        assert fn("click", ValueError("x"))["error"] != fn("click", OSError("x"))["error"]
