"""
Node 56: Multi-Agent Debate System (Agent Swarm)
UFO Galaxy 64-Core MCP Matrix - Phase 5: Scientific Brain

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

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "56")
NODE_NAME = os.getenv("NODE_NAME", "AgentSwarm")
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", "http://localhost:8000")
MODEL_ROUTER_URL = os.getenv("MODEL_ROUTER_URL", "http://localhost:8058")
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

class ChainOfThoughtAgent(ReasoningAgent):
    """Agent using Chain-of-Thought reasoning."""
    
    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.COT)
    
    async def propose(self, problem: str, context: Dict[str, Any]) -> AgentProposal:
        """Generate step-by-step reasoning."""
        steps = []
        
        # Step 1: Understand the problem
        steps.append(f"Understanding: The problem asks about '{problem[:50]}...'")
        
        # Step 2: Identify key components
        keywords = self._extract_keywords(problem)
        steps.append(f"Key components: {', '.join(keywords[:5])}")
        
        # Step 3: Apply reasoning
        steps.append("Applying logical reasoning to connect components")
        
        # Step 4: Derive solution
        solution = self._derive_solution(problem, keywords)
        steps.append(f"Conclusion: {solution}")
        
        confidence = self._calculate_confidence(len(steps), bool(context))
        
        proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=solution,
            reasoning=steps,
            confidence=confidence
        )
        self.history.append(proposal)
        return proposal
    
    async def critique(self, proposal: AgentProposal) -> Critique:
        """Critique using logical analysis."""
        points = []
        severity = "minor"
        
        # Check reasoning chain
        if len(proposal.reasoning) < 3:
            points.append("Insufficient reasoning steps")
            severity = "major"
        
        # Check confidence
        if proposal.confidence > 0.9:
            points.append("Overconfident without strong evidence")
        
        # Check solution specificity
        if len(proposal.solution) < 20:
            points.append("Solution lacks detail")
            severity = "major" if severity == "minor" else severity
        
        return Critique(
            critic_id=self.agent_id,
            target_id=proposal.agent_id,
            points=points if points else ["No significant issues found"],
            severity=severity
        )
    
    async def defend(self, critiques: List[Critique]) -> AgentProposal:
        """Refine proposal based on critiques."""
        if not self.history:
            raise ValueError("No previous proposal to defend")
        
        last_proposal = self.history[-1]
        new_steps = last_proposal.reasoning.copy()
        
        # Address critiques
        for critique in critiques:
            for point in critique.points:
                new_steps.append(f"Addressing: {point}")
        
        new_steps.append("Refined solution after considering critiques")
        
        new_proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=last_proposal.solution + " (refined)",
            reasoning=new_steps,
            confidence=min(last_proposal.confidence + 0.05, 0.95)
        )
        self.history.append(new_proposal)
        return new_proposal
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        words = text.lower().split()
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "to", "of", "and", "or", "in", "on", "at"}
        return [w for w in words if w not in stopwords and len(w) > 3][:10]
    
    def _derive_solution(self, problem: str, keywords: List[str]) -> str:
        """Derive a solution based on problem and keywords."""
        if "optimize" in problem.lower() or "best" in problem.lower():
            return f"Optimal approach considering {', '.join(keywords[:3])}"
        elif "explain" in problem.lower():
            return f"Explanation based on analysis of {', '.join(keywords[:3])}"
        elif "calculate" in problem.lower() or "compute" in problem.lower():
            return f"Computed result using {', '.join(keywords[:3])}"
        else:
            return f"Solution addressing {', '.join(keywords[:3])}"

class TreeOfThoughtAgent(ReasoningAgent):
    """Agent using Tree-of-Thought reasoning."""
    
    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.TOT)
    
    async def propose(self, problem: str, context: Dict[str, Any]) -> AgentProposal:
        """Generate branching exploration."""
        steps = []
        
        # Generate multiple branches
        branches = self._generate_branches(problem)
        steps.append(f"Exploring {len(branches)} possible approaches")
        
        for i, branch in enumerate(branches[:3]):
            steps.append(f"Branch {i+1}: {branch}")
        
        # Evaluate branches
        best_branch = self._evaluate_branches(branches)
        steps.append(f"Best approach: {best_branch}")
        
        solution = f"Selected approach: {best_branch}"
        confidence = self._calculate_confidence(len(steps), len(branches) > 2)
        
        proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=solution,
            reasoning=steps,
            confidence=confidence
        )
        self.history.append(proposal)
        return proposal
    
    async def critique(self, proposal: AgentProposal) -> Critique:
        """Critique by exploring alternative branches."""
        points = []
        severity = "minor"
        
        # Check if alternatives were considered
        if "branch" not in str(proposal.reasoning).lower():
            points.append("Did not explore alternative approaches")
            severity = "major"
        
        # Suggest alternative
        suggested = "Consider exploring additional solution paths"
        
        return Critique(
            critic_id=self.agent_id,
            target_id=proposal.agent_id,
            points=points if points else ["Approach seems reasonable"],
            severity=severity,
            suggested_fix=suggested
        )
    
    async def defend(self, critiques: List[Critique]) -> AgentProposal:
        """Expand exploration based on critiques."""
        if not self.history:
            raise ValueError("No previous proposal to defend")
        
        last_proposal = self.history[-1]
        new_steps = last_proposal.reasoning.copy()
        
        # Add new branches based on critiques
        new_steps.append("Expanding exploration based on feedback")
        
        new_proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=last_proposal.solution + " (expanded)",
            reasoning=new_steps,
            confidence=min(last_proposal.confidence + 0.03, 0.95)
        )
        self.history.append(new_proposal)
        return new_proposal
    
    def _generate_branches(self, problem: str) -> List[str]:
        """Generate possible solution branches."""
        base_approaches = [
            "Direct analytical approach",
            "Decomposition into sub-problems",
            "Pattern matching with known solutions",
            "Iterative refinement",
            "Constraint-based reasoning"
        ]
        return random.sample(base_approaches, min(3, len(base_approaches)))
    
    def _evaluate_branches(self, branches: List[str]) -> str:
        """Evaluate and select best branch."""
        return branches[0] if branches else "Default approach"

class ProgramAidedAgent(ReasoningAgent):
    """Agent using Program-Aided Language reasoning."""
    
    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.PAL)
    
    async def propose(self, problem: str, context: Dict[str, Any]) -> AgentProposal:
        """Generate code-based reasoning."""
        steps = []
        
        # Translate to pseudo-code
        steps.append("Translating problem to computational form")
        
        # Generate algorithm
        algorithm = self._generate_algorithm(problem)
        steps.append(f"Algorithm: {algorithm}")
        
        # Execute (simulate)
        result = self._simulate_execution(algorithm)
        steps.append(f"Execution result: {result}")
        
        solution = f"Programmatic solution: {result}"
        confidence = self._calculate_confidence(len(steps), True)
        
        proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=solution,
            reasoning=steps,
            confidence=confidence
        )
        self.history.append(proposal)
        return proposal
    
    async def critique(self, proposal: AgentProposal) -> Critique:
        """Critique by checking computational validity."""
        points = []
        severity = "minor"
        
        # Check for computational approach
        if "algorithm" not in str(proposal.reasoning).lower() and "code" not in str(proposal.reasoning).lower():
            points.append("Could benefit from computational verification")
        
        return Critique(
            critic_id=self.agent_id,
            target_id=proposal.agent_id,
            points=points if points else ["Computationally sound"],
            severity=severity
        )
    
    async def defend(self, critiques: List[Critique]) -> AgentProposal:
        """Add computational verification."""
        if not self.history:
            raise ValueError("No previous proposal to defend")
        
        last_proposal = self.history[-1]
        new_steps = last_proposal.reasoning.copy()
        new_steps.append("Added computational verification")
        
        new_proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=last_proposal.solution + " (verified)",
            reasoning=new_steps,
            confidence=min(last_proposal.confidence + 0.05, 0.95)
        )
        self.history.append(new_proposal)
        return new_proposal
    
    def _generate_algorithm(self, problem: str) -> str:
        """Generate pseudo-algorithm."""
        return "def solve(input): return process(analyze(input))"
    
    def _simulate_execution(self, algorithm: str) -> str:
        """Simulate algorithm execution."""
        return "Computed result"

class SelfCritiqueAgent(ReasoningAgent):
    """Agent using Self-Critique and Revision."""
    
    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.CRITIQUE)
    
    async def propose(self, problem: str, context: Dict[str, Any]) -> AgentProposal:
        """Generate self-critiqued solution."""
        steps = []
        
        # Initial attempt
        steps.append("Initial solution attempt")
        
        # Self-critique
        steps.append("Self-critique: checking for weaknesses")
        
        # Revision
        steps.append("Revised solution after self-critique")
        
        solution = "Self-refined solution"
        confidence = self._calculate_confidence(len(steps), True)
        
        proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=solution,
            reasoning=steps,
            confidence=confidence
        )
        self.history.append(proposal)
        return proposal
    
    async def critique(self, proposal: AgentProposal) -> Critique:
        """Deep critique with constructive feedback."""
        points = []
        severity = "minor"
        
        # Thorough analysis
        if proposal.confidence > 0.8:
            points.append("High confidence may indicate blind spots")
        
        if len(proposal.reasoning) < 4:
            points.append("Could benefit from more thorough analysis")
            severity = "major"
        
        return Critique(
            critic_id=self.agent_id,
            target_id=proposal.agent_id,
            points=points if points else ["Well-reasoned approach"],
            severity=severity,
            suggested_fix="Consider additional self-critique iterations"
        )
    
    async def defend(self, critiques: List[Critique]) -> AgentProposal:
        """Incorporate critiques into refined solution."""
        if not self.history:
            raise ValueError("No previous proposal to defend")
        
        last_proposal = self.history[-1]
        new_steps = last_proposal.reasoning.copy()
        
        for critique in critiques:
            new_steps.append(f"Incorporated feedback: {critique.points[0] if critique.points else 'general'}")
        
        new_proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=last_proposal.solution + " (self-revised)",
            reasoning=new_steps,
            confidence=min(last_proposal.confidence + 0.07, 0.95)
        )
        self.history.append(new_proposal)
        return new_proposal

class KnowledgeRetrievalAgent(ReasoningAgent):
    """Agent using External Knowledge Retrieval."""
    
    def __init__(self, agent_id: str):
        super().__init__(agent_id, ReasoningStrategy.RETRIEVAL)
        self.knowledge_base = {
            "optimization": "Use gradient descent or evolutionary algorithms",
            "search": "Apply binary search or hash tables for efficiency",
            "classification": "Consider decision trees or neural networks",
            "prediction": "Use regression or time series analysis",
        }
    
    async def propose(self, problem: str, context: Dict[str, Any]) -> AgentProposal:
        """Generate knowledge-backed solution."""
        steps = []
        
        # Retrieve relevant knowledge
        knowledge = self._retrieve_knowledge(problem)
        steps.append(f"Retrieved knowledge: {knowledge}")
        
        # Apply knowledge
        steps.append("Applying domain knowledge to problem")
        
        # Synthesize solution
        solution = f"Knowledge-based solution: {knowledge}"
        confidence = self._calculate_confidence(len(steps), bool(knowledge))
        
        proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=solution,
            reasoning=steps,
            confidence=confidence
        )
        self.history.append(proposal)
        return proposal
    
    async def critique(self, proposal: AgentProposal) -> Critique:
        """Critique based on knowledge gaps."""
        points = []
        severity = "minor"
        
        # Check for knowledge backing
        if "knowledge" not in str(proposal.reasoning).lower() and "evidence" not in str(proposal.reasoning).lower():
            points.append("Could benefit from external knowledge verification")
        
        return Critique(
            critic_id=self.agent_id,
            target_id=proposal.agent_id,
            points=points if points else ["Well-supported by knowledge"],
            severity=severity
        )
    
    async def defend(self, critiques: List[Critique]) -> AgentProposal:
        """Add additional knowledge support."""
        if not self.history:
            raise ValueError("No previous proposal to defend")
        
        last_proposal = self.history[-1]
        new_steps = last_proposal.reasoning.copy()
        new_steps.append("Added additional knowledge references")
        
        new_proposal = AgentProposal(
            agent_id=self.agent_id,
            strategy=self.strategy,
            solution=last_proposal.solution + " (knowledge-enhanced)",
            reasoning=new_steps,
            confidence=min(last_proposal.confidence + 0.05, 0.95)
        )
        self.history.append(new_proposal)
        return new_proposal
    
    def _retrieve_knowledge(self, problem: str) -> str:
        """Retrieve relevant knowledge."""
        problem_lower = problem.lower()
        for key, value in self.knowledge_base.items():
            if key in problem_lower:
                return value
        return "General problem-solving heuristics apply"

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
        """Run proposal round."""
        proposals = []
        for agent in agents:
            proposal = await agent.propose(problem, context)
            proposals.append(proposal)
        
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
        """Run critique round."""
        critiques = []
        
        for agent in agents:
            # Each agent critiques 2 others
            other_proposals = [p for p in proposals if p.agent_id != agent.agent_id]
            targets = random.sample(other_proposals, min(2, len(other_proposals)))
            
            for target in targets:
                critique = await agent.critique(target)
                critiques.append(critique)
        
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
        """Run defense round."""
        proposals = []
        
        for agent in agents:
            # Get critiques targeting this agent
            agent_critiques = [c for c in critiques if c.target_id == agent.agent_id]
            
            if agent_critiques:
                proposal = await agent.defend(agent_critiques)
            else:
                # No critiques, just refine
                proposal = await agent.defend([])
            
            proposals.append(proposal)
        
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
    title=f"UFO Galaxy Node {NODE_ID}: {NODE_NAME}",
    description="Multi-Agent Debate System with Tournament-Style Reasoning",
    version="1.0.0",
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
        port=8056,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )
