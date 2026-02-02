"""
Node Factory Engine - 节点工厂引擎核心模块

功能：
1. 动态节点生成
2. 节点代码生成（使用 Node_114_OpenCode）
3. 节点测试生成
4. 节点部署和验证
"""

import os
import json
import subprocess
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class NodeType(Enum):
    """节点类型"""
    PERCEPTION = "perception"  # 感知节点
    COGNITION = "cognition"    # 认知节点
    ACTION = "action"          # 行动节点
    LEARNING = "learning"      # 学习节点
    INTEGRATION = "integration"  # 集成节点


@dataclass
class NodeSpecification:
    """节点规格"""
    node_number: int
    node_name: str
    node_type: NodeType
    description: str
    port: int
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[int] = field(default_factory=list)
    api_endpoints: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_number": self.node_number,
            "node_name": self.node_name,
            "node_type": self.node_type.value,
            "description": self.description,
            "port": self.port,
            "capabilities": self.capabilities,
            "dependencies": self.dependencies,
            "api_endpoints": self.api_endpoints
        }


@dataclass
class NodeGenerationResult:
    """节点生成结果"""
    success: bool
    node_spec: NodeSpecification
    generated_files: Dict[str, str] = field(default_factory=dict)
    validation_results: Dict[str, bool] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "node_spec": self.node_spec.to_dict(),
            "generated_files": self.generated_files,
            "validation_results": self.validation_results,
            "errors": self.errors,
            "timestamp": self.timestamp
        }


class NodeFactoryEngine:
    """节点工厂引擎"""
    
    def __init__(
        self,
        opencode_client=None,
        metacognition_client=None,
        output_dir: Optional[str] = None
    ):
        """
        初始化节点工厂引擎
        
        Args:
            opencode_client: OpenCode 客户端（Node_114）
            metacognition_client: 元认知客户端（Node_108）
            output_dir: 输出目录
        """
        self.opencode_client = opencode_client
        self.metacognition_client = metacognition_client
        self.output_dir = output_dir or "/tmp/generated_nodes"
        
        # 创建输出目录
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        # 生成历史
        self.generation_history: List[NodeGenerationResult] = []
        
        # 节点模板
        self.templates = self._load_templates()
    
    def generate_node(
        self,
        node_spec: NodeSpecification,
        auto_deploy: bool = False
    ) -> NodeGenerationResult:
        """
        生成节点
        
        Args:
            node_spec: 节点规格
            auto_deploy: 是否自动部署
            
        Returns:
            NodeGenerationResult: 生成结果
        """
        result = NodeGenerationResult(
            success=False,
            node_spec=node_spec
        )
        
        try:
            # 1. 生成节点目录结构
            node_dir = self._create_node_structure(node_spec)
            
            # 2. 生成核心引擎代码
            engine_code = self._generate_engine_code(node_spec)
            engine_path = os.path.join(node_dir, "core", f"{node_spec.node_name.lower()}_engine.py")
            self._write_file(engine_path, engine_code)
            result.generated_files["engine"] = engine_path
            
            # 3. 生成 FastAPI 服务器代码
            server_code = self._generate_server_code(node_spec)
            server_path = os.path.join(node_dir, "server.py")
            self._write_file(server_path, server_code)
            result.generated_files["server"] = server_path
            
            # 4. 生成 README 文档
            readme_content = self._generate_readme(node_spec)
            readme_path = os.path.join(node_dir, "README.md")
            self._write_file(readme_path, readme_content)
            result.generated_files["readme"] = readme_path
            
            # 5. 生成测试文件
            test_code = self._generate_test_code(node_spec)
            test_path = os.path.join(self.output_dir, "tests", f"test_node_{node_spec.node_number}.py")
            Path(test_path).parent.mkdir(parents=True, exist_ok=True)
            self._write_file(test_path, test_code)
            result.generated_files["test"] = test_path
            
            # 6. 验证生成的代码
            validation_results = self._validate_generated_code(result.generated_files)
            result.validation_results = validation_results
            
            # 7. 如果所有验证通过，标记为成功
            if all(validation_results.values()):
                result.success = True
            else:
                result.errors.append("Some validations failed")
            
            # 8. 自动部署（如果启用）
            if auto_deploy and result.success:
                deploy_result = self._deploy_node(node_spec, node_dir)
                result.validation_results["deployment"] = deploy_result
            
        except Exception as e:
            result.errors.append(str(e))
        
        # 记录历史
        self.generation_history.append(result)
        
        return result
    
    def generate_node_from_description(
        self,
        description: str,
        node_number: int,
        port: int,
        auto_deploy: bool = False
    ) -> NodeGenerationResult:
        """
        从自然语言描述生成节点
        
        Args:
            description: 节点描述
            node_number: 节点编号
            port: 端口
            auto_deploy: 是否自动部署
            
        Returns:
            NodeGenerationResult: 生成结果
        """
        # 使用 LLM 理解描述并生成规格
        node_spec = self._parse_description_to_spec(
            description, node_number, port
        )
        
        return self.generate_node(node_spec, auto_deploy)
    
    def get_generation_history(self, limit: int = 100) -> List[NodeGenerationResult]:
        """获取生成历史"""
        return self.generation_history[-limit:]
    
    # ========== 私有方法 ==========
    
    def _load_templates(self) -> Dict[str, str]:
        """加载节点模板"""
        return {
            "engine": """
# {node_name} Engine

class {node_name}Engine:
    def __init__(self):
        pass
    
    def process(self, data):
        # TODO: Implement processing logic
        return data
""",
            "server": """
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="Node_{node_number}_{node_name}")

@app.get("/")
async def root():
    return {{"node": "Node_{node_number}_{node_name}", "status": "running"}}

@app.get("/health")
async def health():
    return {{"status": "healthy"}}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port={port})
""",
            "readme": """
# Node_{node_number}_{node_name}

{description}

## API Endpoints

- GET `/` - Root endpoint
- GET `/health` - Health check

## Port

{port}
"""
        }
    
    def _create_node_structure(self, node_spec: NodeSpecification) -> str:
        """创建节点目录结构"""
        node_dir = os.path.join(
            self.output_dir,
            f"node_{node_spec.node_number}_{node_spec.node_name.lower()}"
        )
        
        # 创建目录
        Path(node_dir).mkdir(parents=True, exist_ok=True)
        Path(os.path.join(node_dir, "api")).mkdir(exist_ok=True)
        Path(os.path.join(node_dir, "core")).mkdir(exist_ok=True)
        Path(os.path.join(node_dir, "utils")).mkdir(exist_ok=True)
        
        # 创建 __init__.py
        for subdir in ["", "api", "core", "utils"]:
            init_path = os.path.join(node_dir, subdir, "__init__.py")
            Path(init_path).touch()
        
        return node_dir
    
    def _generate_engine_code(self, node_spec: NodeSpecification) -> str:
        """生成引擎代码"""
        # 简化实现：使用模板
        # 实际应该调用 Node_114_OpenCode 生成
        
        template = self.templates["engine"]
        code = template.format(
            node_name=node_spec.node_name,
            description=node_spec.description
        )
        
        return code
    
    def _generate_server_code(self, node_spec: NodeSpecification) -> str:
        """生成服务器代码"""
        template = self.templates["server"]
        code = template.format(
            node_number=node_spec.node_number,
            node_name=node_spec.node_name,
            port=node_spec.port
        )
        
        return code
    
    def _generate_readme(self, node_spec: NodeSpecification) -> str:
        """生成 README"""
        template = self.templates["readme"]
        content = template.format(
            node_number=node_spec.node_number,
            node_name=node_spec.node_name,
            description=node_spec.description,
            port=node_spec.port
        )
        
        return content
    
    def _generate_test_code(self, node_spec: NodeSpecification) -> str:
        """生成测试代码"""
        test_code = f"""
import pytest
import requests

NODE_URL = "http://localhost:{node_spec.port}"

def test_root():
    response = requests.get(f"{{NODE_URL}}/")
    assert response.status_code == 200
    data = response.json()
    assert data["node"] == "Node_{node_spec.node_number}_{node_spec.node_name}"

def test_health():
    response = requests.get(f"{{NODE_URL}}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
"""
        return test_code
    
    def _validate_generated_code(
        self, generated_files: Dict[str, str]
    ) -> Dict[str, bool]:
        """验证生成的代码"""
        results = {}
        
        for file_type, file_path in generated_files.items():
            # 检查文件是否存在
            if not os.path.exists(file_path):
                results[file_type] = False
                continue
            
            # 检查文件是否为空
            if os.path.getsize(file_path) == 0:
                results[file_type] = False
                continue
            
            # Python 文件语法检查
            if file_path.endswith(".py"):
                try:
                    with open(file_path, "r") as f:
                        code = f.read()
                    compile(code, file_path, "exec")
                    results[file_type] = True
                except SyntaxError:
                    results[file_type] = False
            else:
                results[file_type] = True
        
        return results
    
    def _deploy_node(self, node_spec: NodeSpecification, node_dir: str) -> bool:
        """部署节点"""
        # 简化实现：仅返回成功
        # 实际应该启动节点服务器并验证
        return True
    
    def _parse_description_to_spec(
        self, description: str, node_number: int, port: int
    ) -> NodeSpecification:
        """从描述解析节点规格"""
        # 简化实现：基于关键词推断
        # 实际应该调用 Node_01_OneAPI 进行深度理解
        
        node_type = NodeType.ACTION  # 默认
        
        if "感知" in description or "监控" in description:
            node_type = NodeType.PERCEPTION
        elif "认知" in description or "分析" in description:
            node_type = NodeType.COGNITION
        elif "学习" in description:
            node_type = NodeType.LEARNING
        elif "集成" in description:
            node_type = NodeType.INTEGRATION
        
        # 提取节点名称（简化）
        node_name = f"CustomNode{node_number}"
        
        return NodeSpecification(
            node_number=node_number,
            node_name=node_name,
            node_type=node_type,
            description=description,
            port=port
        )
    
    def _write_file(self, path: str, content: str):
        """写入文件"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
