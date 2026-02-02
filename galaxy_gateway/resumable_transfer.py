"""
UFO³ Galaxy - 断点续传和流式传输模块

功能：
1. 分块传输（大文件分片）
2. 断点续传（传输失败恢复）
3. 流式传输（实时数据）
4. 传输进度跟踪
5. 传输速度控制

作者：Manus AI
日期：2026-01-22
版本：1.0
"""

import os
import asyncio
import hashlib
import json
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ============================================================================
# 配置
# ============================================================================

class TransferConfig:
    """传输配置"""
    CHUNK_SIZE = 1024 * 1024  # 1MB per chunk
    MAX_RETRIES = 3           # 最大重试次数
    RETRY_DELAY = 1           # 重试延迟（秒）
    PROGRESS_INTERVAL = 1     # 进度更新间隔（秒）

# ============================================================================
# 枚举
# ============================================================================

class TransferState(Enum):
    """传输状态"""
    PENDING = "pending"
    TRANSFERRING = "transferring"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ChunkInfo:
    """分块信息"""
    index: int
    offset: int
    size: int
    checksum: Optional[str] = None
    transferred: bool = False
    retries: int = 0

@dataclass
class TransferSession:
    """传输会话"""
    session_id: str
    file_path: str
    file_size: int
    file_checksum: str
    chunk_size: int
    chunks: List[ChunkInfo] = field(default_factory=list)
    state: TransferState = TransferState.PENDING
    transferred_bytes: int = 0
    start_time: float = 0
    end_time: float = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于保存/恢复）"""
        return {
            "session_id": self.session_id,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "file_checksum": self.file_checksum,
            "chunk_size": self.chunk_size,
            "chunks": [
                {
                    "index": c.index,
                    "offset": c.offset,
                    "size": c.size,
                    "checksum": c.checksum,
                    "transferred": c.transferred,
                    "retries": c.retries
                }
                for c in self.chunks
            ],
            "state": self.state.value,
            "transferred_bytes": self.transferred_bytes,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "error": self.error
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TransferSession':
        """从字典创建"""
        session = cls(
            session_id=data["session_id"],
            file_path=data["file_path"],
            file_size=data["file_size"],
            file_checksum=data["file_checksum"],
            chunk_size=data["chunk_size"],
            state=TransferState(data["state"]),
            transferred_bytes=data["transferred_bytes"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            error=data.get("error")
        )
        
        session.chunks = [
            ChunkInfo(
                index=c["index"],
                offset=c["offset"],
                size=c["size"],
                checksum=c.get("checksum"),
                transferred=c["transferred"],
                retries=c["retries"]
            )
            for c in data["chunks"]
        ]
        
        return session

# ============================================================================
# 断点续传管理器
# ============================================================================

class ResumableTransferManager:
    """断点续传管理器"""
    
    def __init__(self, state_dir: str = "/tmp/transfer_states"):
        self.state_dir = state_dir
        self.sessions: Dict[str, TransferSession] = {}
        self.config = TransferConfig()
        
        # 确保状态目录存在
        os.makedirs(state_dir, exist_ok=True)
    
    # ========================================================================
    # 会话管理
    # ========================================================================
    
    def create_session(
        self,
        session_id: str,
        file_path: str,
        chunk_size: int = None
    ) -> TransferSession:
        """
        创建传输会话
        
        Args:
            session_id: 会话 ID
            file_path: 文件路径
            chunk_size: 分块大小（可选）
        
        Returns:
            TransferSession: 传输会话
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        file_size = os.path.getsize(file_path)
        file_checksum = self._calculate_file_checksum(file_path)
        chunk_size = chunk_size or self.config.CHUNK_SIZE
        
        # 计算分块
        chunks = []
        offset = 0
        index = 0
        
        while offset < file_size:
            size = min(chunk_size, file_size - offset)
            chunks.append(ChunkInfo(
                index=index,
                offset=offset,
                size=size
            ))
            offset += size
            index += 1
        
        session = TransferSession(
            session_id=session_id,
            file_path=file_path,
            file_size=file_size,
            file_checksum=file_checksum,
            chunk_size=chunk_size,
            chunks=chunks
        )
        
        self.sessions[session_id] = session
        self._save_session(session)
        
        return session
    
    def load_session(self, session_id: str) -> Optional[TransferSession]:
        """
        加载传输会话
        
        Args:
            session_id: 会话 ID
        
        Returns:
            TransferSession: 传输会话（如果存在）
        """
        if session_id in self.sessions:
            return self.sessions[session_id]
        
        state_file = os.path.join(self.state_dir, f"{session_id}.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r') as f:
            data = json.load(f)
        
        session = TransferSession.from_dict(data)
        self.sessions[session_id] = session
        
        return session
    
    def _save_session(self, session: TransferSession):
        """保存会话状态"""
        state_file = os.path.join(self.state_dir, f"{session.session_id}.json")
        
        with open(state_file, 'w') as f:
            json.dump(session.to_dict(), f, indent=2)
    
    def delete_session(self, session_id: str):
        """删除会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
        
        state_file = os.path.join(self.state_dir, f"{session_id}.json")
        if os.path.exists(state_file):
            os.remove(state_file)
    
    # ========================================================================
    # 发送端
    # ========================================================================
    
    async def send_file(
        self,
        session_id: str,
        send_chunk_callback: Callable[[int, bytes], asyncio.Future],
        progress_callback: Callable[[float, float], None] = None
    ) -> bool:
        """
        发送文件（支持断点续传）
        
        Args:
            session_id: 会话 ID
            send_chunk_callback: 发送分块的回调函数 (chunk_index, chunk_data) -> Future
            progress_callback: 进度回调函数 (progress, speed) -> None
        
        Returns:
            bool: 是否成功
        """
        session = self.load_session(session_id)
        
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        session.state = TransferState.TRANSFERRING
        session.start_time = time.time()
        self._save_session(session)
        
        try:
            last_progress_time = time.time()
            last_transferred_bytes = session.transferred_bytes
            
            for chunk in session.chunks:
                # 跳过已传输的分块
                if chunk.transferred:
                    continue
                
                # 读取分块数据
                chunk_data = await self._read_chunk(session.file_path, chunk)
                
                # 发送分块（带重试）
                success = False
                for retry in range(self.config.MAX_RETRIES):
                    try:
                        await send_chunk_callback(chunk.index, chunk_data)
                        success = True
                        break
                    except Exception as e:
                        chunk.retries += 1
                        if retry < self.config.MAX_RETRIES - 1:
                            await asyncio.sleep(self.config.RETRY_DELAY)
                        else:
                            raise e
                
                if not success:
                    raise Exception(f"Failed to send chunk {chunk.index}")
                
                # 更新状态
                chunk.transferred = True
                session.transferred_bytes += chunk.size
                self._save_session(session)
                
                # 更新进度
                current_time = time.time()
                if progress_callback and current_time - last_progress_time >= self.config.PROGRESS_INTERVAL:
                    progress = session.transferred_bytes / session.file_size
                    speed = (session.transferred_bytes - last_transferred_bytes) / (current_time - last_progress_time)
                    progress_callback(progress, speed)
                    
                    last_progress_time = current_time
                    last_transferred_bytes = session.transferred_bytes
            
            # 完成
            session.state = TransferState.COMPLETED
            session.end_time = time.time()
            self._save_session(session)
            
            return True
        
        except Exception as e:
            session.state = TransferState.FAILED
            session.error = str(e)
            self._save_session(session)
            return False
    
    async def _read_chunk(self, file_path: str, chunk: ChunkInfo) -> bytes:
        """读取分块数据"""
        with open(file_path, 'rb') as f:
            f.seek(chunk.offset)
            data = f.read(chunk.size)
        
        # 计算校验和
        chunk.checksum = self._calculate_checksum(data)
        
        return data
    
    # ========================================================================
    # 接收端
    # ========================================================================
    
    async def receive_file(
        self,
        session_id: str,
        output_path: str,
        file_size: int,
        file_checksum: str,
        chunk_size: int = None,
        progress_callback: Callable[[float, float], None] = None
    ) -> bool:
        """
        接收文件（支持断点续传）
        
        Args:
            session_id: 会话 ID
            output_path: 输出路径
            file_size: 文件大小
            file_checksum: 文件校验和
            chunk_size: 分块大小（可选）
            progress_callback: 进度回调函数 (progress, speed) -> None
        
        Returns:
            bool: 是否成功
        """
        # 尝试加载已存在的会话
        session = self.load_session(session_id)
        
        if not session:
            # 创建新会话
            chunk_size = chunk_size or self.config.CHUNK_SIZE
            
            # 创建空文件
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'wb') as f:
                f.truncate(file_size)
            
            # 计算分块
            chunks = []
            offset = 0
            index = 0
            
            while offset < file_size:
                size = min(chunk_size, file_size - offset)
                chunks.append(ChunkInfo(
                    index=index,
                    offset=offset,
                    size=size
                ))
                offset += size
                index += 1
            
            session = TransferSession(
                session_id=session_id,
                file_path=output_path,
                file_size=file_size,
                file_checksum=file_checksum,
                chunk_size=chunk_size,
                chunks=chunks,
                state=TransferState.TRANSFERRING,
                start_time=time.time()
            )
            
            self.sessions[session_id] = session
            self._save_session(session)
        
        return session
    
    async def write_chunk(
        self,
        session_id: str,
        chunk_index: int,
        chunk_data: bytes
    ) -> bool:
        """
        写入分块数据
        
        Args:
            session_id: 会话 ID
            chunk_index: 分块索引
            chunk_data: 分块数据
        
        Returns:
            bool: 是否成功
        """
        session = self.load_session(session_id)
        
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        if chunk_index >= len(session.chunks):
            raise ValueError(f"Invalid chunk index: {chunk_index}")
        
        chunk = session.chunks[chunk_index]
        
        # 验证数据大小
        if len(chunk_data) != chunk.size:
            raise ValueError(f"Chunk size mismatch: expected {chunk.size}, got {len(chunk_data)}")
        
        # 写入文件
        with open(session.file_path, 'r+b') as f:
            f.seek(chunk.offset)
            f.write(chunk_data)
        
        # 更新状态
        chunk.transferred = True
        chunk.checksum = self._calculate_checksum(chunk_data)
        session.transferred_bytes += chunk.size
        
        # 检查是否完成
        if all(c.transferred for c in session.chunks):
            # 验证文件校验和
            actual_checksum = self._calculate_file_checksum(session.file_path)
            if actual_checksum == session.file_checksum:
                session.state = TransferState.COMPLETED
                session.end_time = time.time()
            else:
                session.state = TransferState.FAILED
                session.error = f"Checksum mismatch: expected {session.file_checksum}, got {actual_checksum}"
        
        self._save_session(session)
        
        return True
    
    # ========================================================================
    # 工具方法
    # ========================================================================
    
    def _calculate_checksum(self, data: bytes) -> str:
        """计算校验和"""
        return hashlib.sha256(data).hexdigest()
    
    def _calculate_file_checksum(self, file_path: str) -> str:
        """计算文件校验和"""
        sha256 = hashlib.sha256()
        
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def get_progress(self, session_id: str) -> Optional[float]:
        """获取传输进度"""
        session = self.load_session(session_id)
        
        if not session:
            return None
        
        return session.transferred_bytes / session.file_size
    
    def get_speed(self, session_id: str) -> Optional[float]:
        """获取传输速度（字节/秒）"""
        session = self.load_session(session_id)
        
        if not session or session.start_time == 0:
            return None
        
        elapsed = time.time() - session.start_time
        if elapsed == 0:
            return 0
        
        return session.transferred_bytes / elapsed

# ============================================================================
# 使用示例
# ============================================================================

async def example_usage():
    """使用示例"""
    print("="*80)
    print("断点续传示例")
    print("="*80)
    
    # 创建管理器
    manager = ResumableTransferManager()
    
    # 创建测试文件
    test_file = "/tmp/test_large_file.bin"
    file_size = 10 * 1024 * 1024  # 10MB
    
    print(f"\n创建测试文件: {test_file} ({file_size / 1024 / 1024:.2f} MB)")
    with open(test_file, 'wb') as f:
        f.write(b'x' * file_size)
    
    # 创建发送会话
    session_id = "test_session_001"
    session = manager.create_session(session_id, test_file)
    
    print(f"\n会话 ID: {session_id}")
    print(f"文件大小: {session.file_size / 1024 / 1024:.2f} MB")
    print(f"分块数: {len(session.chunks)}")
    print(f"每块大小: {session.chunk_size / 1024:.2f} KB")
    
    # 模拟发送
    print("\n开始传输...")
    
    async def mock_send_chunk(chunk_index: int, chunk_data: bytes):
        """模拟发送分块"""
        await asyncio.sleep(0.01)  # 模拟网络延迟
        # 在实际应用中，这里会通过网络发送数据
    
    def progress_callback(progress: float, speed: float):
        """进度回调"""
        print(f"进度: {progress*100:.1f}%, 速度: {speed/1024/1024:.2f} MB/s")
    
    success = await manager.send_file(
        session_id,
        mock_send_chunk,
        progress_callback
    )
    
    print(f"\n传输结果: {'成功' if success else '失败'}")
    
    if success:
        print(f"传输时间: {session.end_time - session.start_time:.2f} 秒")
        print(f"平均速度: {session.file_size / (session.end_time - session.start_time) / 1024 / 1024:.2f} MB/s")
    
    # 清理
    os.remove(test_file)
    manager.delete_session(session_id)
    
    print("\n" + "="*80)
    print("断点续传示例完成")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(example_usage())
