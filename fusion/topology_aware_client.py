"""
UFO Galaxy Fusion - Topology-Aware Constellation Client

拓扑感知的 ConstellationClient

扩展微软的 ConstellationClient，添加:
1. 拓扑管理
2. 拓扑路由
3. 负载均衡
4. 智能任务分配

作者: Manus AI
日期: 2026-01-25
"""

import logging
import sys
from typing import Dict, List, Optional, Any
from pathlib import Path

# 添加微软 UFO 到 Python 路径
MICROSOFT_UFO_PATH = Path(__file__).parent.parent / "microsoft-ufo"
if str(MICROSOFT_UFO_PATH) not in sys.path:
    sys.path.insert(0, str(MICROSOFT_UFO_PATH))

try:
    from galaxy.client.constellation_client import ConstellationClient
    from galaxy.client.config_loader import ConstellationConfig
    CONSTELLATION_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️  ConstellationClient not available: {e}")
    CONSTELLATION_AVAILABLE = False
    # 创建模拟类
    class ConstellationClient:
        def __init__(self, config=None, task_name=None): pass
        async def initialize(self): pass
    class ConstellationConfig: pass

# 导入拓扑管理器
from .topology_manager import TopologyManager, RoutingStrategy

logger = logging.getLogger(__name__)


class TopologyAwareConstellationClient(ConstellationClient if CONSTELLATION_AVAILABLE else object):
    """
    拓扑感知的 ConstellationClient
    
    扩展微软的 ConstellationClient，添加三层球体拓扑支持
    
    新增功能:
    - 基于拓扑的智能任务分配
    - 多种路由策略 (负载均衡、最短路径、域亲和、层级优先)
    - 负载监控和自动均衡
    - 拓扑可视化和统计
    
    使用示例:
    ```python
    client = TopologyAwareConstellationClient(
        config=constellation_config,
        task_name="my_task",
        topology_config_path="/path/to/topology.json",
        enable_topology=True
    )
    
    await client.initialize()
    
    # 基于拓扑分配任务
    target_node = await client.assign_task_with_topology(
        task={"description": "分析图片"},
        domain="vision",
        layer="perception",
        strategy=RoutingStrategy.LOAD_BALANCED
    )
    ```
    """
    
    def __init__(
        self,
        config: Optional['ConstellationConfig'] = None,
        task_name: Optional[str] = None,
        topology_config_path: Optional[str] = None,
        enable_topology: bool = True,
        default_routing_strategy: RoutingStrategy = RoutingStrategy.LOAD_BALANCED
    ):
        """
        初始化拓扑感知客户端
        
        Args:
            config: Constellation 配置
            task_name: 任务名称
            topology_config_path: 拓扑配置文件路径
            enable_topology: 是否启用拓扑功能
            default_routing_strategy: 默认路由策略
        """
        # 调用父类初始化 (如果可用)
        if CONSTELLATION_AVAILABLE:
            super().__init__(config, task_name)
        
        self.enable_topology = enable_topology
        self.topology_manager: Optional[TopologyManager] = None
        self.default_routing_strategy = default_routing_strategy
        
        # 任务历史 (用于统计和优化)
        self.task_history: List[Dict[str, Any]] = []
        
        # 如果启用拓扑，加载拓扑管理器
        if enable_topology and topology_config_path:
            logger.info("🌐 Initializing TopologyManager...")
            try:
                self.topology_manager = TopologyManager(topology_config_path)
                logger.info("✅ TopologyManager initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize TopologyManager: {e}")
                self.enable_topology = False
        else:
            logger.warning("⚠️  Topology not enabled or config path not provided")
    
    async def initialize(self) -> Dict[str, bool]:
        """
        初始化客户端
        
        Returns:
            初始化结果字典
        """
        # 调用父类初始化 (如果可用)
        if CONSTELLATION_AVAILABLE:
            result = await super().initialize()
        else:
            result = {}
        
        # 打印拓扑统计
        if self.topology_manager:
            stats = self.topology_manager.get_topology_stats()
            logger.info(f"📊 Topology stats: {stats}")
        
        return result
    
    async def assign_task_with_topology(
        self,
        task: Dict[str, Any],
        domain: Optional[str] = None,
        layer: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        source_node: Optional[str] = None,
        strategy: Optional[RoutingStrategy] = None,
        exclude_nodes: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        基于拓扑分配任务
        
        这是核心方法，使用拓扑管理器选择最佳节点
        
        Args:
            task: 任务描述字典
            domain: 目标域 (如果未指定，从任务推断)
            layer: 目标层级 (如果未指定，从任务推断)
            capabilities: 所需能力列表
            source_node: 源节点 (用于路径优化)
            strategy: 路由策略 (如果未指定，使用默认策略)
            exclude_nodes: 排除的节点列表
        
        Returns:
            目标节点 ID，如果没有找到则返回 None
        """
        if not self.enable_topology or not self.topology_manager:
            # 回退到标准分配
            logger.warning("⚠️  Topology not enabled, using standard assignment")
            return await self._standard_assign(task)
        
        # 1. 从任务中提取域和层级 (如果未指定)
        if not domain:
            domain = task.get('domain') or self._infer_domain(task)
        
        if not layer:
            layer = task.get('layer') or self._infer_layer(task)
        
        if not capabilities:
            capabilities = task.get('required_capabilities', [])
        
        # 2. 使用默认策略 (如果未指定)
        if strategy is None:
            strategy = self.default_routing_strategy
        
        logger.info(
            f"🔍 Finding best node: domain={domain}, layer={layer}, "
            f"strategy={strategy.value}"
        )
        
        # 3. 使用拓扑管理器查找最佳节点
        target_node = self.topology_manager.find_best_node(
            domain=domain,
            layer=layer,
            capabilities=capabilities,
            source_node=source_node,
            strategy=strategy,
            exclude_nodes=exclude_nodes
        )
        
        if not target_node:
            logger.error(f"❌ No suitable node found for task: {task}")
            return None
        
        # 4. 记录任务历史
        self._record_task(task, target_node, domain, layer, strategy)
        
        logger.info(
            f"✅ Task assigned to node: {target_node} "
            f"(domain={domain}, layer={layer}, strategy={strategy.value})"
        )
        
        # 5. 发送任务到目标节点 (如果 ConstellationClient 可用)
        if CONSTELLATION_AVAILABLE:
            return await self._send_task_to_node(target_node, task)
        else:
            return target_node
    
    def _infer_domain(self, task: Dict[str, Any]) -> str:
        """
        从任务描述推断域
        
        使用简单的关键词匹配
        
        Args:
            task: 任务描述
        
        Returns:
            推断的域
        """
        description = task.get('description', '').lower()
        
        # 关键词映射
        domain_keywords = {
            'vision': ['image', 'vision', 'visual', 'see', 'camera', 'ocr', 'picture', 'photo'],
            'nlu': ['text', 'language', 'understand', 'nlu', 'nlp', 'chat', 'conversation'],
            'state_management': ['state', 'manage', 'track', 'lock', 'sync'],
            'task_management': ['task', 'schedule', 'orchestrate', 'coordinate'],
            'security': ['auth', 'security', 'encrypt', 'decrypt', 'permission'],
            'storage': ['store', 'save', 'database', 'file', 'persist'],
            'network': ['fetch', 'download', 'upload', 'http', 'api'],
            'media': ['audio', 'video', 'media', 'sound', 'music'],
            'knowledge': ['knowledge', 'memory', 'learn', 'remember'],
            'search': ['search', 'find', 'query', 'lookup'],
            'device_control': ['control', 'device', 'adb', 'scrcpy', 'automation'],
            'monitoring': ['monitor', 'log', 'telemetry', 'health', 'status']
        }
        
        # 匹配关键词
        for domain, keywords in domain_keywords.items():
            if any(kw in description for kw in keywords):
                logger.debug(f"🔍 Inferred domain: {domain} (from description)")
                return domain
        
        # 默认域
        logger.debug("🔍 Using default domain: general")
        return 'general'
    
    def _infer_layer(self, task: Dict[str, Any]) -> str:
        """
        从任务描述推断层级
        
        使用简单的关键词匹配
        
        Args:
            task: 任务描述
        
        Returns:
            推断的层级
        """
        description = task.get('description', '').lower()
        
        # 关键词映射
        layer_keywords = {
            'core': ['coordinate', 'manage', 'control', 'orchestrate', 'global'],
            'cognitive': ['analyze', 'understand', 'process', 'think', 'reason'],
            'perception': ['perceive', 'detect', 'capture', 'sense', 'observe']
        }
        
        # 匹配关键词
        for layer, keywords in layer_keywords.items():
            if any(kw in description for kw in keywords):
                logger.debug(f"🔍 Inferred layer: {layer} (from description)")
                return layer
        
        # 默认层级 (从感知层开始)
        logger.debug("🔍 Using default layer: perception")
        return 'perception'
    
    async def _standard_assign(self, task: Dict[str, Any]) -> Optional[str]:
        """
        标准任务分配 (回退方案)
        
        当拓扑不可用时使用
        
        Args:
            task: 任务描述
        
        Returns:
            目标节点 ID
        """
        if not CONSTELLATION_AVAILABLE:
            logger.warning("⚠️  ConstellationClient not available")
            return None
        
        # 使用父类的设备管理器
        devices = self.device_manager.device_registry.get_all_devices()
        
        if not devices:
            logger.error("❌ No devices available")
            return None
        
        # 简单选择第一个空闲设备
        for device_id, device in devices.items():
            if hasattr(device, 'status') and device.status == "IDLE":
                logger.info(f"✅ Selected idle device: {device_id}")
                return device_id
        
        # 如果没有空闲设备，选择第一个
        first_device = list(devices.keys())[0]
        logger.info(f"✅ Selected first available device: {first_device}")
        return first_device
    
    async def _send_task_to_node(self, node_id: str, task: Dict[str, Any]) -> str:
        """
        发送任务到指定节点
        
        Args:
            node_id: 节点 ID
            task: 任务描述
        
        Returns:
            节点 ID
        """
        logger.info(f"📤 Sending task to node {node_id}: {task.get('description', 'N/A')}")
        
        # TODO: 实现实际的任务发送逻辑
        # 这里需要使用 device_manager 发送任务
        # 具体实现取决于微软 UFO 的 API
        
        return node_id
    
    def _record_task(
        self,
        task: Dict[str, Any],
        target_node: str,
        domain: str,
        layer: str,
        strategy: RoutingStrategy
    ):
        """
        记录任务历史
        
        用于统计和优化
        
        Args:
            task: 任务描述
            target_node: 目标节点
            domain: 域
            layer: 层级
            strategy: 路由策略
        """
        import time
        
        record = {
            "timestamp": time.time(),
            "task_description": task.get('description', 'N/A'),
            "target_node": target_node,
            "domain": domain,
            "layer": layer,
            "strategy": strategy.value
        }
        
        self.task_history.append(record)
        
        # 限制历史记录大小
        if len(self.task_history) > 1000:
            self.task_history = self.task_history[-1000:]
    
    def get_topology_stats(self) -> Optional[Dict[str, Any]]:
        """
        获取拓扑统计信息
        
        Returns:
            统计信息字典，如果拓扑不可用则返回 None
        """
        if self.topology_manager:
            return self.topology_manager.get_topology_stats()
        return None
    
    def get_task_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取任务历史
        
        Args:
            limit: 返回的最大记录数
        
        Returns:
            任务历史列表
        """
        return self.task_history[-limit:]
    
    def update_node_load(self, node_id: str, load: float):
        """
        更新节点负载
        
        Args:
            node_id: 节点 ID
            load: 负载值 (0.0 - 1.0)
        """
        if self.topology_manager:
            self.topology_manager.update_load(node_id, load)
    
    def get_node_info(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        获取节点信息
        
        Args:
            node_id: 节点 ID
        
        Returns:
            节点信息字典
        """
        if self.topology_manager:
            node_info = self.topology_manager.get_node_info(node_id)
            if node_info:
                return node_info.to_dict()
        return None
    
    def get_layer_nodes(self, layer: str) -> List[str]:
        """
        获取指定层级的所有节点
        
        Args:
            layer: 层级 ("core", "cognitive", "perception")
        
        Returns:
            节点 ID 列表
        """
        if self.topology_manager:
            return self.topology_manager.get_layer_nodes(layer)
        return []
    
    def get_domain_nodes(self, domain: str) -> List[str]:
        """
        获取指定域的所有节点
        
        Args:
            domain: 域名称
        
        Returns:
            节点 ID 列表
        """
        if self.topology_manager:
            return self.topology_manager.get_domain_nodes(domain)
        return []
    
    def visualize_topology(self, output_path: str):
        """
        可视化拓扑
        
        Args:
            output_path: 输出图片路径
        """
        if self.topology_manager:
            self.topology_manager.visualize_topology(output_path)
        else:
            logger.warning("⚠️  Topology manager not available")
    
    def export_topology(self, output_path: str):
        """
        导出拓扑配置
        
        Args:
            output_path: 输出文件路径
        """
        if self.topology_manager:
            self.topology_manager.export_topology(output_path)
        else:
            logger.warning("⚠️  Topology manager not available")
    
    def __repr__(self) -> str:
        return (
            f"<TopologyAwareConstellationClient "
            f"topology_enabled={self.enable_topology} "
            f"nodes={len(self.topology_manager.nodes) if self.topology_manager else 0}>"
        )
