"""
Node 56: Multi-Agent Debate System (Agent Swarm)
Galaxy 64-Core MCP Matrix - Phase 5: Scientific Brain

Population-based debate with tournament-style reasoning.
"""

import os
import json
import asyncio
import logging
import hashlib
import random
from typing import Dict, Optional, List, Any, Tuple
from datetime import datetime
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx
from nodes.common.cors_config import get_cors_origins

# =============================================================================
# Configuration
# =============================================================================

from core.port_config import get_service_port, get_node_port

NODE_ID = os.getenv("NODE_ID", "126")
NODE_NAME = os.getenv("NODE_NAME", "AgentSwarm")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", f"http://localhost:{get_service_port('state_machine')}")
MODEL_ROUTER_URL = os.getenv("MODEL_ROUTER_URL", f"http://localhost:{get_node_port('Node_58_ModelRouter')}")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Debate configuration
DEFAULT_AGENT_COUNT = 5
MAX_ROUNDS = 4
CONSENSUS_THRESHOLD = 0.7
DEBATE_TIMEOUT = int(os.getenv("DEBATE_TIMEOUT", "60"))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class ReasoningStrategy(str, Enum):
    COT = "chain_of_thought"           # Step-by-step reasoning
    TOT = "tree_of_thought"            # Branching exploration
    PAL = "program_aided"              # Code-based reasoning
    CRITIQUE = "self_critique"         # Self-revision
    RETRIEVAL = "knowledge_retrieval"  # External knowledge

class DebatePhase(str, Enum):
    PROPOSAL = "proposal"
    CRITIQUE = "critique"
    DEFENSE = "defense"
    CONSENSUS = "consensus"

@dataclass
class AgentProposal:
    """A proposal from a reasoning agent."""
    agent_id: str
    strategy: ReasoningStrategy
    solution: str
    reasoning: List[str]
    confidence: float
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

@dataclass
class Critique:
    """A critique of another agent's proposal."""
    critic_id: str
    target_id: str
    points: List[str]
    severity: str  # "minor", "major", "critical"
    suggested_fix: Optional[str] = None

@dataclass
class DebateRound:
    """A single round of debate."""
    round_number: int
    phase: DebatePhase
    proposals: List[AgentProposal] = field(default_factory=list)
    critiques: List[Critique] = field(default_factory=list)
    consensus_score: float = 0.0

class DebateRequest(BaseModel):
    problem: str = Field(..., description="Problem to solve through debate")
    context: Dict[str, Any] = Field(default={}, description="Additional context")
    agent_count: int = Field(default=DEFAULT_AGENT_COUNT, ge=2, le=10)
    max_rounds: int = Field(default=MAX_ROUNDS, ge=1, le=10)
    strategies: Optional[List[ReasoningStrategy]] = None

class DebateResult(BaseModel):
    problem: str
    final_solution: str
    confidence: float
    consensus_reached: bool
    rounds: List[Dict[str, Any]]
    winning_strategy: str
    agent_contributions: Dict[str, float]
    debate_duration_ms: float

# =============================================================================
# Reasoning Agents
# =============================================================================

class ReasoningAgent(ABC):
    """Base class for reasoning agents."""

    def __init__(self, agent_id: str, strategy: ReasoningStrategy):
        self.agent_id = agent_id
        self.strategy = strategy
        self.history: List[AgentProposal] = []

    @abstractmethod
    async def propose(self, problem: str, context: Dict[str, Any]) -> AgentProposal:
        """Generate a proposal for the problem."""
        pass

    @abstractmethod
    async def critique(self, proposal: AgentProposal) -> Critique:
        """Critique another agent's proposal."""
        pass

    @abstractmethod
    async def defend(self, critiques: List[Critique]) -> AgentProposal:
        """Defend and refine proposal based on critiques."""
        pass

    def _calculate_confidence(self, reasoning_steps: int, has_evidence: bool) -> float:
        """Calculate confidence score."""
        base = 0.5
        step_bonus = min(reasoning_steps * 0.1, 0.3)
        evidence_bonus = 0.2 if has_evidence else 0
        return min(base + step_bonus + evidence_bonus, 0.95)


async def _llm_complete(prompt: str, max_tokens: int = 700) -> str:
    """Real LLM call via Node_58_ModelRouter's /chat, used by every reasoning agent."""
    async with httpx.AsyncClient(timeout=DEBATE_TIMEOUT) as client:
        resp = await client.post(
            f"{MODEL_ROUTER_URL}/chat",
            json={"prompt": prompt, "max_tokens": max_tokens, "temperature": 0.7},
        )
        resp.raise_for_status()
        return resp.json()["response"]


def _parse_steps_and_solution(text: str) -> Tuple[List[str], str]:
    """Parse a STEP:/SOLUTION: formatted LLM response into (reasoning steps, solution).

    Falls back to treating the whole response as the solution with no
    structured steps if the model didn't follow the requested format -
    real model output can't be guaranteed to be perfectly formatted.
    """
    steps: List[str] = []
    solution = ""
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("STEP:"):
            steps.append(line.split(":", 1)[1].strip())
        elif line.upper().startswith("SOLUTION:"):
            solution = line.split(":", 1)[1].strip()
    if not solution:
        solution = text.strip()
    return steps, solution


def _parse_critique(text: str) -> Tuple[List[str], str, Optional[str]]:
    """Parse a POINT:/SEVERITY:/FIX: formatted LLM response."""
    points: List[str] = []
    severity = "minor"
    fix: Optional[str] = None
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("POINT:"):
            points.append(line.split(":", 1)[1].strip())
        elif line.upper().startswith("SEVERITY:"):
            candidate = line.split(":", 1)[1].strip().lower()
            if candidate in ("minor", "major", "critical"):
                severity = candidate
        elif line.upper().startswith("FIX:"):
            value = line.split(":", 1)[1].strip()
            if value and value.lower() != "none":
                fix = value
    if not points:
        points = ["No significant issues found"]
    return points, severity, fix


# Per-strategy instructions that give each agent a genuinely different
# reasoning approach to the same problem, rather than just a different label.
_STRATEGY_INSTRUCTIONS: Dict[ReasoningStrategy, str] = {
    ReasoningStrategy.COT: (
        "Solve this using explicit step-by-step chain-of-thought reasoning. "
        "Work through the problem logically, one step at a time."
    ),
    ReasoningStrategy.TOT: (
        "Solve this using tree-of-thought reasoning: consider at least 3 distinct "
        "solution approaches (branches), briefly evaluate each, then commit to the "
        "best one. Show each branch as its own step."
    ),
    ReasoningStrategy.PAL: (
        "Solve this using program-aided reasoning: express your solution as actual "
        "working code (a real function/algorithm), and use each step to explain a "
        "piece of that code's logic."
    ),
    ReasoningStrategy.CRITIQUE: (
        "Solve this using self-critique: first draft a solution, then critique your "
        "own draft for weaknesses, then produce a refined final solution. Show the "
        "draft, the self-critique, and the revision as separate steps."
    ),
    ReasoningStrategy.RETRIEVAL: (
        "Solve this using knowledge retrieval: first state what relevant background "
        "knowledge/facts/techniques apply to this problem (as steps), then use them "
        "to construct your solution."
    ),
}

_RESPONSE_FORMAT = (
    'Respond ONLY in this exact format (one line per step):\n'
    "STEP: <reasoning step>\n"
    "STEP: <reasoning step>\n"
    "...\n"
    "SOLUTION: <your final solution, self-contained>"
)


class LLMReasoningAgent(ReasoningAgent):
    """Reasoning agent whose propose/critique/defend are real LLM calls
    (via Node_58_ModelRouter), differentiated per strategy by
    _STRATEGY_INSTRUCTIONS. Concrete strategy subclasses below just fix
    the strategy passed to __init__.
    """

    def __init__(self, agent_id: str, strategy: ReasoningStrategy):
        super().__init__(agent_id, strategy)
        self._last_problem: str = ""

    async def propose(self, problem: str, context: Dict[str, Any]) -> AgentProposal:
        self._last_problem = problem
        instruction = _STRATEGY_INSTRUCTIONS[self.strategy]
        context_note = f"\nAdditional context: {context}" if context else ""
        prompt = f"{instruction}\n\nProblem: {problem}{context_note}\n\n{_RESPONSE_FORMAT}"

        response = await _llm_complete(prompt)
        steps, solution = _parse_steps_and_solution(response)
        confidence = self._calculate_confidence(len(steps), bool(steps))

        proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=solution,
            reasoning=steps,
            confidence=confidence,
        )
        self.history.append(proposal)
        return proposal

    async def critique(self, proposal: AgentProposal) -> Critique:
        prompt = (
            f"You are reviewing another AI agent's proposed solution to this problem:\n"
            f"Problem: {self._last_problem or '(unknown - reviewing in isolation)'}\n\n"
            f"Their solution: {proposal.solution}\n"
            f"Their reasoning steps:\n" + "\n".join(f"- {s}" for s in proposal.reasoning) + "\n\n"
            "Critique it critically and constructively. Respond ONLY in this format:\n"
            "POINT: <specific issue>\n"
            "POINT: <specific issue>\n"
            "...\n"
            "SEVERITY: minor|major|critical\n"
            "FIX: <concrete suggested fix, or 'none' if no fix needed>"
        )
        response = await _llm_complete(prompt, max_tokens=400)
        points, severity, fix = _parse_critique(response)

        return Critique(
            critic_id=self.agent_id,
            target_id=proposal.agent_id,
            points=points,
            severity=severity,
            suggested_fix=fix,
        )

    async def defend(self, critiques: List[Critique]) -> AgentProposal:
        if not self.history:
            raise ValueError("No previous proposal to defend")
        last_proposal = self.history[-1]

        if critiques:
            critique_text = "\n".join(
                f"- ({c.severity}) {point}" + (f" Suggested fix: {c.suggested_fix}" if c.suggested_fix else "")
                for c in critiques for point in c.points
            )
            prompt = (
                f"Problem: {self._last_problem}\n\n"
                f"Your previous solution: {last_proposal.solution}\n"
                f"Your previous reasoning:\n" + "\n".join(f"- {s}" for s in last_proposal.reasoning) + "\n\n"
                f"Other agents raised these critiques:\n{critique_text}\n\n"
                "Revise and improve your solution to address these critiques. "
                f"{_RESPONSE_FORMAT}"
            )
        else:
            prompt = (
                f"Problem: {self._last_problem}\n\n"
                f"Your previous solution: {last_proposal.solution}\n"
                "No critiques were raised. Refine and strengthen your solution further if possible. "
                f"{_RESPONSE_FORMAT}"
            )

        response = await _llm_complete(prompt)
        steps, solution = _parse_steps_and_solution(response)
        confidence = self._calculate_confidence(len(steps), bool(steps))

        new_proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=solution,
            reasoning=steps or last_proposal.reasoning,
            confidence=max(confidence, last_proposal.confidence),
        )
        self.history.append(new_proposal)
        return new_proposal


class ChainOfThoughtAgent(LLMReasoningAgent):
    """Agent using Chain-of-Thought reasoning."""

    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.COT)


class TreeOfThoughtAgent(LLMReasoningAgent):
    """Agent using Tree-of-Thought reasoning."""

    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.TOT)


class ProgramAidedAgent(LLMReasoningAgent):
    """Agent using Program-Aided Language reasoning."""

    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.PAL)


class SelfCritiqueAgent(LLMReasoningAgent):
    """Agent using Self-Critique and Revision."""

    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.CRITIQUE)


class KnowledgeRetrievalAgent(LLMReasoningAgent):
    """Agent using External Knowledge Retrieval."""

    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.RETRIEVAL)

# =============================================================================
# Debate Orchestrator
# =============================================================================

class DebateOrchestrator:
    """Orchestrates multi-agent debates."""
    
    AGENT_CLASSES = {
        ReasoningStrategy.COT: ChainOfThoughtAgent,
        ReasoningStrategy.TOT: TreeOfThoughtAgent,
        ReasoningStrategy.PAL: ProgramAidedAgent,
        ReasoningStrategy.CRITIQUE: SelfCritiqueAgent,
        ReasoningStrategy.RETRIEVAL: KnowledgeRetrievalAgent,
    }
    
    def __init__(self):
        self.debate_history: List[Dict[str, Any]] = []
        self.strategy_performance: Dict[str, List[float]] = {s.value: [] for s in ReasoningStrategy}
    
    async def run_debate(self, request: DebateRequest) -> DebateResult:
        """Run a full debate session."""
        import time
        start_time = time.time()
        
        # Create agents
        strategies = request.strategies or list(ReasoningStrategy)[:request.agent_count]
        agents = self._create_agents(strategies)
        
        rounds: List[DebateRound] = []
        
        # Round 1: Initial proposals
        round1 = await self._run_proposal_round(agents, request.problem, request.context)
        rounds.append(round1)
        
        # Round 2: Cross-critique
        round2 = await self._run_critique_round(agents, round1.proposals)
        rounds.append(round2)
        
        # Round 3: Defense and refinement
        round3 = await self._run_defense_round(agents, round2.critiques)
        rounds.append(round3)
        
        # Round 4: Consensus building
        round4 = await self._run_consensus_round(agents, rounds)
        rounds.append(round4)
        
        # Determine winner
        final_solution, winning_strategy, confidence = self._determine_winner(rounds)
        
        # Calculate contributions
        contributions = self._calculate_contributions(agents, rounds)
        
        # Update strategy performance
        for agent in agents:
            self.strategy_performance[agent.strategy.value].append(contributions.get(agent.agent_id, 0))
        
        duration = (time.time() - start_time) * 1000
        
        result = DebateResult(
            problem=request.problem,
            final_solution=final_solution,
            confidence=confidence,
            consensus_reached=round4.consensus_score >= CONSENSUS_THRESHOLD,
            rounds=[self._round_to_dict(r) for r in rounds],
            winning_strategy=winning_strategy,
            agent_contributions=contributions,
            debate_duration_ms=duration
        )
        
        # Store in history
        self.debate_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "problem": request.problem[:100],
            "winning_strategy": winning_strategy,
            "confidence": confidence
        })
        
        return result
    
    def _create_agents(self, strategies: List[ReasoningStrategy]) -> List[ReasoningAgent]:
        """Create debate agents."""
        agents = []
        for i, strategy in enumerate(strategies):
            agent_class = self.AGENT_CLASSES.get(strategy, ChainOfThoughtAgent)
            agents.append(agent_class(f"agent_{i}_{strategy.value}"))
        return agents
    
    async def _run_proposal_round(
        self,
        agents: List[ReasoningAgent],
        problem: str,
        context: Dict[str, Any]
    ) -> DebateRound:
        """Run proposal round.

        每个 agent 的 propose() 是一次独立的 LLM 调用(真实 httpx 请求打到
        Node_58),彼此互不依赖——之前用 for + await 顺序跑,N 个 agent 就是
        N 倍单次调用延迟,不是最慢那个 agent 的延迟。改用 asyncio.gather 真正
        并发,这才是这层"多智能体"名副其实的地方:agent 数量增加不再线性
        拉长这一轮耗时。
        """
        proposals = list(await asyncio.gather(
            *(agent.propose(problem, context) for agent in agents)
        ))

        return DebateRound(
            round_number=1,
            phase=DebatePhase.PROPOSAL,
            proposals=proposals
        )

    async def _run_critique_round(
        self,
        agents: List[ReasoningAgent],
        proposals: List[AgentProposal]
    ) -> DebateRound:
        """Run critique round(同上:每个 agent 对目标的 critique 调用互相独立,并发跑)。"""
        tasks = []
        for agent in agents:
            # Each agent critiques 2 others
            other_proposals = [p for p in proposals if p.agent_id != agent.agent_id]
            targets = random.sample(other_proposals, min(2, len(other_proposals)))
            tasks.extend(agent.critique(target) for target in targets)

        critiques = list(await asyncio.gather(*tasks)) if tasks else []

        return DebateRound(
            round_number=2,
            phase=DebatePhase.CRITIQUE,
            critiques=critiques
        )

    async def _run_defense_round(
        self,
        agents: List[ReasoningAgent],
        critiques: List[Critique]
    ) -> DebateRound:
        """Run defense round(同上:每个 agent 的辩护调用互相独立,并发跑)。"""
        async def _defend(agent: ReasoningAgent) -> AgentProposal:
            agent_critiques = [c for c in critiques if c.target_id == agent.agent_id]
            return await agent.defend(agent_critiques)

        proposals = list(await asyncio.gather(*(_defend(agent) for agent in agents)))

        return DebateRound(
            round_number=3,
            phase=DebatePhase.DEFENSE,
            proposals=proposals
        )
    
    async def _run_consensus_round(
        self,
        agents: List[ReasoningAgent],
        previous_rounds: List[DebateRound]
    ) -> DebateRound:
        """Run consensus building round."""
        # Get latest proposals
        latest_proposals = previous_rounds[-1].proposals if previous_rounds[-1].proposals else previous_rounds[0].proposals
        
        # Calculate consensus score
        confidences = [p.confidence for p in latest_proposals]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        # Check solution similarity (simplified)
        solutions = [p.solution for p in latest_proposals]
        unique_solutions = len(set(solutions))
        similarity = 1 - (unique_solutions - 1) / max(len(solutions), 1)
        
        consensus_score = (avg_confidence + similarity) / 2
        
        return DebateRound(
            round_number=4,
            phase=DebatePhase.CONSENSUS,
            proposals=latest_proposals,
            consensus_score=consensus_score
        )
    
    def _determine_winner(self, rounds: List[DebateRound]) -> Tuple[str, str, float]:
        """Determine winning solution."""
        # Get final proposals
        final_proposals = rounds[-1].proposals
        
        if not final_proposals:
            return "No solution reached", "none", 0.0
        
        # Find highest confidence
        best = max(final_proposals, key=lambda p: p.confidence)
        
        return best.solution, best.strategy.value, best.confidence
    
    def _calculate_contributions(
        self,
        agents: List[ReasoningAgent],
        rounds: List[DebateRound]
    ) -> Dict[str, float]:
        """Calculate each agent's contribution."""
        contributions = {}
        
        for agent in agents:
            # Base contribution from proposals
            proposal_count = sum(
                1 for r in rounds for p in r.proposals if p.agent_id == agent.agent_id
            )
            
            # Contribution from critiques
            critique_count = sum(
                1 for r in rounds for c in r.critiques if c.critic_id == agent.agent_id
            )
            
            # Final confidence
            final_confidence = 0
            for r in reversed(rounds):
                for p in r.proposals:
                    if p.agent_id == agent.agent_id:
                        final_confidence = p.confidence
                        break
                if final_confidence:
                    break
            
            contributions[agent.agent_id] = (
                proposal_count * 0.3 +
                critique_count * 0.2 +
                final_confidence * 0.5
            )
        
        # Normalize
        total = sum(contributions.values())
        if total > 0:
            contributions = {k: v / total for k, v in contributions.items()}
        
        return contributions
    
    def _round_to_dict(self, round: DebateRound) -> Dict[str, Any]:
        """Convert round to dictionary."""
        return {
            "round_number": round.round_number,
            "phase": round.phase.value,
            "proposals": [
                {
                    "agent_id": p.agent_id,
                    "strategy": p.strategy.value,
                    "solution": p.solution,
                    "reasoning_steps": len(p.reasoning),
                    "confidence": p.confidence
                }
                for p in round.proposals
            ],
            "critiques": [
                {
                    "critic": c.critic_id,
                    "target": c.target_id,
                    "severity": c.severity,
                    "points_count": len(c.points)
                }
                for c in round.critiques
            ],
            "consensus_score": round.consensus_score
        }
    
    def get_strategy_stats(self) -> Dict[str, Any]:
        """Get strategy performance statistics."""
        stats = {}
        for strategy, scores in self.strategy_performance.items():
            if scores:
                stats[strategy] = {
                    "debates": len(scores),
                    "avg_contribution": sum(scores) / len(scores),
                    "max_contribution": max(scores),
                    "min_contribution": min(scores)
                }
        return stats

# =============================================================================
# FastAPI Application
# =============================================================================

orchestrator: Optional[DebateOrchestrator] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global orchestrator
    
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME}")
    orchestrator = DebateOrchestrator()
    logger.info(f"Node {NODE_ID} ({NODE_NAME}) is ready")
    
    yield
    
    logger.info(f"Shutting down Node {NODE_ID}")

app = FastAPI(
    title=f"Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Multi-Agent Debate System with Tournament-Style Reasoning",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
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
        "debates_completed": len(orchestrator.debate_history) if orchestrator else 0
    }

@app.post("/debate", response_model=DebateResult)
async def run_debate(request: DebateRequest):
    """Run a multi-agent debate."""
    return await orchestrator.run_debate(request)

@app.get("/strategies")
async def list_strategies():
    """List available reasoning strategies."""
    return {
        "strategies": [
            {
                "name": s.value,
                "description": _get_strategy_description(s)
            }
            for s in ReasoningStrategy
        ]
    }

@app.get("/strategy-stats")
async def get_strategy_stats():
    """Get strategy performance statistics."""
    return orchestrator.get_strategy_stats()

@app.get("/history")
async def get_debate_history(limit: int = 50):
    """Get recent debate history."""
    return {
        "debates": orchestrator.debate_history[-limit:],
        "total": len(orchestrator.debate_history)
    }

@app.get("/stats")
async def get_stats():
    """Get overall statistics."""
    history = orchestrator.debate_history
    
    if not history:
        return {"total_debates": 0}
    
    winning_strategies = [d["winning_strategy"] for d in history]
    strategy_wins = {}
    for s in winning_strategies:
        strategy_wins[s] = strategy_wins.get(s, 0) + 1
    
    return {
        "total_debates": len(history),
        "avg_confidence": sum(d["confidence"] for d in history) / len(history),
        "strategy_wins": strategy_wins,
        "strategy_performance": orchestrator.get_strategy_stats()
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "layer": "L1_GATEWAY",
        "capabilities": ["multi_agent_debate", "tournament_reasoning", "consensus_building"]
    }

def _get_strategy_description(strategy: ReasoningStrategy) -> str:
    """Get strategy description."""
    descriptions = {
        ReasoningStrategy.COT: "Chain-of-Thought: Step-by-step logical reasoning",
        ReasoningStrategy.TOT: "Tree-of-Thought: Branching exploration of solution paths",
        ReasoningStrategy.PAL: "Program-Aided Language: Code-based computational reasoning",
        ReasoningStrategy.CRITIQUE: "Self-Critique: Iterative self-revision and refinement",
        ReasoningStrategy.RETRIEVAL: "Knowledge Retrieval: External knowledge-backed reasoning",
    }
    return descriptions.get(strategy, "Reasoning strategy")

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8126,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
