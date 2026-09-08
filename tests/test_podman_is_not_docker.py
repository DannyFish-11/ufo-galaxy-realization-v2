"""Podman 那半边:引擎在 ≠ compose 连得上。

真跑挖出来的
------------
这台机器上装好 podman 之后:

* ``podman info`` **通** → ``daemon_up("podman")`` 返回 True
  → 启动器认为它就绪、什么都不做;
* 可 ``podman compose`` 会转发给 docker-compose,而后者要连
  ``unix:///run/podman/podman.sock`` —— 那个 socket 是**另一件事**::

      unable to get image 'nats:2.10-alpine': failed to connect to the
      docker API at unix:///run/podman/podman.sock ... no such file or directory

这是 Docker 那个缺陷的镜像版,而且更阴:Docker 是"引擎没起来",看得出来;
Podman 是"引擎起来了、但另一样东西没起来",看起来一切正常。

另外原来给 Podman 的提示是「试 `podman machine start`」—— 那是 macOS/Windows
的说法。Linux 上 podman 无守护、压根没有 machine,照着做的人会去启动一个
不存在的东西,跟在 Linux 上叫人"启动 Docker Desktop"是同一种错。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import core.container_runtime as cr
import launcher.services as svc


class TestEngineUpIsNotComposeReady:
    def test_the_two_judgements_are_separate(self):
        """混成一个判据,表现就是基础设施那行说不出为什么起不来。"""
        with patch.object(cr, "daemon_up", return_value=True):
            with patch.object(cr, "podman_api_socket", return_value=("/run/podman/podman.sock", False)):
                ready, why = cr.compose_api_ready("podman")
        assert ready is False
        assert "socket" in why

    def test_socket_present_means_ready(self):
        with patch.object(cr, "daemon_up", return_value=True):
            with patch.object(cr, "podman_api_socket", return_value=("/run/podman/podman.sock", True)):
                assert cr.compose_api_ready("podman") == (True, "")

    def test_engine_down_is_reported_as_engine_down(self):
        with patch.object(cr, "daemon_up", return_value=False):
            ready, why = cr.compose_api_ready("podman")
        assert ready is False
        assert "引擎" in why

    def test_docker_does_not_get_a_socket_check(self):
        """Docker 的 daemon_up 已经是"能不能说话"了,不必再查一遍。"""
        with patch.object(cr, "daemon_up", return_value=True):
            assert cr.compose_api_ready("docker") == (True, "")

    def test_an_unknown_socket_path_is_not_treated_as_down(self):
        """问不出路径 ≠ socket 没起来。别去拉一个不知道在哪的东西。"""
        with patch.object(cr, "daemon_up", return_value=True):
            with patch.object(cr, "podman_api_socket", return_value=("", False)):
                assert cr.compose_api_ready("podman") == (True, "")


class TestTheSocketPathComesFromPodman:
    def test_it_asks_podman_instead_of_guessing(self):
        """root 下是 /run/podman/podman.sock,rootless 在 $XDG_RUNTIME_DIR 底下,
        还随发行版变。写死一个必然有一半机器是错的。"""
        import inspect

        src = inspect.getsource(cr.podman_api_socket)
        assert "RemoteSocket" in src
        # 只看代码行 —— 文档串里举例说"root 下是 /run/podman/…"是在解释
        # 为什么不能写死,那是记录,不是写死。
        code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
        code = "\n".join(ln for ln in code if '"""' not in ln and "``" not in ln)
        assert "/run/podman" not in code, "路径不该写死在代码里"

    def test_no_podman_means_no_path(self):
        with patch.object(cr, "runtime_binary", return_value=None):
            assert cr.podman_api_socket() == ("", False)

    def test_a_failed_query_gives_no_path(self):
        with patch.object(cr, "runtime_binary", return_value="/usr/bin/podman"):
            with patch("subprocess.run", side_effect=OSError("起不来")):
                assert cr.podman_api_socket() == ("", False)


class TestHintsSpeakForThisMachine:
    def test_linux_is_not_told_to_start_a_machine(self):
        """Linux 上 podman 无守护,没有 machine 这个东西。"""
        with patch.object(svc.sys, "platform", "linux"):
            hint = svc._podman_engine_hint()
        assert "machine" not in hint

    def test_macos_is_told_about_the_machine(self):
        with patch.object(svc.sys, "platform", "darwin"):
            assert "machine" in svc._podman_engine_hint()

    def test_systemd_gets_the_unit_command(self):
        with patch.object(svc.sys, "platform", "linux"):
            with patch.object(svc, "_linux_has_systemd", return_value=True):
                assert "podman.socket" in svc._podman_api_hint()

    def test_no_systemd_gets_the_direct_command(self):
        """容器里走的就是这条 —— 没有 systemd,socket 单元起不来。"""
        with patch.object(svc.sys, "platform", "linux"):
            with patch.object(svc, "_linux_has_systemd", return_value=False):
                hint = svc._podman_api_hint()
        assert "podman system service" in hint
        assert "systemd" in hint

    def test_the_api_hint_points_at_the_log(self):
        with patch.object(svc.sys, "platform", "linux"):
            with patch.object(svc, "_linux_has_systemd", return_value=False):
                assert "日志" in svc._podman_api_hint()


class TestTheBringUpIsWired:
    def test_the_launcher_tries_to_start_the_socket(self):
        """构造得出来 ≠ 用上了。"""
        import inspect

        src = inspect.getsource(svc)
        assert "_try_start_podman_api(" in src

    def test_readiness_is_rechecked_after_the_engine_is_up(self):
        """引擎在之后还要再判一次 compose 连不连得上 —— 原来根本没有这一步,
        daemon_up 一 True 就直奔 compose,然后失败。"""
        import inspect

        src = inspect.getsource(svc.GalaxyUnified.ensure_docker_infra)
        assert "compose_api_ready" in src

    def test_there_is_a_distinct_status_for_api_down(self):
        """说成"未就绪"会让人去查引擎,而引擎根本没问题。"""
        import inspect

        src = inspect.getsource(svc.GalaxyUnified.ensure_docker_infra)
        assert "api_down" in src

    @pytest.mark.parametrize(
        "platform,expect",
        [("win32", "machine"), ("darwin", "machine"), ("linux", "podman system service")],
    )
    def test_bring_up_has_a_path_per_platform(self, platform, expect):
        import inspect

        src = inspect.getsource(svc._try_start_podman_api)
        assert expect in src

    def test_the_podman_log_is_registered(self):
        """提示语指向的日志必须在登记表里,否则那句话会退化成没有路径。"""
        from core.log_locations import get_log, log_hint

        assert get_log("podman") is not None
        assert "logs/podman.log" in log_hint("podman")
