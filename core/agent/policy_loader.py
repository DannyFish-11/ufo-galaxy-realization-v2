"""
Galaxy - Agent Policy Loader
==============================

从 core/agent/policies/ 目录加载三份策略文件:

  SOUL.md   — 人格/边界/口吻（仅注入 Agent 执行链路，纯聊天不注入）
  AGENTS.md — Agent 工作规范（执行链路注入）
  USER.md   — 用户偏好模板（chat 与 task 均可注入）

PolicySet 封装已加载的三份内容，提供便捷的构建方法:
  policy_set.build_soul_system_prompt()  — SOUL + AGENTS 合并系统提示（执行用）
  policy_set.build_chat_system_prompt()  — USER 注入的聊天系统提示（纯聊天用）

注意：
  - SOUL 内容永远不出现在 chat_only 的系统提示中
  - 文件不存在时使用内置默认值，确保系统不因文件缺失而崩溃
  - 支持运行时 reload()，热更新无需重启服务
"""

import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Galaxy.Agent.PolicyLoader")

# 策略文件所在目录（相对本文件的固定路径）
_POLICIES_DIR = Path(__file__).parent / "policies"

# ============================================================================
# 默认内置策略（文件不存在时兜底，确保系统可运行）
# ============================================================================

_DEFAULT_SOUL = """\
# SOUL — Galaxy 智能体人格核心

你是 Galaxy，一个 L4 级自主性 AI 系统。

## 核心人格
- 精准、务实、高效
- 面对复杂任务时逐步拆解，每步可验证
- 主动说明执行计划，不隐瞒操作意图
- 发现问题时主动报告，不掩盖错误

## 能力边界
- 只执行经明确授权或用户明确请求的操作
- 设备操控、文件修改等不可逆操作前确认意图
- 不执行可能损害用户数据或设备安全的命令

## 输出风格
- 执行结果以结构化格式呈现
- 使用步骤编号说明执行过程
- 失败时给出原因分析和建议的修复方向
"""

_DEFAULT_AGENTS = """\
# AGENTS — Galaxy 工作规范

## 任务执行标准
1. 任务接收后先输出执行计划，再逐步执行
2. 每个执行步骤记录到 agent_steps，包含输入/输出/状态
3. 工具调用必须通过 capability_registry，不允许硬编码绕过
4. 遇到不确定情况时停止执行并询问用户，不猜测继续

## 工具使用规则
- 优先使用已注册的 MCP/Skill 工具，不重复实现已有能力
- 调用工具前检查参数完整性
- 工具调用失败时重试最多 2 次，仍失败则上报错误

## 质量标准
- 最终回复必须包含 task_result（成功/失败及原因）
- 长任务提供进度百分比估算
- 不允许空结果或"已完成"等无信息回复

## 协作规范
- 多 Agent 场景中每个 Agent 只负责分配给自己的子任务
- 子任务完成后更新 agent_steps 状态
- 主 Agent 汇总所有子任务结果后再回复用户
"""

_DEFAULT_USER = """\
# USER — 用户偏好配置

## 语言偏好
- 主要语言: 中文
- 技术术语可使用英文

## 回复风格
- 简洁直接，避免冗余解释
- 技术内容使用代码块格式
- 重要信息加粗标注

## 交互习惯
- 倾向于分步骤说明
- 喜欢看到操作进度
- 对错误原因有详细说明的需求

## 权限偏好
- 允许自动执行常规文件操作
- 设备操控需要确认
- 网络请求需要说明目的
"""


# ============================================================================
# PolicySet
# ============================================================================

class PolicySet:
    """
    已加载的策略集合。

    Attributes:
        soul_content   — SOUL.md 内容（字符串）
        agents_content — AGENTS.md 内容（字符串）
        user_content   — USER.md 内容（字符串）
        loaded_at      — 加载时间戳
    """

    def __init__(
        self,
        soul_content: str,
        agents_content: str,
        user_content: str,
        loaded_at: Optional[float] = None,
    ):
        self.soul_content = soul_content
        self.agents_content = agents_content
        self.user_content = user_content
        self.loaded_at = loaded_at or time.time()

    # ------------------------------------------------------------------
    # 系统提示构建
    # ------------------------------------------------------------------

    def build_soul_system_prompt(self) -> str:
        """
        构建 Agent 执行链路使用的系统提示。

        包含 SOUL + AGENTS + USER，适用于 task_execute 和 hybrid 模式。
        SOUL 在此方法中注入，chat_only 模式永远不调用此方法。
        """
        parts = []
        if self.soul_content.strip():
            parts.append(self.soul_content.strip())
        if self.agents_content.strip():
            parts.append(self.agents_content.strip())
        if self.user_content.strip():
            parts.append(self.user_content.strip())
        return "\n\n---\n\n".join(parts)

    def build_chat_system_prompt(self) -> str:
        """
        构建纯聊天使用的系统提示。

        仅包含 USER 偏好，**不包含 SOUL**。
        保持自然对话体验，不暴露 Agent 执行人格。
        """
        base = (
            "你是 Galaxy 智能助手。\n"
            "如果用户需要执行具体操作，告知他们描述指令即可，系统会自动调度执行。\n"
        )
        if self.user_content.strip():
            return base + "\n\n---\n\n" + self.user_content.strip()
        return base

    def to_dict(self) -> dict:
        return {
            "soul_loaded": bool(self.soul_content.strip()),
            "agents_loaded": bool(self.agents_content.strip()),
            "user_loaded": bool(self.user_content.strip()),
            "loaded_at": self.loaded_at,
        }


# ============================================================================
# PolicyLoader
# ============================================================================

class PolicyLoader:
    """
    策略加载器。

    单例使用，支持 reload() 热更新。
    """

    def __init__(self, policies_dir: Optional[Path] = None):
        self._dir = policies_dir or _POLICIES_DIR
        self._policy_set: Optional[PolicySet] = None
        logger.info("PolicyLoader 初始化，策略目录: %s", self._dir)

    def load(self) -> PolicySet:
        """
        从策略目录加载所有策略文件。

        文件不存在时使用内置默认值，确保系统可运行。

        Returns:
            PolicySet 实例
        """
        soul = self._read_file("SOUL.md", _DEFAULT_SOUL)
        agents = self._read_file("AGENTS.md", _DEFAULT_AGENTS)
        user = self._read_file("USER.md", _DEFAULT_USER)

        self._policy_set = PolicySet(
            soul_content=soul,
            agents_content=agents,
            user_content=user,
        )
        logger.info(
            "PolicyLoader: 策略加载完成 (soul=%d chars, agents=%d chars, user=%d chars)",
            len(soul),
            len(agents),
            len(user),
        )
        return self._policy_set

    def reload(self) -> PolicySet:
        """热更新策略文件，无需重启服务"""
        logger.info("PolicyLoader: 热更新策略文件")
        return self.load()

    def get(self) -> PolicySet:
        """
        获取当前策略集（懒加载，首次调用时自动读取文件）

        Returns:
            PolicySet 实例
        """
        if self._policy_set is None:
            return self.load()
        return self._policy_set

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _read_file(self, filename: str, default: str) -> str:
        """读取策略文件，不存在时返回 default"""
        path = self._dir / filename
        if not path.exists():
            logger.debug("策略文件 %s 不存在，使用内置默认值", path)
            return default
        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                logger.warning("策略文件 %s 为空，使用内置默认值", path)
                return default
            logger.debug("策略文件 %s 已加载 (%d chars)", path, len(content))
            return content
        except Exception as e:
            logger.error("读取策略文件 %s 失败: %s，使用内置默认值", path, e)
            return default


# ============================================================================
# 模块级单例
# ============================================================================

_policy_loader_instance: Optional[PolicyLoader] = None


def get_policy_loader() -> PolicyLoader:
    """获取 PolicyLoader 全局单例"""
    global _policy_loader_instance
    if _policy_loader_instance is None:
        _policy_loader_instance = PolicyLoader()
    return _policy_loader_instance
