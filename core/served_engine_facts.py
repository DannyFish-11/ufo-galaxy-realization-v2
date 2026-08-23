"""core/served_engine_facts.py — 模型由外部引擎伺候时，**问它，别算它**
================================================================================

修的是什么
==========
:meth:`core.compute_scheduler.ComputeScheduler.context_budget_for` 算 ``n_ctx``
的那一路，前提是**我们自己加载模型**：显存是我们的、KV cache 是我们分配的，所以
"能开多长"由我们说了算。

可模型由一台 OpenAI 兼容引擎伺候时（FreeToken 的 ``ft serve``、vLLM、llama.cpp
server），这个前提整个不成立：

* 权重是**它**加载的，KV cache 是**它**分配的；
* FreeToken 更是把这件事做成动态的 —— ``--memory-ratio 0.9`` + ``--moe-cache-auto``
  + ``--num-tokens auto``，KV 容量取"权重和专家缓存之后剩下的显存"，而且
  ``POST /v1/cache/rebuild`` 可以**不重启就改**。

于是我们算出来的那个 ``n_ctx`` 不再是"我要开多长"，而是**对别人已经开了多长的一次
猜测**。猜高了：模型早就被引擎截断，而截断在那一层是无声的；猜低了：白白提前压缩、
丢细节。而这个数同时是压缩阈值（``OpenClawd._react_n_ctx`` 就取自同一处），所以猜错
的代价是双份的。

而这件事**根本不需要猜**：引擎自己报。

两个数不是一回事
================
FreeToken 的源码把这层区别写得很清楚（``server/openai_api.py::_model_context_length``）::

    The model ceiling, not `min(ceiling, KV budget)`: a rebuild moves the latter,
    and agents read this once at startup.

* ``/v1/models`` 的 ``context_length`` / ``/v1/stats`` 的 ``model.ctx`` —— **模型
  天花板**（``max_seq_len``）。与我们目录里的 ``max_ctx_val`` 同一个口径；
* ``/v1/stats`` 的 ``kv.total_pages × kv.page_size`` —— **此刻真正装得下多少
  token**，而且它会随 cache rebuild 变。

**真正能用的是两者取小。** 只看天花板就会高估到被截断；只看 KV 又会在没报 KV 的
引擎上什么都得不到。

与本仓其它几处同一个立场
========================
``effective_weight_mb``（磁盘上的真文件压过目录声明）、``context_measurements``
（实测 KV 单价压过目录声明）—— 这里是第三处：**引擎报的真实容量压过我们的静态
推算**。都遵循同一条：可量的量，量不到才退回声明，而且退回时要说出来。

问不到就返回 ``None``，调用方原样走老路径 —— 没配引擎时行为逐字节不变。
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.ServedEngineFacts")

#: 探活超时（秒）。这条在装配路径上，不能因为一台没起来的服务把整条链拖住。
PROBE_TIMEOUT_S = 1.5

#: 探到的事实缓存多久。
#:
#: **不能缓存太久**：KV 容量会随 ``POST /v1/cache/rebuild`` 变，缓存久了拿到的就是
#: 一个过期的"真值"，比静态推算更有欺骗性（它看起来是量出来的）。也不能不缓存：
#: ``context_budget_for`` 在换档与每次 ReAct 循环开头都会走到。10 秒是个折中。
CACHE_TTL_S = 10.0

#: 可信区间 —— 与 ``core.context_measurements`` 的 ``_MIN/_MAX_CREDIBLE_*`` 同一个
#: 立场：**一个不可信的"实测值"比没有实测值更危险**，因为它会理直气壮地压过声明。
#: 下限取 1：报 0 或负数就是"没这个数"，不是"上下文为零"。
_MIN_CREDIBLE_CTX = 1
#: 上限取 16 M token。当前已知最长的是 Qwythos-9B 的 1 M，留一个数量级的余量;
#: 再大就不是"长上下文"而是"这个字段读错了"（比如把字节数当成了 token 数）。
_MAX_CREDIBLE_CTX = 1 << 24

_cache: Dict[str, tuple] = {}


@dataclass(frozen=True)
class ServedEngineFacts:
    """一台 OpenAI 兼容引擎**此刻**报出来的事实。"""

    #: 它自报的模型 id（FreeToken 默认取 ``--model`` 路径的 basename）。
    model_id: str
    #: 模型天花板（``max_seq_len``）。``0`` = 没报。
    model_ctx: int
    #: 此刻 KV 真正装得下多少 token。``0`` = 没报（例如非分页 KV 的实现）。
    kv_tokens: int
    #: 它此刻占了多少显存（MB）。``0`` = 没报。
    vram_mb: int
    #: 它认为这是不是 MoE；``None`` = 没报。
    is_moe: Optional[bool]
    #: 注意力形态：``mha`` / ``hybrid_linear`` / ``hybrid_swa``；``""`` = 没报。
    attn: str
    #: 这份事实是从哪个地址问来的 —— 理由串里要说得出来。
    base_url: str

    def usable_ctx(self) -> int:
        """**此刻真正能用多长** —— 天花板与 KV 容量取小；两个都没报返回 0。

        取小的理由见模块文档:只看天花板会高估到被引擎静默截断,只看 KV 会在没报
        KV 的引擎上什么都得不到。
        """
        known = [n for n in (self.model_ctx, self.kv_tokens) if n > 0]
        return min(known) if known else 0

    def why(self) -> str:
        """给理由串用的一句话 —— 这个数是谁报的、被哪一头卡住的。"""
        if self.kv_tokens > 0 and self.model_ctx > 0:
            capped = "KV 容量" if self.kv_tokens <= self.model_ctx else "模型上限"
            return f"引擎 {self.base_url} 实报：模型上限 {self.model_ctx}、KV 装得下 {self.kv_tokens}，取小（被{capped}卡住）"
        if self.model_ctx > 0:
            return f"引擎 {self.base_url} 实报模型上限 {self.model_ctx}（未报 KV 容量）"
        return f"引擎 {self.base_url} 实报 KV 装得下 {self.kv_tokens}（未报模型上限）"


def _credible_ctx(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    if n < _MIN_CREDIBLE_CTX or n > _MAX_CREDIBLE_CTX:
        return 0
    return n


def _get_json(base_url: str, path: str) -> Optional[dict]:
    """GET 一个只读端点；任何失败都返回 ``None``（探活不该把调用方拖崩）。"""
    url = base_url.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_S) as resp:  # noqa: S310
            if getattr(resp, "status", 200) != 200:
                return None
            body = resp.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.debug("探 %s 失败（服务没起来或不讲这套协议）: %s", url, exc)
        return None
    try:
        doc = json.loads(body)
    except (ValueError, TypeError):
        return None
    return doc if isinstance(doc, dict) else None


def probe(base_url: str, *, use_cache: bool = True) -> Optional[ServedEngineFacts]:
    """问一台引擎它此刻的真实容量；问不到返回 ``None``。

    走 ``GET /v1/stats``。这个端点是只读的控制面，FreeToken 把它列在
    ``access_log_filter`` 的静默名单里 —— 它本来就是被高频轮询的那类。
    """
    if not base_url:
        return None
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]

    now = time.monotonic()
    if use_cache:
        hit = _cache.get(root)
        if hit is not None and now - hit[0] < CACHE_TTL_S:
            return hit[1]

    doc = _get_json(root, "/v1/stats")
    facts: Optional[ServedEngineFacts] = None
    if doc is not None:
        model = doc.get("model") if isinstance(doc.get("model"), dict) else {}
        kv = doc.get("kv") if isinstance(doc.get("kv"), dict) else {}
        # kv 报的是**页**，一页多少 token 由它自己给 —— 不能假设 1。
        try:
            kv_tokens = int(kv.get("total_pages") or 0) * int(kv.get("page_size") or 0)
        except (TypeError, ValueError):
            kv_tokens = 0
        try:
            vram_mb = int(int(doc.get("vram_bytes") or 0) / (1024 * 1024))
        except (TypeError, ValueError):
            vram_mb = 0
        moe = model.get("moe")
        facts = ServedEngineFacts(
            model_id=str(model.get("id") or ""),
            model_ctx=_credible_ctx(model.get("ctx")),
            kv_tokens=_credible_ctx(kv_tokens),
            vram_mb=max(0, vram_mb),
            is_moe=bool(moe) if isinstance(moe, bool) else None,
            attn=str(model.get("attn") or ""),
            base_url=root,
        )
        if facts.usable_ctx() <= 0:
            # 应答了但没有任何可用的容量信息 —— 当作没问到，别让一个空壳事实
            # 去压过静态推算。
            #
            # **这一层在当前实现下是冗余的**：唯一的生产调用方
            # ``ComputeScheduler.context_budget_for`` 自己也判了 ``usable_ctx() > 0``，
            # 所以没有任何输入能把"这里返回空壳"与"这里返回 None"区分开 —— 反向
            # 验证时把它拆掉，一条测试都不红。留着是因为它把**契约**写死在产出端：
            # 「本函数返回的 facts，usable_ctx() 必然为正」。一旦有第二个调用方（比如
            # 状态盘想显示引擎实报容量）忘了判，它就从冗余变成承重的。
            # 与 ``context_runway.burn_per_round`` 里那层非正增量过滤同一个性质。
            logger.debug("%s 应答了 /v1/stats 但没有可信的上下文容量，按问不到处理", root)
            facts = None

    _cache[root] = (now, facts)
    return facts


def _lane_urls() -> Dict[str, str]:
    """每条泳道配的地址（provider 名 → base_url）。没配的不出现。"""
    try:
        from core.multi_llm_router import _LOCAL_OPENAI_LANES  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — 问不出泳道就当没配
        logger.debug("泳道表不可用: %s", exc)
        return {}
    out: Dict[str, str] = {}
    for lane in _LOCAL_OPENAI_LANES:
        raw = os.environ.get(f"{lane['env_prefix']}_URL", "").strip()
        if not raw:
            continue
        if not raw.startswith(("http://", "https://")):
            raw = f"http://{raw}"
        out[lane["provider"]] = raw.rstrip("/")
    return out


def _declared_tag(provider: str) -> str:
    try:
        from core.multi_llm_router import _LOCAL_OPENAI_LANES  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return ""
    for lane in _LOCAL_OPENAI_LANES:
        if lane["provider"] == provider:
            return os.environ.get(f"{lane['env_prefix']}_SERVES", "").strip()
    return ""


def _normalize_model_id(name: str) -> str:
    """把两套命名惯例归到同一个形状 —— 只抹分隔符与大小写，**不做任何截断或前缀匹配**。

    ``Qwen3.6-35B-A3B``(FreeToken 报的 basename) 与 ``qwen3.6:35b-a3b``(目录 tag)
    归一化后都是 ``qwen3.635ba3b``。而 C 档那两个候选归一化后是
    ``qwen3.635ba3b`` 与 ``agentsa135ba3b`` —— **不同**，这正是这条判据必须保住的
    性质:两个同尺寸同架构的候选不许被认混。
    """
    out = []
    for ch in (name or "").strip().lower():
        if ch in "-_: ":
            continue
        out.append(ch)
    return "".join(out)


def facts_for_tag(tag: str, *, use_cache: bool = True) -> Optional[ServedEngineFacts]:
    """这个型号**正由哪台引擎伺候**、那台此刻能装多长；没有就返回 ``None``。

    认领判据两条，顺序有讲究：

    1. 用户在那条泳道上**显式声明**过 ``{前缀}_SERVES`` —— 只有起服务的人知道自己
       装的是什么，这里不猜；
    2. 引擎自报的 id 与这个 tag **归一化后逐字相同**。引擎按自己那套命名报
       （FreeToken 取 ``--model`` 路径的 basename:``Qwen3.6-35B-A3B``;OpenVINO 报
       ``MiniCPM-o-4_5-int4-ov``），与目录 tag 差的只是分隔符惯例，抹掉
       ``-`` ``_`` ``:`` 再比大小写不敏感 —— 这不是猜，是同一个字符串换了写法。

    **故意不做家族兜底（按根名松匹配）。** 目录里 ``get_model`` 有那条兜底,对"由哪个
    后端加载"是对的;对容量是错的,与 ``exact_model`` 存在的理由完全一样 ——
    ``qwen3.6:27b`` 与 ``qwen3.6:35b-a3b`` 根名相同,松匹配会拿一台服务的 KV 容量去
    定另一个型号的上下文。

    都不满足就不认领 —— **认错比认不出更糟**:认不出只是退回静态推算,认错则会拿另
    一台服务的容量去定这一位的上下文,而那个数**看起来是量出来的**,没有人会去怀疑它。
    """
    tag = (tag or "").strip()
    if not tag:
        return None
    want = _normalize_model_id(tag)
    for provider, url in _lane_urls().items():
        facts = probe(url, use_cache=use_cache)
        if facts is None:
            continue
        declared = _declared_tag(provider)
        if declared and declared == tag:
            return facts
        if facts.model_id and _normalize_model_id(facts.model_id) == want:
            return facts
    return None


def clear_cache() -> None:
    """丢掉缓存 —— 换档、重建 cache pool 之后该叫一次。"""
    _cache.clear()
