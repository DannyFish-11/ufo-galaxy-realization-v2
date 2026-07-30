"""挂死的测试必须会被中止 —— 否则整轮 CI 一个结论都拿不到。

被修的问题
----------
仓库此前没有 ``pytest-timeout``,``pytest.ini`` 里也没有任何超时设置。于是**一条挂住的
测试会永久挂住**:pytest 不会中止它,整个作业只能等 runner 超时被回收。

实测后果(GitHub Actions ``test`` 作业,连续多次):

    14:59:43  ...test_returns_only_device_kind_entries            PASSED [99%]
    15:04:02  ...test_capability_filter_applied_to_device_entries PASSED       ← 隔 4 分 19 秒
    15:23:56  ...test_returns_empty_when_no_device_entries                     ← 开始,再无输出
    15:23:55  ##[error] The runner has received a shutdown signal

整轮 4 万多条测试**一个结论都没有**:没有失败清单,也没有任何线索指出卡在哪。同一个测试
类单独跑只要 4.32 秒、5 条全过 —— 说明不是这些用例本身有 bug,而是跑到全量套件尾部时才
出现的累积性挂起。main 自己也有同样签名(某次 test 作业卡 64 分钟被杀,同 run 其它 16 个
作业全绿),所以这不是某个 PR 引入的。

为什么这条测试值得存在
----------------------
超时配置是那种"配上了就没人再想起、被删掉也不会有人立刻发现"的东西 —— 而它一旦失效,
症状就是**再次退回到"整轮没有结论"**,排查成本极高(这次前后耗掉了一个多小时才定位)。
所以把三件事钉住:插件在、阈值在、方式是 signal。
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ini() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(REPO_ROOT / "pytest.ini", encoding="utf-8")
    return cfg


class TestTimeoutIsConfigured:
    def test_plugin_is_installed(self):
        """没装插件的话,下面那些 ini 键只是几行注释而已 —— 一点作用都没有。"""
        pytest.importorskip("pytest_timeout", reason="pytest-timeout 未安装 —— 挂死的测试将永不中止")

    def test_plugin_is_declared_in_dev_requirements(self):
        """CI 靠 requirements-dev.txt 装它。本机碰巧装了不算数。"""
        req = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        assert "pytest-timeout" in req, "pytest-timeout 不在 requirements-dev.txt 里,CI 上等于没有"

    def test_timeout_value_is_set_and_sane(self, ini):
        raw = ini.get("pytest", "timeout", fallback="")
        assert raw, "pytest.ini 里没有 timeout —— 挂死的测试将永不中止"
        value = int(raw)
        # 下限:实测仓库最慢的真实用例是 30.11s(test_dispatch_task_uses_websocket_from_local_cache),
        # 阈值必须留足余量,否则会把正常的慢测试误判成超时。
        assert value >= 90, f"timeout={value}s 太紧,最慢的真实用例已有 30s,会误伤"
        # 上限:太宽就抓不住异常者了 —— CI 上那个病态用例耗了 4 分 19 秒(259s)。
        assert value <= 240, f"timeout={value}s 太宽,抓不住 CI 上那个 259s 的异常用例"

    def test_method_is_signal_not_thread(self, ini):
        """这个选择是实测出来的,不是偏好。

        * ``signal`` —— 打断那一条并如实报成 failure,**整轮继续跑完**,拿得到完整失败清单;
        * ``thread`` —— dump 所有线程栈后**直接杀进程**,整轮中止,还是拿不到清单。

        我们要的正是"完整清单 + 指出卡在哪",所以只能是 signal。
        """
        method = ini.get("pytest", "timeout_method", fallback="")
        assert method == "signal", (
            f"timeout_method={method!r} —— thread 方式会杀掉整个进程," "又回到「整轮没有结论」那个老问题上;应为 signal"
        )

    def test_faulthandler_backstop_is_set(self, ini):
        """不依赖信号的兜底诊断。

        per-test 超时**本地实测有效**,但在 CI 上没救回来:作业仍挂死在 92%,日志逐字节停住
        四十多分钟,**一条 Timeout 行都没有**。原因可能是挂点不在 pytest_runtest_protocol
        覆盖范围内(pytest-timeout 只挂这一个钩子),也可能卡在不响应信号递送的 C 调用里。

        faulthandler 走独立看门狗线程、不经过信号,所以上面那条不管为什么失灵,它都照样能打出
        **每个线程**的完整堆栈(实测精确到文件与行号)。它只 dump 不终止 —— 终止由作业级
        timeout-minutes 负责。
        """
        raw = ini.get("pytest", "faulthandler_timeout", fallback="")
        assert raw, "没有 faulthandler_timeout —— per-test 超时一旦失灵就再没有任何线索"
        assert int(raw) >= 60, f"faulthandler_timeout={raw}s 太紧,会在正常慢用例上刷无用堆栈"

    def test_ci_test_job_has_a_hard_ceiling(self):
        """作业级硬上限:挂死时至少得到一个明确的「作业超时」。

        没有它,挂死的作业会一直耗到 runner 被回收(实测有 64 分钟的),GitHub 只丢下一句
        "The runner has received a shutdown signal" —— 既没有失败清单,也没有任何线索。
        """
        import yaml

        ci = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        job = ci["jobs"]["test"]
        assert "timeout-minutes" in job, "test 作业没有 timeout-minutes,挂死时会耗到 runner 被回收"
        # 正常全量约 20 分钟;上限要留足余量,但不能大到失去意义。
        assert 30 <= int(job["timeout-minutes"]) <= 90, f"timeout-minutes={job['timeout-minutes']} 不在合理区间"

    def test_not_hidden_in_addopts(self, ini):
        """必须是 ini 选项,不能塞进 addopts。

        没装 pytest-timeout 的环境下:ini 里的未知键只产生一条 PytestConfigWarning(exit 0),
        而 addopts 里的 ``--timeout`` 会让 pytest 直接报错、连测试都跑不起来。已实测。
        """
        addopts = ini.get("pytest", "addopts", fallback="")
        assert "--timeout" not in addopts, "--timeout 写进 addopts 会让没装插件的环境直接跑不起来"


#: 丢给子进程去跑的迷你套件:两种真实挂法,前后各夹一条正常用例。
#: 用它来证明「挂住的那条被打断」且「整轮继续跑完」。
_HANG_SUITE = """
import threading, time

def test_before():
    assert True

def test_hangs_on_a_lock():
    lock = threading.Lock()
    lock.acquire()
    lock.acquire()          # 永久阻塞

def test_hangs_on_sleep():
    time.sleep(3600)

def test_after():
    assert True
"""


class TestItActuallyInterruptsAHang:
    """光有配置不够 —— 得证明它真的能打断挂住的测试,而且不掐掉整轮。

    为什么必须用子进程
    ------------------
    我第一版是在**本进程内**写两条会挂的用例,再用 ``pytest.raises`` 去接。那是错的:
    pytest-timeout 抛的 ``_pytest.outcomes.Failed`` 继承自 ``BaseException``,
    ``pytest.raises(Exception)`` 根本抓不住;更根本的是**超时本身就是这条用例的失败**,
    不存在"在用例内部捕获它"这回事 —— 那一版直接把自己写成了 2 failed。

    正确的验法是把挂法丢进**子进程**的 pytest 里,再检查它的输出与退出行为。
    """

    @staticmethod
    def _run(tmp_path, method: str):
        import subprocess
        import sys

        (tmp_path / "test_hang_demo.py").write_text(_HANG_SUITE, encoding="utf-8")
        (tmp_path / "pytest.ini").write_text(f"[pytest]\ntimeout = 3\ntimeout_method = {method}\n", encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-v", str(tmp_path)],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=90,  # 若超时机制彻底失效,子进程会挂住 —— 这里兜住,不拖垮本轮
        )

    def test_a_hang_is_interrupted_and_reported(self, tmp_path):
        pytest.importorskip("pytest_timeout")
        r = self._run(tmp_path, "signal")
        assert "Timeout" in r.stdout, f"挂住的用例没有被超时打断:\n{r.stdout[-2000:]}"
        assert "test_hangs_on_a_lock" in r.stdout
        assert "test_hangs_on_sleep" in r.stdout

    def test_the_run_continues_past_the_hang(self, tmp_path):
        """这正是选 signal 而非 thread 的全部理由 —— 挂住之后**后面的用例还得跑**。

        thread 方式会 dump 线程栈然后杀掉整个进程,``test_after`` 根本不会被执行,于是
        又回到「整轮拿不到完整清单」那个老问题上。
        """
        pytest.importorskip("pytest_timeout")
        r = self._run(tmp_path, "signal")
        assert "test_after" in r.stdout, f"超时之后整轮被掐断了,后续用例没跑:\n{r.stdout[-2000:]}"
        assert (
            "2 failed" in r.stdout and "2 passed" in r.stdout
        ), f"期望恰好 2 挂 2 过(前后两条正常用例都要跑到):\n{r.stdout[-2000:]}"

    def test_without_the_timeout_it_would_hang_forever(self, tmp_path):
        """反证:关掉超时,同一份套件会挂到子进程超时为止。

        没有这条,上面两条只能说明"现在能中止",无法说明"以前会挂死"—— 而"会挂死"正是
        这次要修的东西。
        """
        import subprocess
        import sys

        (tmp_path / "test_hang_demo.py").write_text(_HANG_SUITE, encoding="utf-8")
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")  # 不设超时
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(
                [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", str(tmp_path)],
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
                timeout=20,
            )
