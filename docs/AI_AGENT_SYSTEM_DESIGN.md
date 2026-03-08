# Galaxy AI Agent System Design

> Architecture specification for the Galaxy multi-agent system — a fractal, self-organizing agent ecosystem with digital twin integration.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Agent Lifecycle](#agent-lifecycle)
- [Three Creation Modes](#three-creation-modes)
- [Message Bus Protocol](#message-bus-protocol)
- [Team Collaboration Strategies](#team-collaboration-strategies)
- [Fractal Decomposition](#fractal-decomposition)
- [Agent Manifest & Migration](#agent-manifest--migration)
- [System Integration Layer](#system-integration-layer)
- [Digital Twin Integration](#digital-twin-integration)
- [Production Safeguards](#production-safeguards)
- [Decision Guide](#decision-guide)
- [API Reference](#api-reference)

---

## Overview

Galaxy's Agent System implements an L4-autonomy multi-agent architecture with three core design principles:

1. **Fractal Self-Similarity** — Every agent follows the same receive → decompose → execute → aggregate loop, from leaf executors to the root coordinator.
2. **Dynamic Creation** — Agents are created on-demand via templates, LLM generation, or runtime splitting — no static wiring.
3. **Digital Twin Coupling** — Each agent can optionally mirror its state to a twin model, enabling predictive simulation and deviation detection.

### Key Components

| Module | File | Purpose |
|--------|------|---------|
| Agent Factory | `core/agent_factory.py` | Agent lifecycle management, 3 creation modes |
| Agent Team | `core/agent_team.py` | Multi-agent collaboration strategies |
| Fractal Agent | `core/fractal_agent.py` | Recursive task decomposition |
| Agent Manifest | `core/agent_manifest.py` | Serializable deployment package for edge devices |
| System Integration | `core/system_integration.py` | Unified capability registry |
| Agent Context | `core/agent_context.py` | Passive context loading from AGENTS.md |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         REST / WebSocket API                     │
│                     core/routes/agents.py                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐     │
│  │ Agent Factory │  │  Agent Team  │  │  Fractal Executor  │     │
│  │   3 modes     │  │ 3 strategies │  │ recursive decomp   │     │
│  └──────┬───────┘  └──────┬───────┘  └────────┬───────────┘     │
│         │                  │                    │                  │
│  ┌──────┴──────────────────┴────────────────────┴───────────┐    │
│  │                    Agent Message Bus                        │    │
│  │          (async queues, broadcast, request-reply)          │    │
│  └────────────────────────────┬───────────────────────────────┘    │
│                               │                                    │
│  ┌────────────────────────────┴───────────────────────────────┐    │
│  │                  System Integration Layer                    │    │
│  │         Unified Capability Registry (6 types)               │    │
│  │     DEVICE | MCP | SKILL | NODE | AGENT | BUILTIN           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐   │
│  │ Multi-LLM    │  │ Twin Model   │  │ Circuit Breaker     │   │
│  │ Router       │  │ Manager      │  │ (Monitoring)        │   │
│  └──────────────┘  └──────────────┘  └─────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent Lifecycle

### State Machine

```
                    ┌──────────┐
         create()   │   IDLE   │◄──────────── task complete
         ─────────►│          │
                    └────┬─────┘
                         │ execute_agent_task()
                         ▼
                    ┌──────────┐
                    │ WORKING  │──────────────────────────┐
                    └────┬─────┘                          │
                         │ queue > threshold               │ error
                         ▼                                 ▼
                    ┌──────────┐                    ┌──────────┐
                    │SPLITTING │                    │  ERROR   │
                    └────┬─────┘                    └──────────┘
                         │ children created
                         ▼
                    ┌──────────┐
                    │ WAITING  │── children done ──► IDLE
                    └──────────┘

         Termination: any state ──► TERMINATED (TTL expired / manual)
         Completion:  any state ──► COMPLETED  (all tasks done)
```

### States

| State | Value | Description |
|-------|-------|-------------|
| `IDLE` | `idle` | No active tasks, ready to accept work |
| `WORKING` | `working` | Actively processing tasks |
| `WAITING` | `waiting` | Waiting for child agents to complete |
| `SPLITTING` | `splitting` | In the process of creating child agents |
| `COMPLETED` | `completed` | All tasks finished successfully |
| `ERROR` | `error` | Encountered an unrecoverable error |
| `TERMINATED` | `terminated` | Cleaned up by TTL or manual termination |

### Roles

| Role | Use Case |
|------|----------|
| `COORDINATOR` | Decomposes complex tasks, manages sub-agents |
| `EXECUTOR` | Runs concrete tasks (code, device control) |
| `ANALYST` | Data analysis, research, information extraction |
| `PLANNER` | Strategic planning, risk assessment |
| `MONITOR` | Observes and reports on execution |
| `COMMUNICATOR` | Handles external communication |
| `SPECIALIST` | Domain-specific expert |

---

## Three Creation Modes

### Mode 1: Template Creation

**When:** Known task types with predictable requirements.

```python
agent = factory.create_from_template("coordinator")
agent = factory.create_from_template("data_analyst", overrides={"name": "Sales Analyst"})
```

**Available templates:** `coordinator`, `data_analyst`, `code_executor`, `research`, `device_controller`, `planner`

**Behavior:** Instantiates from `AGENT_TEMPLATES` dict. Fast, deterministic, no LLM call.

### Mode 2: LLM Generation

**When:** Novel tasks that don't fit templates; need dynamic capability configuration.

```python
agent = await factory.create_from_llm(
    task_description="Analyze satellite imagery for deforestation patterns",
    context={"data_format": "GeoTIFF", "region": "Amazon"}
)
```

**Behavior:**
1. Builds a structured prompt from the task description
2. Calls LLM via `MultiLLMRouter.chat_json()` to generate `AgentConfig`
3. On LLM failure → falls back to template matching via keyword heuristics
4. Protected by circuit breaker (5 failures → 30s recovery)

### Mode 3: Split / Reproduction

**When:** Agent's task queue exceeds `split_threshold` (default: 3 pending tasks).

```python
children = await factory.split_agent(agent_id, num_children=3)
```

**Behavior:**
1. Parent enters `SPLITTING` state
2. Creates N child agents inheriting parent's capabilities (with strength variation)
3. Distributes parent's task queue evenly among children
4. Children execute in parallel via `asyncio.gather()`
5. If ALL children fail → fallback to parent serial execution
6. Child TTL = parent TTL / 2 (prevents infinite growth)
7. Respects `max_depth` limit (default: 3)

### Decision Tree

```
New Task Arrives
    │
    ├── Known task type? ──── YES ──► Template Creation (Mode 1)
    │                                  Fast, predictable
    │
    ├── LLM available? ──── YES ──► LLM Generation (Mode 2)
    │                                Dynamic, adaptive
    │
    └── Queue overloaded? ── YES ──► Split / Reproduction (Mode 3)
                                     Scales horizontally
```

---

## Message Bus Protocol

### Architecture

The `AgentMessageBus` is an in-memory async queue system. Each agent gets a dedicated `asyncio.Queue` (max 1000 messages).

### Message Format

```python
@dataclass
class AgentMessage:
    id: str           # "msg_{12-char-hex}"
    sender_id: str    # Source agent ID
    receiver_id: str  # Target agent ID
    msg_type: str     # Message type (see below)
    payload: Dict     # Arbitrary data
    timestamp: float  # Unix timestamp
    ack: bool         # Acknowledgement flag
```

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `task_assign` | Parent → Child | Assign a task to a child agent |
| `task_result` | Child → Parent | Report task execution result |
| `heartbeat` | Any → Any | Liveness check |
| `status_query` | Any → Any | Request current status |
| `status_response` | Any → Any | Reply with current status |

### Communication Patterns

1. **Point-to-Point:** `bus.send(msg)` — direct message to one agent
2. **Broadcast:** `bus.broadcast(sender_id, msg_type, payload)` — to all registered agents
3. **Request-Reply:** `bus.request(msg, timeout=10.0)` — send and wait for response with timeout

---

## Team Collaboration Strategies

### Strategy 1: PARALLEL (Perplexity-style)

**When:** Need diverse perspectives on the same problem; want to compare model outputs.

```
Task ──► Agent A (GPT-4) ──┐
     ──► Agent B (Claude) ──┼──► Synthesize ──► Final Answer
     ──► Agent C (Gemini) ──┘
```

- Same task dispatched to N agents, each using a different LLM
- Results synthesized by coordinator using LLM summarization
- Best for: open-ended questions, creative tasks, fact verification

### Strategy 2: SPECIALIZED (Task Decomposition)

**When:** Complex task that benefits from role-based division of labor.

```
Task ──► Coordinator decomposes ──► Researcher (finds data)
                                 ──► Analyst (processes data)
                                 ──► Writer (generates report)
                                          │
                                          ▼
                                    Coordinator merges
```

- Coordinator uses LLM to decompose task into sub-tasks
- Each sub-task matched to optimal agent template + LLM provider
- Results aggregated by coordinator
- Best for: multi-step workflows, reports, data pipelines

### Strategy 3: SWARM (Collective Intelligence)

**When:** Repetitive tasks that benefit from parallel execution and voting.

```
Task ──► Agent 1 (same type) ──┐
     ──► Agent 2 (same type) ──┼──► Vote/Merge ──► Result
     ──► Agent 3 (same type) ──┘
```

- Multiple agents of the same type process variations of the task
- Results combined via voting (for discrete answers) or merging (for text)
- Best for: classification, batch processing, consensus-building

### Strategy Comparison

| Factor | PARALLEL | SPECIALIZED | SWARM |
|--------|----------|-------------|-------|
| LLM diversity | Multiple models | Best model per sub-task | Same model |
| Task type | Same task, different angles | Different sub-tasks | Same task, batch |
| Cost | High (N x full task) | Medium (optimized routing) | Medium (N x task) |
| Latency | Max of all agents | Sum of critical path | Max of all agents |
| Best for | Quality/verification | Complex workflows | Scale/consensus |

---

## Fractal Decomposition

### Algorithm

```
function execute(task, depth=0):
    complexity = assess_complexity(task)

    if complexity == ATOMIC or depth >= MAX_DEPTH:
        return execute_directly(task)

    subtasks = decompose(task, complexity)
    results = parallel_execute([
        execute(subtask, depth+1)
        for subtask in subtasks
    ])

    return synthesize(results)
```

### Complexity Levels

| Level | Description | Max Subtasks | Action |
|-------|-------------|--------------|--------|
| `ATOMIC` | Indivisible task | 0 | Execute directly |
| `SIMPLE` | 2-3 steps | 3 | May decompose |
| `MODERATE` | Needs decomposition | 4 | Decompose |
| `COMPLEX` | Multi-layer | 5 | Decompose recursively |
| `EPIC` | Large-scale collaboration | 6 | Deep decomposition |

### Safety Limits

- **MAX_DEPTH = 4** — Prevents infinite recursion
- **MAX_SUBTASKS = 6** — Limits branching factor per level
- **Worst case agents:** 6^4 = 1,296 (bounded by factory MAX_AGENTS = 500)

### Decomposition Methods

1. **LLM-based** (preferred): Sends task to LLM with structured prompt, gets JSON subtask list
2. **Rule-based** (fallback): Keyword-based splitting (e.g., "and", "then", sentence boundaries)

---

## Agent Manifest & Migration

### Purpose

`AgentManifest` is a serializable deployment package — an agent's complete "soul" that can be transmitted to edge devices for local execution.

### Structure

```json
{
    "manifest_id": "uuid",
    "agent_name": "device_control_phone01",
    "agent_role": "executor",
    "system_prompt": "You are a device control agent...",
    "execution_mode": "react",
    "tools": [
        {"name": "click", "description": "Click at coordinates", "parameters": {...}}
    ],
    "tasks": [
        {"id": "abc", "instruction": "Open Settings app", "priority": 5}
    ],
    "max_react_turns": 10,
    "timeout_seconds": 300,
    "source_device": "server",
    "target_device": "phone01",
    "discover_local_tools": true
}
```

### Execution Modes

| Mode | Behavior |
|------|----------|
| `react` | ReAct loop: Thought → Action → Observation, up to `max_react_turns` |
| `sequential` | Execute predefined action list in order |
| `autonomous` | Self-discovers tools on target device, makes independent decisions |

### Migration Flow

```
Server                          Edge Device
  │                                │
  ├── Create AgentManifest ──────►│
  │   (serialize to JSON)          │
  │                                ├── Deserialize manifest
  │                                ├── Discover local MCP tools
  │                                ├── Execute in LocalAgentRuntime
  │                                ├── Report results back
  │◄───────────────────────────────┤
```

---

## System Integration Layer

### Capability Registry

The `SystemIntegration` singleton maintains a unified registry of all system capabilities across 6 types:

```python
class CapabilityType(Enum):
    DEVICE = "device"     # Hardware device actions
    MCP = "mcp"           # MCP server tools
    SKILL = "skill"       # Loaded skills
    NODE = "node"         # Distributed nodes
    AGENT = "agent"       # Agent capabilities
    BUILTIN = "builtin"   # Built-in functions
```

### Capability Discovery & Routing

```
User Request: "Turn on the living room light"
    │
    ├── SystemIntegration.discover_capability("device_control")
    │       │
    │       ├── Search DEVICE capabilities → found: smart_hub_001
    │       ├── Search MCP capabilities → found: home-assistant-mcp
    │       └── Select highest priority match
    │
    └── SystemIntegration.execute("device_control", params)
            │
            └── Routes to matched capability handler
```

### Priority-Based Selection

When multiple capabilities match, selection uses:
1. **Priority score** (1-10, higher wins)
2. **Online status** (only online sources considered)
3. **Type preference** (configurable per request)

---

## Digital Twin Integration

### Coupling Modes

| Mode | Sync | Use Case |
|------|------|----------|
| `TIGHT` | Real-time bidirectional | Critical operations, safety-required |
| `LOOSE` | Periodic snapshot sync | Default for team members |
| `DECOUPLED` | No sync | Independent simulation |
| `SHADOW` | Read-only mirror | Monitoring and analytics |

### Integration Points

- **Agent Team:** Each team member auto-creates a digital twin (default: LOOSE)
- **Deviation Detection:** Twin compares predicted vs actual state, flags anomalies
- **Predictive Simulation:** Twin runs ahead to predict outcomes before real execution

---

## Production Safeguards

| Safeguard | Value | Purpose |
|-----------|-------|---------|
| Max agents | 500 | Prevents resource exhaustion |
| Max creates/min | 50 | Rate limits agent creation |
| Queue size/agent | 1,000 | Bounds memory per agent |
| TTL cleanup interval | 60s | Reclaims expired agents |
| Child TTL | Parent/2 | Prevents infinite growth |
| Max depth | 3-4 | Limits recursion |
| Circuit breaker | 5 failures → 30s cooldown | Protects LLM calls |
| State persistence | `data/agent_state.json` | Recovery on restart |

---

## Decision Guide

### When to Use Each Component

| Scenario | Component | Strategy |
|----------|-----------|----------|
| Simple known task | Agent Factory (Template) | Direct execution |
| Novel/unique task | Agent Factory (LLM) | Dynamic generation |
| Overloaded agent | Agent Factory (Split) | Auto-scaling |
| Need model comparison | Agent Team | PARALLEL |
| Complex multi-step workflow | Agent Team | SPECIALIZED |
| Batch processing | Agent Team | SWARM |
| Deep task decomposition | Fractal Agent | Recursive |
| Edge/mobile execution | Agent Manifest | Serialized deployment |
| Cross-system capability lookup | System Integration | Capability registry |

### Scaling Considerations

- **Vertical:** Increase `max_subtasks`, `max_depth` for deeper decomposition
- **Horizontal:** Use Agent Team SWARM for batch parallelism
- **Edge:** Use Agent Manifest to offload to devices
- **Cost:** SPECIALIZED strategy minimizes LLM calls by routing to optimal models

---

## API Reference

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/agents/` | Create agent (template or LLM) |
| `GET` | `/api/v1/agents/` | List all agents |
| `GET` | `/api/v1/agents/{id}` | Get agent details |
| `POST` | `/api/v1/agents/{id}/execute` | Execute task on agent |
| `DELETE` | `/api/v1/agents/{id}` | Terminate agent |
| `POST` | `/api/v1/agents/team` | Create agent team |
| `POST` | `/api/v1/agents/team/{id}/execute` | Execute team task |
| `GET` | `/api/v1/agents/factory/templates` | List available templates |

### Python API

```python
from core.agent_factory import AgentFactory, get_message_bus

# Initialize
factory = AgentFactory(llm_router=router)

# Mode 1: Template
agent = factory.create_from_template("coordinator")

# Mode 2: LLM Generation
agent = await factory.create_from_llm("Analyze sales data for Q4")

# Mode 3: Split
children = await factory.split_agent(agent.id, num_children=3)

# Execute
result = await factory.execute_agent_task(agent.id, {"task": "analyze", "data": [...]})

# Message Bus
bus = get_message_bus()
bus.register(agent.id)
await bus.send(AgentMessage(id="msg_001", sender_id="a", receiver_id="b", msg_type="task_assign", payload={}))

# Team
from core.agent_team import AgentTeam, TeamStrategy
team = AgentTeam(name="analysis", strategy=TeamStrategy.PARALLEL, factory=factory, llm_router=router)
result = await team.execute("Compare market trends across regions")

# Fractal
from core.fractal_agent import FractalExecutor
executor = FractalExecutor(llm_router=router, agent_factory=factory)
result = await executor.execute("Build a comprehensive market analysis report")

# Manifest (for edge deployment)
from core.agent_manifest import AgentManifest
manifest = AgentManifest.create_device_control_agent(
    target_device="phone01",
    instruction="Open Settings and enable Bluetooth"
)
json_payload = manifest.to_json()  # Send via WebSocket
```
