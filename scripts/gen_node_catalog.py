#!/usr/bin/env python3
"""scripts/gen_node_catalog.py — 生成 config/node_catalog.json(节点分类目录)。

数据来自全量节点审计(125 个节点)。目录只放【静态分类】信息:类型、是否需要外部
账号/OAuth、是否占位、一行用途。端口/状态在运行时由 core.node_catalog 合并
config/unified_ports.yaml + NodeFabricRegistry 实时补齐,不写死在这里。

节点面板(设置→端口与节点)与 /api/v1/nodes/roster 都读这份目录。审计更新后重跑本
脚本即可。
"""

from __future__ import annotations

import json
import os

# 每行: (num, name, type, runnable, oauth_service_or_None, purpose)
# oauth: None=无需外部账号; "oauth:Xxx"=真 OAuth 连接器; "key:Xxx"=需 API Key;
#        "llm"=用系统级 LLM 凭据(不单独连接器)。
_ROWS = [
    (0, "StateMachine", "core-runtime", True, None, "中央全局状态机;所有状态同步汇聚于此"),
    (1, "OneAPI", "core-runtime", True, "key:Brave/OpenWeather/Pixverse", "统一 API 网关,聚合下游服务"),
    (2, "Tasker", "core-runtime", True, None, "任务调度/分发引擎"),
    (3, "SecretVault", "core-runtime", True, None, "密钥/凭据保险库"),
    (4, "Router", "core-runtime", True, None, "全局请求路由"),
    (5, "Auth", "core-runtime", True, "oauth:Auth", "鉴权/授权中心(OAuth2 流程)"),
    (6, "Filesystem", "tool-integration", True, None, "文件系统 MCP 访问服务"),
    (7, "Git", "tool-integration", True, None, "本地 Git 版本控制操作"),
    (8, "Fetch", "tool-integration", True, None, "通用 HTTP 抓取/请求服务"),
    (9, "Sandbox", "dev-code", True, None, "沙箱代码执行环境"),
    (10, "Slack", "tool-integration", True, "oauth:Slack", "Slack 集成"),
    (11, "GitHub", "tool-integration", True, "oauth:GitHub", "GitHub API 集成"),
    (12, "Postgres", "data", True, None, "PostgreSQL 数据库服务"),
    (13, "SQLite", "data", True, None, "SQLite 数据库服务"),
    (14, "FFmpeg", "media", True, None, "音视频处理(ffmpeg)"),
    (15, "OCR", "device-automation", True, None, "光学字符识别"),
    (16, "Email", "tool-integration", True, "oauth:Gmail", "邮件收发(SMTP/IMAP,Gmail)"),
    (17, "EdgeTTS", "media", True, None, "文本转语音(Edge TTS)"),
    (18, "DeepL", "tool-integration", True, "key:DeepL", "DeepL 翻译"),
    (19, "Crypto", "tool-integration", True, None, "加解密工具"),
    (20, "Qdrant", "memory-knowledge", True, None, "Qdrant 向量数据库服务"),
    (21, "Notion", "tool-integration", True, "oauth:Notion", "Notion 集成"),
    (22, "BraveSearch", "tool-integration", True, "key:Brave", "Brave 网页搜索"),
    (23, "Time", "tool-integration", True, None, "时间/时区服务"),
    (24, "Weather", "tool-integration", True, "key:OpenWeather", "天气服务"),
    (25, "GoogleSearch", "tool-integration", True, "key:GoogleCSE", "Google 可编程搜索"),
    (26, "Discord", "tool-integration", True, "oauth:Discord", "Discord 集成"),
    (27, "SmartHome", "device-automation", True, None, "智能家居设备控制"),
    (28, "PluginManager0", "infra-adapter", True, None, "插件管理节点"),
    (29, "ExtensionRegistry", "infra-adapter", True, None, "扩展注册节点"),
    (30, "Reserved30", "infra-adapter", False, None, "占位:插件框架 stub"),
    (31, "Reserved31", "infra-adapter", False, None, "占位:插件框架 stub"),
    (32, "Reserved32", "infra-adapter", False, None, "占位:插件框架 stub"),
    (33, "ADB", "device-automation", True, None, "Android Debug Bridge 控制"),
    (34, "Scrcpy", "device-automation", True, None, "Android 投屏/控制"),
    (35, "AppleScript", "device-automation", True, None, "macOS AppleScript 自动化"),
    (36, "UIAWindows", "device-automation", True, None, "Windows UI 自动化"),
    (39, "SSH", "infra-adapter", True, None, "SSH 远程执行"),
    (40, "SFTP", "infra-adapter", True, None, "SFTP 文件传输"),
    (43, "MAVLink", "infra-adapter", True, None, "无人机/MAVLink 协议通信"),
    (44, "NFC", "infra-adapter", True, None, "NFC 近场通信"),
    (45, "DesktopAuto", "device-automation", True, None, "桌面 GUI 自动化"),
    (46, "Camera", "device-automation", True, None, "摄像头采集/控制"),
    (47, "Audio", "media", True, None, "音频采集/播放控制"),
    (49, "OctoPrint", "infra-adapter", True, None, "OctoPrint 3D 打印机控制"),
    (50, "Transformer", "ai-cognition", True, "llm", "Transformer 推理引擎"),
    (51, "QuantumDispatcher", "ai-cognition", True, None, "量子计算分发器"),
    (52, "QiskitSimulator", "ai-cognition", True, None, "Qiskit 量子模拟器"),
    (53, "GraphLogic", "ai-cognition", True, None, "基于图的逻辑推理"),
    (54, "SymbolicMath", "ai-cognition", True, None, "符号数学计算"),
    (55, "MultiModal", "ai-cognition", True, "key:HuggingFace", "多模态处理"),
    (56, "Planning", "ai-cognition", True, None, "规划引擎"),
    (57, "QuantumCloud", "ai-cognition", True, None, "量子云服务"),
    (58, "ModelRouter", "ai-cognition", True, "llm", "跨供应商 LLM 模型路由"),
    (59, "CausalInference", "ai-cognition", True, None, "因果推断"),
    (60, "ReinforcementLearn", "ai-cognition", True, None, "强化学习引擎"),
    (61, "GeometricReasoning", "ai-cognition", True, None, "几何推理"),
    (62, "ProbabilisticProg", "ai-cognition", True, None, "概率编程"),
    (63, "FuzzyLogicEngine", "ai-cognition", True, None, "模糊逻辑推理引擎"),
    (64, "Telemetry", "observability-ops", True, None, "遥测数据采集"),
    (65, "LoggerCentral", "observability-ops", True, None, "中央日志系统"),
    (66, "ConfigManager", "observability-ops", True, None, "配置管理器"),
    (67, "HealthMonitor", "observability-ops", True, None, "健康监控"),
    (68, "Security", "observability-ops", True, None, "安全监控"),
    (69, "BackupRestore", "observability-ops", True, None, "备份/恢复"),
    (70, "AutonomousLearning", "ai-cognition", True, None, "自主学习系统"),
    (71, "MultiDeviceCoord", "device-automation", True, None, "多设备协调"),
    (72, "KnowledgeBase", "memory-knowledge", True, None, "知识库系统"),
    (73, "Learning", "ai-cognition", True, None, "自学习系统"),
    (74, "DigitalTwin", "device-automation", True, None, "物理设备数字孪生"),
    (75, "DataPipeline", "data", True, None, "数据处理流水线"),
    (76, "AlertManager", "observability-ops", True, "key:SMTP", "告警管理器"),
    (77, "TaskScheduler", "core-runtime", True, None, "任务调度器"),
    (78, "DataValidator", "data", True, None, "数据校验服务"),
    (79, "LocalLLM", "ai-cognition", True, None, "本地 LLM 服务"),
    (80, "MemorySystem", "memory-knowledge", True, None, "记忆系统"),
    (81, "Orchestrator", "core-runtime", True, None, "任务编排器"),
    (82, "NetworkGuard", "observability-ops", True, None, "网络监控/防御"),
    (83, "NewsAggregator", "tool-integration", True, "key:NewsFeed", "新闻聚合"),
    (84, "StockTracker", "tool-integration", True, "key:MarketData", "股票追踪"),
    (85, "PromptLibrary", "memory-knowledge", True, None, "提示词库"),
    (86, "SpeechProcessor", "media", True, "llm", "语音处理(ASR/TTS)"),
    (87, "ImageAnalysis", "media", True, "llm", "图像分析"),
    (88, "WorkflowEngine", "core-runtime", True, None, "工作流引擎"),
    (89, "APIGateway", "core-runtime", True, None, "API 网关"),
    (90, "MultimodalVision", "media", True, None, "多模态视觉"),
    (91, "MultimodalAgent", "ai-cognition", True, None, "多模态 agent"),
    (92, "AutoControl", "device-automation", True, None, "Windows+Android 统一控制接口"),
    (93, "VideoProcessor", "media", True, "llm", "视频处理/分析"),
    (94, "AudioAnalysis", "media", True, "llm", "音频分析/转写"),
    (95, "WebRTC_Receiver", "media", True, None, "WebRTC 流接收"),
    (96, "SmartTransportRtr", "core-runtime", True, None, "智能传输路由"),
    (97, "AcademicSearch", "tool-integration", True, "key:SerpAPI", "学术论文搜索"),
    (98, "MultimodalFusion", "media", True, "llm", "多模态融合"),
    (99, "EmbeddingService", "memory-knowledge", True, "llm", "嵌入向量服务"),
    (100, "MemorySystemV2", "memory-knowledge", True, "llm", "记忆系统 v2"),
    (101, "CodeEngine", "dev-code", True, "llm", "代码生成引擎"),
    (102, "DebugOptimize", "dev-code", True, "llm", "调试/优化"),
    (103, "KnowledgeGraph", "memory-knowledge", True, "llm", "知识图谱"),
    (104, "AgentCPM", "ai-cognition", True, None, "AgentCPM 深搜/报告 agent"),
    (105, "UnifiedKnowledgeB", "memory-knowledge", True, "key:HuggingFace", "统一知识库"),
    (106, "GitHubFlow", "tool-integration", True, "oauth:GitHub", "GitHub 工作流自动化"),
    (107, "FunctionCalling", "ai-cognition", True, "llm", "函数调用分发器"),
    (108, "MetaCognition", "ai-cognition", True, "llm", "元认知系统"),
    (109, "ProactiveSensing", "ai-cognition", True, "key:Brave", "主动感知"),
    (110, "SmartOrchestrator", "core-runtime", True, None, "智能编排器"),
    (111, "ContextManager", "core-runtime", True, None, "上下文管理器"),
    (112, "SelfHealing", "ai-cognition", True, None, "自愈系统"),
    (113, "AndroidVLM", "device-automation", True, "llm", "Android 视觉语言模型控制"),
    (114, "DocumentIntellig", "data", True, "llm", "文档解析/理解"),
    (115, "PluginManager", "core-runtime", True, None, "插件管理器"),
    (116, "ExternalToolWrap", "tool-integration", True, "llm", "外部工具封装"),
    (117, "OpenCode", "dev-code", True, "llm", "多语言代码执行/沙箱"),
    (118, "NodeFactory", "core-runtime", True, "llm", "节点工厂(脚手架新节点)"),
    (119, "BenchmarkEval", "dev-code", True, "llm", "基准/评测系统"),
    (120, "FileOperations", "dev-code", True, None, "文件操作服务"),
    (121, "WebOperations", "tool-integration", True, None, "Web 操作/代理"),
    (122, "ShellExecutor", "dev-code", True, None, "Shell 命令执行器"),
    (123, "Calendar", "tool-integration", True, "oauth:Calendar", "日历服务"),
    (124, "LinuxDesktopAuto", "device-automation", True, None, "Linux 桌面自动化"),
    (125, "MediaGen", "media", True, "key:Pixverse", "媒体生成(图/音/视频)"),
    (126, "AgentSwarm", "ai-cognition", True, None, "agent 蜂群协调"),
    (127, "BambuLab", "infra-adapter", True, "key:BambuCloud", "BambuLab 3D 打印机控制"),
    (128, "MediaGenAsync", "media", True, "key:Pixverse", "媒体生成(异步任务,Pixverse)"),
    (130, "AutonomousCoding", "dev-code", True, "llm", "自主编码引擎(门面→core)"),
]

_TYPE_LABELS = {
    "core-runtime": "核心运行时",
    "tool-integration": "工具集成",
    "ai-cognition": "AI 认知",
    "media": "媒体",
    "device-automation": "设备自动化",
    "memory-knowledge": "记忆知识",
    "dev-code": "开发/代码",
    "observability-ops": "可观测/运维",
    "infra-adapter": "基础设施适配",
    "data": "数据",
}


# ── 声明式动作权限(Astrid manifest 门禁思路,借"魂"不借壳)────────────────────
# 每个敏感节点声明它【允许被调用的动作白名单】——派发时由
# core.node_action_permissions 在统一执行器里强制校验(fail-closed):声明了的
# 节点,动作不在白名单 → 拒绝执行,即使 prompt 注入也无法越权调用未声明动作。
#
# 白名单从各节点 main.py/fusion_entry.py 的【真实 dispatch 表】核实提取(不自欺:
# 只给核实过的节点声明;没核实的先不声明=legacy 放行+告警,GALAXY_PERM_STRICT=1
# 可收紧为未声明即拒绝)。支持 fnmatch 通配(如 "get_*")。
# 通用元动作(help/status/health)各节点普遍支持,统一并入。
_META_ACTIONS = ["help", "status", "health"]
_ACTION_PERMISSIONS: dict = {
    27: ["toggle", "off", "set_brightness", "set_temperature"],  # SmartHome
    33: [
        "tap",
        "swipe",
        "input",
        "keyevent",
        "screenshot",
        "shell",  # ADB
        "devices",
        "connected_devices",
        "current_device",
        "adb_path",
    ],
    34: [
        "tap",
        "swipe",
        "input_text",
        "key_event",
        "press_back",  # Scrcpy
        "press_home",
        "screenshot",
        "shell",
        "install",
        "devices",
        "device_info",
        "packages",
    ],
    36: [
        "click",
        "double_click",
        "right_click",
        "drag",
        "move_mouse",  # UIAWindows
        "type_text",
        "press_key",
        "hotkey",
        "scroll",
        "screenshot",
        "locate_on_screen",
        "get_mouse_position",
        "get_screen_size",
        "list_windows",
        "window_action",
        "focus",
        "close",
        "maximize",
        "minimize",
        "restore",
        "find_element",
        "find_elements",
        "get_ui_tree",
    ],
    45: [
        "click",
        "double_click",
        "move",
        "type",
        "press",
        "hotkey",  # DesktopAuto
        "scroll",
        "screenshot",
        "locate",
        "position",
        "screen_size",
    ],
    74: [
        "register_device",
        "get_twin",
        "get_status",
        "get_history",  # DigitalTwin
        "list_devices",
        "simulate",
        "cycle",
        "reset",
    ],
    92: ["click", "input", "press_key", "hotkey", "scroll"],  # AutoControl
    124: ["get", "set", "list", "move", "resize"],  # LinuxDesktopAuto
}


def build() -> dict:
    nodes = []
    for num, name, typ, runnable, oauth, purpose in _ROWS:
        entry = {
            "num": num,
            "name": name,
            "type": typ,
            "type_label": _TYPE_LABELS.get(typ, typ),
            "runnable": runnable,
            "purpose": purpose,
        }
        if oauth:
            kind, _, svc = oauth.partition(":")
            entry["connector"] = {"kind": kind, "service": svc or None}
        if num in _ACTION_PERMISSIONS:
            entry["permissions"] = {
                "actions": sorted(set(_ACTION_PERMISSIONS[num]) | set(_META_ACTIONS)),
            }
        nodes.append(entry)
    nodes.sort(key=lambda n: n["num"])
    return {
        "_comment": "由 scripts/gen_node_catalog.py 从全量节点审计生成;端口/状态运行时合并,勿手改。",
        "type_labels": _TYPE_LABELS,
        "count": len(nodes),
        "nodes": nodes,
    }


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "config", "node_catalog.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(build(), f, ensure_ascii=False, indent=2)
    print(f"wrote {out}: {build()['count']} nodes")
