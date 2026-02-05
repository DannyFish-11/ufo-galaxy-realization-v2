"""
自主编程器 (Autonomous Coder)
根据需求自动生成代码、测试、修复并部署
"""

import os
import subprocess
import tempfile
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class CodingStep(Enum):
    """编程步骤"""
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    DESIGN = "design"
    CODE_GENERATION = "code_generation"
    TESTING = "testing"
    DEBUGGING = "debugging"
    DEPLOYMENT = "deployment"


@dataclass
class CodingTask:
    """编程任务"""
    requirement: str
    language: str
    target_type: str  # 'script', 'module', 'node', 'service'
    constraints: List[str]
    expected_output: Optional[str]


@dataclass
class CodingResult:
    """编程结果"""
    success: bool
    code: str
    file_path: Optional[str]
    test_output: Optional[str]
    errors: List[str]
    node_id: Optional[str]


class AutonomousCoder:
    """自主编程器"""
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.sandbox_dir = tempfile.mkdtemp(prefix='galaxy_coder_')
        logger.info(f"AutonomousCoder initialized with sandbox: {self.sandbox_dir}")
    
    def generate_and_execute(self, task: CodingTask) -> CodingResult:
        """生成并执行代码"""
        logger.info(f"开始处理编程任务: {task.requirement}")
        
        try:
            # 1. 需求分析
            analysis = self._analyze_requirement(task)
            logger.info(f"需求分析完成: {analysis}")
            
            # 2. 规划编程步骤
            steps = self._plan_coding_steps(task, analysis)
            logger.info(f"规划了 {len(steps)} 个编程步骤")
            
            # 3. 生成代码
            code = self._generate_code_with_llm(task, analysis, steps)
            logger.info(f"代码生成完成: {len(code)} 字符")
            
            # 4. 在沙箱中执行
            test_output, errors = self._execute_in_sandbox(code, task.language)
            
            # 5. 如果有错误，尝试自我修正
            if errors:
                logger.warning(f"发现 {len(errors)} 个错误，尝试自我修正...")
                code, test_output, errors = self._self_correct(code, errors, task)
            
            # 6. 部署为节点（如果需要）
            node_id = None
            file_path = None
            if task.target_type == 'node' and not errors:
                node_id, file_path = self._deploy_as_node(code, task)
                logger.info(f"部署为节点: {node_id}")
            else:
                # 保存到临时文件
                file_path = self._save_to_file(code, task.language)
            
            return CodingResult(
                success=len(errors) == 0,
                code=code,
                file_path=file_path,
                test_output=test_output,
                errors=errors,
                node_id=node_id
            )
        
        except Exception as e:
            logger.error(f"编程任务失败: {e}")
            return CodingResult(
                success=False,
                code="",
                file_path=None,
                test_output=None,
                errors=[str(e)],
                node_id=None
            )
    
    def _analyze_requirement(self, task: CodingTask) -> Dict:
        """分析需求"""
        analysis = {
            'inputs': [],
            'outputs': [],
            'dependencies': [],
            'complexity': 'medium',
        }
        
        # 简单的关键词分析
        requirement_lower = task.requirement.lower()
        
        # 识别输入输出
        if 'file' in requirement_lower or '文件' in requirement_lower:
            analysis['inputs'].append('file_path')
            analysis['outputs'].append('file_content')
        
        if 'api' in requirement_lower or 'http' in requirement_lower:
            analysis['dependencies'].append('requests')
        
        if 'json' in requirement_lower:
            analysis['dependencies'].append('json')
        
        return analysis
    
    def _plan_coding_steps(self, task: CodingTask, analysis: Dict) -> List[str]:
        """规划编程步骤"""
        steps = [
            "导入必要的库",
            "定义主函数",
            "实现核心逻辑",
            "添加错误处理",
            "测试代码",
        ]
        
        return steps
    
    def _generate_code_with_llm(self, task: CodingTask, analysis: Dict, steps: List[str]) -> str:
        """使用 LLM 生成代码"""
        # 如果没有 LLM 客户端，使用模板生成
        if not self.llm_client:
            return self._generate_code_from_template(task, analysis)
        
        # 构建 LLM 提示
        prompt = f"""
你是一个专业的程序员。请根据以下需求生成 {task.language} 代码：

需求：{task.requirement}

分析：
- 输入：{', '.join(analysis['inputs'])}
- 输出：{', '.join(analysis['outputs'])}
- 依赖：{', '.join(analysis['dependencies'])}

约束：
{chr(10).join(f'- {c}' for c in task.constraints)}

请生成完整的、可运行的代码。
"""
        
        try:
            # 调用 LLM
            response = self.llm_client.generate(prompt)
            return response
        except Exception as e:
            logger.warning(f"LLM 生成失败: {e}，使用模板生成")
            return self._generate_code_from_template(task, analysis)
    
    def _generate_code_from_template(self, task: CodingTask, analysis: Dict) -> str:
        """从模板生成代码"""
        if task.language == 'python':
            return self._generate_python_template(task, analysis)
        else:
            return f"# TODO: Implement {task.requirement}\n"
    
    def _generate_python_template(self, task: CodingTask, analysis: Dict) -> str:
        """生成 Python 模板代码"""
        imports = []
        if 'requests' in analysis['dependencies']:
            imports.append("import requests")
        if 'json' in analysis['dependencies']:
            imports.append("import json")
        
        imports_str = '\n'.join(imports) if imports else "# No external dependencies"
        
        code = f"""#!/usr/bin/env python3
\"\"\"
{task.requirement}
\"\"\"

{imports_str}


def main():
    \"\"\"主函数\"\"\"
    try:
        # TODO: 实现核心逻辑
        print("执行任务: {task.requirement}")
        
        # 示例：处理输入
        # result = process_input()
        
        # 示例：返回输出
        return True
    
    except Exception as e:
        print(f"错误: {{e}}")
        return False


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
"""
        return code
    
    def _execute_in_sandbox(self, code: str, language: str) -> Tuple[str, List[str]]:
        """在沙箱中执行代码"""
        if language == 'python':
            return self._execute_python_in_sandbox(code)
        else:
            return "", [f"不支持的语言: {language}"]
    
    def _execute_python_in_sandbox(self, code: str) -> Tuple[str, List[str]]:
        """在沙箱中执行 Python 代码"""
        # 保存代码到临时文件
        temp_file = os.path.join(self.sandbox_dir, 'temp_script.py')
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        # 执行代码
        try:
            result = subprocess.run(
                ['python3', temp_file],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.sandbox_dir
            )
            
            output = result.stdout + result.stderr
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
    
    def _self_correct(self, code: str, errors: List[str], task: CodingTask) -> Tuple[str, str, List[str]]:
        """自我修正代码"""
        max_attempts = 3
        
        for attempt in range(max_attempts):
            logger.info(f"自我修正尝试 {attempt + 1}/{max_attempts}")
            
            # 简单的错误修正策略
            if "ModuleNotFoundError" in ' '.join(errors):
                # 尝试安装缺失的模块
                for error in errors:
                    if "No module named" in error:
                        module_name = error.split("'")[1]
                        logger.info(f"尝试安装模块: {module_name}")
                        try:
                            subprocess.run(
                                ['pip3', 'install', module_name],
                                capture_output=True,
                                timeout=60
                            )
                        except Exception:
                            pass
            
            # 重新执行
            test_output, new_errors = self._execute_in_sandbox(code, task.language)
            
            if not new_errors:
                logger.info("自我修正成功")
                return code, test_output, []
            
            errors = new_errors
        
        logger.warning("自我修正失败")
        return code, test_output, errors
    
    def _deploy_as_node(self, code: str, task: CodingTask) -> Tuple[str, str]:
        """部署为节点"""
        # 找到下一个可用的节点 ID
        nodes_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'nodes')
        existing_nodes = [d for d in os.listdir(nodes_dir) if d.startswith('Node_')]
        node_numbers = [int(n.split('_')[1]) for n in existing_nodes if n.split('_')[1].isdigit()]
        next_node_id = max(node_numbers) + 1 if node_numbers else 119
        
        node_name = f"Node_{next_node_id}_AutoGenerated"
        node_dir = os.path.join(nodes_dir, node_name)
        os.makedirs(node_dir, exist_ok=True)
        
        # 保存代码
        main_file = os.path.join(node_dir, 'main.py')
        with open(main_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        # 创建配置文件
        config_file = os.path.join(node_dir, 'config.json')
        config = {
            "node_id": next_node_id,
            "name": node_name,
            "description": task.requirement,
            "auto_generated": True
        }
        
        import json
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


if __name__ == '__main__':
    # 测试自主编程器
    logging.basicConfig(level=logging.INFO)
    
    coder = AutonomousCoder()
    
    task = CodingTask(
        requirement="创建一个读取 JSON 文件并打印内容的脚本",
        language="python",
        target_type="script",
        constraints=["使用标准库", "添加错误处理"],
        expected_output="JSON 内容"
    )
    
    result = coder.generate_and_execute(task)
    
    print(f"\n编程结果:")
    print(f"  成功: {result.success}")
    print(f"  文件: {result.file_path}")
    if result.test_output:
        print(f"  输出: {result.test_output}")
    if result.errors:
        print(f"  错误: {result.errors}")
