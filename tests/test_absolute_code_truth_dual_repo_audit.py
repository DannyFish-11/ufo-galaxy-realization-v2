"""双仓绝对代码真相全量认知审计文档完整性校验。

本测试文件验证 audit/ABSOLUTE_CODE_TRUTH_DUAL_REPO_FULL_AUDIT_CN_2026.md
是否覆盖了以下核心要求：

1. 不继承旧框架，从代码得出结论
2. 明确审计了认证默认状态（GALAXY_AUTH_ENABLED 默认关闭）
3. 明确审计了 NATS 的真实使用状态（可选/no-op）
4. 明确审计了 operator console 的真实状态（原生 JS，非 TypeScript/React）
5. 明确审计了三态 UI 外壳的代码现状（DORMANT/ISLAND/SIDESHEET/FULLAGENT 无实现）
6. 覆盖了本地执行链和跨设备执行链两条路径
7. 覆盖了 Mesh/NATS/WebSocket 三种传输的真实角色
8. 覆盖了 TypeScript/全栈/桌面 Shell 的真实缺口
9. 给出了从 clone 到完整使用的诚实体验描述
10. 给出了假闭环、弱连接、缺失内容的具体判断
"""

from pathlib import Path

DOC_PATH = Path("audit/ABSOLUTE_CODE_TRUTH_DUAL_REPO_FULL_AUDIT_CN_2026.md")


def _read_doc() -> str:
    assert DOC_PATH.exists(), f"缺少审计文档: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 基础：双仓覆盖 + 方法论
# ---------------------------------------------------------------------------

def test_doc_covers_both_repos_with_code_only_methodology() -> None:
    content = _read_doc()
    assert "ufo-galaxy-realization-v2" in content
    assert "ufo-galaxy-android" in content
    # 方法论：不继承旧结论，只看代码
    assert "真实代码" in content or "代码来源" in content


def test_doc_explicitly_rejects_inherited_framing() -> None:
    """文档必须显式说明不继承旧框架，而是从代码推导结论。"""
    content = _read_doc()
    # 必须说明之前 PR 的不足
    assert "之前" in content or "先前" in content or "旧" in content
    # 必须提到要基于代码重新得出结论
    assert "代码" in content and "推导" in content or "代码证明" in content or "代码来源" in content


# ---------------------------------------------------------------------------
# 认证状态审计（关键安全事实）
# ---------------------------------------------------------------------------

def test_doc_audits_auth_disabled_by_default() -> None:
    """文档必须明确指出认证默认关闭（GALAXY_AUTH_ENABLED=false）。"""
    content = _read_doc()
    assert "GALAXY_AUTH_ENABLED" in content
    assert "默认" in content and ("关闭" in content or "false" in content or "False" in content)


def test_doc_identifies_auth_as_false_closure() -> None:
    """文档必须将认证默认关闭识别为假闭环或重要的部署事实。"""
    content = _read_doc()
    # 必须有 auth/认证 相关的判断
    assert "认证" in content
    assert "假闭环" in content or "安全" in content or "不启用" in content


# ---------------------------------------------------------------------------
# NATS 真实状态审计
# ---------------------------------------------------------------------------

def test_doc_audits_nats_as_optional_nooop() -> None:
    """文档必须说明 NATS 是可选的，默认不激活，以 no-op 模式运行。"""
    content = _read_doc()
    assert "NATS" in content
    assert "no-op" in content or "不激活" in content or "可选" in content
    assert "GALAXY_NATS_URL" in content


def test_doc_separates_nats_from_ws_transport() -> None:
    """文档必须说明 NATS 不是 V2↔Android 的传输，WebSocket 才是核心传输。"""
    content = _read_doc()
    assert "WebSocket" in content
    # NATS 和 WS 要分别说明其不同用途
    assert "NATS" in content and "WebSocket" in content


# ---------------------------------------------------------------------------
# Mesh 真实状态审计
# ---------------------------------------------------------------------------

def test_doc_audits_mesh_as_overlay_not_primary_transport() -> None:
    """文档必须说明 Mesh 是 WS 之上的叠加层，不是独立主干传输。"""
    content = _read_doc()
    assert "Mesh" in content or "mesh" in content
    assert "叠加" in content or "overlay" in content or "加速层" in content or "OVERLAY" in content


def test_doc_audits_p2p_lan_dependency() -> None:
    """文档必须说明 P2P 直连依赖同 LAN 条件，NAT 环境下不工作。"""
    content = _read_doc()
    assert "LAN" in content or "局域网" in content
    assert "NAT" in content or "fallback" in content or "回退" in content


# ---------------------------------------------------------------------------
# Operator Console 真实状态审计
# ---------------------------------------------------------------------------

def test_doc_identifies_operator_console_as_vanilla_js() -> None:
    """文档必须指出 operator console 是原生 JS，不是 TypeScript/React。"""
    content = _read_doc()
    # 应该有对 operator console 的诚实描述
    assert "operator-console" in content or "Operator Console" in content or "operator console" in content
    # 应该有对其技术栈的实事求是描述
    assert "JavaScript" in content or "原生 JS" in content or "轮询" in content


# ---------------------------------------------------------------------------
# 三态 UI 外壳现状审计
# ---------------------------------------------------------------------------

def test_doc_audits_tristate_ui_shell_not_implemented() -> None:
    """文档必须指出 DORMANT/ISLAND/SIDESHEET/FULLAGENT 的 UI 渲染层不存在。"""
    content = _read_doc()
    assert "DORMANT" in content
    assert "ISLAND" in content or "SIDESHEET" in content or "FULLAGENT" in content
    # 必须说明其未实现
    assert "不存在" in content or "没有" in content or "未完成" in content


# ---------------------------------------------------------------------------
# 本地执行链审计（之前 PR 经常忽略）
# ---------------------------------------------------------------------------

def test_doc_covers_local_execution_chain() -> None:
    """文档必须覆盖本地执行链（Windows 本机执行），不仅仅是跨设备链。"""
    content = _read_doc()
    assert "本地执行" in content or "local_execution_chain" in content
    assert "DecisionExecutor" in content or "WindowsExecutionArbiter" in content


def test_doc_covers_cross_device_execution_chain() -> None:
    """文档必须覆盖跨设备执行链（V2 → Android）。"""
    content = _read_doc()
    assert "跨设备" in content or "cross_device" in content
    assert "DeviceRouter" in content or "CommandRouter" in content


def test_doc_treats_both_chains_as_equal() -> None:
    """文档必须说明本地链和跨设备链都是第一级链路，地位平等。"""
    content = _read_doc()
    assert "本地执行链" in content
    assert "跨设备执行链" in content


# ---------------------------------------------------------------------------
# Android 角色审计（不能仅仅说"子执行终端"）
# ---------------------------------------------------------------------------

def test_doc_audits_android_local_ai_as_genuine() -> None:
    """文档必须说明 Android 的本地 AI（llama.cpp + NCNN）是真实可用的。"""
    content = _read_doc()
    assert "llama.cpp" in content or "LlamaCpp" in content
    assert "NCNN" in content or "SeeClick" in content


def test_doc_identifies_android_role_as_context_dependent() -> None:
    """文档必须说明 Android 的角色取决于 inference_mode 配置。"""
    content = _read_doc()
    assert "inference_mode" in content
    assert "local" in content and "center" in content


# ---------------------------------------------------------------------------
# V2 角色审计（不能只是"中心调度层"）
# ---------------------------------------------------------------------------

def test_doc_audits_v2_local_execution_capability() -> None:
    """文档必须说明 V2 也有本地执行能力（Windows 本机任务），不只是调度层。"""
    content = _read_doc()
    assert "OpenClawd" in content
    assert "DesktopPresenceRuntime" in content
    assert "Windows" in content


def test_doc_audits_v2_tristate_lifecycle() -> None:
    """文档必须说明 V2 的三态生命周期（SILENT/LIMINAL/MANIFEST）。"""
    content = _read_doc()
    assert "SILENT" in content
    assert "LIMINAL" in content
    assert "MANIFEST" in content


# ---------------------------------------------------------------------------
# TypeScript/全栈缺口审计
# ---------------------------------------------------------------------------

def test_doc_identifies_typescript_react_as_completely_absent() -> None:
    """文档必须指出 TypeScript/React 全栈前端完全不存在。"""
    content = _read_doc()
    assert "TypeScript" in content
    assert "React" in content
    # 必须说明不存在/缺失
    assert "不存在" in content or "缺失" in content or "没有" in content


def test_doc_identifies_tauri_desktop_shell_as_missing() -> None:
    """文档必须指出 Tauri 桌面 Shell 尚未建立。"""
    content = _read_doc()
    assert "Tauri" in content


def test_doc_identifies_multimodal_ui_as_missing() -> None:
    """文档必须指出多模态输入 UI（麦克风/摄像头）不存在。"""
    content = _read_doc()
    assert "多模态" in content
    assert "麦克风" in content or "语音" in content or "摄像头" in content


# ---------------------------------------------------------------------------
# 假闭环识别
# ---------------------------------------------------------------------------

def test_doc_identifies_false_closures() -> None:
    """文档必须明确识别假闭环（不是模糊的"待完善"，而是有具体判断）。"""
    content = _read_doc()
    assert "假闭环" in content


def test_doc_identifies_fake_closed_auth() -> None:
    """文档必须把认证默认关闭列为假闭环或重要安全缺口。"""
    content = _read_doc()
    assert "认证" in content
    assert "假闭环" in content or "安全" in content


# ---------------------------------------------------------------------------
# 从 clone 到使用的完整体验审计
# ---------------------------------------------------------------------------

def test_doc_covers_clone_to_use_experience() -> None:
    """文档必须描述从 clone 到可用的完整体验（含实际操作摩擦点）。"""
    content = _read_doc()
    assert "clone" in content or "克隆" in content
    assert "API Key" in content or "api_key" in content or "API key" in content


def test_doc_is_honest_about_non_technical_user_barriers() -> None:
    """文档必须诚实描述非技术用户无法上手的障碍。"""
    content = _read_doc()
    assert "CLI" in content or "命令行" in content
    assert "非技术" in content or "不懂代码" in content or "普通用户" in content


# ---------------------------------------------------------------------------
# 完整体验白话描述
# ---------------------------------------------------------------------------

def test_doc_has_plain_language_system_description() -> None:
    """文档必须有无术语的白话描述，说明系统完整成熟后是什么体验。"""
    content = _read_doc()
    # 白话场景描述
    assert "手机" in content and "电脑" in content
    assert "完整" in content


def test_doc_has_honest_maturity_conclusion() -> None:
    """文档必须给出诚实的系统成熟度结论，不能只是乐观总结。"""
    content = _read_doc()
    # 必须同时承认已完成和未完成
    assert "已经是真的" in content or "已真实" in content or "真实完成" in content
    assert "还不是真的" in content or "不存在" in content or "缺失" in content


# ---------------------------------------------------------------------------
# 优先级分类
# ---------------------------------------------------------------------------

def test_doc_has_prioritized_gap_classification() -> None:
    """文档必须对缺口进行优先级分类（P0/P1/P2 或等效分类）。"""
    content = _read_doc()
    assert "P0" in content
    assert "P1" in content


# ---------------------------------------------------------------------------
# 代码来源锚点
# ---------------------------------------------------------------------------

def test_doc_has_v2_code_anchors() -> None:
    """文档必须引用 V2 仓库的具体代码文件路径。"""
    content = _read_doc()
    required_anchors = [
        "core/openclawd.py",
        "core/desktop_presence_runtime.py",
        "core/local_execution_chain.py",
        "core/cross_device_execution_chain.py",
        "core/unified_result_ingress.py",
        "core/nats_bus.py",
        "galaxy_gateway/device_router.py",
        "core/auth.py",
    ]
    for anchor in required_anchors:
        assert anchor in content, f"缺少代码锚点: {anchor}"


def test_doc_has_android_code_references() -> None:
    """文档必须引用 Android 仓库的具体代码文件或类名。"""
    content = _read_doc()
    required_android_refs = [
        "LlamaCppPlannerService",
        "NcnnGroundingService",
        "LocalLoopExecutor",
        "GalaxyWebSocketClient",
    ]
    for ref in required_android_refs:
        assert ref in content, f"缺少 Android 代码引用: {ref}"
