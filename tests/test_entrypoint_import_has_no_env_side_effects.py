"""入口脚本的 ``import`` 不得改写 ``os.environ``。

## 修的是什么

`main.py` 与 `unified_launcher.py` 顶部各有一段模块级代码,把 `.env` 和
`runtime/secrets.env` 里的值灌进 `os.environ`。作为**脚本运行**时这是对的
——它们就该在其它 import 读环境变量之前把配置装好。

问题在于这段代码是**无条件的模块级副作用**:任何一次 `import main` 都会执行
它。测试里有 4 处 `import main`(其中 3 处只为读一个哨兵常量),于是:

    tests/integration/test_integration_review_runtime_paths.py::…
        import main as _main            # 只想确认 SYSTEM_ORCHESTRATOR_AUTHORITY 存在
            ↓ main.py 模块级
        把本机 .env 的全部非空值灌进 os.environ
            ↓ 此后整个 pytest 进程都带着,退不回去
        MEMORY_DB_PATH=/app/data/…      → Node_100 建库失败(2 条)
        DEEPSEEK_API_KEY=… 等凭空出现   → "缺 key 时不该入候选池"类断言失败(6 条)

实测:跟着 INSTALL.md 走完(bootstrap 会生成 .env)再跑全量,多出 8 条与改动
毫无关系的失败;把 .env 移开,同一批用例 197 passed。**CI 上没有 .env,所以
这 8 条永远不会在 CI 上出现 —— 只砸本机开发者**,而且顺序依赖、极难归因。

## 修法

把加载逻辑收进函数,调用点放在 ``if __name__ == "__main__":`` 守卫下。
`python main.py` / `python unified_launcher.py` 行为逐字节不变(守卫为真、
仍在其余 import 之前);`import main` 变成无副作用。

## 这里守什么

三层,缺一层都能被绕过:

1. **结构层(AST)**:模块级不得有任何写 `os.environ` 的语句 —— 这条最硬,
   不依赖跑测试的机器上有没有 .env。
2. **行为层**:加载函数本身的三条纪律(空值/# 毒值/不覆盖)必须还在 ——
   防止有人为了"修副作用"把整段逻辑删掉了事。
3. **端到端**:真的起一个子进程 `import main`,比对前后 `os.environ`。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINTS = ["main.py", "unified_launcher.py"]


# ── 1. 结构层:模块级不得写 os.environ ──────────────────────────────────


def _module_level_environ_writes(source: str) -> list[int]:
    """返回模块级(不含函数体、不含 ``if __name__ == "__main__"`` 块)里
    所有写 ``os.environ[...]`` 的行号。

    只看**顶层**语句:函数体里怎么写都行(要被显式调用才生效),
    ``__main__`` 守卫里怎么写也行(那就是"作为脚本运行"的语义)。
    """
    tree = ast.parse(source)

    def is_main_guard(node: ast.AST) -> bool:
        if not isinstance(node, ast.If):
            return False
        return "__name__" in ast.dump(node.test) and "__main__" in ast.dump(node.test)

    hits: list[int] = []
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # 函数/类体内不算模块级副作用
        if is_main_guard(top):
            continue  # 作为脚本运行时才执行,正是我们想要的
        for node in ast.walk(top):
            # os.environ["X"] = ... / _os.environ[...] = ...
            if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
                if isinstance(node.value, ast.Attribute) and node.value.attr == "environ":
                    hits.append(node.lineno)
            # os.environ.update(...) / .setdefault(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"update", "setdefault", "pop"}:
                    tgt = node.func.value
                    if isinstance(tgt, ast.Attribute) and tgt.attr == "environ":
                        hits.append(node.lineno)
    return sorted(set(hits))


@pytest.mark.parametrize("entry", ENTRYPOINTS)
def test_entrypoint_module_level_does_not_write_environ(entry: str) -> None:
    src = (REPO_ROOT / entry).read_text(encoding="utf-8")
    hits = _module_level_environ_writes(src)
    assert not hits, (
        f"{entry} 在模块级写了 os.environ(行 {hits})—— "
        f"这样 `import {Path(entry).stem}` 就会把本机 .env 灌进整个进程。"
        f'把它收进函数,调用点放到 `if __name__ == "__main__":` 下。'
    )


@pytest.mark.parametrize("entry", ENTRYPOINTS)
def test_entrypoint_still_loads_env_when_run_as_script(entry: str) -> None:
    """守卫的另一半:不能为了消副作用把加载**整个删掉**。

    单独运行 `python main.py` 时 .env 必须仍然被装进 os.environ —— 那是真机
    复现过的老 bug(「模型」tab 存的 API Key 重启后读不到)的修复所在。
    """
    tree = ast.parse((REPO_ROOT / entry).read_text(encoding="utf-8"))
    guarded_calls: list[str] = []
    for top in tree.body:
        if not isinstance(top, ast.If):
            continue
        if "__name__" not in ast.dump(top.test) or "__main__" not in ast.dump(top.test):
            continue
        for node in ast.walk(top):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                guarded_calls.append(node.func.id)

    assert any("env" in name for name in guarded_calls), (
        f'{entry} 的 `if __name__ == "__main__"` 块里找不到 .env 加载调用'
        f"(找到的调用:{guarded_calls})—— 作为脚本运行时 .env 必须仍被加载"
    )


# ── 2. 行为层:加载纪律三条 ─────────────────────────────────────────────


@pytest.fixture
def clean_environ():
    """快照 / 还原 os.environ。

    被测函数直接写 os.environ,monkeypatch 追踪不到,必须自己兜。
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)


def _write_env(root: Path, env_text: str = "", store_text: str = "") -> None:
    """写出 tmp 版的 .env 与密钥库 runtime/secrets.env。

    ``store_text`` 写的就是 runtime/secrets.env。之所以形参不叫 ``secrets_text``、
    造出来的假值一律带 ``FAKE_`` 前缀:gitleaks 的 generic-api-key 规则按
    「关键词(secret/token/key/…)+ 赋值 + 十字符以上的值」判定,一个叫
    ``secrets_text="…"`` 的具名实参会**如实**命中它。仓库 .gitleaks.toml 里
    已经为测试目录留了 ``FAKE_`` / ``sk-test-`` / ``PLACEHOLDER_`` 三个白名单
    前缀,这里照着用 —— 让扫描器继续对真泄漏敏感,而不是去放宽白名单。
    """
    (root / ".env").write_text(env_text, encoding="utf-8")
    (root / "runtime").mkdir(exist_ok=True)
    (root / "runtime" / "secrets.env").write_text(store_text, encoding="utf-8")


def _loader():
    import main as _main

    return _main.load_env_files_into_environ


def test_loads_real_values(tmp_path, clean_environ):
    _write_env(tmp_path, "GALAXY_TEST_REAL=yes\n")
    os.environ.pop("GALAXY_TEST_REAL", None)

    _loader()(root=str(tmp_path))

    assert os.environ.get("GALAXY_TEST_REAL") == "yes"


def test_empty_value_is_treated_as_unconfigured(tmp_path, clean_environ):
    """空值进 os.environ 会顶掉代码默认值。

    真机症状:设置面板生成的 .env 把全部 schema 键写成 ``KEY=``,于是
    ``os.environ.get("OLLAMA_URL", "http://localhost:11434")`` 返回 ``""``,
    LocalBrainManager 拿空 URL 去 ping Ollama。
    """
    _write_env(tmp_path, "GALAXY_TEST_EMPTY=\n")
    os.environ.pop("GALAXY_TEST_EMPTY", None)

    _loader()(root=str(tmp_path))

    assert "GALAXY_TEST_EMPTY" not in os.environ
    assert os.environ.get("GALAXY_TEST_EMPTY", "fallback") == "fallback"


def test_inline_comment_poison_value_is_rejected(tmp_path, clean_environ):
    """python-dotenv 会把「空值 + 行内注释」整段注释当成值。

    实测 1.2.2:``OLLAMA_URL= # e.g. http://...`` → ``'# e.g. http://...'``,
    经 normalize 补协议头后变成 ``http://#...`` 的怪 URL,骗过全部 startswith
    检查。以 # 开头的值一律视同未配置。
    """
    _write_env(tmp_path, "GALAXY_TEST_POISON= # e.g. http://localhost:1234\n")
    os.environ.pop("GALAXY_TEST_POISON", None)

    _loader()(root=str(tmp_path))

    assert "GALAXY_TEST_POISON" not in os.environ


def test_existing_environ_wins(tmp_path, clean_environ):
    """shell/系统显式导出的优先级最高,不被 .env 覆盖。"""
    _write_env(tmp_path, "GALAXY_TEST_PRIO=from_dotenv\n")
    os.environ["GALAXY_TEST_PRIO"] = "from_shell"

    _loader()(root=str(tmp_path))

    assert os.environ["GALAXY_TEST_PRIO"] == "from_shell"


def test_secrets_env_is_loaded_too(tmp_path, clean_environ):
    """密钥库(runtime/secrets.env)必须一起加载。

    设置面板把 API Key 写进它而非 .env(见 core/config_store.py);此前重启后
    没人把它注回 os.environ,直读 os.getenv 的路径(含面板"已配置"角标)全都
    看不到,表现为"Key 存了,重启后又显示未配置"。
    """
    _write_env(tmp_path, "", store_text="GALAXY_TEST_FROM_STORE=FAKE_sk-test-value\n")
    os.environ.pop("GALAXY_TEST_FROM_STORE", None)

    _loader()(root=str(tmp_path))

    assert os.environ.get("GALAXY_TEST_FROM_STORE") == "FAKE_sk-test-value"


def test_secrets_env_wins_over_dotenv(tmp_path, clean_environ):
    """先到先得:secrets.env 先加载 = 面板保存的最新真值优先。"""
    _write_env(
        tmp_path,
        "GALAXY_TEST_BOTH=FAKE_from_dotenv\n",
        store_text="GALAXY_TEST_BOTH=FAKE_from_store\n",
    )
    os.environ.pop("GALAXY_TEST_BOTH", None)

    _loader()(root=str(tmp_path))

    assert os.environ["GALAXY_TEST_BOTH"] == "FAKE_from_store"


def test_missing_files_are_not_an_error(tmp_path, clean_environ):
    """全新克隆(还没跑 bootstrap)时两个文件都不存在,不能炸。"""
    _loader()(root=str(tmp_path))  # 不抛异常即通过


# ── 3. 端到端:子进程真 import ──────────────────────────────────────────

_PROBE = r"""
import json, os, sys
sys.path.insert(0, {root!r})
before = dict(os.environ)
import {module}  # noqa: F401
after = dict(os.environ)
added = {{k: v for k, v in after.items() if k not in before}}
changed = {{k for k in before if before[k] != after.get(k)}}
print(json.dumps({{"added": sorted(added), "changed": sorted(changed)}}))
"""


@pytest.mark.parametrize("module", ["main", "unified_launcher"])
def test_importing_entrypoint_changes_nothing_in_environ(module: str) -> None:
    """真的起一个子进程 import,比对前后 os.environ。

    这条是**用当前这台机器上真实存在的 .env** 来验的:CI 上没有 .env,它退化
    成一条弱断言(仍能抓住"import 时凭空造环境变量"的其它写法);本机开发者
    跑起来则是完整的端到端复现 —— 正好是唯一会被这个 bug 砸到的人。
    """
    code = _PROBE.format(root=str(REPO_ROOT), module=module)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"子进程 import {module} 失败:\n{proc.stderr[-3000:]}"

    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not result["added"], f"`import {module}` 凭空新增了环境变量:{result['added']}"
    assert not result["changed"], f"`import {module}` 改写了已有环境变量:{result['changed']}"


_SCRIPT_MODE_PROBE = r"""
import json, os, runpy, sys
before = dict(os.environ)
sys.argv = ["main.py", "--help"]          # argparse 打完帮助就 SystemExit(0)
try:
    runpy.run_path({main_py!r}, run_name="__main__")
except SystemExit:
    pass
added = sorted(k for k in os.environ if k not in before)
sys.stderr.write("PROBE=" + json.dumps(added) + "\n")
"""


def test_running_main_as_a_script_still_configures_the_process() -> None:
    """守卫的反面:``python main.py`` 必须仍然做那三件进程级配置。

    只把副作用挪进函数、却忘了在 ``__main__`` 下调用,会静悄悄地把一堆真机修复
    全部废掉(.env 里的 API Key 重启后又读不到、HF 走回被墙的 huggingface.co
    卡 4 分钟)。所以这里真的用 ``run_name="__main__"`` 跑一遍 main.py。

    哨兵选 ``HF_HUB_DISABLE_TELEMETRY``:它是无条件 ``setdefault``,不依赖这台
    机器上有没有 .env —— CI 上没有 .env 也照样是一条硬断言。
    """
    code = _SCRIPT_MODE_PROBE.format(main_py=str(REPO_ROOT / "main.py"))
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    probe = [ln for ln in proc.stderr.splitlines() if ln.startswith("PROBE=")]
    assert probe, f"探针没跑到底(退出码 {proc.returncode}):\n{proc.stderr[-3000:]}"

    added = json.loads(probe[-1][len("PROBE=") :])
    assert "HF_HUB_DISABLE_TELEMETRY" in added, (
        '`python main.py` 没有执行进程级配置 —— `if __name__ == "__main__"` '
        f"守卫里大概漏了调用。本次新增的环境变量:{added}"
    )
