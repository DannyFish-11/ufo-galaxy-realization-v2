"""launcher/services.py — 服务编排（从 ``unified_launcher.py`` 原样搬来）

它是什么
--------
Galaxy 全部后台服务的编排层：Docker 基建、NATS（embedded / external / no-op
三态）、Tailscale、本地大脑与主脑选择、语音交互、系统托盘、进程看守、
``entrypoint.json`` 写出、优雅停止与状态展示。

搬迁纪律：**物理移动，不是重写**
--------------------------------
这 1954 行来自 ``unified_launcher.py``，逐字节移动。与
:mod:`launcher.nodes` 那次同一个理由：里面密布真机故障攒出来的判据 ——
NATS 三态的降级语义、主脑选择与拉取的时序（``start_local_brain`` 必须排在拉取
之前，否则撞竞态）、端口可绑定探测、URL 哨兵、弱网下的重试……手抄一遍必然丢掉
其中几条，而丢掉哪条要等真机上出问题才知道。

移动会**静默改变语义**的地方（已逐处修）
----------------------------------------
``Path(__file__).parent`` —— 原文件住在仓库根，这个表达式就是仓库根；搬进
``launcher/`` 之后它指向 ``launcher/``。后果不是报错，而是 ``sys.path`` 插错、
``cwd`` 指错、``.env`` 找不到 —— 全都静默。所以显式算 :data:`PROJECT_ROOT`。

注意 ``Path("electron")`` / ``Path("logs")`` 这类**相对 cwd** 的路径不受影响：
它们依赖的是进程工作目录而非模块位置，移动前后一样（这是既有行为，本次不改）。

``unified_launcher.py`` 现在只剩 CLI 外壳，从这里 re-export 公开名字，让既有
importer（``main.py`` 与六个测试文件）在并存期继续可用。它在步骤 8 删除。

刻意的边界
----------
桌面壳的自愈已经在 :mod:`launcher.shell`；节点生命周期在 :mod:`launcher.nodes`。
本模块只管**服务编排**，那两块只调不重复实现。
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.ascii_art import Colors, print_banner, print_section_header, print_status_row
from core.credential_vault import PLACEHOLDER_PREFIXES

#: 仓库根。**搬迁必须显式算**：原文件在仓库根，用的是 ``Path(__file__).parent``；
#: 搬进 ``launcher/`` 后同一个表达式指向 ``launcher/`` —— sys.path 会插错、
#: 子进程 cwd 会指错、``.env`` 会找不到，而且**全都不报错**。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 这里原本还有一段模块级的
#: ``try: from nodes.common.cors_config import get_cors_origins / except ImportError:``
#: 内联兜底函数（随 ``unified_launcher.py`` 一起搬来的）。搬迁时逐行核过：
#: **它是死代码** —— 唯一的调用点 ``start_web_ui()`` 在函数体内又 ``from
#: nodes.common.cors_config import get_cors_origins, get_cors_methods,
#: get_cors_headers`` 了一次，局部名把模块级的那个完全遮蔽，兜底分支永远走不到；
#: 而那次局部 import 本身就在一个大 ``try/except`` 里，缺依赖时的行为由它决定。
#: 全仓也没有第二处 ``from launcher.services import get_cors_origins``。
#: 所以删掉它既不改行为，也顺带消掉 ``scripts/check_debt_freeze.py`` CHECK-3
#: 盯的那类"内联 ImportError 兜底定义"（见 docs/migration/DEPRECATION_POLICY.md §4）
#: —— 不是把它加进豁免名单，是把这笔债真的还掉。
logger = logging.getLogger("Galaxy")


def print_status(message: str, status: str = "info"):
    """打印状态信息（单行，无值列）。"""
    print_status_row(message, status=status)


def _url_sentinel_audit() -> Tuple[str, str, str, List[Dict[str, str]]]:
    """收集克隆界面「启动自检」要展示的取证数据(全 best-effort,绝不抛)。

    返回 (代码版本, OLLAMA_URL 环境值 repr, 解析后地址, 哨兵抓到的记录列表)。
    真机排查两大痛点直接摆上界面:1) 镜像新旧一眼可辨(代码版本);2) URL 哨兵
    抓到的缺协议头请求不再只进日志——用户在克隆界面就能看到 URL + 罪魁 file:line。
    """
    version = "unknown"
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%h %cd", "--date=format:%Y-%m-%d %H:%M"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=str(PROJECT_ROOT),  # 搬迁修正：原为 __file__ 所在目录(仓库根)
        )
        if r.returncode == 0 and r.stdout.strip():
            version = r.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    env_repr = repr(os.environ.get("OLLAMA_URL"))
    try:
        from core.ollama_endpoint import resolve_ollama_base_url

        resolved = resolve_ollama_base_url()
    except Exception:  # noqa: BLE001
        resolved = "?"
    catches: List[Dict[str, str]] = []
    try:
        from core.ollama_url_sentinel import recent_catches

        catches = recent_catches()
    except Exception:  # noqa: BLE001
        pass
    return version, env_repr, resolved, catches


def _short_culprit(culprit: str) -> str:
    """把罪魁帧 `File "D:\\...\\x.py", line N, in fn` 压成 `x.py:N in fn`(界面可读)。"""
    try:
        import re

        m = re.search(r'File "([^"]+)", line (\d+)(?:, in (\S+))?', culprit or "")
        if m:
            # 兼容两种路径分隔符:日志可能来自 Windows(D:\x\y.py)也可能来自 POSIX
            name = re.split(r"[\\/]", m.group(1))[-1]
            fn = f" in {m.group(3)}" if m.group(3) else ""
            return f"{name}:{m.group(2)}{fn}"
    except Exception:  # noqa: BLE001
        pass
    return (culprit or "")[:60]


async def _ensure_recommended_model():
    """Ensure at least one recommended model is available (PR-I3)"""
    try:
        from core.huggingface_model_manager import get_hf_model_manager

        hf = get_hf_model_manager()

        local_models = hf.list_local_models()
        if not local_models:
            logger.info("No local models found, downloading recommended model...")
            try:
                await hf.install_recommended("llm_gemma4_e4b")
                logger.info("Recommended model downloaded successfully")
            except Exception as exc:
                logger.warning("Failed to auto-download model: %s", exc)
                logger.info(
                    "Please manually download a model: "
                    'python -c "from core.huggingface_model_manager import get_hf_model_manager; '
                    "import asyncio; hf=get_hf_model_manager(); "
                    "asyncio.run(hf.install_recommended('llm_gemma4_e4b'))\""
                )
    except Exception:
        pass


def print_section(title: str):
    """打印章节标题。"""
    print_section_header(title)


def _try_start_docker_daemon(docker_path: str) -> None:
    """尽力拉起 Docker 守护进程（已安装但未运行时）。永不抛出。

    - Windows: 启动 Docker Desktop.exe（常见安装路径）。
    - macOS:   open -a Docker。
    - Linux:   尝试 systemctl start docker（无 sudo；rootless/已授权时生效）。
    安装 Docker 本身需要管理员权限/重启，无法可靠地静默完成，因此不在此处尝试安装。
    """
    import subprocess as sp

    try:
        if sys.platform == "win32":
            candidates = [
                os.path.join(
                    os.environ.get("ProgramFiles", r"C:\\Program Files"), "Docker", "Docker", "Docker Desktop.exe"
                ),
                os.path.join(
                    os.environ.get("ProgramW6432", r"C:\\Program Files"), "Docker", "Docker", "Docker Desktop.exe"
                ),
            ]
            for exe in candidates:
                if os.path.exists(exe):
                    sp.Popen([exe], creationflags=getattr(sp, "DETACHED_PROCESS", 0))
                    return
        elif sys.platform == "darwin":
            sp.Popen(["open", "-a", "Docker"])
        else:
            sp.run(["systemctl", "start", "docker"], capture_output=True, timeout=20)
    except Exception:
        pass


def _get_lan_ip() -> str:
    """Return the host's primary LAN IPv4 address, or empty string if unavailable."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return ""


#: 端口预检专用的探测地址。刻意只探环回口,绝不绑通配地址,详见
#: :func:`_probe_port_bindable`。
_PORT_PROBE_HOST = "127.0.0.1"


def _probe_port_bindable(port: int) -> str:
    """试绑一次端口。可绑返回空串;不可绑返回人话原因。

    只做一次真实的 bind/close,不留监听——这是判断"端口是不是已经被占了"
    最直接也最可靠的办法(比连一下看通不通准确:后者对只绑了 IPv4 或正在
    启动中的服务会误判)。

    刻意**不设** SO_REUSEADDR:在 Windows 上它的语义是"允许强抢已被占用的
    端口",打开反而会让探测通过、真正 bind 时才炸,与本函数的目的正好相反。

    **只探环回口,不绑通配地址。** 这既不是妥协也不是为了绕过静态扫描:
    只要不开 SO_REUSEADDR,别的进程占着 ``0.0.0.0:P`` 时,再去绑
    ``127.0.0.1:P`` 同样会 EADDRINUSE(Windows/POSIX 皆然)。所以环回探测
    足以覆盖本函数唯一要防的场景——**本机已经有一个 Galaxy 占着这个端口**
    (真机上 Electron 拉起第二套后端抢 9000 就是这个形态)。

    已知不覆盖的残余情形:某个服务只绑在**某块具体的非环回网卡**上
    (如 ``192.168.1.5:P``)。此时本探测会放行,而 uvicorn 绑 ``0.0.0.0:P``
    仍会失败——那条路径由调用方对 uvicorn 启动失败的处理如实兜底,不会再
    退化成一段无上下文的 traceback。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((_PORT_PROBE_HOST, int(port)))
        return ""
    except OSError as exc:
        return f"{exc.__class__.__name__}: {exc}"


_CLOUD_LLM_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "ZHIPU_API_KEY",
    "QWEN_API_KEY",
    "MOONSHOT_API_KEY",
    "MINIMAX_API_KEY",
    "XAI_API_KEY",
)


def _model_tag_root(tag: str) -> str:
    """模型 tag 去掉冒号后缀，取根名(如 'gemma4:e2b' -> 'gemma4')，用于宽松匹配。"""
    return (tag or "").split(":")[0].strip().lower()


def ai_brain_readiness(
    chosen_model: str,
    available_models: list,
    ollama_healthy: bool,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[str, bool, str]:
    """判定"AI 大脑"启动状态是否真的可用,而不仅仅是"Ollama 服务可达"。

    真机复现过的坑:LocalBrainManager._healthy 只代表"Ollama 服务本身可达"，
    不代表"用户选中的这个模型真的装好了"——曾经服务健康但 gemma4:e2b 从未拉取
    成功,启动横幅却照样打 ✓、显示"就绪"，用户看着一片绿实际上一句话都问不出来
    (每次调用都 404)。这里额外核实选中模型是否真的在已安装列表里(按 tag 前缀
    宽松匹配，兼容 "gemma4:e2b" 与 "gemma4:e2b-q4" 等变体)；若本地模型没装好但
    配置了任一云端 API Key，仍可对话，不算彻底不可用。

    Returns:
        (status, model_installed, model_status_label)
        status: "ok" | "warn" | "fail" —— 供启动横幅 & 最终"降级"统计使用。
    """
    env = env if env is not None else os.environ
    model_installed = bool(chosen_model) and any(
        _model_tag_root(a) == _model_tag_root(chosen_model) for a in available_models
    )
    cloud_key_set = any(
        env.get(k, "").strip() and not env.get(k, "").strip().lower().startswith(PLACEHOLDER_PREFIXES)
        for k in _CLOUD_LLM_KEY_ENV_VARS
    )
    truly_usable = model_installed or cloud_key_set
    status = "ok" if (ollama_healthy and model_installed) else ("warn" if truly_usable else "fail")
    if model_installed:
        label = "已安装"
    elif cloud_key_set:
        label = "未安装(拉取失败/未完成)—— 已配置云端 API Key 可兜底"
    else:
        label = "未安装(拉取失败/未完成)—— 且无云端 API Key,当前无法对话！请去「模型」tab 配置"
    return status, model_installed, label


async def _recheck_ai_brain_phase(brain, phases_state: list, ai_brain_phase_idx: int) -> None:
    """在总结卡打印前，重新探测一次 AI 大脑真实状态，好转了就更新对应条目。

    真机复现过:"AI 大脑"这一行的状态是在 select_and_start_brain() 刚返回那一刻
    算出来、写死进 phases_state 的——但 background_pull() 是故意不阻塞启动的
    后台线程，那一刻很可能还没跑完(甚至 Ollama 服务本身当时都还在冷启动，没
    来得及在 _ensure_ollama_running() 的等待窗口内响应)。等到节点系统、L4
    模块、Electron、托盘、语音这些阶段都跑完、真正要打总结卡时，Ollama 大概率
    已经起来、模型也大概率已经拉好了，但总结卡"降级"栏用的还是那份过时快照，
    导致用户看到"AI 大脑 → 未安装(拉取失败/未完成)"，实际上模型已经真的装好
    可用——这是过期状态展示的问题，不是模型真的没装好。

    只在这里把状态往"更好"的方向纠正(never downgrade)，且只在探测到真实证据
    (ping 通 + 模型列表刷新)时才改，不主观放宽判定标准。
    """
    try:
        if brain is None or not (0 <= ai_brain_phase_idx < len(phases_state)):
            return
        healthy2 = bool(getattr(brain, "_healthy", False)) or await brain._ping_ollama()
        if healthy2:
            brain._healthy = True
            await brain._refresh_model_list()
        bm2 = getattr(brain, "brain_model", None) or os.environ.get("OLLAMA_MODEL", "") or "未选择"
        avail2 = list(getattr(brain, "available_models", []) or [])
        st2, model_installed2, label2 = ai_brain_readiness(bm2, avail2, healthy2)
        name0, status0, _hint0 = phases_state[ai_brain_phase_idx]
        if status0 != "ok" and st2 != status0:
            phases_state[ai_brain_phase_idx] = (name0, st2, (None if model_installed2 else label2))
    except Exception as exc:  # noqa: BLE001
        logger.debug("AI 大脑状态复核跳过(非致命): %s", exc)


# ============================================================================
# Launcher sub-module imports
# (Enums, config, service management, core/node/health/shutdown)
# ============================================================================

from launcher.bootstrap import (
    ServiceType,
    SystemConfig,
    SystemState,
    _write_entrypoint,
)
from launcher.core_services import CoreServiceLauncher
from launcher.health_checks import run_startup_health_check
from launcher.node_startup import NodeSystemLauncher
from launcher.service_manager import ServiceInfo, ServiceManager
from launcher.shutdown import async_shutdown

# ============================================================================
# L4 增强模块启动器
# ============================================================================


class L4EnhancementLauncher:
    """L4 增强模块启动器"""

    def __init__(self, service_manager: ServiceManager, config: SystemConfig):
        self.service_manager = service_manager
        self.config = config
        self.l4_modules = {}

    async def start_all(self) -> Dict[str, bool]:
        """启动所有 L4 增强模块"""
        results = {}

        # 感知模块
        logger.debug("初始化感知模块...")
        try:
            from enhancements.perception.environment_scanner import EnvironmentScanner

            self.l4_modules["environment_scanner"] = EnvironmentScanner()
            results["perception"] = True
        except Exception as e:
            logger.error(f"感知模块初始化失败: {e}")
            results["perception"] = False

        # 推理模块
        logger.debug("初始化推理模块...")
        try:
            from enhancements.reasoning.autonomous_planner import AutonomousPlanner
            from enhancements.reasoning.goal_decomposer import GoalDecomposer
            from enhancements.reasoning.world_model import WorldModel

            self.l4_modules["goal_decomposer"] = GoalDecomposer()
            self.l4_modules["autonomous_planner"] = AutonomousPlanner()
            self.l4_modules["world_model"] = WorldModel()
            results["reasoning"] = True
        except Exception as e:
            logger.error(f"推理模块初始化失败: {e}")
            results["reasoning"] = False

        # 学习模块
        logger.debug("初始化学习模块...")
        try:
            from enhancements.learning.autonomous_learning_engine import AutonomousLearningEngine

            self.l4_modules["learning_engine"] = AutonomousLearningEngine()
            results["learning"] = True
        except Exception as e:
            logger.error(f"学习模块初始化失败: {e}")
            results["learning"] = False

        # 执行模块
        logger.debug("初始化执行模块...")
        try:
            from enhancements.execution.action_executor import ActionExecutor

            self.l4_modules["action_executor"] = ActionExecutor()
            results["execution"] = True
        except Exception as e:
            logger.error(f"执行模块初始化失败: {e}")
            results["execution"] = False

        # 安全模块
        logger.debug("初始化安全模块...")
        try:
            from enhancements.safety.safety_manager import SafetyManager

            self.l4_modules["safety_manager"] = SafetyManager()
            results["safety"] = True
        except Exception as e:
            logger.error(f"安全模块初始化失败: {e}")
            results["safety"] = False

        return results


# ============================================================================
# Web UI 服务器
# ============================================================================


class UnifiedWebUI:
    """统一 Web UI 服务器"""

    def __init__(self, service_manager: ServiceManager, config: SystemConfig):
        self.service_manager = service_manager
        self.config = config
        self.app = None

    async def start(self):
        """启动 Galaxy API 服务（核心运行时 API 层）

        架构说明（API 单一入口原则）：
          core/api_routes.py 是 Galaxy 系统的 **唯一权威 API 定义**。
          所有 REST 路由必须通过 core.api_routes.create_api_routes() 提供。

          当前系统表层方向：桌面三态运行层 + 桌面状态板（desktop tri-state runtime
          + desktop status surface）。dashboard/ 已删除，不再作为运行时表层。

          1. 以内建 FastAPI 应用为主应用（权威应用）。
          2. 在其上叠加 core.startup 引导的子系统中间件
          3. 叠加 core.api_routes 作为 **主 API 层**（系统管理、设备、节点、
             监控、观测性、AI、chat 等全部路由）
          4. 添加健康检查路由
          5. 统一在配置端口提供服务

        注意：此启动器 **不应** 定义自己的 inline API 路由。
        如需新增 API 端点，请在 core/routes/ 下对应子模块中添加。
        """
        try:
            import uvicorn

            # === 步骤 1：以内建 FastAPI 应用为主应用（权威 API 基础） ===
            from fastapi import Depends, FastAPI
            from fastapi.middleware.cors import CORSMiddleware
            from fastapi.responses import JSONResponse

            from core.auth import require_auth as _require_auth
            from nodes.common.cors_config import get_cors_headers, get_cors_methods, get_cors_origins

            self.app = FastAPI(title="Galaxy", description="L4 级自主性智能系统", version="2.0")
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=get_cors_origins(),
                allow_credentials=True,
                allow_methods=get_cors_methods(),
                allow_headers=get_cors_headers(),
            )

            # === 步骤 2：引导核心子系统（缓存 + 监控 + 性能中间件 + 命令路由 + AI） ===
            try:
                from core.startup import bootstrap_subsystems

                bootstrap_results = await bootstrap_subsystems(self.app, self.config)
                ok = sum(1 for v in bootstrap_results.values() if v.get("status") == "ok")
                total = len(bootstrap_results)
                logger.info("核心子系统: %d/%d 正常", ok, total)
                for _name, _info in bootstrap_results.items():
                    _icon = "OK" if _info.get("status") == "ok" else "DEGRADED"
                    logger.info("  [%s] %s: %s", _icon, _name, _info)
            except Exception as e:
                logger.warning("核心子系统引导失败（系统仍可运行）: %s", e)

            # === 步骤 2.5：启动认知进化系统（PR-25/26/27）===
            try:
                from core.cognitive.evolution_system import init_cognitive_evolution

                init_cognitive_evolution()
                logger.info("认知进化系统已初始化")
            except Exception as e:
                logger.warning("认知进化系统初始化失败（非阻塞）: %s", e)

            # === 步骤 3：挂载 core.api_routes 作为主 API 层 ===
            # core/api_routes.py 是 Galaxy 的 **唯一权威 API 入口**。
            # 所有 REST 路由（system、devices、nodes、vision、tasks、chat、
            # ai、monitoring、relay、hybrid、vault、cost、channels、
            # federation、sessions、concurrency、errors、observability 等）
            # 均由 core/routes/ 子模块定义，在此统一挂载。
            # dashboard/backend/main.py 中重叠的路由将被此处覆盖。
            try:
                from core.api_routes import create_api_routes, create_websocket_routes

                api_router = create_api_routes(service_manager=self.service_manager, config=self.config)
                self.app.include_router(api_router)
                logger.info("扩展 API 路由已加载（来自 core.api_routes）")

                # ── 设备接入:canonical 必须**先注册** ────────────────────────
                #
                # 仓库自己的声明(core/api_routes.py 的
                # CORE_COMPAT_DEVICE_INGRESS_POLICY_AUTHORITY):
                #   "core.api_routes 的兼容 WebSocket 接入永远不等价于生产。
                #    canonical 的 Android/V2 设备接入是 galaxy_gateway.routes.websocket
                #    的 /ws/device/{device_id}"
                #
                # 而这里此前**只**挂了 core.api_routes 的兼容面。实测(TestClient 真连真发):
                #
                #   现状      capability_report → {"type":"compat_ws_disabled", ...}
                #             heartbeat         → {"type":"compat_ws_disabled", ...}
                #   挂上之后  capability_report → capability_report_ack
                #             heartbeat         → heartbeat_ack
                #
                # 也就是说桌面本地部署上**设备根本连不进来** —— 兼容面默认禁用
                # (要 GALAXY_ALLOW_PROTECTED_CORE_COMPAT_WS 才开),而 capability_report
                # 正是 Android/WearOS 在 onOpen 时发的设备注册事件。
                #
                # 顺序要紧:FastAPI 对同一路径先注册的赢。canonical 放在前面,
                # 兼容面仍然注册(它还提供 /ws/status、/ws/desktop-presence 等),
                # 只是 /ws/device/{device_id} 不会再被它接管。这一点也实测过 ——
                # 反过来放(兼容面在前)修复不生效,返回的仍是 compat_ws_disabled。
                #
                # 这是纯复用:canonical 那条走 galaxy_gateway.android_bridge 单例
                # (不是 app.state,所以可以挂在任何 app 上),而 android_bridge 正是
                # 调 normalise_to_v3_dict 做 AIP v3 规范化的那条链路 —— 别名归一
                # (heartbeat/agent_heartbeat/device_heartbeat)、v2→v3 改写、
                # schema/version 闸,全都随之接上,一行新协议代码都不用写。
                try:
                    from galaxy_gateway.routes.websocket import register_websocket_routes

                    register_websocket_routes(self.app)
                    logger.info("canonical 设备接入已挂载:/ws/device/{device_id}(galaxy_gateway.routes.websocket)")
                except Exception as _ws_err:  # noqa: BLE001 — 挂不上要看得见,但不阻断其余路由
                    logger.error("canonical 设备接入挂载失败,设备将无法接入:%s", _ws_err, exc_info=True)

                create_websocket_routes(self.app, service_manager=self.service_manager)
                logger.info("WebSocket 端点已加载(兼容面:/ws/status、/ws/desktop-presence 等)")
            except ImportError as e:
                logger.warning("API 路由模块加载失败: %s", e)

            # === 步骤 4：健康检查路由 ===
            try:
                from core.health_check import create_health_routes

                health_router, _health_checker = create_health_routes(
                    service_manager=self.service_manager, config=self.config
                )
                self.app.include_router(health_router)
                logger.info("健康检查路由已加载")
            except ImportError as e:
                logger.warning("健康检查模块加载失败: %s", e)

            # === 步骤 5：统一启动器专属路由 ===
            # 面板表层已收敛到唯一一份：Tauri/Electron 壳内的 React 面板
            # （electron/renderer/panel/）。此处曾挂载的两个并行 Web 表层
            # —— /api-manager（static/api-manager，只有构建产物没有源码）与
            # /operator-console（static/operator-console/index.html，731 行
            # 原生 JS 轮询页）—— 连同其静态目录一并删除。多份表层各自读各自的
            # 聚合层，是"面板显示的态和真实请求驱动的态对不上"这类问题的来源
            # （见 electron/renderer/panel/src/App.tsx 里那段相位优先级的注释）。
            @self.app.get("/api/status")
            async def launcher_status(auth: dict = Depends(_require_auth)):
                return JSONResponse(
                    {
                        "status": "running",
                        "version": "2.0",
                        "state": self.service_manager.state.name,
                        "services": self.service_manager.get_status(),
                        "config": self.config.get_status_dict(),
                    }
                )

            @self.app.get("/api/services")
            async def launcher_services():
                return JSONResponse(self.service_manager.get_status())

            # === 步骤 7：启动 uvicorn ===
            _uvi_config = uvicorn.Config(
                self.app, host=self.config.host, port=self.config.web_ui_port, log_level="warning"
            )
            server = uvicorn.Server(_uvi_config)

            # ── 绑定前先自检端口 ──
            # 端口被占时,uvicorn 是在后台任务里 `sys.exit(1)`,真机上的表现是:
            # 一条无上下文的 `ERROR: [Errno 10048] ...`,加一段横跨 winloop/asyncio
            # 的双层 traceback,末尾还挂一条 `Task exception was never retrieved`
            # —— 用户完全看不出"这只是端口被另一个 Galaxy 占着"。
            # 提前用一次普通 bind 探明,把它变成一句能直接照做的话。
            _bind_err = _probe_port_bindable(self.config.web_ui_port)
            if _bind_err:
                raise RuntimeError(
                    f"API 网关端口 {self.config.web_ui_port} 无法绑定({_bind_err})。"
                    "最常见原因是**已经有一个 Galaxy 在运行**(请勿重复启动),"
                    "或该端口被其它程序占用。"
                    f"可用 `python main.py --port <其它端口>` 换端口启动。"
                )

            logger.info("Galaxy API 服务启动: http://%s:%d", self.config.host, self.config.web_ui_port)
            logger.info("API 文档: http://localhost:%d/docs", self.config.web_ui_port)
            # Run uvicorn via the public serve() entrypoint in a background task.
            # serve() correctly loads the config AND initialises self.lifespan;
            # manually calling server.startup() breaks on uvicorn ≥0.30 with
            # "'Server' object has no attribute 'lifespan'" (the gateway then never
            # binds — /api/v1/chat is unreachable even though the banner says ready).
            # We wait on the public ``server.started`` flag so the socket is bound
            # before probing, then let serve()'s main_loop keep running in the
            # background so the launcher proceeds to later phases (Electron / ready
            # banner) instead of blocking here.
            self._server = server
            self._serve_task = asyncio.create_task(server.serve())
            # serve() 若在我们取回结果前就异常收场(端口竞态、ASGI 启动失败…),
            # asyncio 会在任务被回收时打印 "Task exception was never retrieved"
            # 加一段裸 traceback —— 真机日志里那条噪声就是这么来的。
            # 挂一个吞掉未取回异常的回调:真正的失败下面 result() 会照常抛出,
            # 这里只负责保证"没人取"这件事不会再变成刷屏。
            self._serve_task.add_done_callback(lambda t: t.cancelled() or t.exception())
            for _ in range(300):  # up to ~30s for bind + ASGI startup
                if server.started or self._serve_task.done():
                    break
                await asyncio.sleep(0.1)
            if self._serve_task.done():
                # serve() exited during startup — re-raise the real error so the
                # caller logs an accurate "API 网关启动失败" cause.
                try:
                    self._serve_task.result()
                except SystemExit as exc:
                    # uvicorn 在启动失败时走的是 `sys.exit(1)`,抛出的 SystemExit
                    # 继承自 BaseException —— 下面所有 `except Exception` 都接不住,
                    # 它会一路穿透启动器把整个进程带走(真机上就是那段裸 traceback)。
                    # 转成普通异常,交给既有的失败分支如实汇报。
                    raise RuntimeError(
                        f"API 网关启动失败:uvicorn 以退出码 {exc.code} 中止"
                        f"(端口 {self.config.web_ui_port},详见上方日志)。"
                    ) from exc
            logger.debug("启动后健康检查")
            await run_startup_health_check(self.config.web_ui_port)

        except ImportError as e:
            logger.error("API 服务依赖未安装: %s", e)
            # 同族诚实性修复:此前这里吞掉 ImportError 正常返回,调用方
            # launch_web_ui 的 try/except 看不到失败,启动横幅照打 "✓ API 网关"
            # —— 而 fastapi/uvicorn 缺失时网关根本没起。重新抛出,让横幅走
            # except 分支如实显示 "API 网关 · 启动失败"。
            raise

    # 这里曾有 FALLBACK_HTML 与 _get_legacy_dashboard_html()。两者都已删除：
    # 前者只被后者引用，后者【零调用方】——它读的 dashboard/frontend/public/index.html
    # 这个目录在仓库里根本不存在（PR-8 已把 dashboard 降级、后续清理掉），
    # 所以它即使被调用也只会返回那段占位 HTML。面板表层收敛到 React 面板之后，
    # 这条遗留分支连"兜底"的角色都不再有。


# ============================================================================
# Galaxy 统一系统
# ============================================================================


def _log_root_hint() -> "Path":
    """统一日志根目录。唯一事实来源是 core.log_paths.log_root。"""
    from pathlib import Path as _Path

    try:
        from core.log_paths import log_root

        return log_root()
    except Exception:  # noqa: BLE001 — 横幅不该因为导入失败就不显示
        return _Path(__file__).resolve().parent.parent / "logs"


def _crash_hint() -> str:
    """崩溃聚合视图的路径。"""
    try:
        from core.log_paths import crash_latest_path

        return str(crash_latest_path())
    except Exception:  # noqa: BLE001
        return str(_log_root_hint() / "crashes" / "latest.log")


class GalaxyUnified:
    """Galaxy 统一系统"""

    def __init__(self):
        self.config = SystemConfig.load_from_env()
        self.service_manager = ServiceManager(self.config)
        self.core_launcher = CoreServiceLauncher(self.service_manager, self.config)
        self.node_launcher = NodeSystemLauncher(self.service_manager, self.config)
        self.l4_launcher = L4EnhancementLauncher(self.service_manager, self.config)
        self.web_ui = UnifiedWebUI(self.service_manager, self.config)
        self.running = False
        # 这两个以前**只在启动路径上才存在**。start_tauri() 在 already_running()
        # 时直接 return True 而不设 _desktop_shell,于是调用方读它就是 AttributeError
        # —— 一条只在"壳已经跑着"时才触发的崩溃。显式初始化,把这类判空写法从
        # getattr(..., default) 变回普通属性访问。
        self._desktop_shell: Optional[str] = None
        self.electron_proc = None
        # 详细模式：默认折叠每个阶段为一行；-v / GALAXY_VERBOSE=1 展开逐项明细。
        # main.py 解析到 -v 后会覆写 self._verbose；env 提供无参场景下的兜底。
        self._verbose = os.environ.get("GALAXY_VERBOSE", "").strip().lower() in ("1", "true", "yes", "on")

        # PR-DEVICE-RESOLUTION: LauncherAdapter — unified node contract bridge
        try:
            from launcher.launcher_adapter import LauncherAdapter

            self.launcher_adapter = LauncherAdapter(self.node_launcher)
            logger.info("LauncherAdapter initialised (mode=%s)", self.launcher_adapter.mode.value)

            # 按需激活的最后一根线:core 那边算出 should_start 就 return,这边能
            # start_node() 却没人叫。只能由 launcher 单向注册进 core(core 是底层)。
            # 来龙去脉见 tests/test_on_demand_activation_wiring.py。
            from core.udm_registration_hook import get_hook

            get_hook().set_activation_executor(self.launcher_adapter.activate)
        except Exception as e:
            logger.warning("LauncherAdapter init failed (non-fatal): %s", e)
            self.launcher_adapter = None

        # ===== 集成：初始化能力管理器和连接管理器 =====
        try:
            from core.capability_manager import get_capability_manager
            from core.connection_manager import get_connection_manager

            self.capability_manager = get_capability_manager()
            self.connection_manager = get_connection_manager()
            logger.info("能力管理器和连接管理器已初始化")
        except Exception as e:
            logger.warning(f"能力管理器初始化失败 (非致命): {e}")
            self.capability_manager = None
            self.connection_manager = None

    # -- PR-DEVICE-RESOLUTION: observe-only resolution tracing ----------------

    async def _observe_node_resolutions(self) -> None:
        """Observe-only: record node-to-device mappings before startup.

        Reads the device_node_map.yaml, finds all mappings for nodes that
        are about to be started, and records them to the activation registry.
        This does NOT alter which nodes are started; it only creates an
        audit trail for diagnostics.
        """
        import time

        from core.device_activation_registry import get_registry as get_act_registry
        from core.device_node_resolver import DeviceNodeResolver

        t0 = time.perf_counter()
        registry = get_act_registry()
        resolver = DeviceNodeResolver()
        resolver._ensure_loaded()

        # Get the set of nodes that will be started
        if hasattr(self.node_launcher, "get_core_nodes"):
            nodes_to_start = set(self.node_launcher.get_core_nodes())
        else:
            nodes_to_start = set()

        # Find all mappings that reference these nodes
        for mapping in resolver._mappings:
            impl = mapping.get("implementation", {})
            node_name = impl.get("node", "")
            if node_name not in nodes_to_start:
                continue

            match = mapping.get("match", {})
            device_type = match.get("device_type")
            transport = match.get("transport")
            capabilities = match.get("capabilities", [])

            # Build a pseudo-ResolvedMapping for recording
            from core.activation_policy import (
                ActivationDecision,
                ActivationPolicy,
                ActivationPolicyEngine,
            )
            from core.device_node_resolver import (
                CapabilityProfile,
                NodeImplementation,
                ResolvedMapping,
            )

            node_impl = NodeImplementation(
                node=node_name,
                transport=impl.get("transport", "unknown"),
                port=impl.get("port", 0),
                startup=impl.get("startup", "unknown"),
                healthcheck=impl.get("healthcheck", ""),
                note=mapping.get("note", ""),
            )
            caps = CapabilityProfile(
                provides=mapping.get("capabilities", {}).get("provides", []),
                requires=mapping.get("capabilities", {}).get("requires", []),
            )
            resolved = ResolvedMapping(
                match_type=list(match.keys())[0] if match else "unknown",
                match_key=str(list(match.values())[0]) if match else "unknown",
                implementation=node_impl,
                capabilities=caps,
            )

            # Evaluate activation policy for recording
            engine = ActivationPolicyEngine()
            decision = engine.evaluate(
                node_impl,
                ActivationPolicyEngine.TRIGGER_BOOT,
            )

            registry.record_resolution(
                device_type=device_type,
                transport=transport,
                capabilities=capabilities if not device_type and not transport else None,
                result=resolved,
                decision=decision,
                source_event="boot",
                source_module="unified_launcher._observe_node_resolutions",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

        logger.info(
            "[DeviceResolution] Observed %d node mappings in %.1fms",
            len(nodes_to_start),
            (time.perf_counter() - t0) * 1000,
        )

    async def ensure_docker_infra(self) -> tuple:
        """后台静默拉起 Docker 基础设施(NATS/Redis/Qdrant/Neo4j/Mongo)，让依赖它们的节点可用。

        尽力而为、不阻塞事件循环、不因失败中断启动：
        - ``GALAXY_AUTO_DOCKER=0/false/off`` → 跳过（默认 ``auto`` = Docker 存在即拉起）。
        - Docker CLI 不存在 → 返回安装指引并跳过（安装 Docker 需管理员/重启，
          无法可靠静默完成，不在此尝试）。
        - Docker 已装但守护未运行 → 尝试启动 Docker Desktop/daemon 并轮询等待。
        - 守护就绪 → ``docker compose up -d`` 指定的基础设施服务（不含 galaxy 应用本身、
          也不含 ollama 以免与本地 Ollama 端口冲突），输出写 ``logs/docker.log``。
          镜像已就绪 → 秒级拉起（本轮节点即可连上）；首次需下载 → 放后台（本轮先跳过
          依赖节点，下次启动即生效）。

        Returns:
            ``(status, value, note)`` —— status ∈ {"ok","warn"}（渲染图标）；value 是右侧
            一行摘要；note 是可选的下一步提示（仅 -v 详细模式展示）。由 ``start()`` 折叠成
            单行渲染。任何分支都非致命。
        """
        import shutil
        import subprocess as sp
        import time as _time

        flag = os.environ.get("GALAXY_AUTO_DOCKER", "auto").strip().lower()
        if flag in ("0", "false", "no", "off"):
            return ("warn", "已禁用 (GALAXY_AUTO_DOCKER=0)", "")

        # 选择容器运行时:Docker 或 Podman(两者都装时首启会让你选,单一已装直接用,
        # 都没装则跳过)。选择结果持久化到 .galaxy_runtime,并驱动后台【静默拉取】。
        from core import container_runtime as cr

        runtime = await asyncio.to_thread(cr.resolve_runtime, True)
        if not runtime:
            return (
                "warn",
                "未安装 Docker/Podman — 依赖基础设施的节点将跳过（不影响桌面）",
                "启用全部节点：装 Docker 或 Podman 后重跑 — "
                "https://docs.docker.com/get-docker/ 或 https://podman.io/get-started",
            )
        rt_bin = cr.runtime_binary(runtime)
        rt_name = cr.display_name(runtime)

        compose_file = PROJECT_ROOT / "docker-compose.yml"
        if not compose_file.exists():
            return ("warn", f"docker-compose.yml 缺失 — 跳过 {rt_name} 基础设施", "")

        # 仅基础设施后端；排除 galaxy/galaxy-gateway(应用本身) 与 ollama(避免与本地 Ollama 冲突)。
        services = ["nats", "redis", "qdrant", "neo4j", "mongodb"]

        def _daemon_up() -> bool:
            return cr.daemon_up(runtime)

        def _compose_base():
            return cr.compose_base(runtime)

        def _bring_up():
            if not _daemon_up():
                # Podman 无守护进程(rootless),info 不通多半是配置问题,不尝试"启动守护";
                # 仅 Docker 尝试拉起 Docker Desktop/daemon 并轮询等待。
                if runtime == "docker":
                    _try_start_docker_daemon(rt_bin)
                    deadline = _time.time() + float(os.environ.get("GALAXY_AUTO_DOCKER_DAEMON_WAIT", "60"))
                    while _time.time() < deadline:
                        if _daemon_up():
                            break
                        _time.sleep(3)
                if not _daemon_up():
                    return ("daemon_down", None)
            base = _compose_base()
            if not base:
                return ("no_compose", None)
            log_dir = PROJECT_ROOT / "logs"
            log_dir.mkdir(exist_ok=True)
            logf = open(log_dir / "docker.log", "ab")
            cmd = base + ["-f", str(compose_file), "up", "-d"] + services
            logf.write(f"\n== docker infra up: {cmd} ==\n".encode("utf-8", "replace"))
            logf.flush()
            proc = sp.Popen(cmd, cwd=str(PROJECT_ROOT), stdout=logf, stderr=sp.STDOUT)
            wait_s = float(os.environ.get("GALAXY_AUTO_DOCKER_WAIT", "90"))
            try:
                proc.wait(timeout=wait_s)
                return ("up", proc.returncode)
            except sp.TimeoutExpired:
                return ("pulling", None)  # 首次拉镜像，留后台继续

        status, rc = await asyncio.to_thread(_bring_up)
        if status == "up" and rc == 0:
            return ("ok", f"nats / redis / qdrant / neo4j / mongodb 已就绪 · via {rt_name}", "")
        if status == "pulling":
            return (
                "warn",
                f"首次镜像下载中（{rt_name} 后台静默拉取）",
                "进度见 logs/docker.log；本轮先跳过依赖节点，下次启动即生效",
            )
        if status == "daemon_down":
            _hint = (
                "手动启动 Docker Desktop 后重跑"
                if runtime == "docker"
                else "Podman 引擎/machine 未就绪 — 试 `podman machine start` 后重跑"
            )
            return ("warn", f"{rt_name} 未就绪 — {_hint}", "")
        if status == "no_compose":
            return ("warn", f"未找到 {runtime} compose 命令 — 跳过 " f"(装 {runtime}-compose 或启用 compose 插件)", "")
        return ("warn", f"{rt_name} 启动异常 (rc={rc})，详情见 logs/docker.log", "")

    async def start_electron(self) -> bool:
        """启动 Electron 桌面三态覆盖层。

        自愈部分已收敛到 ``launcher/shell.py`` —— 本方法只剩"拉起进程"。

        原来这里内联着 100 行七级自愈(锁 / 缺失 / 残缺 / 清暂存目录 / 换镜像 /
        整体重建 / 补运行时二进制)。那段代码本身是对的,每一级都是真机故障攒
        出来的;但它嵌在一个 async 方法里,导致两件事做不到:**不启动就诊断不
        了**,以及**修好了是哪一级修的、没修好卡在第几级,事后说不清**。

        ``launcher.shell`` 把同一套判据重排成"零副作用的 diagnose + 可逐级审计
        的 self_heal",判据一条没改。现在这里调它,全仓只有一份自愈实现。
        """
        import shutil
        import subprocess as sp

        from core.electron_launch_guard import write_lock
        from launcher import shell as _shell

        report = _shell.self_heal()
        if not report.ok:
            _stuck = next((s.level for s in reversed(report.steps) if s.applied and not s.ok), "?")
            _blocked = report.after.blocked if report.after else None
            logger.error(
                "Electron 桌面壳自愈未成功(卡在第 %s 级)%s",
                _stuck,
                f":{_blocked}" if _blocked else "",
            )
            for _s in report.steps:
                if _s.applied and not _s.ok and _s.detail:
                    logger.error("  第 %d 级「%s」:%s", _s.level, _s.name, _s.detail[:300])
            return False
        if report.healed_at == 0:
            logger.info("Electron GUI already running (started by another launch path)")
            return True
        if report.healed_at is not None:
            logger.info("Electron 依赖已由第 %d 级自愈修复", report.healed_at)

        electron_dir = Path("electron")
        npm = shutil.which("npm")
        if not npm:  # self_heal 已判过硬阻塞;这里只是让下面的用法有定义
            return False

        # Start Electron — PR-ABSOLUTE-PATH: use absolute paths on Windows
        try:
            env = os.environ.copy()
            env["PATH"] = str(Path(npm).parent) + os.pathsep + env.get("PATH", "")
            # 显式把【真实的网关端口】告诉 Electron，避免它只能猜默认 9000：若后端实际监听端口
            # 与 9000 不一致（config 覆盖等），main.js 的 GATEWAY_BASE 会指错口子 → 感知帧/配置
            # 等 fetch 全部「fetch failed」。这里把 web_ui_port 同步给 Electron，从根上消除端口错配。
            env["GALAXY_GATEWAY_PORT"] = str(self.config.web_ui_port)
            env.setdefault("PORT", str(self.config.web_ui_port))
            # GPU 自适应：默认让 Electron 走硬件加速（有独显的机器更流畅）。若 watch_processes
            # 检测到 GPU 模式反复崩溃，会置 _electron_force_software=True，这里注入
            # GALAXY_ELECTRON_GPU=0 → main.js 据此禁用硬件加速 + --disable-gpu
            # + --disable-gpu-compositing（真正的纯软件渲染兜底）。
            # 三档判据统一到 launcher.shell.render_env —— 硬件加速 → 软件渲染
            # (GALAXY_ELECTRON_GPU=0) → 不透明 basic 小窗(再加 GALAXY_ELECTRON_BASIC=1,
            # 功能保留、只丢透明特效)。写在一处,免得两边各改一半。
            env.update(
                _shell.render_env(
                    force_software=bool(getattr(self, "_electron_force_software", False)),
                    basic_window=bool(getattr(self, "_electron_basic_window", False)),
                )
            )
            # Prefer the locally-installed electron binary — robust and avoids the
            # `npm electron .` bug (invalid command) that hit when npx was absent.
            # CRITICAL: use ABSOLUTE paths for both the binary and the app dir.
            # 之前用相对路径 electron\node_modules\.bin\electron.cmd，而 Popen 的 cwd=electron，
            # 系统会按 electron\electron\... 解析 → "The system cannot find the path specified."
            # → Electron 根本起不来、闪退循环。绝对路径彻底消除该 cwd 相对解析歧义。
            app_dir = electron_dir.resolve()
            bin_name = "electron.cmd" if os.name == "nt" else "electron"
            local_electron = app_dir / "node_modules" / ".bin" / bin_name
            if local_electron.exists():
                cmd = [str(local_electron), str(app_dir)]
            else:
                npx = shutil.which("npx")
                cmd = [npx, "electron", str(app_dir)] if npx else [npm, "exec", "--", "electron", str(app_dir)]
            # Capture Electron stdout/stderr to logs/electron.log so crashes are
            # diagnosable (previously DEVNULL-swallowed → impossible to debug the
            # "exited, restarting" loop / why Ctrl+Space overlay never appears).
            _log_dir = Path("logs")
            _log_dir.mkdir(exist_ok=True)
            _elog = open(_log_dir / "electron.log", "ab")
            _elog.write(
                f"\n===== electron start {__import__('datetime').datetime.now().isoformat()} "
                f"cmd={cmd} =====\n".encode("utf-8", "replace")
            )
            _elog.flush()
            self.electron_proc = sp.Popen(
                cmd,
                cwd=str(app_dir),
                stdout=_elog,
                stderr=sp.STDOUT,
                env=env,
            )
            write_lock(self.electron_proc.pid)
            return True
        except Exception as exc:
            logger.error(f"Electron start failed: {exc}")
            return False

    async def start_tauri(self) -> bool:
        """优先启动 Tauri 桌面壳（系统 WebView，不背 Chromium，常驻内存/启动/体积都远小于 Electron）。

        仅当 desktop-tauri 已构建出二进制时启用；未构建则返回 False，由 start_desktop_shell
        回退到 Electron。首启不强行 cargo build（无工具链/编译太慢），交给用户显式构建一次：
        ``cd desktop-tauri/src-tauri && cargo build --release``。env 与 Electron 完全一致。
        """
        import shutil  # noqa: F401  (对齐 start_electron 的导入风格，未来可能用到)
        import subprocess as sp

        from core.electron_launch_guard import already_running, write_lock

        if os.environ.get("GALAXY_DESKTOP_SHELL", "").strip().lower() == "electron":
            return False  # 显式强制 Electron
        if already_running():
            logger.info("桌面壳已由其他启动路径拉起，跳过 Tauri 启动")
            return True
        tdir = Path("desktop-tauri")
        if not tdir.exists():
            return False
        exe = "galaxy-overlay.exe" if os.name == "nt" else "galaxy-overlay"
        candidates = [
            tdir / "src-tauri" / "target" / "release" / exe,
            tdir / "src-tauri" / "target" / "debug" / exe,
        ]
        binp = next((c for c in candidates if c.exists()), None)
        if not binp:
            # A 档：首启自动构建 Tauri 壳。仅当有 cargo 工具链时尝试；GALAXY_TAURI_AUTOBUILD=0 可关。
            import shutil as _shutil

            _optout = os.environ.get("GALAXY_TAURI_AUTOBUILD", "").strip().lower() in (
                "0",
                "false",
                "no",
                "off",
            )
            if _optout:
                logger.info("GALAXY_TAURI_AUTOBUILD=0：跳过 Tauri 自动构建，回退 Electron。")
            elif _shutil.which("cargo") is None:
                logger.info(
                    "未检测到 Rust(cargo)，跳过 Tauri 自动构建 → 回退 Electron。"
                    "装 Rust(https://rustup.rs) 后重启即自动构建并优先用 Tauri。"
                )
            else:
                # 构建前预检系统级依赖（Linux 的 webkit2gtk 等）——缺则给出 apt 命令并跳过，
                # 避免 cargo build 崩得莫名其妙；Rust crate 依赖由 Cargo 自理。
                try:
                    from core.electron_launch_guard import tauri_build_prereqs_hint

                    _hint = tauri_build_prereqs_hint()
                except Exception:
                    _hint = None
                if _hint:
                    logger.info("Tauri 构建系统依赖缺失，跳过自动构建 → 回退 Electron：\n%s", _hint)
                else:
                    logger.info("首次启动：自动构建 Tauri 桌面壳(cargo build --release，首次约需数分钟)，请稍候…")
                    try:
                        _rc = sp.call(["cargo", "build", "--release"], cwd=str(tdir / "src-tauri"))
                    except Exception as _bexc:  # noqa: BLE001
                        _rc = -1
                        logger.warning("Tauri 自动构建启动失败：%s", _bexc)
                    if _rc == 0:
                        binp = next((c for c in candidates if c.exists()), None)
                        if binp:
                            logger.info("Tauri 壳构建完成 ✓ 之后每次启动将自动优先用它。")
                    else:
                        logger.warning("Tauri 自动构建失败(cargo rc=%s)，本次回退 Electron。", _rc)
        if not binp:
            logger.info(
                "Tauri 壳不可用 → 回退 Electron。" "可手动构建一次：cd desktop-tauri/src-tauri && cargo build --release"
            )
            return False
        try:
            env = os.environ.copy()
            # 与 start_electron 注入同一组 env：端口/IPC/GPU 自适应一致，托盘与 bridge 无需改动。
            env["GALAXY_GATEWAY_PORT"] = str(self.config.web_ui_port)
            env.setdefault("PORT", str(self.config.web_ui_port))
            env.setdefault("GALAXY_IPC_PORT", "9231")
            # 与 start_electron 同一份降级判据(launcher.shell.render_env)。
            # 此前两处各写一遍 —— 改一处漏一处,两个壳的降级行为就会悄悄分叉。
            from launcher import shell as _shell

            env.update(
                _shell.render_env(
                    force_software=bool(getattr(self, "_electron_force_software", False)),
                    basic_window=bool(getattr(self, "_electron_basic_window", False)),
                )
            )
            _log_dir = Path("logs")
            _log_dir.mkdir(exist_ok=True)
            # 复用同一份 logs/electron.log（托盘「View Logs」目录下），便于一处看壳层日志。
            _tlog = open(_log_dir / "electron.log", "ab")
            _tlog.write(
                f"\n===== tauri start {__import__('datetime').datetime.now().isoformat()} "
                f"bin={binp} =====\n".encode("utf-8", "replace")
            )
            _tlog.flush()
            # proc 仍存进 self.electron_proc，让既有的 watch_processes 保活逻辑直接复用。
            self.electron_proc = sp.Popen(
                [str(binp.resolve())],
                cwd=str(tdir.resolve()),
                stdout=_tlog,
                stderr=sp.STDOUT,
                env=env,
            )
            write_lock(self.electron_proc.pid)
            self._desktop_shell = "tauri"
            return True
        except Exception as exc:
            logger.error("Tauri 壳启动失败，回退 Electron: %s", exc)
            return False

    async def start_desktop_shell(self) -> bool:
        """统一桌面壳入口：优先 Tauri（轻量），未构建/失败则回退 Electron。

        ``GALAXY_SKIP_ELECTRON=1`` 在这里生效 —— 这是全仓**唯一**的桌面壳入口
        （``start_tauri`` / ``start_electron`` 都只从这里进），所以闸设在这一处
        就够，不用两边各写一遍。

        为什么现在才接：这个开关在 ``flags.py`` 里登记着（``status="stable"``、
        purpose 白纸黑字写着 "skip starting the Electron three-state GUI"），但
        **全仓零个读取点** —— 也就是设了它没有任何效果。删 ``launch_desktop.py``
        时要给 ``--backend``（只起网关、不拉壳）一个等价新命令，正好落在它身上：
        与其为 ``--backend`` 另造一套判断，不如把这个本来就该生效的开关接上。
        """
        if os.environ.get("GALAXY_SKIP_ELECTRON", "").strip() == "1":
            logger.info("GALAXY_SKIP_ELECTRON=1，跳过桌面壳启动（无头模式）")
            return False
        if await self.start_tauri():
            return True
        self._desktop_shell = "electron"
        return await self.start_electron()

    async def start_system_tray(self) -> bool:
        """启动系统托盘（右下角），与 Electron 解耦、常驻于本启动器进程。

        以前托盘由 Electron `spawn('python -m windows_service.tray_icon')` 拉起，
        Electron 崩溃/重启就把托盘也带没了。现在在 Python 启动器自身进程的后台线程里
        启动（start_tray_in_thread 内部 run_detached），后端存活期间托盘一直在。
        缺 pystray/Pillow 时优雅降级（非致命）。
        """
        try:
            from windows_service.tray_icon import start_tray_in_thread

            tray = await asyncio.to_thread(start_tray_in_thread)
            if tray is not None:
                self._tray = tray
                return True
            return False
        except Exception as exc:
            logger.warning("系统托盘启动失败(非致命): %s", exc)
            return False

    def _electron_log_excerpt(self, max_lines: int = 8) -> str:
        """取 logs/electron.log 尾部的错误摘要，直接打进主日志。

        真机排查痛点：每次降级/放弃都只说"详情见 logs/electron.log"，用户根本
        不会去翻——而崩溃根因(gpu-process-gone 原因、Cannot find module、
        Electron failed to install correctly…)其实就躺在那个文件尾部。这里把
        尾部 8KB 里带错误特征的行摘出来，守护日志自己说清楚"为什么崩"。
        """
        try:
            p = Path("logs") / "electron.log"
            if not p.exists():
                return "(logs/electron.log 不存在 —— Electron 可能根本没被拉起)"
            with open(p, "rb") as f:
                f.seek(max(0, p.stat().st_size - 8192))
                tail = f.read().decode("utf-8", "replace")
            keys = (
                "error",
                "Error",
                "ERROR",
                "FATAL",
                "gone",
                "Cannot find module",
                "GPU",
                "gpu",
                "crash",
                "Unable",
                "failed",
                "Failed",
                "退出",
                "失败",
            )
            lines = [ln.strip() for ln in tail.splitlines() if ln.strip() and any(k in ln for k in keys)]
            picked = lines[-max_lines:] if lines else [ln for ln in tail.splitlines() if ln.strip()][-max_lines:]
            return "\n    ".join(picked) if picked else "(electron.log 为空)"
        except Exception as exc:  # noqa: BLE001 —— 摘要失败绝不能反过来搞挂守护循环
            return f"(读取 electron.log 失败: {exc})"

    async def watch_processes(self):
        """进程保活 + 渲染模式三级自适应：监控 Electron，崩溃时自动重启。

        按机器实际情况自适应渲染模式（无需用户手动判断有没有 GPU）：
        - 默认 GPU（硬件加速）模式启动；
        - 若 GPU 模式 60s 内崩溃 >= MAX_GPU 次（常见于无独显/驱动不支持透明窗口
          GPU 合成）→ 自动切换为软件渲染（--disable-gpu + --disable-gpu-compositing）重试；
        - 若软件渲染也 60s 内崩溃 >= MAX_SW 次 → 第三级降级：不透明 basic 窗口
          （丢透明特效、保留覆盖层功能），而不是直接放弃；
        - basic 窗口也 60s 内崩溃 >= MAX_BASIC 次 → 才停止自动重启并给出指引。
        每次降级/放弃都把 logs/electron.log 尾部错误摘要打进主日志（见 _electron_log_excerpt）。
        """
        import asyncio
        import time

        restarts: list = []  # 最近 60s 窗口内的重启时间戳
        MAX_GPU = 3  # GPU 模式连续崩溃达此数 → 切软件渲染
        MAX_SW = 5  # 软件渲染也崩到此数 → 降级不透明 basic 窗口
        MAX_BASIC = 5  # basic 窗口也崩到此数 → 放弃
        gave_up = False
        if not hasattr(self, "_electron_force_software"):
            self._electron_force_software = False
        if not hasattr(self, "_electron_basic_window"):
            self._electron_basic_window = False
        while True:
            await asyncio.sleep(5)
            proc = getattr(self, "electron_proc", None)
            if not proc or proc.poll() is None or gave_up:
                continue  # 未启动 / 仍在运行 / 已放弃
            # 我们【亲眼看到】自己拉起的壳进程已经退出 —— 立刻把锁清掉。
            # 不清会怎样(真机实证):锁里那个 pid 已死,但 Windows 上 pid 会被系统
            # 回收给无关进程,already_running() 就把陌生进程当成"壳还活着",
            # start_tauri() 早退返回 True → start_desktop_shell() 短路 →
            # 下面的 start_desktop_shell() 根本不会去拉 Electron。真机上 13 条
            # "Electron 已退出,重启中"对应的 electron.log 里只有一个启动标记,
            # GPU→软件渲染→basic 三级降级全程空转,正是这么来的。
            # 自己的孩子自己收尸,是这里唯一能 100% 确定锁已失效的时刻。
            try:
                from core.electron_launch_guard import clear_lock

                clear_lock()
            except Exception as exc:  # noqa: BLE001 —— 清锁失败不该挡住重启
                logger.debug("清理桌面壳锁失败(不影响重启): %s", exc)
            now = time.time()
            restarts = [t for t in restarts if now - t < 60]

            # GPU 模式反复崩溃 → 自动降级为软件渲染（自适应核心）
            if (not self._electron_force_software) and len(restarts) >= MAX_GPU:
                self._electron_force_software = True
                restarts = []
                logger.warning(
                    "Electron GPU 模式 60s 内崩溃 %d 次，自动切换为软件渲染重试"
                    "（你的显卡/驱动可能不支持透明窗口 GPU 合成）。"
                    "崩溃摘要(logs/electron.log 尾部)：\n    %s",
                    MAX_GPU,
                    self._electron_log_excerpt(),
                )
                await self.start_desktop_shell()
                continue

            # 软件渲染也反复崩溃 → 第三级降级：不透明 basic 窗口（保功能、丢透明特效）。
            # 根因：无独显 Windows 上透明分层窗口本身(而不只是 GPU 合成)可能就是崩溃点，
            # 此前直接放弃 → 覆盖层整个没了；现在换不透明小窗再试，外壳尽量活着。
            if self._electron_force_software and not self._electron_basic_window and len(restarts) >= MAX_SW:
                self._electron_basic_window = True
                restarts = []
                logger.warning(
                    "Electron 软件渲染仍 60s 内崩溃 %d 次，降级为【不透明 basic 窗口】重试"
                    "（覆盖层功能保留，仅无透明特效）。崩溃摘要(logs/electron.log 尾部)：\n    %s",
                    MAX_SW,
                    self._electron_log_excerpt(),
                )
                await self.start_desktop_shell()
                continue

            # basic 窗口也反复崩溃 → 放弃（此时多半不是渲染问题，摘要里通常能看出真因）
            if self._electron_basic_window and len(restarts) >= MAX_BASIC:
                gave_up = True
                # 崩溃即刻汇入统一崩溃专区:用户从托盘「💥 崩溃日志」一行点开就能
                # 看到本次崩溃(不必等到手动触发聚合,也不必自己去翻 electron.log)。
                _crash_hint = ""
                try:
                    from core.crash_log_aggregator import aggregate_crashes

                    _crash_path, _crash_n = aggregate_crashes()
                    _crash_hint = f"（已汇入崩溃专区 {_crash_path}，共 {_crash_n} 处）"
                except Exception as _agg_exc:  # noqa: BLE001 — 聚合失败不影响主流程
                    logger.debug("崩溃聚合失败(不影响运行): %s", _agg_exc)
                logger.error(
                    "Electron 在 GPU/软件渲染/不透明 basic 窗口下均反复崩溃，已停止自动重启。"
                    "后端与 API 仍在 http://localhost:%d 正常运行（Ctrl+Alt+Space 覆盖层暂不可用）。"
                    "%s崩溃摘要(logs/electron.log 尾部)：\n    %s",
                    self.config.web_ui_port,
                    _crash_hint,
                    self._electron_log_excerpt(),
                )
                continue

            restarts.append(now)
            _mode = (
                "basic 窗口" if self._electron_basic_window else "软件渲染" if self._electron_force_software else "GPU"
            )
            logger.warning(
                "Electron 已退出，重启中（%s 模式，60s 内第 %d 次；详情见 logs/electron.log）…",
                _mode,
                len(restarts),
            )
            await self.start_desktop_shell()

    async def setup(self):
        """加载配置并初始化服务管理器。"""
        self.service_manager.state = SystemState.LOADING_CONFIG

    async def start_nats(self) -> dict:
        """启动 NATS 消息总线。返回结构化真实结果(供启动横幅如实展示)。

        诚实性修复(所有者 Windows 真机日志实证):此前 EmbeddedNATSServer.start()
        返回 False(如 [WinError 4551] WDAC 拦截 nats-server.exe)被本函数静默吞掉;
        接着 bus.connect() 按约定 C7【返回 {"success": False} 而非抛异常】,也被
        无视返回值地 await 掉 —— 调用方的 try/except 永远走不到 except 分支,
        启动横幅于是在 NATS 根本没起来时照打 "✓ 消息总线 nats://localhost:4222"。
        现在:显式核验每一步结果,失败时带原因/修复指引返回,由横幅降级展示。

        Returns:
            {"ok": bool, "url": str, "error": str, "hint": str, "disabled": bool}
        """
        from core.nats_bus import get_nats_bus
        from core.nats_server import EmbeddedNATSServer

        # 显式关闭(用户在 .env 写 GALAXY_NATS_ENABLED=false 时才走这里;默认已改回
        # 开启——所有者明确指令:默认路径是"尝试启动→成功",不许拿关闭当回避)。
        # 关闭时同样切进程内总线:单机语义完整,只是不再尝试拉起 nats-server。
        if os.environ.get("GALAXY_NATS_ENABLED", "").strip().lower() in ("false", "0", "no", "off"):
            get_nats_bus().enable_local_fallback("GALAXY_NATS_ENABLED=false(按配置显式关闭)")
            return {"ok": False, "url": "", "error": "", "hint": "", "disabled": True}
        nats_url = os.environ.get("GALAXY_NATS_URL")
        embedded_error = ""
        embedded_hint = ""
        if not nats_url:
            server = EmbeddedNATSServer()
            if await server.start():
                return {
                    "ok": True,
                    "url": os.environ.get("GALAXY_NATS_URL", "nats://localhost:4222"),
                    "error": "",
                    "hint": "",
                    "disabled": False,
                }
            embedded_error = getattr(server, "last_error", "") or "内置 nats-server 启动失败"
            embedded_hint = getattr(server, "last_error_hint", "")
        bus = get_nats_bus()
        result = await bus.connect()
        if isinstance(result, dict) and result.get("success") and bus.is_usable():
            return {
                "ok": True,
                "url": os.environ.get("GALAXY_NATS_URL", nats_url or "nats://localhost:4222"),
                "error": "",
                "hint": "",
                "disabled": False,
            }
        _conn_err = (result.get("error", "") if isinstance(result, dict) else str(result)) or "NATS 连接失败"
        # 真解决(所有者不接受"未启用"回避):nats-server 起不来(WDAC 拦截/未安装
        # 等)时自动降级为进程内纯 Python 总线——单机 publish/subscribe 全部照常,
        # 不再让后续每次总线调用重演失败重试刷错;横幅语气为"单机模式正常"。
        bus.enable_local_fallback(embedded_error or _conn_err)
        return {
            "ok": False,
            "url": "",
            "error": embedded_error or _conn_err,
            "hint": embedded_hint,
            "disabled": False,
            "local_fallback": True,
        }

    async def start_tailscale(self):
        """启动 Tailscale 网络。返回真实 Tailscale IP（供显示）。"""
        from core.tailscale_manager import TailscaleManager

        ts = TailscaleManager()
        # 冷启动时网关常先于 Tailscale 就绪 → 首次 entrypoint.json 里没有 tailscale 地址。
        # 注册回调：Tailscale IP 出现/变化时重写 entrypoint.json，把 mesh 地址补进去，
        # 让手机/手表尽快发现网关、异地秒连（不必等下次启动）。
        try:
            ts.on_state_change(lambda _action, _details: self._write_entrypoint_json())
        except Exception:  # noqa: BLE001
            pass
        ts_ip = await ts.initialize()
        if not ts_ip:
            raise RuntimeError("Tailscale not installed")
        return ts_ip

    async def start_local_brain(self):
        """启动本地 Ollama 大脑。"""
        from core.local_brain_manager import LocalBrainManager

        self._brain = LocalBrainManager()
        await self._brain.ensure_running()

    async def start_voice_interaction(self) -> bool:
        """启动语音交互闭环：听麦克风 → ASR → 主回路(驱动三态 + 出回复) → TTS 朗读。

        这是"对它说话它会回应、且三态随对话变化"的关键——此前 VoiceLoop 从未被拉起,
        所以唤醒后说话毫无反应。现在把它接到 DesktopPresenceRuntime.handle_request:
        说话 → LIMINAL(思考动画) → 出回复 → MANIFEST(表达动画) → 朗读 → SILENT。

        缺语音依赖(faster-whisper / edge-tts / sounddevice)时优雅降级,不影响其余启动。
        GALAXY_VOICE=0 可关闭。
        """
        if os.environ.get("GALAXY_VOICE", "1").strip().lower() in ("0", "false", "no", "off"):
            self._voice_input_disabled_reason = "GALAXY_VOICE=0(已手动关闭)"
            return False
        # 麦克风采集依赖 sounddevice/PortAudio。它不就位时 AudioCaptureService.start()
        # 会【静默跳过】、mic 永不打开,而此前本函数照样 return True → 摘要谎报"语音交互
        # 已开启"(所有者反馈"对它说话没反应、不知为何")。这里显式探测并如实报因。
        try:
            from core.multimodal.audio_ingest import _SOUNDDEVICE_AVAILABLE as _sd_ok
        except Exception:
            _sd_ok = False
        if not _sd_ok:
            self._voice_input_disabled_reason = (
                "麦克风采集不可用:sounddevice/PortAudio 未就绪 —— 对它说话不会有反应。"
                "Linux 装 libportaudio2 portaudio19-dev;Windows 试 "
                "pip install --force-reinstall sounddevice"
            )
            logger.warning(
                "\n%s\n⚠️  语音输入未启用:麦克风采集依赖 sounddevice/PortAudio 未就绪。\n    %s\n%s",
                "=" * 66,
                self._voice_input_disabled_reason,
                "=" * 66,
            )
            return False
        try:
            from core.voice_loop import VoiceLoop

            class _VoiceGalaxyAdapter:
                """把 ASR 文本接进主回路:process(text) → handle_request(驱动三态 + 返回回复)。"""

                async def process(self, text: str, source: str = "voice"):
                    try:
                        from core.desktop_presence_runtime import get_desktop_presence_runtime

                        rt = get_desktop_presence_runtime()
                        return await rt.handle_request(
                            message=text,
                            source=source,
                            session_id="voice",
                            user_id="voice",
                            entry_mode="local",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("语音→主回路处理失败: %s", exc)
                        return {"response": ""}

            self._voice_loop = VoiceLoop(
                _VoiceGalaxyAdapter(),
                model_size=os.environ.get("GALAXY_WHISPER_MODEL", "base"),
                speak_responses=False,  # 朗读由 handle_request 经 speech_output 集中处理,避免双声
            )
            await self._voice_loop.start()
            return True
        except ImportError as exc:  # noqa: BLE001
            # 语音输入静默失效最常见的原因。醒目告知 + 给可直接照做的命令,
            # 而不是淹没在启动日志里的一行 warning(所有者反馈"对它说话没反应、不知为何")。
            self._voice_input_disabled_reason = f"缺 ASR 依赖({exc});运行 pip install faster-whisper 后重启"
            logger.warning(
                "\n%s\n⚠️  语音输入未启用 —— 对它说话不会有反应。\n"
                "    缺 ASR 依赖:%s\n"
                "    装上后重启即开启(麦克风/TTS 通常已随默认依赖装好):\n"
                "        pip install faster-whisper\n%s",
                "=" * 66,
                exc,
                "=" * 66,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            _exc_s = str(exc)
            if any(k in _exc_s for k in ("Hub", "locate the files", "snapshot folder", "internet")):
                self._voice_input_disabled_reason = f"Whisper 模型下载失败(检查网络/代理):{exc}"
                logger.warning("语音交互未启动(Whisper 模型下载失败，检查网络或设置代理): %s", exc)
            else:
                self._voice_input_disabled_reason = f"运行时错误:{exc}"
                logger.warning("语音交互未启动(运行时错误，GALAXY_VOICE=0 可关闭): %s", exc)
            return False

    async def select_and_start_brain(self):
        """Phase 5：先选主脑（硬件推荐 + 手动选，放第 5 步而非开头），
        再确保 Ollama 服务本身真的起来了，最后才后台拉取模型。

        修复:之前 background_pull() 在 start_local_brain() 之前就立即触发——
        它开的后台线程第一件事就是探测 Ollama 是否可达，那时 Ollama 服务本身
        可能压根还没起来(尤其 Windows 首次冷启动，GPU/驱动探测、杀毒软件扫描
        exe 都会拖慢 ollama serve 绑定 11434 端口的时间)。start_local_brain()
        内部(LocalBrainManager._ensure_ollama_running)已经有专门等 Ollama
        就绪的重试逻辑(最长约 40 秒)，但 background_pull() 走的是完全独立的
        一次性尝试、连不上就直接判定失败退出，不会重试、也不会等 Ollama
        追上来——真机反馈"不管是重新启动还是手动重试，模型拉取都失败"，
        根因就是这个顺序颠倒的竞态:每次启动都在 Ollama 真正就绪前就已经
        打完这一枪、后台线程退出，直到下次重启又原样重演同一个竞态，
        看起来像是"怎么修都没用"。这里把 start_local_brain() 挪到
        background_pull() 之前，确保后台拉取真正开始时 Ollama 已确认可达。
        """
        import asyncio as _asyncio

        chosen = ""
        # 选择主脑：交互 input 放线程，避免阻塞事件循环。env(OLLAMA_MODEL)/已保存优先，
        # 否则按硬件推荐 + 让用户手动选（见 core.model_selection）。
        try:
            from core import model_selection as ms

            chosen = await _asyncio.to_thread(ms.resolve_main_brain, True)
            if chosen:
                # 证据链：把主脑选型（最终模型 + 硬件 + 候选 + 推荐理由）落进启动会话，
                # 以后能回答「这次为什么选了它、是按什么硬件推荐的」。best-effort。
                try:
                    from core.session_manager import get_session_manager

                    _max_mb, _has_gpu, _hw = ms.get_compute_summary()
                    _rec = ms.recommend(_max_mb, _has_gpu)
                    sm = get_session_manager()
                    await sm.ensure_session("session_system_boot", user_id="system")
                    sm.record_model_selection(
                        "session_system_boot",
                        chosen,
                        reason=("环境/已保存指定" if chosen != _rec else "按实际硬件推荐"),
                        hardware=_hw,
                        candidates=[t for t, _ in ms.list_models()],
                        source="resolve_main_brain",
                    )
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("主脑选择跳过(非致命): %s", exc)

        # 启动本地大脑（LocalBrainManager 读 OLLAMA_MODEL 作主脑，确认 Ollama
        # 服务本身已就绪）—— 必须先于下面的后台拉取执行。
        await self.start_local_brain()

        if chosen:
            from core import model_selection as ms

            ms.background_pull(chosen)  # 本地缺失则后台 ollama pull（Ollama 此时已确认可达）

    async def launch_web_ui(self):
        """启动 Web UI / API 网关。"""
        await self.web_ui.start()

    def _write_entrypoint_json(self):
        """写出 entrypoint.json 供客户端发现。"""
        try:
            _write_entrypoint(self.config.host, self.config.web_ui_port)
        except Exception as _e:
            logger.warning("写入 runtime/entrypoint.json 失败（不影响启动）: %s", _e)

    async def start(self):
        """启动 Galaxy 后端 — 板块式输出。"""
        # 入口角色契约（PR-01）：服务编排是**从属**入口，不是第二个顶层入口。
        #
        # 这一条原本在 ``unified_launcher.main()`` 里（它自己的 CLI 外壳开头）。
        # 第 8 步删本体时那个 main() 一起没了，契约校验就**没有任何地方在跑**了 ——
        # entrypoint_role_contract.py 里 UNIFIED_LAUNCHER_ENTRY_ID 的登记还在，
        # 却再也没人核对，登记就退化成了一份没人读的声明。
        #
        # 搬到 start() 而不是模块级：模块级会让 ``import launcher.services``
        # 带上副作用（tests/test_entrypoint_import_has_no_env_side_effects.py
        # 守的正是这一类）。放在真正开始编排的那一刻，时机与原来一致。
        from entrypoint_role_contract import (
            UNIFIED_LAUNCHER_ENTRY_ID,
            EntrypointRole,
            ensure_entrypoint_role,
        )

        if not ensure_entrypoint_role(UNIFIED_LAUNCHER_ENTRY_ID, EntrypointRole.SUB_ENTRY):
            logger.error("入口角色契约校验失败：服务编排必须是 SUB_ENTRY，不能是第二个顶层入口。")
            raise SystemExit(1)

        await self.setup()
        # 这里【不能】再 new 一个 ServiceManager。__init__ 已经建好一个,并且把
        # core_launcher / node_launcher / l4_launcher / web_ui 全部绑在【那一个】
        # 上了;在这里替换 self.service_manager 只会换掉自己这一份引用,web_ui
        # 仍指向旧实例 —— 而 /api/status、/api/services 这两个端点正是 web_ui
        # 里的闭包(见 UnifiedWebUI 步骤 6)。于是启动过程中 CoreServiceLauncher
        # (launcher/core_services.py:28/43/61)和 NodeSystemLauncher
        # (launcher/node_startup.py:586)注册进去的服务全落在新实例上,而两个查询
        # 端点读的是那个再也收不到任何注册的旧实例:services 恒为空、state 也永远
        # 停在 setup() 写的 LOADING_CONFIG。config 在 __init__(第 711 行)之后不
        # 会被换对象(main.py 只是改它的 host/port 字段),所以这次 new 的入参与
        # __init__ 那次完全相同 —— 纯粹是一份多余且有害的副本,删掉即让全系统
        # 收敛到同一个 ServiceManager。

        # ── 启动阶段渲染（clig.dev：默认每阶段折叠一行，-v 展开逐项明细）──
        from core import cli_render as r

        verbose = bool(getattr(self, "_verbose", False))
        port = self.config.web_ui_port
        host = self.config.host
        phases_state: List[Tuple[str, str, Optional[str]]] = []  # (阶段名, 状态, 专属修复建议) → 末尾总结卡用

        def _emit(
            name: str,
            value: str,
            status: str,
            details: Optional[List[Tuple[str, str, str]]] = None,
            hint: Optional[str] = None,
        ) -> None:
            """记录并渲染一个阶段：默认折叠成一行；-v 时打印小标题 + 逐项明细。

            hint: 若该阶段最终判定为降级/失败，末尾总结卡"降级"行要展示的
            该项【专属】修复建议（而非把所有降级项共用一句通用提示——那样会
            出现"AI 大脑需要重新拉模型/配 Key，却被告知装 Docker 后重跑即恢复"
            这种文不对题的情况）。不传则总结卡显示该项名称、不附带建议。
            """
            phases_state.append((name, status, hint))
            # 计时:每次 _emit 是某阶段收尾,记录距上一次 _emit 的耗时归到该阶段名下
            # (隐蔽:只进 logs/lumiv.log + 面板诊断;GALAXY_PHASE_TIMING=0 可关)。
            try:
                from core.startup_timing import mark as _phase_mark

                _phase_mark(name)
            except Exception:  # noqa: BLE001
                pass
            if verbose:
                r.section(name)
                for label, val, st in details or [(name, value, status)]:
                    r.detail(label, val, st)
            else:
                r.phase(name, value, status)

        if not verbose:
            print()  # banner 与折叠阶段行之间留一行呼吸

        # 立启动计时基准:此后每个 _emit(阶段收尾)的 mark 就能量出该阶段耗时。
        try:
            from core.startup_timing import mark_reset as _phase_mark_reset

            _phase_mark_reset()
        except Exception:  # noqa: BLE001
            pass

        # ── API 网关（第一阶段:先开门,再热身）──
        # 真机复现过的一整类症状的根因:9000 端口的 HTTP 服务此前排在容器探测、
        # NATS、AI 大脑、逐节点拉起、L4 之后才绑定 —— 容器引擎坏掉(如 Windows
        # WDAC/WinError 4551 拦 podman)时前面能干等 150s+,而 Electron 面板是
        # 立刻打开的,用户此时点「保存 API 密钥」,请求打到还没绑定的端口,重试
        # 60s 后报"无法连接后端(已重试多次)…后端可能仍在启动中"。
        # /api/config、/health 对后续任何阶段【零依赖】(容器/NATS/Ollama 全部
        # 可降级),所以把网关绑定提到最前:面板秒级可用,其余阶段照原顺序热身。
        try:
            await self.launch_web_ui()
            # 端口发现文件同步提前:Electron 在 GALAXY_GATEWAY_PORT/PORT 未设时
            # 读 runtime/entrypoint.json 定位后端 —— 此前它在启动序列末尾才写,
            # 面板整个启动期都读不到;绑定成功即写(幂等,末尾照写覆盖)。
            self._write_entrypoint_json()
            _emit(
                "API 网关",
                f"http://localhost:{port}",
                "ok",
                details=[
                    ("FastAPI + Uvicorn", f"http://{host}:{port}", "ok"),
                    ("WebSocket", f"ws://localhost:{port}/ws", "ok"),
                    ("API 文档", f"http://localhost:{port}/docs", "ok"),
                    ("健康检查", "/health", "ok"),
                    ("状态面板", f"http://localhost:{port}/api/v1/projection/operability-contract", "ok"),
                ],
            )
        except Exception as exc:
            _emit("API 网关", "启动失败", "fail")
            logger.error(f"API gateway: {exc}")

        # ── 核心服务 ──
        try:
            from launcher.core_services import CoreServiceLauncher

            cs = CoreServiceLauncher(self.service_manager, self.config)
            results = await cs.start_all()
            _r = results if isinstance(results, dict) else {}
            items = [
                ("Device Agent 管理器", _r.get("device_agent_manager", False)),
                ("设备状态 API :8766", _r.get("device_status_api", False)),
                ("Microsoft UFO 集成", _r.get("microsoft_ufo_integration", False)),
            ]
            up = sum(1 for _, v in items if v)
            st = "ok" if up == len(items) else ("warn" if up else "fail")
            _emit(
                "核心服务",
                f"{up}/{len(items)} 就绪",
                st,
                details=[(n, "就绪" if v else "未就绪", "ok" if v else "warn") for n, v in items],
            )
        except Exception as exc:
            _emit("核心服务", "启动失败", "fail")
            logger.error(f"Core services: {exc}")

        # ── 基础设施 (Docker / Podman，自动拉起；依赖它的节点才能起来) ──
        try:
            d_status, d_value, d_note = await self.ensure_docker_infra()
        except Exception as exc:
            d_status, d_value, d_note = "warn", "基础设施启动异常（非致命）", ""
            logger.warning("ensure_docker_infra failed: %s", exc)
        # 标签反映实际选中的运行时(Docker / Podman);resolve_runtime 已把选择写入
        # GALAXY_CONTAINER_RUNTIME,未选到则统一显示 "容器"。
        _rt = os.environ.get("GALAXY_CONTAINER_RUNTIME", "").strip().capitalize() or "容器"
        d_details = [(f"{_rt} 基础设施", d_value, d_status)]
        if d_note:
            d_details.append(("下一步", d_note, "info"))
        _emit(
            f"基础设施 · {_rt}",
            d_value,
            d_status,
            details=d_details,
            hint="装 Docker/Podman 后重跑即恢复" if d_status != "ok" else None,
        )

        # ── 消息总线 ──
        # 诚实性修复(所有者 Windows 真机日志实证):旧代码"try: await start_nats()
        # 不抛异常 == 成功"—— 但 NATSBus.connect() 按 C7 约定失败时返回
        # {"success": False} 而非抛异常,EmbeddedNATSServer.start() 失败也只
        # return False,于是 nats-server.exe 被 WDAC([WinError 4551])拦截、
        # 根本没起来时,横幅仍打 "✓ 消息总线 nats://localhost:4222"(假绿)。
        # 现在按 start_nats() 的结构化真实结果降级展示:原因 + 影响 + 专属修复指引。
        bus_details: List[Tuple[str, str, str]] = []
        bus_hint: Optional[str] = None
        try:
            _nats_res = await self.start_nats()
        except Exception as exc:  # noqa: BLE001
            _nats_res = {"ok": False, "url": "", "error": str(exc), "hint": "", "disabled": False}
        if _nats_res.get("ok"):
            nats_ok, bus_value = True, _nats_res.get("url") or "已连接"
            bus_details.append(("NATS Bus", bus_value, "ok"))
        elif _nats_res.get("disabled"):
            # 按配置显式关闭 —— 是配置意图而非故障;单机模式正常,如实标注影响。
            nats_ok = False
            bus_value = "单机模式正常(进程内总线)· NATS 按配置关闭,跨设备分发不可用"
            bus_details.append(("NATS Bus", "按配置未启用(GALAXY_NATS_ENABLED=false)", "warn"))
            bus_details.append(("影响", "跨设备任务分发/集群 mesh 不可用;单机进程内总线正常工作", "info"))
            bus_hint = "如需跨设备:设 GALAXY_NATS_ENABLED=true 并确保 nats-server 可运行"
        else:
            # 诚实降级但语气为"单机模式正常"(所有者指令):NATS 起不来不是单机
            # 故障——进程内总线已自动接管全部单机语义,失败原因与放行指引照展示。
            nats_ok = False
            _err = _nats_res.get("error") or "未知原因"
            bus_value = f"单机模式正常(进程内总线)· NATS 未启动:{_err[:60]},仅跨设备分发不可用"
            bus_details.append(("NATS Bus", f"未启动:{_err}", "warn"))
            bus_details.append(
                ("降级", "已自动切换进程内总线 —— 单机功能全部正常;仅跨设备任务分发/集群 mesh 不可用", "info")
            )
            bus_hint = _nats_res.get("hint") or (
                "检查 nats-server 是否可运行(手动执行 nats-server -v 验证);"
                "单机使用可设 GALAXY_NATS_ENABLED=false 明确关闭此项"
            )
            bus_details.append(("修复", bus_hint, "info"))
        try:
            ts_ip = await self.start_tailscale()
            bus_details.append(("Tailscale", ts_ip or "已连接", "ok"))
            # PR-PEER-RELAY: 显示对等中继态（本机已宣告 / 各 peer 经哪条中继）。
            try:
                from core.tailscale_manager import TailscaleManager

                _rs = TailscaleManager().get_relay_status()
                if _rs.get("advertise_relay_enabled"):
                    _via = _rs.get("self_relay")
                    bus_details.append(
                        (
                            "对等中继",
                            ("已宣告（本机充当私有中继）" if not _via else f"经 {_via}"),
                            "ok",
                        )
                    )
            except Exception:
                pass
        except Exception:
            bus_details.append(("Tailscale", "未安装 (LAN 直连模式)", "warn"))
        # 降级时把该项【专属】修复指引挂到总结卡(hint),不再无提示地一笔带过。
        _emit(
            "消息总线",
            bus_value,
            "ok" if nats_ok else "warn",
            details=bus_details,
            hint=bus_hint if not nats_ok else None,
        )

        # ── AI 大脑（含主脑模型选择）──
        try:
            await self.select_and_start_brain()
            brain = getattr(self, "_brain", None)
            # 全部为真实运行时数据（非硬编码）：
            healthy = bool(brain and getattr(brain, "_healthy", False))
            bm = getattr(brain, "brain_model", None) or os.environ.get("OLLAMA_MODEL", "") or "未选择"
            avail = list(getattr(brain, "available_models", []) or [])
            shown = (
                (", ".join(avail[:6]) + (f" 等 {len(avail)} 个" if len(avail) > 6 else ""))
                if avail
                else "（无 / 后台下载中）"
            )
            hp = getattr(brain, "_hardware_profile", None)
            if hp and getattr(hp, "has_gpu", False):
                hw = f"GPU {getattr(hp, 'gpu_name', '?') or '?'} | 显存 {getattr(hp, 'vram_mb', 0)} MB"
            else:
                hw = "CPU 模式（无独显，软件推理）"

            # 关键修复:_healthy 只代表"Ollama 服务本身可达",不代表"选中的这个模型
            # 真的装好了"——真机复现过:服务健康但 gemma4:e2b 从未拉取成功,这里却照样
            # 打 ✓、显示"就绪",用户看着一片绿实际上一句话都问不出来(每次调用都
            # 404)。ai_brain_readiness() 额外核实选中模型是否真的在已安装列表里。
            st, model_installed, model_status_label = ai_brain_readiness(bm, avail, healthy)
            ai_brain_phase_idx = len(phases_state)
            _emit(
                "AI 大脑",
                f"{bm}  ·  {hw}" + ("" if model_installed else "  ⚠ 模型未就绪"),
                st,
                hint=(None if model_installed else model_status_label),
                details=[
                    (
                        "Ollama 推理服务",
                        "就绪" if healthy else "未就绪（检查 ollama 是否运行）",
                        "ok" if healthy else "fail",
                    ),
                    ("AI 主脑模型", f"{bm} — {model_status_label}", "ok" if model_installed else "warn"),
                    ("已安装模型", shown, "ok" if avail else "warn"),
                    ("硬件", hw, "ok"),
                ],
            )
        except Exception as exc:
            ai_brain_phase_idx = len(phases_state)
            _emit("AI 大脑", "启动失败", "fail")
            logger.error(f"Local brain: {exc}")

        # ── 启动自检 · URL 哨兵(审查结果直接摆上克隆界面,不用翻日志)──
        # 关键信息放在折叠行里(默认可见);-v 展开逐条明细 + 取证值(代码版本/
        # 环境变量/解析后地址)。抓到告警时进末尾总结卡并附操作建议。
        try:
            _ver, _env_repr, _resolved, _catches = _url_sentinel_audit()
            _audit_details: List[Tuple[str, str, str]] = [
                ("代码版本", _ver, "ok" if _ver != "unknown" else "warn"),
                ("OLLAMA_URL(env)", _env_repr, "ok"),
                ("解析后地址", _resolved, "ok"),
            ]
            if _catches:
                for _c in _catches[:5]:
                    _audit_details.append(
                        (
                            "缺协议头请求",
                            f"url={_c.get('url', '')!r} ← {_short_culprit(_c.get('culprit', ''))}",
                            "fail",
                        )
                    )
                _first = _catches[0]
                _emit(
                    "启动自检 · URL哨兵",
                    f"⚠ 抓到 {len(_catches)} 条缺协议头请求 · 首条 "
                    f"url={_first.get('url', '')!r} ← {_short_culprit(_first.get('culprit', ''))}",
                    "warn",
                    details=_audit_details,
                    hint="把「启动自检 · URL哨兵」这行(含 url 与 file:line)复制/截图发回即可精确定位",
                )
            else:
                _emit(
                    "启动自检 · URL哨兵", f"零告警 · 代码版本 {_ver} · Ollama {_resolved}", "ok", details=_audit_details
                )
        except Exception as exc:
            logger.debug("URL 哨兵自检展示失败(非致命): %s", exc)

        # ── 节点系统 ──
        try:
            from launcher.node_startup import NodeSystemLauncher

            nl = NodeSystemLauncher(self.service_manager, self.config)
            result = await nl.start_all()
            # 真实计数：start_all 返回 {node_name: ok}。就绪数/尝试总数，不再写死 /13 /117。
            total = len(result) if isinstance(result, dict) else 0
            ready = sum(1 for v in result.values() if v) if isinstance(result, dict) else 0
            st = "ok" if (ready > 0 or total == 0) else "warn"
            details = (
                [(n, "就绪" if v else "未就绪", "ok" if v else "warn") for n, v in result.items()]
                if isinstance(result, dict) and result
                else None
            )
            _emit("节点系统", f"{ready}/{total} 就绪", st, details=details)
        except Exception as exc:
            _emit("节点系统", "启动失败", "fail")
            logger.error(f"Node system: {exc}")

        # ── L4 增强模块（后台增强层、可选）──
        try:
            l4 = L4EnhancementLauncher(self.service_manager, self.config)
            result = await l4.start_all()
            _mods = result.get("modules", {}) if isinstance(result, dict) else {}
            modules = _mods if isinstance(_mods, dict) else {}
            if modules:
                up = sum(1 for ok in modules.values() if ok)
                st = "ok" if up == len(modules) else "warn"
                _emit(
                    "L4 增强模块",
                    f"{up}/{len(modules)} 就绪",
                    st,
                    details=[(n, "就绪" if ok else "未就绪", "ok" if ok else "warn") for n, ok in modules.items()],
                )
            else:
                # 无逐模块明细时不假装全绿；按整体结果如实显示。
                # 诚实性:bool(result) 只说明"7 个对象构造成功",与"自主循环
                # 在不在跑"毫无关系 —— L4EnhancementLauncher 把它们放进
                # self.l4_modules 之后,全仓**没有任何地方再读这个字典**。
                # 真正驱动 L4 循环的 GalaxyMainLoopL4 只有 integration/
                # websocket_server.py 一个入口,而那是个独立脚本,主启动链
                # 不拉它。所以此处绝不能打"已就绪"让人以为它在工作。
                #
                # 系统真正的自主性由「常驻注意力循环 → OpenClawd ReAct」承担
                # (见 core/ambient_attention_loop.py,已默认开启),与本层无关。
                loaded = len(getattr(l4, "l4_modules", {}) or {})
                _emit(
                    "L4 增强模块",
                    (
                        f"已加载 {loaded} 个组件 · 未接入主循环（自主性由常驻注意力循环承担）"
                        if result
                        else "未启用（可选）"
                    ),
                    "warn",
                )
        except Exception as exc:
            _emit("L4 增强模块", "启动失败", "fail")
            logger.error(f"L4 modules: {exc}")

        # (API 网关已在第一阶段绑定 —— 见 start() 开头「先开门,再热身」。)

        # ── 桌面前端 (三态覆盖层：优先 Tauri，未构建则回退 Electron) ──
        electron_ok = await self.start_desktop_shell()
        shell = getattr(self, "_desktop_shell", "electron")
        shell_name = "Tauri（系统 WebView，轻量）" if shell == "tauri" else "Electron"
        if electron_ok:
            _emit(
                "桌面前端 · 三态覆盖层",
                f"已启动（暖金边缘氛围光） · {shell_name}",
                "ok",
                details=[
                    ("壳层", shell_name, "ok"),
                    ("三态覆盖层", "已启动", "ok"),
                    ("第一态", "暖金边缘氛围光（待机即显示）", "ok"),
                    ("三态切换", "AI 实际活动驱动 silent → liminal → manifest", "ok"),
                    ("快捷键", "Ctrl+Alt+Space 唤醒 / Ctrl+Alt+H 隐藏", "ok"),
                ],
            )
        else:
            _emit("桌面前端 · 三态覆盖层", "未启动 — 后端/API 仍完全可用", "warn")
            logger.warning(
                "Electron 三态覆盖层未启动（缺 Node.js 或 electron 依赖安装失败）。"
                "后端与 API 已就绪 http://localhost:%d ；"
                "如需桌面覆盖层：安装 Node.js≥18 后在 electron/ 执行 `npm install`。",
                self.config.web_ui_port,
            )

        # ── 系统托盘（独立于 Electron，常驻）──
        # 托盘原先仅由 Electron 进程 spawn；Electron 在部分机器上崩溃/重启会让右下角
        # 托盘图标随之消失。改由 Python 启动器在自身进程的后台线程启动，与 Electron
        # 解耦 —— 后端在，托盘就在。
        tray_ok = await self.start_system_tray()
        _emit(
            "系统托盘", "右下角常驻" if tray_ok else "不可用 (pip install pystray Pillow)", "ok" if tray_ok else "warn"
        )

        # ── 远程桌面兜底(VNC)：默认关；GALAXY_REMOTE_DESKTOP=1 才自动开（仅 Tailscale 私网内）──
        try:
            from core.remote_desktop import maybe_autostart as _rd_autostart

            _rd_autostart()
        except Exception as _exc:  # noqa: BLE001
            logger.debug("远程桌面兜底自动开启跳过(非致命): %s", _exc)

        # ── Kokoro 离线 TTS 模型主动预取(与语音输入是否可用无关)──
        # 真机排查发现:kokoro 的模型拉取此前【纯被动】——只有第一次真的要朗读、
        # edge-tts 失败降级时才会被 _try_kokoro() 顺手踢一次后台线程,而模型
        # 337MB、~3 分钟起,那时才开始下载必然来不及,当次对话只能落到 SAPI
        # 机器人音。对比 Whisper ASR 模型(145MB)在 start_voice_interaction()
        # 里就是主动 eager 拉取的——这里补上同等的主动性:启动时无条件踢一次
        # 后台拉取(幂等、非阻塞,不依赖麦克风/GALAXY_VOICE,TTS 出声本就与语音
        # 输入是否可用无关),让下载与启动的其余步骤 + 用户前几轮对话的等待时间
        # 并行,而不是等真正要用了才临时抱佛脚。
        try:
            from core.tts.kokoro_engine import kick_background_fetch as _kokoro_prefetch

            _kokoro_prefetch()
        except Exception as _exc:  # noqa: BLE001
            logger.debug("Kokoro 模型主动预取跳过(非致命): %s", _exc)

        # ── 语音交互闭环：听 → 识别 → 主回路(驱动三态 + 回复) → 朗读 ──
        # 这是"对它说话它会回应、三态随对话变化"的关键(此前 VoiceLoop 从未启动)。
        voice_ok = await self.start_voice_interaction()
        _voice_reason = getattr(self, "_voice_input_disabled_reason", None)
        _emit(
            "语音交互",
            (
                "已开启 · 直接对它说话即可（三态随对话变化）"
                if voice_ok
                else f"未启用：{_voice_reason or '详见上方日志'}"
            ),
            "ok" if voice_ok else "warn",
        )

        # ── AI 大脑状态复核（总结卡打印前）──
        # 真机复现过:"AI 大脑"这一行的状态是在 select_and_start_brain() 刚返回
        # 那一刻算出来、写死进 phases_state 的——但 background_pull() 是故意
        # 不阻塞启动的后台线程，此时很可能还没跑完(甚至 Ollama 服务本身当时都
        # 还在冷启动、没来得及在 _ensure_ollama_running() 的等待窗口内响应)。
        # 等到节点系统、L4 模块、Electron、托盘、语音这些阶段都跑完、真正要打
        # 总结卡的这一刻，Ollama 大概率已经起来、模型也大概率已经拉好了，但
        # 总结卡的"降级"栏之前一直用的是那个过时快照，导致用户看到"AI 大脑 →
        # 未安装(拉取失败/未完成)"，实际上模型已经真的装好可用——这是过期状态
        # 展示的问题，不是模型真的没装好。这里在打印总结卡前重新探测一次真实
        # 状态，好转了就更新对应条目，不去猜、不主观放宽判定标准。
        await _recheck_ai_brain_phase(getattr(self, "_brain", None), phases_state, ai_brain_phase_idx)

        # ── 总结卡：状态 + 关键入口 + 降级项 + 下一步 ──
        ok_n = sum(1 for _, s, _h in phases_state if s == "ok")
        # 每个降级项各带自己的专属修复建议，而不是所有项共用一句"装后重跑即恢复"——
        # 那句话只对 Docker 这类"装个东西重跑就好"的场景成立;AI 大脑之类的降级
        # (模型没拉好/没配 Key)配的建议完全不同，共用会文不对题、误导用户。
        degraded_items = [(n, h) for n, s, h in phases_state if s in ("warn", "fail")]
        r.summary_card(
            title="Galaxy L4 · v2.3.21",
            state_ok=ok_n,
            state_degraded=len(degraded_items),
            rows=[
                ("面板", f"http://localhost:{port}"),
                ("文档", f"http://localhost:{port}/docs"),
                ("唤醒", "Ctrl+Alt+Space    隐藏 Ctrl+Alt+H"),
                # 指路必须指向**真实存在的东西**。
                #
                # 这两行原先写的是「托盘 →「💥 崩溃日志」」和「托盘 →「View Logs」」。
                # 托盘菜单按所有者要求清空之后,那两个入口不存在了 —— 横幅还照旧指过去,
                # 用户就会去点一个没有的东西。改成直接给路径:路径来自
                # core.log_paths(唯一事实来源),不在这里另拼一份。
                ("崩溃", f"{_crash_hint()}(全仓崩溃已合并去重)"),
                ("日志", str(_log_root_hint())),
            ],
            degraded=degraded_items or None,
            hints=[("停止", "Ctrl+C"), ("详细", "python main.py -v")],
        )

        # Write entrypoint.json
        self._write_entrypoint_json()

        # Start process watchdog
        await self.watch_processes()

    def stop(self):
        """停止系统（优雅关闭所有子系统）"""
        print()
        print_status("正在停止系统...", "loading")
        self.service_manager.state = SystemState.STOPPING
        self.running = False

        # 优雅关闭核心子系统（事件桥 → 监控 → 缓存）
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                asyncio.ensure_future(async_shutdown())
            else:
                loop.run_until_complete(async_shutdown())
        except Exception as e:
            logger.warning(f"异步关闭失败: {e}")

        # 关闭认知进化系统（PR-25/26/27）
        try:
            from core.cognitive.evolution_system import shutdown_cognitive_evolution

            shutdown_cognitive_evolution()
        except Exception:
            pass

        self.service_manager.stop_all()
        self.service_manager.state = SystemState.STOPPED
        print_status("系统已停止", "success")

    def show_status(self):
        """显示系统状态"""
        print_banner()

        print_section("配置状态")
        status = self.config.get_status_dict()

        print(f"\n{Colors.BOLD}LLM API:{Colors.ENDC}")
        for api, configured in status["llm_apis"].items():
            icon = "✓" if configured else "✗"
            print(f"  {icon} {api.upper()}")

        print(f"\n{Colors.BOLD}数据库:{Colors.ENDC}")
        for db, configured in status["database"].items():
            icon = "✓" if configured else "✗"
            print(f"  {icon} {db}")

        print_section("节点统计")
        all_nodes = self.node_launcher.get_all_nodes()
        core_nodes = self.node_launcher.get_core_nodes()
        print(f"  总节点数: {len(all_nodes)}")
        print(f"  核心节点: {len(core_nodes)}")

        print_section("双仓推进进度（真实代码审计）")
        try:
            from core.dual_repo_progress_report import build_dual_repo_progress_report

            report = build_dual_repo_progress_report(force_rebuild=True)
            summary = report.get("summary_zh") or ""
            if summary:
                print(f"  摘要: {summary}")
            completion = report.get("system_completion_status") or {}
            if isinstance(completion, dict):
                closure_pct = completion.get("system_closure_pct")
                blocking = completion.get("blocking_gap_count")
                verdict = completion.get("completeness_verdict")
                if closure_pct is not None:
                    print(f"  系统收口度: {closure_pct:.2f}%  completeness={verdict}  阻塞项={blocking}")
            review = report.get("complete_joint_system_review") or {}
            if isinstance(review, dict) and review.get("stage"):
                weighted = review.get("weighted_completion_pct")
                weighted_display = "unknown"
                if isinstance(weighted, (int, float)):
                    weighted_display = f"{weighted:.2f}%"
                print(
                    "  联合审查: "
                    f"stage={review.get('stage')} "
                    f"weighted={weighted_display} "
                    f"android_ref={review.get('android_audited_ref')}"
                )
            plan = report.get("closure_phase_execution_plan") or {}
            if isinstance(plan, dict) and plan.get("next_prs"):
                next_prs = list(plan.get("next_prs") or [])[:5]
                if next_prs:
                    print(f"  下一步建议 PR: {', '.join(next_prs)}")
        except Exception as e:
            print_status(f"双仓推进进度不可用: {e}", "warning")


# ============================================================================
# 主函数
# ============================================================================


async def _run_check_only(lumiv: "GalaxyUnified"):
    """仅检查依赖和配置，输出完整系统状态表，不启动服务"""
    print_banner()
    print_section("系统检查模式 (--check-only)")

    # 1. 依赖检查
    print_section("依赖检查")
    try:
        from scripts.check_dependencies import CORE_DEPS, OPTIONAL_DEPS
        from scripts.check_dependencies import check_dep as check_dependency

        missing_core = []
        missing_optional = []
        for dep in CORE_DEPS:
            if not check_dependency(dep):
                missing_core.append(dep)
        for dep in OPTIONAL_DEPS:
            if not check_dependency(dep):
                missing_optional.append(dep)
        print_status(
            f"核心依赖: {len(CORE_DEPS) - len(missing_core)}/{len(CORE_DEPS)} 已安装",
            "success" if not missing_core else "error",
        )
        if missing_core:
            for d in missing_core:
                print_status(f"  缺失: {d}", "error")
        print_status(
            f"可选依赖: {len(OPTIONAL_DEPS) - len(missing_optional)}/{len(OPTIONAL_DEPS)} 已安装",
            "success" if not missing_optional else "warning",
        )
        if missing_optional:
            for d in missing_optional:
                print_status(f"  缺失: {d}", "warning")
    except Exception as e:
        print_status(f"依赖检查脚本加载失败: {e}", "error")

    # 2. 配置检查
    print_section("配置检查")
    status = lumiv.config.get_status_dict()
    llm_count = sum(1 for v in status["llm_apis"].values() if v)
    print_status(f"LLM API: {llm_count} 个已配置", "success" if llm_count > 0 else "warning")

    # 3. 核心模块导入检查
    print_section("核心模块导入")
    core_modules = [
        "core.startup",
        "core.agent_factory",
        "core.multi_llm_router",
        "core.node_registry",
        "core.node_discovery",
        "core.monitoring",
        "core.health_check",
        "core.cache",
        "core.error_framework",
        "core.event_bridge",
        "core.command_router",
        "core.concurrency_manager",
        "core.config_hot_reload",
        "core.digital_twin_engine",
        "core.health_integration",
        "core.api_routes",
    ]
    ok_count = 0
    for mod_name in core_modules:
        try:
            __import__(mod_name)
            ok_count += 1
        except BaseException as e:
            print_status(f"  {mod_name}: {type(e).__name__}: {e}", "error")
    print_status(
        f"核心模块: {ok_count}/{len(core_modules)} 可导入", "success" if ok_count == len(core_modules) else "warning"
    )

    # 4. 节点导入检查
    print_section("节点导入检查")
    nodes_dir = PROJECT_ROOT / "nodes"
    loaded = 0
    failed = 0
    failed_names = []
    if nodes_dir.exists():
        for node_dir in sorted(nodes_dir.iterdir()):
            main_py = node_dir / "main.py"
            if not main_py.exists():
                continue
            mod_path = f"nodes.{node_dir.name}.main"
            try:
                __import__(mod_path)
                loaded += 1
            except BaseException as e:
                failed += 1
                failed_names.append((node_dir.name, f"{type(e).__name__}: {str(e)[:80]}"))
    print_status(f"节点: {loaded}/{loaded + failed} 可导入", "success" if failed == 0 else "warning")
    if failed_names:
        for name, err in failed_names:
            print_status(f"  {name}: {err}", "warning")

    # 汇总
    print_section("检查完成")
    has_core_issues = bool(missing_core) if "missing_core" in locals() else False
    all_ok = (not has_core_issues) and ok_count == len(core_modules)
    if all_ok:
        print_status("系统就绪，可以启动", "success")
    else:
        print_status("存在问题，请检查上方输出", "warning")
    sys.stdout.flush()
