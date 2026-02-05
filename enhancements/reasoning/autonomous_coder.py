"""
自主编程器 (Autonomous Coder) - 修复版
根据需求自动生成代码、测试、修复并部署

修复内容:
1. 集成真实LLM API (OpenAI GPT-4/Claude 3.5)
2. 添加静态代码分析 (pylint, mypy)
3. 实现Docker沙箱隔离执行
4. 添加迭代优化机制
"""
import os
import subprocess
import tempfile
import logging
import json
import ast
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class CodingStep(Enum):
    """编程步骤"""
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    DESIGN = "design"
    CODE_GENERATION = "code_generation"
    STATIC_ANALYSIS = "static_analysis"
    TESTING = "testing"
    DEBUGGING = "debugging"
    OPTIMIZATION = "optimization"
    DEPLOYMENT = "deployment"


@dataclass
class CodingTask:
    """编程任务"""
    requirement: str
    language: str
    target_type: str  # 'script', 'module', 'node', 'service'
    constraints: List[str]
    expected_output: Optional[str]
    context_code: Optional[str] = None  # 上下文代码


@dataclass
class CodingResult:
    """编程结果"""
    success: bool
    code: str
    file_path: Optional[str]
    test_output: Optional[str]
    errors: List[str]
    warnings: List[str]
    node_id: Optional[str]
    iterations: int
    quality_score: float


@dataclass
class CodeQualityReport:
    """代码质量报告"""
    pylint_score: float
    mypy_issues: List[str]
    complexity_score: float
    security_issues: List[str]
    overall_score: float


class LLMClient(ABC):
    """LLM客户端抽象基类"""
    
    @abstractmethod
    def generate(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        """生成代码"""
        pass
    
    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        """对话式生成"""
        pass


class OpenAIClient(LLMClient):
    """OpenAI GPT-4客户端"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self._client = None
        
    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("请安装openai: pip install openai")
        return self._client
    
    def generate(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content
    
    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature
        )
        return response.choices[0].message.content


class AnthropicClient(LLMClient):
    """Anthropic Claude客户端"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self._client = None
        
    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("请安装anthropic: pip install anthropic")
        return self._client
    
    def generate(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        client = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    
    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        client = self._get_client()
        # Convert to Anthropic format
        anthropic_messages = []
        for msg in messages:
            role = "assistant" if msg["role"] == "assistant" else "user"
            anthropic_messages.append({"role": role, "content": msg["content"]})
        
        response = client.messages.create(
            model=self.model,
            max_tokens=2000,
            temperature=temperature,
            messages=anthropic_messages
        )
        return response.content[0].text


class StaticAnalyzer:
    """静态代码分析器"""
    
    def analyze(self, code: str, language: str = "python") -> CodeQualityReport:
        """分析代码质量"""
        pylint_score = self._run_pylint(code)
        mypy_issues = self._run_mypy(code)
        complexity = self._calculate_complexity(code)
        security = self._check_security(code)
        
        overall = (
            pylint_score * 0.3 +
            (1 - len(mypy_issues) / 10) * 0.2 +
            (1 - complexity / 20) * 0.2 +
            (1 - len(security) / 5) * 0.3
        )
        
        return CodeQualityReport(
            pylint_score=pylint_score,
            mypy_issues=mypy_issues,
            complexity_score=complexity,
            security_issues=security,
            overall_score=max(0, min(1, overall))
        )
    
    def _run_pylint(self, code: str) -> float:
        """运行pylint检查"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            result = subprocess.run(
                ['pylint', '--disable=R,C', '--output-format=json', temp_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            os.unlink(temp_file)
            
            # Parse pylint output
            try:
                issues = json.loads(result.stdout) if result.stdout else []
                # Score: 10 - (number of issues * 0.5)
                score = max(0, 10 - len(issues) * 0.5)
                return score / 10  # Normalize to 0-1
            except json.JSONDecodeError:
                return 0.5
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("pylint不可用，跳过检查")
            return 0.5
    
    def _run_mypy(self, code: str) -> List[str]:
        """运行mypy类型检查"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            result = subprocess.run(
                ['mypy', '--ignore-missing-imports', temp_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            os.unlink(temp_file)
            
            if result.stdout:
                return [line for line in result.stdout.split('\n') if line.strip()]
            return []
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("mypy不可用，跳过检查")
            return []
    
    def _calculate_complexity(self, code: str) -> float:
        """计算代码复杂度"""
        try:
            tree = ast.parse(code)
            complexity = 0
            for node in ast.walk(tree):
                if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                    complexity += 1
                elif isinstance(node, ast.FunctionDef):
                    complexity += 1
            return complexity
        except SyntaxError:
            return 10
    
    def _check_security(self, code: str) -> List[str]:
        """安全检查"""
        issues = []
        dangerous_patterns = [
            (r'eval\s*\(', "使用eval()存在安全风险"),
            (r'exec\s*\(', "使用exec()存在安全风险"),
            (r'subprocess\.call.*shell\s*=\s*True', "使用shell=True存在命令注入风险"),
            (r'os\.system\s*\(', "使用os.system()存在安全风险"),
            (r'__import__\s*\(', "动态导入可能存在风险"),
        ]
        for pattern, msg in dangerous_patterns:
            if re.search(pattern, code):
                issues.append(msg)
        return issues


class DockerSandbox:
    """Docker沙箱执行环境"""
    
    def __init__(self, image: str = "python:3.11-slim"):
        self.image = image
        self.container_id = None
        
    def __enter__(self):
        """启动沙箱容器"""
        try:
            result = subprocess.run(
                ['docker', 'run', '-d', '--rm', 
                 '--network=none',  # 禁用网络
                 '--memory=512m',   # 限制内存
                 '--cpus=1',        # 限制CPU
                 '-v', f'{tempfile.gettempdir()}:/workspace',
                 self.image, 'sleep', '300'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                self.container_id = result.stdout.strip()
                logger.info(f"Docker沙箱启动: {self.container_id}")
            else:
                logger.error(f"Docker沙箱启动失败: {result.stderr}")
        except FileNotFoundError:
            logger.warning("Docker不可用，使用本地执行")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """停止沙箱容器"""
        if self.container_id:
            subprocess.run(
                ['docker', 'stop', self.container_id],
                capture_output=True,
                timeout=10
            )
            logger.info(f"Docker沙箱停止: {self.container_id}")
    
    def execute(self, code: str, language: str = "python") -> Tuple[str, List[str]]:
        """在沙箱中执行代码"""
        if not self.container_id or language != "python":
            return self._execute_local(code, language)
        
        try:
            # 保存代码到临时文件
            temp_file = os.path.join(tempfile.gettempdir(), 'sandbox_script.py')
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(code)
            
            # 在容器中执行
            result = subprocess.run(
                ['docker', 'exec', self.container_id,
                 'python3', '/workspace/sandbox_script.py'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            output = result.stdout
            errors = []
            if result.returncode != 0:
                errors.append(f"退出码: {result.returncode}")
                if result.stderr:
                    errors.append(result.stderr)
            
            os.unlink(temp_file)
            return output, errors
            
        except subprocess.TimeoutExpired:
            return "", ["执行超时"]
        except Exception as e:
            return "", [str(e)]
    
    def _execute_local(self, code: str, language: str) -> Tuple[str, List[str]]:
        """本地执行（备用）"""
        if language != "python":
            return "", [f"不支持的语言: {language}"]
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            result = subprocess.run(
                ['python3', temp_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            output = result.stdout
            errors = []
            if result.returncode != 0:
                errors.append(f"退出码: {result.returncode}")
                if result.stderr:
                    errors.append(result.stderr)
            
            os.unlink(temp_file)
            return output, errors
            
        except subprocess.TimeoutExpired:
            return "", ["执行超时"]
        except Exception as e:
            return "", [str(e)]


class AutonomousCoder:
    """自主编程器 - 修复版"""
    
    def __init__(self, llm_client: Optional[LLMClient] = None, use_docker: bool = False):
        self.llm_client = llm_client
        self.use_docker = use_docker
        self.sandbox_dir = tempfile.mkdtemp(prefix='galaxy_coder_')
        self.analyzer = StaticAnalyzer()
        self.max_iterations = 3
        logger.info(f"AutonomousCoder初始化完成，沙箱目录: {self.sandbox_dir}")
    
    def generate_and_execute(self, task: CodingTask) -> CodingResult:
        """生成并执行代码 - 主流程"""
        logger.info(f"开始处理编程任务: {task.requirement}")
        iterations = 0
        
        try:
            # 1. 深度需求分析
            analysis = self._analyze_requirement(task)
            logger.info(f"需求分析完成: {analysis}")
            
            # 2. 规划编程步骤
            steps = self._plan_coding_steps(task, analysis)
            logger.info(f"规划了 {len(steps)} 个编程步骤")
            
            # 3. 迭代生成和优化代码
            code = ""
            test_output = ""
            errors = []
            quality_score = 0.0
            
            for iteration in range(self.max_iterations):
                iterations = iteration + 1
                logger.info(f"=== 迭代 {iterations}/{self.max_iterations} ===")
                
                # 生成代码
                if iteration == 0:
                    code = self._generate_code_with_llm(task, analysis, steps)
                else:
                    # 基于反馈优化代码
                    code = self._optimize_code(code, errors, task, analysis)
                
                logger.info(f"代码生成完成: {len(code)} 字符")
                
                # 4. 静态代码分析
                quality_report = self.analyzer.analyze(code, task.language)
                quality_score = quality_report.overall_score
                logger.info(f"代码质量评分: {quality_score:.2f}")
                
                # 5. 在沙箱中执行
                if self.use_docker:
                    with DockerSandbox() as sandbox:
                        test_output, errors = sandbox.execute(code, task.language)
                else:
                    test_output, errors = self._execute_in_sandbox(code, task.language)
                
                # 6. 检查是否需要继续迭代
                if not errors and quality_score >= 0.7:
                    logger.info("代码质量达标，停止迭代")
                    break
                
                if errors:
                    logger.warning(f"发现 {len(errors)} 个错误，准备优化...")
            
            # 7. 部署为节点（如果需要）
            node_id = None
            file_path = None
            if task.target_type == 'node' and not errors:
                node_id, file_path = self._deploy_as_node(code, task)
                logger.info(f"部署为节点: {node_id}")
            else:
                file_path = self._save_to_file(code, task.language)
            
            return CodingResult(
                success=len(errors) == 0,
                code=code,
                file_path=file_path,
                test_output=test_output,
                errors=errors,
                warnings=quality_report.security_issues if 'quality_report' in locals() else [],
                node_id=node_id,
                iterations=iterations,
                quality_score=quality_score
            )
            
        except Exception as e:
            logger.error(f"编程任务失败: {e}")
            return CodingResult(
                success=False,
                code="",
                file_path=None,
                test_output=None,
                errors=[str(e)],
                warnings=[],
                node_id=None,
                iterations=iterations,
                quality_score=0.0
            )
    
    def _analyze_requirement(self, task: CodingTask) -> Dict:
        """深度需求分析"""
        analysis = {
            'inputs': [],
            'outputs': [],
            'dependencies': [],
            'complexity': 'medium',
            'functions': [],
            'classes': [],
            'context': task.context_code or ""
        }
        
        requirement_lower = task.requirement.lower()
        
        # 识别输入输出
        if 'file' in requirement_lower or '文件' in requirement_lower:
            analysis['inputs'].append('file_path')
            analysis['outputs'].append('file_content')
        
        if 'api' in requirement_lower or 'http' in requirement_lower:
            analysis['dependencies'].append('requests')
            analysis['dependencies'].append('urllib3')
        
        if 'json' in requirement_lower:
            analysis['dependencies'].append('json')
        
        if 'database' in requirement_lower or '数据库' in requirement_lower:
            analysis['dependencies'].append('sqlite3')
        
        if 'async' in requirement_lower or '异步' in requirement_lower:
            analysis['dependencies'].append('asyncio')
        
        # 使用LLM进行更深入的分析
        if self.llm_client:
            prompt = f"""
分析以下编程需求，提取关键信息：
需求: {task.requirement}
语言: {task.language}

请分析并返回JSON格式：
{{
    "functions": ["需要的函数列表"],
    "classes": ["需要的类列表"],
    "complexity": "low/medium/high",
    "key_features": ["关键功能点"]
}}
"""
            try:
                response = self.llm_client.generate(prompt, temperature=0.3)
                # 提取JSON
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    llm_analysis = json.loads(json_match.group())
                    analysis.update(llm_analysis)
            except Exception as e:
                logger.warning(f"LLM分析失败: {e}")
        
        return analysis
    
    def _plan_coding_steps(self, task: CodingTask, analysis: Dict) -> List[str]:
        """规划编程步骤"""
        steps = [
            "导入必要的库",
            "定义常量和配置",
            "定义数据类/结构",
            "实现辅助函数",
            "实现核心类",
            "实现主函数",
            "添加错误处理",
            "添加日志记录",
        ]
        
        if analysis.get('complexity') == 'high':
            steps.insert(3, "设计架构模式")
            steps.append("性能优化")
        
        return steps
    
    def _generate_code_with_llm(self, task: CodingTask, analysis: Dict, steps: List[str]) -> str:
        """使用LLM生成代码"""
        if not self.llm_client:
            return self._generate_code_from_template(task, analysis)
        
        prompt = f"""你是一个专业的Python程序员。请根据以下需求生成完整、可运行的代码。

需求：{task.requirement}

分析：
- 输入：{', '.join(analysis['inputs'])}
- 输出：{', '.join(analysis['outputs'])}
- 依赖：{', '.join(analysis['dependencies'])}
- 复杂度：{analysis.get('complexity', 'medium')}

约束：
{chr(10).join(f'- {c}' for c in task.constraints)}

编程步骤：
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(steps))}

要求：
1. 代码必须完整可运行
2. 包含适当的错误处理
3. 添加文档字符串
4. 遵循PEP 8规范
5. 包含类型提示

请只返回代码，不要包含解释。
"""
        
        try:
            response = self.llm_client.generate(prompt, temperature=0.7, max_tokens=3000)
            # 提取代码块
            code_match = re.search(r'```python\s*(.*?)\s*```', response, re.DOTALL)
            if code_match:
                return code_match.group(1).strip()
            return response.strip()
        except Exception as e:
            logger.warning(f"LLM生成失败: {e}，使用模板生成")
            return self._generate_code_from_template(task, analysis)
    
    def _optimize_code(self, code: str, errors: List[str], task: CodingTask, analysis: Dict) -> str:
        """基于错误优化代码"""
        if not self.llm_client:
            return code
        
        error_text = '\n'.join(errors)
        prompt = f"""请修复以下Python代码中的错误：

原始需求：{task.requirement}

当前代码：
```python
{code}
```

错误信息：
{error_text}

请返回修复后的完整代码，只返回代码，不要包含解释。
"""
        
        try:
            response = self.llm_client.generate(prompt, temperature=0.5, max_tokens=3000)
            code_match = re.search(r'```python\s*(.*?)\s*```', response, re.DOTALL)
            if code_match:
                return code_match.group(1).strip()
            return response.strip()
        except Exception as e:
            logger.warning(f"代码优化失败: {e}")
            return code
    
    def _generate_code_from_template(self, task: CodingTask, analysis: Dict) -> str:
        """从模板生成代码（备用）"""
        if task.language == 'python':
            return self._generate_python_template(task, analysis)
        return f"# TODO: Implement {task.requirement}\n"
    
    def _generate_python_template(self, task: CodingTask, analysis: Dict) -> str:
        """生成Python模板代码"""
        imports = ["import logging", "from typing import Optional, Dict, Any, List"]
        
        for dep in analysis['dependencies']:
            if dep == 'requests':
                imports.append("import requests")
            elif dep == 'json':
                imports.append("import json")
            elif dep == 'asyncio':
                imports.append("import asyncio")
        
        imports_str = '\n'.join(imports)
        
        code = f'''#!/usr/bin/env python3
"""
{task.requirement}
"""

{imports_str}

logger = logging.getLogger(__name__)


def main() -> bool:
    """
    主函数
    
    Returns:
        bool: 执行是否成功
    """
    try:
        logger.info("执行任务: {task.requirement}")
        
        # TODO: 实现核心逻辑
        
        return True
    
    except Exception as e:
        logger.error(f"执行失败: {{e}}")
        return False


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    success = main()
    exit(0 if success else 1)
'''
        return code
    
    def _execute_in_sandbox(self, code: str, language: str) -> Tuple[str, List[str]]:
        """在沙箱中执行代码"""
        if language != 'python':
            return "", [f"不支持的语言: {language}"]
        
        try:
            temp_file = os.path.join(self.sandbox_dir, 'temp_script.py')
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(code)
            
            result = subprocess.run(
                ['python3', temp_file],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.sandbox_dir
            )
            
            output = result.stdout
            errors = []
            
            if result.returncode != 0:
                errors.append(f"退出码: {result.returncode}")
                if result.stderr:
                    errors.append(result.stderr)
            
            return output, errors
            
        except subprocess.TimeoutExpired:
            return "", ["执行超时"]
        except Exception as e:
            return "", [str(e)]
    
    def _deploy_as_node(self, code: str, task: CodingTask) -> Tuple[str, str]:
        """部署为节点"""
        nodes_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes')
        os.makedirs(nodes_dir, exist_ok=True)
        
        existing_nodes = [d for d in os.listdir(nodes_dir) if d.startswith('Node_')]
        node_numbers = [int(n.split('_')[1]) for n in existing_nodes if n.split('_')[1].isdigit()]
        next_node_id = max(node_numbers) + 1 if node_numbers else 119
        
        node_name = f"Node_{next_node_id}_AutoGenerated"
        node_dir = os.path.join(nodes_dir, node_name)
        os.makedirs(node_dir, exist_ok=True)
        
        main_file = os.path.join(node_dir, 'main.py')
        with open(main_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        config_file = os.path.join(node_dir, 'config.json')
        config = {
            "node_id": next_node_id,
            "name": node_name,
            "description": task.requirement,
            "auto_generated": True,
            "language": task.language,
            "created_at": datetime.now().isoformat()
        }
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        
        logger.info(f"节点已部署: {node_name} at {node_dir}")
        return node_name, main_file
    
    def _save_to_file(self, code: str, language: str) -> str:
        """保存代码到文件"""
        ext_map = {
            'python': '.py',
            'javascript': '.js',
            'java': '.java',
            'go': '.go',
        }
        
        ext = ext_map.get(language, '.txt')
        file_path = os.path.join(self.sandbox_dir, f'generated_code{ext}')
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(code)
        
        return file_path


# 便捷函数
def create_coder_with_openai(api_key: Optional[str] = None, use_docker: bool = False) -> AutonomousCoder:
    """创建使用OpenAI的编码器"""
    client = OpenAIClient(api_key=api_key)
    return AutonomousCoder(llm_client=client, use_docker=use_docker)


def create_coder_with_anthropic(api_key: Optional[str] = None, use_docker: bool = False) -> AutonomousCoder:
    """创建使用Anthropic的编码器"""
    client = AnthropicClient(api_key=api_key)
    return AutonomousCoder(llm_client=client, use_docker=use_docker)


if __name__ == '__main__':
    # 测试自主编程器
    logging.basicConfig(level=logging.INFO)
    
    # 使用模板模式测试（无需API密钥）
    coder = AutonomousCoder()
    
    task = CodingTask(
        requirement="创建一个读取JSON文件并打印内容的脚本",
        language="python",
        target_type="script",
        constraints=["使用标准库", "添加错误处理"],
        expected_output="JSON内容"
    )
    
    result = coder.generate_and_execute(task)
    
    print(f"\n编程结果:")
    print(f"  成功: {result.success}")
    print(f"  质量评分: {result.quality_score:.2f}")
    print(f"  迭代次数: {result.iterations}")
    print(f"  文件: {result.file_path}")
    if result.test_output:
        print(f"  输出: {result.test_output}")
    if result.errors:
        print(f"  错误: {result.errors}")
    if result.warnings:
        print(f"  警告: {result.warnings}")
