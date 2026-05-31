"""
Node 09: Sandbox - 安全的代码沙箱执行环境
支持多种编程语言，具备资源限制和安全检查

若宿主机未安装某语言运行时，该语言会被自动排除出可用列表；
健康检查始终立即返回 HTTP 200，可用语言列表在启动时预计算并缓存。
"""
import os, subprocess, tempfile, shutil, signal
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

# resource 模块仅 Unix 下可用
try:
    import resource as _resource
    _RESOURCE_AVAILABLE = True
except ImportError:
    _resource = None  # type: ignore[assignment]
    _RESOURCE_AVAILABLE = False

logger = logging.getLogger("Node_09_Sandbox")

# ============ 运行时状态缓存 ============
_available_languages: List[str] = []
_sandbox_mode: str = "healthy"  # 始终 healthy，只是语言列表可能为空

class ExecuteRequest(BaseModel):
    code: str
    language: str = "python"
    timeout: int = 30
    stdin: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    memory_limit_mb: Optional[int] = 256
    cpu_limit_seconds: Optional[int] = None

class FileExecuteRequest(BaseModel):
    files: Dict[str, str]  # filename: content
    entry_point: str
    language: str = "python"
    timeout: int = 60
    stdin: Optional[str] = None

LANGUAGE_CONFIG = {
    "python": {"ext": ".py", "cmd": ["python3"], "version_check": ["python3", "--version"]},
    "python2": {"ext": ".py", "cmd": ["python2"], "version_check": ["python2", "--version"]},
    "javascript": {"ext": ".js", "cmd": ["node"], "version_check": ["node", "--version"]},
    "typescript": {"ext": ".ts", "cmd": ["ts-node"], "version_check": ["ts-node", "--version"]},
    "bash": {"ext": ".sh", "cmd": ["bash"], "version_check": ["bash", "--version"]},
    "sh": {"ext": ".sh", "cmd": ["sh"], "version_check": ["sh", "--version"]},
    "ruby": {"ext": ".rb", "cmd": ["ruby"], "version_check": ["ruby", "--version"]},
    "php": {"ext": ".php", "cmd": ["php"], "version_check": ["php", "--version"]},
    "perl": {"ext": ".pl", "cmd": ["perl"], "version_check": ["perl", "--version"]},
    "lua": {"ext": ".lua", "cmd": ["lua"], "version_check": ["lua", "-v"]},
    "go": {"ext": ".go", "cmd": ["go", "run"], "version_check": ["go", "version"]},
    "rust": {"ext": ".rs", "cmd": ["rustc", "-o", "/tmp/rust_out", "&&", "/tmp/rust_out"], "version_check": ["rustc", "--version"]},
    "c": {"ext": ".c", "cmd": ["gcc", "-o", "/tmp/c_out", "&&", "/tmp/c_out"], "version_check": ["gcc", "--version"]},
    "cpp": {"ext": ".cpp", "cmd": ["g++", "-o", "/tmp/cpp_out", "&&", "/tmp/cpp_out"], "version_check": ["g++", "--version"]},
}

# 危险命令黑名单
DANGEROUS_PATTERNS = [
    "rm -rf", "dd if=", "mkfs", "format", "fdisk",
    ":(){ :|:& };:", "chmod 777", "wget", "curl http",
    "nc -l", "telnet", "ssh", "/etc/passwd", "/etc/shadow"
]

def check_code_safety(code: str) -> tuple[bool, Optional[str]]:
    """检查代码安全性"""
    for pattern in DANGEROUS_PATTERNS:
        if pattern in code.lower():
            return False, f"Dangerous pattern detected: {pattern}"
    return True, None

def set_resource_limits(memory_limit_mb: int, cpu_limit_seconds: Optional[int]):
    """设置资源限制 (仅 Unix 系统)"""
    if not _RESOURCE_AVAILABLE:
        return  # Windows 不支持 resource 模块
    try:
        # 内存限制
        memory_bytes = memory_limit_mb * 1024 * 1024
        _resource.setrlimit(_resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        
        # CPU 时间限制
        if cpu_limit_seconds:
            _resource.setrlimit(_resource.RLIMIT_CPU, (cpu_limit_seconds, cpu_limit_seconds))
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)


def _check_language_available(lang: str, config: dict) -> bool:
    """以短超时（1 秒）同步探测某语言是否可用，避免长时间阻塞。"""
    try:
        result = subprocess.run(
            config["version_check"],
            capture_output=True,
            timeout=1,
        )
        return result.returncode == 0
    except Exception as exc:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时预计算可用语言列表并缓存，后续健康检查直接返回缓存结果。"""
    global _available_languages
    import concurrent.futures, asyncio
    loop = asyncio.get_event_loop()
    logger.info("Node_09_Sandbox: 正在探测可用语言运行时 …")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = {
            lang: loop.run_in_executor(pool, _check_language_available, lang, cfg)
            for lang, cfg in LANGUAGE_CONFIG.items()
        }
        for lang, fut in futs.items():
            try:
                if await fut:
                    _available_languages.append(lang)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
    if _available_languages:
        logger.info("Node_09_Sandbox: 可用语言: %s", _available_languages)
    else:
        logger.warning(
            "Node_09_Sandbox: 未找到任何可用语言运行时，将以受限模式运行。"
        )
    yield


app = FastAPI(
    title="Node 09 - Sandbox",
    version="3.0.0",
    description="Secure code execution sandbox with resource limits",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health():
    """健康检查 - 使用启动时预计算的语言列表，不阻塞事件循环。"""
    return {
        "status": "healthy",
        "node_id": "09",
        "name": "Sandbox",
        "supported_languages": list(LANGUAGE_CONFIG.keys()),
        "available_languages": _available_languages,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/status")
async def node_status():
    """Node status endpoint."""
    return {
        "node_id": "09",
        "name": "Sandbox",
        "port": 7996,
        "active_sandboxes": 0,
        "available_languages": _available_languages,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/execute")
async def execute_code(request: ExecuteRequest):
    """执行代码"""
    lang = request.language.lower()
    if lang not in LANGUAGE_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {lang}")
    
    # 安全检查
    is_safe, error = check_code_safety(request.code)
    if not is_safe:
        raise HTTPException(status_code=403, detail=error)
    
    config = LANGUAGE_CONFIG[lang]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        code_file = os.path.join(tmpdir, f"code{config['ext']}")
        with open(code_file, "w") as f:
            f.write(request.code)
        
        cmd = config["cmd"] + [code_file]
        if request.args:
            cmd.extend(request.args)
        
        # 准备环境变量
        env = os.environ.copy()
        if request.env:
            env.update(request.env)
        
        try:
            # 设置资源限制的预执行函数
            def preexec_fn():
                set_resource_limits(request.memory_limit_mb or 256, request.cpu_limit_seconds)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=request.timeout,
                input=request.stdin,
                cwd=tmpdir,
                env=env,
                preexec_fn=preexec_fn if os.name != 'nt' else None
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
                "language": lang
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Execution timed out",
                "timeout": request.timeout,
                "language": lang
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "language": lang
            }

@app.post("/execute_files")
async def execute_files(request: FileExecuteRequest):
    """执行多文件项目"""
    lang = request.language.lower()
    if lang not in LANGUAGE_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {lang}")
    
    # 检查所有文件的安全性
    for filename, content in request.files.items():
        is_safe, error = check_code_safety(content)
        if not is_safe:
            raise HTTPException(status_code=403, detail=f"Dangerous code in {filename}: {error}")
    
    config = LANGUAGE_CONFIG[lang]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # 写入所有文件
        for filename, content in request.files.items():
            file_path = os.path.join(tmpdir, filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(content)
        
        entry_file = os.path.join(tmpdir, request.entry_point)
        cmd = config["cmd"] + [entry_file]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=request.timeout,
                input=request.stdin,
                cwd=tmpdir
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
                "language": lang,
                "files_count": len(request.files)
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Execution timed out",
                "timeout": request.timeout
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

@app.post("/eval")
async def eval_expression(expression: str, language: str = "python"):
    """快速求值表达式"""
    if language == "python":
        code = f"print({expression})"
    elif language == "javascript":
        code = f"console.log({expression})"
    elif language == "ruby":
        code = f"puts {expression}"
    elif language == "php":
        code = f"<?php echo {expression}; ?>"
    else:
        raise HTTPException(status_code=400, detail=f"Eval not supported for {language}")
    
    return await execute_code(ExecuteRequest(code=code, language=language, timeout=5))

@app.post("/test")
async def run_tests(code: str, tests: List[Dict[str, Any]], language: str = "python"):
    """运行测试用例"""
    results = []
    for i, test in enumerate(tests):
        stdin = test.get("input", "")
        expected_output = test.get("expected", "")
        
        exec_result = await execute_code(ExecuteRequest(
            code=code,
            language=language,
            stdin=stdin,
            timeout=10
        ))
        
        actual_output = exec_result.get("stdout", "").strip()
        passed = actual_output == expected_output.strip()
        
        results.append({
            "test_id": i + 1,
            "passed": passed,
            "input": stdin,
            "expected": expected_output,
            "actual": actual_output,
            "error": exec_result.get("stderr", "")
        })
    
    passed_count = sum(1 for r in results if r["passed"])
    return {
        "success": True,
        "total": len(tests),
        "passed": passed_count,
        "failed": len(tests) - passed_count,
        "results": results
    }

@app.get("/languages")
async def list_languages():
    """列出所有支持的语言"""
    languages = []
    for lang, config in LANGUAGE_CONFIG.items():
        try:
            result = subprocess.run(config["version_check"], capture_output=True, text=True, timeout=5)
            version = result.stdout.strip() if result.returncode == 0 else "unknown"
            available = result.returncode == 0
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            version = "not installed"
            available = False
        
        languages.append({
            "name": lang,
            "extension": config["ext"],
            "available": available,
            "version": version
        })
    
    return {"success": True, "languages": languages}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    """MCP 工具调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "execute":
        return await execute_code(ExecuteRequest(**params))
    elif tool == "execute_files":
        return await execute_files(FileExecuteRequest(**params))
    elif tool == "eval":
        return await eval_expression(params.get("expression", ""), params.get("language", "python"))
    elif tool == "test":
        return await run_tests(params.get("code", ""), params.get("tests", []), params.get("language", "python"))
    elif tool == "languages":
        return await list_languages()
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    try:
        from core.port_config import get_node_port
        _port = get_node_port("Node_09_Sandbox")
    except (ImportError, KeyError):
        _port = 7996
    uvicorn.run(app, host="0.0.0.0", port=_port)
