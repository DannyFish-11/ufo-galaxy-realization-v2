#!/usr/bin/env python3
"""check_wiring.py — 找出"写完了但没接上"的公开能力。

要抓什么
--------
本仓反复出现过同一种情形:一个能力**实现完整、单测齐全、文档详尽**,但在生产代码里
**零个调用方**。它不会报错、不会变慢、不会让任何测试变红 —— 它只是不生效。

本轮实测到的一例(我自己刚写完就犯的):

  * ``DesktopPresenceRuntime.halt_ambient_presence`` —— "中心可叫停"实现了,
    但没有任何按钮/端点/事件去按它。能力存在,入口不存在。
    (后来在 ``core/routes/operator.py`` 补了端点才真正接上。)

它当时有完整单测且全绿。**单测证明的是"这个函数对不对",不是"有没有人用它"**。

判据
----
一个 ``core/`` 或 ``galaxy_gateway/`` 下的公开函数/方法,若同时满足:

  1. 名字不以 ``_`` 开头;
  2. 全仓(除 ``tests/`` 等,见 ``REFERENCE_SKIP_PARTS``)找不到任何引用;
  3. 不在豁免清单里(见 ``_EXEMPT_*``);

就算"未接线"。

为什么必须有基线,以及基线为什么只记名字
----------------------------------------
第一次跑出来是 **794 条**。这个数字本身就是结论:未接线的公开能力在本仓是**存量债**,
不是偶发缺陷。794 条告警等价于 0 条告警 —— 没人会去读,读了也不知道该先修哪条。

而这道检查真正值钱的信号只有一个:**你这次新写的东西没人调用**。存量的 700 多条是
另一件事(要不要清理、按什么顺序清理),不该由这道闸来逼,也逼不动 —— 这与
``check_file_complexity.py`` 重做基线时的判断是同一条:

    把已经欠下的债记成债(基线),和阻止新债(阈值),是两件事;
    混在一起的结果就是两件都失效。

所以基线记的是**名字集合**而不是位置:函数搬家、行号漂移都不该让基线失效,只有
"出现了一个此前没有的未接线公开能力"才算新债。名字从基线里消失(被接上了、被删了、
被改名了)不判失败,只在输出里提一句 —— 否则每次重构都要重记基线,又会退化成
"红了不用管"。

刻意的边界
----------
* 用 AST 找引用,不用正则:``foo`` 出现在注释、docstring 里不算调用。
  但字符串常量算 —— ``__all__ = ["foo"]`` / ``getattr(x, "foo")`` 是真实的动态引用。
* **定义只看 ``core/`` 与 ``galaxy_gateway/``,引用扫全仓**。这两个范围不对称是有意的:
  ``nodes/`` 下 125 个节点各自是独立进程入口,"没有仓内调用方"是它们的常态(报出来
  只有噪声),但它们**调用** core 的能力,所以必须计入引用侧。早先版本引用侧也只扫
  这两个目录,把"只被 nodes/ 或 scripts/ 用到"的能力误判成了未接线。
* 方法名全仓唯一时才判定 —— 同名方法在多个类上时无法靠 AST 静态区分,宁可漏报不误报。
* **不做关键字参数级的检查**。实测过:"函数有调用方但某个可选参数从没被传过"能扫出
  885 处、涉及 2080 个参数。可选参数本来就允许不传,这个信号里绝大多数是正常的,
  没有可用的信噪比。想抓"参数加了却没人用"只能靠评审,工具做不到。

用法::

    python scripts/check_wiring.py                    # 只报新增(默认)
    python scripts/check_wiring.py --strict           # 有新增即非零退出
    python scripts/check_wiring.py --all              # 连存量一起列出
    python scripts/check_wiring.py --json             # 机器可读
    python scripts/check_wiring.py --update-baseline  # 重记基线
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "config" / "wiring_baseline.json"

#: 定义侧:在这几个目录里找"公开能力"。
#:
#: nodes/ 是后加的,而**它的缺席造成过一次真实的长期缺陷**:
#: ``nodes/Node_05_Auth/oauth_routes.py`` 里的 ``register_oauth_routes(app)``
#: 定义了 9 条 ``/auth/oauth/*`` 路由,却从来没有被任何地方调用过 ——
#: 那一族因此不在统一启动器的 9000 上,也不在 Node_05 自己的 8005 上,
#: 任何进程都没有服务过它们。手表的设备码登录、Android 的 logout/refresh
#: 全打在不存在的端点上,而这个工具**看不见**,因为定义侧当时只扫
#: core/ 与 galaxy_gateway/。
#:
#: 加上 nodes/ 之后未接线从 648 涨到 859(+217)。那 217 条是存量,按本仓惯例
#: 记进基线、闸只看增量 —— 重点不是那个数字,而是这一大块代码从此**在视野里**。
#:
#: 2026-08-05 再补 launcher/。上面那段记着"定义侧当时只扫 core/ 与 galaxy_gateway/"
#: 导致 nodes/ 整块看不见 —— 同一件事又发生了一次:统一启动器落地后,launcher/ 的
#: 18 个模块(含 2235 行的 services.py)从来没进过这道门的视野。
#:
#: 这已经是本仓第三次栽在「范围是人划的」上(面板配置守卫、复杂度门、这里)。
#: 记下来:**新增顶层产品目录时,要回来看的不止一处**。
DEFINITION_DIRS = ("core", "galaxy_gateway", "nodes", "launcher")

#: 已知的残余盲区:**import 但从不调用,算"已接线"**。
#:
#: 引用侧按名字统计,而 ``from x import y`` 会让 y 出现在引用集合里。所以一个
#: 被 import 进来、却从没被调用的函数,这里看不出来。
#:
#: 试过收紧(只认真正的使用,不认 import 绑定):未接线从 859 涨到 **1391(+532)**,
#: 而新增的那批绝大多数是 ``__init__.py`` 里的**正当再导出** —— 那是公开 API 的
#: 组织方式,不是缺陷。为一个次要盲区换 532 条噪声,这道闸会先被噪声压垮。
#:
#: 记下这个数字,是为了下一个人不用再走一遍这条路;也为了说清楚本工具**抓的是
#: "全仓零引用"**,不是"零调用"。真正造成过长期缺陷的那种(register_oauth_routes:
#: 既没人 import 也没人调用)属于前者,抓得到。
#:
#: 引用侧:扫全仓,除了这些。tests/ 必须排除 —— 只有测试调用它,恰恰就是本工具要抓的。
REFERENCE_SKIP_PARTS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "site-packages",
    "build",
    "dist",
    "external",  # 第三方源码
    "tests",  # 见上:被测试调用不算"接上了"
    "chroma_db",
    "logs",
    "data",
    "media_gen_output",
}

#: 名字命中这些前缀的一律不报 —— 它们本来就是"给外面用"的。
_EXEMPT_PREFIXES = (
    "get_",  # 单例访问器:调用方常在别的仓/运行时动态取
    "create_router",  # FastAPI 路由工厂:由 api_routes 动态挂载
    "main",
)

#: 整个模块豁免:这些模块的存在意义就是"被外部/动态调用"。
_EXEMPT_MODULES = (
    "core/routes/",  # 路由处理函数由装饰器注册,静态看不到调用方
    "galaxy_gateway/routes/",  # 同上
    "core/schemas/",  # 数据契约
    "core/api_routes.py",
)

#: 精确豁免:有明确理由的个案。写清楚理由,不写理由不许加。
#: 逐名豁免。**先想想能不能用结构判据**(见 :func:`_is_singleton_reset`)——
#: 逐名清单只会越来越长,而且没人敢删。
_EXEMPT_NAMES: Dict[str, str] = {
    "close_app": (
        "**故意不接线**。UFODeepIntegration.launch_app / close_app 能执行任意二进制"
        "(subprocess.Popen([app_path]) —— 那个正则只挡 shell 元字符,而这里根本没有 "
        "shell,Popen 就是精确执行那个路径,{'app_path': '/bin/sh'} 照样起 shell)。"
        "本轮曾把它们暴露成 POST /app/launch 与 /app/close,CodeQL 当场判 critical:"
        "任何人都能远程在宿主上执行任意程序。已撤回。"
        "要接的话得先定产品策略 —— 允许启动哪些程序(白名单)、谁有权调 —— "
        "那是产品决定,不该由改这行代码的人顺手定。在那之前它保持不可达,"
        "而这条豁免是为了让下一个人看见理由,而不是又去接一遍。"
    ),
    "clear_ledger": (
        "**故意不接线**。core/egress_guard.py 的出站账本是个有界 ring buffer,"
        "它自己会滚,生产路径上没有任何一处**应该**去清空它 —— 一个能被远程清账本的"
        "出口闸,等于给攻击者留了擦脚印的开关。"
        "它存在是为了两件事:测试之间不让账本串味,以及本机运维手动清理。"
        "两者都不是生产调用方,所以这里没有「该被谁调用」的答案 —— 正确答案就是没人。"
    ),
    "declared_ports": (
        "**内省接口,故意没有生产调用方**。core/upper_ports.py 的绑定表内省 —— "
        "它存在只为两件事:让 tests/test_upper_ports_bindings_are_real.py 能逐条校验"
        "「表里每个端口是否真的解析得出来」,以及人工审查时把 57 条上层依赖列出来看。"
        "生产路径上没有任何一处**应该**去枚举绑定表:要用哪个端口,调用点直接写死端口名,"
        "枚举出来再挑等于把静态依赖变成动态的,反而更难查。所以「该被谁调用」的正确答案就是没人。"
    ),
    "binding_of": (
        "**内省接口,故意没有生产调用方**,与上面 declared_ports 同一个理由。"
        "它回答的是「这个端口名绑到哪个模块:属性」,用途是测试失败时把目标打进错误消息里,"
        "以及审查时对照。生产代码只需要 resolve() 的结果,不需要知道它从哪来 —— "
        "真需要知道的时候,该看的是 config/upper_layer_ports.json 那张表,不是绕一层函数。"
    ),
    "clear_registry": (
        "**故意不接线**,与上面 clear_ledger 同一个理由。core/scope_authority.py 里"
        "它清的是两样东西:按会话的已定作用域表,和权威交接账本。"
        "生产路径上没有任何一处**应该**去清它们 —— 清掉已定作用域会让 transition 档"
        "失去沿用依据(于是权威变成判不出来),清掉交接账本等于抹掉"
        "「那次冲突发生时谁说了算」的唯一记录。一个能被远程清空权威交接记录的开关,"
        "和一个能清空出站账本的开关是同一类东西。"
        "它存在只为让测试之间不串味。"
    ),
}


def _iter_definition_files() -> List[Path]:
    out: List[Path] = []
    for scan_dir in DEFINITION_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if any(part in REFERENCE_SKIP_PARTS for part in path.parts):
                continue
            out.append(path)
    return out


def _iter_reference_files() -> List[Path]:
    out: List[Path] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in REFERENCE_SKIP_PARTS for part in path.parts):
            continue
        out.append(path)
    return out


def _is_singleton_reset(node) -> bool:
    """这个函数是不是「模块级单例的测试用复位入口」。

    为什么按结构判而不是按名字
    --------------------------
    此前 ``_EXEMPT_NAMES`` 里手工列着 10 个 ``reset_*``,理由清一色是"测试专用
    重置入口,生产无调用方是设计如此"。全仓这类函数有 130 多个 —— 逐个往清单里
    加,清单只会越来越长,而且加进去之后没人敢删。这正是本文件开头写过的那种
    退化方式。

    更要紧的是:**按名字前缀一刀切是错的**。``reset_bucket(tool_name)``、
    ``reset_device(device_id)``、``reset_session(session_id)`` 都以 ``reset_``
    开头,但它们是真实的运行时操作 —— 限流桶复位、设备健康复位、会话预算复位。
    按前缀豁免会把这三条真该有调用方的能力一起藏掉。

    结构判据把两类分得很干净:

        测试用复位   模块级函数 + 无必填参数 + 函数体里有 global
        运行时操作   类的方法 / 带必填参数(操作的是某个 keyed 对象)

    实测:130 多个 ``reset_*`` 里,符合这个结构的都是把模块级单例置回 None 的
    那种;上面三条一条都不符合。
    """
    if not node.name.startswith("reset_"):
        return False
    # 有必填参数 → 它操作的是传进来的那个对象,不是模块级单例。**这一条是主判据**,
    # reset_bucket / reset_device / reset_session 全被它挡住。
    args = [a.arg for a in node.args.args if a.arg != "self"]
    required = len(args) - len(node.args.defaults)
    if required > 0 or node.args.kwonlyargs or node.args.vararg:
        return False
    # 复位模块级状态有两种写法,都要认:
    #   global _x; _x = None        —— 重新绑定,需要 global 声明
    #   _stacks.clear()             —— 原地改容器,**不需要** global
    # 第一版只认前者,结果 core/focus_stack.py 的 reset_focus_stacks(用的是后者)
    # 立刻被报了出来 —— 它此前一直躺在手工豁免名单里,换成结构判据才现形。
    for n in ast.walk(node):
        if isinstance(n, ast.Global):
            return True
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "clear"
            and isinstance(n.func.value, ast.Name)
        ):
            return True
    return False


def _is_exempt(rel: str, name: str) -> bool:
    if name in _EXEMPT_NAMES:
        return True
    if name.startswith(_EXEMPT_PREFIXES):
        return True
    return any(rel.startswith(prefix) for prefix in _EXEMPT_MODULES)


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError):
        # 语法错误的文件不是本工具该管的事(有 lint 管),静默跳过而不是中断整次扫描。
        return None


def collect_definitions(files: List[Path], root: Path = REPO_ROOT) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
    """返回 (定义名 → 定义位置列表, 名字 → 定义次数)。

    ``root`` 只用来把位置显示成相对路径。给它一个默认值而不是硬写 ``REPO_ROOT``,
    是为了让本函数能对着任意目录跑 —— 测试要在 tmp_path 里造桩文件验证判据,
    而"只能对着本仓跑"的分析函数是没法被真正验证的。
    """
    definitions: Dict[str, List[str]] = defaultdict(list)
    def_count: Dict[str, int] = defaultdict(int)
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                if _is_framework_registered(node):
                    continue
                if _is_singleton_reset(node):
                    continue
                definitions[node.name].append(f"{rel}:{node.lineno}")
                def_count[node.name] += 1
    return definitions, def_count


#: 被框架按装饰器注册的方法名。带这类装饰器的函数**不该**算"未接线":
#: 调用方是框架本身,静态分析按名字永远找不到。
_REGISTRAR_ATTRS = frozenset(
    {
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "head",
        "options",
        "websocket",
        "middleware",
        "exception_handler",
        "on_event",
        "route",
        "app",  # celery/click 之类的 @something.app(...)
        # 事件发射器的通用注册式:@emitter.on("事件名")。pyee / aiortc(RTCPeerConnection)
        # / python-socketio 都是这个写法,与 FastAPI 的 @app.get 是同一个结构事实 ——
        # 调用方是框架,按名字静态找不到。本仓 nodes/Node_95_WebRTC_Receiver 的
        # @pc.on("iceconnectionstatechange") 此前就被误报成未接线。
        "on",
    }
)


def _is_framework_registered(node) -> bool:
    """这个函数是不是被装饰器注册给框架了(FastAPI 路由、中间件、事件钩子…)。

    为什么按**结构**判而不是按路径开白名单
    ----------------------------------------
    本仓原先只有 ``_EXEMPT_MODULES`` 这条路:整个 ``core/routes/`` 目录豁免,理由写着
    "路由处理函数由装饰器注册,静态看不到调用方"。那个理由是对的,但它绑在**目录**上,
    于是同样是路由处理器、只要不长在那个目录里就照报不误 —— ``launcher/services.py``
    里嵌在 ``start()`` 内的 ``@self.app.get("/api/status")`` 就是这么被报成未接线的
    (那个文件 2235 行,里面绝大多数不是路由,整个豁免掉才是真的放水)。

    「被装饰器注册」是一个**结构事实**,与它长在哪个目录无关。按结构判之后:
    路由处理器无论写在哪儿都不误报,而同目录下**非**路由的死函数照样报得出来。
    """
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        # 只认 `x.y(...)` / `x.y` 形式;裸名字装饰器(@staticmethod)不算注册
        if isinstance(target, ast.Attribute) and target.attr in _REGISTRAR_ATTRS:
            return True
    return False


def _self_exported_constants(tree: ast.AST) -> Set[int]:
    """本文件 ``__all__`` 里那些**指向本文件自己定义**的字符串常量节点的 id()。

    为什么只排除"自己导出自己"
    --------------------------
    ``__all__`` 有两种截然不同的用法，判据必须分开：

    * **自证**：模块在自己的 ``__all__`` 里列自己定义的函数。这**不是使用** ——
      它只是声明"这个名字是我的公开面"。可字符串常量一律算引用的话，模块只要
      声明了 ``__all__``，它自己的公开函数就永远不可能被判为"未接线"，而**写得越
      规范的模块越会声明 __all__**，守卫恰好对最该管的代码失效。

      不是假想：``core/phase_contract.py`` 的 ``resolve_render_posture`` 一度在全仓
      没有任何调用方（渲染契约写好了但没接进桥），本工具带 ``--strict`` 跑仍是绿
      的，就是被它自己 ``__all__`` 里那个字符串自证了。

    * **再导出**：包的 ``__init__.py`` 在 ``__all__`` 里列**别处定义**的名字（本仓
      ``core/continuum/__init__.py`` 就是典型）。那是**真实的引用** —— 它把那个名字
      抬进了包的公开面。排除它会把整片再导出误判成未接线。

    所以判据是"同一文件内定义 + 出现在该文件 ``__all__``"才排除。第一版一刀切排除
    了全部 ``__all__`` 字符串，被 ``tests/test_check_wiring.py`` 里那条再导出用例
    当场抓住。
    """
    own_defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    marked: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        if node.value is None:
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in own_defs:
                marked.add(id(sub))
    return marked


def collect_references(files: List[Path]) -> Set[str]:
    """全仓被引用到的名字。调用、属性访问、from-import、字符串常量都算。

    例外：模块**自己 __all__ 里指向自己定义**的字符串不算引用——见
    :func:`_self_exported_constants`。
    """
    referenced: Set[str] = set()
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        skip = _self_exported_constants(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    referenced.add(alias.name)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in skip:
                    continue
                referenced.add(node.value)
    return referenced


def find_unwired(definitions, referenced, def_count) -> List[Tuple[str, str]]:
    """定义了、但在非测试代码里没有任何引用的公开函数。"""
    out: List[Tuple[str, str]] = []
    for name, locations in sorted(definitions.items()):
        # 同名多处定义时静态无法确定引用指向哪一个 —— 宁可漏报不误报。
        if def_count[name] > 1:
            continue
        rel = locations[0].split(":")[0]
        if _is_exempt(rel, name):
            continue
        # 这里的"被引用"是**全仓非测试代码里出现过这个名字**,不是"外部可达"。
        #
        # 原注释写的是"定义处自身不会自证",那句话是错的:``self.foo(...)`` 写在
        # foo 自己的模块里,也是一个 ast.Attribute,照样算引用。于是一个只被同模块
        # 内部调用、外面没有任何人用的公开能力,能靠自引用躲过这道闸
        # (实例:core/ontology/links.py 的 for_source,唯一引用来自同文件的
        # resolve_all)。**这是本闸已知的漏检,不是它的设计意图。**
        #
        # 为什么没有顺手修:量过了。
        #   仅靠模块内自引用而算作"已接线"的:888 个
        #   其中连模块内可达性都通不过的:      243 个
        # 而这 243 条里占多数的是**误报**——装饰器返回的内层函数(error_framework
        # 的 async_wrapper)、以及节点按字符串名分发的 action handler(分发表就在
        # 同一个文件里,Node_83 的 add_feed 之类)。把它们报出来,这道闸就会变成
        # 没人看的噪音,然后被关掉——而本文件顶部的设计说明恰恰写着,那比一道窄而
        # 常开的闸更糟。
        #
        # 真要修,需要的是函数级可达性 + 一个能理解字符串分发的模型,不是在这里
        # 多加一个条件。在那之前,这条漏检是**写明的**,不是假装不存在的。
        if name in referenced:
            continue
        out.append((name, locations[0]))
    return out


def load_baseline() -> Set[str]:
    if not BASELINE_PATH.is_file():
        return set()
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set(data.get("unwired") or [])


def write_baseline(names: List[str]) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": (
            "scripts/check_wiring.py 的存量基线:记录时已存在的「公开但零调用方」能力名。"
            "这是**债的记账**,不是白名单 —— 名字在这里只代表『不是这次新欠的』。"
            "新出现的名字才判失败(--strict)。用 --update-baseline 重记;"
            "重记产生的 diff 会明确显示新增了哪些,评审时请确认那是有意的。"
        ),
        "unwired": sorted(names),
    }
    BASELINE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true", help="出现基线之外的未接线能力即非零退出")
    parser.add_argument("--all", action="store_true", help="连基线内的存量一并列出")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--update-baseline", action="store_true", help="把当前结果重记为基线")
    args = parser.parse_args()

    def_files = _iter_definition_files()
    ref_files = _iter_reference_files()
    definitions, def_count = collect_definitions(def_files)
    referenced = collect_references(ref_files)
    unwired = find_unwired(definitions, referenced, def_count)

    baseline = load_baseline()
    current_names = {name for name, _ in unwired}
    new = [(n, w) for n, w in unwired if n not in baseline]
    known = [(n, w) for n, w in unwired if n in baseline]
    resolved = sorted(baseline - current_names)

    if args.update_baseline:
        write_baseline(sorted(current_names))
        print(f"已重记基线:{len(current_names)} 条 → {BASELINE_PATH.relative_to(REPO_ROOT)}")
        return 0

    if args.json:
        print(
            json.dumps(
                {
                    "definition_files": len(def_files),
                    "reference_files": len(ref_files),
                    "baseline": len(baseline),
                    "new": [{"name": n, "at": w} for n, w in new],
                    "known": [{"name": n, "at": w} for n, w in known],
                    "resolved": resolved,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if (new and args.strict) else 0

    print(
        f"定义侧 {len(def_files)} 个文件({', '.join(DEFINITION_DIRS)});"
        f"引用侧 {len(ref_files)} 个文件(全仓,不含 tests/)\n"
        f"未接线合计 {len(unwired)} —— 基线内 {len(known)},新增 {len(new)}\n"
    )

    if new:
        print(f"⚠️  {len(new)} 个**新出现**的公开能力在生产代码里没有任何调用方:\n")
        for name, where in new:
            print(f"  {name:48} {where}")
        print(
            "\n  每一条都值得回答一句:它到底该被谁调用?答不上来,它现在就是不生效的。\n"
            "  确认无需接线的,加进 _EXEMPT_NAMES 并写明理由;确认是存量的,用 --update-baseline。"
        )
    else:
        print("✅ 没有新增的「实现了但没有任何调用方」的公开能力。")

    if resolved:
        # 不判失败:接上了、删了、改名了都会走到这里,每次都逼人重记基线会让这道闸退化成噪声。
        print(f"\n📉 基线里有 {len(resolved)} 条已不再未接线(接上/删除/改名)。可用 --update-baseline 收敛基线。")

    if args.all and known:
        print(f"\n── 基线内的存量({len(known)} 条)──\n")
        for name, where in known:
            print(f"  {name:48} {where}")

    return 1 if (new and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
