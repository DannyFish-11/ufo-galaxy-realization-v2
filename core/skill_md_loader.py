"""
Galaxy - SKILL.md 格式加载器
================================

兼容 OpenClaw 的 SKILL.md 格式
支持简洁的 Markdown + YAML frontmatter 格式

SKILL.md 格式示例:
---
name: weather
description: "Get current weather"
version: "1.0.0"
tags: ["weather", "api"]
---

# Weather Skill

## When to Use
- "What's the weather?"

## Commands
curl "wttr.in/London?format=3"
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# RUF006: retain fire-and-forget create_task results so the event loop's weak
# reference can't let them be garbage-collected mid-execution.
_BACKGROUND_TASKS: set = set()

logger = logging.getLogger("Galaxy.SkillMD")

# 一条技能整体能跑多久。**这是总预算,不是每条命令的时限。**
#
# 定成 30 秒是为了它**小于**任何合理的调用方预算(判据 120 秒、请求超时、
# 界面上一次交互)。内层比外层小,超时才会以"结果"的形式回到调用方手里,
# 而不是把调用方一起拖死。要跑更久的技能,调用方自己把 budget_s 抬上去 ——
# 抬的人知道自己的预算有多大,这里不知道。
DEFAULT_EXECUTE_BUDGET_S = 30.0

# Strict allowlist of commands permitted in SKILL.md execution
ALLOWED_COMMANDS = frozenset(
    [
        "curl",
        "wget",
        "python",
        "python3",
        "node",
        "bash",
        "sh",
    ]
)


# 起子进程时让它自成一组。POSIX 用 start_new_session,Windows 用新进程组标志 ——
# 两边都是为了让下面那个 kill 能一次收掉整棵树。
if os.name == "nt":  # pragma: no cover - 只在 Windows 上取这一支
    _NEW_GROUP_KW: Dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
else:
    _NEW_GROUP_KW = {"start_new_session": True}


def _kill_process_tree(process: Any) -> None:
    """把超时的子进程**连同它的孩子**一起收掉。

    实测撞出来的两件事,都写在这儿,因为它们都不直观:

    1. **要收的是一棵树,不是一个进程。** ``sh -c 'sleep 999'`` 里,``sleep``
       是 ``sh`` 的孩子。只 kill 掉 ``sh``,``sleep`` 照样活着 —— CI 上 GitHub
       在清理阶段打出的 ``Terminate orphan process: (curl)`` 就是这个形状。
       所以起进程时让它自成一组,这里整组一起发信号。

    2. **收完要用 wait(),不能再 communicate()。** 活着的孙子**攥着 stdout 管道
       不放**,``communicate()`` 等的是管道 EOF,那个 EOF 永远不会来。实测:
       kill 之后再 ``communicate()`` 卡满 4 秒没回来,``wait()`` 0.00 秒就回来
       —— 它只收进程,不等管道。第一版修法就是栽在这儿,自己把自己挂住了。
    """
    with contextlib.suppress(Exception):
        if os.name != "nt" and process.pid:
            pgid = os.getpgid(process.pid)
            # **绝不给自己所在的组发信号。**
            #
            # 上面起进程时带了 start_new_session,所以正常情况下孩子自成一组。
            # 但那个参数哪天被谁顺手删掉(自证时我就试过一次),孩子就落在本进程
            # 同一个组里 —— 这一行 killpg 会把**调用方自己**一起杀掉。实测:
            # 删掉那个参数之后,整个 pytest 进程被自己的清理逻辑打死,连一行
            # 失败信息都没留下。
            #
            # 一个"清理"动作能把调用方打死,是比它要治的那个泄漏更坏的故障。
            # 所以先问一句:这是不是我自己的组?是就退回去只杀那一个进程。
            if pgid != os.getpgid(0):
                os.killpg(pgid, signal.SIGKILL)
                return
    with contextlib.suppress(Exception):
        process.kill()


@dataclass
class SkillMD:
    """SKILL.md 解析结果"""

    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    homepage: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Markdown 内容
    content: str = ""

    # 解析的命令
    commands: List[Dict[str, str]] = field(default_factory=list)

    # 来源
    source_path: str = ""

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "homepage": self.homepage,
            "metadata": self.metadata,
            "content": self.content,
            "commands": self.commands,
            "source_path": self.source_path,
        }


class SkillMDLoader:
    """
    SKILL.md 格式加载器

    兼容 OpenClaw 的技能格式
    """

    _instance = None

    def __init__(self):
        self.skills: Dict[str, SkillMD] = {}
        logger.info("SKILL.md 加载器初始化")

    async def _refresh_capability_registry(self, skill_id: str, event: str) -> None:
        """SKILL.md 加载/卸载后，最佳努力刷新能力总线并广播事件。"""
        try:
            from core.agent.capability_registry import CapabilityRegistry

            reg = CapabilityRegistry.get_instance()
            await reg.refresh(force=True)
            logger.info("CapabilityRegistry 已刷新（SKILL.md %s: %s）", skill_id, event)
        except Exception as exc:
            logger.debug("CapabilityRegistry 刷新失败（不影响运行）: %s", exc)

        try:
            from core.routes._shared import broadcast_event

            await broadcast_event(
                "skill_update", {"skill_id": skill_id, "event": event, "runtime_semantics": "shell_command_skill"}
            )
            await broadcast_event(
                "capability_update",
                {
                    "source": "skill_md_loader",
                    "skill_id": skill_id,
                    "event": event,
                    "runtime_semantics": "shell_command_skill",
                },
            )
        except Exception as exc:
            logger.debug("SKILL.md capability broadcast failed（不影响运行）: %s", exc)

    def _inject_skill_to_registry(self, skill_id: str) -> None:
        """将 SKILL.md 技能注入能力总线。"""
        try:
            from core.agent.capability_registry import CapabilityRegistry

            skill = self.skills.get(skill_id)
            if not skill:
                return
            CapabilityRegistry.get_instance().inject_skill(
                skill_id=skill_id,
                skill_name=skill.name,
                description=skill.description or skill.name,
                parameters={},
            )
            logger.info("SKILL.md 技能已注入能力总线: %s", skill_id)
        except Exception as exc:
            logger.debug("SKILL.md 技能注入能力总线失败（不影响运行）: %s", exc)

    @classmethod
    def get_instance(cls) -> "SkillMDLoader":
        if cls._instance is None:
            cls._instance = SkillMDLoader()
        return cls._instance

    def parse(self, content: str, source_path: str = "") -> Optional[SkillMD]:
        """
        解析 SKILL.md 内容

        Args:
            content: SKILL.md 文件内容
            source_path: 来源路径

        Returns:
            解析后的 SkillMD 对象
        """
        try:
            # 提取 YAML frontmatter
            frontmatter = {}
            md_content = content

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    yaml_content = parts[1].strip()
                    md_content = parts[2].strip()

                    # 简单解析 YAML (不依赖 PyYAML)
                    frontmatter = self._parse_yaml(yaml_content)

            # 创建 SkillMD 对象
            skill = SkillMD(
                name=frontmatter.get("name", "unnamed"),
                description=frontmatter.get("description", ""),
                version=frontmatter.get("version", "1.0.0"),
                author=frontmatter.get("author", ""),
                tags=frontmatter.get("tags", []),
                homepage=frontmatter.get("homepage", ""),
                metadata=frontmatter.get("metadata", {}),
                content=md_content,
                source_path=source_path,
            )

            # 解析命令
            skill.commands = self._extract_commands(md_content)

            return skill

        except Exception as e:
            logger.error(f"解析 SKILL.md 失败: {e}")
            return None

    def _parse_yaml(self, yaml_content: str) -> Dict:
        """简单解析 YAML frontmatter"""
        result = {}

        for line in yaml_content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # key: value
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                # 处理引号
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]

                # 处理列表
                if value.startswith("[") and value.endswith("]"):
                    # 简单列表解析
                    items = value[1:-1].split(",")
                    value = [item.strip().strip('"').strip("'") for item in items if item.strip()]

                # 处理字典
                elif value.startswith("{"):
                    try:
                        value = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        pass

                result[key] = value

        return result

    def _extract_commands(self, md_content: str) -> List[Dict[str, str]]:
        """从 Markdown 中提取命令"""
        commands = []

        # 提取代码块
        pattern = r"```(\w+)?\n(.*?)```"
        matches = re.findall(pattern, md_content, re.DOTALL)

        for lang, code in matches:
            lang = lang or "bash"
            code = code.strip()

            # 只提取 bash/sh 命令
            if lang in ["bash", "sh", "shell", ""]:
                for line in code.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        commands.append(
                            {
                                "language": lang,
                                "command": line,
                            }
                        )

        return commands

    async def load(self, path: str, skill_id: str = None) -> Dict[str, Any]:
        """
        加载 SKILL.md 文件

        Args:
            path: SKILL.md 文件路径或包含 SKILL.md 的目录
            skill_id: 自定义技能 ID

        Returns:
            加载结果
        """
        path = Path(path)

        # 确定文件路径
        if path.is_file():
            skill_file = path
            skill_dir = path.parent
        elif path.is_dir():
            skill_file = path / "SKILL.md"
            skill_dir = path
        else:
            return {"success": False, "error": f"路径不存在: {path}"}

        if not skill_file.exists():
            return {"success": False, "error": f"找不到 SKILL.md: {skill_file}"}

        try:
            # 读取文件
            content = skill_file.read_text()

            # 解析
            skill = self.parse(content, str(skill_dir))

            if not skill:
                return {"success": False, "error": "解析失败"}

            # 使用自定义 ID 或名称
            skill_id = skill_id or skill.name.lower().replace(" ", "-")

            # 存储
            self.skills[skill_id] = skill
            self._inject_skill_to_registry(skill_id)
            try:
                loop = asyncio.get_running_loop()
                _bt = loop.create_task(self._refresh_capability_registry(skill_id, "load"))
                _BACKGROUND_TASKS.add(_bt)
                _bt.add_done_callback(_BACKGROUND_TASKS.discard)
            except RuntimeError:
                logger.debug("SKILL.md load capability refresh skipped: no running event loop")
            except Exception as exc:
                logger.debug("SKILL.md load capability refresh scheduling failed: %s", exc)

            logger.info(f"加载技能: {skill.name} ({skill_id})")

            return {
                "success": True,
                "skill_id": skill_id,
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "commands_count": len(skill.commands),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def execute(
        self,
        skill_id: str,
        params: Dict[str, Any] = None,
        budget_s: float = DEFAULT_EXECUTE_BUDGET_S,
    ) -> Dict[str, Any]:
        """
        执行技能

        Args:
            skill_id: 技能 ID
            params: 参数 (用于替换命令中的占位符)
            budget_s: **整个技能**的总时限。不是每条命令的时限。

        Returns:
            执行结果
        """
        if skill_id not in self.skills:
            return {"success": False, "error": "技能不存在"}

        skill = self.skills[skill_id]
        params = params or {}

        results = []
        # 整条技能只有一个截止时刻。
        #
        # 从前这里是每条命令各给 60 秒、没有总上限 —— 于是 6 条命令挂住就是
        # 360 秒,而调用方(判据、请求、界面)给的预算往往只有一两分钟。
        # **内层时限比外层预算大,优雅降级那条路就永远走不到**:调用方只会看到
        # 自己被硬杀掉,拿不到"哪几条跑了、哪几条超时"这份结果。
        #
        # 真实案发:CI 上 tests/test_skill_md.py 连续两次被 pytest-timeout 在
        # 120 秒砍掉 —— 示例技能有 6 条 curl,wttr.in 挂住的那次,6×60 必然超。
        deadline = time.monotonic() + max(0.0, budget_s)

        for cmd_info in skill.commands:
            command = cmd_info["command"]

            left = deadline - time.monotonic()
            if left <= 0:
                # 预算用完了。**这不是失败,也不是成功 —— 是没轮到。**
                # 标成失败会让人去查一条根本没跑过的命令;当成跳过不记,
                # 这份结果就假装技能整条跑完了。所以单独说。
                results.append(
                    {
                        "command": command,
                        "success": False,
                        "attempted": False,
                        "error": f"没轮到执行 —— 整条技能的 {budget_s:.0f} 秒预算已用完",
                        "runtime_semantics": "shell_command_skill",
                        "capability_checked": True,
                    }
                )
                continue

            # 替换参数
            for key, value in params.items():
                command = command.replace(f"{{{key}}}", str(value))
                command = command.replace(f"${key}", str(value))

            try:
                # Parse command into argv safely (no shell interpolation)
                try:
                    argv = shlex.split(command)
                except ValueError as exc:
                    results.append(
                        {
                            "command": command,
                            "success": False,
                            "error": f"命令解析失败: {exc}",
                        }
                    )
                    continue

                if not argv:
                    results.append(
                        {
                            "command": command,
                            "success": False,
                            "error": "空命令",
                        }
                    )
                    continue

                # Enforce allowlist: use os.path.basename so full paths like
                # /usr/bin/curl resolve to "curl" before checking.
                base_cmd = os.path.basename(argv[0])
                if base_cmd not in ALLOWED_COMMANDS:
                    logger.warning("命令被安全策略阻止: '%s'", base_cmd)
                    results.append(
                        {
                            "command": command,
                            "success": False,
                            "error": (
                                f"命令被安全策略阻止: '{base_cmd}' 不在允许列表中。"
                                f" 允许的命令: {', '.join(sorted(ALLOWED_COMMANDS))}"
                            ),
                        }
                    )
                    continue

                resolved = shutil.which(base_cmd)
                if resolved is None and not (os.path.isabs(argv[0]) and os.path.exists(argv[0])):
                    results.append(
                        {
                            "command": command,
                            "success": False,
                            "error": f"运行时能力不可用: 找不到可执行命令 '{base_cmd}'",
                            "runtime_semantics": "shell_command_skill",
                            "capability_checked": True,
                        }
                    )
                    continue

                # Execute safely — no shell; argv is explicit.
                # Because create_subprocess_exec never invokes a shell, shell
                # metacharacters (;, |, &, $()) in argument values are treated
                # as literal strings and cannot cause injection.
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    # 自成一个进程组/会话。**超时要收的不是一个进程,是一棵树** ——
                    # 见下面 _kill_process_tree 的说明。
                    **_NEW_GROUP_KW,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=left,
                    )
                except asyncio.TimeoutError:
                    # 超时必须把这棵进程树收掉,并且**用 wait() 而不是
                    # communicate()** —— 两件事都是实测撞出来的,见函数说明。
                    _kill_process_tree(process)
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(process.wait(), timeout=5)
                    raise

                results.append(
                    {
                        "command": command,
                        "success": process.returncode == 0,
                        "stdout": stdout.decode(),
                        "stderr": stderr.decode(),
                        "runtime_semantics": "shell_command_skill",
                        "capability_checked": True,
                    }
                )

            except asyncio.TimeoutError:
                results.append(
                    {
                        "command": command,
                        "success": False,
                        "attempted": True,
                        "error": f"执行超时(整条技能剩余预算 {left:.1f} 秒)",
                        "runtime_semantics": "shell_command_skill",
                        "capability_checked": True,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "command": command,
                        "success": False,
                        "error": str(e),
                        "runtime_semantics": "shell_command_skill",
                        "capability_checked": True,
                    }
                )

        return {
            "success": all(r["success"] for r in results),
            "results": results,
            "runtime_semantics": "shell_command_skill",
        }

    def list_skills(self) -> List[Dict]:
        """列出所有技能"""
        return [skill.to_dict() for skill in self.skills.values()]

    def get_skill(self, skill_id: str) -> Optional[Dict]:
        """获取技能详情"""
        if skill_id in self.skills:
            return self.skills[skill_id].to_dict()
        return None

    def unload(self, skill_id: str) -> Dict[str, Any]:
        """卸载技能"""
        if skill_id not in self.skills:
            return {"success": False, "error": "技能不存在"}

        skill = self.skills.pop(skill_id)
        try:
            from core.agent.capability_registry import CapabilityRegistry

            CapabilityRegistry.get_instance().eject(f"skill__{skill_id}")
        except Exception as exc:
            logger.debug("SKILL.md 技能从能力总线移除失败（不影响运行）: %s", exc)

        try:
            loop = asyncio.get_running_loop()
            _bt = loop.create_task(self._refresh_capability_registry(skill_id, "unload"))
            _BACKGROUND_TASKS.add(_bt)
            _bt.add_done_callback(_BACKGROUND_TASKS.discard)
        except RuntimeError:
            logger.debug("SKILL.md unload capability refresh skipped: no running event loop")
        except Exception as exc:
            logger.debug("SKILL.md unload capability refresh scheduling failed: %s", exc)

        return {
            "success": True,
            "skill_id": skill_id,
            "name": skill.name,
        }


# 全局实例
skill_md_loader = SkillMDLoader.get_instance()
