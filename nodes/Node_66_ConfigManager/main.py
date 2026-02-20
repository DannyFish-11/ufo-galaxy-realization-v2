# -*- coding: utf-8 -*-

"""
Node_66_ConfigManager: 配置管理服务

该服务负责管理系统的配置文件，支持多种格式（JSON, YAML, INI），
并提供动态加载、访问、修改和保存配置的功能。
它还提供了健康检查和状态查询的异步接口。
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Union

# 尝试导入 yaml 和 configparser，如果失败则在后续进行处理
try:
    import yaml
except ImportError:
    yaml = None
try:
    import configparser
except ImportError:
    configparser = None

# --- 枚举定义 ---

class ServiceStatus(Enum):
    """服务运行状态枚举"""
    STOPPED = "stopped"
    RUNNING = "running"
    DEGRADED = "degraded"
    ERROR = "error"

class ConfigFormat(Enum):
    """支持的配置文件格式枚举"""
    JSON = "json"
    YAML = "yaml"
    INI = "ini"
    UNKNOWN = "unknown"

# --- 数据类定义 ---

@dataclass
class AppConfig:
    """应用程序配置数据类"""
    service_name: str = "Node_66_ConfigManager"
    version: str = "1.0.0"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8066
    supported_formats: list[str] = field(default_factory=lambda: ["json", "yaml", "ini"])

# --- 主服务类 ---

class ConfigManagerService:
    """
    配置管理主服务类

    实现了配置的加载、解析、获取、设置和保存等核心功能，
    并支持异步操作和多种配置文件格式。
    """

    def __init__(self, default_config: AppConfig = AppConfig()):
        """
        初始化配置管理器服务。

        Args:
            default_config (AppConfig): 服务的默认配置。
        """
        self.node_name = "Node_66_ConfigManager"
        self._status = ServiceStatus.STOPPED
        self._config_data: Dict[str, Any] = {}
        self._app_config = default_config
        self._setup_logging()
        self.logger.info(f"{self.node_name} 服务正在初始化...")
        self._check_dependencies()
        self._status = ServiceStatus.RUNNING

    def _setup_logging(self):
        """配置日志记录器"""
        self.logger = logging.getLogger(self.node_name)
        self.logger.setLevel(self._app_config.log_level.upper())
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

    def _check_dependencies(self):
        """检查并报告缺失的依赖项"""
        if 'yaml' in self._app_config.supported_formats and yaml is None:
            self.logger.warning("PyYAML 未安装，YAML 文件格式将不受支持。请运行 'pip install pyyaml' 安装。")
            self._app_config.supported_formats.remove('yaml')
        if 'ini' in self._app_config.supported_formats and configparser is None:
            self.logger.warning("configparser 未找到，INI 文件格式将不受支持。")
            self._app_config.supported_formats.remove('ini')

    def _detect_format(self, file_path: str) -> ConfigFormat:
        """根据文件扩展名检测配置文件格式"""
        _, ext = os.path.splitext(file_path)
        ext = ext.lower().strip('.')
        if ext == 'json':
            return ConfigFormat.JSON
        elif ext in ['yaml', 'yml']:
            return ConfigFormat.YAML
        elif ext == 'ini':
            return ConfigFormat.INI
        else:
            return ConfigFormat.UNKNOWN

    async def load_config(self, file_path: str) -> bool:
        """
        从指定路径异步加载配置文件。

        Args:
            file_path (str): 配置文件的路径。

        Returns:
            bool: 如果加载成功则返回 True，否则返回 False。
        """
        self.logger.info(f"尝试从 '{file_path}' 加载配置...")
        config_format = self._detect_format(file_path)

        if config_format == ConfigFormat.UNKNOWN:
            self.logger.error(f"不支持的配置文件格式: {file_path}")
            self._status = ServiceStatus.ERROR
            return False
        
        if config_format.value not in self._app_config.supported_formats:
            self.logger.error(f"{config_format.value.upper()} 格式不受支持，因为缺少相关依赖。")
            self._status = ServiceStatus.ERROR
            return False

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                parser = getattr(self, f"_parse_{config_format.value}")
                self._config_data = parser(content)
                self.logger.info(f"成功从 '{file_path}' 加载并解析配置。")
                return True
        except FileNotFoundError:
            self.logger.error(f"配置文件未找到: {file_path}")
            self._status = ServiceStatus.ERROR
            return False
        except Exception as e:
            self.logger.error(f"加载或解析配置文件 '{file_path}' 时出错: {e}", exc_info=True)
            self._status = ServiceStatus.ERROR
            return False

    def _parse_json(self, content: str) -> Dict[str, Any]:
        """解析 JSON 格式的配置内容"""
        return json.loads(content)

    def _parse_yaml(self, content: str) -> Dict[str, Any]:
        """解析 YAML 格式的配置内容"""
        if yaml:
            return yaml.safe_load(content)
        raise NotImplementedError("YAML parser is not available.")

    def _parse_ini(self, content: str) -> Dict[str, Any]:
        """解析 INI 格式的配置内容"""
        if configparser:
            parser = configparser.ConfigParser()
            parser.read_string(content)
            # 将 ConfigParser 对象转换为字典
            return {section: dict(parser.items(section)) for section in parser.sections()}
        raise NotImplementedError("INI parser is not available.")

    def get_config(self, key: str, default: Any = None) -> Any:
        """
        根据键获取配置项的值。

        Args:
            key (str): 配置项的键，支持点分隔的嵌套访问 (e.g., 'database.host')。
            default (Any): 如果键不存在时返回的默认值。

        Returns:
            Any: 配置项的值。
        """
        try:
            keys = key.split('.')
            value = self._config_data
            for k in keys:
                if isinstance(value, dict):
                    value = value[k]
                else:
                    raise KeyError(f"路径 '{key}' 中的 '{k}' 不是一个有效的字典")
            return value
        except (KeyError, TypeError) as e:
            self.logger.warning(f"获取配置 '{key}' 失败: {e}。返回默认值。")
            return default

    async def health_check(self) -> Dict[str, Union[str, int]]:
        """
        执行健康检查并返回服务状态。

        Returns:
            Dict[str, Union[str, int]]: 包含服务状态和节点名称的字典。
        """
        self.logger.debug("执行健康检查...")
        return {
            "status": self._status.value,
            "node_name": self.node_name,
            "timestamp": asyncio.get_event_loop().time()
        }

    async def get_status(self) -> Dict[str, Any]:
        """
        获取服务的详细状态，包括当前加载的配置。

        Returns:
            Dict[str, Any]: 包含服务状态、应用配置和当前数据的字典。
        """
        self.logger.debug("获取服务详细状态...")
        return {
            "status": self._status.value,
            "app_config": self._app_config.__dict__,
            "loaded_config_data": self._config_data
        }

    async def run(self):
        """
        服务的主运行循环。
        目前该服务主要通过外部调用其方法来工作，
        此循环可以用于未来的周期性任务，如配置重新加载。
        """
        self.logger.info(f"{self.node_name} 服务已启动并正在运行。")
        self._status = ServiceStatus.RUNNING
        try:
            while self._status == ServiceStatus.RUNNING:
                # 在这里可以添加周期性任务，例如每隔一段时间自动重新加载配置
                await asyncio.sleep(60) # 每分钟检查一次
        except asyncio.CancelledError:
            self.logger.info(f"{self.node_name} 服务已停止。")
        finally:
            self._status = ServiceStatus.STOPPED

# --- 示例使用 ---            
async def main():
    """主函数，用于演示服务功能"""
    # 1. 创建示例配置文件
    if not os.path.exists("config"):
        os.makedirs("config")

    # JSON 示例
    json_config = {"database": {"host": "localhost", "port": 5432, "user": "admin"}, "api_key": "secret-key-json"}
    with open("config/config.json", "w", encoding='utf-8') as f:
        json.dump(json_config, f, indent=2)

    # YAML 示例
    if yaml:
        yaml_config = "database:\n  host: db.example.com\n  port: 3306\n  user: yaml_user\napi_key: secret-key-yaml"
        with open("config/config.yaml", "w", encoding='utf-8') as f:
            f.write(yaml_config)

    # INI 示例
    if configparser:
        ini_config = "[database]\nhost = ini.db.local\nport = 1433\nuser = sql_user\n\n[api]\nkey = secret-key-ini"
        with open("config/config.ini", "w", encoding='utf-8') as f:
            f.write(ini_config)

    # 2. 初始化服务
    service = ConfigManagerService()

    # 3. 演示加载不同格式的配置文件
    # 加载 JSON
    await service.load_config("config/config.json")
    print("\n--- 从 JSON 加载的配置 ---")
    print(f"数据库主机: {service.get_config('database.host')}")
    print(f"API 密钥: {service.get_config('api_key')}")

    # 加载 YAML (如果支持)
    if 'yaml' in service._app_config.supported_formats:
        await service.load_config("config/config.yaml")
        print("\n--- 从 YAML 加载的配置 ---")
        print(f"数据库主机: {service.get_config('database.host')}")
        print(f"API 密钥: {service.get_config('api_key')}")

    # 加载 INI (如果支持)
    if 'ini' in service._app_config.supported_formats:
        await service.load_config("config/config.ini")
        print("\n--- 从 INI 加载的配置 ---")
        print(f"数据库主机: {service.get_config('database.host')}")
        print(f"API 密钥: {service.get_config('api.key')}") # INI 解析后结构不同

    # 4. 演示健康检查和状态查询
    print("\n--- 服务状态检查 ---")
    health = await service.health_check()
    print(f"健康检查结果: {health}")

    status = await service.get_status()
    print(f"详细状态: {json.dumps(status, indent=2)}")

    # 5. 启动服务主循环 (在实际应用中，这会是一个长时间运行的任务)
    print("\n--- 启动服务运行循环 (将在10秒后停止以进行演示) ---")
    run_task = asyncio.create_task(service.run())
    await asyncio.sleep(10)
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        print("服务运行循环已成功取消。")

if __name__ == "__main__":
    # 设置全局日志级别
    logging.basicConfig(level=logging.INFO)
    # 检查并安装依赖
    if yaml is None:
        print("检测到 PyYAML 未安装，正在尝试安装...")
        try:
            import subprocess
            import sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml"])
            print("PyYAML 安装成功。")
        except Exception as e:
            print(f"PyYAML 安装失败: {e}")
    
    # 运行主程序
    asyncio.run(main())
