#!/usr/bin/env python3
"""
生成完整的拓扑配置文件

基于现有的 102 个节点，生成包含三层球体拓扑的配置文件
"""

import json
import math
from pathlib import Path

# 节点列表（从实际目录读取）
NODES = [
    "Node_00_StateMachine", "Node_01_OneAPI", "Node_02_Tasker", "Node_03_SecretVault",
    "Node_04_Router", "Node_05_Auth", "Node_06_Filesystem", "Node_07_Git",
    "Node_08_Fetch", "Node_09_Sandbox", "Node_10_Slack", "Node_11_GitHub",
    "Node_12_Postgres", "Node_13_SQLite", "Node_14_FFmpeg", "Node_15_OCR",
    "Node_16_Email", "Node_17_EdgeTTS", "Node_18_DeepL", "Node_19_Crypto",
    "Node_20_Qdrant", "Node_21_Notion", "Node_22_BraveSearch", "Node_23_Calendar",
    "Node_23_Time", "Node_24_Weather", "Node_25_GoogleSearch", "Node_28_Reserved",
    "Node_29_Reserved", "Node_30_Reserved", "Node_31_Reserved", "Node_32_Reserved",
    "Node_33_ADB", "Node_34_Scrcpy", "Node_35_AppleScript", "Node_36_UIAWindows",
    "Node_37_LinuxDBus", "Node_38_BLE", "Node_39_SSH", "Node_40_SFTP",
    "Node_41_MQTT", "Node_42_CANbus", "Node_43_MAVLink", "Node_44_NFC",
    "Node_45_DesktopAuto", "Node_46_Camera", "Node_47_Audio", "Node_48_MediaGen",
    "Node_48_Serial", "Node_49_OctoPrint", "Node_50_Transformer", "Node_51_QuantumDispatcher",
    "Node_52_QiskitSimulator", "Node_53_GraphLogic", "Node_54_SymbolicMath", "Node_56_AgentSwarm",
    "Node_56_Planning", "Node_57_QuantumCloud", "Node_58_ModelRouter", "Node_59_CausalInference",
    "Node_61_GeometricReasoning", "Node_62_ProbabilisticProgramming", "Node_64_Telemetry", "Node_65_LoggerCentral",
    "Node_66_ConfigManager", "Node_67_HealthMonitor", "Node_68_Security", "Node_69_BackupRestore",
    "Node_70_BambuLab", "Node_71_MediaGen", "Node_72_KnowledgeBase", "Node_73_Learning",
    "Node_74_DigitalTwin", "Node_79_LocalLLM", "Node_80_MemorySystem", "Node_81_Orchestrator",
    "Node_82_NetworkGuard", "Node_83_NewsAggregator", "Node_84_StockTracker", "Node_85_PromptLibrary",
    "Node_90_MultimodalVision", "Node_91_MultimodalAgent", "Node_92_AutoControl", "Node_95_WebRTC_Receiver",
    "Node_96_SmartTransportRouter", "Node_97_AcademicSearch", "Node_100_MemorySystem", "Node_101_CodeEngine",
    "Node_102_DebugOptimize", "Node_103_KnowledgeGraph", "Node_104_AgentCPM", "Node_105_UnifiedKnowledgeBase",
    "Node_106_GitHubFlow", "Node_108_MetaCognition", "Node_109_ProactiveSensing", "Node_110_SmartOrchestrator",
    "Node_111_ContextManager", "Node_112_SelfHealing", "Node_113_AndroidVLM", "Node_116_ExternalToolWrapper",
    "Node_117_OpenCode", "Node_118_NodeFactory"
]

# 层级分配规则（基于节点 ID 和功能）
def assign_layer(node_name):
    """分配层级"""
    node_id = int(node_name.split('_')[1])
    
    # Core Layer (0-15): 核心系统管理
    if node_id <= 15:
        return "core"
    # Cognitive Layer (16-61): 智能处理和分析
    elif node_id <= 61:
        return "cognitive"
    # Perception Layer (62+): 感知和数据采集
    else:
        return "perception"

# 域分配规则
def assign_domain(node_name):
    """分配域"""
    name_lower = node_name.lower()
    
    # 状态管理
    if any(kw in name_lower for kw in ['state', 'config', 'manager']):
        return "state_management"
    # 视觉
    elif any(kw in name_lower for kw in ['vision', 'camera', 'ocr', 'image', 'vlm']):
        return "vision"
    # NLU/语言
    elif any(kw in name_lower for kw in ['nlu', 'llm', 'language', 'text', 'tts']):
        return "nlu"
    # 任务管理
    elif any(kw in name_lower for kw in ['task', 'orchestrat', 'router', 'dispatch']):
        return "task_management"
    # 安全
    elif any(kw in name_lower for kw in ['auth', 'security', 'crypto', 'vault']):
        return "security"
    # 存储
    elif any(kw in name_lower for kw in ['filesystem', 'postgres', 'sqlite', 'storage', 'backup']):
        return "storage"
    # 网络
    elif any(kw in name_lower for kw in ['fetch', 'ssh', 'sftp', 'mqtt', 'network']):
        return "network"
    # 沙箱
    elif any(kw in name_lower for kw in ['sandbox', 'docker']):
        return "sandbox"
    # 设备控制
    elif any(kw in name_lower for kw in ['adb', 'scrcpy', 'applescript', 'uia', 'dbus', 'ble', 'serial']):
        return "device_control"
    # 媒体
    elif any(kw in name_lower for kw in ['media', 'ffmpeg', 'audio', 'video']):
        return "media"
    # 知识
    elif any(kw in name_lower for kw in ['knowledge', 'memory', 'learning', 'qdrant']):
        return "knowledge"
    # 监控
    elif any(kw in name_lower for kw in ['telemetry', 'logger', 'health', 'monitor']):
        return "monitoring"
    # 搜索
    elif any(kw in name_lower for kw in ['search', 'brave', 'google', 'academic']):
        return "search"
    # 通知
    elif any(kw in name_lower for kw in ['slack', 'email', 'notification']):
        return "notification"
    # 默认
    else:
        return "general"

# 能力分配
def assign_capabilities(node_name):
    """分配能力"""
    name_lower = node_name.lower()
    caps = []
    
    if 'state' in name_lower:
        caps.extend(['state_management', 'lock_management'])
    if 'vision' in name_lower or 'camera' in name_lower or 'ocr' in name_lower:
        caps.extend(['vision', 'image_processing'])
    if 'llm' in name_lower or 'nlu' in name_lower:
        caps.extend(['nlu', 'text_processing'])
    if 'router' in name_lower or 'orchestrat' in name_lower:
        caps.extend(['routing', 'orchestration'])
    if 'auth' in name_lower or 'security' in name_lower:
        caps.extend(['authentication', 'security'])
    if 'storage' in name_lower or 'database' in name_lower:
        caps.extend(['storage', 'persistence'])
    if 'network' in name_lower or 'fetch' in name_lower:
        caps.extend(['network', 'http'])
    if 'media' in name_lower or 'audio' in name_lower or 'video' in name_lower:
        caps.extend(['media_processing'])
    if 'knowledge' in name_lower or 'memory' in name_lower:
        caps.extend(['knowledge_management', 'memory'])
    if 'search' in name_lower:
        caps.extend(['search', 'information_retrieval'])
    
    return caps if caps else ['general']

# 生成球面坐标
def generate_coordinates(index, total, layer):
    """生成球面坐标"""
    # 层级半径
    layer_radius = {
        "core": 1.0,
        "cognitive": 2.0,
        "perception": 3.0
    }
    
    radius = layer_radius[layer]
    
    # 使用黄金螺旋分布节点
    golden_angle = math.pi * (3 - math.sqrt(5))  # 约 137.5 度
    
    theta = math.acos(1 - 2 * (index + 0.5) / total)  # 极角
    phi = (index * golden_angle) % (2 * math.pi)      # 方位角
    
    return {
        "theta": round(theta, 4),
        "phi": round(phi, 4),
        "radius": radius
    }

# 生成邻居关系（基于层级和域）
def generate_neighbors(node_id, all_nodes, layer, domain):
    """生成邻居节点"""
    neighbors = []
    
    # 同层同域节点
    same_layer_domain = [
        n['id'] for n in all_nodes
        if n['layer'] == layer and n['domain'] == domain and n['id'] != node_id
    ]
    
    # 选择最多 3 个同层同域邻居
    neighbors.extend(same_layer_domain[:3])
    
    # 上层节点（如果不是核心层）
    if layer == "cognitive":
        core_nodes = [n['id'] for n in all_nodes if n['layer'] == "core"]
        neighbors.extend(core_nodes[:2])
    elif layer == "perception":
        cognitive_nodes = [n['id'] for n in all_nodes if n['layer'] == "cognitive"]
        neighbors.extend(cognitive_nodes[:2])
    
    return neighbors

# 生成拓扑配置
def generate_topology():
    """生成完整拓扑配置"""
    
    # 分层统计
    layers_count = {"core": 0, "cognitive": 0, "perception": 0}
    
    # 第一遍：生成基础节点信息
    nodes = []
    for idx, node_name in enumerate(NODES):
        node_id = node_name.split('_')[0] + "_" + node_name.split('_')[1]
        node_display_name = "_".join(node_name.split('_')[2:]) if len(node_name.split('_')) > 2 else node_name
        
        layer = assign_layer(node_name)
        layers_count[layer] += 1
        
        domain = assign_domain(node_name)
        capabilities = assign_capabilities(node_name)
        
        # 生成坐标
        layer_index = {"core": 0, "cognitive": 1, "perception": 2}[layer]
        coords = generate_coordinates(idx, len(NODES), layer)
        
        # 端口分配（基于节点 ID）
        base_port = 8000 + int(node_name.split('_')[1])
        
        node = {
            "id": node_id,
            "name": node_display_name,
            "layer": layer,
            "domain": domain,
            "coordinates": coords,
            "capabilities": capabilities,
            "api_url": f"http://localhost:{base_port}",
            "neighbors": [],  # 第二遍填充
            "metadata": {
                "priority": "critical" if layer == "core" else "high" if layer == "cognitive" else "normal",
                "max_load": 100 if layer == "core" else 200 if layer == "cognitive" else 300
            }
        }
        
        nodes.append(node)
    
    # 第二遍：生成邻居关系
    for node in nodes:
        node['neighbors'] = generate_neighbors(
            node['id'],
            nodes,
            node['layer'],
            node['domain']
        )
    
    # 生成完整配置
    config = {
        "version": "1.0",
        "topology_type": "three_layer_sphere",
        "description": "UFO Galaxy - 102 Nodes Three-Layer Sphere Topology",
        "generated_at": "2026-01-25",
        "layers": [
            {
                "name": "core",
                "index": 0,
                "radius": 1.0,
                "node_count": layers_count["core"],
                "description": "核心层 - 系统管理和协调"
            },
            {
                "name": "cognitive",
                "index": 1,
                "radius": 2.0,
                "node_count": layers_count["cognitive"],
                "description": "认知层 - 智能处理和分析"
            },
            {
                "name": "perception",
                "index": 2,
                "radius": 3.0,
                "node_count": layers_count["perception"],
                "description": "感知层 - 数据采集和感知"
            }
        ],
        "domains": list(set(n['domain'] for n in nodes)),
        "nodes": nodes
    }
    
    return config

# 主函数
if __name__ == "__main__":
    print("🔧 Generating topology configuration...")
    
    config = generate_topology()
    
    output_path = Path(__file__).parent.parent / "config" / "topology.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Topology configuration generated: {output_path}")
    print(f"   - Total nodes: {len(config['nodes'])}")
    print(f"   - Layers: {[(l['name'], l['node_count']) for l in config['layers']]}")
    print(f"   - Domains: {len(config['domains'])} domains")
