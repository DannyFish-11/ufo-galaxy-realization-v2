"""
环境扫描器 (Environment Scanner)
自动发现系统中可用的工具、编程语言、IDE、设备等资源
"""

import os
import platform
import subprocess
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ToolType(Enum):
    """工具类型"""
    PROGRAMMING_LANGUAGE = "programming_language"
    IDE = "ide"
    COMPILER = "compiler"
    VERSION_CONTROL = "version_control"
    DATABASE = "database"
    WEB_SERVER = "web_server"
    CONTAINER = "container"
    DEVICE = "device"
    OTHER = "other"


@dataclass
class DiscoveredTool:
    """发现的工具"""
    name: str
    type: ToolType
    version: Optional[str]
    path: Optional[str]
    capabilities: List[str]
    metadata: Dict


class EnvironmentScanner:
    """环境扫描器"""
    
    def __init__(self):
        self.os_type = platform.system()
        self.discovered_tools = {}
        logger.info(f"EnvironmentScanner initialized on {self.os_type}")
    
    def scan_and_register_all(self) -> Dict[str, DiscoveredTool]:
        """扫描并注册所有工具"""
        logger.info("开始扫描环境中的所有工具...")
        
        # 扫描编程语言
        self._scan_programming_languages()
        
        # 扫描 IDE
        self._scan_ides()
        
        # 扫描版本控制工具
        self._scan_version_control()
        
        # 扫描容器工具
        self._scan_containers()
        
        # 扫描数据库
        self._scan_databases()
        
        # 扫描设备
        self._scan_devices()
        
        logger.info(f"扫描完成，发现 {len(self.discovered_tools)} 个工具")
        return self.discovered_tools
    
    def _scan_programming_languages(self):
        """扫描编程语言"""
        languages = {
            'python': ['python', 'python3', 'python3.11'],
            'node': ['node'],
            'java': ['java'],
            'go': ['go'],
            'rust': ['rustc'],
            'gcc': ['gcc'],
            'g++': ['g++'],
        }
        
        for lang_name, commands in languages.items():
            for cmd in commands:
                version = self._get_command_version(cmd)
                if version:
                    path = self._get_command_path(cmd)
                    self.discovered_tools[f"{lang_name}_{cmd}"] = DiscoveredTool(
                        name=cmd,
                        type=ToolType.PROGRAMMING_LANGUAGE,
                        version=version,
                        path=path,
                        capabilities=self._get_language_capabilities(lang_name),
                        metadata={'language': lang_name}
                    )
                    logger.info(f"发现编程语言: {cmd} {version}")
                    break
    
    def _scan_ides(self):
        """扫描 IDE"""
        if self.os_type == "Windows":
            self._scan_windows_ides()
        elif self.os_type == "Linux":
            self._scan_linux_ides()
        elif self.os_type == "Darwin":
            self._scan_macos_ides()
    
    def _scan_windows_ides(self):
        """扫描 Windows IDE"""
        # 检查常见 IDE 的注册表路径
        ide_paths = {
            'vscode': [
                r'C:\Program Files\Microsoft VS Code\Code.exe',
                r'C:\Program Files (x86)\Microsoft VS Code\Code.exe',
            ],
            'pycharm': [
                r'C:\Program Files\JetBrains\PyCharm*\bin\pycharm64.exe',
            ],
            'android_studio': [
                r'C:\Program Files\Android\Android Studio\bin\studio64.exe',
            ],
        }
        
        for ide_name, paths in ide_paths.items():
            for path_pattern in paths:
                if '*' in path_pattern:
                    # 使用 glob 匹配
                    import glob
                    matches = glob.glob(path_pattern)
                    if matches:
                        path = matches[0]
                        self._register_ide(ide_name, path)
                        break
                elif os.path.exists(path_pattern):
                    self._register_ide(ide_name, path_pattern)
                    break
    
    def _scan_linux_ides(self):
        """扫描 Linux IDE"""
        # 检查常见 IDE 命令
        ides = ['code', 'pycharm', 'studio.sh']
        
        for ide_cmd in ides:
            path = self._get_command_path(ide_cmd)
            if path:
                self._register_ide(ide_cmd, path)
    
    def _scan_macos_ides(self):
        """扫描 macOS IDE"""
        # 检查 Applications 目录
        app_paths = {
            'vscode': '/Applications/Visual Studio Code.app',
            'pycharm': '/Applications/PyCharm.app',
            'android_studio': '/Applications/Android Studio.app',
        }
        
        for ide_name, path in app_paths.items():
            if os.path.exists(path):
                self._register_ide(ide_name, path)
    
    def _register_ide(self, name: str, path: str):
        """注册 IDE"""
        self.discovered_tools[f"ide_{name}"] = DiscoveredTool(
            name=name,
            type=ToolType.IDE,
            version=None,
            path=path,
            capabilities=['code_editing', 'debugging', 'project_management'],
            metadata={'executable': path}
        )
        logger.info(f"发现 IDE: {name} at {path}")
    
    def _scan_version_control(self):
        """扫描版本控制工具"""
        vcs_tools = ['git', 'svn', 'hg']
        
        for tool in vcs_tools:
            version = self._get_command_version(tool)
            if version:
                path = self._get_command_path(tool)
                self.discovered_tools[f"vcs_{tool}"] = DiscoveredTool(
                    name=tool,
                    type=ToolType.VERSION_CONTROL,
                    version=version,
                    path=path,
                    capabilities=['version_control', 'collaboration'],
                    metadata={}
                )
                logger.info(f"发现版本控制工具: {tool} {version}")
    
    def _scan_containers(self):
        """扫描容器工具"""
        containers = ['docker', 'podman']
        
        for tool in containers:
            version = self._get_command_version(tool)
            if version:
                path = self._get_command_path(tool)
                self.discovered_tools[f"container_{tool}"] = DiscoveredTool(
                    name=tool,
                    type=ToolType.CONTAINER,
                    version=version,
                    path=path,
                    capabilities=['containerization', 'isolation', 'deployment'],
                    metadata={}
                )
                logger.info(f"发现容器工具: {tool} {version}")
    
    def _scan_databases(self):
        """扫描数据库"""
        databases = {
            'mysql': ['mysql', 'mysqld'],
            'postgresql': ['psql', 'postgres'],
            'mongodb': ['mongo', 'mongod'],
            'redis': ['redis-cli', 'redis-server'],
        }
        
        for db_name, commands in databases.items():
            for cmd in commands:
                version = self._get_command_version(cmd)
                if version:
                    path = self._get_command_path(cmd)
                    self.discovered_tools[f"db_{db_name}"] = DiscoveredTool(
                        name=db_name,
                        type=ToolType.DATABASE,
                        version=version,
                        path=path,
                        capabilities=['data_storage', 'query'],
                        metadata={'command': cmd}
                    )
                    logger.info(f"发现数据库: {db_name} {version}")
                    break
    
    def _scan_devices(self):
        """扫描设备"""
        # 检查 ADB (Android 设备)
        adb_version = self._get_command_version('adb')
        if adb_version:
            adb_path = self._get_command_path('adb')
            # 获取连接的设备列表
            devices = self._get_adb_devices()
            self.discovered_tools['device_android'] = DiscoveredTool(
                name='Android Device',
                type=ToolType.DEVICE,
                version=adb_version,
                path=adb_path,
                capabilities=['mobile_control', 'app_deployment'],
                metadata={'devices': devices}
            )
            logger.info(f"发现 Android 设备: {len(devices)} 个")
    
    def _get_command_version(self, command: str) -> Optional[str]:
        """获取命令版本"""
        version_flags = ['--version', '-v', '-V', 'version']
        
        for flag in version_flags:
            try:
                result = subprocess.run(
                    [command, flag],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    # 提取版本号（第一行）
                    return result.stdout.strip().split('\n')[0]
            except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
                continue
        
        return None
    
    def _get_command_path(self, command: str) -> Optional[str]:
        """获取命令路径"""
        try:
            if self.os_type == "Windows":
                result = subprocess.run(
                    ['where', command],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
            else:
                result = subprocess.run(
                    ['which', command],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
            
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except Exception:
            pass
        
        return None
    
    def _get_language_capabilities(self, language: str) -> List[str]:
        """获取编程语言的能力"""
        capabilities_map = {
            'python': ['scripting', 'data_analysis', 'web_development', 'ai_ml'],
            'node': ['web_development', 'api_development', 'scripting'],
            'java': ['enterprise_development', 'android_development'],
            'go': ['system_programming', 'cloud_native'],
            'rust': ['system_programming', 'performance_critical'],
            'gcc': ['c_programming', 'system_programming'],
            'g++': ['cpp_programming', 'system_programming'],
        }
        
        return capabilities_map.get(language, ['general_programming'])
    
    def _get_adb_devices(self) -> List[str]:
        """获取 ADB 连接的设备列表"""
        try:
            result = subprocess.run(
                ['adb', 'devices'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # 跳过第一行标题
                devices = []
                for line in lines:
                    if line.strip() and '\t' in line:
                        device_id = line.split('\t')[0]
                        devices.append(device_id)
                return devices
        except Exception:
            pass
        
        return []
    
    def get_tool(self, tool_id: str) -> Optional[DiscoveredTool]:
        """获取工具"""
        return self.discovered_tools.get(tool_id)
    
    def get_tools_by_type(self, tool_type: ToolType) -> List[DiscoveredTool]:
        """按类型获取工具"""
        return [tool for tool in self.discovered_tools.values() if tool.type == tool_type]
    
    def get_tools_by_capability(self, capability: str) -> List[DiscoveredTool]:
        """按能力获取工具"""
        return [tool for tool in self.discovered_tools.values() if capability in tool.capabilities]


if __name__ == '__main__':
    # 测试环境扫描器
    logging.basicConfig(level=logging.INFO)
    scanner = EnvironmentScanner()
    tools = scanner.scan_and_register_all()
    
    print(f"\n发现 {len(tools)} 个工具:")
    for tool_id, tool in tools.items():
        print(f"  - {tool.name} ({tool.type.value}): {tool.version or 'N/A'}")
