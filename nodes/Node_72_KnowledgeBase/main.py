# -*- coding: utf-8 -*-

"""
Node_72_KnowledgeBase: 知识库管理节点

该节点负责知识的存储、检索、管理和维护，为上层应用提供智能问答和信息查询的基础。
它支持文本知识的向量化存储和相似度检索，并提供简单的增删改查接口。
"""

import asyncio
import dataclasses
import enum
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

# --- 配置和常量 --- #

LOG_LEVEL = logging.INFO
DEFAULT_CONFIG_PATH = "/home/ubuntu/kb_config.json"
DEFAULT_KB_PATH = "/home/ubuntu/knowledge_base.json"

# 配置日志记录器
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()  # 输出到控制台
    ]
)

logger = logging.getLogger("KnowledgeBaseService")


# --- 枚举定义 --- #

class ServiceStatus(enum.Enum):
    """服务运行状态"""
    STOPPED = "stopped"         # 已停止
    INITIALIZING = "initializing" # 初始化中
    RUNNING = "running"         # 运行中
    DEGRADED = "degraded"       # 降级运行（部分功能异常）
    ERROR = "error"             # 发生严重错误

class KnowledgeStatus(enum.Enum):
    """知识条目状态"""
    ACTIVE = "active"           # 活跃状态，可被检索
    ARCHIVED = "archived"       # 已归档，不参与检索
    PENDING = "pending"         # 待处理，例如等待向量化


# --- 数据类定义 --- #

@dataclasses.dataclass
class KnowledgeBaseConfig:
    """知识库节点配置"""
    node_id: str = "Node_72_KnowledgeBase"
    log_level: str = "INFO"
    kb_file_path: str = DEFAULT_KB_PATH
    embedding_model: str = "mock_embedding_v1"  # 模拟使用的向量化模型
    max_results: int = 10  # 最大检索结果数

@dataclasses.dataclass
class KnowledgeEntry:
    """知识条目数据结构"""
    id: str
    content: str
    metadata: Dict[str, Any]
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE
    embedding: Optional[List[float]] = None  # 存储文本内容的向量表示
    created_at: str = dataclasses.field(default_factory=lambda: asyncio.get_event_loop().time().__str__())
    updated_at: str = dataclasses.field(default_factory=lambda: asyncio.get_event_loop().time().__str__())


# --- 核心服务类 --- #

class KnowledgeBaseService:
    """知识库管理主服务"""

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        """初始化服务"""
        self.config_path = config_path
        self.config: KnowledgeBaseConfig = self._load_config()
        self.status: ServiceStatus = ServiceStatus.INITIALIZING
        self._knowledge_base: Dict[str, KnowledgeEntry] = {}
        self._lock = asyncio.Lock()  # 用于保护对知识库文件的并发访问

        logger.info(f"服务 {self.config.node_id} 正在初始化...")
        asyncio.create_task(self._initialize_knowledge_base())

    def _load_config(self) -> KnowledgeBaseConfig:
        """加载配置文件，如果文件不存在则创建默认配置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    return KnowledgeBaseConfig(**config_data)
            else:
                logger.warning(f"配置文件 {self.config_path} 不存在，将创建并使用默认配置。")
                default_config = KnowledgeBaseConfig()
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(dataclasses.asdict(default_config), f, indent=4)
                return default_config
        except (IOError, json.JSONDecodeError, TypeError) as e:
            logger.error(f"加载配置文件失败: {e}，将使用内存中的默认配置。")
            self.status = ServiceStatus.DEGRADED
            return KnowledgeBaseConfig()

    async def _initialize_knowledge_base(self):
        """异步加载知识库文件"""
        async with self._lock:
            try:
                if os.path.exists(self.config.kb_file_path):
                    logger.info(f"从 {self.config.kb_file_path} 加载知识库...")
                    with open(self.config.kb_file_path, 'r', encoding='utf-8') as f:
                        kb_data = json.load(f)
                        for entry_id, entry_data in kb_data.items():
                            # 兼容旧格式，确保 status 字段存在
                            if 'status' in entry_data:
                                entry_data['status'] = KnowledgeStatus(entry_data['status'])
                            else:
                                entry_data['status'] = KnowledgeStatus.ACTIVE
                            self._knowledge_base[entry_id] = KnowledgeEntry(**entry_data)
                    logger.info(f"成功加载 {len(self._knowledge_base)} 条知识。")
                else:
                    logger.warning(f"知识库文件 {self.config.kb_file_path} 不存在，将创建一个空的知识库。")
                self.status = ServiceStatus.RUNNING
            except (IOError, json.JSONDecodeError) as e:
                logger.error(f"初始化知识库失败: {e}")
                self.status = ServiceStatus.ERROR

    async def _save_knowledge_base(self):
        """将当前知识库状态异步保存到文件"""
        async with self._lock:
            try:
                logger.info(f"正在将知识库保存到 {self.config.kb_file_path}...")
                kb_data_to_save = { 
                    entry_id: dataclasses.asdict(entry) 
                    for entry_id, entry in self._knowledge_base.items() 
                }
                # 将枚举成员转换为字符串值
                for entry_data in kb_data_to_save.values():
                    entry_data['status'] = entry_data['status'].value

                with open(self.config.kb_file_path, 'w', encoding='utf-8') as f:
                    json.dump(kb_data_to_save, f, indent=4, ensure_ascii=False)
                logger.info("知识库保存成功。")
            except IOError as e:
                logger.error(f"保存知识库文件失败: {e}")
                self.status = ServiceStatus.DEGRADED

    async def _generate_embedding(self, text: str) -> List[float]:
        """
        模拟生成文本的向量表示。
        在实际应用中，这里会调用一个真正的 embedding 模型服务。
        """
        logger.debug(f"为文本生成向量: '{text[:30]}...'" )
        # 模拟一个耗时操作
        await asyncio.sleep(0.05)
        # 模拟一个 128 维的向量，实际维度取决于模型
        return [hash(word) / 1e10 for word in text.split()] + [0.0] * (128 - len(text.split()))

    async def add_knowledge(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """添加一条新的知识，并为其生成向量"""
        if self.status != ServiceStatus.RUNNING:
            raise RuntimeError("服务未在运行状态，无法添加知识。")
        
        entry_id = str(uuid.uuid4())
        embedding = await self._generate_embedding(content)
        
        new_entry = KnowledgeEntry(
            id=entry_id,
            content=content,
            metadata=metadata or {},
            embedding=embedding
        )
        
        self._knowledge_base[entry_id] = new_entry
        await self._save_knowledge_base()
        logger.info(f"成功添加知识条目，ID: {entry_id}")
        return entry_id

    async def search_knowledge(self, query: str, top_k: int = 5) -> List[Tuple[str, float, str]]:
        """
        根据查询文本检索最相关的知识。
        当前实现为简单的关键字匹配，未来可升级为向量相似度搜索。
        """
        if self.status != ServiceStatus.RUNNING:
            raise RuntimeError("服务未在运行状态，无法进行检索。")

        logger.info(f"收到检索请求: '{query}'")
        # 在实际应用中，这里会计算查询向量和知识库中所有向量的余弦相似度
        # query_embedding = await self._generate_embedding(query)
        
        # 简化实现：基于关键字匹配计算得分
        results = []
        query_words = set(query.lower().split())
        for entry in self._knowledge_base.values():
            if entry.status == KnowledgeStatus.ACTIVE:
                content_words = set(entry.content.lower().split())
                common_words = query_words.intersection(content_words)
                score = len(common_words)  # 简单的得分策略
                if score > 0:
                    results.append((entry.id, float(score), entry.content))
        
        # 按得分降序排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:min(top_k, self.config.max_results)]

    async def get_knowledge_entry(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """获取指定ID的知识条目"""
        return self._knowledge_base.get(entry_id)

    async def update_knowledge_status(self, entry_id: str, status: KnowledgeStatus) -> bool:
        """更新知识条目的状态（如归档）"""
        if entry_id in self._knowledge_base:
            self._knowledge_base[entry_id].status = status
            self._knowledge_base[entry_id].updated_at = str(asyncio.get_event_loop().time())
            await self._save_knowledge_base()
            logger.info(f"知识条目 {entry_id} 状态已更新为 {status.value}")
            return True
        return False

    async def health_check(self) -> Dict[str, Any]:
        """提供健康检查接口，返回服务当前状态和统计信息"""
        return {
            "node_id": self.config.node_id,
            "service_status": self.status.value,
            "timestamp": asyncio.get_event_loop().time(),
            "knowledge_count": len(self._knowledge_base),
            "kb_file_path": self.config.kb_file_path,
            "config_file_path": self.config_path
        }

    async def get_status(self) -> Dict[str, Any]:
        """获取服务的详细状态"""
        return await self.health_check()

async def main():
    """主执行函数"""
    logger.info("启动 Node_72_KnowledgeBase 服务...")
    service = KnowledgeBaseService()

    # 等待服务完成初始化
    while service.status == ServiceStatus.INITIALIZING:
        await asyncio.sleep(0.1)

    if service.status == ServiceStatus.ERROR:
        logger.error("服务启动失败，请检查日志。")
        return

    logger.info("服务启动成功，进入运行状态。")

    # --- 模拟一些操作 ---
    try:
        # 1. 添加一些知识
        await service.add_knowledge("UFO Galaxy 是一个面向未来的分布式智能操作系统。", {"source": "official_doc"})
        await service.add_knowledge("知识库节点使用向量数据库存储和检索信息。", {"source": "tech_spec"})
        await service.add_knowledge("Python 是世界上最受欢迎的编程语言之一。", {"source": "survey_2024"})

        # 2. 进行一次检索
        query = "UFO Galaxy 是什么"
        search_results = await service.search_knowledge(query)
        logger.info(f"对 '{query}' 的检索结果:")
        for entry_id, score, content in search_results:
            logger.info(f"  - ID: {entry_id}, Score: {score}, Content: {content}")

        # 3. 归档一条知识
        if search_results:
            entry_to_archive = search_results[0][0]
            await service.update_knowledge_status(entry_to_archive, KnowledgeStatus.ARCHIVED)

        # 4. 再次检索，确认归档生效
        search_results_after_archive = await service.search_knowledge(query)
        logger.info(f"归档后，对 '{query}' 的检索结果:")
        for entry_id, score, content in search_results_after_archive:
            logger.info(f"  - ID: {entry_id}, Score: {score}, Content: {content}")

        # 5. 保持服务运行，模拟一个后台服务
        logger.info("服务正在后台运行，按 Ctrl+C 退出。")
        while True:
            await asyncio.sleep(60)
            health = await service.health_check()
            logger.debug(f"健康检查: {health}")

    except asyncio.CancelledError:
        logger.info("服务被终止。")
    except Exception as e:
        logger.error(f"服务运行时发生未捕获的异常: {e}", exc_info=True)
    finally:
        logger.info("服务正在关闭...")
        service.status = ServiceStatus.STOPPED

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("收到用户中断信号，程序退出。")

