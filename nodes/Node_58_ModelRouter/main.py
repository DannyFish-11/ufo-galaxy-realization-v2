"""
Node 58: Model Router (Cost/Logic)
UFO Galaxy 64-Core MCP Matrix - DeepSeek Audited Architecture

Intelligent routing of AI requests based on:
- Task complexity (multi-dimensional scoring)
- Cost optimization
- Model availability
- Failover handling
- Session persistence (SQLite)
"""

import os
import json
import asyncio
import logging
import re
import sqlite3
import hashlib
from typing import Dict, Optional, List, Any
from datetime import datetime
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "58")
NODE_NAME = os.getenv("NODE_NAME", "ModelRouter")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
TRANSFORMER_URL = os.getenv("TRANSFORMER_URL", "http://localhost:8050")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
ONEAPI_URL = os.getenv("ONEAPI_URL", "http://localhost:3000")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_PATH = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "data", "router.db"))

# API Keys from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Database Manager (SQLite Persistence)
# =============================================================================

class DatabaseManager:
    """SQLite database manager for routing decisions and session history."""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._ensure_directory()
        self._init_database()
    
    def _ensure_directory(self):
        """Ensure database directory exists."""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
    
    def _init_database(self):
        """Initialize database tables."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Routing decisions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS routing_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                prompt_hash TEXT,
                prompt_preview TEXT,
                complexity_score REAL,
                target_model TEXT,
                model_tier TEXT,
                routing_reason TEXT,
                estimated_cost REAL,
                estimated_tokens INTEGER,
                response_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Session history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                turn_number INTEGER,
                role TEXT,
                content TEXT,
                model_used TEXT,
                tokens_used INTEGER,
                cost_usd REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Usage statistics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usage_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE,
                total_requests INTEGER DEFAULT 0,
                local_requests INTEGER DEFAULT 0,
                cloud_requests INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                total_cost_usd REAL DEFAULT 0.0
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_routing_session 
            ON routing_decisions(session_id, created_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_history 
            ON session_history(session_id, turn_number)
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")
    
    def save_routing_decision(
        self,
        session_id: str,
        prompt: str,
        complexity_score: float,
        target_model: str,
        model_tier: str,
        reason: str,
        estimated_cost: float,
        estimated_tokens: int,
        response_time_ms: int
    ):
        """Save a routing decision to database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:16]
            prompt_preview = prompt[:200] + "..." if len(prompt) > 200 else prompt
            
            cursor.execute("""
                INSERT INTO routing_decisions 
                (session_id, prompt_hash, prompt_preview, complexity_score, 
                 target_model, model_tier, routing_reason, estimated_cost, 
                 estimated_tokens, response_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, prompt_hash, prompt_preview, complexity_score,
                target_model, model_tier, reason, estimated_cost,
                estimated_tokens, response_time_ms
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save routing decision: {e}")
    
    def save_session_turn(
        self,
        session_id: str,
        turn_number: int,
        role: str,
        content: str,
        model_used: str,
        tokens_used: int,
        cost_usd: float
    ):
        """Save a session turn to database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO session_history 
                (session_id, turn_number, role, content, model_used, tokens_used, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, turn_number, role, 
                content[:1000], model_used, tokens_used, cost_usd
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save session turn: {e}")
    
    def get_session_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Get session history."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT turn_number, role, content, model_used, tokens_used, cost_usd, created_at
                FROM session_history
                WHERE session_id = ?
                ORDER BY turn_number DESC
                LIMIT ?
            """, (session_id, limit))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get session history: {e}")
            return []
    
    def get_routing_stats(self, session_id: str = None) -> Dict:
        """Get routing statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if session_id:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_requests,
                        AVG(complexity_score) as avg_complexity,
                        AVG(response_time_ms) as avg_response_time,
                        SUM(estimated_cost) as total_cost,
                        SUM(estimated_tokens) as total_tokens
                    FROM routing_decisions
                    WHERE session_id = ?
                """, (session_id,))
            else:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_requests,
                        AVG(complexity_score) as avg_complexity,
                        AVG(response_time_ms) as avg_response_time,
                        SUM(estimated_cost) as total_cost,
                        SUM(estimated_tokens) as total_tokens
                    FROM routing_decisions
                """)
            
            row = cursor.fetchone()
            conn.close()
            
            return {
                "total_requests": row[0] or 0,
                "avg_complexity": round(row[1] or 0, 3),
                "avg_response_time_ms": int(row[2] or 0),
                "total_cost_usd": round(row[3] or 0, 4),
                "total_tokens": row[4] or 0
            }
        except Exception as e:
            logger.error(f"Failed to get routing stats: {e}")
            return {}
    
    def get_recent_decisions(self, limit: int = 10) -> List[Dict]:
        """Get recent routing decisions."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT session_id, prompt_preview, target_model, model_tier,
                       complexity_score, estimated_cost, created_at
                FROM routing_decisions
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get recent decisions: {e}")
            return []

# =============================================================================
# Models
# =============================================================================

class ModelTier(str, Enum):
    LOCAL = "local"
    CLOUD_CHEAP = "cloud_cheap"
    CLOUD_SMART = "cloud_smart"
    CLOUD_PREMIUM = "cloud_premium"

class RouteRequest(BaseModel):
    prompt: str = Field(..., description="The prompt to route")
    session_id: str = Field(default="default", description="Session ID for history")
    context: Dict[str, Any] = Field(default={}, description="Additional context")
    prefer_local: bool = Field(default=False, description="Prefer local models")
    max_cost_usd: float = Field(default=1.0, description="Maximum cost in USD")
    require_vision: bool = Field(default=False, description="Requires vision capability")
    require_code: bool = Field(default=False, description="Requires code capability")
    include_history: bool = Field(default=True, description="Include session history")

class RouteResponse(BaseModel):
    selected_model: str
    model_tier: ModelTier
    reason: str
    complexity_score: float
    complexity_analysis: Dict[str, Any]
    estimated_cost_usd: float
    estimated_tokens: int
    fallback_model: Optional[str] = None
    session_context: Dict[str, Any] = {}

class ChatRequest(BaseModel):
    prompt: str
    session_id: str = Field(default="default")
    model: Optional[str] = None
    context: Dict[str, Any] = Field(default={})
    max_tokens: int = Field(default=2048)
    temperature: float = Field(default=0.7)

class ChatResponse(BaseModel):
    response: str
    model_used: str
    tokens_used: int
    cost_usd: float
    latency_ms: float
    routed_by: str = "Node 58"

# =============================================================================
# Model Configuration
# =============================================================================

MODEL_CONFIG = {
    # Local Models (Ollama)
    "llama2": {
        "tier": ModelTier.LOCAL,
        "provider": "ollama",
        "cost_per_1k_tokens": 0.0,
        "max_tokens": 4096,
        "capabilities": ["chat", "code_basic"],
        "speed": "fast"
    },
    "llama3": {
        "tier": ModelTier.LOCAL,
        "provider": "ollama",
        "cost_per_1k_tokens": 0.0,
        "max_tokens": 8192,
        "capabilities": ["chat", "code", "reasoning"],
        "speed": "fast"
    },
    "codellama": {
        "tier": ModelTier.LOCAL,
        "provider": "ollama",
        "cost_per_1k_tokens": 0.0,
        "max_tokens": 16384,
        "capabilities": ["code", "code_advanced"],
        "speed": "medium"
    },
    "mistral": {
        "tier": ModelTier.LOCAL,
        "provider": "ollama",
        "cost_per_1k_tokens": 0.0,
        "max_tokens": 8192,
        "capabilities": ["chat", "reasoning"],
        "speed": "fast"
    },
    
    # Cloud Cheap
    "gpt-3.5-turbo": {
        "tier": ModelTier.CLOUD_CHEAP,
        "provider": "openai",
        "cost_per_1k_tokens": 0.0015,
        "max_tokens": 16384,
        "capabilities": ["chat", "code", "reasoning"],
        "speed": "fast"
    },
    "claude-3-haiku": {
        "tier": ModelTier.CLOUD_CHEAP,
        "provider": "anthropic",
        "cost_per_1k_tokens": 0.00025,
        "max_tokens": 200000,
        "capabilities": ["chat", "code", "reasoning", "vision"],
        "speed": "fast"
    },
    
    # Cloud Smart
    "gpt-4": {
        "tier": ModelTier.CLOUD_SMART,
        "provider": "openai",
        "cost_per_1k_tokens": 0.03,
        "max_tokens": 8192,
        "capabilities": ["chat", "code", "reasoning", "code_advanced", "analysis"],
        "speed": "medium"
    },
    "claude-3-sonnet": {
        "tier": ModelTier.CLOUD_SMART,
        "provider": "anthropic",
        "cost_per_1k_tokens": 0.003,
        "max_tokens": 200000,
        "capabilities": ["chat", "code", "reasoning", "vision", "analysis"],
        "speed": "medium"
    },
    
    # Cloud Premium
    "gpt-4-turbo": {
        "tier": ModelTier.CLOUD_PREMIUM,
        "provider": "openai",
        "cost_per_1k_tokens": 0.01,
        "max_tokens": 128000,
        "capabilities": ["chat", "code", "reasoning", "code_advanced", "analysis", "vision"],
        "speed": "medium"
    },
    "claude-3-opus": {
        "tier": ModelTier.CLOUD_PREMIUM,
        "provider": "anthropic",
        "cost_per_1k_tokens": 0.015,
        "max_tokens": 200000,
        "capabilities": ["chat", "code", "reasoning", "code_advanced", "analysis", "vision", "creative"],
        "speed": "slow"
    },
}

# =============================================================================
# Enhanced Complexity Judge (Multi-dimensional Scoring)
# =============================================================================

class ComplexityJudge:
    """
    Enhanced complexity analyzer with multi-dimensional scoring.
    
    Scoring dimensions:
    - Length score (30%)
    - Keyword score (30%)
    - Pattern score (20%)
    - Structure score (10%)
    - Special character score (10%)
    """
    
    # Simple keywords -> route to local
    SIMPLE_KEYWORDS = {
        "time", "weather", "status", "hello", "hi", "thanks", "help",
        "what is", "who is", "when", "where", "ok", "okay", "yes", "no",
        "时间", "天气", "你好", "谢谢", "帮助",
        "list", "show", "display", "get", "ping", "echo"
    }
    
    # Medium complexity keywords
    MEDIUM_KEYWORDS = {
        "explain", "how to", "compare", "difference", "summary", "summarize",
        "translate", "convert", "calculate", "analyze", "describe",
        "解释", "如何", "比较", "总结", "翻译", "计算", "分析"
    }
    
    # High complexity keywords
    COMPLEX_KEYWORDS = {
        "complex", "advanced", "optimize", "algorithm", "architecture",
        "quantum", "physics", "mathematical", "proof", "theorem",
        "research", "dissertation", "comprehensive", "in-depth",
        "implement", "recursive", "distributed", "scalable", "microservice",
        "复杂", "高级", "优化", "算法", "架构", "量子", "物理", "数学"
    }
    
    # High complexity patterns (regex)
    HIGH_COMPLEXITY_PATTERNS = [
        r"write.*code.*for",
        r"implement.*function.*that",
        r"design.*system.*for",
        r"explain.*concept.*of",
        r"compare.*and.*contrast",
        r"what.*is.*difference.*between",
        r"how.*to.*optimize",
        r"best.*practice.*for",
        r"calculate.*the.*probability",
        r"analyze.*the.*following"
    ]
    
    # Code indicators
    CODE_PATTERNS = [
        r"```",
        r"def\s+\w+",
        r"function\s+\w+",
        r"class\s+\w+",
        r"import\s+\w+",
        r"#include",
        r"public\s+class",
    ]
    
    def __init__(self):
        self.code_regex = [re.compile(p, re.IGNORECASE) for p in self.CODE_PATTERNS]
        self.complex_patterns = [re.compile(p, re.IGNORECASE) for p in self.HIGH_COMPLEXITY_PATTERNS]
    
    def judge(self, prompt: str, context: Dict = None) -> Dict:
        """
        Judge the complexity of a prompt with multi-dimensional scoring.
        
        Returns:
            Dict with complexity_score (0-1), detailed analysis, and recommended_tier
        """
        prompt_lower = prompt.lower()
        analysis = {
            "length": len(prompt),
            "word_count": len(prompt.split()),
            "sentence_count": len(re.split(r'[.!?]+', prompt)),
            "factors": []
        }
        
        # Dimension 1: Length score (25%)
        # More aggressive scaling for longer prompts
        length_score = min(len(prompt) / 200, 1.0)  # Reach max at 200 chars instead of 500
        analysis["length_score"] = round(length_score, 3)
        analysis["factors"].append(f"length: {len(prompt)} chars")
        
        # Dimension 2: Keyword score (30%)
        keyword_score = 0.0
        
        # Check simple keywords (reduce score)
        simple_matches = sum(1 for kw in self.SIMPLE_KEYWORDS if kw in prompt_lower)
        if simple_matches > 0:
            keyword_score = 0.1
            analysis["factors"].append(f"simple_keywords: {simple_matches}")
        
        # Check medium keywords
        medium_matches = sum(1 for kw in self.MEDIUM_KEYWORDS if kw in prompt_lower)
        if medium_matches > 0:
            keyword_score = max(keyword_score, 0.3 + medium_matches * 0.1)
            analysis["factors"].append(f"medium_keywords: {medium_matches}")
        
        # Check complex keywords
        complex_matches = sum(1 for kw in self.COMPLEX_KEYWORDS if kw in prompt_lower)
        if complex_matches > 0:
            keyword_score = max(keyword_score, 0.6 + complex_matches * 0.1)
            analysis["factors"].append(f"complex_keywords: {complex_matches}")
        
        keyword_score = min(keyword_score, 1.0)
        if keyword_score == 0.0:
            keyword_score = 0.3  # Default
        analysis["keyword_score"] = round(keyword_score, 3)
        
        # Dimension 3: Pattern score (20%)
        pattern_score = 0.0
        for regex in self.complex_patterns:
            if regex.search(prompt_lower):
                pattern_score += 0.15
        pattern_score = min(pattern_score, 0.6)
        
        # Code detection
        code_detected = False
        for regex in self.code_regex:
            if regex.search(prompt):
                code_detected = True
                pattern_score = max(pattern_score, 0.5)
                analysis["factors"].append("code_detected")
                break
        
        analysis["pattern_score"] = round(pattern_score, 3)
        analysis["has_code"] = code_detected
        
        # Dimension 4: Structure score (10%)
        structure_score = 0.3
        sentence_count = analysis["sentence_count"]
        if sentence_count > 3:
            structure_score = 0.5
            analysis["factors"].append(f"multi_sentence: {sentence_count}")
        if prompt.count("?") > 2:
            structure_score = max(structure_score, 0.6)
            analysis["factors"].append("multiple_questions")
        if "\n" in prompt and len(prompt.split("\n")) > 5:
            structure_score = max(structure_score, 0.7)
            analysis["factors"].append("multi_line")
        analysis["structure_score"] = round(structure_score, 3)
        
        # Dimension 5: Special character score (10%)
        special_chars = sum(1 for char in prompt if char in '{}[]()<>;=+-*/%^&|~`')
        special_score = min(special_chars * 0.03, 0.5)
        analysis["special_score"] = round(special_score, 3)
        analysis["special_char_count"] = special_chars
        
        # Calculate final weighted score
        # Adjusted weights: keywords and patterns more important
        complexity_score = (
            length_score * 0.20 +
            keyword_score * 0.40 +
            pattern_score * 0.25 +
            structure_score * 0.10 +
            special_score * 0.05
        )
        
        # Determine recommended tier
        # Adjusted thresholds for better distribution
        if complexity_score < 0.20:
            recommended_tier = ModelTier.LOCAL
            complexity_level = "very_low"
        elif complexity_score < 0.35:
            recommended_tier = ModelTier.LOCAL
            complexity_level = "low"
        elif complexity_score < 0.50:
            recommended_tier = ModelTier.CLOUD_CHEAP
            complexity_level = "medium"
        elif complexity_score < 0.65:
            recommended_tier = ModelTier.CLOUD_SMART
            complexity_level = "high"
        else:
            recommended_tier = ModelTier.CLOUD_PREMIUM
            complexity_level = "very_high"
        
        analysis["complexity_level"] = complexity_level
        analysis["is_simple_query"] = complexity_score < 0.3 or len(prompt) < 50
        
        return {
            "complexity_score": round(complexity_score, 3),
            "analysis": analysis,
            "recommended_tier": recommended_tier,
            "estimated_tokens": len(prompt.split()) * 2  # Rough estimate
        }

# =============================================================================
# Cost Estimator
# =============================================================================

class CostEstimator:
    """Estimate costs for model requests."""
    
    @staticmethod
    def estimate(prompt: str, model: str, include_response: bool = True) -> Dict:
        """
        Estimate cost for a request.
        
        Args:
            prompt: The input prompt
            model: Model name
            include_response: Whether to include estimated response tokens
        
        Returns:
            Dict with cost breakdown
        """
        model_config = MODEL_CONFIG.get(model, MODEL_CONFIG["llama2"])
        
        # Estimate tokens (rough: 1 word ≈ 1.3 tokens)
        input_tokens = int(len(prompt.split()) * 1.3)
        output_tokens = input_tokens if include_response else 0  # Assume similar length
        total_tokens = input_tokens + output_tokens
        
        # Calculate cost
        cost_per_1k = model_config["cost_per_1k_tokens"]
        input_cost = (input_tokens / 1000) * cost_per_1k
        output_cost = (output_tokens / 1000) * cost_per_1k * 2  # Output typically costs more
        total_cost = input_cost + output_cost
        
        return {
            "model": model,
            "tier": model_config["tier"].value,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "input_cost_usd": round(input_cost, 6),
            "output_cost_usd": round(output_cost, 6),
            "total_cost_usd": round(total_cost, 6),
            "is_free": cost_per_1k == 0,
            "estimated_time_ms": int(total_tokens * (10 if model_config["speed"] == "fast" else 20))
        }

# =============================================================================
# Model Router
# =============================================================================

class ModelRouter:
    """Intelligent model router with failover and persistence support."""
    
    def __init__(self, ollama_url: str, oneapi_url: str, db: DatabaseManager):
        self.ollama_url = ollama_url
        self.oneapi_url = oneapi_url
        self.judge = ComplexityJudge()
        self.cost_estimator = CostEstimator()
        self.db = db
        self.http_client = httpx.AsyncClient(timeout=60.0)
        
        # Track model availability
        self.model_health: Dict[str, bool] = {}
        
        # In-memory usage statistics
        self.usage_stats = {
            "total_requests": 0,
            "local_requests": 0,
            "cloud_requests": 0,
            "total_cost_usd": 0.0,
            "total_tokens": 0
        }
    
    async def route(
        self, 
        request: RouteRequest, 
        background_tasks: BackgroundTasks = None
    ) -> RouteResponse:
        """Route a request to the appropriate model."""
        import time
        start_time = time.time()
        
        # Judge complexity
        judgment = self.judge.judge(request.prompt, request.context)
        complexity_score = judgment["complexity_score"]
        recommended_tier = judgment["recommended_tier"]
        estimated_tokens = judgment["estimated_tokens"]
        
        # Override if prefer_local
        if request.prefer_local:
            recommended_tier = ModelTier.LOCAL
        
        # Select model based on tier and requirements
        selected_model = self._select_model(
            tier=recommended_tier,
            require_vision=request.require_vision,
            require_code=request.require_code,
            max_cost=request.max_cost_usd,
            estimated_tokens=estimated_tokens
        )
        
        # Get model config
        model_config = MODEL_CONFIG.get(selected_model, MODEL_CONFIG["llama2"])
        
        # Estimate cost
        cost_estimate = self.cost_estimator.estimate(request.prompt, selected_model)
        
        # Determine fallback
        fallback_model = self._get_fallback(selected_model)
        
        # Get session history if requested
        session_context = {"session_id": request.session_id, "history_length": 0}
        if request.include_history:
            history = self.db.get_session_history(request.session_id, limit=5)
            session_context["history_length"] = len(history)
        
        # Build reason
        reason_parts = [
            f"Complexity: {complexity_score:.2f} ({judgment['analysis']['complexity_level']})",
            f"Tier: {recommended_tier.value}",
        ]
        if judgment["analysis"]["factors"]:
            reason_parts.append(f"Factors: {', '.join(judgment['analysis']['factors'][:3])}")
        if request.prefer_local:
            reason_parts.append("(prefer_local override)")
        
        response_time_ms = int((time.time() - start_time) * 1000)
        
        # Save to database in background
        if background_tasks:
            background_tasks.add_task(
                self.db.save_routing_decision,
                request.session_id,
                request.prompt,
                complexity_score,
                selected_model,
                model_config["tier"].value,
                " | ".join(reason_parts),
                cost_estimate["total_cost_usd"],
                estimated_tokens,
                response_time_ms
            )
        
        return RouteResponse(
            selected_model=selected_model,
            model_tier=model_config["tier"],
            reason=" | ".join(reason_parts),
            complexity_score=complexity_score,
            complexity_analysis=judgment["analysis"],
            estimated_cost_usd=cost_estimate["total_cost_usd"],
            estimated_tokens=estimated_tokens,
            fallback_model=fallback_model,
            session_context=session_context
        )
    
    def _select_model(
        self,
        tier: ModelTier,
        require_vision: bool,
        require_code: bool,
        max_cost: float,
        estimated_tokens: int
    ) -> str:
        """Select the best model for the given requirements."""
        candidates = []
        
        for model_name, config in MODEL_CONFIG.items():
            if config["tier"] != tier:
                continue
            if require_vision and "vision" not in config["capabilities"]:
                continue
            if require_code and "code" not in config["capabilities"]:
                continue
            
            estimated_cost = (estimated_tokens / 1000) * config["cost_per_1k_tokens"]
            if estimated_cost > max_cost:
                continue
            
            candidates.append((model_name, config))
        
        if not candidates:
            return "llama2"
        
        candidates.sort(key=lambda x: x[1]["cost_per_1k_tokens"])
        return candidates[0][0]
    
    def _get_fallback(self, primary_model: str) -> Optional[str]:
        """Get fallback model for a primary model."""
        config = MODEL_CONFIG.get(primary_model)
        if not config:
            return "llama2"
        
        tier = config["tier"]
        fallback_map = {
            ModelTier.CLOUD_PREMIUM: "gpt-4",
            ModelTier.CLOUD_SMART: "gpt-3.5-turbo",
            ModelTier.CLOUD_CHEAP: "llama3",
            ModelTier.LOCAL: None
        }
        return fallback_map.get(tier)
    
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Execute a chat request with automatic routing."""
        start_time = datetime.now()
        
        if not request.model:
            route_result = await self.route(RouteRequest(
                prompt=request.prompt,
                session_id=request.session_id,
                context=request.context
            ))
            model = route_result.selected_model
        else:
            model = request.model
        
        model_config = MODEL_CONFIG.get(model, MODEL_CONFIG["llama2"])
        
        try:
            if model_config["provider"] == "ollama":
                response, tokens = await self._call_ollama(model, request)
            else:
                response, tokens = await self._call_cloud(model, model_config, request)
            
            cost = (tokens / 1000) * model_config["cost_per_1k_tokens"]
            
            self.usage_stats["total_requests"] += 1
            self.usage_stats["total_tokens"] += tokens
            self.usage_stats["total_cost_usd"] += cost
            if model_config["tier"] == ModelTier.LOCAL:
                self.usage_stats["local_requests"] += 1
            else:
                self.usage_stats["cloud_requests"] += 1
            
            latency = (datetime.now() - start_time).total_seconds() * 1000
            
            return ChatResponse(
                response=response,
                model_used=model,
                tokens_used=tokens,
                cost_usd=cost,
                latency_ms=latency
            )
            
        except Exception as e:
            logger.error(f"Chat error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def _call_ollama(self, model: str, request: ChatRequest) -> tuple:
        """Call Ollama API."""
        try:
            response = await self.http_client.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": request.prompt}],
                    "stream": False,
                    "options": {
                        "temperature": request.temperature,
                        "num_predict": request.max_tokens
                    }
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("message", {}).get("content", ""), data.get("eval_count", 100)
            else:
                raise Exception(f"Ollama error: {response.status_code}")
        except Exception as e:
            logger.warning(f"Ollama call failed: {e}, returning mock response")
            return f"[Mock Response] Processed by {model}", 50
    
    async def _call_cloud(self, model: str, config: Dict, request: ChatRequest) -> tuple:
        """Call cloud API (OpenAI/Anthropic)."""
        logger.info(f"Would call cloud model {model} (mock mode)")
        return f"[Mock Cloud Response] Processed by {model}", 100

# =============================================================================
# FastAPI Application
# =============================================================================

db_manager: Optional[DatabaseManager] = None
router: Optional[ModelRouter] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global db_manager, router
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    
    # Initialize database
    db_manager = DatabaseManager(DATABASE_PATH)
    
    # Initialize router
    router = ModelRouter(OLLAMA_URL, ONEAPI_URL, db_manager)
    
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")
    if router and router.http_client:
        await router.http_client.aclose()

app = FastAPI(
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Intelligent Model Router with Cost Optimization and Session Persistence",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "database": "connected" if db_manager else "disconnected",
        "features": ["sqlite_persistence", "cost_estimation", "multi_dimensional_scoring"]
    }

@app.post("/route", response_model=RouteResponse)
async def route_prompt(request: RouteRequest, background_tasks: BackgroundTasks):
    """Route a prompt to the appropriate model."""
    return await router.route(request, background_tasks)

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Execute a chat request with automatic routing."""
    return await router.chat(request)

@app.get("/analyze/{prompt}")
async def analyze_prompt(prompt: str):
    """Analyze prompt complexity without routing."""
    judgment = router.judge.judge(prompt)
    cost_estimate = router.cost_estimator.estimate(prompt, "gpt-4")
    
    return {
        "prompt": prompt[:100] + "..." if len(prompt) > 100 else prompt,
        "complexity": judgment,
        "cost_estimates": {
            "local": router.cost_estimator.estimate(prompt, "llama2"),
            "cloud_cheap": router.cost_estimator.estimate(prompt, "claude-3-haiku"),
            "cloud_smart": router.cost_estimator.estimate(prompt, "gpt-4"),
        }
    }

@app.get("/stats")
async def get_stats():
    """Get routing statistics."""
    db_stats = db_manager.get_routing_stats() if db_manager else {}
    recent = db_manager.get_recent_decisions(5) if db_manager else []
    
    return {
        "memory_stats": router.usage_stats if router else {},
        "database_stats": db_stats,
        "recent_decisions": recent
    }

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    """Get session information."""
    history = db_manager.get_session_history(session_id) if db_manager else []
    stats = db_manager.get_routing_stats(session_id) if db_manager else {}
    
    return {
        "session_id": session_id,
        "history": history,
        "stats": stats
    }

@app.get("/models")
async def list_models():
    """List available models."""
    return {
        "models": {
            name: {
                "tier": config["tier"].value,
                "provider": config["provider"],
                "cost_per_1k_tokens": config["cost_per_1k_tokens"],
                "capabilities": config["capabilities"]
            }
            for name, config in MODEL_CONFIG.items()
        }
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L1_GATEWAY",
        "status": "running",
        "version": "2.0.0",
        "features": [
            "Multi-dimensional complexity scoring",
            "SQLite session persistence",
            "Cost estimation",
            "Automatic model routing",
            "Failover support"
        ]
    }

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8058,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
