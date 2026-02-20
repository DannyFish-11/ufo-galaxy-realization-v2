"""
OpenCode 代码生成节点 (Node 117)
多模型支持的智能代码生成与优化系统
"""

import os
import json
import asyncio
import hashlib
import tempfile
import subprocess
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ModelProvider(Enum):
    """支持的AI模型提供商"""
    GPT4 = "gpt-4"
    GPT4_TURBO = "gpt-4-turbo"
    CLAUDE_3_OPUS = "claude-3-opus"
    CLAUDE_3_SONNET = "claude-3-sonnet"
    GEMINI_PRO = "gemini-pro"
    GEMINI_ULTRA = "gemini-ultra"


class CodeTaskType(Enum):
    """代码任务类型"""
    GENERATE = "generate"           # 代码生成
    COMPLETE = "complete"           # 代码补全
    REVIEW = "review"               # 代码审查
    OPTIMIZE = "optimize"           # 代码优化
    EXPLAIN = "explain"             # 代码解释
    REFACTOR = "refactor"           # 代码重构
    TEST_GENERATE = "test_generate" # 测试生成
    DOCUMENT = "document"           # 文档生成


@dataclass
class CodeContext:
    """代码上下文"""
    language: str
    framework: Optional[str] = None
    existing_code: str = ""
    requirements: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class CodeResult:
    """代码生成结果"""
    success: bool
    code: str
    language: str
    task_type: CodeTaskType
    model_used: ModelProvider
    execution_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class CodeReviewResult:
    """代码审查结果"""
    score: int  # 0-100
    issues: List[Dict[str, Any]] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    security_concerns: List[str] = field(default_factory=list)
    performance_notes: List[str] = field(default_factory=list)


class BaseCodeModel:
    """代码生成模型基类"""

    def __init__(self, provider: ModelProvider, api_key: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key or os.getenv(f"{provider.value.upper()}_API_KEY")
        self.request_count = 0
        self.token_usage = {"input": 0, "output": 0}

    async def generate(self, prompt: str, context: CodeContext) -> str:
        """生成代码 - 子类实现"""
        raise NotImplementedError

    async def complete(self, partial_code: str, context: CodeContext) -> str:
        """补全代码 - 子类实现"""
        raise NotImplementedError

    def _build_system_prompt(self, task_type: CodeTaskType, context: CodeContext) -> str:
        """构建系统提示词"""
        prompts = {
            CodeTaskType.GENERATE: f"""You are an expert {context.language} developer.
Generate clean, efficient, and well-documented code based on the requirements.
Framework: {context.framework or 'None'}
Follow best practices and coding standards.""",

            CodeTaskType.COMPLETE: f"""You are an expert {context.language} developer.
Complete the partial code provided. Maintain consistency with existing code style.
Consider: {', '.join(context.constraints) if context.constraints else 'None'}""",

            CodeTaskType.REVIEW: f"""You are a senior code reviewer.
Analyze the code for:
- Bugs and logical errors
- Security vulnerabilities
- Performance issues
- Code style violations
- Maintainability concerns
Provide detailed feedback with severity levels.""",

            CodeTaskType.OPTIMIZE: f"""You are a performance optimization expert.
Optimize the provided code for:
- Execution speed
- Memory usage
- Algorithmic efficiency
- Resource utilization
Maintain functionality while improving performance.""",

            CodeTaskType.EXPLAIN: f"""You are a technical educator.
Explain the code clearly and concisely.
Cover: purpose, logic flow, key components, and any complex algorithms.""",

            CodeTaskType.REFACTOR: f"""You are a refactoring expert.
Improve code structure and readability without changing behavior.
Focus on: modularity, naming, DRY principles, and design patterns.""",

            CodeTaskType.TEST_GENERATE: f"""You are a test automation expert.
Generate comprehensive unit tests covering:
- Normal cases
- Edge cases
- Error conditions
- Boundary values""",

            CodeTaskType.DOCUMENT: f"""You are a technical writer.
Generate clear documentation including:
- Function/class descriptions
- Parameter explanations
- Return value details
- Usage examples"""
        }
        return prompts.get(task_type, prompts[CodeTaskType.GENERATE])


class GPT4CodeModel(BaseCodeModel):
    """GPT-4 代码模型"""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(ModelProvider.GPT4, api_key)
        self.model_name = "gpt-4-0125-preview"

    async def generate(self, prompt: str, context: CodeContext) -> str:
        """使用 GPT-4 生成代码"""
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=self.api_key)

            system_prompt = self._build_system_prompt(CodeTaskType.GENERATE, context)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]

            response = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.2,
                max_tokens=4000
            )

            self.request_count += 1
            self.token_usage["input"] += response.usage.prompt_tokens
            self.token_usage["output"] += response.usage.completion_tokens

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"GPT-4 generation error: {e}")
            raise

    async def complete(self, partial_code: str, context: CodeContext) -> str:
        """使用 GPT-4 补全代码"""
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=self.api_key)

            system_prompt = self._build_system_prompt(CodeTaskType.COMPLETE, context)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Complete this code:\n```{context.language}\n{partial_code}\n```"}
            ]

            response = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.3,
                max_tokens=2000
            )

            self.request_count += 1
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"GPT-4 completion error: {e}")
            raise


class ClaudeCodeModel(BaseCodeModel):
    """Claude 代码模型"""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-opus"):
        super().__init__(ModelProvider.CLAUDE_3_OPUS, api_key)
        self.model_name = model

    async def generate(self, prompt: str, context: CodeContext) -> str:
        """使用 Claude 生成代码"""
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self.api_key)

            system_prompt = self._build_system_prompt(CodeTaskType.GENERATE, context)

            message = await client.messages.create(
                model=self.model_name,
                max_tokens=4000,
                temperature=0.2,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}]
            )

            self.request_count += 1
            self.token_usage["output"] += message.usage.output_tokens
            self.token_usage["input"] += message.usage.input_tokens

            return message.content[0].text

        except Exception as e:
            logger.error(f"Claude generation error: {e}")
            raise

    async def complete(self, partial_code: str, context: CodeContext) -> str:
        """使用 Claude 补全代码"""
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=self.api_key)

            system_prompt = self._build_system_prompt(CodeTaskType.COMPLETE, context)

            message = await client.messages.create(
                model=self.model_name,
                max_tokens=2000,
                temperature=0.3,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": f"Complete this code:\n```{context.language}\n{partial_code}\n```"
                }]
            )

            self.request_count += 1
            return message.content[0].text

        except Exception as e:
            logger.error(f"Claude completion error: {e}")
            raise


class GeminiCodeModel(BaseCodeModel):
    """Gemini 代码模型"""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-pro"):
        super().__init__(ModelProvider.GEMINI_PRO, api_key)
        self.model_name = model

    async def generate(self, prompt: str, context: CodeContext) -> str:
        """使用 Gemini 生成代码"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)

            model = genai.GenerativeModel(self.model_name)

            system_prompt = self._build_system_prompt(CodeTaskType.GENERATE, context)
            full_prompt = f"{system_prompt}\n\n{prompt}"

            response = await model.generate_content_async(
                full_prompt,
                generation_config={
                    "temperature": 0.2,
                    "max_output_tokens": 4000
                }
            )

            self.request_count += 1
            return response.text

        except Exception as e:
            logger.error(f"Gemini generation error: {e}")
            raise

    async def complete(self, partial_code: str, context: CodeContext) -> str:
        """使用 Gemini 补全代码"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)

            model = genai.GenerativeModel(self.model_name)

            system_prompt = self._build_system_prompt(CodeTaskType.COMPLETE, context)
            full_prompt = f"{system_prompt}\n\nComplete this code:\n```{context.language}\n{partial_code}\n```"

            response = await model.generate_content_async(
                full_prompt,
                generation_config={
                    "temperature": 0.3,
                    "max_output_tokens": 2000
                }
            )

            self.request_count += 1
            return response.text

        except Exception as e:
            logger.error(f"Gemini completion error: {e}")
            raise


class CodeExecutionEnvironment:
    """代码执行环境管理"""

    SUPPORTED_LANGUAGES = {
        "python": {
            "extension": ".py",
            "command": ["python3"],
            "timeout": 30
        },
        "javascript": {
            "extension": ".js",
            "command": ["node"],
            "timeout": 30
        },
        "typescript": {
            "extension": ".ts",
            "command": ["ts-node"],
            "timeout": 30
        },
        "bash": {
            "extension": ".sh",
            "command": ["bash"],
            "timeout": 10
        },
        "go": {
            "extension": ".go",
            "command": ["go", "run"],
            "timeout": 30
        },
        "rust": {
            "extension": ".rs",
            "command": ["rustc", "-o", "/tmp/output", "&&", "/tmp/output"],
            "timeout": 60
        }
    }

    def __init__(self, sandbox_dir: Optional[str] = None):
        self.sandbox_dir = sandbox_dir or tempfile.mkdtemp(prefix="opencode_")
        self.execution_history: List[Dict[str, Any]] = []
        os.makedirs(self.sandbox_dir, exist_ok=True)

    async def execute(self, code: str, language: str, 
                     input_data: Optional[str] = None) -> Dict[str, Any]:
        """在沙箱环境中执行代码"""

        if language not in self.SUPPORTED_LANGUAGES:
            return {
                "success": False,
                "error": f"Unsupported language: {language}",
                "output": "",
                "exit_code": -1
            }

        lang_config = self.SUPPORTED_LANGUAGES[language]
        file_ext = lang_config["extension"]
        timeout = lang_config["timeout"]

        # 创建临时文件
        file_hash = hashlib.md5(code.encode()).hexdigest()[:8]
        temp_file = os.path.join(self.sandbox_dir, f"code_{file_hash}{file_ext}")

        try:
            # 写入代码文件
            with open(temp_file, "w") as f:
                f.write(code)

            # 构建执行命令
            cmd = lang_config["command"] + [temp_file]

            # 执行代码
            start_time = datetime.now()

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=subprocess.PIPE if input_data else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.sandbox_dir
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=input_data.encode() if input_data else None),
                    timeout=timeout
                )

                execution_time = (datetime.now() - start_time).total_seconds()

                result = {
                    "success": process.returncode == 0,
                    "output": stdout.decode("utf-8", errors="replace"),
                    "error": stderr.decode("utf-8", errors="replace"),
                    "exit_code": process.returncode,
                    "execution_time": execution_time,
                    "language": language
                }

                self.execution_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "language": language,
                    "success": result["success"],
                    "execution_time": execution_time
                })

                return result

            except asyncio.TimeoutError:
                process.kill()
                return {
                    "success": False,
                    "error": f"Execution timeout after {timeout} seconds",
                    "output": "",
                    "exit_code": -1
                }

        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "output": "",
                "exit_code": -1
            }
        finally:
            # 清理临时文件
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def validate_syntax(self, code: str, language: str) -> Dict[str, Any]:
        """验证代码语法"""

        if language == "python":
            return self._validate_python_syntax(code)
        elif language in ["javascript", "typescript"]:
            return self._validate_js_syntax(code)
        else:
            return {"valid": True, "errors": []}  # 默认通过

    def _validate_python_syntax(self, code: str) -> Dict[str, Any]:
        """验证 Python 语法"""
        import ast

        try:
            ast.parse(code)
            return {"valid": True, "errors": []}
        except SyntaxError as e:
            return {
                "valid": False,
                "errors": [{
                    "line": e.lineno,
                    "column": e.offset,
                    "message": str(e)
                }]
            }

    def _validate_js_syntax(self, code: str) -> Dict[str, Any]:
        """验证 JavaScript 语法 (使用 node --check)"""
        try:
            result = subprocess.run(
                ["node", "--check", "-"],
                input=code,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                return {"valid": True, "errors": []}
            else:
                return {
                    "valid": False,
                    "errors": [{"message": result.stderr}]
                }
        except Exception as e:
            return {"valid": False, "errors": [{"message": str(e)}]}


class OpenCodeNode:
    """
    OpenCode 代码生成节点
    多模型支持的智能代码生成与优化系统
    """

    def __init__(self):
        self.models: Dict[ModelProvider, BaseCodeModel] = {}
        self.execution_env = CodeExecutionEnvironment()
        self.default_model = ModelProvider.GPT4
        self._init_models()

    def _init_models(self):
        """初始化所有可用的模型"""
        # GPT-4
        if os.getenv("OPENAI_API_KEY"):
            self.models[ModelProvider.GPT4] = GPT4CodeModel()
            self.models[ModelProvider.GPT4_TURBO] = GPT4CodeModel()

        # Claude
        if os.getenv("ANTHROPIC_API_KEY"):
            self.models[ModelProvider.CLAUDE_3_OPUS] = ClaudeCodeModel(model="claude-3-opus-20240229")
            self.models[ModelProvider.CLAUDE_3_SONNET] = ClaudeCodeModel(model="claude-3-sonnet-20240229")

        # Gemini
        if os.getenv("GOOGLE_API_KEY"):
            self.models[ModelProvider.GEMINI_PRO] = GeminiCodeModel(model="gemini-1.5-pro")
            self.models[ModelProvider.GEMINI_ULTRA] = GeminiCodeModel(model="gemini-1.0-ultra")

    def get_available_models(self) -> List[str]:
        """获取可用模型列表"""
        return [model.value for model in self.models.keys()]

    async def generate_code(
        self,
        description: str,
        context: CodeContext,
        model: Optional[ModelProvider] = None
    ) -> CodeResult:
        """
        生成代码

        Args:
            description: 代码需求描述
            context: 代码上下文
            model: 使用的模型（默认使用配置中的默认模型）

        Returns:
            CodeResult: 代码生成结果
        """
        import time
        start_time = time.time()

        model_provider = model or self.default_model

        if model_provider not in self.models:
            return CodeResult(
                success=False,
                code="",
                language=context.language,
                task_type=CodeTaskType.GENERATE,
                model_used=model_provider,
                execution_time=0,
                errors=[f"Model {model_provider.value} not available"]
            )

        try:
            model_instance = self.models[model_provider]

            # 构建提示词
            prompt = self._build_generation_prompt(description, context)

            # 生成代码
            generated_code = await model_instance.generate(prompt, context)

            # 提取代码块
            code = self._extract_code_block(generated_code, context.language)

            # 验证语法
            syntax_check = self.execution_env.validate_syntax(code, context.language)

            execution_time = time.time() - start_time

            return CodeResult(
                success=True,
                code=code,
                language=context.language,
                task_type=CodeTaskType.GENERATE,
                model_used=model_provider,
                execution_time=execution_time,
                metadata={
                    "syntax_valid": syntax_check["valid"],
                    "raw_response": generated_code
                },
                warnings=[] if syntax_check["valid"] else ["Syntax validation failed"],
                errors=syntax_check.get("errors", [])
            )

        except Exception as e:
            return CodeResult(
                success=False,
                code="",
                language=context.language,
                task_type=CodeTaskType.GENERATE,
                model_used=model_provider,
                execution_time=time.time() - start_time,
                errors=[str(e)]
            )

    async def complete_code(
        self,
        partial_code: str,
        context: CodeContext,
        model: Optional[ModelProvider] = None
    ) -> CodeResult:
        """
        补全代码

        Args:
            partial_code: 部分代码
            context: 代码上下文
            model: 使用的模型

        Returns:
            CodeResult: 代码补全结果
        """
        import time
        start_time = time.time()

        model_provider = model or self.default_model

        if model_provider not in self.models:
            return CodeResult(
                success=False,
                code="",
                language=context.language,
                task_type=CodeTaskType.COMPLETE,
                model_used=model_provider,
                execution_time=0,
                errors=[f"Model {model_provider.value} not available"]
            )

        try:
            model_instance = self.models[model_provider]

            completed_code = await model_instance.complete(partial_code, context)
            code = self._extract_code_block(completed_code, context.language)

            execution_time = time.time() - start_time

            return CodeResult(
                success=True,
                code=code,
                language=context.language,
                task_type=CodeTaskType.COMPLETE,
                model_used=model_provider,
                execution_time=execution_time,
                metadata={"raw_response": completed_code}
            )

        except Exception as e:
            return CodeResult(
                success=False,
                code="",
                language=context.language,
                task_type=CodeTaskType.COMPLETE,
                model_used=model_provider,
                execution_time=time.time() - start_time,
                errors=[str(e)]
            )

    async def review_code(
        self,
        code: str,
        context: CodeContext,
        model: Optional[ModelProvider] = None
    ) -> CodeReviewResult:
        """
        审查代码

        Args:
            code: 待审查的代码
            context: 代码上下文
            model: 使用的模型

        Returns:
            CodeReviewResult: 代码审查结果
        """
        model_provider = model or self.default_model

        if model_provider not in self.models:
            return CodeReviewResult(
                score=0,
                issues=[{"severity": "error", "message": f"Model {model_provider.value} not available"}]
            )

        try:
            model_instance = self.models[model_provider]

            review_prompt = f"""Review the following {context.language} code:

\`\`\`{context.language}
{code}
\`\`\`

Provide a detailed review including:
1. Overall score (0-100)
2. List of issues with severity (critical/high/medium/low)
3. Suggested improvements
4. Security concerns
5. Performance notes

Format as JSON with keys: score, issues, improvements, security_concerns, performance_notes"""

            review_context = CodeContext(
                language=context.language,
                framework=context.framework
            )

            response = await model_instance.generate(review_prompt, review_context)

            # 尝试解析 JSON 响应
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    review_data = json.loads(json_match.group())
                    return CodeReviewResult(
                        score=review_data.get("score", 70),
                        issues=review_data.get("issues", []),
                        improvements=review_data.get("improvements", []),
                        security_concerns=review_data.get("security_concerns", []),
                        performance_notes=review_data.get("performance_notes", [])
                    )
            except json.JSONDecodeError:
                pass

            # 如果 JSON 解析失败，返回基本结果
            return CodeReviewResult(
                score=70,
                improvements=["Review completed but structured parsing failed"],
                issues=[]
            )

        except Exception as e:
            return CodeReviewResult(
                score=0,
                issues=[{"severity": "error", "message": str(e)}]
            )

    async def optimize_code(
        self,
        code: str,
        context: CodeContext,
        optimization_goals: List[str] = None,
        model: Optional[ModelProvider] = None
    ) -> CodeResult:
        """
        优化代码

        Args:
            code: 待优化的代码
            context: 代码上下文
            optimization_goals: 优化目标
            model: 使用的模型

        Returns:
            CodeResult: 代码优化结果
        """
        import time
        start_time = time.time()

        model_provider = model or self.default_model
        goals = optimization_goals or ["performance", "readability"]

        if model_provider not in self.models:
            return CodeResult(
                success=False,
                code="",
                language=context.language,
                task_type=CodeTaskType.OPTIMIZE,
                model_used=model_provider,
                execution_time=0,
                errors=[f"Model {model_provider.value} not available"]
            )

        try:
            model_instance = self.models[model_provider]

            optimize_prompt = f"""Optimize the following {context.language} code for {', '.join(goals)}:

\`\`\`{context.language}
{code}
\`\`\`

Provide:
1. Optimized code
2. Explanation of changes
3. Expected improvements"""

            response = await model_instance.generate(optimize_prompt, context)
            optimized_code = self._extract_code_block(response, context.language)

            execution_time = time.time() - start_time

            return CodeResult(
                success=True,
                code=optimized_code,
                language=context.language,
                task_type=CodeTaskType.OPTIMIZE,
                model_used=model_provider,
                execution_time=execution_time,
                metadata={
                    "optimization_goals": goals,
                    "raw_response": response
                },
                suggestions=["Review optimized code before deployment"]
            )

        except Exception as e:
            return CodeResult(
                success=False,
                code="",
                language=context.language,
                task_type=CodeTaskType.OPTIMIZE,
                model_used=model_provider,
                execution_time=time.time() - start_time,
                errors=[str(e)]
            )

    async def execute_code(
        self,
        code: str,
        language: str,
        input_data: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        执行代码

        Args:
            code: 要执行的代码
            language: 编程语言
            input_data: 输入数据

        Returns:
            Dict: 执行结果
        """
        return await self.execution_env.execute(code, language, input_data)

    def _build_generation_prompt(self, description: str, context: CodeContext) -> str:
        """构建代码生成提示词"""
        prompt_parts = [f"Task: {description}"]

        if context.framework:
            prompt_parts.append(f"Framework: {context.framework}")

        if context.existing_code:
            prompt_parts.append(f"\nExisting code:\n\`\`\`{context.language}\n{context.existing_code}\n\`\`\`")

        if context.requirements:
            prompt_parts.append(f"\nRequirements:\n" + "\n".join(f"- {r}" for r in context.requirements))

        if context.constraints:
            prompt_parts.append(f"\nConstraints:\n" + "\n".join(f"- {c}" for c in context.constraints))

        if context.dependencies:
            prompt_parts.append(f"\nDependencies: {', '.join(context.dependencies)}")

        prompt_parts.append(f"\nGenerate {context.language} code that meets all requirements.")

        return "\n".join(prompt_parts)

    def _extract_code_block(self, text: str, language: str) -> str:
        """从文本中提取代码块"""
        import re

        # 尝试匹配 markdown 代码块
        pattern = rf'\`\`\`(?:{language})?\n(.*?)\n\`\`\`'
        match = re.search(pattern, text, re.DOTALL)

        if match:
            return match.group(1).strip()

        # 如果没有代码块标记，返回整个文本
        return text.strip()

    def get_execution_history(self) -> List[Dict[str, Any]]:
        """获取执行历史"""
        return self.execution_env.execution_history

    def get_model_stats(self) -> Dict[str, Any]:
        """获取模型使用统计"""
        stats = {}
        for provider, model in self.models.items():
            stats[provider.value] = {
                "request_count": model.request_count,
                "token_usage": model.token_usage
            }
        return stats


# 节点配置
NODE_CONFIG = {
    "id": "node_117_open_code",
    "name": "OpenCode",
    "version": "1.0.0",
    "description": "多模型支持的智能代码生成与优化系统",
    "author": "UFO Galaxy Team",
    "capabilities": [
        "code_generation",
        "code_completion",
        "code_review",
        "code_optimization",
        "code_execution",
        "multi_model_support"
    ],
    "supported_models": [
        "gpt-4",
        "gpt-4-turbo",
        "claude-3-opus",
        "claude-3-sonnet",
        "gemini-pro",
        "gemini-ultra"
    ],
    "supported_languages": [
        "python",
        "javascript",
        "typescript",
        "go",
        "rust",
        "bash"
    ]
}


async def main():
    """主函数 - 示例用法"""

    # 初始化节点
    node = OpenCodeNode()

    print("=" * 60)
    print("OpenCode Node 117 - 代码生成系统")
    print("=" * 60)

    # 显示可用模型
    print(f"\n可用模型: {node.get_available_models()}")

    # 示例 1: 生成代码
    print("\n--- 示例 1: 生成代码 ---")

    context = CodeContext(
        language="python",
        requirements=[
            "实现一个快速排序算法",
            "包含类型注解",
            "添加文档字符串"
        ],
        constraints=["时间复杂度 O(n log n)", "空间复杂度 O(log n)"]
    )

    result = await node.generate_code(
        description="创建一个快速排序函数",
        context=context,
        model=ModelProvider.GPT4 if ModelProvider.GPT4 in node.models else None
    )

    print(f"生成成功: {result.success}")
    print(f"使用模型: {result.model_used.value}")
    print(f"执行时间: {result.execution_time:.2f}s")
    if result.success:
        print(f"\n生成的代码:\n{result.code[:500]}...")

    # 示例 2: 代码审查
    print("\n--- 示例 2: 代码审查 ---")

    sample_code = """
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[0]
    left = [x for x in arr[1:] if x < pivot]
    right = [x for x in arr[1:] if x >= pivot]
    return quicksort(left) + [pivot] + quicksort(right)
"""

    review_context = CodeContext(language="python")
    review = await node.review_code(sample_code, review_context)

    print(f"审查评分: {review.score}/100")
    print(f"发现 {len(review.issues)} 个问题")
    print(f"改进建议: {review.improvements[:2] if review.improvements else 'None'}")

    # 示例 3: 执行代码
    print("\n--- 示例 3: 执行代码 ---")

    test_code = """
print("Hello from OpenCode!")
result = sum(range(10))
print(f"Sum of 0-9: {result}")
"""

    exec_result = await node.execute_code(test_code, "python")
    print(f"执行成功: {exec_result['success']}")
    print(f"输出: {exec_result['output'].strip()}")

    # 显示统计信息
    print("\n--- 统计信息 ---")
    stats = node.get_model_stats()
    print(f"模型使用统计: {json.dumps(stats, indent=2)}")

    print("\n" + "=" * 60)
    print("OpenCode 演示完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
