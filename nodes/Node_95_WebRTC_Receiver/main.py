"""
Node_95: WebRTC 接收器 - 完整实现版本

功能：
1. 接收来自 Android 端的 WebRTC 视频流
2. 完整的 WebRTC 信令处理（Offer/Answer/ICE）
3. H.264 视频解码
4. 提供 HTTP API 供 Node_90 (VLM) 调用
5. 支持实时截图和 MJPEG 流

依赖：
- aiortc: WebRTC 实现
- av: 视频解码
- opencv-python: 图像处理

作者: Manus AI
版本: 2.0 (完整实现)
日期: 2026-01-24
"""

import asyncio
import logging
import base64
import io
import time
from datetime import datetime
from typing import Optional, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn
from PIL import Image
import numpy as np

# WebRTC 相关
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, VideoStreamTrack
from aiortc.contrib.media import MediaRecorder
import av

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Node_95: WebRTC Receiver", version="2.0")

# ============================================================================
# 全局状态
# ============================================================================

class WebRTCState:
    """WebRTC 状态管理"""
    
    def __init__(self):
        # WebRTC 连接
        self.peer_connections: Dict[str, RTCPeerConnection] = {}
        
        # 最新帧
        self.latest_frames: Dict[str, np.ndarray] = {}
        self.frame_timestamps: Dict[str, datetime] = {}
        
        # WebSocket 连接
        self.signaling_connections: Dict[str, WebSocket] = {}
        
        # 统计
        self.stats = {
            "total_connections": 0,
            "active_connections": 0,
            "total_frames_received": 0,
            "total_bytes_received": 0
        }
    
    def update_frame(self, device_id: str, frame: np.ndarray):
        """更新最新帧"""
        self.latest_frames[device_id] = frame
        self.frame_timestamps[device_id] = datetime.now()
        self.stats["total_frames_received"] += 1
    
    def get_latest_frame(self, device_id: str) -> Optional[np.ndarray]:
        """获取最新帧"""
        return self.latest_frames.get(device_id)
    
    def is_receiving(self, device_id: str) -> bool:
        """是否正在接收"""
        if device_id not in self.frame_timestamps:
            return False
        
        # 如果超过 5 秒没有新帧，认为已停止
        last_time = self.frame_timestamps[device_id]
        return (datetime.now() - last_time).total_seconds() < 5.0

state = WebRTCState()

# ============================================================================
# API 模型
# ============================================================================

class SignalingMessage(BaseModel):
    """信令消息"""
    type: str  # "offer", "answer", "ice_candidate"
    sdp: Optional[str] = None
    candidate: Optional[str] = None
    sdpMid: Optional[str] = None
    sdpMLineIndex: Optional[int] = None

class FrameRequest(BaseModel):
    """帧请求"""
    device_id: str
    format: str = "jpeg"  # "jpeg", "png", "base64"

# ============================================================================
# 视频帧处理
# ============================================================================

class FrameReceiver:
    """视频帧接收器"""
    
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.frame_count = 0
    
    async def on_track(self, track: VideoStreamTrack):
        """处理视频轨道"""
        logger.info(f"[{self.device_id}] Received video track: {track.kind}")
        
        try:
            while True:
                # 接收视频帧
                frame = await track.recv()
                
                # 转换为 numpy 数组
                img = frame.to_ndarray(format="bgr24")
                
                # 更新状态
                state.update_frame(self.device_id, img)
                
                self.frame_count += 1
                if self.frame_count % 30 == 0:  # 每 30 帧打印一次
                    logger.debug(f"[{self.device_id}] Received {self.frame_count} frames")
        
        except Exception as e:
            logger.error(f"[{self.device_id}] Error receiving frames: {e}")

# ============================================================================
# WebRTC 信令处理
# ============================================================================

@app.websocket("/signaling/{device_id}")
async def websocket_signaling(websocket: WebSocket, device_id: str):
    """
    WebRTC 信令 WebSocket 端点
    处理 Offer/Answer/ICE Candidate 交换
    """
    await websocket.accept()
    state.signaling_connections[device_id] = websocket
    state.stats["total_connections"] += 1
    state.stats["active_connections"] += 1
    
    logger.info(f"[{device_id}] Signaling connection established")
    
    try:
        while True:
            # 接收信令消息
            data = await websocket.receive_json()
            logger.info(f"[{device_id}] Received signaling message: {data.get('type')}")
            
            # 处理信令消息
            await handle_signaling_message(device_id, websocket, data)
    
    except WebSocketDisconnect:
        logger.info(f"[{device_id}] Signaling connection closed")
    except Exception as e:
        logger.error(f"[{device_id}] Signaling error: {e}")
    finally:
        # 清理连接
        if device_id in state.signaling_connections:
            del state.signaling_connections[device_id]
        
        if device_id in state.peer_connections:
            await state.peer_connections[device_id].close()
            del state.peer_connections[device_id]
        
        state.stats["active_connections"] -= 1

async def handle_signaling_message(device_id: str, websocket: WebSocket, message: dict):
    """处理信令消息"""
    msg_type = message.get("type")
    
    try:
        if msg_type == "offer":
            # 处理 Offer
            await handle_offer(device_id, websocket, message)
        
        elif msg_type == "ice_candidate":
            # 处理 ICE Candidate
            await handle_ice_candidate(device_id, message)
        
        else:
            logger.warning(f"[{device_id}] Unknown signaling message type: {msg_type}")
    
    except Exception as e:
        logger.error(f"[{device_id}] Error handling signaling message: {e}")
        await websocket.send_json({
            "type": "error",
            "error": str(e)
        })

async def handle_offer(device_id: str, websocket: WebSocket, message: dict):
    """处理 Offer 并创建 Answer"""
    sdp = message.get("sdp")
    if not sdp:
        raise ValueError("Missing SDP in offer")
    
    logger.info(f"[{device_id}] Creating peer connection")
    
    # 创建 RTCPeerConnection
    pc = RTCPeerConnection()
    state.peer_connections[device_id] = pc
    
    # 创建帧接收器
    receiver = FrameReceiver(device_id)
    
    # 监听视频轨道
    @pc.on("track")
    async def on_track(track):
        logger.info(f"[{device_id}] Track received: {track.kind}")
        if track.kind == "video":
            asyncio.create_task(receiver.on_track(track))
    
    # 监听 ICE 连接状态
    @pc.on("iceconnectionstatechange")
    async def on_ice_connection_state_change():
        logger.info(f"[{device_id}] ICE connection state: {pc.iceConnectionState}")
        
        if pc.iceConnectionState == "failed":
            await pc.close()
    
    # 监听 ICE Candidate
    @pc.on("icecandidate")
    async def on_ice_candidate(candidate):
        if candidate:
            logger.debug(f"[{device_id}] Sending ICE candidate")
            await websocket.send_json({
                "type": "ice_candidate",
                "candidate": candidate.candidate,
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex
            })
    
    # 设置远程描述（Offer）
    offer_desc = RTCSessionDescription(sdp=sdp, type="offer")
    await pc.setRemoteDescription(offer_desc)
    
    logger.info(f"[{device_id}] Remote description set (Offer)")
    
    # 创建 Answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    
    logger.info(f"[{device_id}] Answer created")
    
    # 发送 Answer
    await websocket.send_json({
        "type": "answer",
        "sdp": pc.localDescription.sdp
    })
    
    logger.info(f"[{device_id}] Answer sent")

async def handle_ice_candidate(device_id: str, message: dict):
    """处理 ICE Candidate"""
    candidate = message.get("candidate")
    sdp_mid = message.get("sdpMid")
    sdp_mline_index = message.get("sdpMLineIndex")
    
    if not candidate:
        logger.debug(f"[{device_id}] Received end-of-candidates")
        return
    
    pc = state.peer_connections.get(device_id)
    if not pc:
        logger.warning(f"[{device_id}] No peer connection for ICE candidate")
        return
    
    # 添加 ICE Candidate
    ice_candidate = RTCIceCandidate(
        candidate=candidate,
        sdpMid=sdp_mid,
        sdpMLineIndex=sdp_mline_index
    )
    
    await pc.addIceCandidate(ice_candidate)
    logger.debug(f"[{device_id}] ICE candidate added")

# ============================================================================
# HTTP API 端点
# ============================================================================

@app.get("/")
async def root():
    """根端点"""
    return {
        "service": "Node_95: WebRTC Receiver",
        "version": "2.0",
        "status": "running",
        "stats": state.stats,
        "active_devices": list(state.latest_frames.keys())
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "active_connections": state.stats["active_connections"],
        "total_frames_received": state.stats["total_frames_received"]
    }

@app.post("/get_latest_frame")
async def get_latest_frame(request: FrameRequest):
    """
    获取最新的视频帧
    供 Node_90 (VLM) 调用
    """
    device_id = request.device_id
    
    # 检查是否有帧
    frame = state.get_latest_frame(device_id)
    if frame is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"No frame available for device {device_id}"}
        )
    
    # 检查是否正在接收
    if not state.is_receiving(device_id):
        return JSONResponse(
            status_code=503,
            content={"error": f"Device {device_id} is not streaming"}
        )
    
    # 转换格式
    if request.format == "jpeg":
        # 转换为 JPEG
        img = Image.fromarray(frame)
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=90)
        img_bytes = buffered.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
    
    elif request.format == "png":
        # 转换为 PNG
        img = Image.fromarray(frame)
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
    
    elif request.format == "base64":
        # 直接返回 base64
        img = Image.fromarray(frame)
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=90)
        img_bytes = buffered.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
    
    else:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unsupported format: {request.format}"}
        )
    
    return {
        "success": True,
        "device_id": device_id,
        "timestamp": state.frame_timestamps[device_id].isoformat(),
        "format": request.format,
        "frame_data": img_base64,
        "frame_size": {
            "width": frame.shape[1],
            "height": frame.shape[0]
        }
    }

@app.get("/stream_mjpeg/{device_id}")
async def stream_mjpeg(device_id: str):
    """
    MJPEG 流端点
    供浏览器或其他客户端实时查看
    """
    async def generate():
        while True:
            frame = state.get_latest_frame(device_id)
            
            if frame is not None:
                # 转换为 JPEG
                img = Image.fromarray(frame)
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG", quality=85)
                img_bytes = buffered.getvalue()
                
                # 发送 MJPEG 帧
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + img_bytes + b'\r\n')
            
            await asyncio.sleep(0.033)  # ~30 FPS
    
    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/devices")
async def list_devices():
    """列出所有连接的设备"""
    devices = []
    
    for device_id in state.latest_frames.keys():
        devices.append({
            "device_id": device_id,
            "is_receiving": state.is_receiving(device_id),
            "last_frame_time": state.frame_timestamps.get(device_id, datetime.now()).isoformat(),
            "has_peer_connection": device_id in state.peer_connections
        })
    
    return {
        "devices": devices,
        "total": len(devices)
    }

# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    logger.info("="*80)
    logger.info("Node_95: WebRTC Receiver v2.0 (完整实现)")
    logger.info("="*80)
    logger.info("Starting on port 8095")
    logger.info("WebRTC signaling: ws://localhost:8095/signaling/{device_id}")
    logger.info("HTTP API: http://localhost:8095")
    logger.info("="*80)
    
    uvicorn.run(app, host="0.0.0.0", port=8095, log_level="info")
