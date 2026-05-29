"""
galaxy_gateway/routes/swarm.py — Agent Swarm dispatch API.

POST /api/v1/swarm/dispatch
  Body: {"team_name": str, "mission": str, "strategy": "parallel|specialized|swarm"}
  Response: {"task_id": str, "status": "dispatched", "assignments": [...]}

GET /api/v1/swarm/teams
  Response: {"teams": [{"name": str, "members": [...], "strategy": str}]}

GET /api/v1/swarm/status/{task_id}
  Response: {"task_id": str, "status": str, "results": [...]}
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.agent_team import AgentTeam, TeamMember, TeamResult, TeamStrategy
from core.schemas.orchestration import OrchestrationRequest, OrchestrationResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/swarm", tags=["swarm"])


# ── Pydantic request/response models ──

class DispatchRequest(BaseModel):
    team_name: str = Field(default="default", description="Name of the Agent team to dispatch")
    mission: str = Field(..., description="Mission description / user prompt")
    strategy: str = Field(default="specialized", description="Team strategy: parallel | specialized | swarm")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Extra context for the mission")


class DispatchResponse(BaseModel):
    task_id: str
    status: str
    strategy: str
    member_count: int
    assignments: List[Dict[str, Any]]


class TeamInfo(BaseModel):
    name: str
    members: List[str]
    strategy: str
    description: str


class TeamsResponse(BaseModel):
    teams: List[TeamInfo]


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: float = Field(ge=0.0, le=1.0)
    results: List[Dict[str, Any]]


# ── Default Agent Teams ──

DEFAULT_TEAMS: Dict[str, AgentTeam] = {}


def _init_default_teams() -> None:
    """Initialize built-in Agent teams on first call."""
    global DEFAULT_TEAMS
    if DEFAULT_TEAMS:
        return

    # Team 1: Core Operations — system management, node control, diagnostics
    DEFAULT_TEAMS["core"] = AgentTeam(
        name="core",
        strategy=TeamStrategy.SPECIALIZED,
        members=[
            TeamMember(name="node_operator", role="node_control", llm_preference="ollama", priority=1),
            TeamMember(name="system_admin", role="diagnostics", llm_preference="ollama", priority=2),
            TeamMember(name="mesh_coordinator", role="mesh_sync", llm_preference="ollama", priority=3),
        ],
    )

    # Team 2: Research — information gathering, analysis, coding
    DEFAULT_TEAMS["research"] = AgentTeam(
        name="research",
        strategy=TeamStrategy.PARALLEL,
        members=[
            TeamMember(name="analyst", role="data_analysis", llm_preference="deepseek", priority=1),
            TeamMember(name="coder", role="code_generation", llm_preference="qwen", priority=2),
            TeamMember(name="searcher", role="web_search", llm_preference="openai", priority=3),
        ],
    )

    # Team 3: Creative — content creation, design, media
    DEFAULT_TEAMS["creative"] = AgentTeam(
        name="creative",
        strategy=TeamStrategy.SWARM,
        members=[
            TeamMember(name="writer", role="content_writing", llm_preference="claude", priority=1),
            TeamMember(name="designer", role="ui_ux", llm_preference="openai", priority=2),
        ],
    )

    logger.info("Default Agent teams initialized: %s", list(DEFAULT_TEAMS.keys()))


# ── Route handlers ──

@router.post("/dispatch", response_model=DispatchResponse)
async def dispatch_team(request: DispatchRequest, req: Request):
    """Dispatch an Agent team to execute a mission."""
    _init_default_teams()

    swarm_coordinator = getattr(req.app.state, "swarm_coordinator", None)
    if swarm_coordinator is None:
        raise HTTPException(status_code=503, detail="SwarmCoordinator not initialized")

    # Resolve strategy
    try:
        strategy = TeamStrategy(request.strategy.lower())
    except ValueError:
        strategy = TeamStrategy.SPECIALIZED

    # Resolve team
    team = DEFAULT_TEAMS.get(request.team_name)
    if team is None:
        # Fall back to core team with overridden strategy
        team = DEFAULT_TEAMS.get("core", AgentTeam(name="fallback", strategy=strategy, members=[]))
        team = team.model_copy(update={"strategy": strategy})

    task_id = f"swarm-{uuid.uuid4().hex[:12]}"

    # Build orchestration request
    orch_request = OrchestrationRequest(
        mission=request.mission,
        team=team,
        context=request.context or {},
    )

    try:
        result: OrchestrationResult = await swarm_coordinator.dispatch_team(
            team=team,
            orch_request=orch_request,
            task_id=task_id,
        )

        assignments = []
        for member, device in zip(result.members, result.assigned_devices):
            assignments.append({
                "member": member.name,
                "role": member.role,
                "device": device,
                "status": "assigned",
            })

        return DispatchResponse(
            task_id=task_id,
            status="dispatched",
            strategy=strategy.value,
            member_count=len(team.members),
            assignments=assignments,
        )

    except Exception as e:
        logger.error("Swarm dispatch failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Dispatch failed: {e}") from e


@router.get("/teams", response_model=TeamsResponse)
async def list_teams():
    """List all available Agent teams."""
    _init_default_teams()

    teams = []
    for name, team in DEFAULT_TEAMS.items():
        teams.append(TeamInfo(
            name=name,
            members=[m.name for m in team.members],
            strategy=team.strategy.value,
            description=f"{len(team.members)} members, {team.strategy.value} strategy",
        ))

    return TeamsResponse(teams=teams)


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str, req: Request):
    """Get the status of a dispatched swarm task."""
    swarm_coordinator = getattr(req.app.state, "swarm_coordinator", None)
    if swarm_coordinator is None:
        raise HTTPException(status_code=503, detail="SwarmCoordinator not initialized")

    # TODO: Implement real task tracking via TaskRegistry
    return TaskStatusResponse(
        task_id=task_id,
        status="running",
        progress=0.5,
        results=[],
    )
