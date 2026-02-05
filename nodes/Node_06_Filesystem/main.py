"""
Node 06: Filesystem - 文件系统操作
====================================
提供文件读写、目录管理、文件搜索、压缩解压功能
"""
import os
import io
import json
import shutil
import zipfile
import tarfile
import hashlib
import mimetypes
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Node 06 - Filesystem", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# 基础目录（从环境变量读取）
BASE_DIR = os.getenv("FILESYSTEM_BASE_DIR", "/tmp/filesystem")
os.makedirs(BASE_DIR, exist_ok=True)

class FileInfo(BaseModel):
    name: str
    path: str
    type: str  # file, directory
    size: int
    modified_at: datetime
    created_at: datetime
    mime_type: Optional[str] = None
    permissions: str

class FilesystemManager:
    def __init__(self):
        self.base_dir = Path(BASE_DIR).resolve()
        self.allowed_extensions = os.getenv("FILESYSTEM_ALLOWED_EXTENSIONS", "*").split(",")
        self.max_file_size = int(os.getenv("FILESYSTEM_MAX_FILE_SIZE", "104857600"))  # 100MB

    def _resolve_path(self, path: str) -> Path:
        """解析并验证路径"""
        # 移除开头的斜杠
        path = path.lstrip("/")
        full_path = (self.base_dir / path).resolve()

        # 安全检查：确保路径在基础目录内
        if not str(full_path).startswith(str(self.base_dir)):
            raise HTTPException(status_code=403, detail="Access denied: path outside base directory")

        return full_path

    def _get_file_info(self, path: Path) -> FileInfo:
        """获取文件信息"""
        stat = path.stat()
        mime_type, _ = mimetypes.guess_type(str(path))

        return FileInfo(
            name=path.name,
            path=str(path.relative_to(self.base_dir)),
            type="directory" if path.is_dir() else "file",
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime),
            created_at=datetime.fromtimestamp(stat.st_ctime),
            mime_type=mime_type,
            permissions=oct(stat.st_mode)[-3:]
        )

    def list_directory(self, path: str = "") -> List[FileInfo]:
        """列出目录内容"""
        full_path = self._resolve_path(path)

        if not full_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        if not full_path.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        items = []
        for item in full_path.iterdir():
            try:
                items.append(self._get_file_info(item))
            except Exception:
                pass

        return sorted(items, key=lambda x: (x.type != "directory", x.name.lower()))

    def read_file(self, path: str) -> bytes:
        """读取文件"""
        full_path = self._resolve_path(path)

        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        if full_path.is_dir():
            raise HTTPException(status_code=400, detail="Path is a directory")

        with open(full_path, 'rb') as f:
            return f.read()

    def write_file(self, path: str, content: bytes, append: bool = False) -> FileInfo:
        """写入文件"""
        full_path = self._resolve_path(path)

        # 检查文件大小限制
        if len(content) > self.max_file_size:
            raise HTTPException(status_code=413, detail=f"File too large, max size: {self.max_file_size} bytes")

        # 创建父目录
        full_path.parent.mkdir(parents=True, exist_ok=True)

        mode = 'ab' if append else 'wb'
        with open(full_path, mode) as f:
            f.write(content)

        return self._get_file_info(full_path)

    def delete_file(self, path: str) -> bool:
        """删除文件或目录"""
        full_path = self._resolve_path(path)

        if not full_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")

        if full_path.is_dir():
            shutil.rmtree(full_path)
        else:
            full_path.unlink()

        return True

    def create_directory(self, path: str) -> FileInfo:
        """创建目录"""
        full_path = self._resolve_path(path)
        full_path.mkdir(parents=True, exist_ok=True)
        return self._get_file_info(full_path)

    def move_file(self, source: str, destination: str) -> FileInfo:
        """移动/重命名文件"""
        src_path = self._resolve_path(source)
        dst_path = self._resolve_path(destination)

        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Source not found")

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))

        return self._get_file_info(dst_path)

    def copy_file(self, source: str, destination: str) -> FileInfo:
        """复制文件"""
        src_path = self._resolve_path(source)
        dst_path = self._resolve_path(destination)

        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Source not found")

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_dir():
            shutil.copytree(str(src_path), str(dst_path))
        else:
            shutil.copy2(str(src_path), str(dst_path))

        return self._get_file_info(dst_path)

    def search_files(self, pattern: str, path: str = "") -> List[FileInfo]:
        """搜索文件"""
        full_path = self._resolve_path(path)
        results = []

        for item in full_path.rglob(f"*{pattern}*"):
            try:
                results.append(self._get_file_info(item))
            except Exception:
                pass

        return results

    def get_file_hash(self, path: str, algorithm: str = "sha256") -> str:
        """计算文件哈希"""
        full_path = self._resolve_path(path)

        if not full_path.exists() or full_path.is_dir():
            raise HTTPException(status_code=400, detail="Invalid file path")

        hash_obj = hashlib.new(algorithm)
        with open(full_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_obj.update(chunk)

        return hash_obj.hexdigest()

    def compress_files(self, paths: List[str], output_path: str, format: str = "zip") -> FileInfo:
        """压缩文件"""
        output_full_path = self._resolve_path(output_path)
        output_full_path.parent.mkdir(parents=True, exist_ok=True)

        if format == "zip":
            with zipfile.ZipFile(output_full_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for path in paths:
                    full_path = self._resolve_path(path)
                    if full_path.is_dir():
                        for file_path in full_path.rglob("*"):
                            if file_path.is_file():
                                zf.write(file_path, file_path.relative_to(self.base_dir))
                    else:
                        zf.write(full_path, full_path.relative_to(self.base_dir))
        elif format == "tar.gz":
            with tarfile.open(output_full_path, "w:gz") as tf:
                for path in paths:
                    full_path = self._resolve_path(path)
                    tf.add(full_path, full_path.relative_to(self.base_dir))
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

        return self._get_file_info(output_full_path)

    def extract_archive(self, archive_path: str, output_path: str = "") -> FileInfo:
        """解压文件"""
        archive_full_path = self._resolve_path(archive_path)
        output_full_path = self._resolve_path(output_path) if output_path else archive_full_path.parent

        if not archive_full_path.exists():
            raise HTTPException(status_code=404, detail="Archive not found")

        if zipfile.is_zipfile(archive_full_path):
            with zipfile.ZipFile(archive_full_path, 'r') as zf:
                zf.extractall(output_full_path)
        elif tarfile.is_tarfile(archive_full_path):
            with tarfile.open(archive_full_path, "r:*") as tf:
                tf.extractall(output_full_path)
        else:
            raise HTTPException(status_code=400, detail="Unknown archive format")

        return self._get_file_info(output_full_path)

# 全局文件系统管理器
fs_manager = FilesystemManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "06",
        "name": "Filesystem",
        "base_dir": str(fs_manager.base_dir),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/list")
async def list_directory(path: str = ""):
    """列出目录内容"""
    return fs_manager.list_directory(path)

@app.get("/read/{path:path}")
async def read_file(path: str):
    """读取文件"""
    content = fs_manager.read_file(path)
    mime_type, _ = mimetypes.guess_type(path)

    if mime_type and mime_type.startswith("text/"):
        return {"content": content.decode('utf-8', errors='ignore')}

    return StreamingResponse(io.BytesIO(content), media_type=mime_type or "application/octet-stream")

class WriteFileRequest(BaseModel):
    path: str
    content: str
    append: bool = False

@app.post("/write")
async def write_file(request: WriteFileRequest):
    """写入文件"""
    return fs_manager.write_file(request.path, request.content.encode(), request.append)

@app.post("/upload")
async def upload_file(path: str = "", file: UploadFile = File(...)):
    """上传文件"""
    content = await file.read()
    file_path = os.path.join(path, file.filename) if path else file.filename
    return fs_manager.write_file(file_path, content)

@app.delete("/delete/{path:path}")
async def delete_file(path: str):
    """删除文件或目录"""
    return {"success": fs_manager.delete_file(path)}

@app.post("/mkdir")
async def create_directory(path: str):
    """创建目录"""
    return fs_manager.create_directory(path)

class MoveRequest(BaseModel):
    source: str
    destination: str

@app.post("/move")
async def move_file(request: MoveRequest):
    """移动/重命名文件"""
    return fs_manager.move_file(request.source, request.destination)

@app.post("/copy")
async def copy_file(request: MoveRequest):
    """复制文件"""
    return fs_manager.copy_file(request.source, request.destination)

@app.get("/search")
async def search_files(pattern: str, path: str = ""):
    """搜索文件"""
    return fs_manager.search_files(pattern, path)

@app.get("/hash/{path:path}")
async def get_file_hash(path: str, algorithm: str = "sha256"):
    """获取文件哈希"""
    return {"hash": fs_manager.get_file_hash(path, algorithm)}

class CompressRequest(BaseModel):
    paths: List[str]
    output_path: str
    format: str = "zip"

@app.post("/compress")
async def compress_files(request: CompressRequest):
    """压缩文件"""
    return fs_manager.compress_files(request.paths, request.output_path, request.format)

@app.post("/extract")
async def extract_archive(archive_path: str, output_path: str = ""):
    """解压文件"""
    return fs_manager.extract_archive(archive_path, output_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006)
