#!/usr/bin/env python3
"""
UFO Galaxy V2 - 设备注册脚本
快速将设备注册到 Galaxy 系统
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime

def get_local_ip():
    """获取本机 IP 地址"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_device_type():
    """检测设备类型"""
    import platform
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "macos"
    elif system == "linux":
        return "linux"
    else:
        return "other"

def get_device_id():
    """生成设备 ID"""
    import platform
    import hashlib
    hostname = platform.node()
    device_type = get_device_type()
    hash_input = f"{device_type}-{hostname}-{datetime.now().strftime('%Y%m%d')}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:8]
    return f"{device_type}_{hostname}_{hash_value}"

def register_device(gateway_url, device_id, device_name, device_type, aliases, capabilities, ip_address):
    """注册设备到 Gateway"""
    
    url = f"{gateway_url}/api/devices/register"
    
    payload = {
        "device_id": device_id,
        "device_name": device_name,
        "device_type": device_type,
        "aliases": aliases,
        "capabilities": capabilities,
        "ip_address": ip_address
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        print(f"❌ 无法连接到 Gateway: {gateway_url}")
        print("   请确保 Gateway 服务正在运行")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"❌ 注册失败: {e}")
        return None
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="UFO Galaxy 设备注册工具")
    
    parser.add_argument("--gateway", default="http://localhost:8080", 
                        help="Gateway 地址 (默认: http://localhost:8080)")
    parser.add_argument("--device-id", default=None, help="设备 ID (默认自动生成)")
    parser.add_argument("--device-name", default=None, help="设备名称")
    parser.add_argument("--device-type", default=None, 
                        choices=["windows", "linux", "macos", "android", "other"],
                        help="设备类型")
    parser.add_argument("--aliases", default="", help="设备别名 (逗号分隔)")
    parser.add_argument("--capabilities", default="", help="设备能力 (逗号分隔)")
    parser.add_argument("--ip", default=None, help="IP 地址")
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("  UFO Galaxy 设备注册工具")
    print("=" * 50)
    print()
    
    # 自动检测或使用参数
    device_id = args.device_id or get_device_id()
    device_name = args.device_name or f"我的{get_device_type().title()}设备"
    device_type = args.device_type or get_device_type()
    ip_address = args.ip or get_local_ip()
    
    # 解析别名和能力
    aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]
    if not aliases:
        aliases = [device_type, "本地设备"]
    
    capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]
    if not capabilities:
        # 默认能力
        default_capabilities = {
            "windows": ["execute_script", "send_notification", "status_update", "desktop_automation"],
            "linux": ["execute_command", "file_transfer", "status_update"],
            "macos": ["applescript", "send_notification", "status_update"],
            "android": ["tap", "swipe", "screenshot", "input_text"],
            "other": ["status_update"]
        }
        capabilities = default_capabilities.get(device_type, ["status_update"])
    
    print(f"📡 Gateway: {args.gateway}")
    print(f"🆔 设备 ID: {device_id}")
    print(f"📛 设备名称: {device_name}")
    print(f"💻 设备类型: {device_type}")
    print(f"🌐 IP 地址: {ip_address}")
    print(f"🏷️  别名: {', '.join(aliases)}")
    print(f"⚡ 能力: {', '.join(capabilities)}")
    print()
    
    # 确认注册
    confirm = input("确认注册? (y/n): ")
    if confirm.lower() != 'y':
        print("已取消")
        return
    
    print()
    print("正在注册...")
    
    result = register_device(
        args.gateway,
        device_id,
        device_name,
        device_type,
        aliases,
        capabilities,
        ip_address
    )
    
    if result:
        print()
        print("✅ 注册成功!")
        print()
        print("设备信息:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print()
        print("现在可以通过以下方式控制设备:")
        print(f"  curl -X POST {args.gateway}/api/execute \\")
        print(f'    -H "Content-Type: application/json" \\')
        print(f'    -d \'{{"device_id": "{device_id}", "command": "status"}}\'')
    else:
        print()
        print("❌ 注册失败")
        sys.exit(1)

if __name__ == "__main__":
    main()
