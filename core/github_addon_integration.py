"""core/github_addon_integration.py —— 一个 GitHub 仓库以什么身份接进来

从 ``core/github_installer.py`` 拆出来的一件独立的事:**判定接入形态**。和"怎么把代码
拿下来""依赖装到哪"都无关 —— 它只回答一个问题:这个仓库接进来之后,到底算什么。

拆的直接原因也很实在:加上三档形态的判定与说明之后,那个文件从 1642 涨到 1699,越过了
``scripts/check_file_complexity.py`` 的基线,而那道门给的两条出路是拆分或抬基线 ——
这个仓前两次(``voice_duplex_session.py``、``addon_dependency_isolation.py``)选的都是拆。

## 三档是并列的,不是"成功 / 降级"两档

===========  ====================================================================
``mcp``      根上有 ``mcp_tool.json`` —— 注册成了一个 MCP 工具
``skill``    根上有 ``skill.json`` 或 ``SKILL.md`` —— 注册成了一个 Skill
``project``  哪个契约都没有 —— 以**项目完整形式**接进来:代码落盘,没注册成任何工具
===========  ====================================================================

**MCP / Skill 是 GitHub 项目的交集,不是它的定义。** 接一个仓库可能是为了拿它跑实验、
读它、拿它当素材;"它没变成一个 MCP 工具"不是一次失败,而是另一种接法。

改之前不是这样:``install_success`` 对所有类型一律看 ``registration && verification``,
而普通仓库那条路的 ``registration`` 被写死成 ``success: False`` + 一句 error。结果是
**接一个普通项目永远返回 success=False + HTTP 400** —— 在面板上只能显示成一次失败,
而它明明成功了。这一层把那个判定改对,并且把结论写成一个字段,而不是让每个消费者
拿两个嵌套布尔去反推。

## 为什么结论要落成一个字段

``integration`` 会同时写进安装响应**和 manifest 记录**。写进 manifest 是必须的:
``/api/v1/github/list`` 发的是 manifest 记录,不写进去的话,重启之后面板就只能靠
``registration`` / ``verification`` 反推形态 —— 那就成了第二处权威,判定规则改一次,
界面说的和实际发生的就分家。

``skill_md`` 归到 ``skill``:它是 Skill 的一种写法,不是第三种形态。具体是哪种写法
留在 ``variant`` 里,排障时要用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "MCP_TOOL_MANIFEST",
    "SKILL_MANIFEST",
    "SKILL_MD_MANIFEST",
    "INTEGRABLE_TYPES",
    "detect_addon_type",
    "integration_form",
    "build_integration",
    "cloned_only_results",
]

#: 仓库根上的三种集成契约。谁都没有 → 以项目完整形式接入。
MCP_TOOL_MANIFEST = "mcp_tool.json"
SKILL_MANIFEST = "skill.json"
SKILL_MD_MANIFEST = "SKILL.md"

#: **声称**自己是一个可调用工具的那几种类型。只有声称了,才有"注册成没成"这个问题。
INTEGRABLE_TYPES = frozenset({"mcp", "skill", "skill_md"})

#: 类型 → 形态。不在表里的一律是 ``project``,包括将来新增而这里还没跟上的类型 ——
#: 认不出的东西归到"就是个项目"是安全的方向:它只是少说了一句话,不会多说一句假话。
_FORM_BY_TYPE = {"mcp": "mcp", "skill": "skill", "skill_md": "skill"}


def detect_addon_type(dest: Path, forced_type: Optional[str] = None) -> str:
    """看一眼仓库根,判定它是哪一种。

    ``forced_type`` 是调用方强制指定(排障用),优先于自动判定 —— 但注意它只改
    **判定结果**,不会凭空造出契约文件:强制成 ``mcp`` 而根上没有 ``mcp_tool.json``,
    后面读 manifest 那一步会拿到空字典,注册随之失败。这是有意的:让它在能说清
    "缺什么"的地方失败,而不是在这里就拒绝。
    """
    if forced_type in ("mcp", "skill", "skill_md"):
        return forced_type
    if forced_type is None:
        if (dest / MCP_TOOL_MANIFEST).exists():
            return "mcp"
        if (dest / SKILL_MANIFEST).exists():
            return "skill"
        if (dest / SKILL_MD_MANIFEST).exists():
            return "skill_md"
    return "ordinary_tool_repo"


def present_contracts(dest: Path) -> Dict[str, bool]:
    """根上到底摆着哪几份契约。

    ``detect_addon_type`` 只回答"选中了哪一种"(按 mcp → skill → SKILL.md 的顺序,
    第一个命中就停)。但面板要把**三个槽位**都摆出来,那就得知道另外两份在不在 ——
    一个仓库完全可能同时带着 ``mcp_tool.json`` 和 ``skill.json``,而只有前者被选中。

    不报这一份的话,三个槽位就只能按 ``detected_type`` 点亮一个、另外两个一律画成
    "没有" —— 那是在**替仓库说一句它没说过的话**。
    """
    return {
        "mcp": (dest / MCP_TOOL_MANIFEST).exists(),
        "skill": (dest / SKILL_MANIFEST).exists(),
        "skill_md": (dest / SKILL_MD_MANIFEST).exists(),
    }


def integration_form(detected_type: str) -> str:
    """``mcp`` / ``skill`` / ``project`` —— 面板要区分的那三档。"""
    return _FORM_BY_TYPE.get(detected_type, "project")


def build_integration(
    detected_type: str,
    reg_result: Dict[str, Any],
    verify_result: Dict[str, Any],
    contracts: Optional[Dict[str, bool]] = None,
) -> Tuple[Dict[str, Any], bool, str]:
    """算出 ``(integration, install_success, install_state)``。

    ``install_state`` **不由 install_success 推**:推的话 ``project`` 这一档会变成
    ``"verified"``,而它根本没有可自证的对象。三种状态各说各的事:

    ===================================  ==========================================
    ``verified``                         有契约,注册并自证都过了
    ``registration_or_verification_failed``  有契约,但卡在注册或自证
    ``cloned_only``                      没有契约 —— 这不是失败,是另一种接法
    ===================================  ==========================================
    """
    integrated = detected_type in INTEGRABLE_TYPES
    install_success = (bool(reg_result.get("success")) and bool(verify_result.get("success"))) if integrated else True

    if not integrated:
        # 没有契约:``detail`` 说的是"它以什么形式接进来了",不是一句错误。
        detail = str(reg_result.get("message") or "")
    elif install_success:
        detail = ""
    else:
        detail = str(reg_result.get("error") or verify_result.get("error") or "注册或自证没通过")

    integration = {
        "form": integration_form(detected_type),
        "ok": install_success,
        "variant": detected_type,
        "detail": detail,
        # 三个槽位各自的实情。``chosen`` 说的是"这一份被选中并走了注册那条路",
        # ``present`` 说的是"根上摆着这份文件" —— 两者不是一回事。
        "contracts": {
            key: {
                "present": bool((contracts or {}).get(key)),
                "chosen": detected_type == key,
            }
            for key in ("mcp", "skill", "skill_md")
        },
    }
    install_state = (
        "cloned_only" if not integrated else ("verified" if install_success else "registration_or_verification_failed")
    )
    return integration, install_success, install_state


def cloned_only_results() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """没有契约那条路的 ``(registration, verification)``。

    两份都**不带 error**,带的是 ``message``。接一个 GitHub 项目本身就是一件完整的事 ——
    它可能是拿来跑实验的、拿来读的、拿来当素材的。把"它没变成 MCP 工具"写成一个错误,
    等于规定了"接项目 = 接工具",而那不是这个功能的全集。
    """
    return (
        {
            "success": False,
            "registered": False,
            "state": "cloned_only",
            "message": (
                f"仓库根上没有 {MCP_TOOL_MANIFEST} / {SKILL_MANIFEST} / {SKILL_MD_MANIFEST} —— "
                "它以项目完整形式接进来:代码已落盘,但没有注册成任何可调用的工具。"
            ),
        },
        {
            "success": False,
            "checks": {"integrable_type_detected": False},
            "message": "没有集成契约,因此没有可自证的对象 —— 这不是一次失败。",
        },
    )
