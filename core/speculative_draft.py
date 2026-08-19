"""core/speculative_draft.py — 投机解码的草稿位(声明 × 绑定能力 × 真机实测)
=============================================================================

投机解码是**再挂一个小模型**:草稿模型一次抢答一整块 token,目标模型回头验一遍。
验过的照收、验错的丢掉 —— 所以输出**无损**(贪心逐 token 相同,采样保持分布)。

为什么这件事不能做成一个开关
----------------------------
因为它**不一定更快**,而且方向取决于机器,不取决于代码:

* 上游自己写着 MoE 上加速更低;
* 公开实测里既有 2.69× 也有 **净 −44.6%**(RTX 3090 + Q4_K_XL 走 llama.cpp);
* 同一台机器上 ``--spec-draft-n-max`` 取默认 15 是净亏、取 4 才 +27%。

也就是说,"要不要开"和"开多大块"这两件事,**没有任何一处代码能替这台机器回答**。
本仓库对这类问题已经有一条既定处置:不臆造,问出来(见 ``core/model_probe.py``)。
所以这里同样切成三件互不冒充的事:

============  ================================================================
声明          目录里静态写着:这个型号**有没有**草稿模型可挂、走哪套机制。
              见 :class:`DraftSpec`。它回答"存不存在",不回答"值不值得"。
绑定能力      这台机器上的加载器**透不透得出**那些参数。见
              :func:`llama_binding_draft_support`。它回答"接不接得上"。
真机实测      开/关各跑一遍,比 tok/s。见 :class:`DraftMeasurement`。
              **只有它回答"值不值得",而且默认是没测过 → 不开。**
============  ================================================================

绑定那一维为什么必须单独探
--------------------------
DFlash 在 llama.cpp 是 **CLI/server 的旗标**(``--dflash`` / ``-md`` /
``--spec-type draft-dflash`` / ``--spec-draft-n-max``),而本仓库的 C/D 推理位走的是
``llama-cpp-python`` **进程内**加载。这个洞仓库已经踩过一次 ——
``core/local_model_backends.py`` 里那条 warning 记着:``--n-cpu-moe`` 在 CLI 上有、
在 python 绑定上没有,于是 C 档的专家卸载在多数机器上**静默不生效**。

同一个洞极可能原样重现。所以这里不假设绑定支持,**去问签名**;问不到就如实报
``unsupported``,而不是把旗标塞进 kwargs 让它被静默忽略 —— 后者的表现是"开了但
没变快",查起来要从头怀疑一遍。

"没查过" 与 "确认没有" 是两件事
-------------------------------
``mechanism`` 默认 ``"unknown"`` 而不是 ``"none"``,与 ``ModelSpec.is_moe`` 用
``Optional[bool]`` 是同一条:前者该去问,后者到此为止。压成一个值的话,"还没查"
会被当成"查过了,没有",于是永远不会再有人去查。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

logger = logging.getLogger("Galaxy.SpeculativeDraft")

#: 仓库根 —— 与 ``core/model_catalog.py`` 取法一致(本文件在 ``core/`` 下)。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 声明维 ──────────────────────────────────────────────────────────────────

#: 草稿位走哪套机制。``unknown`` = 没人查过(默认);``none`` = 查过,确认没有。
#:
#: * ``dflash``      —— llama.cpp + **外挂**的 DFlash 块扩散草稿检查点
#:                      (``--spec-type draft-dflash`` + ``-md <检查点>``)
#: * ``mtp_self``    —— llama.cpp + 模型**自带**的 MTP 头
#:                      (``--spec-type draft-mtp``,无外挂检查点)
#: * ``ollama_mtp``  —— Ollama 那套:Modelfile 的 ``DRAFT`` 指令 + MTP
#:
#: 三套刻意分开,不是分类癖:
#:
#: * ``dflash`` 与 ``mtp_self`` 都走 llama.cpp,但**一个要下第二份权重、一个不要** ——
#:   显存账、可用性判定、失败模式全不一样。压成一个"投机解码",准入就没法算了。
#: * ``ollama_mtp`` 接的是另一个后端(``source="local"``),参数与开启方式与前两者
#:   毫无共同之处。
#:
#: 合成一个开关,等于让调用方拿着一个它无法正确使用的抽象。
DRAFT_MECHANISMS: Tuple[str, ...] = ("unknown", "none", "dflash", "mtp_self", "ollama_mtp")

#: 走 llama.cpp 的那两套,各自的 ``--spec-type`` 取值。表在这里,不在调用点上拼 ——
#: 拼字符串的话,哪天多一套机制,这里会静默少一条而不是报错。
SPEC_TYPE_OF: Dict[str, str] = {
    "dflash": "draft-dflash",
    "mtp_self": "draft-mtp",
}

#: 真正是一套机制的那几个 —— 从 :data:`DRAFT_MECHANISMS` 减去两个"元"取值派生,
#: **不重抄一遍**。第一版把它们抄成了字面元组,加 ``mtp_self`` 时漏改了其中一处,
#: 表现是新机制被判成"没人查过",探测直接不列它 —— 不报错、不变慢,只是不生效。
_REAL_MECHANISMS: Tuple[str, ...] = tuple(m for m in DRAFT_MECHANISMS if m not in ("unknown", "none"))

#: 需要**外挂**一份草稿权重的机制。其余的草稿在目标模型自己身上。
#: 这一栏决定 ``is_possible`` 要不要求有候选检查点,也决定显存要不要多算一份。
NEEDS_EXTERNAL_CHECKPOINT: Tuple[str, ...] = ("dflash",)


@dataclass(frozen=True)
class DraftSpec:
    """一个型号的草稿位**声明** —— 回答"存不存在",不回答"值不值得"。"""

    mechanism: str = "unknown"
    #: 候选检查点标识。**未经真机核实** —— 探测脚本拿它去问,问不到就是没有。
    #:
    #: 刻意叫"候选"而不是"检查点":这些名字来自上游文档与检索,不是这台机器上
    #: 真实存在的东西。仓库对二手数字的处置一以贯之 —— 可以拿来当**假设**去问,
    #: 不能拿来当**事实**去填。空 = 连候选都没有,探测无从下手。
    candidate_repos: Tuple[str, ...] = ()
    #: 草稿模型跑起来额外占多少加速器内存(MB)。``0`` = **没量过**。
    #:
    #: 注意 ``0`` 不是"不占" —— 草稿是**额外**权重,一定占。准入把它当 0 处理,
    #: 就是仓库里记着的那个 MiniCPM-o 故障形态:准入判"放得下",加载到一半 OOM,
    #: 报错还在加载**途中**不在准入处。所以 :func:`tier_draft_footprint_mb`
    #: 遇到"已启用但没量过"会显式报判不了,而不是加 0。
    runtime_mb_val: int = 0
    note: str = ""

    @classmethod
    def unknown(cls) -> "DraftSpec":
        return cls()

    @property
    def is_settled(self) -> bool:
        """有没有人查过这一栏。``unknown`` 之外都算查过(含确认没有)。"""
        return self.mechanism != "unknown"

    @property
    def needs_external_checkpoint(self) -> bool:
        """这套机制要不要再下一份草稿权重。自带 MTP 头的不要。"""
        return self.mechanism in NEEDS_EXTERNAL_CHECKPOINT

    @property
    def is_possible(self) -> bool:
        """这个型号**可能**挂得上草稿。

        外挂式的还要求至少有一个候选可问 —— 声明了 ``dflash`` 却一个检查点都没有,
        探测无从下手,那和没声明是一回事。自带 MTP 头的不需要候选:草稿就在权重里,
        要问的是"这份 GGUF 里到底有没有那个头",而那只有真机答得出。
        """
        if self.mechanism not in _REAL_MECHANISMS:
            return False
        return bool(self.candidate_repos) if self.needs_external_checkpoint else True

    @property
    def spec_type(self) -> str:
        """llama.cpp 的 ``--spec-type`` 取值;不走 llama.cpp 的机制返回空串。"""
        return SPEC_TYPE_OF.get(self.mechanism, "")

    def runtime_mb(self) -> int:
        """草稿额外占多少(MB);``0`` = 没量过,**不是**不占。"""
        return int(self.runtime_mb_val or 0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mechanism": self.mechanism,
            "candidate_repos": list(self.candidate_repos),
            "runtime_mb": self.runtime_mb(),
            "measured": self.runtime_mb() > 0,
            "is_possible": self.is_possible,
            "needs_external_checkpoint": self.needs_external_checkpoint,
            "spec_type": self.spec_type,
            "note": self.note,
        }


# ── 绑定能力维 ──────────────────────────────────────────────────────────────

#: 这台机器上的加载器接不接得上草稿位。
#:
#: ``absent`` 与 ``unsupported`` 刻意分开:前者是没装 ``llama-cpp-python``(装上
#: 可能就有),后者是装了但这个版本/构建不透出参数(得换构建或改走 llama-server)。
#: 合成一个"不支持",用户会去装一个已经装好的东西。
BINDING_SUPPORT: Tuple[str, ...] = ("unknown", "absent", "unsupported", "supported")

#: 在 ``llama_cpp.Llama.__init__`` 上找这些参数名之一,即认为绑定透出了草稿位。
#:
#: 列一组而不是钉死一个:上游改过名字(``draft_model`` 是长期存在的那个,
#: 后来的 DFlash 支持另走 ``spec_*``)。多认几个别名的代价是可能误报支持,
#: 而只认一个的代价是**明明支持却报不支持** —— 后者会让整条路被误判为死路。
_DRAFT_PARAM_NAMES: Tuple[str, ...] = (
    "draft_model",
    "spec_type",
    "spec_draft_n_max",
    "model_draft",
    "dflash",
)


def llama_binding_draft_support() -> Tuple[str, Tuple[str, ...]]:
    """问 ``llama-cpp-python`` 的构造函数签名:草稿位的参数透出来了吗。

    Returns:
        ``(结论, 找到的参数名)``。结论取值见 :data:`BINDING_SUPPORT`。

    **只读签名,不加载任何模型** —— 与 ``LocalBrainManager`` 那边探 ``n_cpu_moe``
    用的是同一招(见 ``core/local_model_backends.py`` 的 ``_apply_moe_offload``),
    因为那正是这个洞第一次被发现的地方。
    """
    try:
        import inspect  # noqa: PLC0415

        from llama_cpp import Llama  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — 没装就是没装,不是错误
        logger.debug("llama-cpp-python 不可用,草稿位绑定按 absent 处理: %s", exc)
        return "absent", ()

    try:
        params = set(inspect.signature(Llama.__init__).parameters)
    except (TypeError, ValueError) as exc:
        logger.debug("llama-cpp-python 签名读不出来: %s", exc)
        return "unknown", ()

    found = tuple(p for p in _DRAFT_PARAM_NAMES if p in params)
    return ("supported" if found else "unsupported"), found


# ── 实测维 ──────────────────────────────────────────────────────────────────

#: 真机 A/B 的结论。默认 ``untested`` —— **那不是"没问题",是"没验成"**。
#:
#: ``slower`` 是一个**真实且常见**的结果,必须能被表达出来:公开数据里 RTX 3090 +
#: Q4 走 llama.cpp 是净 −44.6%。把它和 ``error`` 合并,会让"测过了,结论是别开"
#: 看起来像"测挂了,回头再试"。
DRAFT_VERDICTS: Tuple[str, ...] = ("untested", "faster", "slower", "unsupported", "error")

#: 判定为"更快"所需的最小提速。低于它的差异淹没在采样噪声里 —— 拿 1% 的
#: 波动去开一个要占显存的东西不划算。
MIN_SPEEDUP: float = 1.05


@dataclass(frozen=True)
class DraftMeasurement:
    """一次真机 A/B 的结果。**这是唯一有资格说"值不值得"的东西。**"""

    tag: str
    verdict: str = "untested"
    baseline_tok_s: float = 0.0
    draft_tok_s: float = 0.0
    #: ``draft_tok_s / baseline_tok_s``;``0`` = 没测出来。**小于 1 表示更慢。**
    speedup: float = 0.0
    #: 这次用的草稿块大小(``--spec-draft-n-max``)。默认 15 在公开实测里是净亏,
    #: 所以这一位必须记下来 —— 否则复现不了,也说不清结论是针对哪个配置的。
    n_max: int = 0
    drafter_repo: str = ""
    #: 实测到的草稿额外显存(MB)。``0`` = 没量到。
    drafter_runtime_mb: int = 0
    measured_at: float = 0.0
    detail: str = ""

    @property
    def should_enable(self) -> bool:
        """够不够格开:测过、判为更快、且提速过得了 :data:`MIN_SPEEDUP` 这道线。"""
        return self.verdict == "faster" and self.speedup >= MIN_SPEEDUP

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "verdict": self.verdict,
            "baseline_tok_s": round(float(self.baseline_tok_s), 3),
            "draft_tok_s": round(float(self.draft_tok_s), 3),
            "speedup": round(float(self.speedup), 4),
            "n_max": int(self.n_max),
            "drafter_repo": self.drafter_repo,
            "drafter_runtime_mb": int(self.drafter_runtime_mb),
            "measured_at": float(self.measured_at),
            "should_enable": self.should_enable,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "DraftMeasurement":
        verdict = str(raw.get("verdict", "untested"))
        return cls(
            tag=str(raw.get("tag", "")),
            verdict=verdict if verdict in DRAFT_VERDICTS else "untested",
            baseline_tok_s=float(raw.get("baseline_tok_s", 0.0) or 0.0),
            draft_tok_s=float(raw.get("draft_tok_s", 0.0) or 0.0),
            speedup=float(raw.get("speedup", 0.0) or 0.0),
            n_max=int(raw.get("n_max", 0) or 0),
            drafter_repo=str(raw.get("drafter_repo", "") or ""),
            drafter_runtime_mb=int(raw.get("drafter_runtime_mb", 0) or 0),
            measured_at=float(raw.get("measured_at", 0.0) or 0.0),
            detail=str(raw.get("detail", "") or ""),
        )


# ── 实测结果的持久化 ────────────────────────────────────────────────────────
#
# 单独一个文件,**不并进** runtime/model_state.json。那份记的是"用户选了哪一档",
# 是人的决定;这份记的是"这台机器上测出来什么",是机器的事实。两者的生命周期
# 不同(换机器要重测,换档位不用),写在一起会互相牵连 —— 而那个文件已经因为
# 全会话共享踩过一次坑(一个临时脚本把它落成 C,两条无关测试一起变红)。

#
# 路径**不做 env 覆盖**,与 ``model_catalog._STATE_FILE`` 同一条约定。
#
# 第一版给了个 ``GALAXY_DRAFT_STATE_FILE`` 纯粹为了测试隔离,CI 当场拦下:凡是被代码
# 读取的 ``GALAXY_*`` 都得登记进 ``CONFIG_SCHEMA`` 与面板的 ``CONFIG_KEYS``,否则
# ``POST /api/config`` 会把它当 unknown_keys 拒掉 —— 而"运行时状态文件放哪"根本不该
# 出现在面板上(与已豁免的 ``GALAXY_CONFIG_PATH`` 是同一个"站在梯子上搬梯子"的问题,
# 何况让配置接口指定任意写入路径本身也不是好主意)。
#
# 测试要隔离就直接改这个模块级常量 —— 隔壁 ``model_catalog`` 从来就是这么做的。
_STATE_FILE = PROJECT_ROOT / "runtime" / "speculative_draft.json"

_lock = threading.Lock()


def state_file() -> Path:
    """实测结果落在哪。测试要隔离就 monkeypatch 本模块的 ``_STATE_FILE``。"""
    return _STATE_FILE


def _read_all() -> Dict[str, Any]:
    path = state_file()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:  # noqa: BLE001 — 读不出来等于没测过
        logger.debug("草稿实测记录读取失败,按没测过处理: %s", exc)
    return {}


def load_measurement(tag: str) -> DraftMeasurement:
    """取某型号的实测结果;没有就是 ``untested``(**不是** None)。

    返回语义明确的空态而不是 None:调用方读到 ``untested`` 知道"没验成",
    读到 None 只会去补一个默认值 —— 而这里唯一安全的默认是"别开"。
    """
    raw = _read_all().get(str(tag or ""))
    if not isinstance(raw, dict):
        return DraftMeasurement(tag=str(tag or ""))
    return DraftMeasurement.from_dict({**raw, "tag": str(tag or "")})


def save_measurement(m: DraftMeasurement) -> None:
    """写回一条实测结果(原子写,逐型号覆盖)。"""
    if not m.tag:
        return
    with _lock:
        data = _read_all()
        data[m.tag] = m.to_dict()
        path = state_file()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            from core.atomic_json import atomic_write_json  # noqa: PLC0415

            atomic_write_json(path, data, indent=2, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 — 记不下来不该让探测失败
            logger.warning("草稿实测记录保存失败(非致命): %s", exc)


#: 逐趟原始结果挂在这个顶层键下,与逐型号的结论分开放。
#:
#: 带下划线前缀是为了跟型号 tag 划清界限 —— 目录里的 tag 形如 ``gemma4:e2b`` /
#: ``openbmb/minicpm-o4.5``,不会以下划线开头。同一层里混着两种含义的键,
#: 迟早有人遍历它当型号表用。
_RUNS_KEY = "_runs"


def save_labelled_run(tag: str, label: str, run: Dict[str, Any]) -> None:
    """记下一趟**人工标注**的量测结果(``label`` 为 ``"baseline"`` 或块大小)。

    llama-server 的草稿位旗标是**启动参数**,一个进程里切不了 —— 所以两趟之间人
    要重起一次服务,而"这一趟是哪个配置"只能由人声明。这里如实按人给的标签存,
    不去猜服务是怎么起的:猜错了会把同一个配置量两遍,还得出一个漂亮的 1.00×。
    """
    if not tag or not label:
        return
    with _lock:
        data = _read_all()
        runs = data.get(_RUNS_KEY)
        if not isinstance(runs, dict):
            runs = {}
        per_tag = runs.get(tag)
        if not isinstance(per_tag, dict):
            per_tag = {}
        per_tag[str(label)] = dict(run)
        runs[tag] = per_tag
        data[_RUNS_KEY] = runs
        path = state_file()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            from core.atomic_json import atomic_write_json  # noqa: PLC0415

            atomic_write_json(path, data, indent=2, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("草稿量测记录保存失败(非致命): %s", exc)


def load_labelled_runs(tag: str) -> Dict[str, Dict[str, Any]]:
    """取某型号已经量过的那几趟;一趟都没有返回空字典。"""
    runs = _read_all().get(_RUNS_KEY)
    if not isinstance(runs, dict):
        return {}
    per_tag = runs.get(str(tag or ""))
    return dict(per_tag) if isinstance(per_tag, dict) else {}


def is_enabled(tag: str) -> bool:
    """这台机器上,这个型号的草稿位该不该开。

    三个条件同时成立才开 —— 少一条都不开:

    1. 目录声明了机制且有候选(:attr:`DraftSpec.is_possible`);
    2. 实测判为更快且过了 :data:`MIN_SPEEDUP`;
    3. env 没有显式关掉(``GALAXY_SPECULATIVE_DRAFT=0``)。

    **默认关**是有意的:没测过的机器上开它,期望值是负的(公开实测里净亏的
    那一档正是本仓库 C 档那种 MoE + 量化的组合)。
    """
    raw = os.environ.get("GALAXY_SPECULATIVE_DRAFT", "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if not draft_spec_of(tag).is_possible:
        return False
    return load_measurement(tag).should_enable


def draft_spec_of(tag: str) -> DraftSpec:
    """取某型号的草稿声明;目录里没有这一条就是 :meth:`DraftSpec.unknown`。

    走 ``exact_model`` 而不是 ``get_model`` —— 与显存口径同一条纪律:同家族兜底
    对"由哪个后端加载"是对的,对"挂哪个草稿"是错的(35B 的草稿不能给 2B 用)。
    """
    try:
        from core.model_catalog import exact_model  # noqa: PLC0415

        spec = exact_model(tag)
    except Exception as exc:  # noqa: BLE001 — 目录不可用不该让这里崩
        logger.debug("目录不可用,草稿声明按 unknown 处理: %s", exc)
        return DraftSpec.unknown()
    if spec is None:
        return DraftSpec.unknown()
    got = getattr(spec, "draft", None)
    return got if isinstance(got, DraftSpec) else DraftSpec.unknown()


def draft_footprint_mb(tag: str) -> Tuple[int, str]:
    """这个型号**当前**要为草稿位额外留多少显存(MB)。

    Returns:
        ``(额外 MB, 说明)``。``(-1, ...)`` = **判不了** —— 已启用但没量过占多少。

    为什么"判不了"要用 -1 而不是 0:0 会被求和处静默吸收,于是准入拿着一个偏小的
    门槛放行,加载到一半 OOM —— 正是目录里记着的那个故障形态。判不了必须能被
    调用方看见,见 ``core.model_catalog.tier_runtime_footprint_range_mb``。
    """
    if not is_enabled(tag):
        return 0, "草稿位未启用"
    spec = draft_spec_of(tag)
    m = load_measurement(tag)
    mb = int(m.drafter_runtime_mb or 0) or spec.runtime_mb()
    if mb > 0:
        return mb, f"草稿位已启用({m.drafter_repo or spec.mechanism}),额外 {mb} MB"
    if not spec.needs_external_checkpoint:
        # 自带 MTP 头:草稿就在目标模型的权重里,本来就没有"额外一份"。
        # 这里报 0 是**确定的 0**,不是"没量过" —— 与下面那条判不了完全不同。
        #
        # (它仍会多占一点 —— 多验几个 token 的激活与 KV。那点开销跟着上下文预算走,
        #  不是一份独立权重,不该在这条按"多一个模型"计的账里估。)
        return 0, "草稿位已启用(自带 MTP 头,无外挂权重)"
    return -1, "草稿位已启用但没人量过它占多少显存"


SPECULATIVE_DRAFT_AUTHORITY: str = (
    "SPECULATIVE_DRAFT_V1: core/speculative_draft.py | 投机解码草稿位唯一入口. "
    "三维互不冒充: 声明(DraftSpec, 目录静态, 回答存不存在) × 绑定能力"
    "(llama_binding_draft_support, 读 llama-cpp-python 签名, 回答接不接得上) × "
    "真机实测(DraftMeasurement, 回答值不值得). is_enabled() 三条全成立才开, "
    "默认关. draft_footprint_mb() 返回 -1 表示判不了(已启用但没量过), "
    "调用方不得当 0 吸收. 实测记录独立落 runtime/speculative_draft.json."
)

__all__ = [
    "DRAFT_MECHANISMS",
    "SPEC_TYPE_OF",
    "NEEDS_EXTERNAL_CHECKPOINT",
    "BINDING_SUPPORT",
    "DRAFT_VERDICTS",
    "MIN_SPEEDUP",
    "DraftSpec",
    "DraftMeasurement",
    "llama_binding_draft_support",
    "draft_spec_of",
    "draft_footprint_mb",
    "is_enabled",
    "load_measurement",
    "save_measurement",
    "save_labelled_run",
    "load_labelled_runs",
    "state_file",
    "SPECULATIVE_DRAFT_AUTHORITY",
]
