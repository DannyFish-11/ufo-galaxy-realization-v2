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
import re
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
        """没装插件的话,下面那些 ini 键只是几行注释而已 —— 一点作用都没有。

        **这条原先写成 ``pytest.importorskip``,也就是插件不在时它自己「跳过」。**
        那正好是它要防的失效模式:插件一旦从环境里消失(比如某个作业不再装
        requirements-dev.txt、或依赖解析出岔),挂死保护静默归零,而这条守卫
        report 一个绿色的 SKIPPED —— 没有人会去看跳过的测试。

        改成硬断言。跑测试的环境就该按 requirements-dev.txt 装齐:仓库里所有
        真正跑 pytest 的 CI 作业都装了(逐个作业核过),本机 `pip install -r
        requirements-dev.txt` 也一样。这与「刻意用 ini 键而非 addopts」并不冲突
        —— 那条是为了让缺插件的环境**仍然跑得起来**;这条是让缺插件这件事
        **响亮地报出来**。一条清晰失败 ≠ pytest 起不来。
        """
        try:
            import pytest_timeout  # noqa: F401
        except ImportError:  # pragma: no cover - 只有环境坏掉时才走到
            pytest.fail(
                "pytest-timeout 未安装 —— 挂死的测试将永不中止,整轮 CI 会退回到"
                "「一个结论都拿不到」。请 `pip install -r requirements-dev.txt`。"
                "(不要把这条改回 importorskip:跳过等于把护栏失效伪装成绿灯)"
            )

    def test_timeout_is_armed_in_this_very_session(self, pytestconfig):
        """查**本次运行实际生效的值**,而不是只读 pytest.ini 的文本。

        上面几条都是读文件、比字符串 —— 它们证明"配置写对了",证明不了"这一轮
        真的带着它在跑"。两者能分开:命令行 ``--timeout=0`` 会把 ini 覆盖掉,
        ``-p no:timeout`` 会把插件整个关掉,pyproject 里的配置块也可能抢走优先级。
        任何一种发生,文本仍然完美,保护却已经没了。

        这条从 ``pytestconfig`` 取本次会话的有效值,是唯一能分辨这两者的判据。
        """
        assert pytestconfig.pluginmanager.hasplugin("timeout"), (
            "pytest-timeout 插件在本次会话里没有注册(是不是命令行加了 `-p no:timeout`?)" " —— 挂死的测试将永不中止"
        )

        effective = pytestconfig.getini("timeout")
        assert effective, f"本次会话的有效 timeout 是 {effective!r} —— 等于没有超时保护"
        assert float(effective) >= 90, f"本次会话有效 timeout={effective}s 太紧,最慢的真实用例已有 30s,会误伤"

        method = pytestconfig.getini("timeout_method")
        assert method == "signal", f"本次会话有效 timeout_method={method!r} —— thread 会杀掉整个进程,又拿不到完整清单"

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

    def test_ci_test_jobs_all_have_a_hard_ceiling(self):
        """作业级硬上限:挂死时至少得到一个明确的「作业超时」。

        没有它,挂死的作业会一直耗到 runner 被回收(实测有 64 分钟的),GitHub 只丢下一句
        "The runner has received a shutdown signal" —— 既没有失败清单,也没有任何线索。

        **这条原先只查名为 ``test`` 的那一个作业。** 后来测试被分片(见
        ``scripts/ci_test_shard.py``:一个进程扛 4 万多条用例会把 runner 压垮),
        真正跑测试的变成了 ``test-shard``,``test`` 退化为汇总。原判据于是**查错了对象** ——
        它盯着一个只 echo 一句话的作业,而放过了真正会挂死的那个。

        所以改成:**凡是测试相关的作业,一个都不许无界**。这比原来严格 ——
        原来只管一个,现在两个都管,将来再加分片作业也自动纳入。
        """
        import yaml

        ci = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        jobs = ci["jobs"]

        for name in ("test", "test-shard"):
            assert name in jobs, f"ci.yml 里找不到作业 {name!r} —— 守卫失效,先修守卫"
            job = jobs[name]
            assert "timeout-minutes" in job, f"{name} 作业没有 timeout-minutes,挂死时会耗到 runner 被回收"

        # 真正跑测试的那个:分片后单片实测 4 分 52 秒(11085 passed)。
        # 下限 15 分钟 ≈ 3 倍余量,足以吸收 runner 慢的那些天;
        # 上限 60 分钟 —— 再大就失去"及时止损"的意义,又变回耗到被回收。
        shard_ceiling = int(jobs["test-shard"]["timeout-minutes"])
        assert 15 <= shard_ceiling <= 60, f"test-shard 的 timeout-minutes={shard_ceiling} 不在合理区间"

        # 汇总作业只 echo 一句,给它一个小上限即可;大了等于没有。
        summary_ceiling = int(jobs["test"]["timeout-minutes"])
        assert summary_ceiling <= 15, f"汇总作业 timeout-minutes={summary_ceiling} 过大,失去止损意义"

    def test_the_sharded_job_is_the_one_that_runs_pytest(self):
        """守卫自检:确认"真正跑测试的是 test-shard"这个前提仍然成立。

        如果哪天有人把 pytest 挪回 ``test``、或改了作业名,上面那条会盯着错误的
        对象却**依然通过** —— 那正是它这次出问题的方式。这里把前提本身钉住。
        """
        import yaml

        ci = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        jobs = ci["jobs"]

        def runs_pytest(job) -> bool:
            return any("pytest" in str(step.get("run", "")) for step in job.get("steps", []))

        assert runs_pytest(jobs["test-shard"]), "test-shard 不再跑 pytest —— 分片结构变了,守卫需要跟着改"
        assert not runs_pytest(jobs["test"]), "test 变回直接跑 pytest 了 —— 那它也需要一个跑测试量级的上限"

    def test_not_hidden_in_addopts(self, ini):
        """必须是 ini 选项,不能塞进 addopts。

        没装 pytest-timeout 的环境下:ini 里的未知键只产生一条 PytestConfigWarning(exit 0),
        而 addopts 里的 ``--timeout`` 会让 pytest 直接报错、连测试都跑不起来。已实测。
        """
        addopts = ini.get("pytest", "addopts", fallback="")
        assert "--timeout" not in addopts, "--timeout 写进 addopts 会让没装插件的环境直接跑不起来"

    def test_no_ci_job_disarms_the_timeout_on_the_command_line(self):
        """命令行能悄悄把 ini 里配好的超时关掉,而所有读文件的守卫都察觉不到。

        ``--timeout=0`` 覆盖 ini 值;``-p no:timeout`` 直接卸掉插件。任一出现,
        pytest.ini 依旧完美、上面那些断言依旧全绿,而挂死保护已经归零 —— 症状
        就是再次退回「整轮没有结论」,而且这次连守卫都在替它背书。

        现状(逐个作业核过)只有 ``-p no:warnings``,与超时无关,故这条应当通过。

        ── 允许 ``--timeout-method=`` 的理由(本条曾是一刀切禁令)────────────────
        本守卫原本禁掉任何含 ``--timeout`` 的命令行。它的**本意**是"别把挂死保护
        关掉",而 ``--timeout-method=`` 改的是**打断机制**、不改超时秒数,不构成
        "关掉"。

        必须放行它,是因为 Windows 上 ``timeout_method = signal``(pytest.ini 的
        取值,基于实测选出)**根本无法工作** —— signal 方式依赖 SIGALRM,而 Windows
        没有这个信号。仓库首次在 windows-latest 上跑 CI 立刻撞到:

            AttributeError: module 'signal' has no attribute 'SIGALRM'
            (pytest_timeout.py:324 → INTERNALERROR → no tests ran)

        也就是说:不放行的话,Windows 作业连一条用例都跑不了 —— 那才是真正的
        "保护归零"。放行 method、继续禁 ``--timeout=<秒数>`` 覆盖与 ``no:timeout``
        卸载,才是这条规则的准确表达。

        仍然禁掉的:
          * ``--timeout=0`` / ``--timeout=<任何秒数>`` —— 会覆盖 ini 里的 120s
          * ``-p no:timeout`` —— 直接卸掉插件
        """
        # ``--timeout-method=...`` 放行；``--timeout=...``(含 =0)与 no:timeout 仍禁。
        _DISARM = re.compile(r"--timeout(?!-method)\b|no:timeout")

        offenders: list[str] = []
        for wf in sorted((REPO_ROOT / ".github/workflows").glob("*.yml")):
            text = wf.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if _DISARM.search(stripped):
                    offenders.append(f"{wf.name}:{lineno}: {stripped}")

        assert not offenders, "有 CI 作业在命令行上关掉/覆盖了 per-test 超时:\n" + "\n".join(offenders)

    def test_timeout_method_override_is_only_used_where_the_platform_forces_it(self):
        """放行 ``--timeout-method=`` 之后,防止它被随手用在 Linux 作业上。

        Windows 上是**没得选**(无 SIGALRM);Linux 上 signal 方式是实测选出来的
        (能打断单条并让整轮跑完拿到完整失败清单,thread 会杀掉整个进程)。
        所以这个覆盖只应出现在 windows runner 的作业里。
        """
        import yaml

        ci_path = REPO_ROOT / ".github/workflows/ci.yml"
        ci = yaml.safe_load(ci_path.read_text(encoding="utf-8"))

        offenders: list[str] = []
        for job_name, job in ci.get("jobs", {}).items():
            runs_on = str(job.get("runs-on", ""))
            for step in job.get("steps", []):
                run = str(step.get("run", ""))
                if "--timeout-method" in run and "windows" not in runs_on.lower():
                    offenders.append(f"{job_name} (runs-on: {runs_on})")

        assert (
            not offenders
        ), (
            "非 Windows 作业使用了 --timeout-method 覆盖 —— Linux 上应沿用 pytest.ini "
            "实测选出的 signal 方式:\n" + "\n".join(offenders)
        )


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
        # 不用 importorskip:插件缺失正是本文件要抓的失效模式,跳过等于放行。
        # 缺失时由 test_plugin_is_installed 给出那条带修复指引的失败,这里跟着红,
        # 两条一起指向同一件事。
        r = self._run(tmp_path, "signal")
        assert "Timeout" in r.stdout, f"挂住的用例没有被超时打断:\n{r.stdout[-2000:]}"
        assert "test_hangs_on_a_lock" in r.stdout
        assert "test_hangs_on_sleep" in r.stdout

    def test_the_run_continues_past_the_hang(self, tmp_path):
        """这正是选 signal 而非 thread 的全部理由 —— 挂住之后**后面的用例还得跑**。

        thread 方式会 dump 线程栈然后杀掉整个进程,``test_after`` 根本不会被执行,于是
        又回到「整轮拿不到完整清单」那个老问题上。
        """
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
