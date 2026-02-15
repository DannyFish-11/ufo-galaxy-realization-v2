#!/usr/bin/env python3
"""
Learning Node Service for UFO Galaxy v5.0

FastAPI-based service providing:
- REST API endpoints for learning operations
- WebSocket endpoint for real-time learning updates
- Integration with autonomous learning engine
- Knowledge graph queries

Port: 8070

Author: UFO Galaxy Team
Version: 5.0.0
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Import learning system components
try:
    from autonomous_learning_engine import (
        AutonomousLearningEngine,
        LearningObservation,
        LearningStage,
        PatternRecognizer,
        KnowledgeAccumulator
    )
    from knowledge_graph import KnowledgeGraph, Entity, EntityType, Relationship, RelationshipType
    from emergence_detector import EmergenceDetector, EmergenceType
    from search_integrator import SearchIntegrator
    from feedback_loop import FeedbackLoop
except ImportError:
    # For standalone testing
    import sys
    sys.path.insert(0, '/mnt/okcomputer/output/ufo-galaxy-v5/enhancements/learning')
    from autonomous_learning_engine import (
        AutonomousLearningEngine,
        LearningObservation,
        LearningStage,
        PatternRecognizer,
        KnowledgeAccumulator
    )
    from knowledge_graph import KnowledgeGraph, Entity, EntityType, Relationship, RelationshipType
    from emergence_detector import EmergenceDetector, EmergenceType
    from search_integrator import SearchIntegrator
    from feedback_loop import FeedbackLoop

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Pydantic models for API

class LearnRequest(BaseModel):
    """Request model for learning endpoint."""
    content: str = Field(..., description="Content to learn from")
    source: str = Field(default="api", description="Source of the content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class LearnResponse(BaseModel):
    """Response model for learning endpoint."""
    success: bool
    observation_id: Optional[str] = None
    patterns_found: int = 0
    message: str = ""


class KnowledgeQueryRequest(BaseModel):
    """Request model for knowledge query."""
    query: str = Field(..., description="Search query")
    entity_types: Optional[List[str]] = Field(default=None, description="Filter by entity types")
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=10, ge=1, le=100)


class PatternResponse(BaseModel):
    """Response model for patterns."""
    id: str
    pattern_type: str
    description: str
    confidence: float
    frequency: int
    examples: List[str]
    created_at: str


class FeedbackRequest(BaseModel):
    """Request model for feedback."""
    target_type: str = Field(..., description="Type of target: 'pattern', 'knowledge', 'experiment'")
    target_id: str = Field(..., description="ID of the target")
    rating: float = Field(..., ge=-1.0, le=1.0, description="Feedback rating from -1 to 1")
    comment: Optional[str] = Field(default=None, description="Optional comment")


class StatusResponse(BaseModel):
    """Response model for system status."""
    status: str
    learning_active: bool
    current_stage: Optional[str]
    total_observations: int
    total_patterns: int
    total_knowledge_items: int
    uptime_seconds: float


# Global state
class LearningNodeState:
    """Maintains global state for the learning node."""
    
    def __init__(self):
        self.engine: Optional[AutonomousLearningEngine] = None
        self.knowledge_graph: Optional[KnowledgeGraph] = None
        self.emergence_detector: Optional[EmergenceDetector] = None
        self.search_integrator: Optional[SearchIntegrator] = None
        self.feedback_loop: Optional[FeedbackLoop] = None
        self.started_at: Optional[datetime] = None
        self.active_connections: Set[WebSocket] = set()
        self._initialized = False
    
    async def initialize(self):
        """Initialize all learning components."""
        if self._initialized:
            return
        
        logger.info("Initializing Learning Node...")
        
        # Initialize knowledge graph
        self.knowledge_graph = KnowledgeGraph("ufo_learning_graph")
        
        # Initialize pattern recognizer and knowledge accumulator
        pattern_recognizer = PatternRecognizer()
        knowledge_accumulator = KnowledgeAccumulator()
        
        # Initialize learning engine
        self.engine = AutonomousLearningEngine(
            pattern_recognizer=pattern_recognizer,
            knowledge_accumulator=knowledge_accumulator,
            cycle_interval=60.0
        )
        
        # Initialize emergence detector
        self.emergence_detector = EmergenceDetector()
        
        # Initialize search integrator
        self.search_integrator = SearchIntegrator()
        
        # Initialize feedback loop
        self.feedback_loop = FeedbackLoop()
        
        # Register data sources
        await self._register_data_sources()
        
        # Register callbacks
        self._register_callbacks()
        
        self.started_at = datetime.now()
        self._initialized = True
        
        logger.info("Learning Node initialized successfully")
    
    async def _register_data_sources(self):
        """Register data sources with the learning engine."""
        # Web search data source
        async def web_search_source():
            try:
                results = await self.search_integrator.search_web(
                    "machine learning artificial intelligence",
                    max_results=5
                )
                return [
                    {'content': r['title'] + ": " + r.get('snippet', ''), 
                     'metadata': {'source': 'web', 'url': r.get('url', '')}}
                    for r in results
                ]
            except Exception as e:
                logger.error(f"Web search source error: {e}")
                return []
        
        # ArXiv data source
        async def arxiv_source():
            try:
                results = await self.search_integrator.search_arxiv(
                    "machine learning",
                    max_results=3
                )
                return [
                    {'content': r['title'] + ". " + r.get('summary', ''), 
                     'metadata': {'source': 'arxiv', 'id': r.get('id', '')}}
                    for r in results
                ]
            except Exception as e:
                logger.error(f"ArXiv source error: {e}")
                return []
        
        self.engine.register_data_source("web_search", web_search_source)
        self.engine.register_data_source("arxiv", arxiv_source)
    
    def _register_callbacks(self):
        """Register learning stage callbacks."""
        async def on_observe(data):
            await self._broadcast({
                'type': 'learning_update',
                'stage': 'observe',
                'data': {'observations_count': len(data)},
                'timestamp': datetime.now().isoformat()
            })
        
        async def on_analyze(data):
            await self._broadcast({
                'type': 'learning_update',
                'stage': 'analyze',
                'data': {'patterns_count': len(data)},
                'timestamp': datetime.now().isoformat()
            })
            
            # Check for emergence
            for pattern in data:
                emergence = self.emergence_detector.check_pattern_emergence(pattern)
                if emergence:
                    await self._broadcast({
                        'type': 'emergence_detected',
                        'emergence': emergence,
                        'timestamp': datetime.now().isoformat()
                    })
        
        self.engine.on_stage(LearningStage.OBSERVE, on_observe)
        self.engine.on_stage(LearningStage.ANALYZE, on_analyze)
    
    async def _broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected WebSocket clients."""
        disconnected = set()
        
        for websocket in self.active_connections:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.add(websocket)
        
        # Remove disconnected clients
        self.active_connections -= disconnected
    
    def get_uptime(self) -> float:
        """Get system uptime in seconds."""
        if not self.started_at:
            return 0.0
        return (datetime.now() - self.started_at).total_seconds()


# Global state instance
state = LearningNodeState()


# FastAPI lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    # Startup
    await state.initialize()
    await state.engine.start()
    logger.info("Learning Node service started on port 8070")
    
    yield
    
    # Shutdown
    await state.engine.stop()
    logger.info("Learning Node service stopped")


# Create FastAPI app
app = FastAPI(
    title="UFO Galaxy Learning Node",
    description="Autonomous learning system with real-time WebSocket updates",
    version="5.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# REST API Endpoints

@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint."""
    return {
        "service": "UFO Galaxy Learning Node",
        "version": "5.0.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Get learning node status."""
    engine_status = state.engine.get_status() if state.engine else {}
    
    return StatusResponse(
        status="healthy" if state.engine and state.engine._running else "degraded",
        learning_active=state.engine._running if state.engine else False,
        current_stage=engine_status.get('current_stage'),
        total_observations=engine_status.get('total_observations', 0),
        total_patterns=len(state.engine.pattern_recognizer.get_patterns()) if state.engine else 0,
        total_knowledge_items=engine_status.get('knowledge_stats', {}).get('total_items', 0),
        uptime_seconds=state.get_uptime()
    )


@app.post("/learn", response_model=LearnResponse)
async def learn(request: LearnRequest):
    """
    Submit content for learning.
    
    The content will be processed through the learning pipeline:
    observation → pattern recognition → knowledge accumulation.
    """
    try:
        # Create observation
        observation = LearningObservation(
            id="",
            source=request.source,
            content=request.content,
            timestamp=datetime.now(),
            metadata=request.metadata
        )
        
        # Add to engine observations
        state.engine._observations.append(observation)
        
        # Trigger immediate pattern recognition if enough observations
        if len(state.engine._observations) % 5 == 0:
            recent_obs = state.engine._observations[-10:]
            patterns = await state.engine.pattern_recognizer.recognize_patterns(recent_obs)
            
            return LearnResponse(
                success=True,
                observation_id=observation.id,
                patterns_found=len(patterns),
                message=f"Learned from content, found {len(patterns)} patterns"
            )
        
        return LearnResponse(
            success=True,
            observation_id=observation.id,
            patterns_found=0,
            message="Content added to learning queue"
        )
        
    except Exception as e:
        logger.error(f"Learning error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/knowledge/{query}")
async def query_knowledge(
    query: str,
    entity_types: Optional[str] = None,
    min_confidence: float = 0.0,
    limit: int = 10
):
    """
    Query accumulated knowledge.
    
    Args:
        query: Search query string
        entity_types: Comma-separated list of entity types to filter
        min_confidence: Minimum confidence threshold
        limit: Maximum results to return
    """
    try:
        results = []
        
        # Query knowledge accumulator
        knowledge_items = state.engine.knowledge_accumulator.get_knowledge(
            query=query,
            min_confidence=min_confidence,
            limit=limit
        )
        
        results.extend(knowledge_items)
        
        # Also search knowledge graph if available
        if state.knowledge_graph:
            type_filter = None
            if entity_types:
                type_filter = [EntityType(et.strip()) for et in entity_types.split(",")]
            
            entities = state.knowledge_graph.search(
                query=query,
                entity_types=type_filter,
                limit=limit
            )
            
            for entity in entities:
                results.append({
                    'type': 'entity',
                    'id': entity.id,
                    'name': entity.name,
                    'entity_type': entity.entity_type.value,
                    'description': entity.description,
                    'confidence': entity.confidence
                })
        
        return {
            'query': query,
            'results_count': len(results),
            'results': results
        }
        
    except Exception as e:
        logger.error(f"Knowledge query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/patterns", response_model=List[PatternResponse])
async def get_patterns(
    pattern_type: Optional[str] = None,
    min_confidence: float = 0.0,
    limit: int = 20
):
    """
    Get discovered patterns.
    
    Args:
        pattern_type: Filter by pattern type
        min_confidence: Minimum confidence threshold
        limit: Maximum patterns to return
    """
    try:
        from autonomous_learning_engine import PatternType
        
        type_filter = None
        if pattern_type:
            type_filter = PatternType(pattern_type)
        
        patterns = state.engine.pattern_recognizer.get_patterns(
            pattern_type=type_filter,
            min_confidence=min_confidence
        )
        
        return [
            PatternResponse(
                id=p.id,
                pattern_type=p.pattern_type.value,
                description=p.description,
                confidence=p.confidence,
                frequency=p.frequency,
                examples=p.examples[:3],
                created_at=p.created_at.isoformat()
            )
            for p in patterns[:limit]
        ]
        
    except Exception as e:
        logger.error(f"Patterns query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """
    Submit feedback on learning results.
    
    Feedback is used to improve future learning cycles.
    """
    try:
        feedback_record = await state.feedback_loop.submit_feedback(
            target_type=request.target_type,
            target_id=request.target_id,
            rating=request.rating,
            comment=request.comment,
            metadata={'timestamp': datetime.now().isoformat()}
        )
        
        return {
            'success': True,
            'feedback_id': feedback_record.get('id'),
            'message': 'Feedback recorded successfully'
        }
        
    except Exception as e:
        logger.error(f"Feedback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/learning/history")
async def get_learning_history(limit: int = 10):
    """Get recent learning cycle history."""
    try:
        history = state.engine.get_learning_history(limit=limit)
        return {
            'cycles': history,
            'total_cycles': len(state.engine._cycles)
        }
    except Exception as e:
        logger.error(f"History error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/stats")
async def get_graph_stats():
    """Get knowledge graph statistics."""
    try:
        if not state.knowledge_graph:
            return {'error': 'Knowledge graph not initialized'}
        
        return state.knowledge_graph.get_stats()
        
    except Exception as e:
        logger.error(f"Graph stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emergence/recent")
async def get_recent_emergence(limit: int = 10):
    """Get recent emergence events."""
    try:
        if not state.emergence_detector:
            return {'error': 'Emergence detector not initialized'}
        
        events = state.emergence_detector.get_recent_events(limit=limit)
        return {
            'events': events,
            'total_events': len(state.emergence_detector._emergence_history)
        }
        
    except Exception as e:
        logger.error(f"Emergence query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search/integrated")
async def integrated_search(
    query: str,
    sources: Optional[str] = "web,arxiv,github",
    max_results: int = 10
):
    """
    Perform integrated search across multiple sources.
    
    Args:
        query: Search query
        sources: Comma-separated list of sources (web, arxiv, github)
        max_results: Maximum results per source
    """
    try:
        source_list = [s.strip() for s in sources.split(",")]
        
        results = await state.search_integrator.integrated_search(
            query=query,
            sources=source_list,
            max_results=max_results
        )
        
        return results
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# WebSocket Endpoint

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time learning updates.
    
    Clients receive:
    - Learning stage updates
    - New pattern discoveries
    - Emergence events
    - System status changes
    """
    await websocket.accept()
    state.active_connections.add(websocket)
    
    try:
        # Send initial status
        await websocket.send_json({
            'type': 'connected',
            'message': 'Connected to UFO Galaxy Learning Node',
            'timestamp': datetime.now().isoformat()
        })
        
        # Send current status
        engine_status = state.engine.get_status() if state.engine else {}
        await websocket.send_json({
            'type': 'status',
            'data': engine_status,
            'timestamp': datetime.now().isoformat()
        })
        
        # Keep connection alive and handle client messages
        while True:
            try:
                message = await websocket.receive_json()
                
                # Handle client commands
                if message.get('action') == 'get_status':
                    await websocket.send_json({
                        'type': 'status',
                        'data': state.engine.get_status() if state.engine else {},
                        'timestamp': datetime.now().isoformat()
                    })
                
                elif message.get('action') == 'get_patterns':
                    patterns = state.engine.pattern_recognizer.get_patterns(
                        limit=message.get('limit', 10)
                    )
                    await websocket.send_json({
                        'type': 'patterns',
                        'data': [{
                            'id': p.id,
                            'type': p.pattern_type.value,
                            'description': p.description,
                            'confidence': p.confidence
                        } for p in patterns],
                        'timestamp': datetime.now().isoformat()
                    })
                
                elif message.get('action') == 'ping':
                    await websocket.send_json({
                        'type': 'pong',
                        'timestamp': datetime.now().isoformat()
                    })
                    
            except Exception as e:
                logger.error(f"WebSocket message error: {e}")
                break
                
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        state.active_connections.discard(websocket)


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "engine": state.engine is not None and state.engine._running,
            "knowledge_graph": state.knowledge_graph is not None,
            "emergence_detector": state.emergence_detector is not None,
            "search_integrator": state.search_integrator is not None,
            "feedback_loop": state.feedback_loop is not None
        }
    }


def main():
    """Run the learning node service."""
    uvicorn.run(
        "learning_node:app",
        host="0.0.0.0",
        port=8070,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
