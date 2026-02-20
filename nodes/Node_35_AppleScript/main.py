import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

# 配置日志记录器
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("node_35_applescript.log")
    ]
)

logger = logging.getLogger(__name__)

class NodeStatus(Enum):
    """定义节点运行状态的枚举"""
    INITIALIZING = "INITIALIZING"  # 正在初始化
    RUNNING = "RUNNING"          # 正在运行
    STOPPED = "STOPPED"          # 已停止
    ERROR = "ERROR"              # 出现错误
    DEGRADED = "DEGRADED"        # 降级运行

class ScriptExecutionStatus(Enum):
    """定义 AppleScript 脚本执行状态的枚举"""
    PENDING = "PENDING"          # 等待执行
    SUCCESS = "SUCCESS"          # 执行成功
    FAILED = "FAILED"            # 执行失败
    TIMEOUT = "TIMEOUT"          # 执行超时

@dataclass
class AppleScriptConfig:
    """存储 AppleScript 节点的配置信息"""
    node_name: str = "Node_35_AppleScript" # 节点名称
    default_timeout: int = 30  # 默认脚本执行超时时间（秒）
    log_file: str = "node_35_applescript.log" # 日志文件路径

@dataclass
class ExecutionResult:
    """存储单次脚本执行的结果"""
    status: ScriptExecutionStatus = ScriptExecutionStatus.PENDING
    output: Optional[str] = None
    error: Optional[str] = None
    execution_time: float = 0.0

class Node35AppleScriptService:
    """主服务类，负责处理 AppleScript 的执行和节点管理"""

    def __init__(self, config: Optional[AppleScriptConfig] = None):
        """初始化服务"""
        self.config = config if config else self.load_config()
        self.status = NodeStatus.INITIALIZING
        self.last_execution_result: Optional[ExecutionResult] = None
        logger.info(f"节点 {self.config.node_name} 正在初始化...")
        self._verify_environment()
        self.status = NodeStatus.RUNNING
        logger.info(f"节点 {self.config.node_name} 初始化完成，当前状态: {self.status.value}")

    def load_config(self) -> AppleScriptConfig:
        """加载配置。在此示例中，我们使用默认配置。"""
        logger.info("加载默认配置...")
        return AppleScriptConfig()

    def _verify_environment(self):
        """验证运行环境，主要是检查 `osascript` 命令是否存在"""
        logger.info("正在验证运行环境...")
        try:
            # 使用 subprocess.run 检查命令是否存在且可执行
            result = subprocess.run(["which", "osascript"], capture_output=True, text=True, check=True)
            if result.stdout:
                logger.info(f"`osascript` 命令已找到: {result.stdout.strip()}")
            else:
                logger.error("`osascript` 命令未找到，此节点无法在非 macOS 环境下运行。")
                self.status = NodeStatus.ERROR
                raise EnvironmentError("`osascript` command not found. This node can only run on macOS.")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"环境验证失败: {e}")
            self.status = NodeStatus.ERROR
            raise EnvironmentError("Failed to verify `osascript` command.") from e

    async def execute_script(self, script: str, timeout: Optional[int] = None) -> ExecutionResult:
        """异步执行 AppleScript 脚本"""
        if self.status != NodeStatus.RUNNING:
            logger.warning(f"节点状态为 {self.status.value}，无法执行脚本。")
            return ExecutionResult(status=ScriptExecutionStatus.FAILED, error="Node is not in RUNNING state.")

        execution_timeout = timeout if timeout is not None else self.config.default_timeout
        logger.info(f"准备执行 AppleScript，超时设置为 {execution_timeout} 秒。")
        logger.debug(f"待执行脚本:\n---\n{script}\n---")

        start_time = asyncio.get_event_loop().time()

        try:
            # 创建子进程来执行 osascript 命令
            process = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # 等待脚本执行完成或超时
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=execution_timeout)

            end_time = asyncio.get_event_loop().time()
            execution_time = end_time - start_time

            output_str = stdout.decode().strip()
            error_str = stderr.decode().strip()

            if process.returncode == 0:
                logger.info(f"脚本执行成功，耗时 {execution_time:.2f} 秒。")
                result = ExecutionResult(
                    status=ScriptExecutionStatus.SUCCESS,
                    output=output_str,
                    execution_time=execution_time
                )
            else:
                logger.error(f"脚本执行失败，返回码: {process.returncode}")
                logger.error(f"错误信息: {error_str}")
                result = ExecutionResult(
                    status=ScriptExecutionStatus.FAILED,
                    output=output_str, # 有时错误信息也会输出到 stdout
                    error=error_str,
                    execution_time=execution_time
                )

        except asyncio.TimeoutError:
            logger.error(f"脚本执行超时（超过 {execution_timeout} 秒）。")
            end_time = asyncio.get_event_loop().time()
            result = ExecutionResult(
                status=ScriptExecutionStatus.TIMEOUT,
                error=f"Script execution timed out after {execution_timeout} seconds.",
                execution_time=end_time - start_time
            )
            # 超时后尝试终止进程
            if "process" in locals() and process.returncode is None:
                process.terminate()
                await process.wait()
                logger.warning("已终止超时的脚本进程。")
        except Exception as e:
            logger.critical(f"执行脚本时发生意外错误: {e}", exc_info=True)
            end_time = asyncio.get_event_loop().time()
            result = ExecutionResult(
                status=ScriptExecutionStatus.FAILED,
                error=str(e),
                execution_time=end_time - start_time
            )

        self.last_execution_result = result
        return result

    async def health_check(self) -> dict:
        """提供节点的健康检查接口"""
        logger.info("执行健康检查...")
        # 简单的健康检查逻辑：如果节点状态是 RUNNING，则健康
        is_healthy = self.status == NodeStatus.RUNNING
        return {
            "node_name": self.config.node_name,
            "status": self.status.value,
            "is_healthy": is_healthy,
            "timestamp": asyncio.get_event_loop().time()
        }

    async def get_status(self) -> dict:
        """提供节点详细状态的查询接口"""
        logger.info("查询节点状态...")
        return {
            "node_name": self.config.node_name,
            "status": self.status.value,
            "config": self.config.__dict__,
            "last_execution": self.last_execution_result.__dict__ if self.last_execution_result else None
        }

    async def stop(self):
        """停止节点服务"""
        self.status = NodeStatus.STOPPED
        logger.info(f"节点 {self.config.node_name} 已停止。")

async def main():
    """主函数，用于演示和测试节点功能"""
    logger.info("--- 启动 Node_35_AppleScript 服务演示 ---")
    
    service = None
    try:
        # 1. 初始化服务
        service = Node35AppleScriptService()
        initial_status = await service.get_status()
        logger.info(f"服务初始化状态: {initial_status}")

        # 2. 执行健康检查
        health = await service.health_check()
        logger.info(f"健康检查结果: {health}")

        # 3. 定义一个简单的 AppleScript 脚本
        simple_script = '''display dialog "Hello from UFO Galaxy!" buttons {"OK"} default button "OK" with icon note'''
        logger.info("\n--- 准备执行一个简单的 AppleScript ---")
        result = await service.execute_script(simple_script, timeout=10)
        logger.info(f"简单脚本执行结果: {result.status.value}")
        if result.output:
            logger.info(f"输出: {result.output}")
        if result.error:
            logger.error(f"错误: {result.error}")

        # 4. 查询执行后的状态
        status_after_exec = await service.get_status()
        logger.info(f"执行后状态: {status_after_exec}")

        # 5. 定义一个会失败的 AppleScript 脚本（语法错误）
        failing_script = '''display dialog "This will fail''' # 缺少闭合引号
        logger.info("\n--- 准备执行一个会失败的 AppleScript ---")
        result_fail = await service.execute_script(failing_script)
        logger.info(f"失败脚本执行结果: {result_fail.status.value}")
        if result_fail.error:
            logger.error(f"捕获到的错误: {result_fail.error}")

        # 6. 定义一个可能超时的脚本
        timeout_script = 'delay 10' # 延迟10秒
        logger.info("\n--- 准备执行一个会超时的 AppleScript (超时设置为3秒) ---")
        result_timeout = await service.execute_script(timeout_script, timeout=3)
        logger.info(f"超时脚本执行结果: {result_timeout.status.value}")
        if result_timeout.error:
            logger.error(f"捕获到的错误: {result_timeout.error}")

    except EnvironmentError as e:
        logger.critical(f"无法启动服务，环境不满足要求: {e}")
    except Exception as e:
        logger.critical(f"在主函数中发生未捕获的异常: {e}", exc_info=True)
    finally:
        if service:
            await service.stop()
        logger.info("--- Node_35_AppleScript 服务演示结束 ---")

if __name__ == "__main__":
    # 注意：此脚本需要在 macOS 环境下运行才能成功执行 AppleScript
    # 在非 macOS 环境下，初始化会失败并打印错误信息
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
