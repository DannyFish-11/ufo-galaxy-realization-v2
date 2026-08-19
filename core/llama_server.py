"""core/llama_server.py — 把推理位从"进程内加载"改成"我们自己起的 llama-server"
=================================================================================

为什么非改不可
--------------
本仓库 C/D 两档的推理位一直走 ``llama-cpp-python`` **进程内**加载。而它需要的两件
关键能力,恰恰都只存在于 llama.cpp 的 **CLI/server 旗标**上,python 绑定不透出:

===================  ==========================================================
``--n-cpu-moe N``    MoE 专家卸载。**C 档的全部前提** —— 18 GB 权重的 35B 塞进
                     8 GB 显存,靠的就是"专家留内存、只有激活的 3B 上卡"
                     (目录里 ``runtime_mb_val=7300`` 就是按这个前提写的)。
                     ``moe_offload_supported()`` 实测:0.3.34 的 ``Llama.__init__``
                     既没有 ``n_cpu_moe`` 也没有 ``override_tensor``。
``--spec-type``      投机解码草稿位。D 档推理位自带 MTP 头,走 ``draft-mtp``。
                     同样只在 CLI/server 上。
===================  ==========================================================

两件事**同一个洞、同一个补救**,所以一起做:起一个我们自己管理的 ``llama-server``,
经 OpenAI 兼容口说话。

这不是"多一个后端",是把一条**声称生效、实际不生效**的路修好
------------------------------------------------------------
在此之前的现场是:调度器认真算出 ``n_cpu_moe``,加载器发现绑定不支持,打一条
warning,然后**按 n_gpu_layers 照常加载** —— 而准入早在之前就按"专家卸载生效"的
7.3 GB 放行了。判据说装得下、这条路做不到,中间隔着一次加载,表现是一次没头没脑的
OOM。本模块让那条判据第一次名副其实。

三件事分开,谁也不冒充谁
-----------------------
================  ============================================================
**能不能起**      二进制在不在(:func:`llama_server_binary`)。
**支不支持**      这个构建的 ``--help`` 里到底有没有那个旗标
                  (:func:`server_supported_flags`)。**去问,不假设** ——
                  llama.cpp 的旗标改过名,而且各家发行版构建裁剪不一。
**要不要传**      调度器算出来的 ``n_cpu_moe`` / 目录声明的草稿位机制,
                  由 :func:`build_server_args` 组装。
================  ============================================================

组装是**纯函数**:不起进程、不碰文件,因此可以被完整单测。这一点很要紧 —— 命令行
拼错的后果是服务起不来或者旗标被忽略,而这两件事在生产上都表现为"改了没效果"。

端口不占注册表
--------------
端口在启动时**向内核要一个空闲的**(bind :0),不写死也不进
``config/unified_ports.yaml``:这个进程是我们自己起、自己关的私有服务,不是需要
被别人按约定找到的节点。写死一个端口只会在同机跑两份时撞车。

起来之后,地址经 ``GALAXY_LOCAL_OPENAI_URL`` 导出 —— 那正是 ``multi_llm_router``
注册 ``local_openai`` provider 读的那个键,于是路由不需要认识本模块就能用上它。
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("Galaxy.LlamaServer")

#: 二进制名。自建的 llama.cpp 与各发行版包主要用第一个;后两个是历史/裁剪构建的
#: 叫法(与 ``scripts/setup_reasoning_slot.py`` 原来那份候选表同源 —— 那份现在
#: 委托到本模块,不再自己找)。
SERVER_BINARY_NAMES: Tuple[str, ...] = ("llama-server", "llama_server", "server")
SERVER_BINARY_NAME = SERVER_BINARY_NAMES[0]

#: ``--help`` 探测的超时。它只打印帮助就退出,给足余量仍是秒级。
_HELP_TIMEOUT_S = 10.0

#: 起服务后等它就绪的总时长。大权重首次 mmap + 上卡可能要一会儿。
STARTUP_TIMEOUT_S = 180.0

#: 探活间隔。
_POLL_INTERVAL_S = 1.0


def llama_server_binary() -> Optional[str]:
    """``llama-server`` 在哪;找不到返回 ``None``(**不是**空串)。

    ``GALAXY_LLAMA_SERVER_BIN`` 优先 —— 自建构建往往不在 PATH 上,而"我知道它在哪"
    这件事人比探测权威。给了但指不到东西时**不静默回落 PATH**:那会让人以为自己
    指定的构建生效了,实际跑的是另一个。
    """
    raw = os.environ.get("GALAXY_LLAMA_SERVER_BIN", "").strip()
    if raw:
        if os.path.isfile(raw) and os.access(raw, os.X_OK):
            return raw
        logger.warning("GALAXY_LLAMA_SERVER_BIN 指向的不是可执行文件,按找不到处理: %s", raw)
        return None
    for name in SERVER_BINARY_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


_flags_cache: Optional[Tuple[str, frozenset]] = None


def server_supported_flags(*, runner: Any = None) -> frozenset:
    """这个构建的 ``--help`` 里出现过哪些长旗标;二进制不在返回空集合。

    **去问,不假设。** llama.cpp 的旗标历史上改过名,各家发行版的构建也裁剪不一。
    拼一条这个构建不认识的旗标,轻则服务起不来、重则被忽略 —— 而"被忽略"正是
    本模块要终结的那种失败(专家卸载那个洞就是这么活了很久的)。

    结果按二进制路径缓存:``--help`` 要起一次进程,而它在一次运行里不会变。
    """
    global _flags_cache
    binary = llama_server_binary()
    if not binary:
        return frozenset()
    if _flags_cache is not None and _flags_cache[0] == binary:
        return _flags_cache[1]

    run = runner or _run_help
    try:
        text = run(binary)
    except Exception as exc:  # noqa: BLE001 — 问不出来就是问不出来
        logger.warning("llama-server --help 读不出来,按不支持任何旗标处理: %s", exc)
        return frozenset()

    flags = set()
    for token in str(text or "").replace(",", " ").split():
        if token.startswith("--") and len(token) > 2:
            flags.add(token.split("=", 1)[0].strip())
    found = frozenset(flags)
    _flags_cache = (binary, found)
    return found


def _run_help(binary: str) -> str:
    proc = subprocess.run(  # noqa: S603 — 路径来自 which/显式配置,参数固定
        [binary, "--help"],
        capture_output=True,
        text=True,
        timeout=_HELP_TIMEOUT_S,
        check=False,
    )
    # 有的构建把帮助打在 stderr 上。两边都要。
    return f"{proc.stdout}\n{proc.stderr}"


def reset_flag_cache() -> None:
    """丢掉 ``--help`` 缓存。给测试用 —— 不清的话上一条用例的构建会漏给下一条。"""
    global _flags_cache
    _flags_cache = None


# ── 能力判据:这条路能不能做那两件事 ────────────────────────────────────────

#: 专家卸载的旗标。llama.cpp 上是这一个;写成常量而不是在两处拼字符串。
MOE_FLAG = "--n-cpu-moe"

#: 投机解码相关旗标。``--spec-type`` 选机制,``--model-draft`` 只有外挂式要,
#: ``--spec-draft-n-max`` 控制块大小。
SPEC_TYPE_FLAG = "--spec-type"
DRAFT_MODEL_FLAG = "--model-draft"
SPEC_N_MAX_FLAG = "--spec-draft-n-max"


def server_moe_offload_supported() -> bool:
    """这条路能不能做专家卸载 —— 问这个构建的帮助,不是问约定。"""
    return MOE_FLAG in server_supported_flags()


def server_draft_supported() -> bool:
    """这条路能不能挂草稿位。"""
    return SPEC_TYPE_FLAG in server_supported_flags()


# ── 旗标组装:唯一定义处,纯函数 ────────────────────────────────────────────


@dataclass(frozen=True)
class ServerPlan:
    """一次启动要用的完整命令行,以及**被丢掉的东西和原因**。

    ``notes`` 不是日志的替代品,是结论的一部分:调用方据此判断"专家卸载到底生没
    生效"。第一版只返回 argv,于是"这个构建不支持 --n-cpu-moe"这件事只能靠翻日志,
    而那正是旧实现里静默失效的形状。
    """

    argv: Tuple[str, ...] = ()
    #: 被丢掉的能力与原因,一条一句人话。
    notes: Tuple[str, ...] = ()
    #: 专家卸载**确实**进了命令行。准入那条 7.3 GB 的账只有在这一位为真时才成立。
    moe_offload_applied: bool = False
    #: 草稿位确实进了命令行。
    draft_applied: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "argv": list(self.argv),
            "notes": list(self.notes),
            "moe_offload_applied": self.moe_offload_applied,
            "draft_applied": self.draft_applied,
        }


def build_server_args(
    *,
    model_path: str,
    port: int,
    alias: str = "",
    n_gpu_layers: int = -1,
    n_ctx: int = 0,
    n_cpu_moe: int = 0,
    draft_spec_type: str = "",
    draft_model_path: str = "",
    draft_n_max: int = 0,
    supported_flags: Optional[frozenset] = None,
    binary: str = "",
    host: str = "127.0.0.1",
) -> ServerPlan:
    """把分配结果 + 草稿位声明拼成 ``llama-server`` 的完整命令行。

    纯函数:不起进程、不读文件、不查环境(``supported_flags`` 与 ``binary`` 都可注入)。
    命令行拼错的后果是"起不来"或"旗标被忽略",两者在生产上都表现为"改了没效果",
    所以这一步必须能被完整单测。

    只传这个构建**认识**的旗标;认不得的**不传并记一条 note** —— 传了要么让服务
    起不来,要么被吞掉,而被吞掉正是这一整个模块要终结的失败方式。
    """
    flags = server_supported_flags() if supported_flags is None else supported_flags
    exe = binary or llama_server_binary() or SERVER_BINARY_NAME

    argv: List[str] = [exe, "-m", model_path, "--host", host, "--port", str(int(port))]
    notes: List[str] = []

    # 空的能力清单是**问不到**,不是"这个构建什么都不支持"。两者对用户是两回事:
    # 前者去装个二进制,后者去换个构建。逐条报"这个构建不认识 X" 会把前者说成后者,
    # 于是人对着一个根本没装的东西研究它为什么不支持某个旗标。
    unprobed = not flags
    if unprobed:
        notes.append(
            "问不到 llama-server 的能力清单(二进制不在,或 --help 读不出来)—— "
            "下面这条命令只含通用旗标,专家卸载与草稿位都没拼进去"
        )

    def _note(msg: str) -> None:
        """能力清单问得到时才逐条解释;问不到时上面那一条已经说清了。"""
        if not unprobed:
            notes.append(msg)

    if alias:
        # 让服务对外报的模型名就是目录里的 tag,路由那边不必再靠
        # GALAXY_LOCAL_OPENAI_SERVES 声明"这个服务伺候的是哪个型号"。
        if "--alias" in flags:
            argv += ["--alias", alias]
        else:
            _note("这个构建不认识 --alias,服务报的模型名将是权重文件名而非目录 tag")

    if n_gpu_layers is not None and int(n_gpu_layers) != 0:
        argv += ["--n-gpu-layers", str(int(n_gpu_layers))]
    if n_ctx and int(n_ctx) > 0:
        argv += ["--ctx-size", str(int(n_ctx))]

    # ── 专家卸载 ──
    moe_applied = False
    if n_cpu_moe:
        if MOE_FLAG in flags:
            argv += [MOE_FLAG, str(int(n_cpu_moe))]
            moe_applied = True
        else:
            _note(
                f"这个构建不认识 {MOE_FLAG} —— 专家卸载没生效,"
                "而准入是按「专家留内存」的显存账放行的,显存不足时会 OOM"
            )

    # ── 草稿位 ──
    draft_applied = False
    if draft_spec_type:
        if SPEC_TYPE_FLAG not in flags:
            _note(f"这个构建不认识 {SPEC_TYPE_FLAG} —— 草稿位没挂上")
        elif draft_model_path and DRAFT_MODEL_FLAG not in flags:
            _note(f"这个构建不认识 {DRAFT_MODEL_FLAG} —— 外挂式草稿位没挂上")
        else:
            argv += [SPEC_TYPE_FLAG, draft_spec_type]
            if draft_model_path:
                argv += [DRAFT_MODEL_FLAG, draft_model_path]
            if draft_n_max and int(draft_n_max) > 0:
                if SPEC_N_MAX_FLAG in flags:
                    argv += [SPEC_N_MAX_FLAG, str(int(draft_n_max))]
                else:
                    # 块大小传不进去是**实质性**的:上游默认 15 在公开实测里是净亏,
                    # 而实测选出来的往往是 4。说清楚,别让人以为实测结论生效了。
                    _note(f"这个构建不认识 {SPEC_N_MAX_FLAG} —— 块大小用的是构建默认值," "而不是真机实测选出来的那个")
            draft_applied = True

    return ServerPlan(
        argv=tuple(argv),
        notes=tuple(notes),
        moe_offload_applied=moe_applied,
        draft_applied=draft_applied,
    )


def free_port() -> int:
    """向内核要一个空闲端口。见模块头"端口不占注册表"。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ── 进程监管 ────────────────────────────────────────────────────────────────


@dataclass
class LlamaServerProcess:
    """我们自己起、自己关的那个 ``llama-server``。

    刻意**不是** ``LocalModelBackend`` 的子类:那个基类在
    ``core.local_model_backends`` 里,而本模块要被它引用(算旗标、问能力)。让重逻辑
    不依赖那个基类,既避开循环导入,也让启动/探活/收尾能脱离后端 ABC 单独测。
    后端那一侧只是一层很薄的适配。
    """

    model_id: str = ""
    port: int = 0
    plan: Optional[ServerPlan] = None
    _proc: Any = None
    _started_at: float = 0.0
    #: 启动失败时那句人话。空 = 没失败过。
    error: str = ""
    _env_exported: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def base_url(self) -> str:
        """OpenAI 兼容根。没起来返回空串。"""
        return f"http://127.0.0.1:{self.port}/v1" if self.port and self.is_running else ""

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(
        self,
        *,
        model_path: str,
        alias: str = "",
        n_gpu_layers: int = -1,
        n_ctx: int = 0,
        n_cpu_moe: int = 0,
        draft_spec_type: str = "",
        draft_model_path: str = "",
        draft_n_max: int = 0,
        spawn: Any = None,
        health: Any = None,
        timeout_s: float = STARTUP_TIMEOUT_S,
        export_env: bool = True,
        binary: str = "",
        supported_flags: Optional[frozenset] = None,
    ) -> bool:
        """起服务并等它就绪。起不来返回 False,原因留在 :attr:`error`。

        ``spawn`` / ``health`` 可注入,于是整条启动逻辑(包括超时与失败归因)能在
        不起任何进程的情况下被测到。
        """
        if not model_path:
            self.error = "没有权重路径 —— 这个型号的 GGUF 不在本机"
            return False
        binary = binary or llama_server_binary() or ""
        if not binary:
            self.error = (
                f"找不到 {SERVER_BINARY_NAME}。装一个 llama.cpp 的构建," "或用 GALAXY_LLAMA_SERVER_BIN 指到你自己那份"
            )
            return False

        self.port = self.port or free_port()
        self.plan = build_server_args(
            model_path=model_path,
            port=self.port,
            alias=alias,
            n_gpu_layers=n_gpu_layers,
            n_ctx=n_ctx,
            n_cpu_moe=n_cpu_moe,
            draft_spec_type=draft_spec_type,
            draft_model_path=draft_model_path,
            draft_n_max=draft_n_max,
            binary=binary,
            supported_flags=supported_flags,
        )
        for note in self.plan.notes:
            # 每一条都是"你以为开着、其实没开"的候选,必须响亮。
            logger.warning("llama-server 启动计划: %s", note)

        launch = spawn or _spawn
        try:
            self._proc = launch(list(self.plan.argv))
        except Exception as exc:  # noqa: BLE001
            self.error = f"起不来: {exc}"
            logger.warning("llama-server 启动失败: %s", exc)
            return False

        self._started_at = time.time()
        probe = health or self._http_health
        deadline = self._started_at + float(timeout_s)
        while time.time() < deadline:
            if not self.is_running:
                self.error = f"进程提前退出(exit={self._proc.poll()}) —— 多半是旗标或权重的问题"
                logger.warning("llama-server %s", self.error)
                return False
            if probe(self.port):
                logger.info(
                    "llama-server 就绪 port=%s 专家卸载=%s 草稿位=%s",
                    self.port,
                    self.plan.moe_offload_applied,
                    self.plan.draft_applied,
                )
                if export_env:
                    self._export_env(alias or self.model_id)
                return True
            time.sleep(_POLL_INTERVAL_S)

        self.error = f"{timeout_s:.0f}s 内没就绪"
        logger.warning("llama-server 启动超时,已收掉")
        self.stop()
        return False

    def _export_env(self, served_tag: str) -> None:
        """把地址交给路由 —— 它读的是 ``GALAXY_LOCAL_OPENAI_URL``。

        这样 ``multi_llm_router`` 不必认识本模块就能用上这个服务;而
        ``GALAXY_LOCAL_OPENAI_SERVES`` 声明"它伺候的是哪个目录型号",槽位解析
        据此把推理位落到它身上(见 ``_local_by_slot``)。
        """
        exported: List[str] = []
        os.environ["GALAXY_LOCAL_OPENAI_URL"] = f"http://127.0.0.1:{self.port}/v1"
        exported.append("GALAXY_LOCAL_OPENAI_URL")
        if served_tag:
            os.environ["GALAXY_LOCAL_OPENAI_SERVES"] = served_tag
            exported.append("GALAXY_LOCAL_OPENAI_SERVES")
        self._env_exported = tuple(exported)

    @staticmethod
    def _http_health(port: int) -> bool:
        try:
            import httpx  # noqa: PLC0415

            resp = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:  # noqa: BLE001 — 还没起来就是还没起来
            return False

    def stop(self, *, grace_s: float = 10.0) -> None:
        """收掉服务。先客气后强硬,两步都不抛。"""
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=grace_s)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception as exc:  # noqa: BLE001
                logger.debug("llama-server 收尾失败(进程可能已经没了): %s", exc)
        # 起服务时导出的那几个键要收回去 —— 留着会让路由继续往一个已经关掉的
        # 端口发请求,报错在别处,看不出跟这次关停有关。
        for key in self._env_exported:
            os.environ.pop(key, None)
        self._env_exported = ()


def _spawn(argv: Sequence[str]) -> Any:
    return subprocess.Popen(  # noqa: S603 — argv 由 build_server_args 组装,无 shell
        list(argv),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


__all__ = [
    "SERVER_BINARY_NAME",
    "SERVER_BINARY_NAMES",
    "STARTUP_TIMEOUT_S",
    "MOE_FLAG",
    "SPEC_TYPE_FLAG",
    "DRAFT_MODEL_FLAG",
    "SPEC_N_MAX_FLAG",
    "ServerPlan",
    "LlamaServerProcess",
    "llama_server_binary",
    "server_supported_flags",
    "server_moe_offload_supported",
    "server_draft_supported",
    "build_server_args",
    "free_port",
    "reset_flag_cache",
]
