"""函数体里 ``from 仓库里的模块 import 名字`` —— 那个名字得真的在那个模块里。

这类 import 大多包在 ``try/except Exception`` 里,名字不存在时**不会报错**,只会让那条路径一声不响地退成
「不可用」。真跑一轮在日志里看到的样子:设备参与度每 3 秒对 8 台设备各记三条
``Exception suppressed: cannot import name ...``(一轮 600 多条),而那三条路径从来没生效过。逐个扫出来还有:

- ``/api/v1/vision/understand`` 每次 500(把协程丢进线程池,拿回没 await 的协程对象),
  ``/api/v1/vision/ocr`` 永远回失败(``DeepSeekOCR2Adapter`` / ``process_image`` 都不存在);
- 调度真相 harness 永远答「能力策略不可用」、永远判不收敛;
- 叙事层每次往 trace 里记一条假的 ``android_recovery_failed``。

只核对**仓库自己的**模块(顶层目录在仓库里);外部包(例如 Node_36 加载的微软 UFO ``agents.*``)与
``external/`` 下原样放进来的第三方代码不管。
目标模块用 ``__getattr__`` 做惰性导出、或 ``import *`` 的,静态看不出来,跳过。
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
from typing import Iterator, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
SCANNED = ("core", "contracts", "galaxy_gateway", "launcher", "nodes", "windows_service", "enhancements")
#: 顶层目录在仓库里、但不是本仓自己的代码:external/ 是原样放进来的第三方(微软 UFO,自己 import ufo.*)
VENDORED = frozenset({"external"})


def _module_file(root: Path, module: str) -> Optional[Path]:
    base = root.joinpath(*module.split("."))
    for p in (base.with_suffix(".py"), base / "__init__.py"):
        if p.is_file():
            return p
    return None


def _is_repo_package(root: Path, module: str) -> bool:
    top = module.split(".")[0]
    return top not in VENDORED and ((root / top).is_dir() or (root / f"{top}.py").is_file())


@lru_cache(maxsize=None)
def _top_level_names(path: Path) -> Tuple[Optional[frozenset], bool]:
    """(顶层定义的名字, 静态看不全)。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None, True
    names: Set[str] = set()
    opaque = False

    def walk(body) -> None:
        nonlocal opaque
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
                opaque = opaque or n.name == "__getattr__"
            elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                    names.update(x.id for x in ast.walk(t) if isinstance(x, ast.Name))
            elif isinstance(n, ast.Import):
                names.update((a.asname or a.name).split(".")[0] for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    opaque = opaque or a.name == "*"
                    names.add(a.asname or a.name)
            elif isinstance(n, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for field in ("body", "orelse", "finalbody"):
                    walk(getattr(n, field, None) or [])
                for h in getattr(n, "handlers", None) or []:
                    walk(h.body)

    walk(tree.body)
    return frozenset(names), opaque


def _sources(root: Path) -> Iterator[Path]:
    for top in SCANNED:
        for p in (root / top).rglob("*.py"):
            if "__pycache__" not in p.parts and "node_modules" not in p.parts:
                yield p


def _unresolved(root: Path = REPO) -> List[str]:
    bad: List[str] = []
    for path in _sources(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.ImportFrom) or n.level or not n.module or not _is_repo_package(root, n.module):
                continue
            where = f"{path.relative_to(root).as_posix()}:{n.lineno}"
            target = _module_file(root, n.module)
            if target is None:
                bad.append(f"{where} {n.module} (模块不存在)")
                continue
            names, opaque = _top_level_names(target)
            if names is None or opaque:
                continue
            for a in n.names:
                if a.name != "*" and a.name not in names and _module_file(root, f"{n.module}.{a.name}") is None:
                    bad.append(f"{where} from {n.module} import {a.name}")
    return bad


def test_every_import_of_a_repo_module_names_something_that_is_there():
    bad = _unresolved()
    assert not bad, "这些 import 的名字在目标模块里不存在(包在 try 里就会一声不响地退成「不可用」):\n" + "\n".join(bad)


def test_the_scan_catches_a_missing_name(tmp_path):
    """扫描本身得认得出缺陷签名,不然上面那条永远绿。"""
    pkg = tmp_path / "core"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "real.py").write_text("def here():\n    return 1\n", encoding="utf-8")
    (pkg / "user.py").write_text(
        "def f():\n    try:\n        from core.real import gone\n    except Exception:\n        pass\n",
        encoding="utf-8",
    )
    (pkg / "fine.py").write_text("from core.real import here\nfrom core.nowhere import x\n", encoding="utf-8")
    assert sorted(_unresolved(tmp_path)) == [
        "core/fine.py:2 core.nowhere (模块不存在)",
        "core/user.py:3 from core.real import gone",
    ]


def test_the_vision_routes_await_the_pipeline():
    """``understand()`` 是协程:路由与设备 WS 的 OCR 请求都得 await 它,不是丢进线程池。"""
    import inspect

    from core.vision_pipeline import VisionPipeline

    assert inspect.iscoroutinefunction(VisionPipeline.understand)
    for rel in ("core/routes/vision.py", "core/api_routes.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "pipeline.understand, " not in src, f"{rel} 又把 understand 丢进线程池了"
