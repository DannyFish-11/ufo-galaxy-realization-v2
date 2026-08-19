"""core/runtime_readiness.py — 这一档的每一位，**加载运行时装齐了没**
=====================================================================

只回答一个问题：按当前(或指定)档位，**每个在岗模型要的那个后端**装了没、
装了的那个**做不做得到目录声称的落位**。装齐 → 空表。

为什么要单独一个模块
====================
这段判据原本长在 ``core/routes/models.py`` 里，只有 HTTP 那两个端点在用。
可"缺依赖"这件事最该在**用户还没进面板的时候**说 —— 克隆完、选完档、启动时。
而启动路径(``core.model_selection`` / ``launcher``)不该、也不能去 import 一个
FastAPI 路由模块。

于是判据留在路由里 = 判据只服务一个消费方；再来一个消费方就只能各写一份，
然后在某个后端上分家。这里把它挪到中立位置：**路由和启动路径读的是同一份**。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("Galaxy.RuntimeReadiness")

#: 后端 → 装它的 pip 包名。报缺口时必须带上"怎么装"，否则用户拿到告警也不知道该干嘛。
BACKEND_PIP: Dict[str, str] = {
    "llama_cpp": "llama-cpp-python",
    "transformers": "transformers",
    "vllm": "vllm",
}


def slot_runtime_gaps(tier_key: str = "") -> List[Dict[str, Any]]:
    """这一档里，哪几位的**加载运行时**没装 —— 每位一条，装齐则空表。

    为什么必须报出来
    ================
    ``list_available_backends()`` 早就在答"哪个后端的依赖装了"，可换档/换人那条
    路从来没问过它。于是：选了带 llama_cpp 推理位的档 → 换档时那一位加载抛
    ``No module named 'llama_cpp'`` → 被 ``reconcile_tier`` 捕获、撤账、写一行
    WARNING 到日志里 → **面板上什么都看不到**。用户以为两个模型都跑起来了，
    实际只有一位在岗。

    ``llama-cpp-python`` 是**刻意**归档的可选依赖(GB 级、要编译、平台特定，
    见 requirements.txt 的可选依赖存档段)，不该改成硬依赖 —— 但"可选"的前提是
    缺了要**说**，而不是默默少跑一个模型。
    """
    try:
        from core.local_model_backends import (  # noqa: PLC0415
            list_available_backends,
            moe_offload_supported,
        )
        from core.model_catalog import (  # noqa: PLC0415
            active_tags,
            backend_for_tag,
            effective_weight_mb,
            get_model,
            load_tier,
            resolve_is_moe,
        )

        key = tier_key or load_tier()
        # 探测函数本身也可能在**调用时**抛(不只是 import 时)。只裹 import 的话，
        # 一次探测异常会把 /status、/tier 整个打挂 —— 而这一层的职责只是"报缺口"，
        # 报不出来就该安静退场，没有理由拖垮它服务的那个接口。
        ready = set(list_available_backends())
        return _collect_gaps(
            key,
            ready,
            moe_offload_supported,
            active_tags,
            backend_for_tag,
            get_model,
            resolve_is_moe,
            effective_weight_mb,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("运行时就绪度不可评估: %s", exc)
        return []


def _collect_gaps(
    key, ready, moe_offload_supported, active_tags, backend_for_tag, get_model, resolve_is_moe, effective_weight_mb
):
    """逐位比对"要哪个后端 / 装了没 / 做不做得到声称的落位"。"""
    gaps: List[Dict[str, Any]] = []
    for tag in active_tags(key):
        backend = backend_for_tag(tag)
        spec = get_model(tag)
        if backend not in ready:
            gaps.append(
                {
                    "kind": "backend_missing",
                    "tag": tag,
                    "backend": backend,
                    "pip": BACKEND_PIP.get(backend, backend),
                    "detail": (
                        f"加载 {tag} 要用 {backend} 后端,但它的依赖没装 —— 这一位不会上岗。"
                        f"装法: pip install {BACKEND_PIP.get(backend, backend)}"
                    ),
                    "source": getattr(spec, "source", ""),
                }
            )
            continue
        # 后端装了,还要看它**做不做得到目录声称的那种落位**。
        #
        # MoE 的 runtime_mb 是按"专家卸载生效"写的(35B:18 GB 权重 → 7.3 GB 驻留)。
        # 卸载做不到时那个数就是空头支票 —— 准入按 7.3 GB 放行,加载时按 18 GB 要
        # 显存,8 GB 卡上必炸。而告警只在加载时才喊,中间隔着一整次加载。
        # 整权重按 effective_weight_mb 取,不是 spec.size_mb():这句话说的是"卸载
        # 不生效时它会按整权重要多少显存",而权重文件已经在磁盘上时,目录那条
        # "按 Q4_K_M 记"的声明就不该再压过实际的文件。用户换成 Q8_0 时,这条
        # 缺口报的数会跟着变,而不是继续报一个量化对不上的旧数。
        weight_mb = effective_weight_mb(tag) if spec is not None else 0
        if (
            backend == "llama_cpp"
            and spec is not None
            and resolve_is_moe(tag)
            and spec.runtime_mb() < weight_mb
            and not moe_offload_supported()
        ):
            gaps.append(
                {
                    "kind": "moe_offload_unavailable",
                    "tag": tag,
                    "backend": backend,
                    "pip": "",
                    "detail": (
                        f"{tag} 的显存账({spec.runtime_mb()} MB)是按**专家卸载生效**算的,"
                        f"但这台机器上**两条路都做不到**:装着的 llama-cpp-python 既不支持 "
                        f"n_cpu_moe 也不支持 override_tensor,而 llama-server 也没找到 —— "
                        f"这一位会按整权重 {weight_mb} MB 要显存,小显存上必然装不下。"
                        f"解法:装一个 llama.cpp 的 llama-server(或用 GALAXY_LLAMA_SERVER_BIN "
                        f"指到你自己编的那份)。装上之后**不需要再配什么** —— 后端选择会自动改走它,"
                        f"服务由本进程起、地址自动导出。"
                    ),
                    "source": getattr(spec, "source", ""),
                    "declared_runtime_mb": spec.runtime_mb(),
                    "actual_runtime_mb": weight_mb,
                }
            )
    return gaps


def tier_is_runnable(tier_key: str) -> bool:
    """这一档**现在**跑得起来吗 —— 有任何一条缺口就不算。

    推荐档位时要用：推一个当前运行时根本落不了地的档，等于把失败推迟到加载时。
    """
    return not slot_runtime_gaps(tier_key)


def effective_tier(tier_key: str = "") -> str:
    """这台机器**现在**实际跑得起来的档：想要的那个跑得起来就是它，否则往下降。

    为什么光"喊"不够
    ================
    :func:`tier_is_runnable` 和 ``print_runtime_gaps`` 已经能在选档当场和每次启动
    时把缺口打到终端上。但**打完之后什么都没变**：存着 C 档的机器照样去加载 C 档，
    推理位照样抛 ``No module named 'llama_cpp'``，照样被
    ``reconcile_tier`` 捕获、撤账、写一行日志。用户看到的仍然是"少了一个模型"，
    只是这回上面还多了一行他看不懂的告警。

    探针有、降级路径没有，比两样都没有更糟：它给人"已经防住了"的错觉。

    降级只影响**运行时**，不回写记录
    ================================
    用户存的还是 C —— 那是他的意图，机器现在的状态是暂时的(装上缺的依赖、
    换回支持卸载的 ``llama-cpp-python``，重启就该自动回到 C)。把降档写回记录等于
    拿一次环境故障永久改掉用户的选择，而且他不会知道自己被改了。

    Args:
        tier_key: 想要的档；空则取当前存的(:func:`~core.model_catalog.load_tier`)。

    Returns:
        实际跑得起来的档位键。想要的那个本来就跑得起来 → 原样返回。全都跑不起来
        → 最低那一档(纯 CPU 保底，见 :func:`~core.model_catalog.tier_keys`)。
    """
    want = (tier_key or "").strip().upper()
    try:
        from core.model_catalog import load_tier, tier_keys  # noqa: PLC0415

        want = want or load_tier().strip().upper()
        keys = tier_keys()  # 由低到高
        if want not in keys:
            return want
        if tier_is_runnable(want):
            return want
        # 只往**下**找：降级是为了能跑起来，不是替用户改主意往上升。
        for key in reversed(keys[: keys.index(want)]):
            if tier_is_runnable(key):
                return key
        return keys[0]
    except Exception as exc:  # noqa: BLE001
        # 评估不了就**不降** —— 与 slot_runtime_gaps 同一个方向:判不了不代表跑不了，
        # 拿一次探测异常去改用户的档，比不改危险得多。
        logger.debug("有效档位不可评估(保持原档): %s", exc)
        return want


def format_gaps(gaps: List[Dict[str, Any]]) -> List[str]:
    """把缺口渲染成可直接打给用户看的几行(终端/日志共用一份措辞)。"""
    return [f"[{g.get('kind', '?')}] {g.get('tag', '?')}: {g.get('detail', '')}" for g in gaps]
