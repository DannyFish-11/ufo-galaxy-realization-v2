"""
UFO Galaxy - 自主编程引擎 V2
=============================

增强版自主编程引擎，集成真实的 LLM 代码生成

功能:
1. 真实 LLM 代码生成（通过 llm_code_generator）
2. 静态代码分析
3. 自动测试执行
4. 代码质量评估
5. 版本控制集成
"""

import os
import sys
import json
import asyncio
import logging
import subprocess
import tempfile
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from pathlib import Path

# 添加项目路径
sys.path.insert(0, '/home/ubuntu/code_audit/ufo-galaxy-realization')

from enhancements.coding.llm_code_generator import (
    LLMCodeGenerator,
    LLMConfig,
    LLMProvider,
    CodeGenerationRequest,
    CodeGenerationResult
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CodingTaskType(str, Enum):
    """编程任务类型"""
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    OPTIMIZE = "optimize"
    REFACTOR = "refactor"
    TEST = "test"
    DOCUMENT = "document"


@dataclass
class CodingContext:
    """编程上下文"""
    task_type: CodingTaskType
    description: str
    target_files: List[str] = field(default_factory=list)
    existing_code: Dict[str, str] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    language: str = "python"
    workspace_root: str = ""


@dataclass
class CodingResult:
    """编程结果"""
    success: bool
    code_changes: Dict[str, str] = field(default_factory=dict)
    test_results: Dict[str, Any] = field(default_factory=dict)
    quality_score: float = 0.0
    explanation: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class CodeAnalyzer:
    """代码分析器"""
    
    def __init__(self):
        self.available_tools = self._detect_tools()
    
    def _detect_tools(self) -> Dict[str, bool]:
        """检测可用的分析工具"""
        tools = {}
        
        # 检查 Python 工具
        for tool in ['pylint', 'flake8', 'mypy', 'black', 'isort', 'bandit']:
            try:
                result = subprocess.run(
                    [tool, '--version'],
                    capture_output=True,
                    timeout=5
                )
                tools[tool] = result.returncode == 0
            except Exception:
                tools[tool] = False
        
        return tools
    
    def analyze_syntax(self, code: str, filename: str = "temp.py") -> Tuple[bool, List[str]]:
        """语法分析"""
        errors = []
        
        try:
            compile(code, filename, 'exec')
            return True, []
        except SyntaxError as e:
            errors.append(f"Syntax error at line {e.lineno}: {e.msg}")
            return False, errors
    
    def analyze_style(self, code: str, filename: str = "temp.py") -> List[str]:
        """代码风格分析"""
        warnings = []
        
        if not self.available_tools.get('flake8'):
            return warnings
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_path = f.name
            
            result = subprocess.run(
                ['flake8', '--max-line-length=120', temp_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        warnings.append(line.replace(temp_path, filename))
            
            os.unlink(temp_path)
        except Exception as e:
            logger.warning(f"Style analysis failed: {e}")
        
        return warnings
    
    def analyze_security(self, code: str, filename: str = "temp.py") -> List[str]:
        """安全分析"""
        issues = []
        
        if not self.available_tools.get('bandit'):
            return issues
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_path = f.name
            
            result = subprocess.run(
                ['bandit', '-f', 'json', temp_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.stdout:
                try:
                    data = json.loads(result.stdout)
                    for issue in data.get('results', []):
                        issues.append(f"[{issue['severity']}] {issue['issue_text']} (line {issue['line_number']})")
                except json.JSONDecodeError:
                    pass
            
            os.unlink(temp_path)
        except Exception as e:
            logger.warning(f"Security analysis failed: {e}")
        
        return issues
    
    def calculate_quality_score(
        self,
        syntax_ok: bool,
        style_warnings: List[str],
        security_issues: List[str]
    ) -> float:
        """计算代码质量分数"""
        if not syntax_ok:
            return 0.0
        
        score = 100.0
        
        # 风格警告扣分
        score -= len(style_warnings) * 2
        
        # 安全问题扣分
        for issue in security_issues:
            if 'HIGH' in issue:
                score -= 20
            elif 'MEDIUM' in issue:
                score -= 10
            else:
                score -= 5
        
        return max(0.0, min(100.0, score))


class TestRunner:
    """测试运行器"""
    
    def __init__(self, workspace_root: str = ""):
        self.workspace_root = workspace_root
    
    def run_tests(self, test_file: str) -> Dict[str, Any]:
        """运行测试"""
        result = {
            'passed': False,
            'total': 0,
            'passed_count': 0,
            'failed_count': 0,
            'errors': [],
            'output': ''
        }
        
        try:
            proc = subprocess.run(
                ['python3', '-m', 'pytest', test_file, '-v', '--tb=short'],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.workspace_root or None
            )
            
            result['output'] = proc.stdout + proc.stderr
            result['passed'] = proc.returncode == 0
            
            # 解析测试结果
            for line in proc.stdout.split('\n'):
                if ' passed' in line:
                    try:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == 'passed':
                                result['passed_count'] = int(parts[i-1])
                            elif part == 'failed':
                                result['failed_count'] = int(parts[i-1])
                    except (ValueError, IndexError):
                        pass
            
            result['total'] = result['passed_count'] + result['failed_count']
            
        except subprocess.TimeoutExpired:
            result['errors'].append("Test execution timed out")
        except Exception as e:
            result['errors'].append(str(e))
        
        return result
    
    def run_code(self, code: str, timeout: int = 10) -> Dict[str, Any]:
        """运行代码并捕获输出"""
        result = {
            'success': False,
            'output': '',
            'error': '',
            'return_code': -1
        }
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_path = f.name
            
            proc = subprocess.run(
                ['python3', temp_path],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            result['success'] = proc.returncode == 0
            result['output'] = proc.stdout
            result['error'] = proc.stderr
            result['return_code'] = proc.returncode
            
            os.unlink(temp_path)
            
        except subprocess.TimeoutExpired:
            result['error'] = "Code execution timed out"
        except Exception as e:
            result['error'] = str(e)
        
        return result


class AutonomousCodingEngineV2:
    """自主编程引擎 V2"""
    
    def __init__(
        self,
        workspace_root: str = "",
        llm_config: Optional[LLMConfig] = None
    ):
        self.workspace_root = workspace_root or os.getcwd()
        
        # 初始化 LLM 代码生成器
        self.llm_generator = LLMCodeGenerator(llm_config)
        
        # 初始化分析器和测试运行器
        self.analyzer = CodeAnalyzer()
        self.test_runner = TestRunner(workspace_root)
        
        # 编程历史
        self.history: List[Dict[str, Any]] = []
    
    async def execute_task(self, context: CodingContext) -> CodingResult:
        """执行编程任务"""
        logger.info(f"Executing coding task: {context.task_type.value}")
        
        result = CodingResult(success=False)
        
        try:
            # 1. 读取现有代码
            if not context.existing_code:
                context.existing_code = self._read_existing_code(context.target_files)
            
            # 2. 生成代码
            gen_result = await self._generate_code(context)
            
            if not gen_result.success:
                result.errors.append(f"Code generation failed: {gen_result.error}")
                return result
            
            result.code_changes = gen_result.code_changes
            result.explanation = gen_result.explanation
            
            # 3. 分析生成的代码
            for file_path, code in result.code_changes.items():
                syntax_ok, syntax_errors = self.analyzer.analyze_syntax(code, file_path)
                
                if not syntax_ok:
                    result.errors.extend(syntax_errors)
                    continue
                
                style_warnings = self.analyzer.analyze_style(code, file_path)
                security_issues = self.analyzer.analyze_security(code, file_path)
                
                result.warnings.extend(style_warnings)
                result.warnings.extend(security_issues)
                
                quality = self.analyzer.calculate_quality_score(
                    syntax_ok, style_warnings, security_issues
                )
                result.quality_score = max(result.quality_score, quality)
            
            # 4. 如果有语法错误，尝试修复
            if result.errors:
                logger.info("Attempting to fix syntax errors...")
                fixed_result = await self._fix_errors(context, result)
                if fixed_result.success:
                    result = fixed_result
            
            # 5. 运行测试（如果是测试任务或有测试文件）
            if context.task_type == CodingTaskType.TEST:
                for file_path in result.code_changes:
                    if '_test.py' in file_path or 'test_' in file_path:
                        # 先保存测试文件
                        self._save_code(file_path, result.code_changes[file_path])
                        test_result = self.test_runner.run_tests(file_path)
                        result.test_results[file_path] = test_result
            
            # 6. 记录历史
            self._record_history(context, result)
            
            result.success = len(result.errors) == 0
            
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            result.errors.append(str(e))
        
        return result
    
    async def _generate_code(self, context: CodingContext) -> CodeGenerationResult:
        """生成代码"""
        # 根据任务类型调用不同的生成方法
        if context.task_type == CodingTaskType.BUG_FIX:
            if context.target_files and context.existing_code:
                file_path = context.target_files[0]
                code = context.existing_code.get(file_path, "")
                return await self.llm_generator.generate_bug_fix(
                    context.description, file_path, code
                )
        
        elif context.task_type == CodingTaskType.FEATURE:
            return await self.llm_generator.generate_feature(
                context.description,
                context.target_files,
                context.existing_code
            )
        
        elif context.task_type == CodingTaskType.TEST:
            if context.target_files and context.existing_code:
                file_path = context.target_files[0]
                code = context.existing_code.get(file_path, "")
                return await self.llm_generator.generate_tests(file_path, code)
        
        elif context.task_type == CodingTaskType.OPTIMIZE:
            if context.target_files and context.existing_code:
                file_path = context.target_files[0]
                code = context.existing_code.get(file_path, "")
                return await self.llm_generator.optimize_code(
                    file_path, code, context.constraints
                )
        
        elif context.task_type == CodingTaskType.REFACTOR:
            if context.target_files and context.existing_code:
                file_path = context.target_files[0]
                code = context.existing_code.get(file_path, "")
                return await self.llm_generator.refactor_code(file_path, code)
        
        elif context.task_type == CodingTaskType.DOCUMENT:
            if context.target_files and context.existing_code:
                file_path = context.target_files[0]
                code = context.existing_code.get(file_path, "")
                return await self.llm_generator.generate_documentation(file_path, code)
        
        # 默认：通用代码生成
        request = CodeGenerationRequest(
            task_type=context.task_type.value,
            description=context.description,
            target_files=context.target_files,
            context_code=context.existing_code,
            language=context.language,
            constraints=context.constraints
        )
        return await self.llm_generator.client.generate_code(request)
    
    async def _fix_errors(self, context: CodingContext, result: CodingResult) -> CodingResult:
        """尝试修复错误"""
        fix_context = CodingContext(
            task_type=CodingTaskType.BUG_FIX,
            description=f"Fix the following errors:\n" + "\n".join(result.errors),
            target_files=list(result.code_changes.keys()),
            existing_code=result.code_changes,
            language=context.language
        )
        
        return await self.execute_task(fix_context)
    
    def _read_existing_code(self, target_files: List[str]) -> Dict[str, str]:
        """读取现有代码"""
        code = {}
        for file_path in target_files:
            full_path = os.path.join(self.workspace_root, file_path)
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r') as f:
                        code[file_path] = f.read()
                except Exception as e:
                    logger.warning(f"Failed to read {file_path}: {e}")
        return code
    
    def _save_code(self, file_path: str, code: str):
        """保存代码到文件"""
        full_path = os.path.join(self.workspace_root, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(code)
    
    def _record_history(self, context: CodingContext, result: CodingResult):
        """记录编程历史"""
        self.history.append({
            'timestamp': datetime.now().isoformat(),
            'task_type': context.task_type.value,
            'description': context.description,
            'target_files': context.target_files,
            'success': result.success,
            'quality_score': result.quality_score,
            'errors_count': len(result.errors),
            'warnings_count': len(result.warnings)
        })
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        if not self.history:
            return {'total_tasks': 0}
        
        success_count = sum(1 for h in self.history if h['success'])
        
        return {
            'total_tasks': len(self.history),
            'success_count': success_count,
            'success_rate': success_count / len(self.history),
            'avg_quality_score': sum(h['quality_score'] for h in self.history) / len(self.history),
            'by_task_type': self._group_by_task_type()
        }
    
    def _group_by_task_type(self) -> Dict[str, int]:
        """按任务类型分组统计"""
        counts = {}
        for h in self.history:
            task_type = h['task_type']
            counts[task_type] = counts.get(task_type, 0) + 1
        return counts


# 测试代码
async def test_autonomous_coding_engine_v2():
    """测试自主编程引擎 V2"""
    print("=== 测试自主编程引擎 V2 ===")
    
    engine = AutonomousCodingEngineV2(
        workspace_root='/tmp/test_coding'
    )
    
    # 测试代码分析器
    print("\n--- 测试代码分析器 ---")
    print(f"Available tools: {engine.analyzer.available_tools}")
    
    test_code = """
def hello(name):
    print(f"Hello, {name}!")
    return True

if __name__ == "__main__":
    hello("World")
"""
    
    syntax_ok, errors = engine.analyzer.analyze_syntax(test_code)
    print(f"Syntax OK: {syntax_ok}")
    
    style_warnings = engine.analyzer.analyze_style(test_code)
    print(f"Style warnings: {len(style_warnings)}")
    
    quality = engine.analyzer.calculate_quality_score(syntax_ok, style_warnings, [])
    print(f"Quality score: {quality}")
    
    # 测试代码运行
    print("\n--- 测试代码运行 ---")
    run_result = engine.test_runner.run_code(test_code)
    print(f"Run success: {run_result['success']}")
    print(f"Output: {run_result['output']}")
    
    print("\n✅ 自主编程引擎 V2 测试完成")
    print("注意：完整的代码生成功能需要配置有效的 LLM API Key")


if __name__ == "__main__":
    asyncio.run(test_autonomous_coding_engine_v2())
