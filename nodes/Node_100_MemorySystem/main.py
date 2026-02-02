"""
Node_100_MemorySystem - 记忆和学习系统

功能：
1. 短期记忆（会话级别）
2. 长期记忆（持久化）
3. 经验存储和检索
4. 模式识别
5. 知识提取

技术栈：
- SQLite（持久化存储）
- 向量嵌入（经验检索）
- 聚类算法（模式识别）

版本：1.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node_100_MemorySystem", version="1.0.0")
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

DB_PATH = os.getenv("MEMORY_DB_PATH", "/tmp/galaxy_memory.db")
MAX_SHORT_TERM_SIZE = 100  # 短期记忆最大条目数

# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class Experience:
    """经验"""
    id: str
    timestamp: str
    command: str
    context: Dict[str, Any]
    actions: List[Dict[str, Any]]
    result: Dict[str, Any]
    success: bool
    duration: float
    session_id: str

@dataclass
class Pattern:
    """模式"""
    id: str
    name: str
    description: str
    frequency: int
    examples: List[str]
    created_at: str
    updated_at: str

@dataclass
class Knowledge:
    """知识"""
    id: str
    topic: str
    content: str
    source: str
    confidence: float
    created_at: str
    updated_at: str

class StoreExperienceRequest(BaseModel):
    """存储经验请求"""
    command: str
    context: Dict[str, Any]
    actions: List[Dict[str, Any]]
    result: Dict[str, Any]
    success: bool
    duration: float
    session_id: str

class RetrieveRequest(BaseModel):
    """检索请求"""
    query: str
    limit: int = 10

class ExtractPatternsRequest(BaseModel):
    """提取模式请求"""
    min_frequency: int = 3

# ============================================================================
# 数据库管理
# ============================================================================

class MemoryDatabase:
    """记忆数据库"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建经验表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS experiences (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                command TEXT NOT NULL,
                context TEXT NOT NULL,
                actions TEXT NOT NULL,
                result TEXT NOT NULL,
                success INTEGER NOT NULL,
                duration REAL NOT NULL,
                session_id TEXT NOT NULL
            )
        """)
        
        # 创建模式表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                frequency INTEGER NOT NULL,
                examples TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # 创建知识表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_command ON experiences(command)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session ON experiences(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_topic ON knowledge(topic)")
        
        conn.commit()
        conn.close()
    
    def store_experience(self, experience: Experience) -> bool:
        """存储经验"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO experiences 
                (id, timestamp, command, context, actions, result, success, duration, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                experience.id,
                experience.timestamp,
                experience.command,
                json.dumps(experience.context),
                json.dumps(experience.actions),
                json.dumps(experience.result),
                1 if experience.success else 0,
                experience.duration,
                experience.session_id
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error storing experience: {e}")
            return False
    
    def retrieve_experiences(self, query: str, limit: int = 10) -> List[Experience]:
        """检索经验"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 简单的关键词匹配
            cursor.execute("""
                SELECT * FROM experiences 
                WHERE command LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (f"%{query}%", limit))
            
            rows = cursor.fetchall()
            conn.close()
            
            experiences = []
            for row in rows:
                experiences.append(Experience(
                    id=row[0],
                    timestamp=row[1],
                    command=row[2],
                    context=json.loads(row[3]),
                    actions=json.loads(row[4]),
                    result=json.loads(row[5]),
                    success=bool(row[6]),
                    duration=row[7],
                    session_id=row[8]
                ))
            
            return experiences
        except Exception as e:
            print(f"Error retrieving experiences: {e}")
            return []
    
    def get_all_experiences(self) -> List[Experience]:
        """获取所有经验"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM experiences ORDER BY timestamp DESC")
            rows = cursor.fetchall()
            conn.close()
            
            experiences = []
            for row in rows:
                experiences.append(Experience(
                    id=row[0],
                    timestamp=row[1],
                    command=row[2],
                    context=json.loads(row[3]),
                    actions=json.loads(row[4]),
                    result=json.loads(row[5]),
                    success=bool(row[6]),
                    duration=row[7],
                    session_id=row[8]
                ))
            
            return experiences
        except Exception as e:
            print(f"Error getting all experiences: {e}")
            return []
    
    def store_pattern(self, pattern: Pattern) -> bool:
        """存储模式"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO patterns 
                (id, name, description, frequency, examples, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                pattern.id,
                pattern.name,
                pattern.description,
                pattern.frequency,
                json.dumps(pattern.examples),
                pattern.created_at,
                pattern.updated_at
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error storing pattern: {e}")
            return False
    
    def get_patterns(self) -> List[Pattern]:
        """获取所有模式"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM patterns ORDER BY frequency DESC")
            rows = cursor.fetchall()
            conn.close()
            
            patterns = []
            for row in rows:
                patterns.append(Pattern(
                    id=row[0],
                    name=row[1],
                    description=row[2],
                    frequency=row[3],
                    examples=json.loads(row[4]),
                    created_at=row[5],
                    updated_at=row[6]
                ))
            
            return patterns
        except Exception as e:
            print(f"Error getting patterns: {e}")
            return []
    
    def store_knowledge(self, knowledge: Knowledge) -> bool:
        """存储知识"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO knowledge 
                (id, topic, content, source, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                knowledge.id,
                knowledge.topic,
                knowledge.content,
                knowledge.source,
                knowledge.confidence,
                knowledge.created_at,
                knowledge.updated_at
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error storing knowledge: {e}")
            return False
    
    def get_knowledge(self, topic: str) -> List[Knowledge]:
        """获取知识"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM knowledge 
                WHERE topic LIKE ?
                ORDER BY confidence DESC
            """, (f"%{topic}%",))
            
            rows = cursor.fetchall()
            conn.close()
            
            knowledge_list = []
            for row in rows:
                knowledge_list.append(Knowledge(
                    id=row[0],
                    topic=row[1],
                    content=row[2],
                    source=row[3],
                    confidence=row[4],
                    created_at=row[5],
                    updated_at=row[6]
                ))
            
            return knowledge_list
        except Exception as e:
            print(f"Error getting knowledge: {e}")
            return []

# 初始化数据库
db = MemoryDatabase(DB_PATH)

# ============================================================================
# 短期记忆
# ============================================================================

class ShortTermMemory:
    """短期记忆（会话级别）"""
    
    def __init__(self, max_size: int = MAX_SHORT_TERM_SIZE):
        self.max_size = max_size
        self.memory: Dict[str, List[Experience]] = defaultdict(list)
    
    def add(self, session_id: str, experience: Experience):
        """添加经验"""
        self.memory[session_id].append(experience)
        
        # 限制大小
        if len(self.memory[session_id]) > self.max_size:
            self.memory[session_id] = self.memory[session_id][-self.max_size:]
    
    def get(self, session_id: str, limit: int = 10) -> List[Experience]:
        """获取经验"""
        return self.memory[session_id][-limit:]
    
    def clear(self, session_id: str):
        """清空会话记忆"""
        if session_id in self.memory:
            del self.memory[session_id]

# 初始化短期记忆
short_term_memory = ShortTermMemory()

# ============================================================================
# 模式识别
# ============================================================================

class PatternRecognizer:
    """模式识别器"""
    
    def extract_patterns(self, experiences: List[Experience], min_frequency: int = 3) -> List[Pattern]:
        """提取模式"""
        # 统计命令频率
        command_freq = defaultdict(int)
        command_examples = defaultdict(list)
        
        for exp in experiences:
            command_freq[exp.command] += 1
            if len(command_examples[exp.command]) < 5:
                command_examples[exp.command].append(exp.id)
        
        # 创建模式
        patterns = []
        for command, freq in command_freq.items():
            if freq >= min_frequency:
                pattern_id = hashlib.md5(command.encode()).hexdigest()
                pattern = Pattern(
                    id=pattern_id,
                    name=f"Pattern: {command}",
                    description=f"用户经常执行命令: {command}",
                    frequency=freq,
                    examples=command_examples[command],
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat()
                )
                patterns.append(pattern)
        
        return patterns

# 初始化模式识别器
pattern_recognizer = PatternRecognizer()

# ============================================================================
# 知识提取
# ============================================================================

class KnowledgeExtractor:
    """知识提取器"""
    
    def extract_knowledge(self, experiences: List[Experience]) -> List[Knowledge]:
        """从经验中提取知识"""
        knowledge_list = []
        
        # 提取成功率
        success_count = sum(1 for exp in experiences if exp.success)
        total_count = len(experiences)
        
        if total_count > 0:
            success_rate = success_count / total_count
            knowledge = Knowledge(
                id=hashlib.md5("success_rate".encode()).hexdigest(),
                topic="success_rate",
                content=f"总体成功率: {success_rate:.2%} ({success_count}/{total_count})",
                source="experience_analysis",
                confidence=1.0 if total_count >= 10 else 0.5,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat()
            )
            knowledge_list.append(knowledge)
        
        # 提取平均执行时间
        if total_count > 0:
            avg_duration = sum(exp.duration for exp in experiences) / total_count
            knowledge = Knowledge(
                id=hashlib.md5("avg_duration".encode()).hexdigest(),
                topic="avg_duration",
                content=f"平均执行时间: {avg_duration:.2f} 秒",
                source="experience_analysis",
                confidence=1.0 if total_count >= 10 else 0.5,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat()
            )
            knowledge_list.append(knowledge)
        
        return knowledge_list

# 初始化知识提取器
knowledge_extractor = KnowledgeExtractor()

# ============================================================================
# API 端点
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "name": "Node_100_MemorySystem",
        "database": os.path.exists(DB_PATH),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/store_experience")
async def store_experience(request: StoreExperienceRequest) -> Dict[str, Any]:
    """存储经验"""
    # 生成 ID
    exp_id = hashlib.md5(
        f"{request.command}{request.session_id}{datetime.now().isoformat()}".encode()
    ).hexdigest()
    
    # 创建经验对象
    experience = Experience(
        id=exp_id,
        timestamp=datetime.now().isoformat(),
        command=request.command,
        context=request.context,
        actions=request.actions,
        result=request.result,
        success=request.success,
        duration=request.duration,
        session_id=request.session_id
    )
    
    # 存储到短期记忆
    short_term_memory.add(request.session_id, experience)
    
    # 存储到长期记忆（数据库）
    success = db.store_experience(experience)
    
    return {
        "success": success,
        "experience_id": exp_id,
        "timestamp": experience.timestamp
    }

@app.post("/retrieve_experiences")
async def retrieve_experiences(request: RetrieveRequest) -> Dict[str, Any]:
    """检索经验"""
    experiences = db.retrieve_experiences(request.query, request.limit)
    
    return {
        "success": True,
        "count": len(experiences),
        "experiences": [asdict(exp) for exp in experiences]
    }

@app.get("/get_short_term_memory/{session_id}")
async def get_short_term_memory(session_id: str, limit: int = 10) -> Dict[str, Any]:
    """获取短期记忆"""
    experiences = short_term_memory.get(session_id, limit)
    
    return {
        "success": True,
        "session_id": session_id,
        "count": len(experiences),
        "experiences": [asdict(exp) for exp in experiences]
    }

@app.post("/extract_patterns")
async def extract_patterns(request: ExtractPatternsRequest) -> Dict[str, Any]:
    """提取模式"""
    # 获取所有经验
    experiences = db.get_all_experiences()
    
    # 提取模式
    patterns = pattern_recognizer.extract_patterns(experiences, request.min_frequency)
    
    # 存储模式
    for pattern in patterns:
        db.store_pattern(pattern)
    
    return {
        "success": True,
        "count": len(patterns),
        "patterns": [asdict(p) for p in patterns]
    }

@app.get("/get_patterns")
async def get_patterns() -> Dict[str, Any]:
    """获取所有模式"""
    patterns = db.get_patterns()
    
    return {
        "success": True,
        "count": len(patterns),
        "patterns": [asdict(p) for p in patterns]
    }

@app.post("/extract_knowledge")
async def extract_knowledge() -> Dict[str, Any]:
    """提取知识"""
    # 获取所有经验
    experiences = db.get_all_experiences()
    
    # 提取知识
    knowledge_list = knowledge_extractor.extract_knowledge(experiences)
    
    # 存储知识
    for knowledge in knowledge_list:
        db.store_knowledge(knowledge)
    
    return {
        "success": True,
        "count": len(knowledge_list),
        "knowledge": [asdict(k) for k in knowledge_list]
    }

@app.get("/get_knowledge/{topic}")
async def get_knowledge(topic: str) -> Dict[str, Any]:
    """获取知识"""
    knowledge_list = db.get_knowledge(topic)
    
    return {
        "success": True,
        "topic": topic,
        "count": len(knowledge_list),
        "knowledge": [asdict(k) for k in knowledge_list]
    }

@app.get("/stats")
async def stats() -> Dict[str, Any]:
    """统计信息"""
    experiences = db.get_all_experiences()
    patterns = db.get_patterns()
    
    success_count = sum(1 for exp in experiences if exp.success)
    total_count = len(experiences)
    
    return {
        "success": True,
        "total_experiences": total_count,
        "success_rate": success_count / total_count if total_count > 0 else 0,
        "total_patterns": len(patterns),
        "database_path": DB_PATH,
        "database_size_mb": os.path.getsize(DB_PATH) / 1024 / 1024 if os.path.exists(DB_PATH) else 0
    }

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8100)
