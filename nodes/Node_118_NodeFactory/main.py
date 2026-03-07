"""
Node 118 - NodeFactory (节点工厂)
提供节点动态创建、管理和生命周期控制能力
"""
import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Type
from dataclasses import dataclass, field, asdict
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import importlib
import subprocess

try:
    from nodes.common.cors_config import get_cors_origins
except ImportError:
    def get_cors_origins():
        return ["*"]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 118 - NodeFactory", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class NodeType(str, Enum):
    """节点类型"""
    SERVICE = "service"         # 服务节点
    WORKER = "worker"           # 工作节点
    GATEWAY = "gateway"         # 网关节点
    STORAGE = "storage"         # 存储节点
    COMPUTE = "compute"         # 计算节点
    INTEGRATION = "integration" # 集成节点


class NodeState(str, Enum):
    """节点状态"""
    CREATED = "created"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class NodeTemplate:
    """节点模板"""
    template_id: str
    name: str
    node_type: NodeType
    description: str
    base_image: Optional[str] = None
    entry_point: str = "main.py"
    dependencies: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    default_config: Dict[str, Any] = field(default_factory=dict)
    ports: List[int] = field(default_factory=list)
    environment: Dict[str, str] = field(default_factory=dict)


@dataclass
class NodeInstance:
    """节点实例"""
    instance_id: str
    template_id: str
    name: str
    node_type: NodeType
    state: NodeState = NodeState.CREATED
    config: Dict[str, Any] = field(default_factory=dict)
    host: str = "localhost"
    port: int = 0
    pid: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    health_status: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeBlueprint:
    """节点蓝图（用于代码生成）"""
    blueprint_id: str
    name: str
    node_type: NodeType
    capabilities: List[str]
    api_endpoints: List[Dict[str, Any]]
    dependencies: List[str]
    code_template: str


class NodeFactory:
    """节点工厂"""
    
    def __init__(self):
        self.templates: Dict[str, NodeTemplate] = {}
        self.instances: Dict[str, NodeInstance] = {}
        self.blueprints: Dict[str, NodeBlueprint] = {}
        self._processes: Dict[str, subprocess.Popen] = {}
        self._port_counter = 9000
        self._initialize_default_templates()
    
    def _initialize_default_templates(self):
        """初始化默认模板"""
        default_templates = [
            NodeTemplate(
                template_id="generic_service",
                name="Generic Service",
                node_type=NodeType.SERVICE,
                description="通用服务节点模板",
                entry_point="main.py",
                dependencies=["fastapi", "uvicorn"],
                ports=[8000],
                default_config={"host": "0.0.0.0", "port": 8000}
            ),
            NodeTemplate(
                template_id="worker_node",
                name="Worker Node",
                node_type=NodeType.WORKER,
                description="工作节点模板",
                entry_point="worker.py",
                dependencies=["celery", "redis"],
                default_config={"concurrency": 4}
            ),
            NodeTemplate(
                template_id="api_gateway",
                name="API Gateway",
                node_type=NodeType.GATEWAY,
                description="API 网关节点模板",
                entry_point="gateway.py",
                dependencies=["fastapi", "httpx"],
                ports=[8080],
                default_config={"rate_limit": 100}
            ),
        ]
        
        for template in default_templates:
            self.templates[template.template_id] = template
    
    def register_template(self, template: NodeTemplate) -> bool:
        """注册节点模板"""
        self.templates[template.template_id] = template
        logger.info(f"Registered template: {template.template_id}")
        return True
    
    def create_instance(self, template_id: str, name: str,
                        config: Dict[str, Any] = None) -> str:
        """创建节点实例"""
        if template_id not in self.templates:
            raise ValueError(f"Template not found: {template_id}")
        
        template = self.templates[template_id]
        
        # 分配端口
        port = self._allocate_port()
        
        # 合并配置
        instance_config = {**template.default_config, **(config or {})}
        instance_config["port"] = port
        
        instance = NodeInstance(
            instance_id=str(uuid.uuid4()),
            template_id=template_id,
            name=name,
            node_type=template.node_type,
            config=instance_config,
            port=port
        )
        
        self.instances[instance.instance_id] = instance
        logger.info(f"Created instance: {instance.instance_id} ({name})")
        return instance.instance_id
    
    def _allocate_port(self) -> int:
        """分配端口"""
        port = self._port_counter
        self._port_counter += 1
        return port
    
    async def start_instance(self, instance_id: str) -> bool:
        """启动节点实例 - 真实subprocess启动"""
        if instance_id not in self.instances:
            return False

        instance = self.instances[instance_id]

        if instance.state == NodeState.RUNNING:
            return True

        instance.state = NodeState.INITIALIZING

        try:
            template = self.templates.get(instance.template_id)
            if not template:
                raise ValueError(f"Template not found: {instance.template_id}")

            # 查找节点入口文件
            entry_point = template.entry_point
            node_dir = instance.config.get("node_dir")
            port = instance.port

            if node_dir and os.path.exists(os.path.join(node_dir, entry_point)):
                # 真实启动子进程
                env = os.environ.copy()
                env.update(template.environment)
                env["PORT"] = str(port)
                env["NODE_INSTANCE_ID"] = instance_id
                env["NODE_NAME"] = instance.name

                process = subprocess.Popen(
                    ["python", entry_point],
                    cwd=node_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                self._processes[instance_id] = process
                instance.pid = process.pid

                # 等待节点启动并检查健康
                import httpx
                for attempt in range(10):
                    await asyncio.sleep(0.5)
                    # 检查进程是否还在运行
                    if process.poll() is not None:
                        stderr = process.stderr.read().decode() if process.stderr else ""
                        raise RuntimeError(f"节点进程退出(code={process.returncode}): {stderr[:200]}")
                    # 检查健康端点
                    try:
                        async with httpx.AsyncClient() as client:
                            resp = await client.get(f"http://localhost:{port}/health", timeout=2.0)
                            if resp.status_code == 200:
                                instance.state = NodeState.RUNNING
                                instance.started_at = datetime.now()
                                instance.health_status = "healthy"
                                logger.info(f"Started instance: {instance_id} (pid={process.pid}, port={port})")
                                return True
                    except (httpx.ConnectError, httpx.TimeoutException):
                        continue

                raise RuntimeError(f"节点启动超时(port={port})")

            elif instance.config.get("blueprint_id"):
                # 从蓝图生成的代码启动
                blueprint = self.blueprints.get(instance.config["blueprint_id"])
                if blueprint:
                    import tempfile
                    work_dir = tempfile.mkdtemp(prefix=f"galaxy_node_{instance.name}_")
                    code_path = os.path.join(work_dir, "main.py")
                    with open(code_path, "w") as f:
                        f.write(blueprint.code_template.replace(
                            "port=8000", f"port={port}"
                        ))

                    process = subprocess.Popen(
                        ["python", "main.py"],
                        cwd=work_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    self._processes[instance_id] = process
                    instance.pid = process.pid
                    instance.config["work_dir"] = work_dir

                    await asyncio.sleep(1.0)
                    if process.poll() is None:
                        instance.state = NodeState.RUNNING
                        instance.started_at = datetime.now()
                        instance.health_status = "healthy"
                        logger.info(f"Started blueprint instance: {instance_id} (pid={process.pid})")
                        return True
                    else:
                        raise RuntimeError("蓝图节点启动失败")

            else:
                # 无法找到入口文件时，标记为就绪但不启动进程
                logger.warning(f"No entry point found for {instance_id}, marking as RUNNING (virtual)")
                instance.state = NodeState.RUNNING
                instance.started_at = datetime.now()
                instance.health_status = "virtual"
                return True

        except Exception as e:
            instance.state = NodeState.ERROR
            instance.health_status = f"error: {str(e)[:100]}"
            logger.error(f"Failed to start instance {instance_id}: {e}")
            return False
    
    async def stop_instance(self, instance_id: str) -> bool:
        """停止节点实例"""
        if instance_id not in self.instances:
            return False
        
        instance = self.instances[instance_id]
        
        if instance.state == NodeState.STOPPED:
            return True
        
        instance.state = NodeState.STOPPING
        
        try:
            # 停止进程
            if instance_id in self._processes:
                self._processes[instance_id].terminate()
                del self._processes[instance_id]
            
            instance.state = NodeState.STOPPED
            instance.stopped_at = datetime.now()
            instance.health_status = "stopped"
            
            logger.info(f"Stopped instance: {instance_id}")
            return True
            
        except Exception as e:
            instance.state = NodeState.ERROR
            logger.error(f"Failed to stop instance {instance_id}: {e}")
            return False
    
    async def restart_instance(self, instance_id: str) -> bool:
        """重启节点实例"""
        await self.stop_instance(instance_id)
        await asyncio.sleep(1)
        return await self.start_instance(instance_id)
    
    def delete_instance(self, instance_id: str) -> bool:
        """删除节点实例"""
        if instance_id not in self.instances:
            return False
        
        instance = self.instances[instance_id]
        
        if instance.state == NodeState.RUNNING:
            asyncio.create_task(self.stop_instance(instance_id))
        
        del self.instances[instance_id]
        logger.info(f"Deleted instance: {instance_id}")
        return True
    
    def generate_node_code(self, blueprint: NodeBlueprint) -> str:
        """根据蓝图生成节点代码"""
        code = f'''"""
{blueprint.name}
Auto-generated by NodeFactory
"""
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="{blueprint.name}", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Capabilities: {", ".join(blueprint.capabilities)}

'''
        
        # 生成 API 端点
        for endpoint in blueprint.api_endpoints:
            method = endpoint.get("method", "get").lower()
            path = endpoint.get("path", "/")
            name = endpoint.get("name", "endpoint")
            description = endpoint.get("description", "")
            
            code += f'''
@app.{method}("{path}")
async def {name}():
    """{description}"""
    return {{"status": "ok", "endpoint": "{name}"}}

'''
        
        # 添加健康检查
        code += '''
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
        
        return code
    
    def create_blueprint(self, name: str, node_type: NodeType,
                         capabilities: List[str],
                         api_endpoints: List[Dict[str, Any]]) -> str:
        """创建节点蓝图"""
        blueprint = NodeBlueprint(
            blueprint_id=str(uuid.uuid4()),
            name=name,
            node_type=node_type,
            capabilities=capabilities,
            api_endpoints=api_endpoints,
            dependencies=["fastapi", "uvicorn"],
            code_template=""
        )
        
        # 生成代码
        blueprint.code_template = self.generate_node_code(blueprint)
        
        self.blueprints[blueprint.blueprint_id] = blueprint
        logger.info(f"Created blueprint: {blueprint.blueprint_id}")
        return blueprint.blueprint_id
    
    def get_instance(self, instance_id: str) -> Optional[NodeInstance]:
        """获取节点实例"""
        return self.instances.get(instance_id)
    
    def list_instances(self, node_type: Optional[NodeType] = None,
                       state: Optional[NodeState] = None) -> List[NodeInstance]:
        """列出节点实例"""
        instances = list(self.instances.values())
        
        if node_type:
            instances = [i for i in instances if i.node_type == node_type]
        if state:
            instances = [i for i in instances if i.state == state]
        
        return instances
    
    def get_status(self) -> Dict[str, Any]:
        """获取工厂状态"""
        return {
            "templates": len(self.templates),
            "instances": len(self.instances),
            "running_instances": sum(1 for i in self.instances.values() if i.state == NodeState.RUNNING),
            "blueprints": len(self.blueprints),
            "instances_by_type": {
                nt.value: sum(1 for i in self.instances.values() if i.node_type == nt)
                for nt in NodeType
            }
        }


# 全局实例
node_factory = NodeFactory()


# API 模型
class RegisterTemplateRequest(BaseModel):
    template_id: str
    name: str
    node_type: str
    description: str
    entry_point: str = "main.py"
    dependencies: List[str] = []
    default_config: Dict[str, Any] = {}
    ports: List[int] = []

class CreateInstanceRequest(BaseModel):
    template_id: str
    name: str
    config: Dict[str, Any] = {}

class CreateBlueprintRequest(BaseModel):
    name: str
    node_type: str
    capabilities: List[str]
    api_endpoints: List[Dict[str, Any]]


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_118_NodeFactory"}

@app.get("/status")
async def get_status():
    return node_factory.get_status()

@app.post("/templates")
async def register_template(request: RegisterTemplateRequest):
    template = NodeTemplate(
        template_id=request.template_id,
        name=request.name,
        node_type=NodeType(request.node_type),
        description=request.description,
        entry_point=request.entry_point,
        dependencies=request.dependencies,
        default_config=request.default_config,
        ports=request.ports
    )
    node_factory.register_template(template)
    return {"success": True}

@app.get("/templates")
async def list_templates():
    return {tid: asdict(t) for tid, t in node_factory.templates.items()}

@app.post("/instances")
async def create_instance(request: CreateInstanceRequest):
    try:
        instance_id = node_factory.create_instance(
            request.template_id,
            request.name,
            request.config
        )
        return {"instance_id": instance_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/instances")
async def list_instances(node_type: Optional[str] = None, state: Optional[str] = None):
    nt = NodeType(node_type) if node_type else None
    ns = NodeState(state) if state else None
    instances = node_factory.list_instances(nt, ns)
    return [asdict(i) for i in instances]

@app.get("/instances/{instance_id}")
async def get_instance(instance_id: str):
    instance = node_factory.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    return asdict(instance)

@app.post("/instances/{instance_id}/start")
async def start_instance(instance_id: str):
    success = await node_factory.start_instance(instance_id)
    return {"success": success}

@app.post("/instances/{instance_id}/stop")
async def stop_instance(instance_id: str):
    success = await node_factory.stop_instance(instance_id)
    return {"success": success}

@app.post("/instances/{instance_id}/restart")
async def restart_instance(instance_id: str):
    success = await node_factory.restart_instance(instance_id)
    return {"success": success}

@app.delete("/instances/{instance_id}")
async def delete_instance(instance_id: str):
    success = node_factory.delete_instance(instance_id)
    return {"success": success}

@app.post("/blueprints")
async def create_blueprint(request: CreateBlueprintRequest):
    blueprint_id = node_factory.create_blueprint(
        request.name,
        NodeType(request.node_type),
        request.capabilities,
        request.api_endpoints
    )
    return {"blueprint_id": blueprint_id}

@app.get("/blueprints")
async def list_blueprints():
    return {bid: {"name": b.name, "node_type": b.node_type.value, "capabilities": b.capabilities}
            for bid, b in node_factory.blueprints.items()}

@app.get("/blueprints/{blueprint_id}/code")
async def get_blueprint_code(blueprint_id: str):
    if blueprint_id not in node_factory.blueprints:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return {"code": node_factory.blueprints[blueprint_id].code_template}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8118)
