"""
UFO Galaxy - 孪生指挥官 (Twin Commander)
========================================

双 AI 指挥官独立分析同一任务 → 交叉验证 → 共识达成。
两个指挥官使用不同 LLM、不同视角，通过辩论/投票/合并达成最终决策。

注意：这与 enhancements/agent_factory/twin_model.py 完全不同。
TwinModel 是被动镜像/快照系统；TwinCommander 是主动双决策系统。
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UFO-Galaxy.TwinCommander")


# ───────────────────── 数据模型 ─────────────────────

class ConsensusStrategy(Enum):
    """共识策略"""
    DEBATE = "debate"                    # 辩论直到达成一致
    VOTE = "vote"                        # 投票，多数获胜
    DEFER_TO_CONFIDENCE = "defer"        # 信心高者胜出
    MERGE = "merge"                      # 合并双方方案


@dataclass
class CommanderConfig:
    """指挥官配置"""
    commander_id: str
    provider: str
    model: str
    perspective: str                     # 视角：analytical / creative / risk-averse / bold
    system_prompt_suffix: str = ""

    def to_dict(self) -> Dict:
        return {
            "commander_id": self.commander_id,
            "provider": self.provider,
            "model": self.model,
            "perspective": self.perspective,
        }


@dataclass
class CommanderAnalysis:
    """指挥官分析结果"""
    commander_id: str
    provider: str
    model: str
    plan: Dict = field(default_factory=dict)
    confidence: float = 0.5
    risks: List[str] = field(default_factory=list)
    reasoning: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "commander_id": self.commander_id,
            "provider": self.provider,
            "model": self.model,
            "confidence": self.confidence,
            "risks": self.risks,
            "reasoning": self.reasoning[:200],
        }


@dataclass
class TwinCommanderResult:
    """孪生指挥官结果"""
    task_id: str
    commander_a_analysis: Optional[CommanderAnalysis] = None
    commander_b_analysis: Optional[CommanderAnalysis] = None
    consensus: Dict = field(default_factory=dict)
    consensus_strategy_used: ConsensusStrategy = ConsensusStrategy.DEBATE
    debate_rounds: int = 0
    total_latency_ms: float = 0.0
    agreement_score: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "commander_a": self.commander_a_analysis.to_dict() if self.commander_a_analysis else None,
            "commander_b": self.commander_b_analysis.to_dict() if self.commander_b_analysis else None,
            "consensus_strategy": self.consensus_strategy_used.value,
            "debate_rounds": self.debate_rounds,
            "agreement_score": self.agreement_score,
            "total_latency_ms": self.total_latency_ms,
        }


# ───────────────────── 默认指挥官配置 ─────────────────────

DEFAULT_COMMANDER_A = CommanderConfig(
    commander_id="commander_alpha",
    provider="anthropic",
    model="claude-sonnet-4-5-20250929",
    perspective="analytical",
    system_prompt_suffix="注重逻辑正确性、风险评估和系统化方法。追求严谨和可靠。",
)

DEFAULT_COMMANDER_B = CommanderConfig(
    commander_id="commander_beta",
    provider="openai",
    model="gpt-4o",
    perspective="creative",
    system_prompt_suffix="注重创新方案、执行效率和用户体验。追求突破和优雅。",
)


# ───────────────────── TwinCommander ─────────────────────

class TwinCommander:
    """
    孪生指挥官 — 两个 AI 独立分析、交叉验证、共识决策。

    工作流程:
    1. 双方并行分析任务（不同 LLM、不同视角）
    2. 交叉验证：各自审查对方方案
    3. 共识解决：根据策略达成最终决策
    """

    def __init__(self, llm_router=None, agent_factory=None,
                 commander_a_config: Optional[CommanderConfig] = None,
                 commander_b_config: Optional[CommanderConfig] = None,
                 consensus_strategy: ConsensusStrategy = ConsensusStrategy.DEBATE,
                 max_debate_rounds: int = 3):
        self.llm_router = llm_router
        self.agent_factory = agent_factory
        self.commander_a = commander_a_config or DEFAULT_COMMANDER_A
        self.commander_b = commander_b_config or DEFAULT_COMMANDER_B
        self.consensus_strategy = consensus_strategy
        self.max_debate_rounds = max_debate_rounds
        logger.info(
            f"TwinCommander 已初始化: "
            f"A={self.commander_a.provider}/{self.commander_a.perspective}, "
            f"B={self.commander_b.provider}/{self.commander_b.perspective}, "
            f"strategy={consensus_strategy.value}"
        )

    async def analyze(self, task_description: str,
                      context: Optional[Dict] = None) -> TwinCommanderResult:
        """
        双指挥官分析主入口。

        1. 双方并行分析
        2. 交叉验证
        3. 共识达成
        """
        task_id = f"twin_{uuid.uuid4().hex[:8]}"
        start = time.time()
        context = context or {}

        logger.info(f"[{task_id}] 孪生指挥官启动分析")

        # 1. 并行分析
        analysis_a, analysis_b = await asyncio.gather(
            self._commander_analyze(self.commander_a, task_description, context),
            self._commander_analyze(self.commander_b, task_description, context),
        )

        logger.info(
            f"[{task_id}] 双方分析完成: "
            f"A(confidence={analysis_a.confidence:.2f}), "
            f"B(confidence={analysis_b.confidence:.2f})"
        )

        # 2. 交叉验证
        cross_val_a, cross_val_b = await asyncio.gather(
            self._cross_validate(self.commander_a, analysis_a, analysis_b),
            self._cross_validate(self.commander_b, analysis_b, analysis_a),
        )

        # 3. 共识
        consensus, rounds, agreement = await self._resolve_consensus(
            analysis_a, analysis_b, cross_val_a, cross_val_b,
            task_description, context,
        )

        result = TwinCommanderResult(
            task_id=task_id,
            commander_a_analysis=analysis_a,
            commander_b_analysis=analysis_b,
            consensus=consensus,
            consensus_strategy_used=self.consensus_strategy,
            debate_rounds=rounds,
            total_latency_ms=(time.time() - start) * 1000,
            agreement_score=agreement,
        )

        logger.info(
            f"[{task_id}] 共识达成: strategy={self.consensus_strategy.value}, "
            f"rounds={rounds}, agreement={agreement:.2f}"
        )
        return result

    async def decide_and_dispatch(self, task_description: str,
                                  context: Optional[Dict] = None) -> Dict:
        """
        高层决策 — 分析后按共识计划分派执行。

        可将任务分派给 AgentSwarm 或 SpecialForcesTeam。
        """
        result = await self.analyze(task_description, context)

        dispatch_info = {
            "task_id": result.task_id,
            "consensus": result.consensus,
            "agreement_score": result.agreement_score,
            "recommended_execution": result.consensus.get("execution_strategy", "direct"),
        }

        logger.info(
            f"[{result.task_id}] 决策完成，推荐执行方式: "
            f"{dispatch_info['recommended_execution']}"
        )
        return dispatch_info

    # ─────── 核心分析 ───────

    async def _commander_analyze(self, config: CommanderConfig,
                                 task: str, context: Dict) -> CommanderAnalysis:
        """单个指挥官分析任务"""
        start = time.time()

        if not self.llm_router:
            return CommanderAnalysis(
                commander_id=config.commander_id,
                provider=config.provider,
                model=config.model,
                plan={"approach": f"[{config.perspective}] 规则分析: {task[:100]}"},
                confidence=0.5,
                risks=["LLM 不可用，降级执行"],
                reasoning=f"以 {config.perspective} 视角进行规则分析",
                latency_ms=0,
            )

        system_prompt = (
            f"你是一位 {config.perspective} 视角的战略指挥官。\n"
            f"{config.system_prompt_suffix}\n\n"
            "独立分析给定任务，提出你的方案。\n"
            "返回 JSON:\n"
            "{\n"
            '  "plan": {"approach": "方法", "steps": ["步骤1", ...], '
            '"execution_strategy": "direct|swarm|team"},\n'
            '  "confidence": 0.0-1.0,\n'
            '  "risks": ["风险1", ...],\n'
            '  "reasoning": "推理过程"\n'
            "}"
        )

        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps({
                        "task": task,
                        "context": context,
                    }, ensure_ascii=False)},
                ],
                provider=config.provider,
                model=config.model,
                task_type="planning",
            )

            return CommanderAnalysis(
                commander_id=config.commander_id,
                provider=config.provider,
                model=config.model,
                plan=result.get("plan", {}),
                confidence=float(result.get("confidence", 0.5)),
                risks=result.get("risks", []),
                reasoning=result.get("reasoning", ""),
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            logger.warning(f"指挥官 {config.commander_id} 分析失败: {e}")
            return CommanderAnalysis(
                commander_id=config.commander_id,
                provider=config.provider,
                model=config.model,
                plan={"approach": f"分析失败: {e}"},
                confidence=0.1,
                risks=[str(e)],
                reasoning=f"分析过程出错: {e}",
                latency_ms=(time.time() - start) * 1000,
            )

    async def _cross_validate(self, reviewer_config: CommanderConfig,
                              own_analysis: CommanderAnalysis,
                              other_analysis: CommanderAnalysis) -> Dict:
        """交叉验证 — 一方审查另一方的方案"""
        if not self.llm_router:
            return {"agreement": 0.5, "objections": [], "suggestions": []}

        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": (
                        f"你是 {reviewer_config.perspective} 视角的评审者。\n"
                        "审查对方指挥官的方案，评估其优缺点。\n"
                        "返回 JSON:\n"
                        "{\n"
                        '  "agreement": 0.0-1.0,\n'
                        '  "objections": ["反对意见1", ...],\n'
                        '  "suggestions": ["改进建议1", ...],\n'
                        '  "strengths": ["优点1", ...]\n'
                        "}"
                    )},
                    {"role": "user", "content": json.dumps({
                        "my_plan": own_analysis.plan,
                        "my_confidence": own_analysis.confidence,
                        "other_plan": other_analysis.plan,
                        "other_confidence": other_analysis.confidence,
                        "other_reasoning": other_analysis.reasoning,
                    }, ensure_ascii=False)},
                ],
                provider=reviewer_config.provider,
                model=reviewer_config.model,
                task_type="analysis",
            )
            return {
                "agreement": float(result.get("agreement", 0.5)),
                "objections": result.get("objections", []),
                "suggestions": result.get("suggestions", []),
                "strengths": result.get("strengths", []),
            }
        except Exception as e:
            logger.warning(f"交叉验证失败: {e}")
            return {"agreement": 0.5, "objections": [], "suggestions": []}

    # ─────── 共识解决 ───────

    async def _resolve_consensus(
        self,
        analysis_a: CommanderAnalysis,
        analysis_b: CommanderAnalysis,
        cross_val_a: Dict,
        cross_val_b: Dict,
        task_description: str,
        context: Dict,
    ) -> tuple:
        """根据策略解决共识，返回 (consensus, rounds, agreement_score)"""

        avg_agreement = (cross_val_a.get("agreement", 0.5) + cross_val_b.get("agreement", 0.5)) / 2

        if self.consensus_strategy == ConsensusStrategy.DEBATE:
            return await self._resolve_debate(
                analysis_a, analysis_b, cross_val_a, cross_val_b,
                task_description, avg_agreement,
            )
        elif self.consensus_strategy == ConsensusStrategy.VOTE:
            return self._resolve_vote(analysis_a, analysis_b, cross_val_a, cross_val_b)
        elif self.consensus_strategy == ConsensusStrategy.DEFER_TO_CONFIDENCE:
            return self._resolve_defer(analysis_a, analysis_b, avg_agreement)
        else:  # MERGE
            return await self._resolve_merge(
                analysis_a, analysis_b, task_description, avg_agreement
            )

    async def _resolve_debate(self, analysis_a, analysis_b,
                              cross_val_a, cross_val_b,
                              task_description, agreement):
        """辩论模式 — 多轮交互直到达成一致"""
        rounds = 0

        if agreement >= 0.7:
            # 已经足够一致，选信心高的
            winner = analysis_a if analysis_a.confidence >= analysis_b.confidence else analysis_b
            return winner.plan, 0, agreement

        # 辩论循环
        current_a = analysis_a
        current_b = analysis_b
        current_agreement = agreement

        for round_num in range(self.max_debate_rounds):
            rounds = round_num + 1
            logger.info(f"辩论第 {rounds} 轮, agreement={current_agreement:.2f}")

            if current_agreement >= 0.7:
                break

            if not self.llm_router:
                break

            # A 根据 B 的反对意见修订
            revised_a = await self._revise_plan(
                self.commander_a, current_a,
                cross_val_b.get("objections", []),
                cross_val_b.get("suggestions", []),
            )

            # B 根据 A 的反对意见修订
            revised_b = await self._revise_plan(
                self.commander_b, current_b,
                cross_val_a.get("objections", []),
                cross_val_a.get("suggestions", []),
            )

            # 重新交叉验证
            cross_val_a, cross_val_b = await asyncio.gather(
                self._cross_validate(self.commander_a, revised_a, revised_b),
                self._cross_validate(self.commander_b, revised_b, revised_a),
            )

            current_a = revised_a
            current_b = revised_b
            current_agreement = (
                cross_val_a.get("agreement", 0.5) + cross_val_b.get("agreement", 0.5)
            ) / 2

        # 辩论结束，选信心高的
        winner = current_a if current_a.confidence >= current_b.confidence else current_b
        return winner.plan, rounds, current_agreement

    def _resolve_vote(self, analysis_a, analysis_b, cross_val_a, cross_val_b):
        """投票模式 — 交叉验证得分高者获胜"""
        score_a = cross_val_b.get("agreement", 0.5)  # B 对 A 的认可
        score_b = cross_val_a.get("agreement", 0.5)  # A 对 B 的认可
        agreement = (score_a + score_b) / 2

        winner = analysis_a if score_a >= score_b else analysis_b
        return winner.plan, 0, agreement

    def _resolve_defer(self, analysis_a, analysis_b, agreement):
        """信心优先 — 自信度高者获胜"""
        winner = analysis_a if analysis_a.confidence >= analysis_b.confidence else analysis_b
        return winner.plan, 0, agreement

    async def _resolve_merge(self, analysis_a, analysis_b, task_description, agreement):
        """合并模式 — 第三方 LLM 合并双方方案"""
        if not self.llm_router:
            # 降级：简单合并
            merged = {
                "approach": "merged",
                "plan_a": analysis_a.plan,
                "plan_b": analysis_b.plan,
            }
            return merged, 0, agreement

        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": (
                        "两位指挥官各自提出了方案。请合并双方的优点，"
                        "形成一个综合的最终方案。\n"
                        "返回 JSON: {\"plan\": {\"approach\": ..., \"steps\": [...], "
                        "\"execution_strategy\": \"direct|swarm|team\"}, "
                        "\"merge_reasoning\": \"合并理由\"}"
                    )},
                    {"role": "user", "content": json.dumps({
                        "task": task_description,
                        "plan_a": {
                            "perspective": self.commander_a.perspective,
                            "plan": analysis_a.plan,
                            "confidence": analysis_a.confidence,
                            "reasoning": analysis_a.reasoning,
                        },
                        "plan_b": {
                            "perspective": self.commander_b.perspective,
                            "plan": analysis_b.plan,
                            "confidence": analysis_b.confidence,
                            "reasoning": analysis_b.reasoning,
                        },
                    }, ensure_ascii=False)},
                ],
                task_type="planning",
            )
            return result.get("plan", result), 0, agreement
        except Exception as e:
            logger.warning(f"合并失败: {e}")
            winner = analysis_a if analysis_a.confidence >= analysis_b.confidence else analysis_b
            return winner.plan, 0, agreement

    async def _revise_plan(self, config: CommanderConfig,
                           analysis: CommanderAnalysis,
                           objections: List[str],
                           suggestions: List[str]) -> CommanderAnalysis:
        """指挥官根据对方反馈修订方案"""
        if not self.llm_router or (not objections and not suggestions):
            return analysis

        try:
            result = await self.llm_router.chat_json(
                messages=[
                    {"role": "system", "content": (
                        f"你是 {config.perspective} 视角的指挥官。\n"
                        "根据对方的反对意见和建议修订你的方案。\n"
                        "返回 JSON: {\"plan\": {...}, \"confidence\": 0.0-1.0, "
                        "\"risks\": [...], \"reasoning\": \"修订理由\"}"
                    )},
                    {"role": "user", "content": json.dumps({
                        "my_current_plan": analysis.plan,
                        "objections_from_other": objections,
                        "suggestions_from_other": suggestions,
                    }, ensure_ascii=False)},
                ],
                provider=config.provider,
                model=config.model,
                task_type="planning",
            )

            return CommanderAnalysis(
                commander_id=config.commander_id,
                provider=config.provider,
                model=config.model,
                plan=result.get("plan", analysis.plan),
                confidence=float(result.get("confidence", analysis.confidence)),
                risks=result.get("risks", analysis.risks),
                reasoning=result.get("reasoning", ""),
                latency_ms=analysis.latency_ms,
            )
        except Exception as e:
            logger.warning(f"方案修订失败: {e}")
            return analysis

    def get_status(self) -> Dict:
        return {
            "commander_a": self.commander_a.to_dict(),
            "commander_b": self.commander_b.to_dict(),
            "consensus_strategy": self.consensus_strategy.value,
            "max_debate_rounds": self.max_debate_rounds,
        }


# ───────────────────── 单例 ─────────────────────

_commander_instance: Optional[TwinCommander] = None


def get_twin_commander(llm_router=None, agent_factory=None,
                       commander_a: Optional[CommanderConfig] = None,
                       commander_b: Optional[CommanderConfig] = None,
                       consensus_strategy: ConsensusStrategy = ConsensusStrategy.DEBATE,
                       ) -> TwinCommander:
    global _commander_instance
    if _commander_instance is None:
        _commander_instance = TwinCommander(
            llm_router=llm_router,
            agent_factory=agent_factory,
            commander_a_config=commander_a,
            commander_b_config=commander_b,
            consensus_strategy=consensus_strategy,
        )
    return _commander_instance
