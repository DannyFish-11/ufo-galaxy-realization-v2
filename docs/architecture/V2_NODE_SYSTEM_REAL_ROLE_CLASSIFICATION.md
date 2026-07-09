# V2 Node System Real Role Classification

**Purpose:** Classify existing `Node_XX` units in the V2 system by their actual operational roles. This document answers the question: "What does each node actually do at runtime?" It is NOT a taxonomy replacement, NOT a rewrite proposal, and NOT a future semantic node specification.

---

## 1. What This Classification Is — And What It Is Not

### What it IS
- A practical role classification of existing `Node_XX` units based on their runtime behavior and what they actually provide to the capability fabric
- A reference for understanding which nodes are invoked during which kinds of tasks
- A foundation for later semantic capability annotation (Phase 1-1) and runtime matching (Phase 2+)

### What it is NOT
- **Not a replacement taxonomy.** The existing `NodeGroup`, `capabilities.json` category, and phase groupings remain in place. This classification is an overlay, not a replacement.
- **Not a definition of future semantic task nodes.** A future semantic task node (in a goal-directed agent graph) is a fundamentally different concept from a capability provider node.
- **Not an execution refactoring plan.** This document does not propose changes to how nodes are loaded, initialized, or invoked.
- **Not a definitive boundary.** Many nodes overlap across role categories; classification here reflects primary role.

---

## 2. Limits of Legacy Groupings

The V2 codebase currently organizes nodes through several legacy grouping mechanisms:

### 2.1 core / development / extended / academic Phase Groups
Nodes are assigned to a startup phase group (core, development, extended, academic). This grouping reflects **initialization order and system dependency depth**, not operational capability role. A `core` node is not necessarily more central to task execution than an `extended` node — it simply starts earlier.

**Limitation:** Phase group tells you when a node starts, not what it does.

### 2.2 NodeGroup Assignments
Some nodes carry a `NodeGroup` tag (e.g., `perception`, `actuation`, `planning`). These groupings were added organically and are inconsistently applied across the 100+ nodes. Many nodes lack a `NodeGroup` or carry a group label that understates their actual role.

**Limitation:** NodeGroup coverage is incomplete and not enforced by schema.

### 2.3 capabilities.json Categories
The `config/capabilities.json` file lists node capabilities as string arrays. These capability strings are useful for routing but do not reflect the operational role structure — a node may have capabilities listed across multiple functional domains with no single-role assignment.

**Limitation:** capabilities.json is route-table data, not role-model data.

---

## 3. Real Role Model

The following seven categories reflect what `Node_XX` units actually do during system operation. A node may have secondary presence in another category, but each node has a dominant role.

---

### 3.1 Infra Nodes

**Definition:** Nodes responsible for system lifecycle, health monitoring, configuration authority, launcher coordination, and registry management. These nodes support the operational envelope — they do not directly execute user tasks.

**Key characteristics:**
- Invoked at startup and shutdown boundaries
- Provide system health signals, configuration reads, and process lifecycle control
- Typically in the `core` phase group

**Representative nodes:**
| Node | Primary infra function |
|------|----------------------|
| `Node_01_SystemHealth` | System health monitoring, liveness checks |
| `Node_02_ConfigManager` | Configuration loading and authority |
| `Node_03_Registry` | Node and capability registry management |
| `Node_04_Lifecycle` | Startup/shutdown sequencing |
| `Node_05_Dashboard` | Operator dashboard surface |

---

### 3.2 Tool / Capability Nodes

**Definition:** Nodes that expose a discrete, general-purpose tool capability (file operations, web access, calendar, search, code execution). These are the most common node type and form the core of the capability fabric. They are invoked on-demand by the orchestrator or planner.

**Key characteristics:**
- Stateless or near-stateless per invocation
- Well-defined input/output interface
- Typically no persistent background service
- May wrap external APIs or system calls

**Representative nodes:**
| Node | Capability |
|------|----------|
| `Node_11_GitHub` | GitHub API integration (repo ops, issue management) |
| `Node_120_File` | File system operations (read, write, delete, search) |
| `Node_121_Web` | Web browsing, URL fetch, content extraction |
| `Node_122_Shell` | Shell command execution |
| `Node_123_Calendar` | Calendar query and scheduling |
| `Node_101_CodeEngine` | Code execution sandbox |
| `Node_106_GitHubFlow` | Git workflow automation |

---

### 3.3 Device Control / Actuation Nodes

**Definition:** Nodes that translate high-level action intent into concrete control of a device or platform. These nodes operate on a specific execution surface (Windows UI, macOS, ADB/Android, desktop automation) and produce verified or attempted-action evidence.

**Key characteristics:**
- Platform-specific; each node targets a specific OS or device type
- Produce execution evidence (screenshots, accessibility feedback, return codes)
- Must handle partial execution and failure modes
- Are candidates for truth-publication integration in later phases

**Representative nodes:**
| Node | Execution surface |
|------|-----------------|
| `Node_33_ADB` | Android device control via ADB (tap, swipe, install, shell) |
| `Node_35_AppleScript` | macOS application control via AppleScript |
| `Node_36_UIAWindows` | Windows UI Automation (click, type, inspect) |
| `Node_45_DesktopAuto` | Cross-platform desktop automation |
| `Node_122_Shell` | Shell/terminal command execution (also Tool node) |

---

### 3.4 Perception / Multimodal Nodes

**Definition:** Nodes that ingest or produce perceptual data: screenshots, OCR output, VLM inference, audio analysis, and grounding annotations. These nodes are the sensory interface of the V2 capability fabric.

**Key characteristics:**
- Produce structured or semi-structured observations from raw sensory data
- Output may be strong (OCR character string) or inferred (VLM scene description)
- Some nodes depend on external model services; others are local
- Android perception emissions feed into these nodes

**Representative nodes:**
| Node | Perception type |
|------|---------------|
| `Node_15_OCR` | Text extraction from images/screenshots |
| `Node_90_MultimodalVision` | General-purpose VLM inference on images |
| `Node_91_MultimodalAgent` | Multimodal agent combining vision and language reasoning |
| `Node_94_AudioAnalysis` | Audio feature extraction and transcription |
| `Node_113_AndroidVLM` | Android-specific VLM inference (local or forwarded) |

---

### 3.5 AI / Planning / Memory / Orchestration Nodes

**Definition:** Nodes that perform high-level reasoning, task planning, context management, memory retrieval, or multi-node orchestration. These nodes consume outputs from tool, actuation, and perception nodes and produce plans, decisions, or coordinated task sequences.

**Key characteristics:**
- Stateful or context-bearing (especially memory nodes)
- May invoke multiple downstream nodes to achieve a goal
- Planning and orchestration nodes are closest to "semantic task" territory — but they are still provider/runtime units, not autonomous semantic task nodes
- Subject to strict authority boundaries (V2 owns orchestration; these nodes execute under that authority)

**Representative nodes:**
| Node | Role |
|------|------|
| `Node_56_Planning` | Task decomposition and step planning |
| `Node_58_ModelRouter` | LLM model selection and routing |
| `Node_80_MemorySystem` | Context storage, retrieval, and freshness management |
| `Node_81_Orchestrator` | Cross-node task orchestration and execution sequencing |
| `Node_91_MultimodalAgent` | Multimodal reasoning and plan grounding (also Perception) |
| `Node_101_CodeEngine` | Code-based reasoning and execution (also Tool) |
| `Node_126_AgentSwarm` | Multi-agent coordination and parallel subtask dispatch |

---

### 3.6 Bridge / Protocol / Integration Nodes

**Definition:** Nodes that translate between system components, external protocols, or third-party services. These nodes are primarily connective — they normalize data formats, mediate API differences, and route messages between subsystems.

**Key characteristics:**
- Primarily message transformation and routing
- May sit between V2 and external services (webhooks, APIs, MCP servers)
- Some bridge nodes also expose tool capabilities, but their primary role is integration

**Representative nodes:**
| Node | Bridge function |
|------|---------------|
| `Node_11_GitHub` | GitHub API bridge (also Tool node) |
| `Node_121_Web` | HTTP/web protocol bridge (also Tool node) |
| `Node_70_MCPBridge` | MCP (Model Context Protocol) server bridge |
| `Node_75_WebhookRelay` | Webhook ingestion and relay |
| `Node_72_AndroidBridge` | Android↔V2 protocol mediation |

---

### 3.7 Stub / Placeholder / Future Concept Nodes

**Definition:** Nodes that are registered in the capability fabric but are not yet fully implemented, are reserved for future capabilities, or exist as interface stubs for planned integrations.

**Key characteristics:**
- May initialize without error but produce no useful output
- Reserved namespace in capabilities.json
- Intended for future phases; their presence does not imply current functionality
- Should not be used in production task routing without validation

**Representative nodes:**
| Node | Status |
|------|--------|
| `Node_95_SemanticGrounding` | Stub: future semantic grounding integration |
| `Node_98_RuntimeContract` | Placeholder: future NodeContract enforcement |
| `Node_99_GraphRuntime` | Placeholder: future semantic task graph runtime |
| `Node_150_AutonomousPlanner` | Stub: future fully autonomous planning agent |

---

## 4. Key Conclusions

### Current Node_XX Are Provider/Runtime Units
All currently operational `Node_XX` are **capability providers and runtime units**. They do not self-schedule, do not own task context, and do not autonomously chain with each other. They are invoked by the orchestrator or planner in response to a task graph step.

### Do Not Conflate Node_XX With Future Semantic Task Nodes
A future semantic task node (as envisioned in Phase 3+) would be:
- Goal-directed and context-aware
- Able to reason about its own invocation conditions
- Participating in a typed capability contract

Current `Node_XX` do not meet these criteria. The semantic annotation layer (Phase 1-1) will enrich existing nodes with metadata, but metadata enrichment does not transform a provider node into a semantic task node.

### Legacy Groupings Remain Valid for Startup/Routing
The `core/development/extended/academic` phase groups and `capabilities.json` categories remain the authoritative source for startup sequencing and capability routing. This role classification is additive — it provides a semantic overlay for later-phase features without replacing existing registry logic.

---

## 5. Meaning for Later Phases

| Phase | How this classification is used |
|-------|--------------------------------|
| **Phase 1-1:** Node semantic capability annotations | Provides the role vocabulary for semantic_role field in annotation spec |
| **Phase 2:** RuntimeCapabilityProfile | Each profile maps to one of these role categories; tool/actuation/perception nodes map to different profile types |
| **Phase 3:** NodeContract enforcement | Contract types will differ by role category (actuation contracts need truth-surface binding; planning contracts need context scope) |
| **Phase 3:** Runtime matching | Role category is a first-pass filter before fine-grained capability matching |
| **Phase 4:** Autonomous agent integration | Stub/Placeholder nodes are candidates for activation; AI/Planning/Orchestration nodes are candidates for semantic elevation |

---

## 6. Summary

The V2 node system contains over 100 `Node_XX` units spanning infrastructure, general tools, device control, perception, AI/planning, protocol bridging, and stub/future concepts. Understanding their real operational roles is a prerequisite for any semantic enrichment, runtime profile mapping, or contract enforcement work.

The classification here is a stable reference baseline. It does not require changes to node implementations, startup logic, or capability routing. It is the foundation layer on which Phase 1-1 semantic annotations, Phase 2 runtime profiles, and Phase 3 contracts will be built.
