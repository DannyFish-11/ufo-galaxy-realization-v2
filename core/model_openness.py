"""开放权重 / 闭源权重 —— 按【模型】判定,而不是按 provider 猜。

为什么需要这个模块
------------------
路由器原先只有 provider 粒度的两个集合(``OPEN_SOURCE_PROVIDERS`` /
``PROPRIETARY_PROVIDERS``)。这个粒度表达不了现实:**同一家可以同时供开放权重和闭源
模型**。所有者原话:「它开源和闭源的都有,按照它那个模型区分开来就行了。」

meta 就是被这个粒度卡住的例子。它在 ``PROVIDER_REGISTRY`` 里服务的是
``Llama-4-Maverick-*`` / ``Llama-4-Scout-*`` —— 开放权重;而 ``groq`` 进开源集合的
理由写的正是「托管 Llama 等开源模型」。按同一标准 meta 该算开源。但
``TASK_ROUTING_PREFERENCES`` 的注释又说 meta「定位在专有兜底梯队」。仓库自己两处
说法矛盾,根因就是拿 provider 当分类单位 —— 一家只能被塞进一个格子。

原先那处真不一致
----------------
``meta`` 和 ``openrouter`` **两个集合都没登记**,而两处消费点对"未登记"的处理正好相反:

* ``reorder_open_source_first()``:明文注释「未知提供商按开源处理」→ 被提到专有之前;
* ``select_brain_for_task()`` 的 ``_score()`` 里 ``if name in OPEN_SOURCE_PROVIDERS:
  score += 0.15`` → 拿不到加分,等于当成非开源。

同一个 provider 排序时算开源、打分时算非开源。

判定顺序与保守边界
------------------
``is_open_weight()`` 只对**有把握**的模型族给答案,拿不准一律返回 ``None``。调用方
在 ``None`` 时**回落到既有的 provider 级集合**。这条纪律是刻意的:

本模块的目的是给"未登记"的那几个补上按模型的判定,**不是**去重新裁决那些已经明确
登记过的 provider。举例:``agnes`` 现在在 ``OPEN_SOURCE_PROVIDERS`` 里,理由写的是
「全模态免费 API,开放/免费档友好」—— 那是"免费",未必是"开放权重"。这里若擅自把
``agnes-*`` 判成闭源,就会静默改掉一个别人明确写过的决定。所以 ``agnes-*`` 不在下面
任何一张表里 → 返回 ``None`` → 沿用既有登记。

纯函数、不读环境变量、不碰网络,可完整单测。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

#: 开放权重模型族。判据:权重可公开下载/自托管(哪怕本次是经某家的托管 API 调用)。
#:
#: 这里写"族"而不是逐个型号:型号会不断出新(``deepseek-v4-pro`` → ``v5``…),
#: 逐个列必然漏,漏了就静默回落成"未知"。按族前缀匹配才跟得上。
_OPEN_WEIGHT_PATTERNS: tuple = (
    r"^llama[-_.]?\d",  # Llama-4-Maverick / llama-3.3-70b(Meta 自家 API 与 Groq 托管同族)
    r"^deepseek",  # DeepSeek V3/R1/V4 系,权重公开
    r"^qwen",  # 通义千问,权重公开
    r"^glm[-_.]?\d",  # 智谱 GLM,权重公开
    r"^kimi",  # Kimi-K2 起权重公开(注意:moonshot-v1-* 是闭源,见下)
    r"^mistral",  # Mistral 开放权重系
    r"^mixtral",
    r"^minimax[-_.]",  # MiniMax-M 系,权重公开
    r"^gemma",  # 本地主脑(Gemma 4),权重公开
    r"^minicpm",  # MiniCPM-o 全模态,权重公开
    r"^step[-_.]?\d",  # 阶跃 Step 系
    r"^mimo",  # 小米 MiMo,权重公开
)

#: 闭源权重模型族。判据:只能经该家 API 调用,权重不公开。
_CLOSED_WEIGHT_PATTERNS: tuple = (
    r"^gpt[-_.]?\d",  # OpenAI GPT
    r"^o\d",  # OpenAI o 系推理模型
    r"^claude",  # Anthropic
    r"^gemini",  # Google
    r"^grok",  # xAI
    r"^sonar",  # Perplexity Sonar
    r"^moonshot[-_.]v",  # moonshot-v1-* 是闭源(与开放权重的 kimi-k2 同厂不同权重状态)
)

_OPEN_RE = tuple(re.compile(p, re.I) for p in _OPEN_WEIGHT_PATTERNS)
_CLOSED_RE = tuple(re.compile(p, re.I) for p in _CLOSED_WEIGHT_PATTERNS)

#: provider 级判定的三种结果 + 未知。
OPENNESS_OPEN = "open"
OPENNESS_CLOSED = "closed"
OPENNESS_MIXED = "mixed"
OPENNESS_UNKNOWN = "unknown"


def _strip_namespace(model: str) -> str:
    """去掉聚合器加的命名空间前缀。

    OneAPI / OpenRouter 这类聚合器把上游型号写成 ``meta-llama/llama-3.3-70b`` 或
    ``deepseek/deepseek-chat``。只看整串会全部落到"未知",而它其实就是同一个模型 ——
    取最后一段再判。
    """
    return model.rsplit("/", 1)[-1].strip()


def is_open_weight(model: str) -> Optional[bool]:
    """这个模型是开放权重吗?

    Returns:
        ``True`` 开放权重;``False`` 闭源权重;``None`` **拿不准**。

    ``None`` 不是"否" —— 调用方必须把它当"本模块无法判定",回落到既有的 provider 级
    登记,而不是当成闭源处理。把未知当否会静默改掉别人明确写过的分类(见模块 docstring
    里 ``agnes`` 那个例子)。
    """
    if not model or not isinstance(model, str):
        return None
    name = _strip_namespace(model)
    if not name:
        return None
    # 闭源先判:``moonshot-v1-*``(闭源)与 ``kimi-*``(开放)同厂,若开放族先匹配到
    # 更宽的模式就会误判。目前两族前缀不重叠,但把闭源放前面可以让将来新增更宽的
    # 开放模式时不至于悄悄吃掉闭源型号。
    for rx in _CLOSED_RE:
        if rx.search(name):
            return False
    for rx in _OPEN_RE:
        if rx.search(name):
            return True
    return None


def provider_openness(models: List[str]) -> str:
    """一家 provider 服务的这批模型整体是什么成分。

    Returns:
        ``"open"`` 全部(可判定的)是开放权重;``"closed"`` 全部是闭源;
        ``"mixed"`` 两者都有 —— 这正是 provider 粒度表达不了、所以需要按模型判的情形;
        ``"unknown"`` 一个都判不出来。
    """
    verdicts = [is_open_weight(m) for m in (models or [])]
    known = [v for v in verdicts if v is not None]
    if not known:
        return OPENNESS_UNKNOWN
    if all(known):
        return OPENNESS_OPEN
    if not any(known):
        return OPENNESS_CLOSED
    return OPENNESS_MIXED


def treat_as_open_source(
    provider: str,
    model: str,
    *,
    open_source_providers: frozenset,
    proprietary_providers: frozenset,
) -> bool:
    """路由/打分时该不该把这一手当"开源"。

    这是给 ``multi_llm_router`` 的两处消费点用的**唯一**判定入口 —— 让它们对同一个
    (provider, model) 得出同一个答案,而不是像原先那样排序算开源、打分算非开源。

    判定顺序:

    1. **模型级**(``is_open_weight``)优先 —— 所有者要的就是"按模型区分";
    2. 模型判不出来 → **provider 级既有登记**;
    3. 两级都没有 → ``True``。

    第 3 条与 ``reorder_open_source_first()`` 原有的成文约定一致(「未知提供商按开源
    处理(更符合本仓库以开源自托管/聚合为主的现状)」)。把这个约定明确搬过来,是为了
    让打分那一处也遵守同一条 —— 原先那处对未知是不给加分的,两处因此矛盾。
    """
    verdict = is_open_weight(model)
    if verdict is not None:
        return verdict
    if provider in open_source_providers:
        return True
    if provider in proprietary_providers:
        return False
    return True


def audit_registry(registry_models: Dict[str, List[str]]) -> Dict[str, Dict[str, object]]:
    """诊断用:把每家的模型成分摊开,便于看清哪家是 mixed、哪些型号判不出来。

    给面板/诊断和测试用。不参与路由决策。
    """
    out: Dict[str, Dict[str, object]] = {}
    for provider, models in sorted((registry_models or {}).items()):
        per_model = {m: is_open_weight(m) for m in (models or [])}
        out[provider] = {
            "openness": provider_openness(list(models or [])),
            "models": per_model,
            "undecidable": sorted(m for m, v in per_model.items() if v is None),
        }
    return out
