"""tests/test_container_images_ship_what_they_run.py — 镜像里拷进去的代码，得够它自己跑起来。

2026-09-26 那次 Supply-Chain（run 36236799682），三个镜像一个都没产出：

* galaxy-main：``Dockerfile`` 去 COPY 一个仓库里并不存在的 ``cli/``，构建在 COPY 处就失败了。
  就算删掉那一行，镜像里也缺 main.py 顶层 import 的 ``entrypoint_role_contract.py`` 和
  ``launcher/``，CMD 一启动就 ModuleNotFoundError。还缺两样：``integration/``（``core.perception``
  在包的顶层 import 它，缺了整个感知层导入失败），以及 ``tools/architecture/``
  （``core.system_completion_status`` 顶层 import 它）。
* galaxy-gateway：缺 ``contracts/``，网关的 37 个安卓处理器模块在镜像里导入失败。
  这个 run 里网关镜像其实构建出来了，失败在后面的 SBOM 步骤（见最后一条测试）。
  所以缺这几个包是静默的：镜像能构建，只是跑不起来。
* galaxy-node：``requirements.txt`` 里的 pynput 在 Linux 上依赖 evdev。evdev 只有源码包，
  而 slim 基础镜像里没有编译器。

这些都是仓库内容和 Dockerfile 之间的静态关系，不必真起 Docker 也能核对，本文件做的就是这个。
核对的口径是：镜像里每一处**不设防**的 import（模块顶层，不在函数里、不在 try 里），
只要指向仓库自己的代码，就必须能在镜像里找到。设了防的（函数内惰性导入、try/except
兜底）属于可选依赖，缺了只是降级，不在此列。
"""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

# 镜像 → 它的启动入口（CMD 实际执行的那个文件）
IMAGE_ENTRYPOINTS = {
    "Dockerfile": "main.py",  # CMD ["python", "main.py"]
    "Dockerfile.gateway": "galaxy_gateway/app.py",  # uvicorn galaxy_gateway.app:app
}

# 仓库根下自己的顶层包/模块名 —— import 指向它们才算"仓库自己的代码"
LOCAL_TOP_LEVEL = {
    p.stem if p.suffix == ".py" else p.name
    for p in REPO_ROOT.iterdir()
    if not p.name.startswith(".") and (p.is_dir() or p.suffix == ".py")
}


def _copy_sources(dockerfile: str) -> List[str]:
    """Dockerfile 里从构建上下文拷进镜像的源路径（跳过 ``--from=`` 的多阶段拷贝）。"""
    sources: List[str] = []
    for line in (REPO_ROOT / dockerfile).read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*COPY\s+(.*)", line)
        if not m or "--from=" in line:
            continue
        args = [a for a in m.group(1).split() if not a.startswith("--")]
        sources.extend(args[:-1])
    return sources


def _dockerfiles() -> List[str]:
    return sorted(p.name for p in REPO_ROOT.glob("Dockerfile*") if p.is_file())


def _is_shipped(rel_path: str, sources: List[str]) -> bool:
    for src in sources:
        src = src.rstrip("/")
        if src in (".", "") or rel_path == src or rel_path.startswith(src + "/"):
            return True
    return False


def _shipped_py_files(sources: List[str]) -> Iterator[Path]:
    for src in sources:
        path = REPO_ROOT / src
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            for f in path.rglob("*.py"):
                if "__pycache__" not in f.parts:
                    yield f


def _resolve_local_module(dotted: str) -> Optional[str]:
    """把 ``a.b.c`` 解析到仓库里的文件（取最长的真实存在的前缀）；不存在则 None。"""
    parts = dotted.split(".")
    for n in range(len(parts), 0, -1):
        base = REPO_ROOT.joinpath(*parts[:n])
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate.is_file():
                return candidate.relative_to(REPO_ROOT).as_posix()
        if base.is_dir():  # 命名空间包
            return base.relative_to(REPO_ROOT).as_posix() + "/"
    return None


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _unguarded_imports(tree: ast.AST) -> Iterator[Tuple[int, str]]:
    """模块顶层（含顶层 if，除 TYPE_CHECKING）的绝对 import；函数里、try 里的不算。"""

    def walk(body):
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield node.lineno, alias.name
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                for alias in node.names:
                    yield node.lineno, f"{node.module}.{alias.name}"
            elif isinstance(node, ast.If) and not _is_type_checking_guard(node):
                yield from walk(node.body)
                yield from walk(node.orelse)

    yield from walk(getattr(tree, "body", []))


@functools.lru_cache(maxsize=None)
def _parse(path: Path) -> Optional[ast.AST]:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


@pytest.mark.parametrize("dockerfile", _dockerfiles())
def test_every_copy_source_exists(dockerfile):
    missing = [s for s in _copy_sources(dockerfile) if not (REPO_ROOT / s).exists()]
    assert not missing, f"{dockerfile} COPY 了仓库里不存在的路径，构建会在这一步失败: {missing}"


@pytest.mark.parametrize("dockerfile,entry", sorted(IMAGE_ENTRYPOINTS.items()))
def test_the_entrypoint_is_in_the_image(dockerfile, entry):
    assert _is_shipped(entry, _copy_sources(dockerfile)), f"{dockerfile} 的 CMD 要跑 {entry}，但它没被拷进镜像"


@pytest.mark.parametrize("dockerfile", sorted(IMAGE_ENTRYPOINTS))
def test_unguarded_local_imports_resolve_inside_the_image(dockerfile):
    sources = _copy_sources(dockerfile)
    broken: Dict[str, List[str]] = {}
    for path in _shipped_py_files(sources):
        tree = _parse(path)
        if tree is None:
            continue
        for lineno, dotted in _unguarded_imports(tree):
            if dotted.split(".")[0] not in LOCAL_TOP_LEVEL:
                continue
            target = _resolve_local_module(dotted)
            if target is None or _is_shipped(target, sources):
                continue
            where = f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}"
            if where not in broken.setdefault(target, []):
                broken[target].append(where)
    assert (
        not broken
    ), f"{dockerfile} 拷进镜像的代码在模块顶层 import 了没拷进去的仓库文件，" f"镜像里这些模块会 ModuleNotFoundError（目标 → 引用处）:\n" + "\n".join(
        f"  {t} ← {', '.join(w[:3])}" for t, w in sorted(broken.items())
    )


def test_the_node_image_can_compile_evdev():
    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    if not re.search(r"^\s*pynput\b", requirements, re.M):
        pytest.skip("requirements.txt 不再装 pynput，evdev 不再是传递依赖")
    logical_lines = (REPO_ROOT / "Dockerfile.node").read_text(encoding="utf-8").replace("\\\n", " ").splitlines()
    apt_lines = " ".join(line for line in logical_lines if "apt-get install" in line)
    for package in ("gcc", "libc6-dev"):
        assert re.search(rf"(^|\s){re.escape(package)}(\s|$)", apt_lines), (
            f"Dockerfile.node 没装 {package}:pynput 在 Linux 上依赖只有源码包的 evdev，"
            f"slim 镜像里 `pip install -r requirements.txt` 会在 evdev 处失败"
        )


def test_the_sbom_step_can_find_the_image_it_scans():
    """``outputs:`` 会取代 ``load:``，镜像只落成 tar、不进 Docker 守护进程，syft 按 tag 找不到它。"""
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/supply-chain.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["sbom-sign"]["steps"]
    builds = [s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action")]
    assert builds, "sbom-sign 里找不到构建镜像那一步"
    for step in builds:
        with_ = step.get("with", {})
        assert with_.get("load") is True, "SBOM 按 tag 扫描本地镜像，构建这一步必须 load 进守护进程"
        assert "outputs" not in with_, "outputs 会取代 load，镜像只落成 tar，下一步 syft 找不到它"
