"""core/github_addon_admission.py —— 装一个 GitHub addon 之前,要不要先问人

## 这一层回答的问题

``github__install`` 是 **LLM 直接可调**的工具:说一句"把 https://github.com/x/y 装上",
它就会 clone、检测类型、注册、**在当前会话立刻生效**。方便正是它的价值,
也正是它的风险 —— 装进来的是第三方代码。

改之前的默认状态:``GITHUB_ALLOWLIST`` 为空 = 全放行,没有任何人确认。

## 分级:名单内免确认,名单外问人

这是和使用者定下的形状(候选里的 C)。理由:

* 全都要确认 → 常用仓库每次都要切到面板点一下,**一个让人想绕过的门禁等于没有门禁**
  (这句在 ``/script`` 那轮的提交里写过,同一个道理);
* 全都不确认 → 就是现在这个样子。

## 和现有 allowlist/blocklist 的关系:**只收紧,不放宽**

``validate_repo_url()`` 里那套判定一个字都没改:

=========================  ==================  ==================
情况                       改之前               改之后
=========================  ==================  ==================
blocklist 命中             拒                   拒(不变)
allowlist 非空且命中        放行                 放行,**免确认**
allowlist 非空但不命中      **拒**               **拒**(不变)
allowlist 为空             全放行,无确认         **要问人**
=========================  ==================  ==================

最后一行是唯一的变化,方向是收紧。**"名单外"没有从"拒绝"放宽成"问人"** ——
那会把一道硬闸换成一道可以点"同意"绕过的软闸,是净损失。

## 问不到人 = 拒绝

和 ``Node_122_Shell._human_approved`` 同一个取舍,也同一套机制
(``core.interaction.pending_decision_registry`` 是仓里唯一的 HITL 入口,不另造)。
无头部署要放开,得显式设 ``GALAXY_ADDON_UNATTENDED=1`` —— 那等于声明
"这台机器上没有人把关",应当写进部署文档。

**拒绝要快。** 没有设备在线时 ``request_human_decision`` 会把超时等满(实测 60 秒),
而结论从第一秒起就已经确定。无头环境每次装插件卡一分钟,会被当成坏了,
然后有人去把这道闸关掉 —— 这个坑 ``/script`` 那轮踩过,这里先查设备再问。
"""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass
from typing import List

logger = logging.getLogger("Galaxy.AddonAdmission")

__all__ = ["AdmissionVerdict", "admit_addon_install", "evaluate_addon_admission"]

#: 显式声明"这台机器上没有人把关"。**只能开,不能默认**。
ENV_UNATTENDED = "GALAXY_ADDON_UNATTENDED"


@dataclass(frozen=True)
class AdmissionVerdict:
    """要不要装、要不要先问人,以及**凭哪条规则**。

    ``rule`` 不是装饰:"为什么这次问了我而上次没问"是用户一定会问的问题,
    答不上来的门禁会被当成随机行为,然后被关掉。
    """

    allowed: bool
    needs_human: bool
    reason: str = ""
    rule: str = ""


def evaluate_addon_admission(owner: str, repo: str, *, allowlist: List[str], blocklist: List[str]) -> AdmissionVerdict:
    """纯判定,不碰网络也不问人 —— 可以完整单测。"""
    slug = f"{owner}/{repo}"

    if blocklist and _matches(slug, blocklist):
        return AdmissionVerdict(False, False, f"{slug} 在 GITHUB_BLOCKLIST 里", "blocklist")

    if allowlist:
        if _matches(slug, allowlist):
            return AdmissionVerdict(True, False, f"{slug} 在 GITHUB_ALLOWLIST 里,免确认", "allowlist")
        # 不放宽:名单非空而不命中,仍然是**拒绝**,不是"问一下人"。
        return AdmissionVerdict(False, False, f"{slug} 不在 GITHUB_ALLOWLIST 里", "not_allowlisted")

    return AdmissionVerdict(True, True, f"GITHUB_ALLOWLIST 为空,{slug} 需要人确认", "unlisted")


def _matches(slug: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatch(slug, pat) for pat in patterns)


def _unattended() -> bool:
    return os.getenv(ENV_UNATTENDED, "").strip().lower() in ("1", "true", "yes", "on")


async def admit_addon_install(owner: str, repo: str, ref: str) -> AdmissionVerdict:
    """判定 + 需要时真的去问人。返回的 ``allowed`` 就是最终结论。"""
    from core.github_installer import _get_allowlist, _get_blocklist

    verdict = evaluate_addon_admission(owner, repo, allowlist=_get_allowlist(), blocklist=_get_blocklist())
    if not verdict.allowed or not verdict.needs_human:
        return verdict

    if _unattended():
        logger.warning("%s 已设:跳过 addon 安装的人确认 —— 这台机器上没有人把关", ENV_UNATTENDED)
        return AdmissionVerdict(True, False, f"{ENV_UNATTENDED}=1,跳过确认", "unattended")

    approved = await _ask_human(owner, repo, ref)
    if approved:
        return AdmissionVerdict(True, True, "人确认通过", "human_approved")
    return AdmissionVerdict(False, True, "人确认未通过(或超时/无人可问)", "human_denied")


async def _ask_human(owner: str, repo: str, ref: str) -> bool:
    """问人。**问不到人就是拒绝。**"""
    try:
        from core.interaction.pending_decision_registry import (
            OnTimeout,
            _discover_target_devices,
            request_human_decision,
        )
    except Exception as exc:  # noqa: BLE001 — 问不到人就是拒绝
        logger.warning("人确认通道不可用,拒绝安装 %s/%s: %s", owner, repo, exc)
        return False

    # 先看有没有人可问 —— 见模块 docstring"拒绝要快"那段。
    try:
        targets = await _discover_target_devices()
    except Exception as exc:  # noqa: BLE001
        logger.warning("查不到可问的设备,拒绝安装 %s/%s: %s", owner, repo, exc)
        return False
    if not targets:
        logger.warning(
            "没有可问的设备,拒绝安装 %s/%s(无头环境可设 %s=1)",
            owner,
            repo,
            ENV_UNATTENDED,
        )
        return False

    try:
        outcome = await request_human_decision(
            title=f"安装 GitHub 插件:{owner}/{repo}",
            summary=(
                f"来源 https://github.com/{owner}/{repo}(ref={ref or 'default'})。\n"
                "这会把第三方代码装进来,并在当前会话立刻生效。\n"
                "常用的仓库可以加进 GITHUB_ALLOWLIST,以后就不再问。"
            ),
            options=[{"id": "approve", "label": "安装"}, {"id": "deny", "label": "拒绝"}],
            default_option="deny",
            urgency="high",
            on_timeout=OnTimeout.CANCEL,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("人确认过程出错,拒绝安装 %s/%s: %s", owner, repo, exc)
        return False

    return getattr(outcome, "selected_option", None) == "approve"
