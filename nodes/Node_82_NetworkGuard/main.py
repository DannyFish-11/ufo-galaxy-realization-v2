"""
Node 82: Network Guard - 网络监控与防护
实时监控网络状态、流量分析、安全防护

功能：
1. 网络状态监控 - 实时检测网络连接状态
2. 流量分析 - 监控网络流量和带宽使用
3. 端口扫描 - 检测开放端口和服务
4. 防火墙管理 - 管理防火墙规则
5. VPN 状态 - 监控 VPN 连接（Tailscale 等）

优势：
- 实时监控
- 安全防护
- 流量分析
- 异常检测
"""

import os
import platform
import socket
import psutil
import subprocess
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "82")
NODE_NAME = os.getenv("NODE_NAME", "NetworkGuard")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class NetworkInterface(BaseModel):
    name: str
    addresses: List[str]
    mac_address: Optional[str] = None
    is_up: bool
    speed: Optional[int] = None  # Mbps

class NetworkStats(BaseModel):
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    errors_in: int
    errors_out: int
    drops_in: int
    drops_out: int

class ConnectionInfo(BaseModel):
    local_address: str
    local_port: int
    remote_address: Optional[str] = None
    remote_port: Optional[int] = None
    status: str
    pid: Optional[int] = None

class PortScanResult(BaseModel):
    port: int
    is_open: bool
    service: Optional[str] = None

# =============================================================================
# Network Guard Service
# =============================================================================

class NetworkGuardService:
    """网络监控服务"""
    
    def __init__(self):
        self.system = platform.system()
    
    def get_interfaces(self) -> List[NetworkInterface]:
        """获取网络接口"""
        interfaces = []
        
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            
            for name, addr_list in addrs.items():
                addresses = []
                mac_address = None
                
                for addr in addr_list:
                    if addr.family == socket.AF_INET:
                        addresses.append(addr.address)
                    elif addr.family == psutil.AF_LINK:
                        mac_address = addr.address
                
                stat = stats.get(name)
                
                interfaces.append(NetworkInterface(
                    name=name,
                    addresses=addresses,
                    mac_address=mac_address,
                    is_up=stat.isup if stat else False,
                    speed=stat.speed if stat else None
                ))
        
        except Exception as e:
            logger.error(f"Failed to get interfaces: {e}")
        
        return interfaces
    
    def get_network_stats(self) -> NetworkStats:
        """获取网络统计"""
        try:
            stats = psutil.net_io_counters()
            
            return NetworkStats(
                bytes_sent=stats.bytes_sent,
                bytes_recv=stats.bytes_recv,
                packets_sent=stats.packets_sent,
                packets_recv=stats.packets_recv,
                errors_in=stats.errin,
                errors_out=stats.errout,
                drops_in=stats.dropin,
                drops_out=stats.dropout
            )
        
        except Exception as e:
            logger.error(f"Failed to get network stats: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def get_connections(self, kind: str = "inet") -> List[ConnectionInfo]:
        """获取网络连接"""
        connections = []
        
        try:
            conns = psutil.net_connections(kind=kind)
            
            for conn in conns[:100]:  # 限制返回数量
                connections.append(ConnectionInfo(
                    local_address=conn.laddr.ip if conn.laddr else "",
                    local_port=conn.laddr.port if conn.laddr else 0,
                    remote_address=conn.raddr.ip if conn.raddr else None,
                    remote_port=conn.raddr.port if conn.raddr else None,
                    status=conn.status,
                    pid=conn.pid
                ))
        
        except Exception as e:
            logger.error(f"Failed to get connections: {e}")
        
        return connections
    
    def scan_port(self, host: str, port: int, timeout: float = 1.0) -> bool:
        """扫描单个端口"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except OSError:
            return False
    
    def scan_ports(self, host: str, ports: List[int]) -> List[PortScanResult]:
        """扫描多个端口"""
        results = []
        
        # 常见服务端口映射
        services = {
            21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
            53: "DNS", 80: "HTTP", 110: "POP3", 143: "IMAP",
            443: "HTTPS", 3306: "MySQL", 5432: "PostgreSQL",
            6379: "Redis", 8000: "HTTP-Alt", 8080: "HTTP-Proxy",
            8081: "HTTP-Alt", 27017: "MongoDB"
        }
        
        for port in ports:
            is_open = self.scan_port(host, port)
            results.append(PortScanResult(
                port=port,
                is_open=is_open,
                service=services.get(port) if is_open else None
            ))
        
        return results
    
    def check_internet(self) -> bool:
        """检查互联网连接"""
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False
    
    def get_public_ip(self) -> Optional[str]:
        """获取公网 IP"""
        try:
            import httpx
            response = httpx.get("https://api.ipify.org", timeout=5)
            return response.text
        except Exception:
            return None
    
    def get_tailscale_status(self) -> Dict[str, Any]:
        """获取 Tailscale 状态"""
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                import json
                return json.loads(result.stdout)
            else:
                return {"error": "Tailscale not running or not installed"}
        
        except FileNotFoundError:
            return {"error": "Tailscale not installed"}
        except Exception as e:
            return {"error": str(e)}
    
    def get_firewall_status(self) -> Dict[str, Any]:
        """获取防火墙状态"""
        try:
            if self.system == "Linux":
                # 检查 ufw
                result = subprocess.run(
                    ["sudo", "ufw", "status"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                return {
                    "type": "ufw",
                    "status": "active" if "Status: active" in result.stdout else "inactive",
                    "output": result.stdout
                }
            
            elif self.system == "Windows":
                # 检查 Windows Firewall
                result = subprocess.run(
                    ["netsh", "advfirewall", "show", "allprofiles"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                return {
                    "type": "windows_firewall",
                    "output": result.stdout
                }
            
            else:
                return {"error": f"Unsupported system: {self.system}"}
        
        except Exception as e:
            return {"error": str(e)}
    
    def get_bandwidth_usage(self) -> Dict[str, Any]:
        """获取带宽使用情况"""
        try:
            import time
            
            # 第一次采样
            stats1 = psutil.net_io_counters()
            time.sleep(1)
            # 第二次采样
            stats2 = psutil.net_io_counters()
            
            # 计算速率（字节/秒）
            upload_speed = stats2.bytes_sent - stats1.bytes_sent
            download_speed = stats2.bytes_recv - stats1.bytes_recv
            
            return {
                "upload_speed_bps": upload_speed,
                "download_speed_bps": download_speed,
                "upload_speed_mbps": round(upload_speed / 1024 / 1024, 2),
                "download_speed_mbps": round(download_speed / 1024 / 1024, 2),
                "total_sent_gb": round(stats2.bytes_sent / 1024 / 1024 / 1024, 2),
                "total_recv_gb": round(stats2.bytes_recv / 1024 / 1024 / 1024, 2)
            }
        
        except Exception as e:
            logger.error(f"Failed to get bandwidth usage: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# =============================================================================
# FastAPI Application
# =============================================================================

guard = NetworkGuardService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Node 82: Network Guard")
    yield
    logger.info("Node 82 shutdown complete")

app = FastAPI(
    title="Node 82: Network Guard",
    description="网络监控与防护 - 实时监控、流量分析、安全防护",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    return {
        "service": "Node 82: Network Guard",
        "status": "running",
        "system": guard.system,
        "features": [
            "Network monitoring",
            "Traffic analysis",
            "Port scanning",
            "Firewall management",
            "VPN status"
        ]
    }

@app.get("/health")
async def health():
    internet = guard.check_internet()
    
    return {
        "status": "healthy",
        "internet_connected": internet,
        "system": guard.system,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/interfaces")
async def get_interfaces():
    """获取网络接口"""
    interfaces = guard.get_interfaces()
    return {
        "interfaces": [i.dict() for i in interfaces],
        "count": len(interfaces)
    }

@app.get("/stats")
async def get_stats():
    """获取网络统计"""
    stats = guard.get_network_stats()
    return stats.dict()

@app.get("/connections")
async def get_connections(kind: str = "inet"):
    """获取网络连接"""
    connections = guard.get_connections(kind)
    return {
        "connections": [c.dict() for c in connections],
        "count": len(connections)
    }

@app.post("/scan")
async def scan_ports(host: str, ports: List[int]):
    """扫描端口"""
    if len(ports) > 100:
        raise HTTPException(status_code=400, detail="Too many ports (max 100)")
    
    results = guard.scan_ports(host, ports)
    open_ports = [r for r in results if r.is_open]
    
    return {
        "host": host,
        "results": [r.dict() for r in results],
        "open_ports": [r.dict() for r in open_ports],
        "total_scanned": len(ports),
        "total_open": len(open_ports)
    }

@app.get("/internet")
async def check_internet():
    """检查互联网连接"""
    connected = guard.check_internet()
    public_ip = guard.get_public_ip() if connected else None
    
    return {
        "connected": connected,
        "public_ip": public_ip,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/bandwidth")
async def get_bandwidth():
    """获取带宽使用"""
    usage = guard.get_bandwidth_usage()
    return usage

@app.get("/tailscale")
async def get_tailscale():
    """获取 Tailscale 状态"""
    status = guard.get_tailscale_status()
    return status

@app.get("/firewall")
async def get_firewall():
    """获取防火墙状态"""
    status = guard.get_firewall_status()
    return status

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082)
