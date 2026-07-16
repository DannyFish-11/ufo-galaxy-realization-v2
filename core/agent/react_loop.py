"""
core/agent/react_loop.py
========================
Unified ReAct tool invocation loop (native function-calling style).

Background: Previously the ReAct loop was written three times with inconsistent
parameters:
  - ``core/agent_factory.py``        single Agent, max 8
  - ``core/agent_team.py``           team member, max 6
  - ``core/local_agent_runtime.py``  Manifest local, max 10 (different schema/paradigm)

The first two are isomorphic OpenAI-style tool-calling loops; this module extracts
their loop body into ``run_react_tool_loop()``: the caller provides callbacks for
"how to call LLM", "how to dispatch tools", "how to record tool results", and
"(optional) how to reflect"; the loop handles iteration, message assembly,
loop detection, reflection feedback, and termination.

All limits/budgets/reflection/loop detection are centralized in :class:`ReactConfig`,
overridable via environment variables.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Final, List, Optional

logger = logging.getLogger("Galaxy.Agent.ReactLoop")

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------

# Environment variable names for configuration override
ENV_SINGLE_AGENT_MAX_ITERATIONS: Final[str] = "GALAXY_AGENT_MAX_ITERATIONS"
ENV_TEAM_MAX_ITERATIONS: Final[str] = "GALAXY_TEAM_MAX_ITERATIONS"
ENV_MANIFEST_MAX_TURNS: Final[str] = "GALAXY_MANIFEST_MAX_TURNS"
ENV_AGENT_REFLECTION: Final[str] = "GALAXY_AGENT_REFLECTION"
ENV_AGENT_MAX_REFLECTION: Final[str] = "GALAXY_AGENT_MAX_REFLECTION"
ENV_AGENT_LOOP_WINDOW: Final[str] = "GALAXY_AGENT_LOOP_WINDOW"

# Default configuration values
DEFAULT_SINGLE_AGENT_MAX_ITERATIONS: Final[int] = 8
DEFAULT_TEAM_MEMBER_MAX_ITERATIONS: Final[int] = 6
DEFAULT_MANIFEST_MAX_TURNS: Final[int] = 10
DEFAULT_REFLECTION_ENABLED: Final[bool] = True
DEFAULT_MAX_REFLECTION_ROUNDS: Final[int] = 1
DEFAULT_LOOP_DETECTION_WINDOW: Final[int] = 2

# Tool call result truncation limit (characters)
_TOOL_RESULT_MAX_LENGTH: Final[int] = 4000


# ------------------------------------------------------------------------------
# Environment variable helpers
# ------------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    """Read an integer from environment variable.

    Args:
        name: Environment variable name.
        default: Default value if not set or invalid.

    Returns:
        Integer value from environment or default.
    """
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (ValueError, TypeError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean from environment variable.

    Args:
        name: Environment variable name.
        default: Default value if not set.

    Returns:
        Boolean value from environment or default.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


# ------------------------------------------------------------------------------
# Configuration dataclass
# ------------------------------------------------------------------------------


@dataclass
class ReactConfig:
    """Centralized configuration for the ReAct loop.

    All limits/budgets/reflection/loop detection are concentrated here
    and can be overridden via environment variables.

    Attributes:
        single_agent_max_iterations: Max iterations for single agent mode.
        team_member_max_iterations: Max iterations for team member mode.
        manifest_max_turns: Max turns for manifest mode.
        reflection_enabled: Whether reflection self-check is enabled.
        max_reflection_rounds: Max reflection rounds (consumes iteration budget).
        loop_detection_window: Number of repeated tool-call signatures to trigger
                               early termination (0 disables loop detection).
    """

    # Iteration limits for each context (replaces scattered 8 / 6 / 10 magic numbers)
    single_agent_max_iterations: int = DEFAULT_SINGLE_AGENT_MAX_ITERATIONS
    team_member_max_iterations: int = DEFAULT_TEAM_MEMBER_MAX_ITERATIONS
    manifest_max_turns: int = DEFAULT_MANIFEST_MAX_TURNS

    # Reflection self-check (Reflexion-style)
    reflection_enabled: bool = DEFAULT_REFLECTION_ENABLED
    max_reflection_rounds: int = DEFAULT_MAX_REFLECTION_ROUNDS

    # Loop detection: consecutive repeated tool-call signatures reaching this count
    # triggers early termination (0 means disabled).
    # Prevents model from spinning on same tool/parameters and exhausting budget.
    loop_detection_window: int = DEFAULT_LOOP_DETECTION_WINDOW

    @classmethod
    def from_env(cls) -> "ReactConfig":
        """Create ReactConfig from environment variables.

        Returns:
            ReactConfig instance with values from environment variables
            or defaults where not set.
        """
        return cls(
            single_agent_max_iterations=_env_int(
                ENV_SINGLE_AGENT_MAX_ITERATIONS, DEFAULT_SINGLE_AGENT_MAX_ITERATIONS
            ),
            team_member_max_iterations=_env_int(
                ENV_TEAM_MAX_ITERATIONS, DEFAULT_TEAM_MEMBER_MAX_ITERATIONS
            ),
            manifest_max_turns=_env_int(
                ENV_MANIFEST_MAX_TURNS, DEFAULT_MANIFEST_MAX_TURNS
            ),
            reflection_enabled=_env_bool(
                ENV_AGENT_REFLECTION, DEFAULT_REFLECTION_ENABLED
            ),
            max_reflection_rounds=_env_int(
                ENV_AGENT_MAX_REFLECTION, DEFAULT_MAX_REFLECTION_ROUNDS
            ),
            loop_detection_window=_env_int(
                ENV_AGENT_LOOP_WINDOW, DEFAULT_LOOP_DETECTION_WINDOW
            ),
        )


# ------------------------------------------------------------------------------
# Loop detection helpers
# ------------------------------------------------------------------------------


def tool_call_signature(tool_calls: List[Dict[str, Any]]) -> str:
    """Generate a stable signature for a round of tool_calls, for loop detection.

    Uses tool name + raw parameter string (OpenAI-style ``function.name`` /
    ``function.arguments``).

    Args:
        tool_calls: List of tool call dictionaries.

    Returns:
        Pipe-separated signature string.
    """
    parts: List[str] = []
    for tc in tool_calls or []:
        func = tc.get("function", {}) if isinstance(tc, dict) else {}
        parts.append(f"{func.get('name', '')}:{func.get('arguments', '')}")
    return "|".join(parts)


def is_repeating(history: List[str], window: int) -> bool:
    """Check if the most recent ``window`` tool-call signatures are all identical (and non-empty).

    Args:
        history: List of tool-call signature strings.
        window: Window size to check for repetition.

    Returns:
        True if the last ``window`` entries are identical and non-empty.
    """
    if window <= 0 or len(history) < window:
        return False
    recent = history[-window:]
    return all(s and s == recent[0] for s in recent)


# ------------------------------------------------------------------------------
# Result dataclass
# ------------------------------------------------------------------------------


@dataclass
class ToolLoopResult:
    """Result of a ReAct tool loop execution.

    Attributes:
        final_response: The last LLM response object (caller extracts content/provider).
        iterations: Actual number of LLM call rounds.
        reflection_rounds: Number of reflection-triggered rounds.
        stop_reason: Reason for loop termination -- "final" | "max_iterations" | "loop_detected".
    """

    final_response: Any  # Last LLM response object
    iterations: int  # Actual LLM call rounds
    reflection_rounds: int  # Reflection-triggered rounds
    stop_reason: str  # "final" | "max_iterations" | "loop_detected"


# ------------------------------------------------------------------------------
# Main ReAct loop
# ------------------------------------------------------------------------------


async def run_react_tool_loop(
    *,
    messages: List[Dict[str, Any]],
    llm_call: Callable[[List[Dict[str, Any]]], Awaitable[Any]],
    dispatch_tool: Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]],
    max_iterations: int,
    on_tool_result: Optional[
        Callable[[str, Dict[str, Any], Dict[str, Any], int], None]
    ] = None,
    reflect: Optional[
        Callable[[str], Awaitable[Optional[Dict[str, Any]]]]
    ] = None,
    max_reflection_rounds: int = 0,
    loop_detection_window: int = DEFAULT_LOOP_DETECTION_WINDOW,
) -> ToolLoopResult:
    """Unified native function-calling ReAct loop (for isomorphic callers to reuse).

    Iteratively calls LLM, dispatches tool calls, and manages the conversation
    loop until a final answer is reached or limits are exceeded.

    Args:
        messages: Conversation message list (assistant/tool rounds appended in-place).
        llm_call: ``async (messages) -> resp``; caller handles tools/provider/
            model/circuit breaker/token counting differences in closure.
            resp must have ``.tool_calls`` and ``.content``.
        dispatch_tool: ``async (name, args) -> dict``; caller handles single-tool
            timeout differences in closure; returns ``{"success","result"/"error",...}``.
        max_iterations: Maximum number of LLM call iterations.
        on_tool_result: Optional side-effect callback for recording ToolCallRecord /
            accumulating tokens, etc.
        reflect: Optional reflection callback ``async (final_content) -> {"sufficient","critique"} | None``;
            returning None means pass (reflection never blocks delivery).
        max_reflection_rounds: Max reflection trigger rounds (consumes same max_iterations budget).
        loop_detection_window: Consecutive identical tool-call signatures reaching this count
                               terminates early (0 disables).

    Returns:
        ToolLoopResult with final response, iteration count, reflection rounds, and stop reason.
    """
    resp: Any = None
    iteration: int = 0
    reflection_rounds: int = 0
    sig_history: List[str] = []

    while iteration < max_iterations:
        resp = await llm_call(messages)
        iteration += 1

        tool_calls = getattr(resp, "tool_calls", None)
        if not tool_calls:
            # Candidate final answer -- reflection self-check (bounded; any None/exception passes)
            if (
                reflect is not None
                and reflection_rounds < max_reflection_rounds
                and iteration < max_iterations
            ):
                content = getattr(resp, "content", "") or ""
                try:
                    verdict = await reflect(content)
                except asyncio.CancelledError:
                    raise  # Always propagate cancellation
                except Exception as exc:  # noqa: BLE001 -- reflection failure must pass
                    logger.debug("Reflect callback failed (released): %s", exc)
                    verdict = None
                if verdict and not verdict.get("sufficient", True):
                    reflection_rounds += 1
                    critique = (
                        verdict.get("critique", "")
                        or "Result may be incomplete; please supplement and verify before giving final answer."
                    )
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": f"[Self-check] The above answer has shortcomings: {critique}\nPlease correct or supplement accordingly, then give the final result.",
                        }
                    )
                    continue
            return ToolLoopResult(resp, iteration, reflection_rounds, "final")

        # Loop detection: model spinning on same tool+parameters -> early termination
        sig_history.append(tool_call_signature(tool_calls))
        if is_repeating(sig_history, loop_detection_window):
            logger.info(
                "ReAct loop-detection triggered (window=%d) -- stopping early at iter=%d",
                loop_detection_window,
                iteration,
            )
            return ToolLoopResult(resp, iteration, reflection_rounds, "loop_detected")

        # Assemble assistant(tool_calls) round
        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": resp.content or "",
        }
        assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # Execute tools one by one
        for tc in tool_calls:
            tc_func = tc.get("function", {})
            tc_name = tc_func.get("name", "")
            tc_id = tc.get("id", f"call_{tc_name}")
            import json as _json

            try:
                tc_args = _json.loads(tc_func.get("arguments", "{}"))
            except (ValueError, TypeError):
                tc_args = {}

            result = await dispatch_tool(tc_name, tc_args)
            if on_tool_result is not None:
                try:
                    on_tool_result(tc_name, tc_args, result, iteration - 1)
                except Exception as exc:  # noqa: BLE001 -- recording side-effect should not interrupt loop
                    logger.debug("on_tool_result hook failed: %s", exc)

            result_str = str(result.get("result", result.get("error", "")))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_str[:_TOOL_RESULT_MAX_LENGTH],
                }
            )

    return ToolLoopResult(resp, iteration, reflection_rounds, "max_iterations")
