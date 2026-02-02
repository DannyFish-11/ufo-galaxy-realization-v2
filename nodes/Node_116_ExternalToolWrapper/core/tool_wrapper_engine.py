"""
External Tool Wrapper Engine - 通用工具包装引擎核心模块

功能：
1. 工具自动发现
2. 文档理解与解析
3. 动态命令生成
4. 执行结果验证
"""

import os
import json
import subprocess
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class ToolType(Enum):
    """工具类型"""
    CLI = "cli"  # 命令行工具
    API = "api"  # HTTP API
    LIBRARY = "library"  # 代码库
    GUI = "gui"  # 图形界面应用


class InstallMethod(Enum):
    """安装方法"""
    CURL_SCRIPT = "curl_script"  # curl | bash
    PACKAGE_MANAGER = "package_manager"  # apt/yum/brew
    DOWNLOAD_BINARY = "download_binary"  # 下载二进制文件
    PIP = "pip"  # Python pip
    NPM = "npm"  # Node.js npm
    MANUAL = "manual"  # 手动安装


@dataclass
class ToolKnowledge:
    """工具知识"""
    tool_name: str
    tool_type: ToolType
    description: str
    install_method: InstallMethod
    install_command: str
    config_path: Optional[str] = None
    config_template: Optional[Dict[str, Any]] = None
    common_commands: List[Dict[str, str]] = field(default_factory=list)
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    documentation_url: Optional[str] = None
    learned_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_type": self.tool_type.value,
            "description": self.description,
            "install_method": self.install_method.value,
            "install_command": self.install_command,
            "config_path": self.config_path,
            "config_template": self.config_template,
            "common_commands": self.common_commands,
            "parameters": self.parameters,
            "examples": self.examples,
            "documentation_url": self.documentation_url,
            "learned_at": self.learned_at
        }


@dataclass
class ExecutionResult:
    """执行结果"""
    success: bool
    stdout: str
    stderr: str
    return_code: int
    execution_time: float
    command: str
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "execution_time": self.execution_time,
            "command": self.command,
            "timestamp": self.timestamp
        }


class ToolWrapperEngine:
    """通用工具包装引擎"""
    
    def __init__(self, search_client=None, llm_client=None, sandbox_client=None):
        """
        初始化工具包装引擎
        
        Args:
            search_client: 搜索客户端（Node_22/Node_25）
            llm_client: LLM 客户端（Node_01_OneAPI）
            sandbox_client: 沙箱客户端（Node_09_Sandbox）
        """
        self.search_client = search_client
        self.llm_client = llm_client
        self.sandbox_client = sandbox_client
        
        # 工具知识库
        self.tool_knowledge: Dict[str, ToolKnowledge] = {}
        
        # 执行历史
        self.execution_history: List[ExecutionResult] = []
        
        # 配置
        self.config = {
            "max_search_results": 5,
            "command_timeout": 30,
            "auto_install": True,
            "verify_after_install": True
        }
    
    def discover_tool(self, tool_name: str) -> ToolKnowledge:
        """
        发现并学习工具
        
        Args:
            tool_name: 工具名称
            
        Returns:
            ToolKnowledge: 工具知识
        """
        # 1. 检查是否已经学习过
        if tool_name in self.tool_knowledge:
            return self.tool_knowledge[tool_name]
        
        # 2. 搜索工具信息
        search_results = self._search_tool_info(tool_name)
        
        # 3. 使用 LLM 理解工具
        tool_knowledge = self._understand_tool(tool_name, search_results)
        
        # 4. 存储知识
        self.tool_knowledge[tool_name] = tool_knowledge
        
        return tool_knowledge
    
    def use_tool(
        self,
        tool_name: str,
        task_description: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """
        使用工具完成任务
        
        Args:
            tool_name: 工具名称
            task_description: 任务描述
            context: 上下文信息
            
        Returns:
            ExecutionResult: 执行结果
        """
        context = context or {}
        
        # 1. 发现/获取工具知识
        if tool_name not in self.tool_knowledge:
            tool_knowledge = self.discover_tool(tool_name)
        else:
            tool_knowledge = self.tool_knowledge[tool_name]
        
        # 2. 检查工具是否已安装
        if not self._is_tool_installed(tool_name, tool_knowledge):
            if self.config["auto_install"]:
                install_result = self._install_tool(tool_knowledge)
                if not install_result.success:
                    return install_result
            else:
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr=f"Tool {tool_name} is not installed",
                    return_code=-1,
                    execution_time=0.0,
                    command=""
                )
        
        # 3. 生成命令
        command = self._generate_command(
            tool_knowledge, task_description, context
        )
        
        # 4. 执行命令
        result = self._execute_command(command)
        
        # 5. 验证结果
        result = self._verify_result(result, task_description)
        
        # 6. 记录历史
        self.execution_history.append(result)
        
        return result
    
    def learn_tool(
        self,
        tool_name: str,
        tool_type: str,
        description: str,
        install_command: str,
        examples: Optional[List[str]] = None
    ) -> ToolKnowledge:
        """
        手动教授工具知识
        
        Args:
            tool_name: 工具名称
            tool_type: 工具类型
            description: 描述
            install_command: 安装命令
            examples: 使用示例
            
        Returns:
            ToolKnowledge: 工具知识
        """
        tool_knowledge = ToolKnowledge(
            tool_name=tool_name,
            tool_type=ToolType(tool_type),
            description=description,
            install_method=self._infer_install_method(install_command),
            install_command=install_command,
            examples=examples or []
        )
        
        self.tool_knowledge[tool_name] = tool_knowledge
        return tool_knowledge
    
    def get_known_tools(self) -> List[str]:
        """获取已知工具列表"""
        return list(self.tool_knowledge.keys())
    
    def get_tool_knowledge(self, tool_name: str) -> Optional[ToolKnowledge]:
        """获取工具知识"""
        return self.tool_knowledge.get(tool_name)
    
    def forget_tool(self, tool_name: str) -> bool:
        """忘记工具"""
        if tool_name in self.tool_knowledge:
            del self.tool_knowledge[tool_name]
            return True
        return False
    
    # ========== 私有方法 ==========
    
    def _search_tool_info(self, tool_name: str) -> List[Dict[str, Any]]:
        """搜索工具信息"""
        # 简化实现：返回模拟搜索结果
        # 实际应该调用 Node_22_BraveSearch 或 Node_25_GoogleSearch
        return [
            {
                "title": f"{tool_name} - Official Documentation",
                "url": f"https://{tool_name.lower()}.dev",
                "snippet": f"{tool_name} is a powerful CLI tool..."
            }
        ]
    
    def _understand_tool(
        self, tool_name: str, search_results: List[Dict[str, Any]]
    ) -> ToolKnowledge:
        """使用 LLM 理解工具"""
        # 简化实现：返回基本知识
        # 实际应该调用 Node_01_OneAPI 进行深度理解
        
        # 推断工具类型
        tool_type = ToolType.CLI  # 默认 CLI
        
        # 推断安装方法和命令
        install_method = InstallMethod.CURL_SCRIPT
        install_command = f"curl -fsSL https://{tool_name.lower()}.dev/install.sh | bash"
        
        return ToolKnowledge(
            tool_name=tool_name,
            tool_type=tool_type,
            description=f"{tool_name} CLI tool",
            install_method=install_method,
            install_command=install_command,
            common_commands=[
                {"name": "help", "command": f"{tool_name} --help"},
                {"name": "version", "command": f"{tool_name} --version"}
            ]
        )
    
    def _is_tool_installed(
        self, tool_name: str, tool_knowledge: ToolKnowledge
    ) -> bool:
        """检查工具是否已安装"""
        try:
            # 尝试执行 --version 或 --help
            result = subprocess.run(
                [tool_name, "--version"],
                capture_output=True,
                timeout=5,
                text=True
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _install_tool(self, tool_knowledge: ToolKnowledge) -> ExecutionResult:
        """安装工具"""
        start_time = time.time()
        
        try:
            # 执行安装命令
            result = subprocess.run(
                tool_knowledge.install_command,
                shell=True,
                capture_output=True,
                timeout=300,  # 5分钟超时
                text=True
            )
            
            execution_time = time.time() - start_time
            
            execution_result = ExecutionResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                execution_time=execution_time,
                command=tool_knowledge.install_command
            )
            
            # 验证安装
            if self.config["verify_after_install"]:
                if not self._is_tool_installed(
                    tool_knowledge.tool_name, tool_knowledge
                ):
                    execution_result.success = False
                    execution_result.stderr += "\nVerification failed: tool not found after installation"
            
            return execution_result
            
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="Installation timeout",
                return_code=-1,
                execution_time=time.time() - start_time,
                command=tool_knowledge.install_command
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1,
                execution_time=time.time() - start_time,
                command=tool_knowledge.install_command
            )
    
    def _generate_command(
        self,
        tool_knowledge: ToolKnowledge,
        task_description: str,
        context: Dict[str, Any]
    ) -> str:
        """生成命令"""
        # 简化实现：基于任务描述生成基本命令
        # 实际应该调用 Node_01_OneAPI 进行智能生成
        
        tool_name = tool_knowledge.tool_name
        
        # 如果有示例，尝试匹配
        if tool_knowledge.examples:
            return tool_knowledge.examples[0]
        
        # 否则生成基本命令
        return f"{tool_name} {task_description}"
    
    def _execute_command(self, command: str) -> ExecutionResult:
        """执行命令"""
        start_time = time.time()
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=self.config["command_timeout"],
                text=True
            )
            
            execution_time = time.time() - start_time
            
            return ExecutionResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                execution_time=execution_time,
                command=command
            )
            
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="Command timeout",
                return_code=-1,
                execution_time=time.time() - start_time,
                command=command
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1,
                execution_time=time.time() - start_time,
                command=command
            )
    
    def _verify_result(
        self, result: ExecutionResult, task_description: str
    ) -> ExecutionResult:
        """验证结果"""
        # 简化实现：基于 return_code
        # 实际应该调用 Node_01_OneAPI 进行语义验证
        
        if result.return_code != 0:
            result.success = False
        
        return result
    
    def _infer_install_method(self, install_command: str) -> InstallMethod:
        """推断安装方法"""
        if "curl" in install_command and "bash" in install_command:
            return InstallMethod.CURL_SCRIPT
        elif "apt" in install_command or "yum" in install_command or "brew" in install_command:
            return InstallMethod.PACKAGE_MANAGER
        elif "pip" in install_command:
            return InstallMethod.PIP
        elif "npm" in install_command:
            return InstallMethod.NPM
        elif "wget" in install_command or "download" in install_command:
            return InstallMethod.DOWNLOAD_BINARY
        else:
            return InstallMethod.MANUAL
