import json
import os
from .topology_aware_client import TopologyAwareConstellationClient
from .topology_manager import RoutingStrategy

def activate_topology_client(config_path: str = "config/topology.json"):
    """
    激活拓扑感知客户端，确保它能加载 102 节点拓扑。
    """
    if not os.path.exists(config_path):
        # 原先这里回退到 "config/default_topology.json"。仓里从来没有这个文件 ——
        # 回退分支只能让下面的实例化以另一个「文件不存在」二次失败，还把错误信息
        # 指向一个不存在的路径，比直接报原路径更难排查。仓内真实的拓扑配置只有
        # config/topology.json 一份，没有可回退的第二份，所以如实报错。
        raise FileNotFoundError(
            f"拓扑配置文件未找到: {config_path}（仓内没有可回退的默认拓扑配置）"
        )

    try:
        # 实例化 TopologyAwareConstellationClient
        client = TopologyAwareConstellationClient(
            topology_config_path=config_path,
            enable_topology=True,
            default_routing_strategy=RoutingStrategy.LOAD_BALANCED
        )
        print("✅ TopologyAwareConstellationClient 实例化成功。")
        return client
    except Exception as e:
        print(f"❌ 拓扑感知客户端激活失败: {e}")
        return None

# 3. 模拟一个启动脚本的片段，确保 ConstellationClient 被正确替换
# 检查 galaxy_launcher.py 中是否使用了 ConstellationClient
# 由于不能修改用户代码，我们只创建这个文件作为逻辑验证
