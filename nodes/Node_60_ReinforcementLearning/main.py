"""
Node 60: ReinforcementLearning - Q-Learning & Policy Gradient Agent
"""
import os
import math
import random
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    from core.port_config import get_node_port
    PORT = get_node_port("Node_60_ReinforcementLearning")
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    PORT = int(os.getenv("NODE_PORT", os.getenv("PORT", "8160")))

LEARNING_RATE = float(os.getenv("RL_LEARNING_RATE", "0.01"))
DISCOUNT_FACTOR = float(os.getenv("RL_DISCOUNT_FACTOR", "0.99"))
EPSILON = float(os.getenv("RL_EPSILON", "0.1"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 60 - ReinforcementLearning", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_start_time = datetime.now()


# ---------------------------------------------------------------------------
# In-memory Q-table and episode tracking
# ---------------------------------------------------------------------------

class RLAgent:
    def __init__(self):
        self.q_table: Dict[str, Dict[str, float]] = {}
        self.learning_rate = LEARNING_RATE
        self.discount_factor = DISCOUNT_FACTOR
        self.epsilon = EPSILON
        self.episodes_completed = 0
        self.total_steps = 0
        self.total_reward = 0.0
        self.episode_rewards: List[float] = []
        self.policy_weights: Dict[str, float] = {}

    def _state_key(self, state: Any) -> str:
        return str(state)

    def _ensure_state(self, state_key: str, actions: List[str]) -> None:
        if state_key not in self.q_table:
            self.q_table[state_key] = {a: 0.0 for a in actions}
        else:
            for a in actions:
                if a not in self.q_table[state_key]:
                    self.q_table[state_key][a] = 0.0

    def select_action(self, state: Any, actions: List[str], greedy: bool = False) -> str:
        state_key = self._state_key(state)
        self._ensure_state(state_key, actions)
        if not greedy and random.random() < self.epsilon:
            return random.choice(actions)
        q_vals = self.q_table[state_key]
        return max(q_vals, key=lambda a: q_vals[a])

    def update(self, state: Any, action: str, reward: float, next_state: Any,
               actions: List[str], done: bool) -> float:
        state_key = self._state_key(state)
        next_key = self._state_key(next_state)
        self._ensure_state(state_key, actions)
        self._ensure_state(next_key, actions)

        current_q = self.q_table[state_key].get(action, 0.0)
        if done:
            target = reward
        else:
            max_next_q = max(self.q_table[next_key].values(), default=0.0)
            target = reward + self.discount_factor * max_next_q

        td_error = target - current_q
        self.q_table[state_key][action] = current_q + self.learning_rate * td_error
        self.total_steps += 1
        self.total_reward += reward
        return td_error

    def reset_episode(self) -> None:
        self.episodes_completed += 1

    def get_policy(self) -> Dict[str, str]:
        policy = {}
        for state_key, actions in self.q_table.items():
            if actions:
                policy[state_key] = max(actions, key=lambda a: actions[a])
        return policy

    def get_stats(self) -> Dict[str, Any]:
        avg_reward = (
            sum(self.episode_rewards[-100:]) / len(self.episode_rewards[-100:])
            if self.episode_rewards else 0.0
        )
        return {
            "episodes_completed": self.episodes_completed,
            "total_steps": self.total_steps,
            "total_reward": round(self.total_reward, 4),
            "average_reward_last_100": round(avg_reward, 4),
            "q_table_states": len(self.q_table),
            "learning_rate": self.learning_rate,
            "discount_factor": self.discount_factor,
            "epsilon": self.epsilon,
        }


agent = RLAgent()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TrainRequest(BaseModel):
    state: Any
    action: str
    reward: float
    next_state: Any
    actions: List[str]
    done: bool = False


class PredictRequest(BaseModel):
    state: Any
    actions: List[str]
    greedy: bool = True


class EpisodeStep(BaseModel):
    state: Any
    action: str
    reward: float
    next_state: Any
    done: bool = False


class EpisodeRequest(BaseModel):
    actions: List[str]
    steps: List[EpisodeStep]


class ConfigRequest(BaseModel):
    learning_rate: Optional[float] = None
    discount_factor: Optional[float] = None
    epsilon: Optional[float] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "60",
        "name": "ReinforcementLearning",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    uptime = (datetime.now() - _start_time).total_seconds()
    return {
        "status": "running",
        "node_id": "60",
        "name": "ReinforcementLearning",
        "uptime_seconds": round(uptime, 2),
        "configuration": {
            "learning_rate": agent.learning_rate,
            "discount_factor": agent.discount_factor,
            "epsilon": agent.epsilon,
        },
        "metrics": agent.get_stats(),
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/train")
async def train(request: TrainRequest):
    """Perform one Q-learning update step."""
    td_error = agent.update(
        state=request.state,
        action=request.action,
        reward=request.reward,
        next_state=request.next_state,
        actions=request.actions,
        done=request.done,
    )
    state_key = agent._state_key(request.state)
    return {
        "success": True,
        "td_error": round(td_error, 6),
        "q_values": agent.q_table.get(state_key, {}),
        "total_steps": agent.total_steps,
    }


@app.post("/predict")
async def predict(request: PredictRequest):
    """Select an action for the given state."""
    action = agent.select_action(request.state, request.actions, greedy=request.greedy)
    state_key = agent._state_key(request.state)
    return {
        "success": True,
        "action": action,
        "q_values": agent.q_table.get(state_key, {}),
        "greedy": request.greedy,
    }


@app.post("/reset")
async def reset():
    """Reset the agent (clear Q-table and statistics)."""
    agent.q_table.clear()
    agent.policy_weights.clear()
    agent.episodes_completed = 0
    agent.total_steps = 0
    agent.total_reward = 0.0
    agent.episode_rewards.clear()
    return {"success": True, "message": "Agent reset successfully"}


@app.post("/episode")
async def run_episode(request: EpisodeRequest):
    """Process a complete episode of steps."""
    if not request.steps:
        raise HTTPException(status_code=400, detail="No steps provided")

    episode_reward = 0.0
    updates = []
    for step in request.steps:
        td_error = agent.update(
            state=step.state,
            action=step.action,
            reward=step.reward,
            next_state=step.next_state,
            actions=request.actions,
            done=step.done,
        )
        episode_reward += step.reward
        updates.append({"td_error": round(td_error, 6), "reward": step.reward})

    agent.episode_rewards.append(episode_reward)
    agent.reset_episode()

    return {
        "success": True,
        "episode_number": agent.episodes_completed,
        "episode_reward": round(episode_reward, 4),
        "steps": len(request.steps),
        "updates": updates,
    }


@app.get("/stats")
async def stats():
    """Return training statistics."""
    return {"success": True, "stats": agent.get_stats(), "policy": agent.get_policy()}


@app.post("/config")
async def configure(request: ConfigRequest):
    """Update agent hyperparameters."""
    if request.learning_rate is not None:
        agent.learning_rate = request.learning_rate
    if request.discount_factor is not None:
        agent.discount_factor = request.discount_factor
    if request.epsilon is not None:
        agent.epsilon = request.epsilon
    return {
        "success": True,
        "configuration": {
            "learning_rate": agent.learning_rate,
            "discount_factor": agent.discount_factor,
            "epsilon": agent.epsilon,
        },
    }


@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "train":
        return await train(TrainRequest(**params))
    elif tool == "predict":
        return await predict(PredictRequest(**params))
    elif tool == "reset":
        return await reset()
    elif tool == "episode":
        return await run_episode(EpisodeRequest(**params))
    elif tool == "stats":
        return await stats()
    elif tool == "config":
        return await configure(ConfigRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
