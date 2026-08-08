#!/usr/bin/env python3
"""生成完整的拓扑配置文件（三层球体拓扑）

节点清单**从磁盘扫描得出**，不是写死的名单。

原来这里是一份手抄的 102 个名字，而它上面那行注释写的却是「从实际目录读取」——
注释说的是对的做法，代码没照做。代价有两笔：

1. 名单里有 5 个磁盘上不存在的节点（``Node_37_LinuxDBus`` / ``38_BLE`` /
   ``41_MQTT`` / ``42_CANbus`` / ``48_Serial``）。这五个协议后来是以
   ``core/adapters/*_adapter.py`` 的形式落在 AIP 传输层的（见
   ``galaxy_gateway/bootstrap/lifecycle.py`` 里逐个 ``register_adapter``），
   节点这条路线从来没走通。而 ``config/topology.json`` 会喂给
   ``TopologyManager`` 做负载均衡路由 —— 名单里留着它们，等于让路由器把
   请求派给一个不存在的目标。
2. 少了 23 个磁盘上真实存在的节点，它们在拓扑里根本不出现。

改成扫盘之后这两笔都不会再犯：新增节点自动进拓扑，删掉的节点自动消失。
"""

import json
import math
from pathlib import Path

from core.port_config import get_node_port

REPO_ROOT = Path(__file__).resolve().parent.parent
NODES_DIR = REPO_ROOT / "nodes"

#: 与 ``config/topology.json`` 一起写出去 —— 原来这条是人手加在产物里的，
#: 生成器并不知道它存在，所以重新生成一次就会把它抹掉。
DEPRECATION_NOTICE = (
    "LEGACY (2026-03-14): api_url fields in this file contain hardcoded ports "
    "that may be stale. Canonical port source: config/unified_ports.yaml. "
    "Topology/visualization metadata (layers, coordinates, domains) remains "
    "valid here but ports should be read at runtime via "
    "core.port_config.get_node_port()."
)


def discover_nodes() -> list:
    """扫描 ``nodes/`` 下真实存在的节点目录。

    判据是「有 ``main.py``」—— 与 ``core/node_activation_policy`` 和
    ``tests/test_node_manifest_consistency.py`` 用的是同一条，避免又多出一份
    「哪些算节点」的说法。

    按编号排序而不是按目录名字典序：``generate_coordinates()`` 用下标算球面坐标，
    顺序不稳定的话每次生成出来的坐标都不一样。
    """
    names = [d.name for d in NODES_DIR.iterdir() if d.is_dir() and (d / "main.py").exists()]

    def _key(name: str):
        parts = name.split("_")
        try:
            return (0, int(parts[1]), name)
        except (IndexError, ValueError):
            return (1, 0, name)

    return sorted(names, key=_key)


NODES = discover_nodes()


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
        
        # 端口分配（基于节点名称，通过 port_config 获取）
        try:
            base_port = get_node_port(node_name)
        except KeyError:
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
        # 这条原来是人手加在 config/topology.json 里的，生成器并不知道它存在 ——
        # 重新生成一次就会把它抹掉。放进生成器，它才跟着产物走。
        "_DEPRECATION_NOTICE": DEPRECATION_NOTICE,
        "version": "1.0",
        "topology_type": "three_layer_sphere",
        # 节点数跟着磁盘走，不再写死 —— 原来这里印的 "102 Nodes" 已经和现实差了 23 个。
        "description": f"Galaxy - {len(nodes)} Nodes Three-Layer Sphere Topology",
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
