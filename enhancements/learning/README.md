# UFO Galaxy v5.0 - Autonomous Learning System

A comprehensive self-learning system that demonstrates emergent behavior through continuous learning from multiple data sources.

## Features

### 5-Stage Learning Loop
1. **OBSERVE** - Collect data from multiple sources (Web, arXiv, GitHub)
2. **ANALYZE** - Recognize patterns using ML (scikit-learn)
3. **EXPERIMENT** - Test hypotheses and validate patterns
4. **VALIDATE** - Verify results and confidence scores
5. **DEPLOY** - Apply learned knowledge to the system

### Knowledge Graph
- **13 Entity Types**: Concept, Person, Organization, Technology, Event, Location, Document, Pattern, Algorithm, Dataset, Metric, Hypothesis, Experiment
- **38 Relationship Types**: Including hierarchical (is_a, part_of), causal (causes, enables), temporal (precedes, follows), semantic (related_to, similar_to), and emergence-specific (emerges_from, gives_rise_to)
- NetworkX-based with visualization export (GraphML, GEXF, D3.js, Cytoscape)

### Emergence Detection
Detects 4 types of emergent behavior:
- **Capability Emergence** - New capabilities arise from component interactions
- **Performance Breakthrough** - Significant performance improvements beyond expected bounds
- **New Pattern** - Novel patterns discovered that haven't been seen before
- **Synergy** - Components produce effects greater than the sum of their parts

### Multi-Source Search Integration
- **Web Search** - General web content
- **ArXiv API** - Academic papers and research
- **GitHub API** - Code repositories and projects
- Result aggregation, ranking, and caching

### Feedback Loop
- Explicit and implicit feedback collection
- Performance metrics tracking with trend detection
- Reinforcement learning for decision optimization
- Continuous improvement mechanisms

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Autonomous Learning Engine                │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌────────┐        │
│  │ OBSERVE │→ │ ANALYZE │→ │EXPERIMENT│→ │VALIDATE│→ ...  │
│  └─────────┘  └─────────┘  └──────────┘  └────────┘        │
└─────────────────────────────────────────────────────────────┘
         ↑                              ↓
    ┌────┴────┐                  ┌──────┴──────┐
    │ Search  │                  │   Knowledge  │
    │Integrator│                  │    Graph     │
    └────┬────┘                  └──────┬──────┘
         │                              │
    ┌────┴────┐                  ┌──────┴──────┐
    │Web/arXiv│                  │ 13 Entity   │
    │ GitHub  │                  │ 38 Relations│
    └─────────┘                  └─────────────┘
         ↑                              ↓
    ┌────┴──────────────────────────────┴──────┐
    │           Emergence Detector              │
    │  • Capability Emergence                   │
    │  • Performance Breakthrough               │
    │  • New Pattern                            │
    │  • Synergy                                │
    └───────────────────────────────────────────┘
                        ↓
    ┌───────────────────────────────────────────┐
    │           Feedback Loop                   │
    │  • Feedback Collection                    │
    │  • Metrics Tracking                       │
    │  • Reinforcement Learning                 │
    │  • Continuous Improvement                 │
    └───────────────────────────────────────────┘
```

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

```python
import asyncio
from learning import AutonomousLearningEngine

async def main():
    # Create learning engine
    engine = AutonomousLearningEngine(cycle_interval=60.0)
    
    # Register data sources
    async def my_data_source():
        return [{"content": "Data to learn from"}]
    
    engine.register_data_source("my_source", my_data_source)
    
    # Start learning
    await engine.start()
    
    # Let it run...
    await asyncio.sleep(300)
    
    # Stop learning
    await engine.stop()

asyncio.run(main())
```

### Knowledge Graph Operations

```python
from learning import KnowledgeGraph, Entity, EntityType, Relationship, RelationshipType

# Create knowledge graph
kg = KnowledgeGraph("my_graph")

# Add entities
entity1 = kg.add_entity(Entity(
    id="",
    entity_type=EntityType.CONCEPT,
    name="Machine Learning",
    description="Field of AI"
))

entity2 = kg.add_entity(Entity(
    id="",
    entity_type=EntityType.ALGORITHM,
    name="Neural Networks",
    description="ML algorithm"
))

# Add relationship
kg.add_relationship(Relationship(
    id="",
    source_id=entity1,
    target_id=entity2,
    relationship_type=RelationshipType.USES
))

# Search
results = kg.search("learning")

# Export
kg.export_to_json("knowledge_graph.json")
```

### Emergence Detection

```python
from learning import EmergenceDetector

detector = EmergenceDetector()

# Detect capability emergence
event = detector.check_capability_emergence(
    capability_name="Self-Optimization",
    evidence=[
        {"component": "module1", "observation": "auto-adjustment"},
        {"component": "module2", "observation": "improvement"}
    ],
    confidence=0.85
)

if event:
    print(f"Emergence detected: {event.description}")
```

### Running the Learning Node Service

```bash
python learning_node.py
```

The service will start on port 8070 with the following endpoints:

- `GET /` - Service info
- `GET /status` - System status
- `POST /learn` - Submit content for learning
- `GET /knowledge/{query}` - Query accumulated knowledge
- `GET /patterns` - Get discovered patterns
- `POST /feedback` - Submit feedback
- `GET /learning/history` - Get learning history
- `GET /graph/stats` - Get knowledge graph statistics
- `GET /emergence/recent` - Get recent emergence events
- `POST /search/integrated` - Perform integrated search
- `WebSocket /ws` - Real-time learning updates

## API Examples

### Submit Content for Learning

```bash
curl -X POST http://localhost:8070/learn \
  -H "Content-Type: application/json" \
  -d '{
    "content": "New machine learning technique discovered",
    "source": "api",
    "metadata": {"topic": "ml"}
  }'
```

### Query Knowledge

```bash
curl "http://localhost:8070/knowledge/machine%20learning?limit=5"
```

### Get Patterns

```bash
curl "http://localhost:8070/patterns?min_confidence=0.7&limit=10"
```

### Submit Feedback

```bash
curl -X POST http://localhost:8070/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "target_type": "pattern",
    "target_id": "pattern_123",
    "rating": 0.8,
    "comment": "Useful pattern!"
  }'
```

## Testing

Run all tests:

```bash
python -m pytest tests/
```

Run specific test file:

```bash
python tests/test_autonomous_learning_engine.py
python tests/test_knowledge_graph.py
python tests/test_emergence_detector.py
python tests/test_search_integrator.py
python tests/test_feedback_loop.py
python tests/test_learning_node.py
```

## Configuration

The learning system can be configured through environment variables:

```bash
# Learning engine
LEARNING_CYCLE_INTERVAL=60.0
LEARNING_MIN_CONFIDENCE=0.6

# Knowledge graph
KNOWLEDGE_GRAPH_MAX_ITEMS=10000

# Emergence detection
EMERGENCE_THRESHOLD=0.7
ANOMALY_Z_SCORE=2.5

# Search integration
SEARCH_CACHE_TTL=3600
SEARCH_RATE_LIMIT=60

# Feedback loop
FEEDBACK_THRESHOLD_ACTION=5
```

## Performance

- Pattern recognition: ~100-500 patterns/second (depends on data size)
- Knowledge graph queries: <10ms for typical queries
- Search integration: 1-3 seconds per source (with caching)
- Learning cycle: Configurable (default 60 seconds)

## License

MIT License - UFO Galaxy Team
