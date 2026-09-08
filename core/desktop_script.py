"""桌面脚本 —— 模型写一小段程序,我们**解释**它,而不是 exec 它。

为什么要有这条路
----------------
逐步规划(每一步问一次模型)在"打开设置 → 翻到第三节 → 逐个勾选七个开关"这类
任务上很浪费:七次往返、七张截图,而这七步之间根本没有需要重新判断的东西。
上游(OpenAI 对 GPT-6 Astra)现在也推荐让模型写脚本、由调用方执行,而不是一次
只给一个动作。

为什么**不是** exec
-------------------
"让模型写 PyAutoGUI 脚本然后跑起来"等于把一个 shell 交给模型 ——
``import os; os.system(...)`` 一行就出去了。而且这段代码必须跑在**真实桌面**上
(隔离到容器里就没意义了,它要点的就是这台机器的屏幕),所以 ``core.safe_executor``
那套容器隔离在这里用不上 —— 那是用来把代码**关起来**的,和这里的目的相反。

所以这里是一个**很小的语言**,不是 Python:

* 先用 AST 校验一遍,只放行白名单里的语法节点;
* 然后**解释**校验过的 AST,不调用 ``exec`` / ``eval``。
  受限命名空间的 ``exec`` 是出了名的能逃(``__builtins__``、属性链、
  ``__subclasses__`` 那一套),解释器不给这些东西存在的机会 ——
  属性访问、import、lambda、推导式在这里根本不是合法语法。
* 能调的函数只有**本仓已有的桌面动作**(和逐步规划走的是同一张白名单),
  每一次调用照样过坐标换算与派发那条路。

能写什么
--------
::

    click(100, 200)
    type_text("hello")
    for i in range(3):
        press_key("Tab")
    wait(0.5)

不能写:import、属性访问(``os.system``)、lambda、推导式、赋值给非简单名字、
while(没有静态上界)、函数定义、try、with、global。**认不出的语法一律拒绝整段**,
不是跳过那一行 —— 跳过一行会让后面几步作用在错误的界面状态上。
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ComputerUse.Script")

#: 一段脚本最多执行多少次动作。防的是 ``for i in range(100000)`` 这种 ——
#: 语法完全合法,但会把机器点疯。超了就停,并如实说停在第几步。
MAX_ACTIONS = 40

#: 循环的上界必须是**字面量**且不超过这个数。写成变量的话静态看不出会跑多少轮。
MAX_LOOP_RANGE = 40

#: 脚本里能调的函数 → 规范动作名 + 位置参数的名字。
#:
#: 这张表是**给模型看的 API**,也是执行侧的白名单,一处两用 ——
#: 分成两处的话,提示词里写着能用的函数会有执行侧不认的。
SCRIPT_API: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "click": ("click", ("x", "y")),
    "double_click": ("double_click", ("x", "y")),
    "right_click": ("right_click", ("x", "y")),
    "middle_click": ("middle_click", ("x", "y")),
    "triple_click": ("triple_click", ("x", "y")),
    "move": ("move", ("x", "y")),
    "drag": ("drag", ("from_x", "from_y", "to_x", "to_y")),
    "type_text": ("type", ("text",)),
    "press_key": ("press_key", ("key",)),
    "hotkey": ("hotkey", ("keys",)),
    "scroll": ("scroll", ("clicks",)),
    "wait": ("wait", ("seconds",)),
    # 收尾。参数可省 —— 模型写 done() 就够了,逼它想一句话反而容易改成别的东西。
    "done": ("done", ()),
    "fail": ("fail", ()),
}

#: 终止动作。执行到它就整段结束,后面即便还有语句也不再跑。
TERMINAL_ACTIONS = frozenset({"done", "fail"})

#: 允许的语句/表达式节点。**白名单**,不是黑名单 ——
#: 黑名单永远漏,Python 的语法节点还在不断加。
_ALLOWED_NODES = (
    ast.Module,
    ast.Expr,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.Assign,
    ast.For,
    ast.If,
    ast.Compare,
    ast.BinOp,
    ast.UnaryOp,
    ast.List,
    ast.Tuple,
    ast.keyword,
    # 运算符与比较符
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.FloorDiv,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)

_ALLOWED_BARE_CALLS = frozenset(SCRIPT_API) | {"range"}


@dataclass
class ScriptCheck:
    """一段脚本的校验结果。``ok`` 为假时 ``why`` 一定说得出为什么。"""

    ok: bool
    why: str = ""
    calls: List[str] = field(default_factory=list)


def check_script(source: str) -> ScriptCheck:
    """静态校验。**先拒绝,再执行** —— 拒了就一个动作都不做。"""
    if not (source or "").strip():
        return ScriptCheck(False, "脚本是空的")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        return ScriptCheck(False, f"语法不对: {exc.msg}(第 {exc.lineno} 行)")

    calls: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return ScriptCheck(False, f"这里不允许 {type(node).__name__} —— 这套脚本不是完整的 Python")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                # 属性调用(os.system / obj.method)在这里根本不该出现。
                return ScriptCheck(False, "不允许属性调用(只能直接调白名单里的函数)")
            if node.func.id not in _ALLOWED_BARE_CALLS:
                return ScriptCheck(False, f"不认识的函数: {node.func.id}()")
            calls.append(node.func.id)
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                return ScriptCheck(False, "只能赋值给一个简单变量名")
        if isinstance(node, ast.For):
            why = _check_loop(node)
            if why:
                return ScriptCheck(False, why)
    action_calls = [c for c in calls if c in SCRIPT_API]
    if not action_calls:
        return ScriptCheck(False, "这段脚本一个动作都没有")
    return ScriptCheck(True, "", calls)


def _check_loop(node: ast.For) -> str:
    """循环必须**静态看得出跑多少轮**。看不出就不放行。"""
    if not isinstance(node.target, ast.Name):
        return "循环变量只能是一个简单名字"
    it = node.iter
    if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"):
        return "只能 for ... in range(N)"
    if not it.args or len(it.args) > 2:
        return "range() 只接受 1 到 2 个参数"
    for arg in it.args:
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, int)):
            return "range() 的边界必须是整数字面量(写成变量就静态看不出会跑多少轮)"
    span = it.args[0].value if len(it.args) == 1 else it.args[1].value - it.args[0].value
    if span > MAX_LOOP_RANGE:
        return f"循环上界 {span} 超过 {MAX_LOOP_RANGE}"
    if span < 0:
        return "循环上界比下界小,这段循环一次都不会跑"
    return ""


@dataclass
class ScriptRun:
    """一次执行的完整记录。"""

    ok: bool
    executed: int = 0
    error: str = ""
    actions: List[Dict[str, Any]] = field(default_factory=list)
    #: 脚本自己收尾时是 ``"done"`` / ``"fail"``;没收尾就是空串。
    #: 空串和 ``"fail"`` 不是一回事 —— 前者是"这一段跑完了,任务还没完",
    #: 后者是模型说"做不到"。混起来会让上层把没跑完的当成失败。
    terminal: str = ""


class _Interpreter:
    """解释校验过的 AST。**没有 exec,也没有 eval。**"""

    def __init__(self, dispatch: Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]):
        self._dispatch = dispatch
        self._vars: Dict[str, Any] = {}
        self.actions: List[Dict[str, Any]] = []
        self.executed = 0
        self.terminal = ""

    async def run(self, tree: ast.Module) -> Optional[str]:
        """跑完返回 ``None``;中途停下返回原因。"""
        return await self._exec_body(tree.body)

    async def _exec_body(self, body: List[ast.stmt]) -> Optional[str]:
        for stmt in body:
            why = await self._exec_stmt(stmt)
            if why is not None:
                return why
        return None

    async def _exec_stmt(self, stmt: ast.stmt) -> Optional[str]:
        if isinstance(stmt, ast.Expr):
            _value, why = await self._eval(stmt.value)
            return why
        if isinstance(stmt, ast.Assign):
            value, why = await self._eval(stmt.value)
            if why:
                return why
            self._vars[stmt.targets[0].id] = value
            return None
        if isinstance(stmt, ast.For):
            start, stop = self._loop_bounds(stmt)
            for i in range(start, stop):
                self._vars[stmt.target.id] = i
                why = await self._exec_body(stmt.body)
                if why is not None:
                    return why
            return None
        if isinstance(stmt, ast.If):
            cond, why = await self._eval(stmt.test)
            if why:
                return why
            return await self._exec_body(stmt.body if cond else stmt.orelse)
        return f"执行不了这种语句: {type(stmt).__name__}"

    @staticmethod
    def _loop_bounds(stmt: ast.For) -> Tuple[int, int]:
        args = stmt.iter.args
        return (0, args[0].value) if len(args) == 1 else (args[0].value, args[1].value)

    async def _eval(self, node: ast.expr) -> Tuple[Any, Optional[str]]:
        if isinstance(node, ast.Constant):
            return node.value, None
        if isinstance(node, ast.Name):
            if node.id not in self._vars:
                return None, f"用了没赋值过的变量: {node.id}"
            return self._vars[node.id], None
        if isinstance(node, (ast.List, ast.Tuple)):
            out = []
            for item in node.elts:
                value, why = await self._eval(item)
                if why:
                    return None, why
                out.append(value)
            return out, None
        if isinstance(node, ast.UnaryOp):
            value, why = await self._eval(node.operand)
            if why:
                return None, why
            return (-value if isinstance(node.op, ast.USub) else +value), None
        if isinstance(node, ast.BinOp):
            return await self._eval_binop(node)
        if isinstance(node, ast.Compare):
            return await self._eval_compare(node)
        if isinstance(node, ast.Call):
            return await self._eval_call(node)
        return None, f"算不了这种表达式: {type(node).__name__}"

    async def _eval_binop(self, node: ast.BinOp) -> Tuple[Any, Optional[str]]:
        left, why = await self._eval(node.left)
        if why:
            return None, why
        right, why = await self._eval(node.right)
        if why:
            return None, why
        try:
            if isinstance(node.op, ast.Add):
                return left + right, None
            if isinstance(node.op, ast.Sub):
                return left - right, None
            if isinstance(node.op, ast.Mult):
                return left * right, None
            if isinstance(node.op, ast.FloorDiv):
                return left // right, None
            if isinstance(node.op, ast.Mod):
                return left % right, None
        except Exception as exc:  # noqa: BLE001 — 除零之类,如实报出来
            return None, f"算不下去: {type(exc).__name__}"
        return None, f"不支持的运算: {type(node.op).__name__}"

    async def _eval_compare(self, node: ast.Compare) -> Tuple[Any, Optional[str]]:
        left, why = await self._eval(node.left)
        if why:
            return None, why
        for op, comparator in zip(node.ops, node.comparators):
            right, why = await self._eval(comparator)
            if why:
                return None, why
            result = {
                ast.Eq: left == right,
                ast.NotEq: left != right,
                ast.Lt: left < right,
                ast.LtE: left <= right,
                ast.Gt: left > right,
                ast.GtE: left >= right,
            }.get(type(op))
            if result is None:
                return None, f"不支持的比较: {type(op).__name__}"
            if not result:
                return False, None
            left = right
        return True, None

    async def _eval_call(self, node: ast.Call) -> Tuple[Any, Optional[str]]:
        name = node.func.id
        args: List[Any] = []
        for arg in node.args:
            value, why = await self._eval(arg)
            if why:
                return None, why
            args.append(value)

        if name == "range":
            # 只在 for 里有意义;单独调用没副作用,直接给个值省得报错分支变多。
            return list(range(*args)), None

        if self.executed >= MAX_ACTIONS:
            return None, f"这段脚本的动作数超过上限 {MAX_ACTIONS},已停在第 {self.executed} 个"

        action, argnames = SCRIPT_API[name]
        params: Dict[str, Any] = dict(zip(argnames, args))
        for kw in node.keywords:
            value, why = await self._eval(kw.value)
            if why:
                return None, why
            params[kw.arg] = value
        missing = [a for a in argnames if a not in params]
        if missing:
            return None, f"{name}() 少了参数: {', '.join(missing)}"

        self.executed += 1
        self.actions.append({"action": action, **params})
        if action in TERMINAL_ACTIONS:
            self.terminal = action
            return None, f"__terminal__:{action}"
        result = await self._dispatch(action, params)
        if not (isinstance(result, dict) and result.get("success")):
            why = (result or {}).get("error") if isinstance(result, dict) else ""
            # 一步失败就整段停 —— 后面几步是按"前面成功了"写的,
            # 接着跑等于在错误的界面状态上继续操作。
            return None, f"第 {self.executed} 步 {name}() 失败: {why or '节点没说原因'}"
        return None, None


async def run_script(
    source: str,
    dispatch: Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]],
) -> ScriptRun:
    """校验并执行一段桌面脚本。

    *dispatch* 是真正把一个规范动作派出去的那个函数 —— 由调用方给,
    所以白名单校验、坐标换算、循环检测那一整条路**一点都没绕过**。
    """
    check = check_script(source)
    if not check.ok:
        return ScriptRun(False, 0, check.why)

    interp = _Interpreter(dispatch)
    why = await interp.run(ast.parse(source, mode="exec"))
    if interp.terminal:
        # 收尾是**正常结束**,不是错误 —— 那句 __terminal__ 只是用来中断解释,
        # 不该当成失败原因往上报。
        return ScriptRun(True, interp.executed, "", interp.actions, interp.terminal)
    if why is not None:
        return ScriptRun(False, interp.executed, why, interp.actions)
    return ScriptRun(True, interp.executed, "", interp.actions)


def script_api_prompt() -> str:
    """给模型看的 API 说明 —— 从 :data:`SCRIPT_API` 生成,不手写第二份。

    手写一份的话,加了新动作却忘了改提示词,模型就永远不会用它;
    删了动作却留在提示词里,模型会一直调一个不存在的函数。
    """
    lines = [f"  {name}({', '.join(argnames)})" for name, (_a, argnames) in SCRIPT_API.items()]
    return (
        "可用函数(只有这些,不能 import、不能用属性调用):\n"
        + "\n".join(lines)
        + f"\n可用语法:for i in range(N)(N ≤ {MAX_LOOP_RANGE})、if、简单赋值与算术。"
        + f"\n一段脚本最多 {MAX_ACTIONS} 个动作;任何一步失败,整段就停在那里。"
    )


__all__ = [
    "MAX_ACTIONS",
    "TERMINAL_ACTIONS",
    "MAX_LOOP_RANGE",
    "SCRIPT_API",
    "ScriptCheck",
    "ScriptRun",
    "check_script",
    "run_script",
    "script_api_prompt",
]
