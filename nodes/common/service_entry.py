"""nodes/common/service_entry.py —— 「服务对象」型节点入口的共用部分:按动作名调服务上的方法、照实说有哪些动作。

Node_121_Web / Node_122_Shell / Node_27_SmartHome / Node_70_AutonomousLearning / Node_71_MultiDeviceCoordination
的 ``fusion_entry.py`` 是同一个模板生成的:``execute(action, params)`` 在服务对象上找同名方法,``method(**params)``。
第 10 轮(节点开放给模型之前)查出两处不实:

* 这些服务的方法多半收**一个** pydantic 请求对象(``ShellService.execute(request: ExecuteRequest)``),
  ``execute(command="ls")`` 一调就是 ``unexpected keyword argument`` —— 命令行、网页请求两个节点在进程内从没调通过;
* ``help`` 回的动作表是模板里写死的(网页节点说有 ``api_call``,服务上根本没有),不是这个节点真有的。

这里两件事:参数是一个请求模型的,就用参数把模型建出来再调(:func:`call`);动作表从服务对象上照实列(:func:`actions`)。
"""

from __future__ import annotations

import inspect
import typing
from typing import Any, Callable, Dict, List, Optional, Tuple

#: 模板入口在精确同名之外还认的前缀(与模板一致)
PREFIXES: Tuple[str, ...] = ("do_", "handle_", "process_", "run_", "perform_")


def _is_model(tp: Any) -> bool:
    return inspect.isclass(tp) and hasattr(tp, "model_fields")


def _hints(method: Callable) -> Dict[str, Any]:
    try:
        return typing.get_type_hints(method)
    except Exception:  # noqa: BLE001 — 注解解析不出来(前向引用缺名字):当作没有注解
        return {}


def _params(method: Callable) -> List[inspect.Parameter]:
    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        return []
    return [p for p in sig.parameters.values() if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]


def request_model(method: Callable) -> Optional[Tuple[str, Any]]:
    """方法只收一个 pydantic 请求对象 → (参数名, 模型类);否则 ``None``。"""
    params = _params(method)
    if len(params) != 1:
        return None
    hint = _hints(method).get(params[0].name)
    return (params[0].name, hint) if _is_model(hint) else None


def resolve(service: Any, action: str) -> Optional[Callable]:
    """动作名 → 服务上的方法(先精确同名,再带模板认的前缀);没有就是 ``None``。"""
    name = str(action or "").replace("-", "_")
    if name.startswith("_"):
        return None
    for candidate in (name, *(p + name for p in PREFIXES)):
        method = getattr(service, candidate, None)
        if callable(method):
            return method
    return None


def call(method: Callable, params: Dict[str, Any], run_coro: Callable[[Any], Any]) -> Any:
    """按方法自己的签名调它:只收一个请求模型的,用参数把模型建出来(参数本来就包好了也认)。"""
    params = dict(params or {})
    model = request_model(method)
    if model is not None:
        name, cls = model
        raw = params.pop(name) if set(params) == {name} and isinstance(params.get(name), dict) else params
        result = method(cls(**raw))
    else:
        result = method(**params)
    return run_coro(result) if inspect.isawaitable(result) else result


def type_text(tp: Any) -> str:
    if tp is inspect.Parameter.empty or tp is None:
        return ""
    if typing.get_origin(tp) is not None:  # Optional[str] / List[dict] …… 照写全
        return str(tp).replace("typing.", "")
    return getattr(tp, "__name__", None) or str(tp).replace("typing.", "")


def model_params(cls: Any) -> List[Dict[str, Any]]:
    """一个 pydantic 请求模型的字段 → 参数表(名字、类型、必填)。"""
    return [
        {"name": field.alias or name, "type": type_text(field.annotation), "required": field.is_required()}
        for name, field in cls.model_fields.items()
    ]


def param(name: str, type_: str = "str", required: bool = False, note: str = "") -> Dict[str, Any]:
    """手写的一条参数说明(入口自己从 ``params`` 里取值、没有请求模型时用)。"""
    out: Dict[str, Any] = {"name": name, "type": type_, "required": required}
    if note:
        out["note"] = note
    return out


def describe(method: Callable) -> Dict[str, Any]:
    """一个动作的说明与参数(名字、类型、必填)—— 参数是请求模型的,列模型的字段。"""
    doc = (inspect.getdoc(method) or "").strip().splitlines()
    params: List[Dict[str, Any]] = []
    model = request_model(method)
    if model is not None:
        params = model_params(model[1])
    else:
        hints = _hints(method)
        for p in _params(method):
            params.append(
                {
                    "name": p.name,
                    "type": type_text(hints.get(p.name, p.annotation)),
                    "required": p.default is inspect.Parameter.empty,
                }
            )
    return {"summary": doc[0] if doc else "", "params": params}


def actions(service: Any) -> Dict[str, Dict[str, Any]]:
    """服务对象上真有的动作(公开的方法)及其说明与参数。"""
    out: Dict[str, Dict[str, Any]] = {}
    for name in sorted(dir(service)):
        if name.startswith("_"):
            continue
        method = getattr(service, name, None)
        if callable(method) and not inspect.isclass(method):
            out[name] = describe(method)
    return out


__all__ = ["PREFIXES", "actions", "call", "describe", "model_params", "param", "request_model", "resolve", "type_text"]
