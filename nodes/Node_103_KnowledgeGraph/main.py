"""
Node_103_KnowledgeGraph - 知识图谱和推理引擎

功能：
1. 知识存储（实体、关系、属性）
2. 知识检索（查询和搜索）
3. 知识推理（逻辑推理）
4. 知识关联（发现关联）
5. 解释生成（解释决策）

技术栈：
- SQLite（知识存储）
- 图算法（关系推理）
- LLM（知识提取和推理）

版本：1.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node_103_KnowledgeGraph", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# 配置
# ============================================================================

DB_PATH = os.getenv("KNOWLEDGE_DB_PATH", "/tmp/galaxy_knowledge.db")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-be72ac32a25e4de08ef261d50feebb60")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")

# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class Entity:
    """实体"""
    id: str
    name: str
    type: str
    properties: Dict[str, Any]
    created_at: str

@dataclass
class Relation:
    """关系"""
    id: str
    from_entity: str
    to_entity: str
    relation_type: str
    properties: Dict[str, Any]
    created_at: str

@dataclass
class ReasoningResult:
    """推理结果"""
    conclusion: str
    confidence: float
    reasoning_path: List[str]
    explanation: str

class AddEntityRequest(BaseModel):
    """添加实体请求"""
    name: str
    type: str
    properties: Dict[str, Any] = {}

class AddRelationRequest(BaseModel):
    """添加关系请求"""
    from_entity: str
    to_entity: str
    relation_type: str
    properties: Dict[str, Any] = {}

class QueryRequest(BaseModel):
    """查询请求"""
    query: str
    limit: int = 10

class ReasonRequest(BaseModel):
    """推理请求"""
    facts: List[str]
    question: str

class FindPathRequest(BaseModel):
    """查找路径请求"""
    from_entity: str
    to_entity: str
    max_depth: int = 5

# ============================================================================
# 知识图谱数据库
# ============================================================================

class KnowledgeGraphDB:
    """知识图谱数据库"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建实体表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                properties TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        # 创建关系表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY,
                from_entity TEXT NOT NULL,
                to_entity TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                properties TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (from_entity) REFERENCES entities(id),
                FOREIGN KEY (to_entity) REFERENCES entities(id)
            )
        """)
        
        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_name ON entities(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relation_from ON relations(from_entity)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relation_to ON relations(to_entity)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relation_type ON relations(relation_type)")
        
        conn.commit()
        conn.close()
    
    def add_entity(self, entity: Entity) -> bool:
        """添加实体"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO entities 
                (id, name, type, properties, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                entity.id,
                entity.name,
                entity.type,
                json.dumps(entity.properties),
                entity.created_at
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding entity: {e}")
            return False
    
    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """获取实体"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return Entity(
                    id=row[0],
                    name=row[1],
                    type=row[2],
                    properties=json.loads(row[3]),
                    created_at=row[4]
                )
            return None
        except Exception as e:
            print(f"Error getting entity: {e}")
            return None
    
    def find_entities(self, name: Optional[str] = None, entity_type: Optional[str] = None) -> List[Entity]:
        """查找实体"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            query = "SELECT * FROM entities WHERE 1=1"
            params = []
            
            if name:
                query += " AND name LIKE ?"
                params.append(f"%{name}%")
            
            if entity_type:
                query += " AND type = ?"
                params.append(entity_type)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            
            entities = []
            for row in rows:
                entities.append(Entity(
                    id=row[0],
                    name=row[1],
                    type=row[2],
                    properties=json.loads(row[3]),
                    created_at=row[4]
                ))
            
            return entities
        except Exception as e:
            print(f"Error finding entities: {e}")
            return []
    
    def add_relation(self, relation: Relation) -> bool:
        """添加关系"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO relations 
                (id, from_entity, to_entity, relation_type, properties, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                relation.id,
                relation.from_entity,
                relation.to_entity,
                relation.relation_type,
                json.dumps(relation.properties),
                relation.created_at
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding relation: {e}")
            return False
    
    def get_relations(self, entity_id: str, direction: str = "both") -> List[Relation]:
        """获取实体的关系"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if direction == "out":
                query = "SELECT * FROM relations WHERE from_entity = ?"
            elif direction == "in":
                query = "SELECT * FROM relations WHERE to_entity = ?"
            else:  # both
                query = "SELECT * FROM relations WHERE from_entity = ? OR to_entity = ?"
                cursor.execute(query, (entity_id, entity_id))
                rows = cursor.fetchall()
                conn.close()
                
                relations = []
                for row in rows:
                    relations.append(Relation(
                        id=row[0],
                        from_entity=row[1],
                        to_entity=row[2],
                        relation_type=row[3],
                        properties=json.loads(row[4]),
                        created_at=row[5]
                    ))
                
                return relations
            
            cursor.execute(query, (entity_id,))
            rows = cursor.fetchall()
            conn.close()
            
            relations = []
            for row in rows:
                relations.append(Relation(
                    id=row[0],
                    from_entity=row[1],
                    to_entity=row[2],
                    relation_type=row[3],
                    properties=json.loads(row[4]),
                    created_at=row[5]
                ))
            
            return relations
        except Exception as e:
            print(f"Error getting relations: {e}")
            return []

# 初始化数据库
db = KnowledgeGraphDB(DB_PATH)

# ============================================================================
# 推理引擎
# ============================================================================

class ReasoningEngine:
    """推理引擎"""
    
    def __init__(self, db: KnowledgeGraphDB):
        self.db = db
    
    def find_path(self, from_entity: str, to_entity: str, max_depth: int = 5) -> List[List[str]]:
        """查找两个实体之间的路径（BFS）"""
        # BFS 查找所有路径
        queue = deque([(from_entity, [from_entity])])
        visited = set()
        paths = []
        
        while queue and len(paths) < 10:  # 限制路径数量
            current, path = queue.popleft()
            
            if len(path) > max_depth:
                continue
            
            if current == to_entity:
                paths.append(path)
                continue
            
            if current in visited:
                continue
            
            visited.add(current)
            
            # 获取出边
            relations = self.db.get_relations(current, "out")
            for rel in relations:
                if rel.to_entity not in path:  # 避免环路
                    queue.append((rel.to_entity, path + [rel.to_entity]))
        
        return paths
    
    def reason(self, facts: List[str], question: str) -> ReasoningResult:
        """推理"""
        # 简单的基于规则的推理
        reasoning_path = []
        conclusion = "无法推理出结论"
        confidence = 0.0
        
        # 使用 LLM 进行推理
        if DEEPSEEK_API_KEY:
            llm_result = self._llm_reason(facts, question)
            if llm_result:
                conclusion = llm_result.get("conclusion", conclusion)
                confidence = llm_result.get("confidence", 0.5)
                reasoning_path = llm_result.get("reasoning_path", [])
        
        explanation = f"基于 {len(facts)} 个事实进行推理"
        
        return ReasoningResult(
            conclusion=conclusion,
            confidence=confidence,
            reasoning_path=reasoning_path,
            explanation=explanation
        )
    
    def _llm_reason(self, facts: List[str], question: str) -> Optional[Dict[str, Any]]:
        """使用 LLM 进行推理"""
        try:
            import httpx
            
            facts_str = "\n".join([f"{i+1}. {fact}" for i, fact in enumerate(facts)])
            
            response = httpx.post(
                f"{DEEPSEEK_API_BASE}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个逻辑推理专家，帮助用户基于已知事实进行推理。"
                        },
                        {
                            "role": "user",
                            "content": f"已知事实:\n{facts_str}\n\n问题: {question}\n\n请进行推理并给出结论。"
                        }
                    ],
                    "temperature": 0.3
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                result = response.json()
                conclusion = result["choices"][0]["message"]["content"]
                
                return {
                    "conclusion": conclusion,
                    "confidence": 0.8,
                    "reasoning_path": facts
                }
            else:
                return None
        
        except Exception as e:
            return None
    
    def find_related(self, entity_id: str, max_hops: int = 2) -> List[Tuple[str, int]]:
        """查找相关实体"""
        related = {}
        visited = set()
        queue = deque([(entity_id, 0)])
        
        while queue:
            current, hops = queue.popleft()
            
            if hops >= max_hops:
                continue
            
            if current in visited:
                continue
            
            visited.add(current)
            
            # 获取所有关系
            relations = self.db.get_relations(current, "both")
            for rel in relations:
                # 确定相关实体
                related_entity = rel.to_entity if rel.from_entity == current else rel.from_entity
                
                if related_entity not in related:
                    related[related_entity] = hops + 1
                    queue.append((related_entity, hops + 1))
        
        # 返回按距离排序的相关实体
        return sorted(related.items(), key=lambda x: x[1])

# 初始化推理引擎
reasoning_engine = ReasoningEngine(db)

# ============================================================================
# API 端点
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "name": "Node_103_KnowledgeGraph",
        "database": os.path.exists(DB_PATH),
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/add_entity")
async def add_entity(request: AddEntityRequest) -> Dict[str, Any]:
    """添加实体"""
    entity_id = hashlib.md5(f"{request.name}{request.type}".encode()).hexdigest()
    
    entity = Entity(
        id=entity_id,
        name=request.name,
        type=request.type,
        properties=request.properties,
        created_at=datetime.now().isoformat()
    )
    
    success = db.add_entity(entity)
    
    return {
        "success": success,
        "entity_id": entity_id
    }

@app.get("/get_entity/{entity_id}")
async def get_entity(entity_id: str) -> Dict[str, Any]:
    """获取实体"""
    entity = db.get_entity(entity_id)
    
    if entity:
        return {
            "success": True,
            "entity": asdict(entity)
        }
    else:
        return {
            "success": False,
            "error": "实体不存在"
        }

@app.post("/find_entities")
async def find_entities(name: Optional[str] = None, entity_type: Optional[str] = None) -> Dict[str, Any]:
    """查找实体"""
    entities = db.find_entities(name, entity_type)
    
    return {
        "success": True,
        "count": len(entities),
        "entities": [asdict(e) for e in entities]
    }

@app.post("/add_relation")
async def add_relation(request: AddRelationRequest) -> Dict[str, Any]:
    """添加关系"""
    relation_id = hashlib.md5(
        f"{request.from_entity}{request.to_entity}{request.relation_type}".encode()
    ).hexdigest()
    
    relation = Relation(
        id=relation_id,
        from_entity=request.from_entity,
        to_entity=request.to_entity,
        relation_type=request.relation_type,
        properties=request.properties,
        created_at=datetime.now().isoformat()
    )
    
    success = db.add_relation(relation)
    
    return {
        "success": success,
        "relation_id": relation_id
    }

@app.get("/get_relations/{entity_id}")
async def get_relations(entity_id: str, direction: str = "both") -> Dict[str, Any]:
    """获取实体的关系"""
    relations = db.get_relations(entity_id, direction)
    
    return {
        "success": True,
        "count": len(relations),
        "relations": [asdict(r) for r in relations]
    }

@app.post("/find_path")
async def find_path(request: FindPathRequest) -> Dict[str, Any]:
    """查找路径"""
    paths = reasoning_engine.find_path(request.from_entity, request.to_entity, request.max_depth)
    
    return {
        "success": True,
        "count": len(paths),
        "paths": paths
    }

@app.post("/reason")
async def reason(request: ReasonRequest) -> Dict[str, Any]:
    """推理"""
    result = reasoning_engine.reason(request.facts, request.question)
    
    return {
        "success": True,
        "result": asdict(result)
    }

@app.get("/find_related/{entity_id}")
async def find_related(entity_id: str, max_hops: int = 2) -> Dict[str, Any]:
    """查找相关实体"""
    related = reasoning_engine.find_related(entity_id, max_hops)
    
    return {
        "success": True,
        "count": len(related),
        "related": [{"entity_id": e, "distance": d} for e, d in related]
    }

@app.get("/stats")
async def stats() -> Dict[str, Any]:
    """统计信息"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM entities")
    entity_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM relations")
    relation_count = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "success": True,
        "entity_count": entity_count,
        "relation_count": relation_count,
        "database_path": DB_PATH,
        "database_size_mb": os.path.getsize(DB_PATH) / 1024 / 1024 if os.path.exists(DB_PATH) else 0
    }

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8103)
