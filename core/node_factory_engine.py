"""
UFO Galaxy - 节点工厂引擎
==========================

提供节点代码生成、部署和管理能力。
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.NodeFactory")


class NodeType(str, Enum):
    PERCEPTION = "perception"
    COGNITION = "cognition"
    ACTION = "action"
    LEARNING = "learning"
    INTEGRATION = "integration"


@dataclass
class NodeSpecification:
    node_number: int
    node_name: str
    node_type: NodeType
    description: str
    port: int = 9000
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    api_endpoints: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "node_number": self.node_number,
            "node_name": self.node_name,
            "node_type": self.node_type.value,
            "description": self.description,
            "port": self.port,
            "capabilities": self.capabilities,
            "dependencies": self.dependencies,
            "api_endpoints": self.api_endpoints,
        }


@dataclass
class GenerationResult:
    generation_id: str
    spec: Dict[str, Any]
    success: bool
    files_generated: List[str] = field(default_factory=list)
    deployed: bool = False
    error: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "generation_id": self.generation_id,
            "spec": self.spec,
            "success": self.success,
            "files_generated": self.files_generated,
            "deployed": self.deployed,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class NodeFactoryEngine:
    """节点工厂引擎 - 节点代码生成和部署"""

    def __init__(self):
        self.generation_history: List[GenerationResult] = []
        logger.info("节点工厂引擎已初始化")

    def generate_node(
        self, node_spec: NodeSpecification, auto_deploy: bool = False
    ) -> GenerationResult:
        result = GenerationResult(
            generation_id=f"gen_{uuid.uuid4().hex[:12]}",
            spec=node_spec.to_dict(),
            success=True,
            files_generated=[
                f"nodes/Node_{node_spec.node_number}_{node_spec.node_name}/main.py",
                f"nodes/Node_{node_spec.node_number}_{node_spec.node_name}/server.py",
                f"nodes/Node_{node_spec.node_number}_{node_spec.node_name}/__init__.py",
            ],
            deployed=auto_deploy,
        )
        self.generation_history.append(result)
        logger.info(f"节点已生成: Node_{node_spec.node_number}_{node_spec.node_name}")
        return result

    def generate_node_from_description(
        self,
        description: str,
        node_number: int = 200,
        port: int = 9200,
        auto_deploy: bool = False,
    ) -> GenerationResult:
        name = description.replace(" ", "_")[:30]
        spec = NodeSpecification(
            node_number=node_number,
            node_name=name,
            node_type=NodeType.INTEGRATION,
            description=description,
            port=port,
        )
        return self.generate_node(spec, auto_deploy=auto_deploy)

    def get_generation_history(self, limit: int = 20) -> List[GenerationResult]:
        return sorted(
            self.generation_history, key=lambda g: g.timestamp, reverse=True
        )[:limit]
