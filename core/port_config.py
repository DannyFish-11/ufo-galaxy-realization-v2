"""
Galaxy-Nexus — 统一端口配置读取模块
====================================

单一事实来源：从 config/unified_ports.yaml 读取所有端口分配。
所有模块应通过此模块获取端口号，禁止硬编码。

使用方法:
    from core.port_config import get_node_port, get_service_port, PortConfig

    # 获取节点端口
    port = get_node_port("Node_50_Transformer")  # → 8050

    # 获取基础设施端口
    redis_port = get_service_port("redis")  # → 6379

    # 获取完整配置
    config = PortConfig.instance()
    all_nodes = config.list_node_ports()
"""

import os
import logging
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger("Galaxy.PortConfig")

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PORTS_YAML_PATH = _PROJECT_ROOT / "config" / "unified_ports.yaml"

# 基础设施服务默认端口（当 yaml 不可用时的回退）
_DEFAULT_INFRASTRUCTURE_PORTS: Dict[str, int] = {
    "redis": 6379,
    "qdrant": 6333,
    "dashboard": 8085,        # Dashboard Backend Web UI (unified port)
    "oneapi_web": 3001,
    "api_gateway": 8765,      # Galaxy Gateway (unified port)
    "state_machine": 8765,
    "gateway": 8765,           # Galaxy Gateway (unified port — WS + REST + WebRTC proxy)
    "dashboard_backend": 8085, # Same as dashboard (unified port)
    "websocket": 8085,
    "websocket_http": 8081,
    "health_monitor": 9100,    # Avoid conflict with gateway
    "device_api": 8766,
    "ufo_api": 8767,
    "unified_launcher": 8085,  # Unified Launcher Web UI
    "dockerfile_default": 8086, # Docker container default port
}


class PortConfig:
    """统一端口配置管理器（单例）"""

    _instance: Optional["PortConfig"] = None
    _initialized: bool = False

    def __new__(cls) -> "PortConfig":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._node_ports: Dict[str, int] = {}
        self._service_ports: Dict[str, int] = dict(_DEFAULT_INFRASTRUCTURE_PORTS)
        self._raw_config: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """从 unified_ports.yaml 加载端口配置"""
        try:
            import yaml
        except ImportError:
            logger.warning(
                "PyYAML 未安装，尝试用简单解析器读取端口配置。"
                "建议安装: pip install pyyaml"
            )
            self._load_fallback()
            return

        if not _PORTS_YAML_PATH.exists():
            logger.warning(
                "端口配置文件不存在: %s，使用默认端口", _PORTS_YAML_PATH
            )
            self._load_fallback()
            return

        try:
            with open(_PORTS_YAML_PATH, "r", encoding="utf-8") as f:
                self._raw_config = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.error("读取端口配置失败: %s，使用默认端口", exc)
            self._load_fallback()
            return

        # 遍历所有 layer 提取节点端口
        for key, value in self._raw_config.items():
            if not isinstance(value, dict):
                continue

            # 提取 layer 内的 nodes
            nodes = value.get("nodes")
            if isinstance(nodes, dict):
                for node_name, node_config in nodes.items():
                    if isinstance(node_config, dict) and "port" in node_config:
                        port = int(node_config["port"])
                        self._node_ports[node_name] = port

            # 提取基础设施服务端口
            if key == "infrastructure":
                services = value.get("services", value)
                if isinstance(services, dict):
                    for svc_name, svc_config in services.items():
                        if isinstance(svc_config, dict) and "port" in svc_config:
                            self._service_ports[svc_name.lower()] = int(
                                svc_config["port"]
                            )

        logger.info(
            "端口配置加载完成: %d 个节点, %d 个基础服务",
            len(self._node_ports),
            len(self._service_ports),
        )

    def _load_fallback(self) -> None:
        """回退方案：从 config/unified_config.json 或 node_registry.json 读取端口"""
        # 尝试 unified_config.json
        config_json = _PROJECT_ROOT / "config" / "unified_config.json"
        if config_json.exists():
            try:
                import json

                with open(config_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                nodes = data.get("nodes", {})
                for node_name, node_config in nodes.items():
                    if isinstance(node_config, dict) and "port" in node_config:
                        self._node_ports[node_name] = int(node_config["port"])
                logger.info(
                    "从 unified_config.json 加载了 %d 个节点端口",
                    len(self._node_ports),
                )
            except Exception as exc:
                logger.error("回退加载 unified_config.json 失败: %s", exc)

    def get_node_port(self, node_name: str) -> int:
        """获取节点端口号

        Args:
            node_name: 节点名称，如 "Node_50_Transformer" 或 "Node_50"

        Returns:
            端口号

        Raises:
            KeyError: 节点未找到
        """
        # 精确匹配
        if node_name in self._node_ports:
            return self._node_ports[node_name]

        # 前缀匹配（支持 "Node_50" 匹配 "Node_50_Transformer"）
        for key, port in self._node_ports.items():
            if key.startswith(node_name + "_") or key == node_name:
                return port

        # 也检查环境变量覆盖
        env_key = f"GALAXY_PORT_{node_name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            try:
                return int(env_val)
            except ValueError:
                pass

        raise KeyError(
            f"节点 '{node_name}' 端口未配置。"
            f"请检查 config/unified_ports.yaml 或设置环境变量 {env_key}"
        )

    def get_service_port(self, service_name: str) -> int:
        """获取基础设施服务端口号

        Args:
            service_name: 服务名称，如 "redis", "qdrant", "dashboard"

        Returns:
            端口号

        Raises:
            KeyError: 服务未找到
        """
        key = service_name.lower()
        if key in self._service_ports:
            return self._service_ports[key]

        # 环境变量覆盖
        env_key = f"GALAXY_{key.upper()}_PORT"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            try:
                return int(env_val)
            except ValueError:
                pass

        raise KeyError(
            f"服务 '{service_name}' 端口未配置。"
            f"请检查 config/unified_ports.yaml 或设置环境变量 {env_key}"
        )

    def list_node_ports(self) -> Dict[str, int]:
        """列出所有已配置的节点端口"""
        return dict(self._node_ports)

    def list_service_ports(self) -> Dict[str, int]:
        """列出所有已配置的基础设施服务端口"""
        return dict(self._service_ports)

    def get_node_url(self, node_name: str, host: str = "localhost") -> str:
        """获取节点的完整 URL

        Args:
            node_name: 节点名称
            host: 主机名，默认 localhost

        Returns:
            完整URL，如 "http://localhost:8050"
        """
        port = self.get_node_port(node_name)
        return f"http://{host}:{port}"

    @classmethod
    def instance(cls) -> "PortConfig":
        """获取单例实例"""
        return cls()

    @classmethod
    def reset(cls) -> None:
        """重置单例（仅用于测试）"""
        cls._instance = None
        cls._initialized = False


# ── 模块级便捷函数 ──


def get_node_port(node_name: str) -> int:
    """获取节点端口号（便捷函数）

    Args:
        node_name: 节点名称，如 "Node_50_Transformer"

    Returns:
        端口号
    """
    return PortConfig.instance().get_node_port(node_name)


def get_service_port(service_name: str) -> int:
    """获取基础设施服务端口号（便捷函数）

    Args:
        service_name: 服务名称，如 "redis", "dashboard"

    Returns:
        端口号
    """
    return PortConfig.instance().get_service_port(service_name)


def get_node_url(node_name: str, host: str = "localhost") -> str:
    """获取节点完整URL（便捷函数）

    Args:
        node_name: 节点名称
        host: 主机名

    Returns:
        完整URL
    """
    return PortConfig.instance().get_node_url(node_name, host)
