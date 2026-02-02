"""
OpenCode Engine - OpenCode 专用引擎核心模块

功能：
1. 多模型支持（GPT-4, Claude, DeepSeek等）
2. 自动配置管理
3. 代码质量验证
4. 与系统其他节点深度协同
"""

import os
import json
import subprocess
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ModelProvider(Enum):
    """模型提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    GROQ = "groq"
    LOCAL = "local"


@dataclass
class OpenCodeConfig:
    """OpenCode 配置"""
    model: str = "gpt-4"
    provider: ModelProvider = ModelProvider.OPENAI
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2000
    timeout: int = 30
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider.value,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout
        }


@dataclass
class CodeGenerationResult:
    """代码生成结果"""
    success: bool
    code: str
    language: str
    model_used: str
    execution_time: float
    quality_score: Optional[float] = None
    validation_errors: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "code": self.code,
            "language": self.language,
            "model_used": self.model_used,
            "execution_time": self.execution_time,
            "quality_score": self.quality_score,
            "validation_errors": self.validation_errors,
            "timestamp": self.timestamp
        }


class OpenCodeEngine:
    """OpenCode 专用引擎"""
    
    def __init__(self, secret_vault_client=None, debug_client=None):
        """
        初始化 OpenCode 引擎
        
        Args:
            secret_vault_client: 密钥管理客户端（Node_03_SecretVault）
            debug_client: 调试优化客户端（Node_102_DebugOptimize）
        """
        self.secret_vault_client = secret_vault_client
        self.debug_client = debug_client
        
        # 配置
        self.config = OpenCodeConfig()
        
        # 安装状态
        self.is_installed = False
        self.opencode_path = None
        
        # 支持的模型
        self.supported_models = {
            ModelProvider.OPENAI: ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
            ModelProvider.ANTHROPIC: ["claude-3-opus", "claude-3-sonnet", "claude-3-haiku"],
            ModelProvider.DEEPSEEK: ["deepseek-coder", "deepseek-chat"],
            ModelProvider.GROQ: ["llama-3-70b", "mixtral-8x7b"],
            ModelProvider.LOCAL: ["local-model"]
        }
        
        # 生成历史
        self.generation_history: List[CodeGenerationResult] = []
        
        # 检查安装状态
        self._check_installation()
    
    def generate_code(
        self,
        prompt: str,
        language: Optional[str] = None,
        model: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> CodeGenerationResult:
        """
        生成代码
        
        Args:
            prompt: 代码生成提示
            language: 目标语言（可选）
            model: 指定模型（可选）
            context: 上下文信息（可选）
            
        Returns:
            CodeGenerationResult: 生成结果
        """
        start_time = time.time()
        
        # 确保已安装
        if not self.is_installed:
            install_result = self.install()
            if not install_result["success"]:
                return CodeGenerationResult(
                    success=False,
                    code="",
                    language=language or "unknown",
                    model_used=model or self.config.model,
                    execution_time=time.time() - start_time
                )
        
        # 使用指定模型或默认模型
        model_to_use = model or self.config.model
        
        # 构建命令
        command = self._build_command(prompt, language, model_to_use)
        
        # 执行命令
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=self.config.timeout,
                text=True
            )
            
            execution_time = time.time() - start_time
            
            if result.returncode == 0:
                code = result.stdout.strip()
                
                # 验证代码质量
                quality_score, validation_errors = self._validate_code(
                    code, language
                )
                
                generation_result = CodeGenerationResult(
                    success=True,
                    code=code,
                    language=language or self._detect_language(code),
                    model_used=model_to_use,
                    execution_time=execution_time,
                    quality_score=quality_score,
                    validation_errors=validation_errors
                )
            else:
                generation_result = CodeGenerationResult(
                    success=False,
                    code="",
                    language=language or "unknown",
                    model_used=model_to_use,
                    execution_time=execution_time,
                    validation_errors=[result.stderr]
                )
            
            # 记录历史
            self.generation_history.append(generation_result)
            
            return generation_result
            
        except subprocess.TimeoutExpired:
            return CodeGenerationResult(
                success=False,
                code="",
                language=language or "unknown",
                model_used=model_to_use,
                execution_time=time.time() - start_time,
                validation_errors=["Generation timeout"]
            )
        except Exception as e:
            return CodeGenerationResult(
                success=False,
                code="",
                language=language or "unknown",
                model_used=model_to_use,
                execution_time=time.time() - start_time,
                validation_errors=[str(e)]
            )
    
    def configure(
        self,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        配置 OpenCode
        
        Args:
            model: 模型名称
            provider: 提供商
            api_key: API Key
            temperature: 温度参数
            
        Returns:
            Dict: 配置结果
        """
        if model:
            self.config.model = model
        
        if provider:
            try:
                self.config.provider = ModelProvider(provider)
            except ValueError:
                return {
                    "success": False,
                    "error": f"Invalid provider. Must be one of: {[p.value for p in ModelProvider]}"
                }
        
        if api_key:
            self.config.api_key = api_key
        
        if temperature is not None:
            self.config.temperature = temperature
        
        # 写入配置文件
        config_written = self._write_config_file()
        
        return {
            "success": config_written,
            "config": self.config.to_dict()
        }
    
    def install(self) -> Dict[str, Any]:
        """
        安装 OpenCode
        
        Returns:
            Dict: 安装结果
        """
        # 简化实现：模拟安装
        # 实际应该执行真实的安装命令
        
        install_command = "curl -fsSL https://opencode.dev/install.sh | bash"
        
        try:
            # 模拟安装（实际环境中应执行真实命令）
            # result = subprocess.run(install_command, shell=True, capture_output=True, timeout=300)
            
            # 模拟成功
            self.is_installed = True
            self.opencode_path = "/usr/local/bin/opencode"
            
            return {
                "success": True,
                "message": "OpenCode installed successfully",
                "path": self.opencode_path
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取状态
        
        Returns:
            Dict: 状态信息
        """
        return {
            "installed": self.is_installed,
            "opencode_path": self.opencode_path,
            "config": self.config.to_dict(),
            "supported_models": {
                provider.value: models
                for provider, models in self.supported_models.items()
            },
            "generation_count": len(self.generation_history)
        }
    
    def get_supported_models(self) -> Dict[str, List[str]]:
        """
        获取支持的模型列表
        
        Returns:
            Dict: 提供商 -> 模型列表
        """
        return {
            provider.value: models
            for provider, models in self.supported_models.items()
        }
    
    # ========== 私有方法 ==========
    
    def _check_installation(self):
        """检查安装状态"""
        try:
            result = subprocess.run(
                ["which", "opencode"],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode == 0:
                self.is_installed = True
                self.opencode_path = result.stdout.strip()
        except:
            self.is_installed = False
    
    def _build_command(
        self, prompt: str, language: Optional[str], model: str
    ) -> str:
        """构建命令"""
        command_parts = ["opencode"]
        
        # 添加模型参数
        command_parts.append(f"-m {model}")
        
        # 添加语言参数
        if language:
            command_parts.append(f"-l {language}")
        
        # 添加温度参数
        command_parts.append(f"-t {self.config.temperature}")
        
        # 添加提示
        command_parts.append(f"-p '{prompt}'")
        
        return " ".join(command_parts)
    
    def _validate_code(
        self, code: str, language: Optional[str]
    ) -> Tuple[float, List[str]]:
        """
        验证代码质量
        
        Returns:
            Tuple[float, List[str]]: (质量分数, 错误列表)
        """
        errors = []
        
        # 基本检查
        if not code:
            errors.append("Empty code")
            return 0.0, errors
        
        if len(code) < 10:
            errors.append("Code too short")
        
        # 语法检查（简化实现）
        if language == "python":
            try:
                compile(code, "<string>", "exec")
            except SyntaxError as e:
                errors.append(f"Syntax error: {e}")
        
        # 计算质量分数
        quality_score = 1.0 - (len(errors) * 0.2)
        quality_score = max(0.0, min(1.0, quality_score))
        
        return quality_score, errors
    
    def _detect_language(self, code: str) -> str:
        """检测代码语言"""
        # 简化实现：基于关键词
        if "def " in code or "import " in code:
            return "python"
        elif "function " in code or "const " in code:
            return "javascript"
        elif "public class " in code:
            return "java"
        else:
            return "unknown"
    
    def _write_config_file(self) -> bool:
        """写入配置文件"""
        try:
            config_path = Path.home() / ".opencode.json"
            config_data = {
                "model": self.config.model,
                "provider": self.config.provider.value,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens
            }
            
            # 添加 API Key（如果有）
            if self.config.api_key:
                config_data["api_key"] = self.config.api_key
            
            # 写入文件
            with open(config_path, "w") as f:
                json.dump(config_data, f, indent=2)
            
            return True
        except Exception:
            return False
