"""
UFO Galaxy - LLM 代码生成器
============================

真实的 LLM 代码生成实现，支持多种 LLM 后端

功能:
1. 多 LLM 后端支持 (OpenAI, Claude, Local LLM)
2. 代码生成、修复、优化
3. 代码解释和文档生成
4. 测试用例生成
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """LLM 提供商"""
    OPENAI = "openai"
    CLAUDE = "claude"
    LOCAL = "local"
    ONEAPI = "oneapi"


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: LLMProvider
    api_key: str = ""
    api_base: str = ""
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.2
    timeout: int = 60


@dataclass
class CodeGenerationRequest:
    """代码生成请求"""
    task_type: str  # bug_fix, feature, optimize, refactor, test, document
    description: str
    target_files: List[str] = field(default_factory=list)
    context_code: Dict[str, str] = field(default_factory=dict)  # 文件路径 -> 代码内容
    language: str = "python"
    constraints: List[str] = field(default_factory=list)


@dataclass
class CodeGenerationResult:
    """代码生成结果"""
    success: bool
    code_changes: Dict[str, str] = field(default_factory=dict)  # 文件路径 -> 新代码
    explanation: str = ""
    suggestions: List[str] = field(default_factory=list)
    error: str = ""


class BaseLLMClient(ABC):
    """LLM 客户端基类"""
    
    def __init__(self, config: LLMConfig):
        self.config = config
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """生成文本"""
        pass
    
    @abstractmethod
    async def generate_code(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """生成代码"""
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI 客户端"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or "https://api.openai.com/v1"
        self.model = config.model or "gpt-4"
    
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """生成文本"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    async def generate_code(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """生成代码"""
        system_prompt = self._build_system_prompt(request)
        user_prompt = self._build_user_prompt(request)
        
        try:
            response = await self.generate(user_prompt, system_prompt)
            return self._parse_response(response, request)
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            return CodeGenerationResult(success=False, error=str(e))
    
    def _build_system_prompt(self, request: CodeGenerationRequest) -> str:
        """构建系统提示"""
        return f"""You are an expert {request.language} programmer. Your task is to generate high-quality, production-ready code.

Guidelines:
1. Write clean, readable, and well-documented code
2. Follow best practices and design patterns
3. Include proper error handling
4. Write efficient and optimized code
5. Add type hints where applicable
6. Include docstrings for functions and classes

Output format:
- Return code in markdown code blocks with the file path as a comment at the top
- Separate multiple files with ---
- Include a brief explanation after the code"""
    
    def _build_user_prompt(self, request: CodeGenerationRequest) -> str:
        """构建用户提示"""
        prompt_parts = [
            f"Task Type: {request.task_type}",
            f"Description: {request.description}",
            f"Language: {request.language}"
        ]
        
        if request.target_files:
            prompt_parts.append(f"Target Files: {', '.join(request.target_files)}")
        
        if request.constraints:
            prompt_parts.append(f"Constraints: {', '.join(request.constraints)}")
        
        if request.context_code:
            prompt_parts.append("\nExisting Code Context:")
            for file_path, code in request.context_code.items():
                prompt_parts.append(f"\n--- {file_path} ---\n```{request.language}\n{code}\n```")
        
        return "\n".join(prompt_parts)
    
    def _parse_response(self, response: str, request: CodeGenerationRequest) -> CodeGenerationResult:
        """解析响应"""
        code_changes = {}
        explanation = ""
        
        # 提取代码块
        import re
        code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', response, re.DOTALL)
        
        # 尝试从代码块中提取文件路径
        for i, block in enumerate(code_blocks):
            lines = block.strip().split('\n')
            if lines and lines[0].startswith('#'):
                # 第一行是文件路径注释
                file_path = lines[0].lstrip('# ').strip()
                code = '\n'.join(lines[1:])
            elif request.target_files and i < len(request.target_files):
                file_path = request.target_files[i]
                code = block.strip()
            else:
                file_path = f"generated_{i}.py"
                code = block.strip()
            
            code_changes[file_path] = code
        
        # 提取解释（代码块之外的文本）
        explanation_parts = re.split(r'```.*?```', response, flags=re.DOTALL)
        explanation = ' '.join(part.strip() for part in explanation_parts if part.strip())
        
        return CodeGenerationResult(
            success=True,
            code_changes=code_changes,
            explanation=explanation
        )


class ClaudeClient(BaseLLMClient):
    """Claude 客户端"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or "https://api.anthropic.com/v1"
        self.model = config.model or "claude-3-sonnet-20240229"
    
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """生成文本"""
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.api_base}/messages",
                headers={
                    "x-api-key": self.config.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "max_tokens": self.config.max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
    
    async def generate_code(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """生成代码"""
        # 使用与 OpenAI 相同的逻辑
        openai_client = OpenAIClient(self.config)
        system_prompt = openai_client._build_system_prompt(request)
        user_prompt = openai_client._build_user_prompt(request)
        
        try:
            response = await self.generate(user_prompt, system_prompt)
            return openai_client._parse_response(response, request)
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            return CodeGenerationResult(success=False, error=str(e))


class LocalLLMClient(BaseLLMClient):
    """本地 LLM 客户端 (Ollama/vLLM)"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or "http://localhost:11434"
        self.model = config.model or "codellama"
    
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """生成文本"""
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.api_base}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "temperature": self.config.temperature,
                        "num_predict": self.config.max_tokens
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["response"]
    
    async def generate_code(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """生成代码"""
        openai_client = OpenAIClient(self.config)
        system_prompt = openai_client._build_system_prompt(request)
        user_prompt = openai_client._build_user_prompt(request)
        
        try:
            response = await self.generate(user_prompt, system_prompt)
            return openai_client._parse_response(response, request)
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            return CodeGenerationResult(success=False, error=str(e))


class OneAPIClient(BaseLLMClient):
    """OneAPI 统一接口客户端"""
    
    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.api_base = config.api_base or os.getenv("ONEAPI_BASE_URL", "http://localhost:3000/v1")
        self.model = config.model or os.getenv("ONEAPI_MODEL", "gpt-4")
    
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """生成文本 - 使用 OpenAI 兼容接口"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    async def generate_code(self, request: CodeGenerationRequest) -> CodeGenerationResult:
        """生成代码"""
        openai_client = OpenAIClient(self.config)
        system_prompt = openai_client._build_system_prompt(request)
        user_prompt = openai_client._build_user_prompt(request)
        
        try:
            response = await self.generate(user_prompt, system_prompt)
            return openai_client._parse_response(response, request)
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            return CodeGenerationResult(success=False, error=str(e))


class LLMCodeGenerator:
    """LLM 代码生成器 - 统一接口"""
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """
        初始化代码生成器
        
        如果未提供配置，将从环境变量读取
        """
        if config is None:
            config = self._load_config_from_env()
        
        self.config = config
        self.client = self._create_client(config)
    
    def _load_config_from_env(self) -> LLMConfig:
        """从环境变量加载配置"""
        provider = LLMProvider(os.getenv("LLM_PROVIDER", "oneapi"))
        
        return LLMConfig(
            provider=provider,
            api_key=os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")),
            api_base=os.getenv("LLM_API_BASE", os.getenv("ONEAPI_BASE_URL", "")),
            model=os.getenv("LLM_MODEL", "gpt-4"),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2"))
        )
    
    def _create_client(self, config: LLMConfig) -> BaseLLMClient:
        """创建 LLM 客户端"""
        if config.provider == LLMProvider.OPENAI:
            return OpenAIClient(config)
        elif config.provider == LLMProvider.CLAUDE:
            return ClaudeClient(config)
        elif config.provider == LLMProvider.LOCAL:
            return LocalLLMClient(config)
        elif config.provider == LLMProvider.ONEAPI:
            return OneAPIClient(config)
        else:
            raise ValueError(f"Unknown LLM provider: {config.provider}")
    
    async def generate_bug_fix(
        self,
        description: str,
        file_path: str,
        code: str,
        error_message: str = ""
    ) -> CodeGenerationResult:
        """生成 bug 修复代码"""
        request = CodeGenerationRequest(
            task_type="bug_fix",
            description=f"{description}\nError: {error_message}" if error_message else description,
            target_files=[file_path],
            context_code={file_path: code}
        )
        return await self.client.generate_code(request)
    
    async def generate_feature(
        self,
        description: str,
        target_files: List[str],
        context_code: Optional[Dict[str, str]] = None
    ) -> CodeGenerationResult:
        """生成新功能代码"""
        request = CodeGenerationRequest(
            task_type="feature",
            description=description,
            target_files=target_files,
            context_code=context_code or {}
        )
        return await self.client.generate_code(request)
    
    async def generate_tests(
        self,
        file_path: str,
        code: str
    ) -> CodeGenerationResult:
        """生成测试代码"""
        request = CodeGenerationRequest(
            task_type="test",
            description=f"Generate comprehensive unit tests for the code in {file_path}",
            target_files=[file_path.replace('.py', '_test.py')],
            context_code={file_path: code}
        )
        return await self.client.generate_code(request)
    
    async def optimize_code(
        self,
        file_path: str,
        code: str,
        optimization_goals: List[str] = None
    ) -> CodeGenerationResult:
        """优化代码"""
        goals = optimization_goals or ["performance", "readability", "maintainability"]
        request = CodeGenerationRequest(
            task_type="optimize",
            description=f"Optimize the code for: {', '.join(goals)}",
            target_files=[file_path],
            context_code={file_path: code},
            constraints=goals
        )
        return await self.client.generate_code(request)
    
    async def refactor_code(
        self,
        file_path: str,
        code: str,
        refactoring_type: str = "general"
    ) -> CodeGenerationResult:
        """重构代码"""
        request = CodeGenerationRequest(
            task_type="refactor",
            description=f"Refactor the code ({refactoring_type})",
            target_files=[file_path],
            context_code={file_path: code}
        )
        return await self.client.generate_code(request)
    
    async def generate_documentation(
        self,
        file_path: str,
        code: str
    ) -> CodeGenerationResult:
        """生成文档"""
        request = CodeGenerationRequest(
            task_type="document",
            description="Generate comprehensive documentation including docstrings, README, and usage examples",
            target_files=[file_path, file_path.replace('.py', '_README.md')],
            context_code={file_path: code}
        )
        return await self.client.generate_code(request)
    
    async def explain_code(self, code: str) -> str:
        """解释代码"""
        prompt = f"""Please explain the following code in detail:

```python
{code}
```

Include:
1. Overall purpose and functionality
2. Key components and their roles
3. Important algorithms or patterns used
4. Potential issues or improvements"""
        
        return await self.client.generate(prompt)


# 测试代码
async def test_llm_code_generator():
    """测试 LLM 代码生成器"""
    print("=== 测试 LLM 代码生成器 ===")
    
    # 创建生成器（使用模拟配置）
    config = LLMConfig(
        provider=LLMProvider.ONEAPI,
        api_key=os.getenv("OPENAI_API_KEY", "test-key"),
        api_base=os.getenv("ONEAPI_BASE_URL", "http://localhost:3000/v1"),
        model="gpt-4"
    )
    
    generator = LLMCodeGenerator(config)
    
    print(f"Provider: {config.provider}")
    print(f"Model: {config.model}")
    print(f"API Base: {config.api_base}")
    
    # 测试代码生成请求构建
    request = CodeGenerationRequest(
        task_type="feature",
        description="Create a simple HTTP client with retry logic",
        target_files=["http_client.py"],
        language="python"
    )
    
    print(f"\nTest Request:")
    print(f"  Task Type: {request.task_type}")
    print(f"  Description: {request.description}")
    print(f"  Target Files: {request.target_files}")
    
    # 注意：实际 API 调用需要有效的 API Key
    # 这里只测试请求构建逻辑
    print("\n✅ LLM 代码生成器初始化成功")
    print("注意：实际代码生成需要配置有效的 LLM API Key")


if __name__ == "__main__":
    asyncio.run(test_llm_code_generator())
