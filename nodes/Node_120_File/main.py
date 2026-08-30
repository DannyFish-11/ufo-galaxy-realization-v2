"""
Node 12: File Operations
Galaxy 64-Core MCP Matrix - Core Tool Node

Provides comprehensive file system operations:
- File read/write/append
- Directory operations (create, list, delete)
- File search and pattern matching
- File metadata and permissions
- Archive operations (zip, tar)
- File watching and monitoring

Author: Galaxy Team
Version: 5.0.0
"""

import os
import sys
import json
import asyncio
import logging
import shutil
import hashlib
import mimetypes
import fnmatch
import tarfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn
from nodes.common.cors_config import get_cors_origins

# =============================================================================
# Configuration
# =============================================================================

from core.port_config import get_service_port, get_node_port
from core.fs_walk import iter_tree_files

NODE_ID = os.getenv("NODE_ID", "120")
NODE_NAME = os.getenv("NODE_NAME", "FileOperations")
NODE_PORT = int(os.getenv("NODE_PORT", str(get_node_port("Node_120_File"))))
STATE_MACHINE_URL = os.getenv("STATE_MACHINE_URL", f"http://localhost:{get_service_port('state_machine')}")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.path.join(os.path.expanduser("~"), "workspace"))
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(100 * 1024 * 1024)))  # 100MB

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================

class FileOperation(str, Enum):
    READ = "read"
    WRITE = "write"
    APPEND = "append"
    DELETE = "delete"
    COPY = "copy"
    MOVE = "move"
    RENAME = "rename"
    EXISTS = "exists"
    INFO = "info"
    LIST = "list"
    SEARCH = "search"
    MKDIR = "mkdir"
    RMDIR = "rmdir"
    ARCHIVE = "archive"
    EXTRACT = "extract"
    HASH = "hash"


class ReadRequest(BaseModel):
    path: str
    encoding: str = "utf-8"
    binary: bool = False
    start_line: Optional[int] = None
    end_line: Optional[int] = None


class WriteRequest(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"
    create_dirs: bool = True
    overwrite: bool = True


class AppendRequest(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"
    create_if_missing: bool = True


class CopyMoveRequest(BaseModel):
    source: str
    destination: str
    overwrite: bool = False


class DeleteRequest(BaseModel):
    path: str
    recursive: bool = False


class ListRequest(BaseModel):
    path: str
    pattern: Optional[str] = None
    recursive: bool = False
    include_hidden: bool = False


class SearchRequest(BaseModel):
    root_path: str
    pattern: str
    content_pattern: Optional[str] = None
    max_results: int = 100
    recursive: bool = True


class ArchiveRequest(BaseModel):
    source_paths: List[str]
    output_path: str
    format: str = "zip"  # zip, tar, tar.gz


class ExtractRequest(BaseModel):
    archive_path: str
    output_dir: str


class HashRequest(BaseModel):
    path: str
    algorithm: str = "sha256"  # md5, sha1, sha256, sha512


@dataclass
class FileInfo:
    path: str
    name: str
    size: int
    is_file: bool
    is_dir: bool
    created: str
    modified: str
    accessed: str
    permissions: str
    mime_type: Optional[str]
    extension: Optional[str]


# =============================================================================
# File Operations Service
# =============================================================================

class FileService:
    """Core file operations service."""
    
    def __init__(self, workspace_root: str = WORKSPACE_ROOT):
        self.workspace_root = Path(workspace_root)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        logger.info(f"FileService initialized with workspace: {self.workspace_root}")
    
    def _resolve_path(self, path: str) -> Path:
        """Resolve and validate path within workspace.

        Returns the **resolved** path — the same value that was validated.

        此前这里校验的是 ``p.resolve()``,返回的却是未解析的 ``p``:检查一个值、
        用另一个值。包含性判定本身是对的(``resolve()`` 会把 ``..`` 与符号链接
        都摊平),但把没摊平的那个交出去,等于让下游 19 个调用点各自再解析一次 ——
        下游任何一处解析方式不同,校验就白做了。

        改成"校验哪个就返回哪个"。规范化后的绝对路径也让各接口回给用户的 path
        字段口径一致。

        .. note::
           **仍未堵上的一处**:``realpath`` 与下游真正 ``open()`` 之间存在
           TOCTOU 窗口 —— 两者之间被换掉符号链接仍可逃逸。彻底堵它要走
           ``openat`` + ``O_NOFOLLOW`` 一类的文件描述符方案,不在本函数能解决的
           范围内。这里如实记下来,不假装它不存在。
        """
        # 规范化 → 判定 → 返回同一个值,三步都在这里,下游拿到的就是被判定过的那个。
        #
        # 用 os.path.realpath + os.path.commonpath 而不是 Path.resolve +
        # Path.relative_to:两者安全语义等价(都把 .. 与符号链接摊平后比较祖先),
        # 但前者是 CodeQL 的 py/path-injection 认得的净化形态。换写法之前这里
        # 报过 13 条污点路径 —— 而被报的恰恰是**做净化的那一行**。
        root = os.path.realpath(self.workspace_root)
        # 注意 os.path.join 的语义:path 是绝对路径时它直接取 path。
        # 这正是我们要的 —— 允许绝对路径,但它同样要过下面这道包含性判定。
        candidate = os.path.realpath(os.path.join(root, path))

        try:
            inside = os.path.commonpath([root, candidate]) == root
        except ValueError:
            # Windows 上跨盘符时 commonpath 会抛 —— 跨盘符本来就在工作区外。
            inside = False
        if not inside:
            raise ValueError(f"Path '{path}' is outside the workspace. Access denied.")

        return Path(candidate)
    
    async def read_file(self, request: ReadRequest) -> Dict[str, Any]:
        """Read file content."""
        path = self._resolve_path(request.path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")
        
        try:
            if request.binary:
                import base64
                content = path.read_bytes()
                return {
                    "success": True,
                    "path": str(path),
                    "content": base64.b64encode(content).decode('ascii'),
                    "encoding": "base64",
                    "size": len(content)
                }
            else:
                lines = path.read_text(encoding=request.encoding).splitlines()
                
                if request.start_line is not None or request.end_line is not None:
                    start = (request.start_line or 1) - 1
                    end = request.end_line or len(lines)
                    lines = lines[start:end]
                
                content = '\n'.join(lines)
                return {
                    "success": True,
                    "path": str(path),
                    "content": content,
                    "encoding": request.encoding,
                    "lines": len(lines),
                    "size": len(content)
                }
        except Exception as e:
            logger.error(f"Read error: {e}")
            raise
    
    async def write_file(self, request: WriteRequest) -> Dict[str, Any]:
        """Write content to file."""
        path = self._resolve_path(request.path)
        
        if path.exists() and not request.overwrite:
            raise FileExistsError(f"File exists: {path}")
        
        if request.create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            path.write_text(request.content, encoding=request.encoding)
            return {
                "success": True,
                "path": str(path),
                "size": len(request.content),
                "created": not path.exists()
            }
        except Exception as e:
            logger.error(f"Write error: {e}")
            raise
    
    async def append_file(self, request: AppendRequest) -> Dict[str, Any]:
        """Append content to file."""
        path = self._resolve_path(request.path)
        
        if not path.exists():
            if request.create_if_missing:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            else:
                raise FileNotFoundError(f"File not found: {path}")
        
        try:
            with open(path, 'a', encoding=request.encoding) as f:
                f.write(request.content)
            
            return {
                "success": True,
                "path": str(path),
                "appended_size": len(request.content),
                "total_size": path.stat().st_size
            }
        except Exception as e:
            logger.error(f"Append error: {e}")
            raise
    
    async def delete(self, request: DeleteRequest) -> Dict[str, Any]:
        """Delete file or directory."""
        path = self._resolve_path(request.path)
        
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                if request.recursive:
                    shutil.rmtree(path)
                else:
                    path.rmdir()
            
            return {
                "success": True,
                "path": str(path),
                "deleted": True
            }
        except Exception as e:
            logger.error(f"Delete error: {e}")
            raise
    
    async def copy(self, request: CopyMoveRequest) -> Dict[str, Any]:
        """Copy file or directory."""
        src = self._resolve_path(request.source)
        dst = self._resolve_path(request.destination)
        
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        
        if dst.exists() and not request.overwrite:
            raise FileExistsError(f"Destination exists: {dst}")
        
        try:
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            else:
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            
            return {
                "success": True,
                "source": str(src),
                "destination": str(dst)
            }
        except Exception as e:
            logger.error(f"Copy error: {e}")
            raise
    
    async def move(self, request: CopyMoveRequest) -> Dict[str, Any]:
        """Move file or directory."""
        src = self._resolve_path(request.source)
        dst = self._resolve_path(request.destination)
        
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        
        if dst.exists() and not request.overwrite:
            raise FileExistsError(f"Destination exists: {dst}")
        
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            
            return {
                "success": True,
                "source": str(src),
                "destination": str(dst)
            }
        except Exception as e:
            logger.error(f"Move error: {e}")
            raise
    
    async def list_directory(self, request: ListRequest) -> Dict[str, Any]:
        """List directory contents."""
        path = self._resolve_path(request.path)
        
        if not path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        
        if not path.is_dir():
            raise ValueError(f"Not a directory: {path}")
        
        try:
            items = []
            
            if request.recursive:
                iterator = path.rglob(request.pattern or '*')
            else:
                iterator = path.glob(request.pattern or '*')
            
            for item in iterator:
                if not request.include_hidden and item.name.startswith('.'):
                    continue
                
                info = await self.get_file_info(str(item))
                items.append(info)
            
            return {
                "success": True,
                "path": str(path),
                "count": len(items),
                "items": items
            }
        except Exception as e:
            logger.error(f"List error: {e}")
            raise
    
    async def search(self, request: SearchRequest) -> Dict[str, Any]:
        """Search for files."""
        root = self._resolve_path(request.root_path)
        
        if not root.exists():
            raise FileNotFoundError(f"Root path not found: {root}")
        
        try:
            results = []
            
            # 用户那边的目录随时在变。裸 rglob 撞上并发删除会抛 FileNotFoundError,
            # 而上面几行"根路径不存在"抛的是同一个异常类型 —— 用户根本分不清是自己
            # 路径写错了,还是扫到一半撞上了并发改动。这里让扫描活下来。
            # include_dirs=True 保持与原 rglob/glob 等价：本节点的搜索结果里
            # 目录也是合法条目（get_file_info 会报 is_dir）。
            iterator = iter_tree_files(
                root, request.pattern, recursive=request.recursive, include_dirs=True
            )
            
            for item in iterator:
                if len(results) >= request.max_results:
                    break
                
                # Content search if specified
                if request.content_pattern and item.is_file():
                    try:
                        content = item.read_text(errors='ignore')
                        if request.content_pattern not in content:
                            continue
                    except OSError:
                        continue
                
                info = await self.get_file_info(str(item))
                results.append(info)
            
            return {
                "success": True,
                "root": str(root),
                "pattern": request.pattern,
                "count": len(results),
                "results": results
            }
        except Exception as e:
            logger.error(f"Search error: {e}")
            raise
    
    async def get_file_info(self, path: str) -> Dict[str, Any]:
        """Get file information."""
        p = self._resolve_path(path)
        
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {p}")
        
        stat = p.stat()
        
        info = FileInfo(
            path=str(p),
            name=p.name,
            size=stat.st_size,
            is_file=p.is_file(),
            is_dir=p.is_dir(),
            created=datetime.fromtimestamp(stat.st_ctime).isoformat(),
            modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            accessed=datetime.fromtimestamp(stat.st_atime).isoformat(),
            permissions=oct(stat.st_mode)[-3:],
            mime_type=mimetypes.guess_type(str(p))[0] if p.is_file() else None,
            extension=p.suffix if p.is_file() else None
        )
        
        return asdict(info)
    
    async def create_archive(self, request: ArchiveRequest) -> Dict[str, Any]:
        """Create archive from files."""
        output = self._resolve_path(request.output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            if request.format == 'zip':
                with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for src_path in request.source_paths:
                        src = self._resolve_path(src_path)
                        if src.is_file():
                            zf.write(src, src.name)
                        elif src.is_dir():
                            for item in src.rglob('*'):
                                if item.is_file():
                                    zf.write(item, item.relative_to(src.parent))
            
            elif request.format in ('tar', 'tar.gz'):
                mode = 'w:gz' if request.format == 'tar.gz' else 'w'
                with tarfile.open(output, mode) as tf:
                    for src_path in request.source_paths:
                        src = self._resolve_path(src_path)
                        tf.add(src, arcname=src.name)
            
            else:
                raise ValueError(f"Unsupported format: {request.format}")
            
            return {
                "success": True,
                "output": str(output),
                "format": request.format,
                "size": output.stat().st_size
            }
        except Exception as e:
            logger.error(f"Archive error: {e}")
            raise
    
    async def extract_archive(self, request: ExtractRequest) -> Dict[str, Any]:
        """Extract archive."""
        archive = self._resolve_path(request.archive_path)
        output_dir = self._resolve_path(request.output_dir)
        
        if not archive.exists():
            raise FileNotFoundError(f"Archive not found: {archive}")
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            extracted = []
            
            # 归档成员必须逐个核验落点,不能直接 extractall。
            # 归档里的成员名完全由归档作者控制,可以是 "../../etc/x" 或绝对路径
            # (Zip Slip / Tar Slip);tarfile 还能带符号链接/硬链接成员,指到
            # 沙箱外之后再往里写。裸 extractall 会照单全收,直接绕过本节点赖以
            # 立身的 WORKSPACE_ROOT 沙箱(_safe_path 只校验了 archive/output_dir
            # 这两个入参,管不到归档【内部】的成员名)。
            # 用 os.path.realpath + 前缀比对(而不是 pathlib 的 parents 判断):
            # 二者语义等价,但这是静态分析器(CodeQL py/path-injection)能识别的
            # 标准消毒形态 —— 用 parents 判断会被判成"未消毒的路径拼接"。
            _root_real = os.path.realpath(str(output_dir))
            _root_prefix = _root_real + os.sep

            def _is_inside(member_name: str) -> bool:
                """成员解析后的落点是否仍在 output_dir 内。

                realpath 会一并展开 ``..`` 与符号链接,故绝对路径成员、``../``
                穿越、以及经由已存在符号链接的逃逸都会在这里被判出界。
                """
                target = os.path.realpath(os.path.join(_root_real, member_name))
                return target == _root_real or target.startswith(_root_prefix)

            if archive.suffix == '.zip':
                with zipfile.ZipFile(archive, 'r') as zf:
                    names = zf.namelist()
                    bad = [n for n in names if not _is_inside(n)]
                    if bad:
                        raise ValueError(
                            f"归档包含越界成员(疑似路径穿越),已拒绝解压: {bad[:5]}"
                        )
                    zf.extractall(output_dir)
                    extracted = names

            elif archive.suffix in ('.tar', '.gz', '.tgz'):
                with tarfile.open(archive, 'r:*') as tf:
                    members = tf.getmembers()
                    bad = []
                    for m in members:
                        if not _is_inside(m.name):
                            bad.append(m.name)
                        elif (m.issym() or m.islnk()) and not _is_inside(
                            os.path.join(os.path.dirname(m.name), m.linkname)
                        ):
                            # 链接目标指到沙箱外 → 后续写入会顺着链接逃逸
                            bad.append(f"{m.name} -> {m.linkname}")
                    if bad:
                        raise ValueError(
                            f"归档包含越界成员(疑似路径穿越),已拒绝解压: {bad[:5]}"
                        )
                    # filter='data' 是 Python 官方推荐的安全过滤器(3.12+ 默认,
                    # 3.14 起强制);这里显式传,低版本同样生效,与上面的显式
                    # 核验互为双保险。旧版本不认该参数时退回已核验的 extractall。
                    try:
                        tf.extractall(output_dir, filter='data')
                    except TypeError:
                        tf.extractall(output_dir)
                    extracted = [m.name for m in members]
            
            else:
                raise ValueError(f"Unsupported archive format: {archive.suffix}")
            
            return {
                "success": True,
                "archive": str(archive),
                "output_dir": str(output_dir),
                "extracted_count": len(extracted),
                "files": extracted[:100]  # Limit output
            }
        except Exception as e:
            logger.error(f"Extract error: {e}")
            raise
    
    async def calculate_hash(self, request: HashRequest) -> Dict[str, Any]:
        """Calculate file hash."""
        path = self._resolve_path(request.path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        if not path.is_file():
            raise ValueError(f"Not a file: {path}")
        
        algorithms = {
            'md5': hashlib.md5,
            'sha1': hashlib.sha1,
            'sha256': hashlib.sha256,
            'sha512': hashlib.sha512
        }
        
        if request.algorithm not in algorithms:
            raise ValueError(f"Unsupported algorithm: {request.algorithm}")
        
        try:
            hasher = algorithms[request.algorithm]()
            
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hasher.update(chunk)
            
            return {
                "success": True,
                "path": str(path),
                "algorithm": request.algorithm,
                "hash": hasher.hexdigest()
            }
        except Exception as e:
            logger.error(f"Hash error: {e}")
            raise


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title=f"Node {NODE_ID}: {NODE_NAME}",
    description="File operations service for Galaxy",
    version="5.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

file_service = FileService()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "node_id": NODE_ID,
        "node_name": NODE_NAME,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/read")
async def read_file(request: ReadRequest):
    """Read file content."""
    try:
        return await file_service.read_file(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/write")
async def write_file(request: WriteRequest):
    """Write content to file."""
    try:
        return await file_service.write_file(request)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/append")
async def append_file(request: AppendRequest):
    """Append content to file."""
    try:
        return await file_service.append_file(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/delete")
async def delete_path(request: DeleteRequest):
    """Delete file or directory."""
    try:
        return await file_service.delete(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/copy")
async def copy_path(request: CopyMoveRequest):
    """Copy file or directory."""
    try:
        return await file_service.copy(request)
    except (FileNotFoundError, FileExistsError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/move")
async def move_path(request: CopyMoveRequest):
    """Move file or directory."""
    try:
        return await file_service.move(request)
    except (FileNotFoundError, FileExistsError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/list")
async def list_directory(request: ListRequest):
    """List directory contents."""
    try:
        return await file_service.list_directory(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search")
async def search_files(request: SearchRequest):
    """Search for files."""
    try:
        return await file_service.search(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/info")
async def get_info(path: str):
    """Get file information."""
    try:
        return await file_service.get_file_info(path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/archive")
async def create_archive(request: ArchiveRequest):
    """Create archive."""
    try:
        return await file_service.create_archive(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/extract")
async def extract_archive(request: ExtractRequest):
    """Extract archive."""
    try:
        return await file_service.extract_archive(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/hash")
async def calculate_hash(request: HashRequest):
    """Calculate file hash."""
    try:
        return await file_service.calculate_hash(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download")
async def download_file(path: str):
    """Download file."""
    try:
        p = file_service._resolve_path(path)
        if not p.exists() or not p.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(p, filename=p.name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    logger.info(f"Starting Node {NODE_ID}: {NODE_NAME} on port {NODE_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=NODE_PORT)
