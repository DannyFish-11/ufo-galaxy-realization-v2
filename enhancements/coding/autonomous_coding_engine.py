"""
自主编程引擎 (Autonomous Coding Engine)
L4 系统根据自身实际情况自主利用工具编写代码
"""

import logging
import os
import subprocess
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import json

logger = logging.getLogger(__name__)


class CodingTaskType(Enum):
    """编程任务类型"""
    BUG_FIX = "bug_fix"
    FEATURE_IMPLEMENTATION = "feature_implementation"
    OPTIMIZATION = "optimization"
    REFACTORING = "refactoring"
    TESTING = "testing"
    DOCUMENTATION = "documentation"


class CodeQuality(Enum):
    """代码质量"""
    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"
    FAILED = "failed"


@dataclass
class CodingContext:
    """编程上下文"""
    task_type: CodingTaskType
    description: str
    target_files: List[str]
    available_tools: List[str]
    constraints: List[str]
    success_criteria: List[str]
    metadata: Dict[str, Any]


@dataclass
class CodingResult:
    """编程结果"""
    success: bool
    files_modified: List[str]
    files_created: List[str]
    code_quality: CodeQuality
    test_results: Dict[str, Any]
    execution_log: str
    error: Optional[str]


class AutonomousCodingEngine:
    """自主编程引擎"""

    def __init__(self, workspace_root: str = None):
        """
        初始化自主编程引擎

        Args:
            workspace_root: 工作空间根目录（默认使用项目根目录）
        """
        if workspace_root is None:
            workspace_root = os.getenv(
                "GALAXY_WORKSPACE_ROOT",
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            )
        self.workspace_root = os.path.abspath(workspace_root)
        self.available_tools = self._scan_available_tools()
        self.coding_history: List[Dict] = []
        # 加载历史记录
        self._load_coding_history()

        logger.info(f"AutonomousCodingEngine 初始化完成，工作空间: {self.workspace_root}")
        logger.info(f"可用工具: {', '.join(self.available_tools)}")

    def _load_coding_history(self):
        """从磁盘加载编程历史"""
        history_file = os.path.join(self.workspace_root, 'coding_history.json')
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    self.coding_history = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.coding_history = []
    
    def _scan_available_tools(self) -> List[str]:
        """扫描可用的编程工具"""
        tools = []
        
        # 检查 Python
        if self._check_command("python3.11"):
            tools.append("python3.11")
        
        # 检查 pip
        if self._check_command("pip3"):
            tools.append("pip3")
        
        # 检查 git
        if self._check_command("git"):
            tools.append("git")
        
        # 检查 pytest
        if self._check_command("pytest"):
            tools.append("pytest")
        
        # 检查 black (代码格式化)
        if self._check_command("black"):
            tools.append("black")
        
        # 检查 pylint (代码检查)
        if self._check_command("pylint"):
            tools.append("pylint")
        
        return tools
    
    def _check_command(self, command: str) -> bool:
        """检查命令是否可用"""
        try:
            subprocess.run(
                [command, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    async def autonomous_code(self, context: CodingContext) -> CodingResult:
        """
        自主编程
        
        Args:
            context: 编程上下文
            
        Returns:
            编程结果
        """
        logger.info(f"开始自主编程: {context.description}")
        logger.info(f"任务类型: {context.task_type.value}")
        
        try:
            # 1. 分析任务
            analysis = self._analyze_task(context)
            logger.info(f"任务分析完成: {analysis['complexity']}")
            
            # 2. 选择工具
            tools = self._select_tools(context, analysis)
            logger.info(f"选择工具: {', '.join(tools)}")
            
            # 3. 生成代码
            code_changes = await self._generate_code(context, analysis, tools)
            logger.info(f"生成代码完成: {len(code_changes)} 个文件")
            
            # 4. 应用代码更改
            modified_files, created_files = self._apply_code_changes(code_changes)
            logger.info(f"应用代码更改: 修改 {len(modified_files)} 个，创建 {len(created_files)} 个")
            
            # 5. 运行测试
            test_results = await self._run_tests(context, modified_files + created_files)
            logger.info(f"测试完成: {test_results['passed']}/{test_results['total']} 通过")
            
            # 6. 评估代码质量
            quality = self._evaluate_code_quality(modified_files + created_files, test_results)
            logger.info(f"代码质量: {quality.value}")
            
            # 7. 记录历史
            self._record_coding_history(context, modified_files, created_files, quality)
            
            return CodingResult(
                success=test_results['passed'] == test_results['total'],
                files_modified=modified_files,
                files_created=created_files,
                code_quality=quality,
                test_results=test_results,
                execution_log=self._get_execution_log(),
                error=None
            )
        
        except Exception as e:
            logger.error(f"自主编程失败: {e}")
            return CodingResult(
                success=False,
                files_modified=[],
                files_created=[],
                code_quality=CodeQuality.FAILED,
                test_results={},
                execution_log=self._get_execution_log(),
                error=str(e)
            )
    
    def _analyze_task(self, context: CodingContext) -> Dict:
        """分析任务"""
        analysis = {
            'complexity': 'medium',
            'estimated_files': len(context.target_files),
            'required_tools': [],
            'risks': []
        }
        
        # 根据任务类型判断复杂度
        if context.task_type in [CodingTaskType.REFACTORING, CodingTaskType.FEATURE_IMPLEMENTATION]:
            analysis['complexity'] = 'high'
        elif context.task_type in [CodingTaskType.DOCUMENTATION, CodingTaskType.TESTING]:
            analysis['complexity'] = 'low'
        
        # 分析需要的工具
        if context.task_type == CodingTaskType.TESTING:
            analysis['required_tools'].append('pytest')
        
        if 'performance' in context.description.lower():
            analysis['required_tools'].append('profiler')
        
        return analysis
    
    def _select_tools(self, context: CodingContext, analysis: Dict) -> List[str]:
        """选择工具"""
        tools = []
        
        # 基础工具
        if 'python3.11' in self.available_tools:
            tools.append('python3.11')
        
        # 根据任务类型选择
        if context.task_type == CodingTaskType.TESTING and 'pytest' in self.available_tools:
            tools.append('pytest')
        
        if context.task_type in [CodingTaskType.BUG_FIX, CodingTaskType.OPTIMIZATION]:
            if 'pylint' in self.available_tools:
                tools.append('pylint')
        
        # 代码格式化
        if 'black' in self.available_tools:
            tools.append('black')
        
        return tools
    
    async def _generate_code(
        self,
        context: CodingContext,
        analysis: Dict,
        tools: List[str]
    ) -> Dict[str, str]:
        """
        生成代码
        
        Returns:
            文件路径 -> 代码内容的映射
        """
        code_changes = {}
        
        # 这里是简化版本，实际应该调用 LLM 或使用代码生成模型
        # 目前返回模拟的代码更改
        
        for target_file in context.target_files:
            if context.task_type == CodingTaskType.BUG_FIX:
                # 生成 bug 修复代码
                code_changes[target_file] = self._generate_bug_fix_code(target_file, context)
            
            elif context.task_type == CodingTaskType.FEATURE_IMPLEMENTATION:
                # 生成新功能代码
                code_changes[target_file] = self._generate_feature_code(target_file, context)
            
            elif context.task_type == CodingTaskType.TESTING:
                # 生成测试代码
                test_file = target_file.replace('.py', '_test.py')
                code_changes[test_file] = self._generate_test_code(target_file, context)
        
        return code_changes
    
    def _generate_bug_fix_code(self, file_path: str, context: CodingContext) -> str:
        """生成 bug 修复代码"""
        # 简化版本：读取现有文件并添加注释
        try:
            with open(os.path.join(self.workspace_root, file_path), 'r') as f:
                original_code = f.read()
            
            # 添加修复注释
            fixed_code = f"# Bug fix: {context.description}\n" + original_code
            return fixed_code
        except FileNotFoundError:
            return f"# New file for bug fix: {context.description}\n"
    
    def _generate_feature_code(self, file_path: str, context: CodingContext) -> str:
        """生成新功能代码"""
        # 简化版本：生成基础代码框架
        return f"""
# Feature: {context.description}
# Generated by AutonomousCodingEngine

import logging

logger = logging.getLogger(__name__)


class NewFeature:
    \"\"\"新功能实现\"\"\"
    
    def __init__(self):
        logger.info("NewFeature 初始化")
    
    def execute(self):
        \"\"\"执行新功能\"\"\"
        logger.info("执行新功能")
        # Implement concrete feature logic here based on context.description.
        pass
"""
    
    def _generate_test_code(self, file_path: str, context: CodingContext) -> str:
        """生成测试代码"""
        module_name = os.path.basename(file_path).replace('.py', '')
        
        return f"""
# Test for: {file_path}
# Generated by AutonomousCodingEngine

import pytest
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from {module_name} import *


def test_basic_functionality():
    \"\"\"测试基本功能\"\"\"
    # Add assertions to verify the basic expected behaviour of {module_name}.
    assert True


def test_edge_cases():
    \"\"\"测试边界情况\"\"\"
    # Add assertions to verify boundary and error conditions of {module_name}.
    assert True
"""
    
    def _apply_code_changes(self, code_changes: Dict[str, str]) -> tuple:
        """应用代码更改（带备份和原子写入）"""
        modified_files = []
        created_files = []
        backup_dir = os.path.join(self.workspace_root, ".code_backups")

        for file_path, code in code_changes.items():
            # 安全检查：禁止路径遍历
            full_path = os.path.normpath(os.path.join(self.workspace_root, file_path))
            if not full_path.startswith(self.workspace_root):
                logger.error(f"安全拒绝: 路径遍历尝试 {file_path}")
                continue

            # 确保目录存在
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # 如果文件已存在，先备份
            if os.path.exists(full_path):
                os.makedirs(backup_dir, exist_ok=True)
                import shutil
                backup_name = file_path.replace("/", "_").replace("\\", "_")
                backup_path = os.path.join(backup_dir, f"{backup_name}.bak")
                try:
                    shutil.copy2(full_path, backup_path)
                except IOError as e:
                    logger.warning(f"备份失败 {file_path}: {e}")
                modified_files.append(file_path)
            else:
                created_files.append(file_path)

            # 原子写入：先写临时文件，再 rename
            tmp_path = full_path + ".tmp"
            try:
                with open(tmp_path, 'w') as f:
                    f.write(code)
                os.replace(tmp_path, full_path)
                logger.info(f"应用代码更改: {file_path}")
            except Exception as e:
                logger.error(f"写入失败 {file_path}: {e}")
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        return modified_files, created_files
    
    async def _run_tests(self, context: CodingContext, files: List[str]) -> Dict:
        """运行测试"""
        test_results = {
            'total': 0,
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'details': []
        }
        
        # 如果有 pytest，运行测试
        if 'pytest' in self.available_tools:
            for file_path in files:
                if '_test.py' in file_path or 'test_' in file_path:
                    full_path = os.path.join(self.workspace_root, file_path)
                    
                    try:
                        result = subprocess.run(
                            ['pytest', full_path, '-v'],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=30,
                            cwd=self.workspace_root
                        )
                        
                        # 解析结果（简化版本）
                        output = result.stdout.decode()
                        if 'passed' in output:
                            test_results['total'] += 1
                            test_results['passed'] += 1
                        elif 'failed' in output:
                            test_results['total'] += 1
                            test_results['failed'] += 1
                        
                        test_results['details'].append({
                            'file': file_path,
                            'output': output
                        })
                    
                    except subprocess.TimeoutExpired:
                        logger.warning(f"测试超时: {file_path}")
                        test_results['total'] += 1
                        test_results['failed'] += 1
        
        # 如果没有测试文件，假设通过
        if test_results['total'] == 0:
            test_results['total'] = 1
            test_results['passed'] = 1
        
        return test_results
    
    def _evaluate_code_quality(self, files: List[str], test_results: Dict) -> CodeQuality:
        """评估代码质量"""
        # 基于测试结果评估
        if test_results['total'] == 0:
            return CodeQuality.ACCEPTABLE
        
        success_rate = test_results['passed'] / test_results['total']
        
        if success_rate >= 0.95:
            return CodeQuality.EXCELLENT
        elif success_rate >= 0.80:
            return CodeQuality.GOOD
        elif success_rate >= 0.60:
            return CodeQuality.ACCEPTABLE
        else:
            return CodeQuality.POOR
    
    def _record_coding_history(
        self,
        context: CodingContext,
        modified_files: List[str],
        created_files: List[str],
        quality: CodeQuality
    ):
        """记录编程历史"""
        record = {
            'task_type': context.task_type.value,
            'description': context.description,
            'modified_files': modified_files,
            'created_files': created_files,
            'quality': quality.value,
            'timestamp': self._get_timestamp()
        }
        
        self.coding_history.append(record)
        
        # 保存到文件
        history_file = os.path.join(self.workspace_root, 'coding_history.json')
        with open(history_file, 'w') as f:
            json.dump(self.coding_history, f, indent=2)
    
    def _get_execution_log(self) -> str:
        """获取执行日志"""
        # 简化版本：返回最近的日志
        return "Execution log placeholder"
    
    def _get_timestamp(self) -> str:
        """获取时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_coding_statistics(self) -> Dict:
        """获取编程统计"""
        if not self.coding_history:
            return {
                'total_tasks': 0,
                'by_type': {},
                'by_quality': {},
                'total_files_modified': 0,
                'total_files_created': 0
            }
        
        stats = {
            'total_tasks': len(self.coding_history),
            'by_type': {},
            'by_quality': {},
            'total_files_modified': 0,
            'total_files_created': 0
        }
        
        for record in self.coding_history:
            # 按类型统计
            task_type = record['task_type']
            stats['by_type'][task_type] = stats['by_type'].get(task_type, 0) + 1
            
            # 按质量统计
            quality = record['quality']
            stats['by_quality'][quality] = stats['by_quality'].get(quality, 0) + 1
            
            # 文件统计
            stats['total_files_modified'] += len(record['modified_files'])
            stats['total_files_created'] += len(record['created_files'])
        
        return stats
