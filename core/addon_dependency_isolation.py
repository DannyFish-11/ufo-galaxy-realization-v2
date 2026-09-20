"""core/addon_dependency_isolation.py —— 第三方 addon 的依赖装到哪

从 ``core/github_installer.py`` 拆出来的一件独立的事:**依赖怎么装、装进谁的环境**。
和"从 GitHub 拿代码"无关 —— 哪天 addon 来自别处(本地目录、私有 registry),这一层
原样可用。拆的直接原因也很实在:加上 venv 与 requirements 扫描之后,那个文件从
1644 涨到 1835,越过了 ``scripts/check_file_complexity.py`` 的基线,而那道门给的两条
出路是拆分或抬基线 —— 这个仓上一次(``voice_duplex_session.py``)选的是拆。

## 改之前是什么样

``github_installer`` 的模块 docstring 写着「Install Python dependencies into a
per-addon venv (optional)」,而 ``_install_deps`` 自己的注释写着「Uses the current
Python environment (… a venv per addon would be safer but heavier)」。**两句话在同一个
文件里打架**,实际行为是后者:第三方仓库的依赖 ``pip install`` 进宿主的 Python 环境。
而 ``github__install`` 是 LLM 直接可调的工具,默认 allowlist 为空(全放行)。

另一个更具体的洞:``_install_deps`` 对 ``deps`` 逐项做了很细的净化(拒绝 ``-`` 开头的
条目,注释里明写「``--index-url=恶意源`` → 供应链注入」),然后把第三方的
``requirements.txt`` 原样 ``-r`` 交给 pip —— 而 requirements 文件里**可以写那些选项**。
实测过:文件里写一行 ``--index-url https://…``,pip 打印 ``Looking in indexes: https://…``
并真的用它。前面挡住的,从这扇门原样进来。

## 这一层解决什么、不解决什么

解决的是**依赖被装进宿主环境**。

**不**解决"第三方代码跑在隔离边界里"。Skill 是 ``exec_module`` 进本进程的
(``core/skill_loader.py``),venv 对它的*执行*没有任何约束力;MCP addon 虽然是子进程,
但那也只是换了个解释器,不是沙箱。执行边界是 ``core/execution_isolation.py`` +
Node_09_Sandbox 那条线的事。这个区分必须写出来 —— 否则"装了 venv"会被读成
"已经沙箱化了",而那是一句假话。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AddonDeps")

__all__ = [
    "install_addon_deps",
    "scan_requirements_file",
    "add_venv_to_sys_path",
    "ensure_venv",
    "venv_dir",
    "venv_python",
    "venv_site_packages",
]


# ── Dependency Installation ───────────────────────────────────────────────────

#: 每个 addon 自己的 venv 目录名。带前缀是为了和第三方仓库自带的 ``.venv`` 区分开 ——
#: 撞名的话我们会往人家的环境里装东西,卸载时又会把人家的一起删。
_VENV_DIRNAME = ".galaxy-venv"

#: 显式选择"装进宿主环境"的开关。**只能开,不能默认**。
#:
#: 留这个口子是因为确实有场景需要(比如 addon 要 import 宿主进程里已经打好补丁的库),
#: 但它必须是一次显式选择:这条路会把第三方仓库的依赖装进你**当前这个 Python 环境**,
#: 而那正是这次要改掉的事。
_ENV_ALLOW_HOST_DEPS = "GALAXY_ADDON_HOST_DEPS"


def _host_deps_allowed() -> bool:
    return os.getenv(_ENV_ALLOW_HOST_DEPS, "").strip().lower() in ("1", "true", "yes", "on")


#: addon 的安装根。**这是本模块唯一认可的活动范围** —— 传进来的 addon_dir 必须落在
#: 它下面,否则一律拒绝。
#:
#: 和 ``github_installer._get_install_dir()`` 读同一个环境变量,而且那边改成从这里取,
#: 不留第二份定义 —— 两份会漂移,而漂移的那一刻这道校验就失效了。
_ENV_INSTALL_DIR = "GITHUB_INSTALL_DIR"
_DEFAULT_ADDON_ROOT = Path(__file__).resolve().parent.parent / "data" / "github_addons"


def addon_root() -> Path:
    raw = os.environ.get(_ENV_INSTALL_DIR, "").strip()
    return (Path(raw) if raw else _DEFAULT_ADDON_ROOT).resolve()


class AddonPathError(ValueError):
    """``addon_dir`` 不在 addon 根目录下 —— 拒绝在它上面做任何事。"""


def resolve_addon_dir(addon_dir: Path, root: Optional[Path] = None) -> Path:
    """把 ``addon_dir`` 归一化,并**确认它确实落在 addon 根下**;否则抛。

    ## 为什么这道校验必须在这一层,而不是"调用方已经净化过了"

    ``addon_dir`` 的来源是 ``github__install(url)`` —— 一个 **LLM 可调工具的参数**。
    调用方 ``github_installer`` 确实净化过:
    ``safe_ref = re.sub(r"[^A-Za-z0-9._-]", "_", effective_ref)``。
    但那条正则**允许 ``.`` 和 ``-``**,于是 ``ref=".."`` 原样活下来
    (``re.sub`` 只换非白名单字符,``..`` 两个字符都在白名单里),
    拼出来的 ``dest`` 就带着一个向上跳的路径段。

    CodeQL 在这个文件上报了 10 条(9 条 path expression + 1 条 uncontrolled command
    line),说的就是这件事:路径与命令行都依赖用户提供的值,而**使用点没有校验**。

    所以这里做的不是"消掉告警",是补上那道本来就该有的检查:归一化之后必须仍在根下。
    用 ``is_relative_to`` 而不是前缀字符串比较 —— 后者会被同前缀旁路目录绕过
    (``/addons-evil`` 能通过 ``/addons`` 的前缀检查)。这个坑仓里在
    ``_install_deps`` 的路径型依赖那段已经踩过一次并写在注释里。
    """
    # ``root`` 显式传入优先。**这一点不是可选的**:``GitHubInstaller`` 的
    # ``_install_dir`` 是**可注入**的(测试里就直接赋值),而本模块默认读的是环境变量。
    # 两者不一致时,拿环境变量那个当基准,会把注入方的每一个**合法**目录都判成越界 ——
    # 一道永远说"不"的检查和一道永远说"是"的检查一样没用。
    root = Path(root).resolve() if root is not None else addon_root()
    resolved = Path(addon_dir).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise AddonPathError(f"addon 目录不在 {root} 下,拒绝: {addon_dir!r} → {resolved}")
    return resolved


def venv_dir(addon_dir: Path, root: Optional[Path] = None) -> Path:
    """这个 addon 的 venv 目录。**越界会抛** —— 路径拼接前先确认落点。"""
    return resolve_addon_dir(addon_dir, root) / _VENV_DIRNAME


def venv_python(addon_dir: Path, root: Optional[Path] = None) -> Optional[Path]:
    """这个 addon 的 venv 解释器;没建过、或目录越界,都返回 None。

    **查询类的函数保持"全函数"(不抛)**:问"这儿有没有 venv",越界目录的正确答案是
    "没有",而不是抛一个异常让每个只想看一眼的调用方去接。真正要拦的是**动作** ——
    建 venv、装依赖、改 sys.path,那几处在下面各自拒绝。
    """
    try:
        venv = venv_dir(addon_dir, root)
    except AddonPathError:
        return None
    for rel in ("bin/python", "Scripts/python.exe"):
        candidate = venv / rel
        if candidate.exists():
            return candidate
    return None


def venv_site_packages(addon_dir: Path, root: Optional[Path] = None) -> Optional[Path]:
    """venv 的 site-packages。Skill 走 ``add_venv_to_sys_path`` 用它 —— 见那里的说明。

    同 ``venv_python``:越界返回 None,不抛。
    """
    try:
        venv = venv_dir(addon_dir, root)
    except AddonPathError:
        return None
    if not venv.exists():
        return None
    for pattern in ("lib/python*/site-packages", "Lib/site-packages"):
        for hit in sorted(venv.glob(pattern)):
            if hit.is_dir():
                return hit
    return None


def ensure_venv(addon_dir: Path, root: Optional[Path] = None) -> Optional[Path]:
    """给这个 addon 建一个 venv,返回它的解释器路径;建不出来返回 None。

    用 ``--system-site-packages``:宿主已经装好的东西(httpx、pydantic 这些)照样能 import,
    **新装的只落在 venv 里**。这次要解决的是"往宿主环境里写",不是"不许读宿主的包" ——
    后者会让每个 addon 都要重装一遍整个依赖树,慢到没人会用,而没人用的隔离等于没有隔离。
    """
    existing = venv_python(addon_dir, root)
    if existing is not None:
        return existing

    try:
        target = venv_dir(addon_dir, root)
    except AddonPathError as exc:
        # 动作:越界就不建。返回 None 让调用方按"venv 不可用"处理(它是 fail-closed 的)。
        logger.warning("拒绝为越界目录建 venv: %s", exc)
        return None
    try:
        result = subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("addon venv 创建失败(%s): %s", addon_dir.name, exc)
        return None
    if result.returncode != 0:
        logger.warning("addon venv 创建失败(%s): %s", addon_dir.name, (result.stderr or "")[:300])
        return None
    return venv_python(addon_dir, root)


#: requirements 文件里,以这些开头的行是 **pip 选项**而不是包名。
#:
#: 这正是下面 ``deps`` 那条逐项净化在防的东西(``--index-url=恶意源`` → 供应链注入),
#: 而 ``-r requirements.txt`` 会把整份文件原样交给 pip —— 前面挡住的,从这扇门原样进来。
#: 实测过:requirements.txt 里写一行 ``--index-url https://…``,pip 会打印
#: ``Looking in indexes: https://…`` 并真的用它。
_REQ_OPTION_PREFIXES = ("-",)


def scan_requirements_file(req_file: Path) -> List[str]:
    """扫一份 requirements.txt,返回**违规行的说明**(空列表 = 干净)。

    为什么是"整份拒绝"而不是"逐行过滤"
    -----------------------------------
    requirements 文件是一个整体:删掉其中几行再装,得到的是一套**谁都没验证过**的
    依赖组合 —— 装成功了更糟,因为没人会发现少了什么。所以有一行不合规就整份拒绝,
    并把是哪一行、为什么原样报出去。
    """
    violations: List[str] = []
    try:
        raw = req_file.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return [f"requirements.txt 读不出来: {exc}"]

    for lineno, line in enumerate(raw.splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        text = text.split(" #", 1)[0].strip()  # 行尾注释
        if not text:
            continue
        if text.startswith(_REQ_OPTION_PREFIXES):
            violations.append(f"第 {lineno} 行是 pip 选项而不是包名(供应链注入风险): {text!r}")
            continue
        if not re.fullmatch(r"[A-Za-z0-9._\-\[\]<>=!~,; ]+", text):
            violations.append(f"第 {lineno} 行不是合法的包名/版本规格: {text!r}")
    return violations


def install_addon_deps(addon_dir: Path, deps: List[str], root: Optional[Path] = None) -> Dict[str, Any]:
    """装这个 addon 的 Python 依赖 —— **装进它自己的 venv**,不是宿主环境。

    原先这里是 ``[sys.executable, "-m", "pip", "install", …]``,注释还写着
    "a venv per addon would be safer but heavier" —— 而模块 docstring 同时声称
    "Install Python dependencies into a per-addon venv (optional)"。两句话在同一个
    文件里打架,实际行为是前者:第三方仓库的依赖装进你当前这个 Python 环境。

    返回结构化结果而不是 bool:拒绝的原因(哪一行、为什么)必须能传到调用方,
    只回一个 False 等于把"为什么不装"丢了。
    """
    try:
        addon_dir = resolve_addon_dir(addon_dir, root)
    except AddonPathError as exc:
        logger.warning("拒绝为越界目录装依赖: %s", exc)
        return {"attempted": False, "success": False, "scope": "rejected", "error": str(exc)}

    req_file = addon_dir / "requirements.txt"
    if not deps and not req_file.exists():
        return {"attempted": False, "success": True, "scope": "none"}

    # ── requirements.txt 先扫再喂 ────────────────────────────────────────────
    if req_file.exists():
        violations = scan_requirements_file(req_file)
        if violations:
            logger.warning("addon %s 的 requirements.txt 被拒: %s", addon_dir.name, violations)
            return {
                "attempted": True,
                "success": False,
                "scope": "rejected",
                "error": "requirements.txt 含 pip 选项或非法包名,整份拒绝",
                "violations": violations,
            }

    # ── 选装到哪 ────────────────────────────────────────────────────────────
    scope = "venv"
    python_exe = ensure_venv(addon_dir, root)
    if python_exe is None:
        if not _host_deps_allowed():
            # **fail closed**。建不出 venv 就退回宿主环境,等于这层没装 ——
            # 而且失败得悄无声息,正是这次要改掉的那个形状。
            return {
                "attempted": True,
                "success": False,
                "scope": "venv_unavailable",
                "error": (
                    f"无法为 addon 创建 venv,且未显式允许装进宿主环境。" f"要接受这个代价,设 {_ENV_ALLOW_HOST_DEPS}=1。"
                ),
            }
        logger.warning("addon %s:venv 不可用,按 %s=1 装进宿主环境", addon_dir.name, _ENV_ALLOW_HOST_DEPS)
        python_exe = Path(sys.executable)
        scope = "host"

    pip_cmd = [str(python_exe), "-m", "pip", "install", "--quiet"]
    # 改名是必要的:模块级已经有一个 addon_root() 函数,同名局部变量会把它遮掉。
    addon_boundary = addon_dir.resolve()
    for dep in deps:
        dep = dep.strip()
        if not dep:
            continue
        # 安全:deps 来自第三方仓库的 manifest。"-" 开头的条目会被 pip 当作
        # 【选项】(如 --index-url=恶意源 → 供应链注入),一律拒绝。
        if dep.startswith("-"):
            logger.warning("dep rejected (option-like, injection risk): %r", dep)
            continue
        # Relative paths (e.g. ".") resolved against addon_dir
        if dep.startswith(".") or dep.startswith("/"):
            # 源头净化:路径型依赖只允许安全字符集,在【构造任何路径之前】
            # 就掐断污点(绝对路径 /etc/... 、含 shell 元字符等一律拒绝)。
            if dep.startswith("/") or not re.fullmatch(r"[A-Za-z0-9_./-]+", dep):
                logger.warning("dep rejected (unsafe path chars): %r", dep)
                continue
            dep_path = (addon_dir / dep).resolve()
            # 二次防御:归一后必须仍落在 addon 目录内(防 ../ 穿越)。
            # 用 is_relative_to 而不是 startswith 前缀判断——后者可被
            # 同前缀旁路目录绕过(如 /addons-evil 通过 /addons 的检查)。
            if not dep_path.is_relative_to(addon_boundary):
                logger.warning("dep rejected (escapes addon dir): %r", dep)
                continue
            pip_cmd.append(str(dep_path))
        else:
            # 包名/版本规格:PEP 508 合法字符白名单(字母数字 + . _ - [ ] < > = ! ~ , ;
            # 空格)。掐掉 shell 元字符与选项注入,再交给 pip(list 形式无 shell)。
            if not re.fullmatch(r"[A-Za-z0-9._\-\[\]<>=!~,; ]+", dep):
                logger.warning("dep rejected (unsafe package spec): %r", dep)
                continue
            pip_cmd.append(dep)

    if req_file.exists():
        pip_cmd += ["-r", str(req_file)]

    logger.info("Installing dependencies into %s: %s", scope, pip_cmd[4:])  # skip ['python','-m','pip','install']
    try:
        result = subprocess.run(
            pip_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300
        )
        if result.returncode != 0:
            logger.warning("Dependency install warnings/errors: %s", result.stderr[:500])
            return {
                "attempted": True,
                "success": False,
                "scope": scope,
                "error": (result.stderr or "").strip()[:500] or "pip 退出码非 0",
            }
        return {"attempted": True, "success": True, "scope": scope, "venv": str(venv_dir(addon_dir, root))}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dependency install failed: %s", exc)
        return {"attempted": True, "success": False, "scope": scope, "error": str(exc)}


def add_venv_to_sys_path(addon_dir: Path, root: Optional[Path] = None) -> bool:
    """把 addon venv 的 site-packages 追加进 ``sys.path``。已在里面就不重复加。"""
    site_dir = venv_site_packages(addon_dir, root)  # 越界时它返回 None
    if site_dir is None:
        return False
    entry = str(site_dir)
    if entry in sys.path:
        return True
    sys.path.append(entry)
    logger.info("addon %s:venv site-packages 已加入 import 路径", addon_dir.name)
    return True
