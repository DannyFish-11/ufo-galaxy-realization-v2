"""会话那两条 HTTP 路必须真的 await —— 漏了不会报错，只会静悄悄坏掉。

真跑实测(POST 到真网关,不是 mock):

* ``POST /api/v1/sessions`` 恒 **HTTP 500**
  ``'coroutine' object has no attribute 'to_summary'`` —— 建会话这条路从来没通过;
* ``POST /api/v1/sessions/{id}/join`` 更隐蔽:``ok`` 拿到的是协程对象、**恒为真**,
  于是"会话不存在"的 404 分支永远走不到,接口照样回 ``success: true``,而设备压根
  没加进去。

根因是 ``SessionManager`` 上这几个方法是 async 的(它们要拿 ``self._lock``),而
模块头的用法示例把 await 全漏了 —— 路由就是照着那段抄的。示例写错,抄的人跟着错。

这里钉两件事:**该 await 的都 await 了**,以及**示例里不许再漏 await**。
"""

import ast
import inspect
import re

import core.routes.sessions as sessions_mod
import core.session_manager as sm_mod

#: SessionManager 上必须 await 才有意义的方法。从源码里现取,不手抄一份。
ASYNC_METHODS = {name for name, obj in vars(sm_mod.SessionManager).items() if inspect.iscoroutinefunction(obj)}


def test_there_really_are_async_methods_to_worry_about():
    """自证:这一组不是空的,否则下面几条比的是空气。"""
    assert ASYNC_METHODS, "SessionManager 上一个 async 方法都没有?那这份判据要跟着改"
    assert "create_session" in ASYNC_METHODS and "join_session" in ASYNC_METHODS, ASYNC_METHODS


def _unawaited_calls(module) -> list:
    """找出 ``sm.<async 方法>(...)`` 里没被 await 包住的调用。"""
    tree = ast.parse(inspect.getsource(module))
    awaited = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            awaited.add(id(node.value))

    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in awaited:
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in ASYNC_METHODS:
            continue
        # 只看对 sm 这个 SessionManager 实例的调用；别的对象同名方法不算。
        if isinstance(fn.value, ast.Name) and fn.value.id in {"sm", "self"}:
            bad.append((fn.attr, node.lineno))
    return bad


def test_the_session_routes_await_every_async_call():
    bad = _unawaited_calls(sessions_mod)
    assert not bad, "这些对 SessionManager 的 async 方法的调用漏了 await —— " f"拿到的是协程对象,不是结果: {bad}"


def test_the_usage_example_in_the_module_header_is_not_lying():
    """模块头的示例是别人抄的样板。它漏 await,下游就跟着漏。"""
    doc = sm_mod.__doc__ or ""
    for name in ("get_or_create_session", "add_message"):
        for line in doc.splitlines():
            if re.search(rf"\bsm\.{name}\(", line):
                assert "await" in line, f"示例里 sm.{name}(...) 少了 await: {line.strip()!r}"


def test_the_sync_siblings_are_not_required_to_be_awaited():
    """``*_sync`` 是给同步语境用的,不该被这份判据误伤。"""
    for name in ASYNC_METHODS:
        assert not name.endswith("_sync"), f"{name} 既是 async 又叫 _sync,命名自相矛盾"
