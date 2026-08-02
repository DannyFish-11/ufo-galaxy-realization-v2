"""密钥扫描的配置必须**真的生效**,而不是看起来配好了。

这个文件守两件已经实际发生过的失效,两件的共同点是:**门是绿的,配置是死的**。

## 一、`.gitleaks.toml` 的 allowlist `paths` 写成了 glob,不是正则

gitleaks 的 allowlist ``paths`` 是**正则**。仓库里原先写的是 shell 通配符样子:

    "*.example.*"     ← 以 * 开头,根本不是合法正则
    "*.example"       ← 同上
    "README_*.md"     ← 能编译,但 `_*` 在正则里是"零个或多个下划线",语义跑偏

实测(两个版本的 gitleaks,同一份探针语料:``docs/guide.md`` /
``config/services_config.example.json`` / ``plain.py``,三份内容相同、都含一条
会被 generic-api-key 命中的字符串):

    gitleaks 8.24.3(CI 当前实际用的版本)
        改前 → 3 条,docs/ 与 *.example.* 两条**都没被豁免**
        改后 → 3 条,逐条相同   ← 所以修正是**行为中性**的,不是放松扫描

    gitleaks 8.28.0
        改前 → **直接 panic 退出**(regexp: Compile(`*.example.*`) 失败)
        改后 → 1 条,白名单如期生效

也就是说:那一整块路径豁免在 CI 上**从来没生效过**,而且一旦
``gitleaks-action`` 把默认版本升过 8.28,这道门会从"豁免不生效"变成"整个作业
硬崩"。两种都不好,而且都不会有人主动发现。

## 二、workflow 传给 gitleaks-action 的 `args` 被整个丢弃

``gitleaks-action@v2`` **不接受 ``args`` 输入**。原先那一步传了 6 个 flag,
runner 每次都打:

    ##[warning]Unexpected input(s) 'args', valid inputs are ['']

然后全部丢掉,自己拼命令。其中 ``--no-git`` 那条**改变了语义**:原意是扫工作树,
实际扫的是提交区间。这条有实际操作后果 —— 在后续提交里把泄漏的行删掉是
**清不掉这道门**的,坏行仍在历史提交的 diff 里,必须改写那个提交。

(保留 action 的默认行为是有意的:提交过又删掉的密钥依然是泄漏了,只扫工作树
反而会漏掉这一类。删掉失效的 args 是为了不让配置继续撒谎。)
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"
GUARDRAILS_WORKFLOW = REPO_ROOT / ".github/workflows/guardrails.yml"


@pytest.fixture(scope="module")
def config() -> dict:
    return tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))


def _all_allowlist_paths(config: dict) -> list[tuple[int, str]]:
    """(块序号, 路径正则) 的扁平列表。块序号只是为了报错时好定位。"""
    out: list[tuple[int, str]] = []
    for i, block in enumerate(config.get("allowlists", []), 1):
        for p in block.get("paths", []):
            out.append((i, p))
    return out


def test_there_are_allowlist_paths_to_check(config):
    """守卫自检。

    如果哪天 allowlists 被整块删掉或改名,下面那些"逐条检查"会在空列表上
    **全部通过** —— 那正是这类守卫最常见的失效方式。
    """
    paths = _all_allowlist_paths(config)
    assert len(paths) >= 5, f"只找到 {len(paths)} 条 allowlist path,配置结构可能变了,先修守卫"


@pytest.mark.parametrize("block,pattern", _all_allowlist_paths(tomllib.loads(GITLEAKS_CONFIG.read_text("utf-8"))))
def test_allowlist_path_is_a_valid_regex(block: int, pattern: str):
    """每条 path 必须是合法正则。

    gitleaks 8.28+ 遇到非法正则**直接 panic**,整个作业崩掉;8.24.3 则是静默
    吞掉、豁免不生效。两种失效都不会有人主动发现。

    这里用 Python 的 ``re`` 做代理检查。它与 Go 的 RE2 语法不完全等价,但
    "以 ``*`` / ``+`` / ``?`` 开头"这类**重复算符没有作用对象**的错误,两边
    判定一致 —— 而这正是把 glob 当正则写时会犯的错。
    """
    try:
        re.compile(pattern)
    except re.error as exc:
        pytest.fail(
            f"第 {block} 块的 allowlist path {pattern!r} 不是合法正则({exc})。" f"gitleaks 的 paths 是正则,不是 glob。"
        )


@pytest.mark.parametrize("block,pattern", _all_allowlist_paths(tomllib.loads(GITLEAKS_CONFIG.read_text("utf-8"))))
def test_allowlist_path_does_not_look_like_a_shell_glob(block: int, pattern: str):
    """比"能编译"更严一档:不许长得像 shell 通配符。

    ``README_*.md`` 能编译,但含义是"README_ 后跟零个或多个下划线",与作者想表达的
    "README_ 开头的任意 .md" 完全不同 —— 这种**编译得过、语义跑偏**的写法比直接
    报错更危险,因为永远不会有人发现。
    """
    assert not pattern.startswith("*"), f"第 {block} 块的 {pattern!r} 以 * 开头 —— 这是 glob 写法,正则里非法"
    assert "_*" not in pattern, (
        f"第 {block} 块的 {pattern!r} 含 `_*` —— 在正则里这是「零个或多个下划线」,"
        f"多半是想写 glob 的 `_*`(任意字符)。应写成 `_.*`。"
    )


def test_gitleaks_step_does_not_pass_args_the_action_ignores():
    """``gitleaks-action@v2`` 不接受 ``args``,传了会被整个丢弃。

    原先传的 6 个 flag 里,``--no-git`` 那条**改变了扫描语义**(工作树 vs 提交
    区间),却一直没生效。配置写着一套、实际跑另一套,是最难查的一类问题:
    没有任何断言会失败,只有 runner 日志里一句不起眼的 warning。
    """
    wf = yaml.safe_load(GUARDRAILS_WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["secret-scan"]["steps"]

    gitleaks_steps = [s for s in steps if "gitleaks-action" in str(s.get("uses", ""))]
    assert gitleaks_steps, "secret-scan 里找不到 gitleaks-action 步骤 —— 守卫失效,先修守卫"

    for step in gitleaks_steps:
        given = step.get("with") or {}
        assert "args" not in given, (
            "gitleaks-action@v2 不接受 `args` 输入,传了只会得到一句 "
            "`Unexpected input(s) 'args'` 然后被全部丢弃。"
            "需要改扫描行为的话得换成直接调 gitleaks 二进制,而不是传一堆不生效的 flag。"
        )
