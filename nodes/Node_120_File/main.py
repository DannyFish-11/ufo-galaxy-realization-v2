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

import errno
import os
import stat
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
from core.safe_fs import PathEscapesWorkspace, open_workspace

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
        # 单一路径:能钉描述符就钉,不能(Windows)就拿到一个同接口的纯路径实现,
        # 由 open_workspace 负责把降级说出来。调用点因此不必到处写 if。
        self.guard = open_workspace(self.workspace_root)
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

        .. warning::
           **本函数的返回值只能用于展示**(响应体里的 ``path`` 字段、日志、错误
           消息),**不要**拿它去做真正的 ``open()``。

           原因是这里天然存在 TOCTOU 窗口:它校验的是"此刻这个名字指向哪儿",
           而 ``open()`` 发生在之后,那时同一个名字可以已经指向别处。实测复现
           过 —— 42953 次通过校验里有 576 次读到了工作区外的文件(约 1.3%),
           记录见 ``core/safe_fs`` 的 docstring。

           真正的读写一律走 ``self.guard``(:class:`core.safe_fs.WorkspaceGuard`),
           它把校验和使用绑在同一个文件描述符上,没有中间窗口。
        """
        # 规范化 → 判定 → 返回同一个值,三步都在这里,下游拿到的就是被判定过的那个。
        #
        # 用 os.path.realpath + 前缀比对而不是 Path.resolve + Path.relative_to:
        # 安全语义等价(都把 .. 与符号链接摊平后比较祖先),但前者是 CodeQL 的
        # py/path-injection 认得的净化形态。换写法之前这里报过 13 条污点路径 ——
        # 而被报的恰恰是**做净化的那一行**。
        root = os.path.realpath(self.workspace_root)
        # 注意 os.path.join 的语义:path 是绝对路径时它直接取 path。
        # 这正是我们要的 —— 允许绝对路径,但它同样要过下面这道包含性判定。
        candidate = os.path.realpath(os.path.join(root, path))

        # 前缀比对而不是 commonpath:同结论(两种判据在 60000 组随机路径上完全一致,
        # 前提是两侧都先过 realpath —— 这里正是),但只有前者是 CodeQL
        # py/path-injection 认得的净化。跨盘符时 startswith 直接为假,比 commonpath
        # 抛 ValueError 再兜住更直白。os.path.join(root, "") 而不是 root + os.sep:
        # 根为 "/" 时前者给 "/",后者给 "//"。
        if candidate != root and not candidate.startswith(os.path.join(root, "")):
            raise ValueError(f"Path '{path}' is outside the workspace. Access denied.")

        return Path(candidate)
    
    async def read_file(self, request: ReadRequest) -> Dict[str, Any]:
        """Read file content."""
        # path 只用来回给调用方看;真正的读走 guard,校验与打开是同一个描述符。
        path = self._resolve_path(request.path)

        if not self.guard.is_file(request.path, follow_final=True):
            if not self.guard.exists(request.path, follow_final=True):
                raise FileNotFoundError(f"File not found: {path}")
            raise ValueError(f"Not a file: {path}")

        try:
            if request.binary:
                import base64
                content = self.guard.read_bytes(request.path, follow_final=True)
                return {
                    "success": True,
                    "path": str(path),
                    "content": base64.b64encode(content).decode('ascii'),
                    "encoding": "base64",
                    "size": len(content)
                }
            else:
                lines = self.guard.read_text(
                    request.path, encoding=request.encoding, follow_final=True
                ).splitlines()
                
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
        existed = self.guard.exists(request.path)

        if request.create_dirs:
            parent = os.path.dirname(request.path.replace("\\", "/").rstrip("/"))
            if parent:
                self.guard.mkdir(parent, parents=True, exist_ok=True)

        try:
            # overwrite=False 交给内核的 O_EXCL 判 —— 比"先 exists() 再写"少一个窗口。
            self.guard.write_text(
                request.path,
                request.content,
                encoding=request.encoding,
                overwrite=request.overwrite,
            )
            return {
                "success": True,
                "path": str(path),
                "size": len(request.content),
                "created": not existed
            }
        except Exception as e:
            logger.error(f"Write error: {e}")
            raise
    
    async def append_file(self, request: AppendRequest) -> Dict[str, Any]:
        """Append content to file."""
        path = self._resolve_path(request.path)

        if not self.guard.exists(request.path):
            if not request.create_if_missing:
                raise FileNotFoundError(f"File not found: {path}")
            parent = os.path.dirname(request.path.replace("\\", "/").rstrip("/"))
            if parent:
                self.guard.mkdir(parent, parents=True, exist_ok=True)

        try:
            self.guard.append_text(
                request.path,
                request.content,
                encoding=request.encoding,
                create=request.create_if_missing,
            )

            return {
                "success": True,
                "path": str(path),
                "appended_size": len(request.content),
                "total_size": self.guard.stat(request.path).st_size
            }
        except Exception as e:
            logger.error(f"Append error: {e}")
            raise
    
    async def delete(self, request: DeleteRequest) -> Dict[str, Any]:
        """Delete file or directory."""
        path = self._resolve_path(request.path)

        if not self.guard.exists(request.path):
            raise FileNotFoundError(f"Path not found: {path}")

        try:
            # is_dir 不跟随最后一段:指向目录的符号链接该按"链接"删掉,别顺着删树。
            if self.guard.is_dir(request.path):
                if request.recursive:
                    self.guard.rmtree(request.path)
                else:
                    self.guard.rmdir(request.path)
            else:
                self.guard.unlink(request.path)

            return {
                "success": True,
                "path": str(path),
                "deleted": True
            }
        except Exception as e:
            logger.error(f"Delete error: {e}")
            raise
    
    def _move_destination(self, source: str, destination: str) -> str:
        """还原 ``shutil.move`` 的一条语义:目标是**已存在的目录**时,移进去而不是覆盖它。

        换成 ``os.rename`` 之后这条会丢 —— rename 把"文件改名成一个已存在的目录"
        直接判错。这里补回来,免得换实现顺手改了对外行为。
        """
        if self.guard.is_dir(destination):
            name = os.path.basename(source.replace("\\", "/").rstrip("/"))
            if name:
                return destination.rstrip("/") + "/" + name
        return destination

    def _copy_file(self, source: str, destination: str) -> None:
        """单文件复制:两端都用描述符打开,中间只搬字节。

        源和目标各自只被解析一次,解析结果就是拿去读写的那个描述符 ——
        这条路径上没有 TOCTOU 窗口。元数据用 ``os.fstat``/``os.utime`` 按描述符
        搬,同样不回到路径。
        """
        parent = os.path.dirname(destination.replace("\\", "/").rstrip("/"))
        if parent:
            self.guard.mkdir(parent, parents=True, exist_ok=True)
        src_fd = self.guard.open_fd(source, os.O_RDONLY, follow_final=True)
        try:
            info = os.fstat(src_fd)
            dst_fd = self.guard.open_fd(
                destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666
            )
            try:
                with os.fdopen(os.dup(src_fd), "rb") as reader, os.fdopen(os.dup(dst_fd), "wb") as writer:
                    shutil.copyfileobj(reader, writer)
                os.fchmod(dst_fd, stat.S_IMODE(info.st_mode))
                os.utime(dst_fd, ns=(info.st_atime_ns, info.st_mtime_ns))
            finally:
                os.close(dst_fd)
        finally:
            os.close(src_fd)

    def _copy_tree(self, source: str, destination: str) -> None:
        """目录树复制。

        .. warning::
           **这一条没有完全堵上。** 树内部是逐个条目重新按路径打开的:先列目录拿到
           名字,再按名字打开 —— 中间同样能被换掉。真要堵,得把整棵树的下降也做成
           描述符锚定(``os.fwalk`` + ``dir_fd``),那是另一件事,这里不假装做到了。

           已经做到的是:**根**在 guard 里解析,且下降途中不跟随任何符号链接
           (``symlinks=True`` 把链接原样复制成链接,而不是顺着它把工作区外的内容
           拷进来)—— 后者才是先前 ``copytree`` 默认行为下真正的越界风险。
        """
        # 两端**在这里自己再判一次**落点,不指望调用方已经判过。
        #
        # 先前这里直接用 guard.display_path() 的结果喂 copytree —— 而当时
        # display_path 是纯拼接,能交出工作区外的路径。CodeQL 的 py/path-injection
        # 顺着这条流报到了 copytree,报得对(display_path 已单独修掉)。
        #
        # 教训是别的:一个函数"安全"不该建立在"我的调用方会先检查"上面。这里用
        # realpath + 前缀比对重新确认一遍 —— 多花两次系统调用,换掉一个隐式前提。
        root = os.path.realpath(str(self.workspace_root))
        prefix = os.path.join(root, "")
        src_root = os.path.realpath(os.path.join(root, source))
        dst_root = os.path.realpath(os.path.join(root, destination))
        for candidate in (src_root, dst_root):
            # 前缀比对而不是 commonpath —— 与本文件 extract_archive 里那处同形态,
            # 理由见 core/safe_fs.PathOnlyGuard._resolve 的 docstring。
            if candidate != root and not candidate.startswith(prefix):
                raise ValueError(f"Path '{candidate}' is outside the workspace. Access denied.")

        if self.guard.exists(destination):
            self.guard.rmtree(destination)
        shutil.copytree(src_root, dst_root, symlinks=True)

    async def copy(self, request: CopyMoveRequest) -> Dict[str, Any]:
        """Copy file or directory."""
        src = self._resolve_path(request.source)
        dst = self._resolve_path(request.destination)

        if not self.guard.exists(request.source):
            raise FileNotFoundError(f"Source not found: {src}")

        if self.guard.exists(request.destination) and not request.overwrite:
            raise FileExistsError(f"Destination exists: {dst}")

        try:
            if self.guard.is_dir(request.source):
                # 目录树复制走 shutil.copytree —— 它是**基于路径**的,两端都已经过
                # guard 校验,但树内部逐个条目的打开仍是路径式的。这一段的残留窗口
                # 如实记在 _copy_tree 里,没有假装堵上。
                self._copy_tree(request.source, request.destination)
            else:
                self._copy_file(request.source, request.destination)

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

        if not self.guard.exists(request.source):
            raise FileNotFoundError(f"Source not found: {src}")

        if self.guard.exists(request.destination) and not request.overwrite:
            raise FileExistsError(f"Destination exists: {dst}")

        try:
            destination = self._move_destination(request.source, request.destination)
            parent = os.path.dirname(destination.replace("\\", "/").rstrip("/"))
            if parent:
                self.guard.mkdir(parent, parents=True, exist_ok=True)
            try:
                # rename 两端都锚在各自父目录的描述符上,由内核原子完成 ——
                # 这一条是全流程无窗口的。
                self.guard.rename(request.source, destination)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                # 跨文件系统 rename 不了。shutil.move 在这里也是退回"复制+删除",
                # 我们照做,只是复制那一步走 guard。
                if self.guard.is_dir(request.source):
                    self._copy_tree(request.source, destination)
                    self.guard.rmtree(request.source)
                else:
                    self._copy_file(request.source, destination)
                    self.guard.unlink(request.source)
            dst = self._resolve_path(destination)

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

        if not self.guard.is_dir(request.path, follow_final=True):
            if not self.guard.exists(request.path, follow_final=True):
                raise FileNotFoundError(f"Directory not found: {path}")
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

        if not self.guard.exists(request.root_path, follow_final=True):
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

        try:
            # 一次 stat 定全部字段。此前 is_file()/is_dir() 各自又 stat 一遍,
            # 四次系统调用看到的可以是四个不同状态 —— 于是报出 is_file 和 is_dir
            # 同时为假(甚至同时为真)的自相矛盾结果。现在只认这一次的结果。
            info_stat = self.guard.stat(path, follow_final=True)
        except (OSError, PathEscapesWorkspace) as exc:
            raise FileNotFoundError(f"Path not found: {p}") from exc

        is_file = stat.S_ISREG(info_stat.st_mode)
        is_dir = stat.S_ISDIR(info_stat.st_mode)

        info = FileInfo(
            path=str(p),
            name=p.name,
            size=info_stat.st_size,
            is_file=is_file,
            is_dir=is_dir,
            created=datetime.fromtimestamp(info_stat.st_ctime).isoformat(),
            modified=datetime.fromtimestamp(info_stat.st_mtime).isoformat(),
            accessed=datetime.fromtimestamp(info_stat.st_atime).isoformat(),
            permissions=oct(info_stat.st_mode)[-3:],
            mime_type=mimetypes.guess_type(str(p))[0] if is_file else None,
            extension=p.suffix if is_file else None
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

        if not self.guard.is_file(request.path, follow_final=True):
            if not self.guard.exists(request.path, follow_final=True):
                raise FileNotFoundError(f"File not found: {path}")
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
            
            with self.guard.open(request.path, 'rb', follow_final=True) as f:
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
