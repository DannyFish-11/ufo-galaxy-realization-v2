"""
Node 117 - OpenCode (开放代码节点)
提供代码执行、沙箱运行和多语言支持能力
"""
import os
import json
import asyncio
import logging
import tempfile
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node 117 - OpenCode", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class Language(str, Enum):
    """支持的编程语言"""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    BASH = "bash"
    RUBY = "ruby"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    CPP = "cpp"
    C = "c"


class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class LanguageRuntime:
    """语言运行时"""
    language: Language
    command: str
    file_extension: str
    compile_command: Optional[str] = None
    available: bool = False
    version: Optional[str] = None


@dataclass
class CodeExecution:
    """代码执行记录"""
    execution_id: str
    language: Language
    code: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    execution_time: float = 0.0
    memory_used: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Sandbox:
    """沙箱环境"""
    sandbox_id: str
    working_dir: str
    created_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    executions: List[str] = field(default_factory=list)
    files: Dict[str, str] = field(default_factory=dict)


class OpenCodeEngine:
    """开放代码引擎"""
    
    def __init__(self):
        self.runtimes: Dict[Language, LanguageRuntime] = {}
        self.executions: Dict[str, CodeExecution] = {}
        self.sandboxes: Dict[str, Sandbox] = {}
        self._initialize_runtimes()
    
    def _initialize_runtimes(self):
        """初始化语言运行时"""
        runtimes = [
            LanguageRuntime(Language.PYTHON, "python3", ".py"),
            LanguageRuntime(Language.JAVASCRIPT, "node", ".js"),
            LanguageRuntime(Language.TYPESCRIPT, "npx ts-node", ".ts"),
            LanguageRuntime(Language.BASH, "bash", ".sh"),
            LanguageRuntime(Language.RUBY, "ruby", ".rb"),
            LanguageRuntime(Language.GO, "go run", ".go"),
            LanguageRuntime(Language.RUST, "rustc", ".rs", compile_command="rustc {file} -o {output}"),
            LanguageRuntime(Language.JAVA, "java", ".java", compile_command="javac {file}"),
            LanguageRuntime(Language.CPP, "g++", ".cpp", compile_command="g++ {file} -o {output}"),
            LanguageRuntime(Language.C, "gcc", ".c", compile_command="gcc {file} -o {output}"),
        ]
        
        for runtime in runtimes:
            self.runtimes[runtime.language] = runtime
            self._check_runtime(runtime)
    
    def _check_runtime(self, runtime: LanguageRuntime):
        """检查运行时是否可用"""
        cmd = runtime.command.split()[0]
        if shutil.which(cmd):
            runtime.available = True
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    runtime.version = result.stdout.strip().split('\n')[0]
            except Exception:
                pass
    
    def create_sandbox(self) -> str:
        """创建沙箱环境"""
        sandbox_id = str(uuid.uuid4())
        working_dir = tempfile.mkdtemp(prefix=f"sandbox_{sandbox_id[:8]}_")
        
        sandbox = Sandbox(
            sandbox_id=sandbox_id,
            working_dir=working_dir
        )
        
        self.sandboxes[sandbox_id] = sandbox
        logger.info(f"Created sandbox: {sandbox_id}")
        return sandbox_id
    
    def destroy_sandbox(self, sandbox_id: str) -> bool:
        """销毁沙箱环境"""
        if sandbox_id not in self.sandboxes:
            return False
        
        sandbox = self.sandboxes[sandbox_id]
        
        try:
            shutil.rmtree(sandbox.working_dir, ignore_errors=True)
        except OSError:
            pass

        sandbox.is_active = False
        del self.sandboxes[sandbox_id]
        logger.info(f"Destroyed sandbox: {sandbox_id}")
        return True
    
    def add_file_to_sandbox(self, sandbox_id: str, filename: str, content: str) -> bool:
        """向沙箱添加文件"""
        if sandbox_id not in self.sandboxes:
            return False
        
        sandbox = self.sandboxes[sandbox_id]
        filepath = os.path.join(sandbox.working_dir, filename)
        
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w') as f:
                f.write(content)
            sandbox.files[filename] = filepath
            return True
        except Exception as e:
            logger.error(f"Failed to add file to sandbox: {e}")
            return False
    
    async def execute(self, language: Language, code: str,
                      sandbox_id: Optional[str] = None,
                      timeout: int = 30,
                      stdin: str = None) -> CodeExecution:
        """执行代码"""
        if language not in self.runtimes:
            raise ValueError(f"Unsupported language: {language}")
        
        runtime = self.runtimes[language]
        if not runtime.available:
            raise RuntimeError(f"Runtime not available: {language}")
        
        # 创建执行记录
        execution = CodeExecution(
            execution_id=str(uuid.uuid4()),
            language=language,
            code=code,
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now()
        )
        
        self.executions[execution.execution_id] = execution
        
        # 确定工作目录
        if sandbox_id and sandbox_id in self.sandboxes:
            working_dir = self.sandboxes[sandbox_id].working_dir
            self.sandboxes[sandbox_id].executions.append(execution.execution_id)
        else:
            working_dir = tempfile.mkdtemp()
        
        try:
            # 写入代码文件
            filename = f"code_{execution.execution_id[:8]}{runtime.file_extension}"
            filepath = os.path.join(working_dir, filename)
            
            with open(filepath, 'w') as f:
                f.write(code)
            
            # 编译（如果需要）
            if runtime.compile_command:
                output_file = os.path.join(working_dir, f"output_{execution.execution_id[:8]}")
                compile_cmd = runtime.compile_command.format(file=filepath, output=output_file)
                
                compile_result = await self._run_process(
                    compile_cmd,
                    working_dir,
                    timeout=timeout
                )
                
                if compile_result["exit_code"] != 0:
                    execution.status = ExecutionStatus.FAILED
                    execution.stderr = compile_result["stderr"]
                    execution.exit_code = compile_result["exit_code"]
                    execution.completed_at = datetime.now()
                    return execution
                
                # 运行编译后的程序
                run_cmd = output_file
            else:
                # 直接运行
                run_cmd = f"{runtime.command} {filepath}"
            
            # 执行代码
            start_time = datetime.now()
            result = await self._run_process(
                run_cmd,
                working_dir,
                timeout=timeout,
                stdin=stdin
            )
            end_time = datetime.now()
            
            execution.stdout = result["stdout"]
            execution.stderr = result["stderr"]
            execution.exit_code = result["exit_code"]
            execution.execution_time = (end_time - start_time).total_seconds()
            
            if result["timeout"]:
                execution.status = ExecutionStatus.TIMEOUT
            elif result["exit_code"] == 0:
                execution.status = ExecutionStatus.COMPLETED
            else:
                execution.status = ExecutionStatus.FAILED
            
        except Exception as e:
            execution.status = ExecutionStatus.FAILED
            execution.stderr = str(e)
            logger.error(f"Execution failed: {e}")
        
        finally:
            execution.completed_at = datetime.now()
            
            # 清理临时目录（如果不是沙箱）
            if not sandbox_id:
                try:
                    shutil.rmtree(working_dir, ignore_errors=True)
                except OSError:
                    pass
        
        return execution
    
    async def _run_process(self, command: str, working_dir: str,
                           timeout: int = 30, stdin: str = None) -> Dict[str, Any]:
        """运行进程"""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE if stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(stdin.encode() if stdin else None),
                    timeout=timeout
                )
                
                return {
                    "stdout": stdout.decode('utf-8', errors='replace'),
                    "stderr": stderr.decode('utf-8', errors='replace'),
                    "exit_code": process.returncode,
                    "timeout": False
                }
            except asyncio.TimeoutError:
                process.kill()
                return {
                    "stdout": "",
                    "stderr": "Execution timed out",
                    "exit_code": -1,
                    "timeout": True
                }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "timeout": False
            }
    
    def get_supported_languages(self) -> List[Dict[str, Any]]:
        """获取支持的语言列表"""
        return [
            {
                "language": runtime.language.value,
                "available": runtime.available,
                "version": runtime.version,
                "file_extension": runtime.file_extension
            }
            for runtime in self.runtimes.values()
        ]
    
    def get_execution(self, execution_id: str) -> Optional[CodeExecution]:
        """获取执行记录"""
        return self.executions.get(execution_id)
    
    def get_status(self) -> Dict[str, Any]:
        """获取引擎状态"""
        return {
            "supported_languages": len(self.runtimes),
            "available_languages": sum(1 for r in self.runtimes.values() if r.available),
            "total_executions": len(self.executions),
            "active_sandboxes": sum(1 for s in self.sandboxes.values() if s.is_active),
            "successful_executions": sum(1 for e in self.executions.values() if e.status == ExecutionStatus.COMPLETED)
        }


# 全局实例
code_engine = OpenCodeEngine()


# API 模型
class ExecuteCodeRequest(BaseModel):
    language: str
    code: str
    sandbox_id: Optional[str] = None
    timeout: int = 30
    stdin: Optional[str] = None

class AddFileRequest(BaseModel):
    filename: str
    content: str


# API 端点
@app.get("/health")
async def health_check():
    return {"status": "healthy", "node": "Node_117_OpenCode"}

@app.get("/status")
async def get_status():
    return code_engine.get_status()

@app.get("/languages")
async def get_languages():
    return code_engine.get_supported_languages()

@app.post("/execute")
async def execute_code(request: ExecuteCodeRequest):
    try:
        execution = await code_engine.execute(
            Language(request.language),
            request.code,
            request.sandbox_id,
            request.timeout,
            request.stdin
        )
        return asdict(execution)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

@app.get("/executions/{execution_id}")
async def get_execution(execution_id: str):
    execution = code_engine.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return asdict(execution)

@app.get("/executions")
async def list_executions(language: Optional[str] = None, status: Optional[str] = None, limit: int = 50):
    executions = list(code_engine.executions.values())
    if language:
        executions = [e for e in executions if e.language.value == language]
    if status:
        executions = [e for e in executions if e.status.value == status]
    executions = sorted(executions, key=lambda e: e.started_at or datetime.min, reverse=True)[:limit]
    return [asdict(e) for e in executions]

@app.post("/sandboxes")
async def create_sandbox():
    sandbox_id = code_engine.create_sandbox()
    return {"sandbox_id": sandbox_id}

@app.delete("/sandboxes/{sandbox_id}")
async def destroy_sandbox(sandbox_id: str):
    success = code_engine.destroy_sandbox(sandbox_id)
    return {"success": success}

@app.get("/sandboxes")
async def list_sandboxes():
    return [
        {
            "sandbox_id": s.sandbox_id,
            "working_dir": s.working_dir,
            "is_active": s.is_active,
            "execution_count": len(s.executions),
            "file_count": len(s.files)
        }
        for s in code_engine.sandboxes.values()
    ]

@app.post("/sandboxes/{sandbox_id}/files")
async def add_file(sandbox_id: str, request: AddFileRequest):
    success = code_engine.add_file_to_sandbox(sandbox_id, request.filename, request.content)
    return {"success": success}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8117)
