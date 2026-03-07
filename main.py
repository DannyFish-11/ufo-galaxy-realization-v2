#!/usr/bin/env python3
"""
UFO Galaxy - 主启动入口
========================
一键启动整个 UFO Galaxy 系统。

启动入口统一:
    python main.py              → 代理到 unified_launcher.py (推荐)
    python main.py --legacy     → 使用本文件的原生启动器
    python main.py --setup      → 运行配置向导
    python main.py --status     → 查看系统状态

其他入口:
    python unified_launcher.py  → 完整的统一启动器 (Docker CMD)
    python start_galaxy.py      → 轻量 Dashboard 快速启动
    ./deploy.sh up              → Docker Compose 生产部署
"""

import os
import sys
import json
import time
import signal
import asyncio
import logging
import argparse
import subprocess
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime

# 设置项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

# ── Quick delegation: if no --legacy flag, delegate to unified_launcher ──
if __name__ == "__main__" and "--legacy" not in sys.argv and "--setup" not in sys.argv:
    # Pass all args through to unified_launcher
    _launcher = PROJECT_ROOT / "unified_launcher.py"
    if _launcher.exists():
        _args = [sys.executable, str(_launcher)] + [a for a in sys.argv[1:] if a != "--legacy"]
        sys.exit(subprocess.call(_args))
    # Fallback: continue with this file's native launcher

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("UFO-Galaxy")


class Colors:
    """终端颜色"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_banner():
    """打印启动横幅"""
    banner = f"""
{Colors.CYAN}{Colors.BOLD}
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     ██╗   ██╗███████╗ ██████╗                            ║
    ║     ██║   ██║██╔════╝██╔═══██╗                           ║
    ║     ██║   ██║█████╗  ██║   ██║                           ║
    ║     ██║   ██║██╔══╝  ██║   ██║                           ║
    ║     ╚██████╔╝██║     ╚██████╔╝                           ║
    ║      ╚═════╝ ╚═╝      ╚═════╝                            ║
    ║                                                           ║
    ║      ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗  ║
    ║     ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝  ║
    ║     ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝   ║
    ║     ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝    ║
    ║     ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║     ║
    ║      ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝     ║
    ║                                                           ║
    ║              L4 级自主性智能系统 v1.0                     ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
{Colors.ENDC}
    """
    print(banner)


def print_status(message: str, status: str = "info"):
    """打印状态信息"""
    icons = {
        "info": f"{Colors.BLUE}ℹ️ ",
        "success": f"{Colors.GREEN}✅",
        "warning": f"{Colors.YELLOW}⚠️ ",
        "error": f"{Colors.RED}❌",
        "loading": f"{Colors.CYAN}⏳",
    }
    icon = icons.get(status, icons["info"])
    print(f"{icon} {message}{Colors.ENDC}")


class ConfigManager:
    """配置管理器"""
    
    def __init__(self):
        self.env_file = PROJECT_ROOT / ".env"
        self.config: Dict[str, str] = {}
        self.required_apis = ["OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "XAI_API_KEY"]
        
    def load(self) -> bool:
        """加载配置"""
        # 1. 从 .env 文件加载
        if self.env_file.exists():
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        self.config[key.strip()] = value.strip()
                        os.environ[key.strip()] = value.strip()
                        
        # 2. 从环境变量补充
        for key in self.required_apis:
            if key not in self.config:
                env_value = os.environ.get(key)
                if env_value:
                    self.config[key] = env_value
                    
        return self.validate()
        
    def validate(self) -> bool:
        """验证配置"""
        # 检查是否至少有一个 LLM API
        has_llm = any(
            self.config.get(key) 
            for key in self.required_apis
        )
        return has_llm
        
    def get_status(self) -> Dict[str, Any]:
        """获取配置状态"""
        return {
            "llm_apis": {
                key: bool(self.config.get(key))
                for key in self.required_apis
            },
            "database": {
                "postgresql": bool(self.config.get("DATABASE_URL")),
                "redis": bool(self.config.get("REDIS_URL")),
                "qdrant": bool(self.config.get("QDRANT_URL")),
            },
            "services": {
                "github": bool(self.config.get("GITHUB_TOKEN")),
                "weather": bool(self.config.get("OPENWEATHERMAP_API_KEY")),
                "search": bool(self.config.get("BRAVE_API_KEY")),
            }
        }


class DependencyManager:
    """依赖管理器"""
    
    REQUIRED_PACKAGES = [
        "aiohttp",
        "fastapi",
        "uvicorn",
        "pydantic",
        "python-dotenv",
        "psutil",
        "httpx",
    ]
    
    @classmethod
    def check_and_install(cls) -> bool:
        """检查并安装依赖"""
        missing = []
        
        for package in cls.REQUIRED_PACKAGES:
            try:
                __import__(package.replace("-", "_"))
            except ImportError:
                missing.append(package)
                
        if missing:
            print_status(f"安装缺失的依赖: {', '.join(missing)}", "loading")
            try:
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", 
                    "--quiet", "--disable-pip-version-check"
                ] + missing)
                print_status("依赖安装完成", "success")
                return True
            except subprocess.CalledProcessError:
                print_status("依赖安装失败，请手动运行: pip install -r requirements.txt", "error")
                return False
        return True


class IntegratedServices:
    """
    集成服务层 —— 直接导入并实例化核心节点引擎（进程内调用）。
    解决节点孤岛问题：知识图谱、记忆系统、代码引擎不再只是独立进程，
    而是作为主系统的一部分可被直接调用。
    """

    def __init__(self):
        self.knowledge_db = None
        self.reasoning_engine = None
        self.memory_db = None
        self.short_term_memory = None
        self.pattern_recognizer = None
        self.code_parser = None
        self.code_generator = None
        self.code_reviewer = None
        self.l4_loop = None
        self._initialized = False

    def initialize(self) -> Dict[str, bool]:
        """初始化所有集成服务，返回每个服务的状态"""
        status = {}

        # 确保持久化数据目录存在
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(exist_ok=True)

        # 1. 知识图谱 (Node_103)
        try:
            from nodes.Node_103_KnowledgeGraph.main import KnowledgeGraphDB, ReasoningEngine
            kg_db_path = os.environ.get("KNOWLEDGE_DB_PATH", str(data_dir / "knowledge.db"))
            self.knowledge_db = KnowledgeGraphDB(kg_db_path)
            self.reasoning_engine = ReasoningEngine(self.knowledge_db)
            status["knowledge_graph"] = True
            logger.info("知识图谱引擎已集成")
        except Exception as e:
            status["knowledge_graph"] = False
            logger.warning(f"知识图谱引擎集成失败: {e}")

        # 2. 记忆系统 (Node_100)
        try:
            from nodes.Node_100_MemorySystem.main import (
                MemoryDatabase, ShortTermMemory, PatternRecognizer, KnowledgeExtractor
            )
            mem_db_path = os.environ.get("MEMORY_DB_PATH", str(data_dir / "memory.db"))
            self.memory_db = MemoryDatabase(mem_db_path)
            self.short_term_memory = ShortTermMemory()
            self.pattern_recognizer = PatternRecognizer()
            self.knowledge_extractor = KnowledgeExtractor()
            status["memory_system"] = True
            logger.info("记忆系统引擎已集成")
        except Exception as e:
            status["memory_system"] = False
            logger.warning(f"记忆系统引擎集成失败: {e}")

        # 3. 代码引擎 (Node_101)
        try:
            from nodes.Node_101_CodeEngine.main import (
                PythonCodeParser, CodeUnderstanding, CodeGenerator, CodeReviewer
            )
            self.code_parser = PythonCodeParser()
            self.code_understanding = CodeUnderstanding()
            self.code_generator = CodeGenerator()
            self.code_reviewer = CodeReviewer()
            status["code_engine"] = True
            logger.info("代码引擎已集成")
        except Exception as e:
            status["code_engine"] = False
            logger.warning(f"代码引擎集成失败: {e}")

        # 4. L4 主循环
        try:
            from galaxy_main_loop_l4 import GalaxyMainLoopL4
            self.l4_loop = GalaxyMainLoopL4({"cycle_interval": 5.0})
            status["l4_loop"] = True
            logger.info("L4 主循环已集成")
        except Exception as e:
            status["l4_loop"] = False
            logger.warning(f"L4 主循环集成失败: {e}")

        self._initialized = True
        return status

    def get_status(self) -> Dict[str, Any]:
        """获取各集成服务的运行状态"""
        return {
            "initialized": self._initialized,
            "knowledge_graph": self.knowledge_db is not None,
            "memory_system": self.memory_db is not None,
            "code_engine": self.code_parser is not None,
            "l4_loop": self.l4_loop is not None,
        }


class NodeManager:
    """节点管理器"""
    
    def __init__(self):
        self.nodes_dir = PROJECT_ROOT / "nodes"
        self.running_nodes: Dict[str, subprocess.Popen] = {}
        self.node_configs = self._load_node_configs()
        
    def _load_node_configs(self) -> Dict[str, Any]:
        """加载节点配置"""
        config_file = PROJECT_ROOT / "node_dependencies.json"
        if config_file.exists():
            with open(config_file, 'r') as f:
                return json.load(f)
        return {}
        
    def get_core_nodes(self) -> List[str]:
        """获取核心节点列表"""
        core_nodes = []
        for name, config in self.node_configs.items():
            if config.get("group") == "core":
                core_nodes.append(name)
        return sorted(core_nodes, key=lambda x: self.node_configs.get(x, {}).get("priority", 99))
        
    def get_all_nodes(self) -> List[str]:
        """获取所有节点列表"""
        if not self.nodes_dir.exists():
            return []
        return sorted([
            d.name for d in self.nodes_dir.iterdir()
            if d.is_dir() and (d / "main.py").exists()
        ])
        
    async def start_node(self, node_name: str) -> bool:
        """启动单个节点"""
        node_dir = self.nodes_dir / node_name
        main_py = node_dir / "main.py"
        
        if not main_py.exists():
            return False
            
        try:
            process = subprocess.Popen(
                [sys.executable, str(main_py)],
                cwd=str(node_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
            )
            self.running_nodes[node_name] = process
            return True
        except Exception as e:
            logger.error(f"启动节点 {node_name} 失败: {e}")
            return False
            
    async def start_nodes(self, nodes: List[str], parallel: bool = False) -> Dict[str, bool]:
        """启动多个节点"""
        results = {}
        
        if parallel:
            tasks = [self.start_node(node) for node in nodes]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            for node, result in zip(nodes, results_list):
                results[node] = result is True
        else:
            for node in nodes:
                results[node] = await self.start_node(node)
                await asyncio.sleep(0.1)  # 短暂延迟
                
        return results
        
    def stop_all(self):
        """停止所有节点"""
        for name, process in self.running_nodes.items():
            try:
                process.terminate()
                process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                process.kill()
        self.running_nodes.clear()
        
    def get_status(self) -> Dict[str, str]:
        """获取节点状态"""
        status = {}
        for name, process in self.running_nodes.items():
            if process.poll() is None:
                status[name] = "running"
            else:
                status[name] = "stopped"
        return status

    def get_node_port(self, node_name: str) -> Optional[int]:
        """获取节点的端口号"""
        nodes_config = self.node_configs.get("nodes", self.node_configs)
        node_cfg = nodes_config.get(node_name, {})
        return node_cfg.get("port")

    async def check_node_health(self, node_name: str) -> Dict[str, Any]:
        """通过 HTTP 检查节点健康状态"""
        port = self.get_node_port(node_name)
        if not port:
            return {"node": node_name, "status": "unknown", "error": "no port configured"}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"http://localhost:{port}/health")
                if resp.status_code == 200:
                    return {"node": node_name, "status": "healthy", "data": resp.json()}
                return {"node": node_name, "status": "unhealthy", "code": resp.status_code}
        except Exception as e:
            return {"node": node_name, "status": "unreachable", "error": str(e)}

    async def invoke_node(self, node_name: str, endpoint: str,
                          method: str = "POST", payload: Dict = None) -> Dict[str, Any]:
        """通过 HTTP 调用节点 API —— 真正的节点调用"""
        port = self.get_node_port(node_name)
        if not port:
            return {"success": False, "error": f"节点 {node_name} 未配置端口"}
        try:
            import httpx
            url = f"http://localhost:{port}{endpoint}"
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method.upper() == "GET":
                    resp = await client.get(url)
                else:
                    resp = await client.post(url, json=payload or {})
                return {"success": True, "status_code": resp.status_code, "data": resp.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_detailed_status(self) -> Dict[str, Any]:
        """获取详细的节点统计信息"""
        all_nodes = self.get_all_nodes()
        running = self.get_status()
        nodes_config = self.node_configs.get("nodes", self.node_configs)

        by_group = {}
        for name in all_nodes:
            cfg = nodes_config.get(name, {})
            group = cfg.get("group", "unknown")
            if group not in by_group:
                by_group[group] = {"total": 0, "running": 0, "nodes": []}
            by_group[group]["total"] += 1
            is_running = running.get(name) == "running"
            if is_running:
                by_group[group]["running"] += 1
            by_group[group]["nodes"].append({
                "name": name,
                "port": cfg.get("port"),
                "status": running.get(name, "not_started"),
                "priority": cfg.get("priority", 99),
            })

        return {
            "total_nodes": len(all_nodes),
            "running_nodes": sum(1 for v in running.values() if v == "running"),
            "groups": by_group,
        }


class WebUIServer:
    """Web UI 服务器 —— 提供交互式控制面板和全套 REST API"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.app = None
        self.galaxy_ref = None          # 引用 UFOGalaxy 实例

    def set_galaxy(self, galaxy):
        """设置 Galaxy 实例引用，用于访问集成服务"""
        self.galaxy_ref = galaxy

    async def start(self):
        """启动 Web UI"""
        try:
            from fastapi import FastAPI, HTTPException
            from fastapi.responses import HTMLResponse, JSONResponse
            from fastapi.middleware.cors import CORSMiddleware
            from pydantic import BaseModel
            import uvicorn

            self.app = FastAPI(title="UFO Galaxy", version="2.0",
                               description="L4 级自主性智能系统")
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=get_cors_origins(), allow_methods=["*"], allow_headers=["*"]
            )

            galaxy = self.galaxy_ref  # 捕获引用

            # === 快捷请求模型 ===
            class QueryModel(BaseModel):
                query: str
                limit: int = 10

            class EntityModel(BaseModel):
                name: str
                type: str
                properties: dict = {}

            class RelationModel(BaseModel):
                from_entity: str
                to_entity: str
                relation_type: str
                properties: dict = {}

            class MemoryStoreModel(BaseModel):
                command: str
                context: dict = {}
                actions: list = []
                result: dict = {}
                success: bool = True
                duration: float = 0.0
                session_id: str = "default"

            class CodeParseModel(BaseModel):
                code: str
                language: str = "python"

            class CodeGenModel(BaseModel):
                requirement: str
                language: str = "python"
                context: str = None

            class GoalModel(BaseModel):
                description: str
                goal_type: str = "task_execution"

            class ChatModel(BaseModel):
                message: str
                context: list = []

            # ====================================================================
            # 基础 API
            # ====================================================================

            @self.app.get("/", response_class=HTMLResponse)
            async def index():
                return self._get_dashboard_html()

            @self.app.get("/api/status")
            async def api_status():
                """系统综合状态 —— 真实数据"""
                svc = galaxy.services if galaxy else None
                return JSONResponse({
                    "status": "running",
                    "version": "2.0",
                    "uptime_seconds": int(time.time() - galaxy._start_time) if galaxy else 0,
                    "config": galaxy.config_manager.get_status() if galaxy else {},
                    "nodes": galaxy.node_manager.get_detailed_status() if galaxy else {},
                    "services": svc.get_status() if svc else {},
                    "l4": svc.l4_loop.get_status() if svc and svc.l4_loop else {},
                    "timestamp": datetime.now().isoformat(),
                })

            # ====================================================================
            # 知识图谱 API —— 直接调用 Node_103 引擎
            # ====================================================================

            @self.app.post("/api/knowledge/add_entity")
            async def kg_add_entity(req: EntityModel):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.knowledge_db:
                    raise HTTPException(503, "知识图谱服务未就绪")
                from nodes.Node_103_KnowledgeGraph.main import Entity
                eid = hashlib.md5(f"{req.name}{req.type}".encode()).hexdigest()
                entity = Entity(id=eid, name=req.name, type=req.type,
                                properties=req.properties,
                                created_at=datetime.now().isoformat())
                ok = svc.knowledge_db.add_entity(entity)
                return {"success": ok, "entity_id": eid}

            @self.app.post("/api/knowledge/add_relation")
            async def kg_add_relation(req: RelationModel):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.knowledge_db:
                    raise HTTPException(503, "知识图谱服务未就绪")
                from nodes.Node_103_KnowledgeGraph.main import Relation
                rid = hashlib.md5(
                    f"{req.from_entity}{req.to_entity}{req.relation_type}".encode()
                ).hexdigest()
                rel = Relation(id=rid, from_entity=req.from_entity,
                               to_entity=req.to_entity,
                               relation_type=req.relation_type,
                               properties=req.properties,
                               created_at=datetime.now().isoformat())
                ok = svc.knowledge_db.add_relation(rel)
                return {"success": ok, "relation_id": rid}

            @self.app.post("/api/knowledge/query")
            async def kg_query(req: QueryModel):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.knowledge_db:
                    raise HTTPException(503, "知识图谱服务未就绪")
                entities = svc.knowledge_db.find_entities(name=req.query)
                return {"success": True, "count": len(entities),
                        "entities": [asdict(e) for e in entities[:req.limit]]}

            @self.app.post("/api/knowledge/reason")
            async def kg_reason(req: dict):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.reasoning_engine:
                    raise HTTPException(503, "推理引擎未就绪")
                result = svc.reasoning_engine.reason(
                    req.get("facts", []), req.get("question", ""))
                return {"success": True, "result": asdict(result)}

            @self.app.post("/api/knowledge/find_path")
            async def kg_find_path(req: dict):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.reasoning_engine:
                    raise HTTPException(503, "推理引擎未就绪")
                paths = svc.reasoning_engine.find_path(
                    req.get("from_entity", ""), req.get("to_entity", ""),
                    req.get("max_depth", 5))
                return {"success": True, "paths": paths}

            # ====================================================================
            # 记忆系统 API —— 直接调用 Node_100 引擎
            # ====================================================================

            @self.app.post("/api/memory/store")
            async def mem_store(req: MemoryStoreModel):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.memory_db:
                    raise HTTPException(503, "记忆系统未就绪")
                from nodes.Node_100_MemorySystem.main import Experience
                exp_id = hashlib.md5(
                    f"{req.command}{req.session_id}{datetime.now().isoformat()}".encode()
                ).hexdigest()
                exp = Experience(
                    id=exp_id, timestamp=datetime.now().isoformat(),
                    command=req.command, context=req.context,
                    actions=req.actions, result=req.result,
                    success=req.success, duration=req.duration,
                    session_id=req.session_id)
                svc.short_term_memory.add(req.session_id, exp)
                ok = svc.memory_db.store_experience(exp)
                return {"success": ok, "experience_id": exp_id}

            @self.app.post("/api/memory/retrieve")
            async def mem_retrieve(req: QueryModel):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.memory_db:
                    raise HTTPException(503, "记忆系统未就绪")
                exps = svc.memory_db.retrieve_experiences(req.query, req.limit)
                return {"success": True, "count": len(exps),
                        "experiences": [asdict(e) for e in exps]}

            @self.app.post("/api/memory/patterns")
            async def mem_patterns():
                svc = galaxy.services if galaxy else None
                if not svc or not svc.memory_db:
                    raise HTTPException(503, "记忆系统未就绪")
                exps = svc.memory_db.get_all_experiences()
                patterns = svc.pattern_recognizer.extract_patterns(exps)
                return {"success": True, "count": len(patterns),
                        "patterns": [asdict(p) for p in patterns]}

            @self.app.get("/api/memory/stats")
            async def mem_stats():
                svc = galaxy.services if galaxy else None
                if not svc or not svc.memory_db:
                    raise HTTPException(503, "记忆系统未就绪")
                exps = svc.memory_db.get_all_experiences()
                sc = sum(1 for e in exps if e.success)
                return {"total": len(exps),
                        "success_rate": sc / len(exps) if exps else 0,
                        "patterns": len(svc.memory_db.get_patterns())}

            # ====================================================================
            # 代码引擎 API —— 直接调用 Node_101 引擎
            # ====================================================================

            @self.app.post("/api/code/parse")
            async def code_parse(req: CodeParseModel):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.code_parser:
                    raise HTTPException(503, "代码引擎未就绪")
                analysis = svc.code_parser.parse(req.code)
                return {"success": True, "analysis": asdict(analysis)}

            @self.app.post("/api/code/understand")
            async def code_understand(req: dict):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.code_understanding:
                    raise HTTPException(503, "代码引擎未就绪")
                result = svc.code_understanding.understand(
                    req.get("code", ""), req.get("language", "python"),
                    req.get("question"))
                return {"success": True, **result}

            @self.app.post("/api/code/generate")
            async def code_generate(req: CodeGenModel):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.code_generator:
                    raise HTTPException(503, "代码引擎未就绪")
                code = svc.code_generator.generate(
                    req.requirement, req.language, req.context)
                return {"success": True, "code": code, "language": req.language}

            @self.app.post("/api/code/review")
            async def code_review(req: CodeParseModel):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.code_reviewer:
                    raise HTTPException(503, "代码引擎未就绪")
                result = svc.code_reviewer.review(req.code, req.language)
                return {"success": True, **result}

            # ====================================================================
            # L4 目标提交 API
            # ====================================================================

            @self.app.post("/api/goals/submit")
            async def submit_goal(req: GoalModel):
                svc = galaxy.services if galaxy else None
                if not svc or not svc.l4_loop:
                    raise HTTPException(503, "L4 主循环未就绪")
                result = await svc.l4_loop.submit_goal(req.description)
                return result

            @self.app.get("/api/goals/status")
            async def goal_status():
                svc = galaxy.services if galaxy else None
                if not svc or not svc.l4_loop:
                    raise HTTPException(503, "L4 主循环未就绪")
                return svc.l4_loop.get_status()

            # ====================================================================
            # 节点调用 API —— 通过 HTTP 转发到独立运行的节点服务
            # ====================================================================

            @self.app.post("/api/nodes/invoke")
            async def invoke_node(req: dict):
                if not galaxy:
                    raise HTTPException(503, "系统未就绪")
                node_name = req.get("node_name", "")
                endpoint = req.get("endpoint", "/health")
                method = req.get("method", "GET")
                payload = req.get("payload", {})
                result = await galaxy.node_manager.invoke_node(
                    node_name, endpoint, method, payload)
                return result

            @self.app.get("/api/nodes/health/{node_name}")
            async def node_health(node_name: str):
                if not galaxy:
                    raise HTTPException(503, "系统未就绪")
                return await galaxy.node_manager.check_node_health(node_name)

            @self.app.get("/api/nodes/list")
            async def list_nodes():
                if not galaxy:
                    raise HTTPException(503, "系统未就绪")
                return galaxy.node_manager.get_detailed_status()

            # ====================================================================
            # 挂载 core/api_routes 中已定义的路由（如果可用）
            # ====================================================================
            try:
                from core.api_routes import create_api_routes
                api_router = create_api_routes(
                    service_manager=galaxy,
                    config=galaxy.config_manager if galaxy else None
                )
                if api_router:
                    self.app.include_router(api_router, prefix="/api/v1")
                    logger.info("已挂载 core/api_routes 中的 API 路由")
            except Exception as e:
                logger.warning(f"挂载 core/api_routes 失败（非致命）: {e}")

            # ====================================================================
            # 启动服务器
            # ====================================================================
            config = uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="warning"
            )
            server = uvicorn.Server(config)
            await server.serve()

        except ImportError as e:
            print_status(f"Web UI 依赖未安装，跳过 Web UI: {e}", "warning")
            
    def _get_dashboard_html(self) -> str:
        """获取后台管理面板 HTML —— 展示真实系统状态、集成服务、节点信息"""
        return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UFO Galaxy - 后台管理面板</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);min-height:100vh;color:#e0e0e0}
        .wrap{max-width:1400px;margin:0 auto;padding:16px}
        .hdr{text-align:center;padding:24px 0;border-bottom:1px solid rgba(255,255,255,.08)}
        .hdr h1{font-size:2rem;background:linear-gradient(90deg,#00d4ff,#7b2cbf);
                 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
        .hdr p{color:#888;margin-top:4px;font-size:.9rem}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;margin-top:20px}
        .card{background:rgba(255,255,255,.04);border-radius:12px;padding:20px;
              border:1px solid rgba(255,255,255,.08)}
        .card h3{color:#00d4ff;margin-bottom:12px;font-size:1rem}
        .row{display:flex;justify-content:space-between;padding:6px 0;
             border-bottom:1px solid rgba(255,255,255,.04);font-size:.85rem}
        .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px;vertical-align:middle}
        .dot-on{background:#00ff88}.dot-off{background:#ff4444}.dot-warn{background:#ffa500}
        .badge{padding:2px 8px;border-radius:8px;font-size:.75rem;font-weight:600}
        .badge-ok{background:rgba(0,255,136,.15);color:#00ff88}
        .badge-err{background:rgba(255,68,68,.15);color:#ff4444}
        .badge-warn{background:rgba(255,165,0,.15);color:#ffa500}
        #test-area{margin-top:20px}
        .test-box{display:flex;gap:8px;margin-bottom:12px}
        .test-box input,.test-box select{flex:1;padding:8px 12px;border-radius:8px;border:1px solid rgba(255,255,255,.15);
                        background:rgba(255,255,255,.06);color:#fff;font-size:.85rem}
        .test-box button{padding:8px 20px;border-radius:8px;border:none;
                         background:linear-gradient(90deg,#00d4ff,#7b2cbf);color:#fff;cursor:pointer;font-weight:600}
        #test-result{background:rgba(0,0,0,.3);border-radius:8px;padding:12px;
                     font-family:monospace;font-size:.8rem;max-height:300px;overflow-y:auto;white-space:pre-wrap}
        .tabs{display:flex;gap:8px;margin-bottom:12px}
        .tab{padding:6px 16px;border-radius:8px;cursor:pointer;background:rgba(255,255,255,.06);
             border:1px solid rgba(255,255,255,.1);font-size:.8rem}
        .tab.active{background:rgba(0,212,255,.15);border-color:#00d4ff;color:#00d4ff}
    </style>
</head>
<body>
<div class="wrap">
    <div class="hdr">
        <h1>UFO Galaxy</h1>
        <p>L4 级自主性智能系统 - 后台管理面板</p>
    </div>
    <div class="grid">
        <!-- 系统状态 -->
        <div class="card">
            <h3>系统概览</h3>
            <div id="sys-overview">加载中...</div>
        </div>
        <!-- 集成服务 -->
        <div class="card">
            <h3>集成服务状态</h3>
            <div id="svc-status">加载中...</div>
        </div>
        <!-- API 配置 -->
        <div class="card">
            <h3>API 配置</h3>
            <div id="api-config">加载中...</div>
        </div>
        <!-- 节点统计 -->
        <div class="card">
            <h3>节点统计</h3>
            <div id="node-stats">加载中...</div>
        </div>
        <!-- L4 主循环 -->
        <div class="card">
            <h3>L4 主循环</h3>
            <div id="l4-status">加载中...</div>
        </div>
        <!-- 数据库 -->
        <div class="card">
            <h3>数据库/存储</h3>
            <div id="db-status">加载中...</div>
        </div>
    </div>
    <!-- API 测试区 -->
    <div id="test-area" class="card" style="margin-top:20px">
        <h3>API 测试台</h3>
        <div class="tabs">
            <div class="tab active" onclick="setTab('knowledge')">知识查询</div>
            <div class="tab" onclick="setTab('memory')">记忆检索</div>
            <div class="tab" onclick="setTab('code')">代码解析</div>
            <div class="tab" onclick="setTab('goal')">提交目标</div>
            <div class="tab" onclick="setTab('node')">节点调用</div>
        </div>
        <div class="test-box">
            <input id="test-input" placeholder="输入查询内容..." />
            <button onclick="runTest()">执行</button>
        </div>
        <div id="test-result">等待执行...</div>
    </div>
</div>
<script>
let currentTab='knowledge';
function setTab(t){
    currentTab=t;
    document.querySelectorAll('.tab').forEach(el=>el.classList.remove('active'));
    event.target.classList.add('active');
    const ph={knowledge:'输入实体名称搜索知识图谱...',memory:'输入关键词检索记忆...',
              code:'输入Python代码进行解析...',goal:'输入目标描述...',node:'输入节点名称检查健康...'};
    document.getElementById('test-input').placeholder=ph[t]||'';
}
async function runTest(){
    const input=document.getElementById('test-input').value;
    const el=document.getElementById('test-result');
    el.textContent='执行中...';
    try{
        let url,opts={method:'POST',headers:{'Content-Type':'application/json'}};
        if(currentTab==='knowledge'){url='/api/knowledge/query';opts.body=JSON.stringify({query:input,limit:10})}
        else if(currentTab==='memory'){url='/api/memory/retrieve';opts.body=JSON.stringify({query:input,limit:10})}
        else if(currentTab==='code'){url='/api/code/parse';opts.body=JSON.stringify({code:input,language:'python'})}
        else if(currentTab==='goal'){url='/api/goals/submit';opts.body=JSON.stringify({description:input})}
        else if(currentTab==='node'){url='/api/nodes/health/'+encodeURIComponent(input);opts={method:'GET'}}
        const r=await fetch(url,opts);
        const d=await r.json();
        el.textContent=JSON.stringify(d,null,2);
    }catch(e){el.textContent='错误: '+e.message}
}
function dot(ok){return '<span class="dot '+(ok?'dot-on':'dot-off')+'"></span>'}
function badge(ok,yes,no){return '<span class="badge '+(ok?'badge-ok':'badge-err')+'">'+(ok?(yes||'已就绪'):(no||'未就绪'))+'</span>'}
async function refresh(){
    try{
        const r=await fetch('/api/status');const d=await r.json();
        // 系统概览
        let h='';
        h+='<div class="row"><span>'+dot(true)+'系统运行中</span><span>'+d.uptime_seconds+'s</span></div>';
        h+='<div class="row"><span>版本</span><span>'+d.version+'</span></div>';
        h+='<div class="row"><span>时间</span><span>'+(d.timestamp||'').slice(0,19)+'</span></div>';
        document.getElementById('sys-overview').innerHTML=h;
        // 集成服务
        const svc=d.services||{};h='';
        for(const[k,v]of Object.entries(svc)){
            if(k==='initialized')continue;
            h+='<div class="row"><span>'+dot(v)+k+'</span>'+badge(v)+'</div>';
        }
        document.getElementById('svc-status').innerHTML=h||'<div class="row">无数据</div>';
        // API配置
        const cfg=d.config||{};h='';
        const apis=cfg.llm_apis||{};
        for(const[k,v]of Object.entries(apis)){h+='<div class="row"><span>'+dot(v)+k+'</span>'+badge(v,'已配置','未配置')+'</div>'}
        const dbs=cfg.database||{};
        for(const[k,v]of Object.entries(dbs)){h+='<div class="row"><span>'+dot(v)+k+'</span>'+badge(v,'已连接','未连接')+'</div>'}
        document.getElementById('api-config').innerHTML=h||'<div class="row">无数据</div>';
        // 节点统计
        const nodes=d.nodes||{};h='';
        h+='<div class="row"><span>总节点数</span><span>'+(nodes.total_nodes||0)+'</span></div>';
        h+='<div class="row"><span>运行中</span><span>'+(nodes.running_nodes||0)+'</span></div>';
        const groups=nodes.groups||{};
        for(const[g,info]of Object.entries(groups)){
            h+='<div class="row"><span style="color:#888">'+g+'</span><span>'+info.running+'/'+info.total+'</span></div>';
        }
        document.getElementById('node-stats').innerHTML=h||'<div class="row">无数据</div>';
        // L4主循环
        const l4=d.l4||{};h='';
        h+='<div class="row"><span>'+dot(l4.running)+'运行状态</span>'+badge(l4.running,'运行中','未启动')+'</div>';
        h+='<div class="row"><span>当前阶段</span><span>'+(l4.state||'N/A')+'</span></div>';
        h+='<div class="row"><span>已完成周期</span><span>'+(l4.cycle_count||0)+'</span></div>';
        h+='<div class="row"><span>世界实体数</span><span>'+(l4.world_entities_count||0)+'</span></div>';
        h+='<div class="row"><span>可用资源</span><span>'+(l4.available_resources||0)+'</span></div>';
        document.getElementById('l4-status').innerHTML=h;
        // 数据库
        const db=cfg.database||{};h='';
        for(const[k,v]of Object.entries(db)){h+='<div class="row"><span>'+dot(v)+k+'</span>'+badge(v,'在线','离线')+'</div>'}
        document.getElementById('db-status').innerHTML=h||'<div class="row">使用 SQLite 本地存储</div>';
    }catch(e){console.error(e)}
}
refresh();setInterval(refresh,5000);
</script>
</body>
</html>
        """


class UFOGalaxy:
    """UFO Galaxy 主系统"""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.node_manager = NodeManager()
        self.services = IntegratedServices()
        self.web_ui: Optional[WebUIServer] = None
        self.running = False
        self._start_time = time.time()
        
    async def start(self, minimal: bool = False, with_ui: bool = True):
        """启动系统"""
        print_banner()
        
        # 1. 检查依赖
        print_status("检查依赖...", "loading")
        if not DependencyManager.check_and_install():
            return False
            
        # 2. 加载配置
        print_status("加载配置...", "loading")
        if not self.config_manager.load():
            print_status("未检测到有效的 API 配置", "warning")
            print_status("运行 'python setup_wizard.py' 进行配置", "info")
            # 继续运行，使用模拟模式
            
        # 显示配置状态
        status = self.config_manager.get_status()
        llm_count = sum(1 for v in status["llm_apis"].values() if v)
        print_status(f"检测到 {llm_count} 个 LLM API", "success" if llm_count > 0 else "warning")
        
        # 3. 启动节点
        print_status("启动节点系统...", "loading")
        if minimal:
            nodes = self.node_manager.get_core_nodes()[:5]  # 只启动前5个核心节点
        else:
            nodes = self.node_manager.get_core_nodes()
            
        if nodes:
            results = await self.node_manager.start_nodes(nodes)
            success_count = sum(1 for v in results.values() if v)
            print_status(f"已启动 {success_count}/{len(nodes)} 个节点", "success")
        else:
            print_status("未找到节点配置，跳过节点启动", "warning")

        # 3.5. 初始化集成服务层（进程内直接调用节点引擎）
        print_status("初始化集成服务层...", "loading")
        svc_status = self.services.initialize()
        ok_count = sum(1 for v in svc_status.values() if v)
        print_status(f"集成服务: {ok_count}/{len(svc_status)} 就绪 {svc_status}", "success" if ok_count > 0 else "warning")

        # 4. 启动 Web UI
        if with_ui:
            print_status("启动 Web UI...", "loading")
            self.web_ui = WebUIServer()
            self.web_ui.set_galaxy(self)  # 传递引用，让 API 路由能访问集成服务
            print_status(f"Web UI 已启动: http://localhost:8080", "success")
            
        self.running = True
        print()
        print_status("=" * 50, "info")
        print_status("UFO Galaxy 系统已启动！", "success")
        print_status("=" * 50, "info")
        print()
        print_status("访问 http://localhost:8080 查看控制面板", "info")
        print_status("按 Ctrl+C 停止系统", "info")
        
        # 保持运行
        if with_ui and self.web_ui:
            await self.web_ui.start()
        else:
            while self.running:
                await asyncio.sleep(1)
                
    def stop(self):
        """停止系统"""
        print()
        print_status("正在停止系统...", "loading")
        self.running = False
        self.node_manager.stop_all()
        print_status("系统已停止", "success")
        
    def show_status(self):
        """显示系统状态"""
        print_banner()
        
        # 配置状态
        self.config_manager.load()
        status = self.config_manager.get_status()
        
        print(f"\n{Colors.BOLD}=== API 配置状态 ==={Colors.ENDC}")
        for api, configured in status["llm_apis"].items():
            icon = "✅" if configured else "❌"
            print(f"  {icon} {api}")
            
        print(f"\n{Colors.BOLD}=== 数据库状态 ==={Colors.ENDC}")
        for db, configured in status["database"].items():
            icon = "✅" if configured else "❌"
            print(f"  {icon} {db}")
            
        print(f"\n{Colors.BOLD}=== 节点统计 ==={Colors.ENDC}")
        all_nodes = self.node_manager.get_all_nodes()
        core_nodes = self.node_manager.get_core_nodes()
        print(f"  总节点数: {len(all_nodes)}")
        print(f"  核心节点: {len(core_nodes)}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="UFO Galaxy - L4 级自主性智能系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python main.py              # 默认启动
    python main.py --setup      # 运行配置向导
    python main.py --minimal    # 最小启动
    python main.py --status     # 查看状态
        """
    )
    parser.add_argument("--setup", "-s", action="store_true", help="运行配置向导")
    parser.add_argument("--minimal", "-m", action="store_true", help="最小启动（仅核心节点）")
    parser.add_argument("--no-ui", action="store_true", help="不启动 Web UI")
    parser.add_argument("--status", action="store_true", help="查看系统状态")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Web UI 端口")
    
    args = parser.parse_args()
    
    # 运行配置向导
    if args.setup:
        from setup_wizard import SetupWizard
        wizard = SetupWizard()
        wizard.run_interactive_setup()
        return
        
    # 创建系统实例
    galaxy = UFOGalaxy()
    
    # 查看状态
    if args.status:
        galaxy.show_status()
        return
        
    # 设置信号处理
    def signal_handler(sig, frame):
        galaxy.stop()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动系统
    try:
        asyncio.run(galaxy.start(
            minimal=args.minimal,
            with_ui=not args.no_ui
        ))
    except KeyboardInterrupt:
        galaxy.stop()


if __name__ == "__main__":
    main()
