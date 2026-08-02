"""
Galaxy - Test Configuration
================================

Shared fixtures and configuration for all tests.
"""

import asyncio
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 顶层模块名劫持防护：`import main` 必须拿到仓库根的 main.py
# ---------------------------------------------------------------------------
# 本仓有 128 个 ``nodes/*/main.py``。任何一个测试只要把某个节点目录插进
# ``sys.path``（``tests/integration/test_node108_metacognition.py:22`` 与
# ``tests/test_pr_a_multi_device_runtime_wiring.py:801`` 都这么干），此后
# 全进程的 ``import main`` 就可能解析到那个节点的 main.py —— 而且一旦被
# ``sys.modules`` 缓存，同分片里后续所有用例都跟着中招。
#
# CI 实证（test-shard (4)）：
#     AttributeError: <module 'main' from '.../nodes/Node_113_AndroidVLM/main.py'>
#     has no attribute 'ENV_FILE'
# 受害者是 test_phase0_env_check_secrets_banner.py 与
# test_setup_wizard_container_runtime.py —— 它们自己完全正确，单独跑必过，
# 只有在分片里排到污染者之后才挂。
#
# 与 test_no_test_hijacks_a_singleton.py 守的是同一类问题（进程级全局被某个
# 用例改写后不还原），只是这次被劫持的是**模块名空间**而不是单例对象。
#
# 这里在每个用例前做两件事：
#   1. 保证 PROJECT_ROOT 仍排在 sys.path 最前（有人 insert(0, 节点目录) 就纠正）；
#   2. 若 sys.modules["main"] 已经指向仓库外的文件，就逐出，让下次 import 重新解析。
# 两者都只在**检测到被污染时**动手，正常情况零开销、零行为改变。

_TOP_LEVEL_NAMES_TO_PROTECT = ("main",)


def _restore_project_root_import_precedence() -> None:
    """把 PROJECT_ROOT 拉回 sys.path 首位，并逐出被劫持的顶层模块。"""
    root = str(PROJECT_ROOT)
    if sys.path and sys.path[0] != root:
        # 不删除别人加的路径（可能确实需要），只是把仓库根重新排到最前。
        if root in sys.path:
            sys.path.remove(root)
        sys.path.insert(0, root)

    for name in _TOP_LEVEL_NAMES_TO_PROTECT:
        mod = sys.modules.get(name)
        if mod is None:
            continue
        origin = getattr(mod, "__file__", None)
        if not origin:
            continue
        try:
            resolved = Path(origin).resolve()
        except (OSError, ValueError):
            continue
        # 仓库根下的 main.py 才是对的；nodes/*/main.py 之类一律逐出。
        if resolved != (PROJECT_ROOT / f"{name}.py").resolve():
            sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _guard_top_level_module_hijack():
    """每个用例前后都校正一次 —— 前置保证自己拿到对的，后置不留给下一个。"""
    _restore_project_root_import_precedence()
    yield
    _restore_project_root_import_precedence()


# Set test environment variables
os.environ.setdefault("GALAXY_MODE", "test")
os.environ.setdefault("GALAXY_DEV_MODE", "1")
os.environ.setdefault("PYTHONPATH", str(PROJECT_ROOT))
# Auth is secure-by-default (GALAXY_AUTH_ENABLED=true): provide a test token so
# gateway lifespan auth validation passes (DEV_MODE no longer bypasses auth).
os.environ.setdefault("GALAXY_API_TOKEN", "galaxy-test-token")


# ---------------------------------------------------------------------------
# 把"会落盘的运行时数据"整体引到临时目录
# ---------------------------------------------------------------------------
# 有两条持久化路径会在跑测试时改写【被 git 跟踪的文件】：
#
#   1. CapabilityManager.register_capability() → config/capabilities.json
#      默认目录基于 __file__ 算,是仓库绝对路径,换 CWD 躲不掉。
#   2. KnowledgeBaseSystem.add_knowledge()    → knowledge_db/knowledge_entries.json
#      默认目录是 CWD 相对的 "./knowledge_db",而测试从仓库根启动。
#
# 后果不只是 git status 变脏：capabilities.json 会被测试期间注册的能力覆盖,
# 谁先跑就写谁的,本地跑完一次全套再 commit 就可能把测试产物提交进去
# （knowledge_db/knowledge_entries.json 就是这么进的仓库）。
#
# 这里在【模块级】设置,而不是用 fixture：CapabilityManager 是进程单例,config_dir
# 在第一次构造时就固定了,而那次构造可能发生在任何一个测试的 import 期间 —— 等到
# fixture 跑已经晚了。
_RUNTIME_TMP = tempfile.mkdtemp(prefix="galaxy-test-runtime-")
atexit.register(shutil.rmtree, _RUNTIME_TMP, ignore_errors=True)

# 能力配置：把仓库里的真实 capabilities.json 拷进临时目录,这样 _load_capabilities()
# 读到的内容与生产完全一致,只有【写】被引开。不拷的话能力表会从空开始,行为就变了。
_TMP_CONFIG_DIR = Path(_RUNTIME_TMP) / "config"
_TMP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
_REAL_CAPABILITIES = PROJECT_ROOT / "config" / "capabilities.json"
if _REAL_CAPABILITIES.is_file():
    shutil.copy2(_REAL_CAPABILITIES, _TMP_CONFIG_DIR / "capabilities.json")

# Android 设备状态 store：默认落在 tempfile.gettempdir()/galaxy_android_device_state_store.json，
# 也就是【整机共享的一个固定路径】，而且跨进程、跨测试轮次长期残留。
#
# 后果不只是脏文件。core.dual_repo_system_completeness_review 的 cross_repo_evidence
# 档位是这么判的：
#
#     runtime_cross_repo_activated = get_device_ecosystem_summary()["total_devices_with_snapshot"] > 0
#     label = complete if not gaps else evidence_gap
#
# 只要曾经有任意一条设备快照落过盘，那个 gap 就消失、档位升到 complete，于是
# tests/test_final_integrated_audit_verdict.py::...::test_I03_cross_repo_evidence_gap_consistent
# （断言必须是 evidence_gap）失败 —— 而且是**永久**失败：污染写进了 /tmp，之后每个
# 新进程读到的都是脏值，重跑、换分支都不会自愈，除非有人手动删文件。
#
# 这也是它在 CI 上表现为"顺序依赖"的原因：runner 的 /tmp 是干净的，所以要等同一分片里
# 某个先跑的测试写进快照，后面的 I03 才翻档。谁先跑取决于分片怎么切 —— 于是新增一个
# 测试文件就可能让它红/绿翻转，而真正的原因和那个新文件毫无关系。
#
# 该模块本身已经支持 ANDROID_DEVICE_STATE_STORE_PATH 覆盖，所以这里不必改生产代码，
# 把它引到本次会话的临时目录即可。
os.environ["ANDROID_DEVICE_STATE_STORE_PATH"] = str(Path(_RUNTIME_TMP) / "android_device_state_store.json")

# 跨设备消息总线：测试期间一律关掉。
#
# 与上面那条 /tmp store 是同一类污染，但更重：core.nats_server.EmbeddedNATSServer
# 在连不上 NATS 时会**自动下载 nats-server 二进制**装进 ~/.lumiv/bin，再拉起一个
# 监听 0.0.0.0:4222、**脱离测试进程长期存活**的常驻服务。也就是说跑一次测试会给这台
# 机器留下一个装好的二进制 + 一个常驻进程 + 一个被占的端口。
#
# 直接后果是 tests/test_mesh_worker_panel_toggle.py::TestWorkerToggleEndpoint::
# test_enable_returns_immediately_with_starting_true 的**永久红**：它断言 NATS 不可达
# 时 WorkerRuntime 必须如实落地 last_error（running 保持 False）。第一次跑的时候本机
# 确实没有 NATS —— 但那一次跑**自己**把服务器装上并拉起了；从此每个新进程都连得上，
# running 变 True，断言恒挂。重跑、换分支、清 workspace 都不自愈，除非有人手动杀进程。
#
# 它在 CI 上表现为"某个分片偶发失败"：runner 是干净的，所以要等同一分片里某条更早的
# 用例先把服务器拉起来，后面这条才翻红 —— 于是重新分片就能让红绿翻转，而真正的原因
# 和分片毫无关系。（和 I03 那条一模一样的套路。）
#
# core.nats_server / core.nats_bus 现在真正认这个开关（此前只有 unified_launcher 认，
# 提示文案却一直在教用户设它），关掉后总线降级为进程内内存 pub/sub：同进程内的
# publish/subscribe 语义完整保留，只是不再有网络、不再装东西、不再留常驻进程。
# 确需验证开关本身的用例（test_clone_to_use_startup_hardening 等）自己 monkeypatch 覆盖。
os.environ["GALAXY_NATS_ENABLED"] = "false"

# 以上几个都是硬设而非 setdefault：隔离不能被外部环境里一个残留的变量悄悄取消掉。
os.environ["GALAXY_CONFIG_DIR"] = str(_TMP_CONFIG_DIR)
os.environ["GALAXY_KNOWLEDGE_DIR"] = str(Path(_RUNTIME_TMP) / "knowledge_db")


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def nodes_dir():
    """Return the nodes directory."""
    return PROJECT_ROOT / "nodes"


@pytest.fixture
def config_dir():
    """Return the config directory."""
    return PROJECT_ROOT / "config"


# PR-18: Reset the recovery-readiness guard runtime before every test so that
# tests using the global singleton (ingest_delegated_execution_signal without
# guard_runtime) always start with a clean ring buffer.  Tests that need
# cross-call guard state (i.e. the PR-18 integration tests) use an explicit
# RecoveryReadinessRuntime() instance via the guard_runtime parameter and are
# unaffected by this reset.
@pytest.fixture(autouse=True)
def _reset_recovery_guard_runtime():
    """Auto-use: reset the global recovery-readiness runtime before each test."""
    try:
        from core.attached_runtime_recovery_readiness import (
            reset_recovery_readiness_runtime,
        )

        reset_recovery_readiness_runtime()
    except ImportError:
        pass
    yield


# PR-19: Reset the attached runtime session registry before every test so that
# tests using the global singleton always start with a clean registry.  Tests
# that need cross-call registry state use an explicit AttachedSessionRegistry()
# instance via the registry parameter and are unaffected by this reset.
@pytest.fixture(autouse=True)
def _reset_session_registry():
    """Auto-use: reset the global attached runtime session registry before each test."""
    try:
        from core.attached_runtime_session_registry import reset_session_registry

        reset_session_registry()
    except ImportError:
        pass
    yield


# 反自激励门是带【时间状态】的进程单例:任何测试只要走过一次朗读路径
# (speak_response / IncrementalSpeaker),就会往门里登记一段"刚说过的话",而它在留存
# 窗口内(默认 6 秒 + 按文本长度估算的朗读耗时)会让所有以 recently_spoke() 为条件的
# 门判定为"AI 正在说话"。于是后续测试里 ambient 感知的音频通路会被静默跳过 —— 单文件
# 跑全绿、整套跑失败,而且失败点离真正的污染源很远。这里逐测试清零,消除顺序依赖。
@pytest.fixture(autouse=True)
def _reset_voice_echo_guard():
    """Auto-use: 每个测试前清空反自激励门的"刚说过的话",避免跨测试污染。"""
    try:
        from core.voice_echo_guard import reset_echo_guard

        reset_echo_guard()
    except ImportError:
        pass
    yield
