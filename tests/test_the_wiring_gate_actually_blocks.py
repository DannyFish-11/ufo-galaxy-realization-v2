#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_the_wiring_gate_actually_blocks.py

钉住：**接线闸不能只报告，要拦。**

这道闸(``scripts/check_wiring.py``)找的就是"实现了但没有任何调用方"的公开能力 ——
即"接了等于没接"。而它自己在 CI 里原来是 ``warning mode``：不带 ``--strict``，
于是**永远返回 0**，只打印、从不判失败。

一道只报告不拦截的闸，和它自己要防的那种毛病是同一个。

这不是理论上的：上一个 PR 引入的 ``load_anchor``(会话摘要跨重启取回)写侧接了、
读侧没接，这道闸**如实报了出来**，但 CI 照样全绿，于是那个功能带着断掉的一半合了
进去 —— 摘要存进磁盘、从来没读出来过，而且不报任何错。

本文件钉三件：

1. CI 与 ``make preflight`` **都**带 ``--strict``(两处必须一致，否则本地跑绿、
   CI 才红，或者更糟：反过来)；
2. ``--strict`` 真的会因为**新增**的未接线能力而非零退出 —— 钉行为，不钉参数字串；
3. ``--strict`` **不会**因为基线内的存量而非零退出 —— 否则这道闸一开就把 763 条
   历史债变成阻塞，那只会被人立刻关掉。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "check_wiring.py"


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


class TestBothCallSitesPassStrict:
    """本地与 CI 的跑法必须逐字一致，否则"本地过了"说明不了任何事。"""

    def test_ci_runs_it_strict(self):
        content = _read(".github/workflows/guardrails.yml")
        assert "check_wiring.py --strict" in content, "CI 里这道闸不带 --strict —— 它只会报告，永远不会让构建变红"

    def test_preflight_runs_it_strict(self):
        content = _read("Makefile")
        assert (
            "check_wiring.py --strict" in content
        ), "make preflight 与 CI 的参数漂了 —— 那个目标的全部意义就是逐字一致"

    def test_no_call_site_is_left_in_warning_mode(self):
        """漏网的那一处会让人以为已经拦住了。"""
        for rel in (".github/workflows/guardrails.yml", "Makefile"):
            content = _read(rel)
            for line in content.splitlines():
                if "check_wiring.py" in line and "--update-baseline" not in line and not line.lstrip().startswith("#"):
                    assert "--strict" in line, f"{rel} 里还有一处不带 --strict：{line.strip()}"


class TestStrictActuallyFailsOnSomethingNew:
    """钉**行为**，不钉参数字串 —— 参数在那儿但脚本不据此退出，等于没接。"""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args], capture_output=True, text=True, cwd=str(_ROOT), timeout=300
        )

    def test_the_repo_is_currently_clean(self):
        """先确认当下是干净的 —— 否则下面两条测的就不是同一件事。"""
        r = self._run("--strict")
        assert r.returncode == 0, f"仓库现在就有基线之外的未接线能力，这道闸一开 CI 就红：\n{r.stdout[-2000:]}"

    def test_an_existing_backlog_entry_does_not_fail_the_build(self, tmp_path, monkeypatch):
        """763 条历史债一条都不该让 CI 变红 —— 一开就阻塞的闸只会被立刻关掉。"""
        r = self._run("--strict", "--json")
        data = json.loads(r.stdout)
        assert data["baseline"] > 0, "基线是空的，这条测的东西就不存在了"
        assert data["known"], "基线内一条存量都没有？那说明基线与现状已经对不上了"
        assert not data["new"]
        assert r.returncode == 0

    def test_a_new_unwired_capability_fails_the_build(self, tmp_path):
        """真造一个"公开但零调用方"的能力，确认 --strict 真的非零退出。

        用真脚本跑真仓库(临时塞一个文件进 core/)，不 mock —— 这道闸的价值全在
        它对**真实目录树**的判断上。
        """
        planted = _ROOT / "core" / "_wiring_gate_probe_tmp.py"
        planted.write_text(
            '"""临时探针：验证接线闸真的会拦。测试结束即删。"""\n\n\n'
            "def a_capability_nobody_ever_calls_xyzzy() -> int:\n"
            "    return 42\n",
            encoding="utf-8",
        )
        try:
            strict = self._run("--strict")
            lenient = self._run()
            assert "a_capability_nobody_ever_calls_xyzzy" in strict.stdout, "新增的未接线能力根本没被发现"
            assert strict.returncode != 0, "--strict 发现了新增未接线能力却仍然退出 0 —— 这道闸拦不住任何东西"
            assert lenient.returncode == 0, "不带 --strict 时不该判失败（那是给人看现状用的）"
        finally:
            planted.unlink(missing_ok=True)
